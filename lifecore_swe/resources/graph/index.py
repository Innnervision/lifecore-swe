"""Resource Graph Index: In-memory relational index for external software resources.

Provides associative indexing, adjacency queries, and bidirectional traversal
over external resources, sources, packages, and references.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from ..models import ResourceVerificationStatus
from .schema import ResourceEdge, ResourceEdgeType, ResourceNode, ResourceNodeType


class ResourceGraph:
    """Relational graph container for external software resources."""

    def __init__(
        self,
        nodes: Optional[Dict[str, ResourceNode]] = None,
        edges: Optional[Dict[str, ResourceEdge]] = None,
    ) -> None:
        self.nodes: Dict[str, ResourceNode] = nodes or {}
        self.edges: Dict[str, ResourceEdge] = edges or {}

        self.forward_edges: Dict[str, List[ResourceEdge]] = defaultdict(list)
        self.backward_edges: Dict[str, List[ResourceEdge]] = defaultdict(list)

        self.nodes_by_type: Dict[ResourceNodeType, List[ResourceNode]] = defaultdict(list)
        self.nodes_by_source: Dict[str, List[ResourceNode]] = defaultdict(list)
        self.nodes_by_package: Dict[str, List[ResourceNode]] = defaultdict(list)
        self.nodes_by_status: Dict[ResourceVerificationStatus, List[ResourceNode]] = defaultdict(list)

        self._rebuild_indices()

    def _rebuild_indices(self) -> None:
        self.forward_edges.clear()
        self.backward_edges.clear()
        self.nodes_by_type.clear()
        self.nodes_by_source.clear()
        self.nodes_by_package.clear()
        self.nodes_by_status.clear()

        for node in self.nodes.values():
            self._index_node(node)

        for edge in self.edges.values():
            self._index_edge(edge)

    def _index_node(self, node: ResourceNode) -> None:
        self.nodes_by_type[node.node_type].append(node)
        if node.source:
            self.nodes_by_source[node.source.strip().lower()].append(node)
        if node.package_name:
            self.nodes_by_package[node.package_name.strip().lower()].append(node)
        self.nodes_by_status[node.verification_status].append(node)

    def _index_edge(self, edge: ResourceEdge) -> None:
        self.forward_edges[edge.source_id].append(edge)
        self.backward_edges[edge.target_id].append(edge)

    def add_node(self, node: ResourceNode) -> None:
        """Add or update a node in the graph and update indices."""
        self.nodes[node.node_id] = node
        self._index_node(node)

    def add_edge(self, edge: ResourceEdge) -> None:
        """Add or update an edge in the graph and update adjacency lists."""
        self.edges[edge.edge_id] = edge
        self._index_edge(edge)

    def get_node(self, node_id: str) -> Optional[ResourceNode]:
        """Look up a node by its node_id."""
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Optional[ResourceEdge]:
        """Look up an edge by its edge_id."""
        return self.edges.get(edge_id)

    def get_out_edges(self, node_id: str) -> List[ResourceEdge]:
        """Get outgoing directed edges from node_id."""
        return self.forward_edges.get(node_id, [])

    def get_in_edges(self, node_id: str) -> List[ResourceEdge]:
        """Get incoming directed edges to node_id."""
        return self.backward_edges.get(node_id, [])

    def get_neighbors(
        self,
        node_id: str,
        edge_type: Optional[ResourceEdgeType] = None,
        direction: str = "out",
    ) -> List[Tuple[ResourceNode, ResourceEdge]]:
        """Retrieve neighboring nodes and connecting edges."""
        results: List[Tuple[ResourceNode, ResourceEdge]] = []

        if direction in ("out", "both"):
            for edge in self.forward_edges.get(node_id, []):
                if edge_type is None or edge.edge_type == edge_type:
                    target_node = self.nodes.get(edge.target_id)
                    if target_node is not None:
                        results.append((target_node, edge))

        if direction in ("in", "both"):
            for edge in self.backward_edges.get(node_id, []):
                if edge_type is None or edge.edge_type == edge_type:
                    src_node = self.nodes.get(edge.source_id)
                    if src_node is not None:
                        results.append((src_node, edge))

        return results

    def find_by_type(self, node_type: ResourceNodeType) -> List[ResourceNode]:
        """Retrieve all nodes of a specific ResourceNodeType."""
        return self.nodes_by_type.get(node_type, [])

    def find_by_source(self, source: str) -> List[ResourceNode]:
        """Retrieve all nodes matching a source identifier."""
        return self.nodes_by_source.get(source.strip().lower(), [])

    def find_by_package(self, package_name: str) -> List[ResourceNode]:
        """Retrieve all nodes matching a package name."""
        return self.nodes_by_package.get(package_name.strip().lower(), [])

    def find_by_status(self, status: ResourceVerificationStatus) -> List[ResourceNode]:
        """Retrieve all nodes matching a verification status."""
        return self.nodes_by_status.get(status, [])

    def count_nodes(self) -> int:
        return len(self.nodes)

    def count_edges(self) -> int:
        return len(self.edges)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize complete graph structure to dictionary."""
        return {
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": {eid: e.to_dict() for eid, e in self.edges.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourceGraph:
        """Construct graph from serialized dictionary."""
        nodes = {nid: ResourceNode.from_dict(ndata) for nid, ndata in data.get("nodes", {}).items()}
        edges = {eid: ResourceEdge.from_dict(edata) for eid, edata in data.get("edges", {}).items()}
        return cls(nodes=nodes, edges=edges)
