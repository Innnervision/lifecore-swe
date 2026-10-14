"""LIFECORE-SWE Resource Graph Subsystem (M5-C).

Provides relational graph structures, deterministic multi-attribute ranking,
and bounded evidence retrieval over external software resources.
"""

from .schema import (
    ResourceEdge,
    ResourceEdgeType,
    ResourceNode,
    ResourceNodeType,
    map_resource_type_to_node_type,
)
from .index import ResourceGraph
from .builder import ResourceGraphBuilder
from .ranking import ResourceRanker, ScoredResourceNode
from .retriever import (
    ResourceEvidenceItem,
    ResourceGraphRetriever,
    ResourceRetrievalConfig,
    ResourceRetrievalResult,
)

__all__ = [
    "ResourceNodeType",
    "ResourceEdgeType",
    "ResourceNode",
    "ResourceEdge",
    "map_resource_type_to_node_type",
    "ResourceGraph",
    "ResourceGraphBuilder",
    "ResourceRanker",
    "ScoredResourceNode",
    "ResourceRetrievalConfig",
    "ResourceEvidenceItem",
    "ResourceRetrievalResult",
    "ResourceGraphRetriever",
]
