"""LIFECORE-SWE Resource Intelligence Subsystem (M5-A, M5-B, M5-C, M5-D).

Provides provenance tracking, network permission policies, versioning,
offline ingestion adapters, validation pipelines, persistent external resource
representation, relational Resource Graph, deterministic bounded retrieval,
and truth-bounded context construction for Gemma 4 reasoning.
"""

from .models import (
    FreshnessPolicy,
    FreshnessStatus,
    ResourceRecord,
    ResourceType,
    ResourceVerificationStatus,
    compute_content_hash,
    generate_deterministic_resource_id,
    normalize_url,
)
from .permissions import (
    NetworkPermissionLevel,
    NetworkRequest,
    PermissionDecision,
    PermissionPolicy,
)
from .provenance import (
    ProvenanceRecord,
    RetrievalMethod,
    SourceType,
    TrustLevel,
    generate_provenance_id,
)
from .registry import ResourceRegistry
from .store import ResourceStore
from .validator import ResourceValidator, ValidationResult
from .adapters import (
    AdapterIngestionResult,
    BaseResourceAdapter,
    MockResourceAdapter,
    PackageMetadataAdapter,
    PythonDocsAdapter,
)
from .graph import (
    ResourceEdge,
    ResourceEdgeType,
    ResourceEvidenceItem,
    ResourceGraph,
    ResourceGraphBuilder,
    ResourceGraphRetriever,
    ResourceNode,
    ResourceNodeType,
    ResourceRanker,
    ResourceRetrievalConfig,
    ResourceRetrievalResult,
    ScoredResourceNode,
)
from .context_builder import (
    ResourceContextBuilder,
    UnifiedWorldModelContextBuilder,
)

__all__ = [
    "ResourceType",
    "ResourceVerificationStatus",
    "FreshnessStatus",
    "FreshnessPolicy",
    "ResourceRecord",
    "normalize_url",
    "compute_content_hash",
    "generate_deterministic_resource_id",
    "SourceType",
    "TrustLevel",
    "RetrievalMethod",
    "ProvenanceRecord",
    "generate_provenance_id",
    "NetworkPermissionLevel",
    "NetworkRequest",
    "PermissionDecision",
    "PermissionPolicy",
    "ResourceStore",
    "ResourceRegistry",
    "ResourceValidator",
    "ValidationResult",
    "BaseResourceAdapter",
    "AdapterIngestionResult",
    "PythonDocsAdapter",
    "PackageMetadataAdapter",
    "MockResourceAdapter",
    "ResourceNodeType",
    "ResourceEdgeType",
    "ResourceNode",
    "ResourceEdge",
    "ResourceGraph",
    "ResourceGraphBuilder",
    "ResourceRanker",
    "ScoredResourceNode",
    "ResourceRetrievalConfig",
    "ResourceEvidenceItem",
    "ResourceRetrievalResult",
    "ResourceGraphRetriever",
    "ResourceContextBuilder",
    "UnifiedWorldModelContextBuilder",
]
