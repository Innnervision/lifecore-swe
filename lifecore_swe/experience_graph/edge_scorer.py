"""Deterministic Edge Scorer for Experience-Conditioned Graph with Negative Experience Learning (M4)."""

import hashlib
import math
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..codegraph.schema import Edge, Node
from .models import (
    AttributionStrength,
    ExperienceEdgeStats,
    ExperienceGraphConfig,
    FreshnessStatus,
    NegativeEdgeStats,
    ScoredEdge,
)


class DeterministicEdgeScorer:
    """Computes deterministic edge scores combining static structure, positive boosts, and negative penalties."""

    def __init__(self, config: Optional[ExperienceGraphConfig] = None):
        self.config = config or ExperienceGraphConfig()

    def get_base_score(self, edge_type: str) -> float:
        """Return static structural score by edge relationship type."""
        t = edge_type.upper()
        if t == "CALLS":
            return self.config.base_weight_calls
        elif t == "TESTS":
            return self.config.base_weight_tests
        elif t == "IMPORTS":
            return self.config.base_weight_imports
        elif t == "DEFINES":
            return self.config.base_weight_defines
        return self.config.base_weight_default

    def compute_task_relevance(
        self,
        task_text: str,
        task_category: str,
        task_tokens: Set[str],
        target_symbols: List[str],
        target_files: List[str],
        task_categories: Dict[str, int],
    ) -> float:
        """Compute task ↔ historical experience relevance factor in [0.25, 1.0]."""
        # 1. Category relevance
        if task_category and task_category in task_categories:
            cat_score = 1.0
        elif not task_category:
            cat_score = 0.5
        else:
            cat_score = 0.25

        # 2. Symbol relevance
        sym_score = 0.25
        for sym in target_symbols:
            sym_clean = sym.lower()
            if any(tok in sym_clean or sym_clean in tok for tok in task_tokens):
                sym_score = 1.0
                break

        # 3. File relevance
        file_score = 0.25
        for fpath in target_files:
            fname = Path(fpath).name.lower()
            if fname in task_text.lower() or any(tok in fname for tok in task_tokens):
                file_score = 1.0
                break

        composite = 0.40 * cat_score + 0.35 * sym_score + 0.25 * file_score
        return round(composite, 3)

    def verify_freshness(
        self,
        file_hashes: Dict[str, str],
        repository_versions: List[str],
        repo_path: Optional[Path] = None,
        current_repo_version: str = "",
    ) -> Tuple[FreshnessStatus, float]:
        """Check live filesystem to detect VALID, STALE, CONTRADICTED, or REVALIDATED states."""
        if not repo_path or not file_hashes:
            return FreshnessStatus.VALID, 1.0

        for fpath, recorded_hash in file_hashes.items():
            full_path = repo_path / fpath
            if not full_path.exists():
                return FreshnessStatus.CONTRADICTED, self.config.contradicted_freshness_factor

            current_hash = self._compute_file_hash(full_path)
            if current_hash != recorded_hash:
                return FreshnessStatus.STALE, self.config.stale_freshness_factor

        if current_repo_version and repository_versions:
            if current_repo_version not in repository_versions:
                return FreshnessStatus.REVALIDATED, self.config.revalidated_freshness_factor

        return FreshnessStatus.VALID, 1.0

    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        """Compute SHA-256 hash prefix."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()[:16]

    def score_edge(
        self,
        edge_id: str,
        source: str,
        target: str,
        edge_type: str,
        task_text: str,
        task_category: str = "",
        task_tokens: Optional[Set[str]] = None,
        stats: Optional[ExperienceEdgeStats] = None,
        neg_stats: Optional[NegativeEdgeStats] = None,
        repo_path: Optional[Path] = None,
        current_repo_version: str = "",
        source_symbol: str = "",
        target_symbol: str = "",
    ) -> ScoredEdge:
        """Deterministic edge score calculation: S_final = max(floor, S_base + Delta_pos - Delta_neg)."""
        base_score = self.get_base_score(edge_type)
        tokens = task_tokens or set(re.findall(r"\b[A-Za-z0-9_]{3,}\b", task_text.lower()))

        # =========================================================================
        # 1. Positive Experience Boost (Delta_pos)
        # =========================================================================
        delta_pos = 0.0
        pos_reason = ""
        pos_freshness_status = FreshnessStatus.VALID.value
        pos_freshness_factor = 1.0
        pos_task_rel = 0.0

        if stats and stats.verified_success_count > 0:
            freq_factor = stats.verified_success_count / (1.0 + stats.verified_success_count)
            pos_task_rel = self.compute_task_relevance(
                task_text=task_text,
                task_category=task_category,
                task_tokens=tokens,
                target_symbols=stats.target_symbols,
                target_files=stats.target_files,
                task_categories=stats.task_categories,
            )
            f_status, pos_freshness_factor = self.verify_freshness(
                file_hashes=stats.file_hashes,
                repository_versions=stats.repository_versions,
                repo_path=repo_path,
                current_repo_version=current_repo_version,
            )
            pos_freshness_status = f_status.value
            dt = max(0.0, time.time() - stats.last_success_timestamp) if stats.last_success_timestamp > 0 else 0.0
            recency_factor = max(0.70, math.exp(-dt / self.config.recency_tau_seconds))
            conf_factor = max(0.5, min(1.0, stats.confidence))

            delta_pos = (
                self.config.alpha_experience
                * freq_factor
                * pos_task_rel
                * pos_freshness_factor
                * recency_factor
                * conf_factor
            )
            pos_reason = (
                f"Verified successes: {stats.verified_success_count}, Task relevance: {pos_task_rel:.2f}, "
                f"Freshness: {pos_freshness_status}, Boost: +{delta_pos:.2f}"
            )

        # =========================================================================
        # 2. Negative Experience Penalty (Delta_neg)
        # =========================================================================
        delta_neg = 0.0
        neg_reason = ""
        attrib_strength = AttributionStrength.NONE.value

        if self.config.enable_negative_penalties and neg_stats:
            attrib_strength = neg_stats.max_attribution_strength

            # Attribution Factor (Section 4 & 7)
            if self.config.attribution_filtering_enabled:
                if attrib_strength == AttributionStrength.VERIFIED.value:
                    attrib_factor = 1.0
                elif attrib_strength == AttributionStrength.STRONG.value:
                    attrib_factor = 0.80
                else:
                    attrib_factor = 0.0  # WEAK / MODERATE / NONE receive NO penalty
            else:
                # Ablation: attribution filtering disabled
                if attrib_strength == AttributionStrength.VERIFIED.value:
                    attrib_factor = 1.0
                elif attrib_strength == AttributionStrength.STRONG.value:
                    attrib_factor = 0.80
                elif attrib_strength == AttributionStrength.MODERATE.value:
                    attrib_factor = 0.50
                elif attrib_strength == AttributionStrength.WEAK.value:
                    attrib_factor = 0.25
                else:
                    attrib_factor = 0.0

            # Count of failures to consider
            fail_count = (
                neg_stats.strongly_attributed_failures
                if self.config.attribution_filtering_enabled
                else neg_stats.negative_event_count
            )

            if fail_count > 0 and attrib_factor > 0.0:
                neg_freq_factor = fail_count / (1.0 + fail_count)

                # Task relevance of the failure
                neg_task_rel = self.compute_task_relevance(
                    task_text=task_text,
                    task_category=task_category,
                    task_tokens=tokens,
                    target_symbols=neg_stats.target_symbols,
                    target_files=neg_stats.target_files,
                    task_categories=neg_stats.failure_types,
                )

                # Freshness factor for failure (if code changed, penalty decays)
                _, neg_freshness_factor = self.verify_freshness(
                    file_hashes=neg_stats.file_hashes,
                    repository_versions=neg_stats.repository_versions,
                    repo_path=repo_path,
                    current_repo_version=current_repo_version,
                )

                # Recency decay for negative experience
                dt_neg = max(0.0, time.time() - neg_stats.last_failure_timestamp) if neg_stats.last_failure_timestamp > 0 else 0.0
                recency_neg = max(0.60, math.exp(-dt_neg / self.config.recency_tau_negative_seconds))
                conf_neg = max(0.5, min(1.0, neg_stats.confidence))

                delta_neg = (
                    self.config.beta_negative
                    * neg_freq_factor
                    * attrib_factor
                    * neg_task_rel
                    * neg_freshness_factor
                    * recency_neg
                    * conf_neg
                )
                neg_reason = (
                    f"{fail_count} attributed failure(s) (Attribution: {attrib_strength}, "
                    f"Task relevance: {neg_task_rel:.2f}, Penalty: -{delta_neg:.2f})"
                )

        # =========================================================================
        # 3. Final Aggregation & Floor Protection (Section 8 & 9)
        # =========================================================================
        raw_final = base_score + delta_pos - delta_neg
        final_score = max(self.config.score_floor, round(raw_final, 3))
        net_exp = round(delta_pos - delta_neg, 3)

        # Build composite reason
        reasons = []
        if delta_pos > 0:
            reasons.append(pos_reason)
        if delta_neg > 0:
            reasons.append(neg_reason)
        if not reasons:
            reasons.append(f"Base structural edge ({edge_type}); no prior verified positive or negative experience.")

        composite_reason = "; ".join(reasons)

        return ScoredEdge(
            edge_id=edge_id,
            source=source,
            target=target,
            edge_type=edge_type,
            source_symbol=source_symbol,
            target_symbol=target_symbol,
            base_score=base_score,
            experience_score=round(delta_pos, 3),
            negative_score=round(delta_neg, 3),
            net_experience_score=net_exp,
            task_relevance=pos_task_rel,
            freshness_factor=pos_freshness_factor,
            final_score=final_score,
            contributing_experiences=stats.source_experiences if stats else [],
            contributing_negative_experiences=neg_stats.source_negative_experiences if neg_stats else [],
            selection_reason=composite_reason,
            negative_reason=neg_reason,
            attribution_strength=attrib_strength,
            freshness_status=pos_freshness_status,
        )
