"""Schema definitions for the LIFECORE-SWE Resource Graph (M5-C).

External resources are modeled as a dedicated, provenance-aware graph
completely segregated from the internal repository AST code graph.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from ..models import FreshnessStatus, ResourceRecord, ResourceType, ResourceVerificationStatus


class ResourceNodeType(str, Enum):
    """Categorization of entities within the Resource Graph."""
    RESOURCE = "RESOURCE"
    SOURCE = "SOURCE"
    PACKAGE = "PACKAGE"
    PACKAGE_VERSION = "PACKAGE_VERSION"
    REPOSITORY = "REPOSITORY"
    DOCUMENTATION = "DOCUMENTATION"
    API = "API"
    EXAMPLE = "EXAMPLE"
    ISSUE = "ISSUE"
    COMMIT = "COMMIT"
    PAPER = "PAPER"
    BENCHMARK = "BENCHMARK"


class ResourceEdgeType(str, Enum):
    """Categorization of relational edges within the Resource Graph."""
    SOURCED_FROM = "SOURCED_FROM"
    DOCUMENTS = "DOCUMENTS"
    VERSION_OF = "VERSION_OF"
    REFERENCES = "REFERENCES"
    EXAMPLE_FOR = "EXAMPLE_FOR"
    DEPENDS_ON = "DEPENDS_ON"
    RELATED_TO = "RELATED_TO"
    SUPERSEDES = "SUPERSEDES"
    CONTRADICTS = "CONTRADICTS"
    VALIDATED_BY = "VALIDATED_BY"


def map_resource_type_to_node_type(res_type: ResourceType) -> ResourceNodeType:
    """Map ResourceType from M5-A/B to ResourceNodeType."""
    mapping = {
        ResourceType.DOCUMENTATION: ResourceNodeType.DOCUMENTATION,
        ResourceType.PACKAGE: ResourceNodeType.PACKAGE,
        ResourceType.PACKAGE_VERSION: ResourceNodeType.PACKAGE_VERSION,
        ResourceType.REPOSITORY: ResourceNodeType.REPOSITORY,
        ResourceType.API_REFERENCE: ResourceNodeType.API,
        ResourceType.CODE_EXAMPLE: ResourceNodeType.EXAMPLE,
        ResourceType.ISSUE: ResourceNodeType.ISSUE,
        ResourceType.COMMIT: ResourceNodeType.COMMIT,
        ResourceType.PULL_REQUEST: ResourceNodeType.ISSUE,
        ResourceType.PAPER: ResourceNodeType.PAPER,
        ResourceType.BENCHMARK: ResourceNodeType.BENCHMARK,
        ResourceType.WEB_RESOURCE: ResourceNodeType.RESOURCE,
        ResourceType.OTHER: ResourceNodeType.RESOURCE,
    }
    return mapping.get(res_type, ResourceNodeType.RESOURCE)


@dataclass
class ResourceNode:
    """Represents a discrete external entity in the Resource Graph."""
    node_id: str
    node_type: ResourceNodeType
    title: str
    source: str
    description: str = ""
    url: Optional[str] = None
    package_name: Optional[str] = None
    repository: Optional[str] = None
    version: Optional[str] = None
    content_hash: str = ""
    verification_status: ResourceVerificationStatus = ResourceVerificationStatus.UNVERIFIED
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN
    confidence: float = 1.0
    provenance_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.node_type, str):
            self.node_type = ResourceNodeType(self.node_type)
        if isinstance(self.verification_status, str):
            self.verification_status = ResourceVerificationStatus(self.verification_status)
        if isinstance(self.freshness, str):
            self.freshness = FreshnessStatus(self.freshness)
        if not self.created_at:
            self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    @classmethod
    def from_resource_record(cls, record: ResourceRecord) -> ResourceNode:
        """Construct a ResourceNode directly from an M5-A/B ResourceRecord."""
        n_type = map_resource_type_to_node_type(record.resource_type)
        return cls(
            node_id=record.resource_id,
            node_type=n_type,
            title=record.title or f"{n_type.value}: {record.resource_id}",
            source=record.source,
            description=record.description,
            url=record.url,
            package_name=record.package_name,
            repository=record.repository,
            version=record.version,
            content_hash=record.content_hash,
            verification_status=record.verification_status,
            freshness=record.freshness,
            confidence=record.confidence,
            provenance_id=record.provenance_id,
            metadata=dict(record.metadata),
            created_at=record.created_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["node_type"] = self.node_type.value
        d["verification_status"] = self.verification_status.value
        d["freshness"] = self.freshness.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourceNode:
        d = dict(data)
        d["node_type"] = ResourceNodeType(d["node_type"])
        d["verification_status"] = ResourceVerificationStatus(d.get("verification_status", ResourceVerificationStatus.UNVERIFIED.value))
        d["freshness"] = FreshnessStatus(d.get("freshness", FreshnessStatus.UNKNOWN.value))
        return cls(**d)


@dataclass
class ResourceEdge:
    """Represents a directed relationship between two entities in the Resource Graph."""
    edge_id: str
    source_id: str
    target_id: str
    edge_type: ResourceEdgeType
    provenance_id: Optional[str] = None
    confidence: float = 1.0
    evidence: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.edge_type, str):
            self.edge_type = ResourceEdgeType(self.edge_type)
        if not self.created_at:
            self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["edge_type"] = self.edge_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourceEdge:
        d = dict(data)
        d["edge_type"] = ResourceEdgeType(d["edge_type"])
        return cls(**d)
