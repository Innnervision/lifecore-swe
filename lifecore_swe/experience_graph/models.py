"""Data structures for Experience-Conditioned Code Graph with Negative Experience Learning (M4)."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib
import time


class FreshnessStatus(str, Enum):
    """Freshness verification of edge experience against live repository."""
    VALID = "VALID"
    STALE = "STALE"
    CONTRADICTED = "CONTRADICTED"
    REVALIDATED = "REVALIDATED"


class FailureType(str, Enum):
    """Failure taxonomy for software engineering agent trajectories (M4)."""
    NAVIGATION_FAILURE = "NAVIGATION_FAILURE"
    LOCALIZATION_FAILURE = "LOCALIZATION_FAILURE"
    HYPOTHESIS_FAILURE = "HYPOTHESIS_FAILURE"
    PATCH_FAILURE = "PATCH_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    STALE_INFORMATION = "STALE_INFORMATION"
    TOOL_FAILURE = "TOOL_FAILURE"
    BUDGET_EXHAUSTION = "BUDGET_EXHAUSTION"
    OTHER = "OTHER"


class AttributionStrength(str, Enum):
    """Attribution strength for linking a task failure to a specific graph transition (M4)."""
    NONE = "NONE"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    VERIFIED = "VERIFIED"


@dataclass
class NegativeExperienceRecord:
    """Structured record of a verified or attributed failure trajectory."""
    experience_id: str
    task_id: str
    repository_id: str
    repository_version: str
    task_category: str
    failure_type: str = FailureType.OTHER.value
    failed_hypothesis: str = ""
    failed_action: str = ""
    failed_transition: Optional[str] = None
    source_node: str = ""
    target_node: str = ""
    edge_type: str = ""
    failure_reason: str = ""
    failed_test: str = ""
    expected_behavior: str = ""
    observed_behavior: str = ""
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)
    provenance: Dict[str, Any] = field(default_factory=dict)
    attribution_strength: str = AttributionStrength.NONE.value
    attribution_reason: str = ""
    stale_status: str = FreshnessStatus.VALID.value
    file_hashes: Dict[str, str] = field(default_factory=dict)

    def is_penalizable(self, attribution_filtering: bool = True) -> bool:
        """Rule of Attribution: Only STRONG or VERIFIED attribution is eligible for edge penalties."""
        if not attribution_filtering:
            return self.attribution_strength in (
                AttributionStrength.MODERATE.value,
                AttributionStrength.STRONG.value,
                AttributionStrength.VERIFIED.value,
            )
        return self.attribution_strength in (
            AttributionStrength.STRONG.value,
            AttributionStrength.VERIFIED.value,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NegativeExperienceRecord":
        return cls(**data)


@dataclass
class NegativeEdgeStats:
    """Historical failure statistics attributed to a repository graph edge."""
    edge_id: str
    source: str
    target: str
    edge_type: str
    negative_event_count: int = 0
    strongly_attributed_failures: int = 0
    failed_task_ids: List[str] = field(default_factory=list)
    failure_types: Dict[str, int] = field(default_factory=dict)
    last_failure_timestamp: float = 0.0
    repository_versions: List[str] = field(default_factory=list)
    confidence: float = 1.0
    max_attribution_strength: str = AttributionStrength.NONE.value
    source_negative_experiences: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    target_symbols: List[str] = field(default_factory=list)
    file_hashes: Dict[str, str] = field(default_factory=dict)
    last_attribution_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NegativeEdgeStats":
        return cls(**data)


@dataclass
class ExperienceEdgeStats:
    """Historical verified positive experience associated with a repository graph edge."""
    edge_id: str
    source: str
    target: str
    edge_type: str
    verified_success_count: int = 0
    verified_failure_count: int = 0
    task_categories: Dict[str, int] = field(default_factory=dict)
    last_success_timestamp: float = 0.0
    confidence: float = 1.0
    repository_versions: List[str] = field(default_factory=list)
    source_experiences: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    target_symbols: List[str] = field(default_factory=list)
    file_hashes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperienceEdgeStats":
        return cls(**data)


@dataclass
class ScoredEdge:
    """Graph edge scored dynamically by base structure, positive experience, and negative experience."""
    edge_id: str
    source: str
    target: str
    edge_type: str
    source_symbol: str = ""
    target_symbol: str = ""
    base_score: float = 1.0
    experience_score: float = 0.0
    negative_score: float = 0.0
    net_experience_score: float = 0.0
    task_relevance: float = 0.0
    freshness_factor: float = 1.0
    final_score: float = 1.0
    contributing_experiences: List[str] = field(default_factory=list)
    contributing_negative_experiences: List[str] = field(default_factory=list)
    selection_reason: str = ""
    negative_reason: str = ""
    attribution_strength: str = AttributionStrength.NONE.value
    freshness_status: str = FreshnessStatus.VALID.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScoredEdge":
        return cls(**data)


@dataclass
class ExperienceGraphConfig:
    """Configuration for adaptive graph traversal, positive boosts, and negative penalties."""
    base_weight_calls: float = 1.0
    base_weight_tests: float = 1.0
    base_weight_imports: float = 0.8
    base_weight_defines: float = 0.6
    base_weight_default: float = 0.5
    alpha_experience: float = 1.0
    beta_negative: float = 0.80
    score_floor: float = 0.15
    enable_negative_penalties: bool = True
    attribution_filtering_enabled: bool = True
    recency_tau_seconds: float = 604800.0  # 7 days half-life
    recency_tau_negative_seconds: float = 604800.0  # 7 days
    stale_freshness_factor: float = 0.3
    revalidated_freshness_factor: float = 0.8
    contradicted_freshness_factor: float = 0.0
    max_nodes: int = 15
    max_edges: int = 25
    max_tests: int = 5
    max_files: int = 5
    expansion_depth: int = 1
    max_context_chars: int = 3500
    enable_experience_text: bool = True  # In Condition E, set to False (ablation)
    min_edge_score: float = 0.05

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AdaptiveRetrievalResult:
    """Structured result returned by AdaptiveGraphRetriever."""
    query: str
    candidate_nodes: List[Dict[str, Any]] = field(default_factory=list)
    selected_nodes: List[Dict[str, Any]] = field(default_factory=list)
    selected_edges: List[Dict[str, Any]] = field(default_factory=list)
    scored_edges: List[ScoredEdge] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    relevant_symbols: List[str] = field(default_factory=list)
    associated_tests: List[Dict[str, Any]] = field(default_factory=list)
    experience_guided_edge_utilization: float = 0.0
    experience_supported_edges: List[str] = field(default_factory=list)
    penalized_edges: List[str] = field(default_factory=list)
    negative_avoidance_count: int = 0
    structural_experience_gain: float = 0.0
    compact_context: str = ""
    latency_ms: float = 0.0
    traversal_log: List[Dict[str, Any]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scored_edges"] = [e.to_dict() if hasattr(e, "to_dict") else e for e in self.scored_edges]
        return d
