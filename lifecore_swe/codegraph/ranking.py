"""Ranking and localization utilities for repository graph nodes."""

import re
from typing import Any, Dict, List, Optional
from .schema import Node
from .index import GraphIndex


class GraphRanker:
    """Ranks candidate code entities by relevance to task and structural importance."""

    def __init__(self, index: GraphIndex):
        self.index = index

    def rank_candidates(
        self,
        task_text: str,
        failing_tests: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Rank repository graph nodes according to task keywords and test links."""
        tokens = set(re.findall(r"\b[A-Za-z0-9_]{3,}\b", task_text.lower()))
        failing_tests = failing_tests or []

        scored_nodes = []
        for node in self.index.nodes.values():
            if node.node_type in ("repository", "directory"):
                continue

            score = 0.0

            # 1. Symbol matching
            symbol_parts = set(re.findall(r"\b[A-Za-z0-9_]{3,}\b", node.symbol.lower()))
            overlap = tokens.intersection(symbol_parts)
            score += len(overlap) * 3.0

            # 2. Path matching
            path_parts = set(re.findall(r"\b[A-Za-z0-9_]{3,}\b", node.path.lower()))
            score += len(tokens.intersection(path_parts)) * 1.5

            # 3. Connection to failing tests
            if failing_tests:
                incoming_tests = [
                    e.source for e in self.index.get_incoming(node.node_id, edge_type="TESTS")
                ]
                for ft in failing_tests:
                    if any(ft.lower() in t.lower() for t in incoming_tests):
                        score += 5.0

            # 4. Centrality bonus (in-degree from calls/tests)
            calls_in = len(self.index.get_incoming(node.node_id, edge_type="CALLS"))
            tests_in = len(self.index.get_incoming(node.node_id, edge_type="TESTS"))
            score += (calls_in * 0.5) + (tests_in * 1.0)

            if score > 0:
                d = node.to_dict()
                d["relevance_score"] = round(score, 3)
                scored_nodes.append(d)

        scored_nodes.sort(key=lambda x: x["relevance_score"], reverse=True)
        return scored_nodes[:top_k]
