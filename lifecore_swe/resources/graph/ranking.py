"""Deterministic multi-attribute ranker for external software resources.

Scores and filters candidates based on:
1. Task relevance (lexical and semantic symbol matching)
2. Source authority (official documentation > package registries > public repos > forums)
3. Version compatibility (target version matching vs mismatch penalty)
4. Freshness (FRESH > AGING > UNKNOWN > STALE)
5. Provenance trust level (VERIFIED_INTERNAL > HIGH > MEDIUM > LOW > UNTRUSTED)
6. Verification lifecycle state (VERIFIED > VALIDATED > RETRIEVED > UNVERIFIED > STALE)
7. Confidence score
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..models import FreshnessStatus, ResourceVerificationStatus
from ..provenance import ProvenanceRecord, TrustLevel
from .schema import ResourceNode, ResourceNodeType


@dataclass
class ScoredResourceNode:
    """ResourceNode paired with composite relevance score and audit explanation."""
    node: ResourceNode
    score: float
    sub_scores: Dict[str, float]
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node.node_id,
            "node_type": self.node.node_type.value,
            "title": self.node.title,
            "score": round(self.score, 4),
            "sub_scores": {k: round(v, 4) for k, v in self.sub_scores.items()},
            "reasons": self.reasons,
        }


class ResourceRanker:
    """Ranks resource candidates using deterministic multi-signal scoring."""

    def __init__(
        self,
        w_relevance: float = 0.30,
        w_authority: float = 0.15,
        w_version: float = 0.15,
        w_freshness: float = 0.10,
        w_trust: float = 0.10,
        w_status: float = 0.15,
        w_confidence: float = 0.05,
    ) -> None:
        self.w_relevance = w_relevance
        self.w_authority = w_authority
        self.w_version = w_version
        self.w_freshness = w_freshness
        self.w_trust = w_trust
        self.w_status = w_status
        self.w_confidence = w_confidence

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        """Extract alphanumeric tokens of length >= 3."""
        if not text:
            return set()
        clean = text.replace("-", " ").replace(".", " ").replace("_", " ").replace("/", " ")
        tokens = set(re.findall(r"\b[a-zA-Z0-9]{3,}\b", clean.lower()))
        stop_words = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "will", "when"}
        return tokens - stop_words

    def score(
        self,
        node: ResourceNode,
        query_text: str = "",
        target_package: Optional[str] = None,
        target_version: Optional[str] = None,
        provenance: Optional[ProvenanceRecord] = None,
    ) -> ScoredResourceNode:
        """Calculate composite deterministic score in [0.0, 1.0] and generate explanation reasons."""
        reasons: List[str] = []
        sub_scores: Dict[str, float] = {}

        # 1. Task Relevance
        rel_score, rel_reason = self._compute_relevance(node, query_text, target_package)
        sub_scores["relevance"] = rel_score
        reasons.append(rel_reason)

        # 2. Source Authority
        auth_score, auth_reason = self._compute_authority(node)
        sub_scores["authority"] = auth_score
        reasons.append(auth_reason)

        # 3. Version Compatibility
        ver_score, ver_reason = self._compute_version(node, target_version)
        sub_scores["version"] = ver_score
        reasons.append(ver_reason)

        # 4. Freshness
        fresh_score, fresh_reason = self._compute_freshness(node)
        sub_scores["freshness"] = fresh_score
        reasons.append(fresh_reason)

        # 5. Provenance Trust
        trust_score, trust_reason = self._compute_trust(node, provenance)
        sub_scores["trust"] = trust_score
        reasons.append(trust_reason)

        # 6. Verification Status
        stat_score, stat_reason = self._compute_status(node)
        sub_scores["status"] = stat_score
        reasons.append(stat_reason)

        # 7. Confidence
        conf_score = max(0.0, min(1.0, float(node.confidence)))
        sub_scores["confidence"] = conf_score

        # Weighted total
        total_score = (
            self.w_relevance * rel_score
            + self.w_authority * auth_score
            + self.w_version * ver_score
            + self.w_freshness * fresh_score
            + self.w_trust * trust_score
            + self.w_status * stat_score
            + self.w_confidence * conf_score
        )

        # If rejected or contradicted, apply severe penalty
        if node.verification_status in (
            ResourceVerificationStatus.REJECTED,
            ResourceVerificationStatus.CONTRADICTED,
        ):
            total_score = 0.0
            reasons.append(f"Penalty applied: {node.verification_status.value} resets score to 0.0")

        return ScoredResourceNode(
            node=node,
            score=max(0.0, min(1.0, total_score)),
            sub_scores=sub_scores,
            reasons=reasons,
        )

    def _compute_relevance(
        self,
        node: ResourceNode,
        query_text: str,
        target_package: Optional[str],
    ) -> Tuple[float, str]:
        if not query_text and not target_package:
            return 0.5, "Relevance: Neutral baseline (no query specified)"

        q_tokens = self._tokenize(query_text)
        if target_package:
            q_tokens.add(target_package.lower())

        if not q_tokens:
            return 0.5, "Relevance: Neutral baseline (empty query tokens)"

        # Target package exact match
        if target_package and node.package_name and node.package_name.lower() == target_package.lower():
            return 1.0, f"Relevance: Exact package match on '{target_package}'"

        # Collect node text tokens
        node_tokens = self._tokenize(node.title)
        node_tokens.update(self._tokenize(node.description))
        if node.package_name:
            node_tokens.add(node.package_name.lower())
        if node.repository:
            node_tokens.update(self._tokenize(node.repository))

        # Check symbols in metadata
        symbols = node.metadata.get("symbols", [])
        for s in symbols:
            if isinstance(s, dict) and "name" in s:
                node_tokens.update(self._tokenize(s["name"]))
            elif isinstance(s, str):
                node_tokens.update(self._tokenize(s))

        overlap = q_tokens.intersection(node_tokens)
        if not overlap:
            return 0.0, "Relevance: Zero query token overlap"

        overlap_ratio = len(overlap) / len(q_tokens)
        score = min(1.0, 0.4 + 0.6 * overlap_ratio)
        return score, f"Relevance: Overlap {len(overlap)}/{len(q_tokens)} tokens ({sorted(overlap)[:3]})"

    def _compute_authority(self, node: ResourceNode) -> Tuple[float, str]:
        s = (node.source or "").lower()
        if any(auth in s for auth in ("python-docs", "docs.python.org", "official", "psf")):
            return 1.0, f"Authority: Official documentation source ('{s}')"
        if any(pkg in s for pkg in ("pypi", "pythonhosted", "npm")):
            return 0.85, f"Authority: Package registry source ('{s}')"
        if any(repo in s for repo in ("github", "gitlab")):
            return 0.75, f"Authority: Public repository host ('{s}')"
        if any(comm in s for comm in ("cookbook", "stackoverflow", "community")):
            return 0.50, f"Authority: Community reference ('{s}')"
        return 0.30, f"Authority: Unclassified source ('{s}')"

    def _compute_version(self, node: ResourceNode, target_version: Optional[str]) -> Tuple[float, str]:
        if not target_version:
            if node.version:
                return 0.8, f"Version: Declared version '{node.version}' (no target constraint)"
            return 0.6, "Version: Unversioned entity (no target constraint)"

        if not node.version:
            return 0.5, f"Version: Unversioned entity (target '{target_version}')"

        n_ver = node.version.strip().lower()
        t_ver = target_version.strip().lower()

        if n_ver == t_ver:
            return 1.0, f"Version: Exact version match ('{n_ver}')"

        # Compare major.minor prefix
        n_prefix = ".".join(n_ver.split(".")[:2])
        t_prefix = ".".join(t_ver.split(".")[:2])
        if n_prefix == t_prefix:
            return 0.85, f"Version: Compatible minor version ('{n_ver}' matches '{t_ver}')"

        return 0.1, f"Version: Version mismatch ('{n_ver}' vs target '{t_ver}')"

    def _compute_freshness(self, node: ResourceNode) -> Tuple[float, str]:
        if node.freshness == FreshnessStatus.FRESH:
            return 1.0, "Freshness: FRESH"
        elif node.freshness == FreshnessStatus.AGING:
            return 0.6, "Freshness: AGING"
        elif node.freshness == FreshnessStatus.UNKNOWN:
            return 0.4, "Freshness: UNKNOWN"
        elif node.freshness == FreshnessStatus.STALE:
            return 0.1, "Freshness: STALE"
        return 0.4, f"Freshness: {node.freshness.value}"

    def _compute_trust(self, node: ResourceNode, provenance: Optional[ProvenanceRecord]) -> Tuple[float, str]:
        if provenance is not None:
            t = provenance.trust_level
            if t == TrustLevel.VERIFIED_INTERNAL:
                return 1.0, "Trust: VERIFIED_INTERNAL"
            elif t == TrustLevel.HIGH:
                return 0.9, "Trust: HIGH"
            elif t == TrustLevel.MEDIUM:
                return 0.7, "Trust: MEDIUM"
            elif t == TrustLevel.LOW:
                return 0.4, "Trust: LOW"
            elif t == TrustLevel.UNTRUSTED:
                return 0.0, "Trust: UNTRUSTED"
        return 0.4, "Trust: Default baseline"

    def _compute_status(self, node: ResourceNode) -> Tuple[float, str]:
        s = node.verification_status
        if s == ResourceVerificationStatus.VERIFIED:
            return 1.0, "Status: VERIFIED (Ground-truth verified)"
        elif s == ResourceVerificationStatus.VALIDATED:
            return 0.85, "Status: VALIDATED (Integrity & schema checked)"
        elif s == ResourceVerificationStatus.RETRIEVED:
            return 0.50, "Status: RETRIEVED (Unverified external content)"
        elif s == ResourceVerificationStatus.UNVERIFIED:
            return 0.30, "Status: UNVERIFIED"
        elif s == ResourceVerificationStatus.STALE:
            return 0.20, "Status: STALE"
        elif s == ResourceVerificationStatus.CONTRADICTED:
            return 0.0, "Status: CONTRADICTED"
        elif s == ResourceVerificationStatus.REJECTED:
            return 0.0, "Status: REJECTED"
        return 0.30, f"Status: {s.value}"
