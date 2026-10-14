"""Graph Traversal and Query Engine."""

from typing import Any, Dict, List, Optional, Set
from .schema import Node, Edge
from .index import GraphIndex


class GraphTraversal:
    """Provides semantic graph queries over repository entities."""

    def __init__(self, index: GraphIndex):
        self.index = index

    def find_symbol(self, name: str) -> List[Dict[str, Any]]:
        """Locate all graph nodes matching a symbol name."""
        nodes = self.index.find_by_symbol(name)
        return [n.to_dict() for n in nodes]

    def find_file(self, path: str) -> Optional[Dict[str, Any]]:
        """Locate graph node representing a specific file path."""
        # Try direct file node id
        file_id = f"file:{path}"
        node = self.index.get_node(file_id)
        if node:
            return node.to_dict()
        nodes = self.index.find_by_path(path)
        for n in nodes:
            if n.node_type == "file":
                return n.to_dict()
        return None

    def find_imports(self, node_id: str) -> List[Dict[str, Any]]:
        """Find modules imported by a file/module node."""
        edges = self.index.get_outgoing(node_id, edge_type="IMPORTS")
        imported_nodes = []
        for e in edges:
            target_node = self.index.get_node(e.target)
            if target_node:
                d = target_node.to_dict()
                d["edge_evidence"] = e.evidence
                d["edge_confidence"] = e.confidence
                imported_nodes.append(d)
        return imported_nodes

    def find_callers(self, node_id: str) -> List[Dict[str, Any]]:
        """Find functions, methods, or tests that invoke the given entity."""
        edges = self.index.get_incoming(node_id, edge_type="CALLS")
        callers = []
        for e in edges:
            src_node = self.index.get_node(e.source)
            if src_node:
                d = src_node.to_dict()
                d["edge_evidence"] = e.evidence
                d["edge_confidence"] = e.confidence
                callers.append(d)
        return callers

    def find_callees(self, node_id: str) -> List[Dict[str, Any]]:
        """Find functions or methods called by the given entity."""
        edges = self.index.get_outgoing(node_id, edge_type="CALLS")
        callees = []
        for e in edges:
            target_node = self.index.get_node(e.target)
            if target_node:
                d = target_node.to_dict()
                d["edge_evidence"] = e.evidence
                d["edge_confidence"] = e.confidence
                callees.append(d)
        return callees

    def find_tests(self, node_id: str) -> List[Dict[str, Any]]:
        """Find test entities associated with the given node."""
        # Check incoming TESTS edges
        edges = self.index.get_incoming(node_id, edge_type="TESTS")
        tests = []
        for e in edges:
            src_node = self.index.get_node(e.source)
            if src_node and src_node.node_type == "test":
                d = src_node.to_dict()
                d["edge_evidence"] = e.evidence
                d["edge_confidence"] = e.confidence
                tests.append(d)
        return tests

    def neighbors(
        self,
        node_id: str,
        edge_type: Optional[str] = None,
        direction: str = "both",
    ) -> List[Dict[str, Any]]:
        """Return adjacent nodes and connecting edges."""
        results = []
        seen: Set[str] = set()

        if direction in ("both", "out"):
            for e in self.index.get_outgoing(node_id, edge_type):
                if e.target not in seen:
                    target_node = self.index.get_node(e.target)
                    if target_node:
                        d = target_node.to_dict()
                        d["relationship"] = e.edge_type
                        d["direction"] = "outgoing"
                        d["evidence"] = e.evidence
                        results.append(d)
                        seen.add(e.target)

        if direction in ("both", "in"):
            for e in self.index.get_incoming(node_id, edge_type):
                if e.source not in seen:
                    src_node = self.index.get_node(e.source)
                    if src_node:
                        d = src_node.to_dict()
                        d["relationship"] = e.edge_type
                        d["direction"] = "incoming"
                        d["evidence"] = e.evidence
                        results.append(d)
                        seen.add(e.source)

        return results

    def subgraph(self, node_id: str, depth: int = 1) -> Dict[str, Any]:
        """Extract a bounded k-hop subgraph around a center node."""
        visited_nodes: Set[str] = {node_id}
        frontier: Set[str] = {node_id}
        collected_edges: List[Edge] = []

        for _ in range(depth):
            next_frontier: Set[str] = set()
            for curr in frontier:
                out_edges = self.index.get_outgoing(curr)
                in_edges = self.index.get_incoming(curr)

                for e in out_edges:
                    collected_edges.append(e)
                    if e.target not in visited_nodes:
                        visited_nodes.add(e.target)
                        next_frontier.add(e.target)

                for e in in_edges:
                    collected_edges.append(e)
                    if e.source not in visited_nodes:
                        visited_nodes.add(e.source)
                        next_frontier.add(e.source)

            frontier = next_frontier
            if not frontier:
                break

        # Unique edges
        unique_edges = {e.edge_id: e for e in collected_edges}
        nodes_dict = {
            nid: self.index.get_node(nid).to_dict()
            for nid in visited_nodes
            if self.index.get_node(nid)
        }

        return {
            "center": node_id,
            "depth": depth,
            "nodes": list(nodes_dict.values()),
            "edges": [e.to_dict() for e in unique_edges.values()],
        }

    def search_subgraph(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search nodes matching query tokens and return with local neighborhood context."""
        query_lower = query.lower()
        matched: List[Node] = []

        for node in self.index.nodes.values():
            if (
                query_lower in node.symbol.lower()
                or query_lower in node.path.lower()
                or query_lower in node.node_id.lower()
            ):
                matched.append(node)

        results = []
        for n in matched[:max_results]:
            d = n.to_dict()
            d["incoming_count"] = len(self.index.get_incoming(n.node_id))
            d["outgoing_count"] = len(self.index.get_outgoing(n.node_id))
            results.append(d)

        return results
