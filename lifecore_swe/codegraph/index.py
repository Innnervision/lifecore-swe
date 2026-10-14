"""Graph Index providing indexed lookup and inverted queries."""

from collections import defaultdict
from typing import Dict, List, Optional, Set
from .schema import Node, Edge


class GraphIndex:
    """Indexed container for nodes and edges supporting rapid associative queries."""

    def __init__(self, nodes: Dict[str, Node], edges: Dict[str, Edge]):
        self.nodes = nodes
        self.edges = edges

        self.nodes_by_symbol: Dict[str, List[Node]] = defaultdict(list)
        self.nodes_by_path: Dict[str, List[Node]] = defaultdict(list)
        self.nodes_by_type: Dict[str, List[Node]] = defaultdict(list)

        self.forward_edges: Dict[str, List[Edge]] = defaultdict(list)
        self.backward_edges: Dict[str, List[Edge]] = defaultdict(list)
        self.edges_by_type: Dict[str, List[Edge]] = defaultdict(list)

        self._build_indices()

    def _build_indices(self) -> None:
        for node in self.nodes.values():
            self.nodes_by_symbol[node.symbol.lower()].append(node)
            short_symbol = node.symbol.split(".")[-1].lower()
            if short_symbol != node.symbol.lower():
                self.nodes_by_symbol[short_symbol].append(node)

            self.nodes_by_path[node.path].append(node)
            self.nodes_by_type[node.node_type].append(node)

        for edge in self.edges.values():
            self.forward_edges[edge.source].append(edge)
            self.backward_edges[edge.target].append(edge)
            self.edges_by_type[edge.edge_type].append(edge)

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def find_by_symbol(self, symbol: str) -> List[Node]:
        return self.nodes_by_symbol.get(symbol.lower(), [])

    def find_by_path(self, path: str) -> List[Node]:
        return self.nodes_by_path.get(path, [])

    def find_by_type(self, node_type: str) -> List[Node]:
        return self.nodes_by_type.get(node_type, [])

    def get_outgoing(self, node_id: str, edge_type: Optional[str] = None) -> List[Edge]:
        edges = self.forward_edges.get(node_id, [])
        if edge_type:
            return [e for e in edges if e.edge_type == edge_type]
        return edges

    def get_incoming(self, node_id: str, edge_type: Optional[str] = None) -> List[Edge]:
        edges = self.backward_edges.get(node_id, [])
        if edge_type:
            return [e for e in edges if e.edge_type == edge_type]
        return edges
