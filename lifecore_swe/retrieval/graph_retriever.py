"""Deterministic Graph-Guided Repository Retriever."""

import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from ..codegraph.index import GraphIndex
from ..codegraph.ranking import GraphRanker
from ..codegraph.traversal import GraphTraversal
from ..codegraph.schema import Node, Edge
from .models import RetrievalConfig, RetrievalResult
from .context_builder import ContextBuilder


class GraphRetriever:
    """Performs deterministic, graph-guided code entity and relationship retrieval."""

    def __init__(self, index: GraphIndex):
        self.index = index
        self.traversal = GraphTraversal(index)
        self.ranker = GraphRanker(index)

    def retrieve(
        self,
        task_text: str,
        config: Optional[RetrievalConfig] = None,
        failing_tests: Optional[List[str]] = None,
    ) -> RetrievalResult:
        """Execute deterministic graph retrieval pipeline."""
        start_time = time.perf_counter()
        cfg = config or RetrievalConfig()

        # Step 1: Token extraction from task
        clean_text = task_text.replace("-", " ").replace(".", " ").replace("_", " ")
        tokens = set(re.findall(r"\b[A-Za-z0-9_]{3,}\b", clean_text.lower()))
        # Remove common stop words
        stop_words = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "will", "when"}
        tokens = {t for t in tokens if t not in stop_words}

        # Step 2: Rank initial candidate nodes
        ranked_candidates = self.ranker.rank_candidates(
            task_text=task_text,
            failing_tests=failing_tests,
            top_k=cfg.max_nodes * 2,
        )

        # Fallback if no lexical candidates matched: pick central classes/functions
        if not ranked_candidates:
            for node in self.index.nodes.values():
                if node.node_type in ("class", "function", "method"):
                    d = node.to_dict()
                    d["relevance_score"] = 0.1
                    ranked_candidates.append(d)
                if len(ranked_candidates) >= cfg.max_nodes:
                    break

        # Step 3: Candidate Selection
        selected_nodes_map: Dict[str, Dict[str, Any]] = {}
        for cand in ranked_candidates[: cfg.max_nodes]:
            selected_nodes_map[cand["node_id"]] = cand

        # Step 4: Relationship Expansion (if enabled)
        selected_edges_map: Dict[str, Dict[str, Any]] = {}
        associated_tests_map: Dict[str, Dict[str, Any]] = {}

        if cfg.enable_relationship_expansion and cfg.expansion_depth > 0:
            for nid in list(selected_nodes_map.keys()):
                node = self.index.get_node(nid)
                if not node:
                    continue

                # A. Find Tests
                tests = self.traversal.find_tests(nid)
                for t in tests:
                    t_id = t["node_id"]
                    if t_id not in associated_tests_map:
                        t_dict = dict(t)
                        t_dict["target_symbol"] = node.symbol
                        associated_tests_map[t_id] = t_dict

                    edge_key = f"{t_id}->TESTS->{nid}"
                    if edge_key not in selected_edges_map:
                        selected_edges_map[edge_key] = {
                            "edge_id": edge_key,
                            "source": t_id,
                            "source_symbol": t.get("symbol", ""),
                            "edge_type": "TESTS",
                            "target": nid,
                            "target_symbol": node.symbol,
                        }

                # B. Find Callers
                callers = self.traversal.find_callers(nid)
                for c in callers:
                    c_id = c["node_id"]
                    edge_key = f"{c_id}->CALLS->{nid}"
                    if edge_key not in selected_edges_map:
                        selected_edges_map[edge_key] = {
                            "edge_id": edge_key,
                            "source": c_id,
                            "source_symbol": c.get("symbol", ""),
                            "edge_type": "CALLS",
                            "target": nid,
                            "target_symbol": node.symbol,
                        }
                    # Include caller in selected nodes if budget permits
                    if len(selected_nodes_map) < cfg.max_nodes and c_id not in selected_nodes_map:
                        selected_nodes_map[c_id] = c

                # C. Find Callees
                callees = self.traversal.find_callees(nid)
                for callee in callees:
                    callee_id = callee["node_id"]
                    edge_key = f"{nid}->CALLS->{callee_id}"
                    if edge_key not in selected_edges_map:
                        selected_edges_map[edge_key] = {
                            "edge_id": edge_key,
                            "source": nid,
                            "source_symbol": node.symbol,
                            "edge_type": "CALLS",
                            "target": callee_id,
                            "target_symbol": callee.get("symbol", ""),
                        }
                    if len(selected_nodes_map) < cfg.max_nodes and callee_id not in selected_nodes_map:
                        selected_nodes_map[callee_id] = callee

        # Step 5: Enforce limits and extract relevant files & symbols
        sorted_nodes = sorted(
            selected_nodes_map.values(),
            key=lambda x: (x.get("relevance_score", 0.0), x.get("node_id", "")),
            reverse=True,
        )[: cfg.max_nodes]

        sorted_edges = sorted(
            selected_edges_map.values(),
            key=lambda x: x.get("edge_id", ""),
        )[: cfg.max_edges]

        associated_tests = sorted(
            associated_tests_map.values(),
            key=lambda x: x.get("node_id", ""),
        )[: cfg.max_tests]

        # Extract unique relevant files
        files_set: Set[str] = set()
        for n in sorted_nodes:
            p = n.get("path")
            if p and p.endswith(".py"):
                files_set.add(p)
        for t in associated_tests:
            p = t.get("path")
            if p and p.endswith(".py"):
                files_set.add(p)

        relevant_files = sorted(list(files_set))[: cfg.max_files]
        relevant_symbols = [n.get("symbol", "") for n in sorted_nodes if n.get("symbol")]

        # Step 6: Construct Compact Context
        compact_context = ContextBuilder.build_context(
            relevant_files=relevant_files,
            selected_nodes=sorted_nodes,
            selected_edges=sorted_edges,
            associated_tests=associated_tests,
            max_chars=cfg.max_context_chars,
        )

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return RetrievalResult(
            query=task_text,
            candidate_nodes=ranked_candidates,
            selected_nodes=sorted_nodes,
            selected_edges=sorted_edges,
            relevant_files=relevant_files,
            relevant_symbols=relevant_symbols,
            associated_tests=associated_tests,
            latency_ms=latency_ms,
            compact_context=compact_context,
            config=cfg.to_dict(),
        )
