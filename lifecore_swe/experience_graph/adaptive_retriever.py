"""Adaptive Graph Retriever using Experience-Conditioned Graph with Negative Experience Learning (M4)."""

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..codegraph.index import GraphIndex
from ..codegraph.ranking import GraphRanker
from .adaptive_traversal import AdaptiveGraphTraversal
from .context_builder import AdaptiveContextBuilder
from .edge_scorer import DeterministicEdgeScorer
from .models import (
    AdaptiveRetrievalResult,
    ExperienceGraphConfig,
    ScoredEdge,
)
from .negative_overlay import NegativeGraphOverlay
from .overlay import ExperienceGraphOverlay


class AdaptiveGraphRetriever:
    """Performs deterministic, experience-conditioned repository graph retrieval with negative penalties."""

    def __init__(
        self,
        index: GraphIndex,
        overlay: Optional[ExperienceGraphOverlay] = None,
        negative_overlay: Optional[NegativeGraphOverlay] = None,
        config: Optional[ExperienceGraphConfig] = None,
    ):
        self.index = index
        self.overlay = overlay or ExperienceGraphOverlay()
        self.negative_overlay = negative_overlay or NegativeGraphOverlay()
        self.config = config or ExperienceGraphConfig()
        self.scorer = DeterministicEdgeScorer(config=self.config)
        self.traversal = AdaptiveGraphTraversal(
            index=self.index,
            overlay=self.overlay,
            negative_overlay=self.negative_overlay,
            scorer=self.scorer,
        )
        self.ranker = GraphRanker(index=self.index)

    def retrieve(
        self,
        task_text: str,
        task_category: str = "",
        repo_path: Optional[Path] = None,
        repo_version: str = "",
        failing_tests: Optional[List[str]] = None,
        config: Optional[ExperienceGraphConfig] = None,
    ) -> AdaptiveRetrievalResult:
        """Execute deterministic experience-guided retrieval pipeline with failure penalties."""
        start_time = time.perf_counter()
        cfg = config or self.config

        # Step 1: Task text tokens & candidate node ranking
        clean_text = task_text.replace("-", " ").replace(".", " ").replace("_", " ")
        tokens = set(re.findall(r"\b[A-Za-z0-9_]{3,}\b", clean_text.lower()))
        stop_words = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "will", "when"}
        tokens = {t for t in tokens if t not in stop_words}

        ranked_candidates = self.ranker.rank_candidates(
            task_text=task_text,
            failing_tests=failing_tests,
            top_k=cfg.max_nodes * 2,
        )

        if not ranked_candidates:
            for node in self.index.nodes.values():
                if node.node_type in ("class", "function", "method"):
                    d = node.to_dict()
                    d["relevance_score"] = 0.1
                    ranked_candidates.append(d)
                if len(ranked_candidates) >= cfg.max_nodes:
                    break

        candidate_center_ids = [c["node_id"] for c in ranked_candidates[:3]]

        # Step 2: Adaptive experience-guided traversal with penalties
        subgraph = self.traversal.experience_guided_subgraph(
            center_node_ids=candidate_center_ids,
            depth=cfg.expansion_depth,
            task_text=task_text,
            task_category=task_category,
            max_nodes=cfg.max_nodes,
            max_edges=cfg.max_edges,
            max_tests=cfg.max_tests,
            repo_path=repo_path,
            repo_version=repo_version,
        )

        selected_nodes: List[Dict[str, Any]] = subgraph["nodes"]
        scored_edges: List[ScoredEdge] = subgraph["edges"]
        test_items = subgraph["tests"]
        avoided_edges = subgraph.get("avoided_edges", [])

        associated_tests: List[Dict[str, Any]] = []
        for scored_e, t_dict in test_items:
            t_copy = dict(t_dict)
            t_copy["edge_score"] = scored_e.final_score
            associated_tests.append(t_copy)

        # Step 3: Extract relevant files and symbols
        files_set: Set[str] = set()
        for n in selected_nodes:
            p = n.get("path")
            if p and p.endswith(".py"):
                files_set.add(p)
        for t in associated_tests:
            p = t.get("path")
            if p and p.endswith(".py"):
                files_set.add(p)

        relevant_files = sorted(list(files_set))[: cfg.max_files]
        relevant_symbols = [n.get("symbol", "") for n in selected_nodes if n.get("symbol")]

        # Step 4: Metrics on positive reinforcement and negative penalties
        supported_edges: List[str] = []
        penalized_edges: List[str] = []
        for e in scored_edges:
            if e.experience_score > 0.0:
                supported_edges.append(e.edge_id)
            if e.negative_score > 0.0:
                penalized_edges.append(e.edge_id)

        edge_utilization = len(supported_edges) / max(1, len(scored_edges))
        selected_edges_dicts: List[Dict[str, Any]] = [e.to_dict() for e in scored_edges]

        # Step 5: Compact context formatting
        compact_context = AdaptiveContextBuilder.build_context(
            relevant_files=relevant_files,
            selected_nodes=selected_nodes,
            scored_edges=scored_edges,
            associated_tests=associated_tests,
            experience_supported_edges=supported_edges,
            penalized_edges=penalized_edges,
            include_raw_experience_text=cfg.enable_experience_text,
            max_chars=cfg.max_context_chars,
        )

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return AdaptiveRetrievalResult(
            query=task_text,
            candidate_nodes=ranked_candidates,
            selected_nodes=selected_nodes,
            selected_edges=selected_edges_dicts,
            scored_edges=scored_edges,
            relevant_files=relevant_files,
            relevant_symbols=relevant_symbols,
            associated_tests=associated_tests,
            experience_guided_edge_utilization=round(edge_utilization, 3),
            experience_supported_edges=supported_edges,
            penalized_edges=penalized_edges,
            negative_avoidance_count=len(avoided_edges),
            structural_experience_gain=0.0,
            compact_context=compact_context,
            latency_ms=latency_ms,
            traversal_log=subgraph.get("traversal_log", []),
            config=cfg.to_dict(),
        )
