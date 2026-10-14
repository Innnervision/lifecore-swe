"""Deterministic Graph-Guided Resource Retriever for LIFECORE-SWE.

Performs:
1. Seed identification via lexical and package matching
2. Graph expansion across structural relationships
3. Provenance, freshness, version, and status filtering
4. Multi-attribute ranking
5. Bounded evidence selection and compact context formatting
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..models import FreshnessStatus, ResourceVerificationStatus
from ..provenance import ProvenanceRecord, TrustLevel
from .index import ResourceGraph
from .ranking import ResourceRanker, ScoredResourceNode
from .schema import ResourceEdge, ResourceEdgeType, ResourceNode, ResourceNodeType


@dataclass
class ResourceRetrievalConfig:
    """Configuration for deterministic, bounded resource retrieval."""
    max_resources: int = 5
    max_depth: int = 2
    min_score: float = 0.20
    min_trust_level: TrustLevel = TrustLevel.LOW
    allow_stale: bool = False
    exclude_contradicted_and_rejected: bool = True
    target_package: Optional[str] = None
    target_version: Optional[str] = None
    allowed_node_types: Optional[Set[ResourceNodeType]] = None


@dataclass
class ResourceEvidenceItem:
    """A bounded evidence item selected by the retriever."""
    node: ResourceNode
    score: float
    reasons: List[str]
    sub_scores: Dict[str, float]
    relationships: List[ResourceEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node.node_id,
            "node_type": self.node.node_type.value,
            "title": self.node.title,
            "package_name": self.node.package_name,
            "version": self.node.version,
            "source": self.node.source,
            "verification_status": self.node.verification_status.value,
            "freshness": self.node.freshness.value,
            "score": round(self.score, 4),
            "reasons": self.reasons,
            "sub_scores": {k: round(v, 4) for k, v in self.sub_scores.items()},
            "relationships_count": len(self.relationships),
        }


@dataclass
class ResourceRetrievalResult:
    """Complete structured output from a resource retrieval operation."""
    query: str
    items: List[ResourceEvidenceItem]
    total_candidates_considered: int
    traversal_depth: int
    execution_time_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "items_count": len(self.items),
            "items": [item.to_dict() for item in self.items],
            "total_candidates_considered": self.total_candidates_considered,
            "traversal_depth": self.traversal_depth,
            "execution_time_ms": round(self.execution_time_ms, 2),
        }

    def format_compact_context(self) -> str:
        """Format bounded external evidence context with provenance labels."""
        if not self.items:
            return "EXTERNAL RESOURCE EVIDENCE:\n  (No relevant external resources found)"

        lines = ["EXTERNAL RESOURCE EVIDENCE:"]
        for idx, item in enumerate(self.items, 1):
            n = item.node
            lines.append(f"\n[{idx}] {n.title} ({n.node_type.value})")
            lines.append(f"    Source: {n.source}")
            if n.package_name:
                ver_str = f" v{n.version}" if n.version else ""
                lines.append(f"    Package: {n.package_name}{ver_str}")
            lines.append(f"    Verification Status: {n.verification_status.value}")
            lines.append(f"    Freshness: {n.freshness.value}")
            lines.append(f"    Relevance Score: {item.score:.2f}")
            if n.description:
                short_desc = n.description[:180] + ("..." if len(n.description) > 180 else "")
                lines.append(f"    Summary: {short_desc}")
            if item.relationships:
                rel_strs = [f"{e.edge_type.value}->{e.target_id}" for e in item.relationships[:3]]
                lines.append(f"    Related: {', '.join(rel_strs)}")
        return "\n".join(lines)


class ResourceGraphRetriever:
    """Performs deterministic, bounded retrieval over a ResourceGraph."""

    def __init__(
        self,
        graph: ResourceGraph,
        ranker: Optional[ResourceRanker] = None,
        provenance_records: Optional[Dict[str, ProvenanceRecord]] = None,
    ) -> None:
        self.graph = graph
        self.ranker = ranker or ResourceRanker()
        self.provenance_map: Dict[str, ProvenanceRecord] = provenance_records or {}

    def retrieve(
        self,
        query_text: str,
        config: Optional[ResourceRetrievalConfig] = None,
    ) -> ResourceRetrievalResult:
        """Execute deterministic retrieval pipeline."""
        start_t = time.perf_counter()
        cfg = config or ResourceRetrievalConfig()

        # Step 1: Identify seed candidate nodes
        seed_nodes = self._find_seed_nodes(query_text, cfg)

        # Step 2: Graph expansion up to cfg.max_depth
        candidate_ids = self._expand_graph(seed_nodes, cfg.max_depth)

        # Step 3: Filter and score candidates
        scored_candidates: List[ResourceEvidenceItem] = []
        for nid in candidate_ids:
            node = self.graph.get_node(nid)
            if node is None:
                continue

            # Filtering checks
            if not self._passes_filters(node, cfg):
                continue

            prov = self.provenance_map.get(node.provenance_id) if node.provenance_id else None
            scored_node = self.ranker.score(
                node=node,
                query_text=query_text,
                target_package=cfg.target_package,
                target_version=cfg.target_version,
                provenance=prov,
            )

            if scored_node.score >= cfg.min_score:
                out_edges = self.graph.get_out_edges(node.node_id)
                scored_candidates.append(
                    ResourceEvidenceItem(
                        node=node,
                        score=scored_node.score,
                        reasons=scored_node.reasons,
                        sub_scores=scored_node.sub_scores,
                        relationships=out_edges,
                    )
                )

        # Step 4: Deterministic sort: score descending, then node_id ascending
        scored_candidates.sort(key=lambda item: (-item.score, item.node.node_id))

        # Step 5: Bounded selection
        selected_items = scored_candidates[:cfg.max_resources]
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        return ResourceRetrievalResult(
            query=query_text,
            items=selected_items,
            total_candidates_considered=len(candidate_ids),
            traversal_depth=cfg.max_depth,
            execution_time_ms=elapsed_ms,
        )

    def _find_seed_nodes(self, query_text: str, cfg: ResourceRetrievalConfig) -> Set[str]:
        seeds: Set[str] = set()
        q_tokens = ResourceRanker._tokenize(query_text)
        if cfg.target_package:
            q_tokens.add(cfg.target_package.lower())

        for node in self.graph.nodes.values():
            # Check package name match
            if cfg.target_package and node.package_name and node.package_name.lower() == cfg.target_package.lower():
                seeds.add(node.node_id)
                continue

            # Check token overlap
            node_text = f"{node.title} {node.package_name or ''} {node.description}"
            node_tokens = ResourceRanker._tokenize(node_text)
            if q_tokens.intersection(node_tokens):
                seeds.add(node.node_id)

        # If no seeds found and graph not empty, include package nodes as initial anchor
        if not seeds and cfg.target_package:
            pkg_nodes = self.graph.find_by_package(cfg.target_package)
            for pn in pkg_nodes:
                seeds.add(pn.node_id)

        return seeds

    def _expand_graph(self, seed_ids: Set[str], max_depth: int) -> Set[str]:
        visited: Set[str] = set(seed_ids)
        current_layer: Set[str] = set(seed_ids)

        for _ in range(max_depth):
            next_layer: Set[str] = set()
            for nid in current_layer:
                # Traverse outgoing edges
                for edge in self.graph.get_out_edges(nid):
                    if edge.target_id not in visited:
                        visited.add(edge.target_id)
                        next_layer.add(edge.target_id)
                # Traverse incoming edges
                for edge in self.graph.get_in_edges(nid):
                    if edge.source_id not in visited:
                        visited.add(edge.source_id)
                        next_layer.add(edge.source_id)
            current_layer = next_layer
            if not current_layer:
                break

        return visited

    def _passes_filters(self, node: ResourceNode, cfg: ResourceRetrievalConfig) -> bool:
        # 1. Allowed node types
        if cfg.allowed_node_types is not None and node.node_type not in cfg.allowed_node_types:
            return False

        # 2. Status exclusions
        if cfg.exclude_contradicted_and_rejected:
            if node.verification_status in (
                ResourceVerificationStatus.REJECTED,
                ResourceVerificationStatus.CONTRADICTED,
            ):
                return False

        # 3. Staleness
        if not cfg.allow_stale and node.freshness == FreshnessStatus.STALE:
            return False

        # 4. Provenance trust level
        if node.provenance_id and node.provenance_id in self.provenance_map:
            prov = self.provenance_map[node.provenance_id]
            # TrustLevel enum comparison
            trust_order = {
                TrustLevel.UNTRUSTED: 0,
                TrustLevel.LOW: 1,
                TrustLevel.MEDIUM: 2,
                TrustLevel.HIGH: 3,
                TrustLevel.VERIFIED_INTERNAL: 4,
            }
            if trust_order.get(prov.trust_level, 0) < trust_order.get(cfg.min_trust_level, 0):
                return False

        return True
