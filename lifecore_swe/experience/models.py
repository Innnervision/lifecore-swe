"""Structured data models for persistent experience and memory."""

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class VerificationStatus(str, Enum):
    """Explicit verification lifecycle states for experience records."""
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    TESTED = "TESTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    REVERTED = "REVERTED"


class StaleStatus(str, Enum):
    """Freshness status of historical experience relative to current repository."""
    VALID = "VALID"
    STALE = "STALE"
    CONTRADICTED = "CONTRADICTED"
    REVALIDATED = "REVALIDATED"


@dataclass
class ExperienceRecord:
    """Structured, provenance-tracked experience from a completed SWE task."""
    experience_id: str
    task_id: str
    repository_id: str
    repository_version: str
    task_description: str
    task_category: str = "bug_fix"
    relevant_nodes: List[str] = field(default_factory=list)
    relevant_edges: List[str] = field(default_factory=list)
    files_inspected: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    symbols_modified: List[str] = field(default_factory=list)
    hypothesis: str = ""
    actions: List[Dict[str, Any]] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    patch_summary: str = ""
    final_patch: str = ""
    tests_run: List[Dict[str, Any]] = field(default_factory=list)
    verification_result: Dict[str, Any] = field(default_factory=dict)
    success: bool = False
    failure_reason: Optional[str] = None
    recovery_attempts: int = 0
    tool_usage: Dict[str, int] = field(default_factory=dict)
    confidence: float = 1.0
    timestamp: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    verification_status: str = VerificationStatus.PROPOSED.value
    file_hashes: Dict[str, str] = field(default_factory=dict)
    graph_hash: Optional[str] = None
    stale_status: str = StaleStatus.VALID.value

    @property
    def is_verified(self) -> bool:
        """Only explicitly VERIFIED experiences qualify as positive reusable knowledge."""
        return self.verification_status == VerificationStatus.VERIFIED.value and self.success

    @property
    def is_failed(self) -> bool:
        """Indicates whether this record represents a verified failure trajectory."""
        return self.verification_status == VerificationStatus.FAILED.value or not self.success

    def to_dict(self) -> Dict[str, Any]:
        """Convert experience to serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperienceRecord":
        """Reconstruct ExperienceRecord from dictionary."""
        d = dict(data)
        return cls(**d)

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """Compute SHA-256 hash of a file for staleness detection."""
        if not file_path.exists() or not file_path.is_file():
            return ""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()[:16]


@dataclass
class ExperienceRetrievalConfig:
    """Configurable limits and parameters for experience retrieval."""
    max_experiences: int = 3
    max_context_chars: int = 3000
    include_failed: bool = False
    min_similarity_score: float = 0.05
    stale_detection_enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExperienceRetrievalResult:
    """Structured output returned by the experience retrieval pipeline."""
    query: str
    candidate_count: int = 0
    selected_experiences: List[ExperienceRecord] = field(default_factory=list)
    selection_reasons: Dict[str, List[str]] = field(default_factory=dict)
    ranking_scores: Dict[str, float] = field(default_factory=dict)
    stale_statuses: Dict[str, str] = field(default_factory=dict)
    stale_details: Dict[str, str] = field(default_factory=dict)
    compact_context: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["selected_experiences"] = [e.to_dict() for e in self.selected_experiences]
        return res
