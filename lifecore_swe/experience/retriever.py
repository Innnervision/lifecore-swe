"""Deterministic experience retrieval pipeline with staleness verification."""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from .context_builder import ExperienceContextBuilder
from .models import (
    ExperienceRecord,
    ExperienceRetrievalConfig,
    ExperienceRetrievalResult,
    StaleStatus,
    VerificationStatus,
)
from .ranker import ExperienceRanker
from .store import ExperienceStore


class ExperienceRetriever:
    """Retrieves, filters, validates, and formats historical verified experiences."""

    def __init__(self, store: ExperienceStore, ranker: Optional[ExperienceRanker] = None):
        self.store = store
        self.ranker = ranker or ExperienceRanker()

    def check_staleness(
        self,
        record: ExperienceRecord,
        repo_path: Path,
        current_version: str,
    ) -> Tuple[str, str]:
        """Verify whether stored experience remains valid against current repository state."""
        # 1. Version check
        version_mismatch = (
            record.repository_version
            and current_version
            and record.repository_version != current_version
        )

        # 2. File hash validation
        changed_files: List[str] = []
        missing_files: List[str] = []

        for rel_path, original_hash in record.file_hashes.items():
            full_path = repo_path / rel_path
            if not full_path.exists():
                missing_files.append(rel_path)
            else:
                current_hash = ExperienceRecord.compute_file_hash(full_path)
                if current_hash != original_hash:
                    changed_files.append(rel_path)

        if missing_files:
            return StaleStatus.CONTRADICTED.value, f"Files no longer exist: {missing_files}"

        if changed_files:
            return StaleStatus.STALE.value, f"Files modified since task verified: {changed_files}"

        if version_mismatch:
            return StaleStatus.REVALIDATED.value, f"Repo version changed ({record.repository_version} -> {current_version}), but file content matches."

        return StaleStatus.VALID.value, "File contents and versions match baseline."

    def retrieve(
        self,
        task_text: str,
        repo_path: str,
        repo_id: str,
        repo_version: str = "",
        graph_files: Optional[List[str]] = None,
        graph_symbols: Optional[List[str]] = None,
        config: Optional[ExperienceRetrievalConfig] = None,
    ) -> ExperienceRetrievalResult:
        """Execute deterministic retrieval of verified experiences."""
        start_time = time.perf_counter()
        cfg = config or ExperienceRetrievalConfig()
        r_path = Path(repo_path).resolve()

        # Step 1: Candidate retrieval from persistent store
        status_filter = None if cfg.include_failed else VerificationStatus.VERIFIED.value
        candidates = self.store.list_all(repository_id=repo_id, verification_status=status_filter)

        if cfg.include_failed:
            # Also get failed records
            failed_candidates = self.store.list_all(repository_id=repo_id, verification_status=VerificationStatus.FAILED.value)
            candidates = list({c.experience_id: c for c in (candidates + failed_candidates)}.values())

        if not candidates:
            # If no repo-specific candidates, look for cross-repository verified experiences
            candidates = self.store.list_all(verification_status=VerificationStatus.VERIFIED.value)

        candidate_count = len(candidates)

        # Step 2: Rank candidates
        g_files = graph_files or []
        g_symbols = graph_symbols or []

        ranked_tuples = self.ranker.rank(
            candidates=candidates,
            query_text=task_text,
            target_repository=repo_id,
            target_version=repo_version,
            graph_files=g_files,
            graph_symbols=g_symbols,
            min_score=cfg.min_similarity_score,
        )

        # Step 3: Cutoff to max budget
        selected_tuples = ranked_tuples[: cfg.max_experiences]
        selected_records: List[ExperienceRecord] = []
        selection_reasons: Dict[str, List[str]] = {}
        ranking_scores: Dict[str, float] = {}
        stale_statuses: Dict[str, str] = {}
        stale_details: Dict[str, str] = {}

        for rec, score, reasons in selected_tuples:
            selected_records.append(rec)
            selection_reasons[rec.experience_id] = reasons
            ranking_scores[rec.experience_id] = score

            # Step 4: Staleness detection against disk
            if cfg.stale_detection_enabled:
                stale_st, stale_desc = self.check_staleness(rec, r_path, repo_version)
                stale_statuses[rec.experience_id] = stale_st
                stale_details[rec.experience_id] = stale_desc
                rec.stale_status = stale_st
            else:
                stale_statuses[rec.experience_id] = StaleStatus.VALID.value
                stale_details[rec.experience_id] = ""

        # Step 5: Format compact context
        compact_ctx = ExperienceContextBuilder.build_context(
            experiences=selected_records,
            selection_reasons=selection_reasons,
            ranking_scores=ranking_scores,
            stale_statuses=stale_statuses,
            stale_details=stale_details,
            max_chars=cfg.max_context_chars,
        )

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return ExperienceRetrievalResult(
            query=task_text,
            candidate_count=candidate_count,
            selected_experiences=selected_records,
            selection_reasons=selection_reasons,
            ranking_scores=ranking_scores,
            stale_statuses=stale_statuses,
            stale_details=stale_details,
            compact_context=compact_ctx,
            latency_ms=latency_ms,
        )
