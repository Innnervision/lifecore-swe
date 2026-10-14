"""Adaptive Graph Traversal Guided by Historical Experience and Failure Penalties (M4)."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..codegraph.index import GraphIndex
from ..codegraph.schema import Edge, Node
from .edge_scorer import DeterministicEdgeScorer
from .models import ExperienceGraphConfig, ScoredEdge
from .negative_overlay import NegativeGraphOverlay
from .overlay import ExperienceGraphOverlay


class AdaptiveGraphTraversal:
    """Traverses repository graph prioritizing positive experience and penalizing attributed failures."""

    def __init__(
        self,
        index: GraphIndex,
        overlay: Optional[ExperienceGraphOverlay] = None,
        negative_overlay: Optional[NegativeGraphOverlay] = None,
        scorer: Optional[DeterministicEdgeScorer] = None,
    ):
        self.index = index
        self.overlay = overlay or ExperienceGraphOverlay()
        self.negative_overlay = negative_overlay or NegativeGraphOverlay()
        self.scorer = scorer or DeterministicEdgeScorer()
        self.traversal_log: List[Dict[str, Any]] = []

    def clear_log(self) -> None:
        """Reset traversal audit trail."""
        self.traversal_log = []

    def experience_guided_neighbors(
        self,
        node_id: str,
        task_text: str,
        task_category: str = "",
        repo_path: Optional[Path] = None,
        repo_version: str = "",
        direction: str = "both",
        edge_type: Optional[str] = None,
    ) -> List[Tuple[ScoredEdge, Dict[str, Any]]]:
        """Rank adjacent nodes and connecting edges using positive experience and negative failure penalties."""
        node = self.index.get_node(node_id)
        if not node:
            return []

        tokens = set(re.findall(r"\b[A-Za-z0-9_]{3,}\b", task_text.lower()))
        edges_to_evaluate: List[Edge] = []

        if direction in ("both", "out"):
            edges_to_evaluate.extend(self.index.get_outgoing(node_id, edge_type=edge_type))
        if direction in ("both", "in"):
            edges_to_evaluate.extend(self.index.get_incoming(node_id, edge_type=edge_type))

        scored_list: List[Tuple[ScoredEdge, Dict[str, Any]]] = []

        for e in edges_to_evaluate:
            other_id = e.target if e.source == node_id else e.source
            other_node = self.index.get_node(other_id)
            if not other_node:
                continue

            src_node = self.index.get_node(e.source)
            tgt_node = self.index.get_node(e.target)

            stats = self.overlay.get_edge_stats(e.source, e.target, e.edge_type) if self.overlay else None
            neg_stats = (
                self.negative_overlay.get_negative_stats(e.source, e.target, e.edge_type)
                if self.negative_overlay
                else None
            )

            scored = self.scorer.score_edge(
                edge_id=f"{e.source}->{e.edge_type}->{e.target}",
                source=e.source,
                target=e.target,
                edge_type=e.edge_type,
                task_text=task_text,
                task_category=task_category,
                task_tokens=tokens,
                stats=stats,
                neg_stats=neg_stats,
                repo_path=repo_path,
                current_repo_version=repo_version,
                source_symbol=src_node.symbol if src_node else "",
                target_symbol=tgt_node.symbol if tgt_node else "",
            )
            scored_list.append((scored, other_node.to_dict()))

        # Sort by final_score descending, then edge_id for determinism
        scored_list.sort(key=lambda item: (item[0].final_score, item[0].edge_id), reverse=True)

        return scored_list

    def experience_guided_tests(
        self,
        node_id: str,
        task_text: str,
        task_category: str = "",
        repo_path: Optional[Path] = None,
        repo_version: str = "",
    ) -> List[Tuple[ScoredEdge, Dict[str, Any]]]:
        """Discover and rank test entities connected to a node, combining test successes and regression penalties."""
        return self.experience_guided_neighbors(
            node_id=node_id,
            task_text=task_text,
            task_category=task_category,
            repo_path=repo_path,
            repo_version=repo_version,
            direction="in",
            edge_type="TESTS",
        )

    def experience_guided_subgraph(
        self,
        center_node_ids: List[str],
        depth: int = 1,
        task_text: str = "",
        task_category: str = "",
        max_nodes: int = 15,
        max_edges: int = 25,
        max_tests: int = 5,
        repo_path: Optional[Path] = None,
        repo_version: str = "",
    ) -> Dict[str, Any]:
        """Expand subgraph around centers prioritizing high positive edges and demoting penalized failure paths."""
        self.clear_log()
        visited_nodes: Set[str] = set(center_node_ids)
        selected_edges_map: Dict[str, ScoredEdge] = {}
        associated_tests_map: Dict[str, Tuple[ScoredEdge, Dict[str, Any]]] = {}
        frontier: Set[str] = set(center_node_ids)
        avoided_edges: List[str] = []

        for current_depth in range(1, depth + 1):
            next_frontier: Set[str] = set()
            nodes_considered = list(frontier)
            edges_considered: List[Dict[str, Any]] = []
            selected_edges: List[str] = []
            rejected_edges: List[str] = []

            candidate_transitions: List[Tuple[ScoredEdge, Dict[str, Any]]] = []

            for curr_nid in frontier:
                # 1. Tests
                test_neighbors = self.experience_guided_tests(
                    node_id=curr_nid,
                    task_text=task_text,
                    task_category=task_category,
                    repo_path=repo_path,
                    repo_version=repo_version,
                )
                for scored_e, t_node in test_neighbors:
                    candidate_transitions.append((scored_e, t_node))

                # 2. Callers & Callees & Imports
                general_neighbors = self.experience_guided_neighbors(
                    node_id=curr_nid,
                    task_text=task_text,
                    task_category=task_category,
                    repo_path=repo_path,
                    repo_version=repo_version,
                    direction="both",
                )
                for scored_e, n_dict in general_neighbors:
                    candidate_transitions.append((scored_e, n_dict))

            # Deduplicate transitions by edge_id
            unique_candidates: Dict[str, Tuple[ScoredEdge, Dict[str, Any]]] = {}
            for scored_e, n_dict in candidate_transitions:
                if scored_e.edge_id not in unique_candidates:
                    unique_candidates[scored_e.edge_id] = (scored_e, n_dict)

            # Sort transitions by final_score descending
            sorted_candidates = sorted(
                unique_candidates.values(),
                key=lambda x: (x[0].final_score, x[0].edge_id),
                reverse=True,
            )

            # Select transitions up to remaining edge & node budgets
            stop_reason = "depth_complete"
            for scored_e, n_dict in sorted_candidates:
                nid = n_dict["node_id"]
                edges_considered.append({
                    "edge_id": scored_e.edge_id,
                    "final_score": scored_e.final_score,
                    "experience_score": scored_e.experience_score,
                    "negative_score": scored_e.negative_score,
                    "freshness": scored_e.freshness_status,
                    "attribution": scored_e.attribution_strength,
                })

                if len(selected_edges_map) >= max_edges:
                    stop_reason = "max_edges_reached"
                    rejected_edges.append(scored_e.edge_id)
                    if scored_e.negative_score > 0.0:
                        avoided_edges.append(scored_e.edge_id)
                    continue

                if nid not in visited_nodes and len(visited_nodes) >= max_nodes:
                    rejected_edges.append(scored_e.edge_id)
                    if scored_e.negative_score > 0.0:
                        avoided_edges.append(scored_e.edge_id)
                    continue

                # Accept edge
                selected_edges_map[scored_e.edge_id] = scored_e
                selected_edges.append(scored_e.edge_id)

                if scored_e.edge_type == "TESTS":
                    if len(associated_tests_map) < max_tests:
                        associated_tests_map[nid] = (scored_e, n_dict)

                if nid not in visited_nodes:
                    visited_nodes.add(nid)
                    next_frontier.add(nid)

            self.traversal_log.append({
                "depth": current_depth,
                "nodes_considered": nodes_considered,
                "edges_considered_count": len(edges_considered),
                "edges_selected_count": len(selected_edges),
                "selected_edges": selected_edges,
                "rejected_edges": rejected_edges[:10],
                "avoided_penalized_edges": avoided_edges,
                "stop_reason": stop_reason,
            })

            frontier = next_frontier
            if not frontier or len(selected_edges_map) >= max_edges or len(visited_nodes) >= max_nodes:
                break

        nodes_dict: Dict[str, Dict[str, Any]] = {}
        for nid in visited_nodes:
            n = self.index.get_node(nid)
            if n:
                nodes_dict[nid] = n.to_dict()

        return {
            "center_nodes": center_node_ids,
            "depth": depth,
            "nodes": list(nodes_dict.values()),
            "edges": list(selected_edges_map.values()),
            "tests": list(associated_tests_map.values()),
            "avoided_edges": avoided_edges,
            "traversal_log": self.traversal_log,
        }
