"""Data structures for repository graph retrieval."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RetrievalConfig:
    """Configuration limits and parameters for graph retrieval."""

    max_nodes: int = 12
    max_edges: int = 20
    max_files: int = 5
    max_tests: int = 5
    max_context_chars: int = 4000
    expansion_depth: int = 1
    enable_relationship_expansion: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    """Structured evidence returned by the graph retrieval pipeline."""

    query: str
    candidate_nodes: List[Dict[str, Any]] = field(default_factory=list)
    selected_nodes: List[Dict[str, Any]] = field(default_factory=list)
    selected_edges: List[Dict[str, Any]] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    relevant_symbols: List[str] = field(default_factory=list)
    associated_tests: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    compact_context: str = ""
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
