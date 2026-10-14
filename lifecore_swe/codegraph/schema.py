"""Schema definitions for LIFECORE-SWE Repository Graph."""

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Node:
    """Represents an entity in the repository graph."""

    node_id: str
    node_type: str  # repository, directory, file, module, class, function, method, test
    repository_id: str
    path: str
    symbol: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    language: str = "python"
    content_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Node":
        return cls(**data)


@dataclass
class Edge:
    """Represents a directed relationship between two entities."""

    edge_id: str
    source: str
    target: str
    edge_type: str  # CONTAINS, IMPORTS, DEFINES, CALLS, REFERENCES, TESTS, UNKNOWN
    confidence: float = 1.0
    evidence: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Edge":
        return cls(**data)


def compute_content_hash(text: str) -> str:
    """Compute sha256 hash of a content string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
