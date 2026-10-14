"""Main autonomous software-engineering agent for LIFECORE-SWE."""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .state import AgentState
from .planner import PatchLoopPlanner
from .model_adapter import ModelAdapter, RuleBasedDevAdapter
from ..tools.filesystem import ControlledFileSystemTool
from ..tools.test_runner import TestRunnerTool
from ..tools.diff import DiffTool
from ..verification.verifier import Verifier
from ..trajectory.recorder import TrajectoryRecorder
from ..codegraph.builder import RepositoryGraphBuilder
from ..codegraph.index import GraphIndex
from ..codegraph.traversal import GraphTraversal
from ..codegraph.ranking import GraphRanker
from ..retrieval.graph_retriever import GraphRetriever
from ..retrieval.models import RetrievalConfig, RetrievalResult
import subprocess
from datetime import datetime, timezone
from ..experience.models import (
    ExperienceRecord,
    ExperienceRetrievalConfig,
    ExperienceRetrievalResult,
    VerificationStatus,
)
from ..experience.store import ExperienceStore
from ..experience.retriever import ExperienceRetriever
from ..experience_graph.models import (
    AdaptiveRetrievalResult,
    ExperienceGraphConfig,
    ExperienceEdgeStats,
    ScoredEdge,
)
from ..experience_graph.overlay import ExperienceGraphOverlay
from ..experience_graph.adaptive_retriever import AdaptiveGraphRetriever
from ..experience_graph.negative_overlay import NegativeGraphOverlay
from ..experience_graph.attributor import FailureAttributor
from ..resources.context_builder import ResourceContextBuilder, UnifiedWorldModelContextBuilder
from ..resources.graph.index import ResourceGraph
from ..resources.graph.retriever import (
    ResourceEvidenceItem,
    ResourceGraphRetriever,
    ResourceRetrievalConfig,
    ResourceRetrievalResult,
)


class SWEAgent:
    """Minimal, reproducible SWE agent solving controlled bugs in local repositories."""

    def __init__(
        self,
        repo_path: str,
        task_id: str = "M0.1-TASK-101",
        model_adapter: Optional[ModelAdapter] = None,
        trajectory_output: Optional[str] = None,
        trajectory_mode: Optional[str] = None,
        enable_graph: bool = False,
        enable_graph_guidance: bool = False,
        retrieval_config: Optional[RetrievalConfig] = None,
        retrieval_output: Optional[str] = None,
        expected_files: Optional[List[str]] = None,
        test_target: Optional[str] = None,
        enable_experience: bool = False,
        experience_store: Optional[ExperienceStore] = None,
        experience_config: Optional[ExperienceRetrievalConfig] = None,
        experience_output: Optional[str] = None,
        task_category: str = "bug_fix",
        store_experience_on_completion: bool = True,
        enable_experience_graph: bool = False,
        experience_graph_overlay: Optional[ExperienceGraphOverlay] = None,
        experience_graph_config: Optional[ExperienceGraphConfig] = None,
        include_raw_experience_text: bool = True,
        enable_negative_graph: bool = False,
        negative_graph_overlay: Optional[NegativeGraphOverlay] = None,
        store_negative_experience_on_failure: bool = True,
        condition: Optional[str] = None,
        enable_resource_graph: bool = False,
        resource_graph: Optional[ResourceGraph] = None,
        resource_retriever: Optional[ResourceGraphRetriever] = None,
        resource_retrieval_config: Optional[ResourceRetrievalConfig] = None,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.task_id = task_id
        self.model = model_adapter or RuleBasedDevAdapter()
        self.state = AgentState()
        self.planner = PatchLoopPlanner()
        self.enable_graph = enable_graph
        self.enable_graph_guidance = enable_graph_guidance
        self.retrieval_config = retrieval_config or RetrievalConfig()
        self.retrieval_output = retrieval_output

        # Tools restricted strictly to repo_path
        self.fs_tool = ControlledFileSystemTool(str(self.repo_path))
        self.test_tool = TestRunnerTool(str(self.repo_path))
        self.diff_tool = DiffTool(str(self.repo_path))
        self.test_target = test_target
        self.enable_experience = enable_experience
        self.experience_store = experience_store
        self.experience_config = experience_config or ExperienceRetrievalConfig()
        self.experience_output = experience_output
        self.task_category = task_category
        self.store_experience_on_completion = store_experience_on_completion
        self.experience_retriever = (
            ExperienceRetriever(self.experience_store) if self.experience_store else None
        )
        self.experience_result: Optional[ExperienceRetrievalResult] = None
        self.compact_experience_evidence: str = ""
        self.stored_experience_id: Optional[str] = None
        self.enable_experience_graph = enable_experience_graph
        self.experience_graph_overlay = experience_graph_overlay
        self.experience_graph_config = experience_graph_config or ExperienceGraphConfig()
        self.include_raw_experience_text = include_raw_experience_text
        self.enable_negative_graph = enable_negative_graph
        self.negative_graph_overlay = negative_graph_overlay
        self.store_negative_experience_on_failure = store_negative_experience_on_failure
        self.stored_negative_experience_ids: List[str] = []
        self.condition = condition
        self.enable_resource_graph = enable_resource_graph
        self.resource_graph = resource_graph
        self.resource_retriever = resource_retriever
        self.resource_retrieval_config = resource_retrieval_config or ResourceRetrievalConfig()
        self.resource_retrieval_result: Optional[ResourceRetrievalResult] = None
        self.compact_resource_evidence: str = ""
        self.adaptive_graph_retriever: Optional[AdaptiveGraphRetriever] = None
        self.adaptive_retrieval_result: Optional[AdaptiveRetrievalResult] = None
        exp_files = expected_files or ["event_processor/filters.py"]
        self.verifier = Verifier(str(self.repo_path), expected_files=exp_files, test_target=self.test_target)

        model_info = self.model.get_model_info()
        self.is_real_model = not model_info.get("is_development_adapter", False)
        if trajectory_mode:
            self.trajectory_mode = trajectory_mode
        elif self.enable_resource_graph or "M5" in task_id:
            self.trajectory_mode = "M5"
        elif self.enable_negative_graph or "M4" in task_id:
            self.trajectory_mode = "M4"
        elif self.enable_experience_graph or "M3" in task_id:
            self.trajectory_mode = "M3"
        elif self.enable_experience or "M2" in task_id:
            self.trajectory_mode = "M2"
        elif self.enable_graph_guidance or "M1C" in task_id:
            self.trajectory_mode = "M1C"
        elif self.enable_graph:
            self.trajectory_mode = "M1B"
        elif self.is_real_model:
            self.trajectory_mode = "M1A"
        else:
            self.trajectory_mode = "M0.1"

        default_traj = (
            f"/lifecore-swe/experiments/trajectories/{task_id.lower()}_trajectory.jsonl"
        )
        traj_path = trajectory_output or default_traj
        self.recorder = TrajectoryRecorder(task_id, traj_path)

        self.step_counter = 0
        self.tool_calls_count = 0
        self.search_count = 0
        self.test_runs_count = 0
        self.graph_queries_count = 0
        self.candidate_nodes_count = 0
        self.selected_nodes: List[str] = []
        self.files_modified: List[str] = []
        self.file_contents_cache: Dict[str, str] = {}
        self.compact_graph_evidence: str = ""
        self.retrieval_result: Optional[RetrievalResult] = None

        # Initialize repository graph components if needed
        self.graph_builder = None
        self.graph_index = None
        self.graph_traversal = None
        self.graph_ranker = None
        self.graph_retriever = None

        if self.enable_graph or self.enable_graph_guidance or self.enable_experience_graph:
            self._init_codegraph()

    def _init_codegraph(self) -> None:
        """Construct deterministic code graph for the repository."""
        self.graph_builder = RepositoryGraphBuilder(str(self.repo_path), repo_id=self.repo_path.name)
        nodes, edges = self.graph_builder.build()
        self.graph_index = GraphIndex(nodes, edges)
        self.graph_traversal = GraphTraversal(self.graph_index)
        self.graph_ranker = GraphRanker(self.graph_index)
        self.graph_retriever = GraphRetriever(self.graph_index)
        if self.enable_experience_graph:
            self.adaptive_graph_retriever = AdaptiveGraphRetriever(
                index=self.graph_index,
                overlay=self.experience_graph_overlay,
                negative_overlay=self.negative_graph_overlay if self.enable_negative_graph else None,
                config=self.experience_graph_config,
            )


    def _get_repo_version(self) -> str:
        """Get git commit hash or version identifier for repository."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return self.repo_path.name

    def _determine_experience_influence(self) -> str:
        """Classify how historical experience influenced current execution trajectory."""
        if not self.experience_result or not self.experience_result.selected_experiences:
            return "NONE"

        exp_files = set()
        for e in self.experience_result.selected_experiences:
            exp_files.update(f.lower() for f in e.files_modified + e.files_inspected)

        inspected = set(f.lower() for f in self.state.files_inspected)
        modified = set(f.lower() for f in self.files_modified)

        if any(st == "CONTRADICTED" for st in self.experience_result.stale_statuses.values()):
            return "CONTRADICTED"

        task_success = (
            self.state.verification is not None
            and self.state.verification.get("success", False)
        )

        if modified and modified.intersection(exp_files):
            return "VERIFIED_USEFUL" if task_success else "USED"
        elif inspected and inspected.intersection(exp_files):
            return "REFERENCED"
        elif not inspected.intersection(exp_files):
            return "IGNORED"
        return "RETRIEVED"

    def _format_compact_evidence(self, target_symbol: str, relationships: List[Dict[str, Any]]) -> str:
        """Format graph evidence into the compact human-readable representation."""
        lines = [f"Target:\n{target_symbol}\n", "Relationships:"]
        for r in relationships[:4]:
            source = r.get("source_symbol") or r.get("symbol", "Entity")
            rel = r.get("relationship", "REFERENCES")
            target = r.get("target_symbol") or target_symbol
            lines.append(f"\n{source}\n    {rel}\n{target}")
        return "\n".join(lines)

    def _record_adaptive_step(
        self,
        step_id: int,
        observation: Any,
        action: str,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        hypothesis_summary: Optional[str] = None,
        confidence: Optional[float] = None,
        files_read: Optional[List[str]] = None,
        files_modified: Optional[List[str]] = None,
        searches_count: int = 0,
        test_runs_count: int = 0,
        recovery_attempts: int = 0,
        test_result: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
    ):
        if self.trajectory_mode not in ("M3", "M4"):
            return
        model_name = self.model.get_model_info().get("model_name", "unknown")
        cand_nodes = [c.get("node_id", "") for c in (self.adaptive_retrieval_result.candidate_nodes[:10] if self.adaptive_retrieval_result else (self.retrieval_result.candidate_nodes[:10] if self.retrieval_result else []))]
        sel_nodes = [n.get("node_id", "") for n in (self.adaptive_retrieval_result.selected_nodes if self.adaptive_retrieval_result else (self.retrieval_result.selected_nodes if self.retrieval_result else []))]
        sel_edges = [e.get("edge_id", "") for e in (self.adaptive_retrieval_result.selected_edges if self.adaptive_retrieval_result else (self.retrieval_result.selected_edges if self.retrieval_result else []))]
        sc_edges = [e.to_dict() for e in self.adaptive_retrieval_result.scored_edges] if self.adaptive_retrieval_result else []
        rnk_scores = {c.get("node_id", ""): c.get("relevance_score", 0.0) for c in (self.adaptive_retrieval_result.candidate_nodes[:10] if self.adaptive_retrieval_result else (self.retrieval_result.candidate_nodes[:10] if self.retrieval_result else []))}
        exp_retrieved = [e.experience_id for e in self.experience_result.selected_experiences] if self.experience_result else []
        exp_scores = self.experience_result.ranking_scores if self.experience_result else {}
        exp_reasons = self.experience_result.selection_reasons if self.experience_result else {}
        exp_stale = self.experience_result.stale_statuses if self.experience_result else {}
        exp_context = self.compact_experience_evidence
        exp_util = self.adaptive_retrieval_result.experience_guided_edge_utilization if self.adaptive_retrieval_result else 0.0
        exp_edges = self.adaptive_retrieval_result.experience_supported_edges if self.adaptive_retrieval_result else []
        trav_log = self.adaptive_retrieval_result.traversal_log if self.adaptive_retrieval_result else []

        if self.trajectory_mode == "M4":
            cond = self.condition or ("POSITIVE_NEGATIVE_GRAPH" if self.include_raw_experience_text else "POSITIVE_NEGATIVE_GRAPH_NO_RAW_TEXT")
            penalized = self.adaptive_retrieval_result.penalized_edges if self.adaptive_retrieval_result else []
            neg_avoidance = self.adaptive_retrieval_result.negative_avoidance_count if self.adaptive_retrieval_result else 0
            neg_penalties = {e.edge_id: e.negative_score for e in self.adaptive_retrieval_result.scored_edges if e.negative_score > 0} if self.adaptive_retrieval_result else {}
            self.recorder.record_m4_step(
                model=model_name,
                task=self.task_id,
                condition=cond,
                repository_version=self._get_repo_version(),
                step_id=step_id,
                observation=observation,
                action=action,
                tool=tool,
                arguments=arguments,
                result=result,
                hypothesis_summary=hypothesis_summary,
                confidence=confidence,
                files_read=files_read or [],
                files_modified=files_modified or [],
                searches_count=searches_count,
                test_runs_count=test_runs_count,
                recovery_attempts=recovery_attempts,
                graph_retrieval_query=self.state.task if (self.enable_graph_guidance or self.enable_experience_graph) else "",
                candidate_nodes=cand_nodes,
                selected_nodes=sel_nodes,
                selected_edges=sel_edges,
                scored_edges=sc_edges,
                ranking_scores=rnk_scores,
                context_injected=self.compact_graph_evidence,
                experiences_retrieved=exp_retrieved,
                experience_scores=exp_scores,
                experience_reasons=exp_reasons,
                experience_stale_statuses=exp_stale,
                experience_context_injected=exp_context,
                experience_influence=self._determine_experience_influence(),
                experience_guided_edge_utilization=exp_util,
                experience_supported_edges=exp_edges,
                structural_experience_gain=exp_util,
                penalized_edges=penalized,
                negative_avoidance_count=neg_avoidance,
                negative_experiences_retrieved=self.stored_negative_experience_ids,
                negative_edge_penalties=neg_penalties,
                traversal_log=trav_log,
                test_result=test_result,
                verification=verification,
            )
        else:
            cond = "EXP_CONDITIONED_GRAPH" if self.include_raw_experience_text else "EXP_GRAPH_NO_TEXT"
            self.recorder.record_m3_step(
                model=model_name,
                task=self.task_id,
                condition=cond,
                repository_version=self._get_repo_version(),
                step_id=step_id,
                observation=observation,
                action=action,
                tool=tool,
                arguments=arguments,
                result=result,
                hypothesis_summary=hypothesis_summary,
                confidence=confidence,
                files_read=files_read or [],
                files_modified=files_modified or [],
                searches_count=searches_count,
                test_runs_count=test_runs_count,
                recovery_attempts=recovery_attempts,
                graph_retrieval_query=self.state.task if (self.enable_graph_guidance or self.enable_experience_graph) else "",
                candidate_nodes=cand_nodes,
                selected_nodes=sel_nodes,
                selected_edges=sel_edges,
                scored_edges=sc_edges,
                ranking_scores=rnk_scores,
                context_injected=self.compact_graph_evidence,
                experiences_retrieved=exp_retrieved,
                experience_scores=exp_scores,
                experience_reasons=exp_reasons,
                experience_stale_statuses=exp_stale,
                experience_context_injected=exp_context,
                experience_influence=self._determine_experience_influence(),
                experience_guided_edge_utilization=exp_util,
                experience_supported_edges=exp_edges,
                structural_experience_gain=exp_util,
                traversal_log=trav_log,
                test_result=test_result,
                verification=verification,
            )

    def run(self, task_description: Optional[str] = None) -> Dict[str, Any]:
        """Execute the autonomous SWE loop until completion or max attempts reached."""
        start_time = time.time()

        # Ingest task
        if not task_description:
            task_file = self.repo_path / "TASK.md"
            if task_file.exists():
                with open(task_file, "r", encoding="utf-8") as f:
                    task_description = f.read()
            else:
                task_description = "Unspecified software task."

        self.state.task = task_description
        self.state.current_phase = "INIT"

        last_test_output = ""
        current_test_result: Optional[Dict[str, Any]] = None
        current_verification: Optional[Dict[str, Any]] = None

        # Baseline check before modifications
        baseline_tests = self.test_tool.run_tests(test_target=self.test_target)
        self.test_runs_count += 1
        tests_before = {
            "passed": baseline_tests.get("passed", False),
            "summary": baseline_tests.get("summary", ""),
            "exit_code": baseline_tests.get("exit_code"),
        }

        # Step 0: Pre-reasoning Graph-Guided Retrieval (Adaptive M3 or Static M1C)
        if self.enable_experience_graph and self.adaptive_graph_retriever:
            self.adaptive_retrieval_result = self.adaptive_graph_retriever.retrieve(
                task_text=self.state.task,
                task_category=self.task_category,
                repo_path=self.repo_path,
                repo_version=self._get_repo_version(),
                config=self.experience_graph_config,
            )
            self.compact_graph_evidence = self.adaptive_retrieval_result.compact_context
            self.state.graph_evidence = self.compact_graph_evidence
            self.state.observations.append(self.compact_graph_evidence)

            self.retrieval_result = RetrievalResult(
                query=self.state.task,
                candidate_nodes=self.adaptive_retrieval_result.candidate_nodes,
                selected_nodes=self.adaptive_retrieval_result.selected_nodes,
                selected_edges=self.adaptive_retrieval_result.selected_edges,
                relevant_files=self.adaptive_retrieval_result.relevant_files,
                relevant_symbols=self.adaptive_retrieval_result.relevant_symbols,
                associated_tests=self.adaptive_retrieval_result.associated_tests,
                latency_ms=self.adaptive_retrieval_result.latency_ms,
                compact_context=self.compact_graph_evidence,
                config=self.experience_graph_config.to_dict(),
            )

            if self.retrieval_output:
                out_p = Path(self.retrieval_output)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                with open(out_p, "w", encoding="utf-8") as f:
                    json.dump(self.adaptive_retrieval_result.to_dict(), f, indent=2)

            if self.trajectory_mode in ("M3", "M4"):
                self._record_adaptive_step(
                    step_id=0,
                    observation="Deterministic pre-reasoning experience retrieval completed.",
                    action="experience_pre_retrieval",
                    tool="experience_retriever",
                    arguments={"query": self.state.task},
                    result={
                        "candidate_count": self.experience_result.candidate_count if self.experience_result else 0,
                        "selected_experiences": len(self.experience_result.selected_experiences) if self.experience_result else 0,
                        "latency_ms": self.experience_result.latency_ms if self.experience_result else 0.0,
                    },
                    hypothesis_summary="Verified episodic experience retrieved from prior tasks.",
                    confidence=1.0,
                    test_result=tests_before,
                )
        elif self.enable_graph_guidance and self.graph_retriever:
            self.retrieval_result = self.graph_retriever.retrieve(
                task_text=self.state.task,
                config=self.retrieval_config,
            )
            self.compact_graph_evidence = self.retrieval_result.compact_context
            self.state.graph_evidence = self.compact_graph_evidence
            self.state.observations.append(self.compact_graph_evidence)

            # Persist retrieval artifact if path specified
            if self.retrieval_output:
                out_p = Path(self.retrieval_output)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                with open(out_p, "w", encoding="utf-8") as f:
                    json.dump(self.retrieval_result.to_dict(), f, indent=2)

            # Record step 0 in trajectory
            if self.trajectory_mode in ("M3", "M4"):
                self._record_adaptive_step(
                    step_id=0,
                    observation="Deterministic pre-reasoning experience retrieval completed.",
                    action="experience_pre_retrieval",
                    tool="experience_retriever",
                    arguments={"query": self.state.task},
                    result={
                        "candidate_count": self.experience_result.candidate_count if self.experience_result else 0,
                        "selected_experiences": len(self.experience_result.selected_experiences) if self.experience_result else 0,
                        "latency_ms": self.experience_result.latency_ms if self.experience_result else 0.0,
                    },
                    hypothesis_summary="Verified episodic experience retrieved from prior tasks.",
                    confidence=1.0,
                    test_result=tests_before,
                )
            elif self.trajectory_mode == "M2":
                model_name = self.model.get_model_info().get("model_name", "unknown")
                cond = "GRAPH_EXPERIENCE" if (self.enable_graph_guidance and self.enable_experience) else ("GRAPH" if self.enable_graph_guidance else ("EXPERIENCE" if self.enable_experience else "STATELESS"))
                self.recorder.record_m2_step(
                    model=model_name,
                    task=self.task_id,
                    condition=cond,
                    repository_version=self._get_repo_version(),
                    step_id=0,
                    observation="Deterministic pre-reasoning graph-guided retrieval completed.",
                    action="graph_pre_retrieval",
                    tool="codegraph_retriever",
                    arguments={"query": self.state.task},
                    result={
                        "relevant_files": self.retrieval_result.relevant_files,
                        "relevant_symbols": self.retrieval_result.relevant_symbols,
                        "selected_nodes": len(self.retrieval_result.selected_nodes),
                        "selected_edges": len(self.retrieval_result.selected_edges),
                        "latency_ms": self.retrieval_result.latency_ms,
                    },
                    hypothesis_summary="Initial repository evidence extracted from graph.",
                    confidence=1.0,
                    files_read=[],
                    files_modified=[],
                    searches_count=0,
                    test_runs_count=self.test_runs_count,
                    recovery_attempts=0,
                    graph_retrieval_query=self.state.task,
                    candidate_nodes=[c.get("node_id", "") for c in self.retrieval_result.candidate_nodes[:10]],
                    selected_nodes=[n.get("node_id", "") for n in self.retrieval_result.selected_nodes],
                    selected_edges=[e.get("edge_id", "") for e in self.retrieval_result.selected_edges],
                    ranking_scores={c.get("node_id", ""): c.get("relevance_score", 0.0) for c in self.retrieval_result.candidate_nodes[:10]},
                    context_injected=self.retrieval_result.compact_context,
                    test_result=tests_before,
                    verification=None,
                )
            elif self.trajectory_mode == "M1C":
                model_name = self.model.get_model_info().get("model_name", "unknown")
                self.recorder.record_m1c_step(
                    model=model_name,
                    task=self.task_id,
                    condition="GRAPH_GUIDED",
                    repository_version=self.repo_path.name,
                    step_id=0,
                    observation="Deterministic pre-reasoning graph-guided retrieval completed.",
                    action="graph_pre_retrieval",
                    tool="codegraph_retriever",
                    arguments={"query": self.state.task},
                    result={
                        "relevant_files": self.retrieval_result.relevant_files,
                        "relevant_symbols": self.retrieval_result.relevant_symbols,
                        "selected_nodes": len(self.retrieval_result.selected_nodes),
                        "selected_edges": len(self.retrieval_result.selected_edges),
                        "latency_ms": self.retrieval_result.latency_ms,
                    },
                    hypothesis_summary="Initial repository evidence extracted from graph.",
                    confidence=1.0,
                    files_read=[],
                    files_modified=[],
                    searches_count=0,
                    test_runs_count=self.test_runs_count,
                    recovery_attempts=0,
                    graph_retrieval_query=self.state.task,
                    candidate_nodes=[c.get("node_id", "") for c in self.retrieval_result.candidate_nodes[:10]],
                    selected_nodes=[n.get("node_id", "") for n in self.retrieval_result.selected_nodes],
                    selected_edges=[e.get("edge_id", "") for e in self.retrieval_result.selected_edges],
                    ranking_scores={c.get("node_id", ""): c.get("relevance_score", 0.0) for c in self.retrieval_result.candidate_nodes[:10]},
                    context_injected=self.retrieval_result.compact_context,
                    test_result=tests_before,
                    verification=None,
                )


        # Step 0B: Pre-reasoning Experience Retrieval (Condition C in M2)
        if self.enable_experience and self.experience_retriever and self.include_raw_experience_text:
            g_files = self.retrieval_result.relevant_files if self.retrieval_result else []
            g_symbols = self.retrieval_result.relevant_symbols if self.retrieval_result else []
            self.experience_result = self.experience_retriever.retrieve(
                task_text=self.state.task,
                repo_path=str(self.repo_path),
                repo_id=self.repo_path.name,
                repo_version=self._get_repo_version(),
                graph_files=g_files,
                graph_symbols=g_symbols,
                config=self.experience_config,
            )
            self.compact_experience_evidence = self.experience_result.compact_context
            self.state.experience_context = self.compact_experience_evidence
            self.state.experiences_retrieved = [
                e.experience_id for e in self.experience_result.selected_experiences
            ]
            if self.compact_experience_evidence:
                self.state.observations.append(self.compact_experience_evidence)

            if self.experience_output:
                out_p = Path(self.experience_output)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                with open(out_p, "w", encoding="utf-8") as f:
                    json.dump(self.experience_result.to_dict(), f, indent=2)

            if self.trajectory_mode in ("M3", "M4"):
                self._record_adaptive_step(
                    step_id=self.step_counter,
                    observation=obs_text,
                    action=action,
                    tool=action,
                    arguments=args,
                    result=result,
                    hypothesis_summary=self.state.hypotheses[-1].get("thought_summary") if self.state.hypotheses else None,
                    confidence=self.state.hypotheses[-1].get("confidence") if self.state.hypotheses else None,
                    files_read=list(self.state.files_inspected),
                    files_modified=list(self.files_modified),
                    searches_count=self.search_count,
                    test_runs_count=self.test_runs_count,
                    recovery_attempts=self.state.recovery_attempts,
                    test_result=current_test_result,
                )
            elif self.trajectory_mode == "M2":
                model_name = self.model.get_model_info().get("model_name", "unknown")
                cond = "GRAPH_EXPERIENCE" if self.enable_graph_guidance else "EXPERIENCE"
                self.recorder.record_m2_step(
                    model=model_name,
                    task=self.task_id,
                    condition=cond,
                    repository_version=self._get_repo_version(),
                    step_id=0,
                    observation="Deterministic pre-reasoning experience retrieval completed.",
                    action="experience_pre_retrieval",
                    tool="experience_retriever",
                    arguments={"query": self.state.task},
                    result={
                        "candidate_count": self.experience_result.candidate_count if self.experience_result else 0,
                        "selected_experiences": len(self.experience_result.selected_experiences) if self.experience_result else 0,
                        "latency_ms": self.experience_result.latency_ms if self.experience_result else 0.0,
                    },
                    hypothesis_summary="Verified episodic experience retrieved from prior tasks.",
                    confidence=1.0,
                    files_read=[],
                    files_modified=[],
                    searches_count=0,
                    test_runs_count=self.test_runs_count,
                    recovery_attempts=0,
                    graph_retrieval_query=self.state.task if self.enable_graph_guidance else "",
                    candidate_nodes=[c.get("node_id", "") for c in self.retrieval_result.candidate_nodes[:10]] if self.retrieval_result else [],
                    selected_nodes=[n.get("node_id", "") for n in self.retrieval_result.selected_nodes] if self.retrieval_result else [],
                    selected_edges=[e.get("edge_id", "") for e in self.retrieval_result.selected_edges] if self.retrieval_result else [],
                    ranking_scores={c.get("node_id", ""): c.get("relevance_score", 0.0) for c in self.retrieval_result.candidate_nodes[:10]} if self.retrieval_result else {},
                    context_injected=self.compact_graph_evidence,
                    experiences_retrieved=self.state.experiences_retrieved,
                    experience_scores=self.experience_result.ranking_scores,
                    experience_reasons=self.experience_result.selection_reasons,
                    experience_stale_statuses=self.experience_result.stale_statuses,
                    experience_context_injected=self.compact_experience_evidence,
                    experience_influence="RETRIEVED",
                    test_result=tests_before,
                    verification=None,
                )

        # External Resource Retrieval (M5-D)
        if self.enable_resource_graph and self.resource_retriever:
            self.resource_retrieval_result = self.resource_retriever.retrieve(
                query_text=self.state.task,
                config=self.resource_retrieval_config,
            )
            prov_map = getattr(self.resource_retriever, "provenance_map", {})
            self.compact_resource_evidence = ResourceContextBuilder.build_resource_context(
                retrieval_result=self.resource_retrieval_result,
                provenance_map=prov_map,
            )
            self.state.observations.append(self.compact_resource_evidence)

        # Autonomous Loop
        max_loop_iterations = 10
        loop_iter = 0

        while self.state.current_phase not in ("COMPLETED", "STOPPED") and loop_iter < max_loop_iterations:
            loop_iter += 1

            state_dict = self.state.to_dict()
            state_dict["inspected_contents"] = self.file_contents_cache
            state_dict["last_test_output"] = last_test_output
            state_dict["graph_evidence"] = self.compact_graph_evidence
            state_dict["experience_context"] = self.compact_experience_evidence
            state_dict["resource_context"] = self.compact_resource_evidence
            state_dict["resource_evidence"] = self.compact_resource_evidence

            if hasattr(self.model, "select_action") and "enable_graph" in self.model.select_action.__code__.co_varnames:
                action_desc = self.model.select_action(state_dict, enable_graph=self.enable_graph)
            else:
                action_desc = self.model.select_action(state_dict)

            action = action_desc.get("action", "stop")
            tool_name = action_desc.get("tool", "none")
            args = action_desc.get("arguments", {})
            thought_summary = action_desc.get("thought_summary", "")
            hyp_summary = action_desc.get("hypothesis", "")
            step_confidence = action_desc.get("confidence", 0.8)
            reason_for_graph_query = action_desc.get("reason_for_graph_query", "")

            self.step_counter += 1
            result = None
            step_graph_queries: List[Dict[str, Any]] = []
            step_nodes_returned: List[str] = []
            step_edges_returned: List[str] = []
            step_nodes_selected: List[str] = []
            step_nodes_rejected: List[str] = []

            # 1. Graph Tools
            if action == "graph_search" and self.graph_traversal:
                self.tool_calls_count += 1
                self.graph_queries_count += 1
                query = args.get("query", "")
                nodes = self.graph_traversal.search_subgraph(query)
                self.candidate_nodes_count += len(nodes)
                step_nodes_returned = [n["node_id"] for n in nodes]
                step_graph_queries.append({"query": query, "type": "graph_search", "count": len(nodes)})
                result = nodes[:5]

                if nodes:
                    top_node = nodes[0]
                    self.selected_nodes.append(top_node["node_id"])
                    step_nodes_selected.append(top_node["node_id"])
                    step_nodes_rejected.extend([n["node_id"] for n in nodes[1:5]])
                    callers = self.graph_traversal.find_callers(top_node["node_id"])
                    tests = self.graph_traversal.find_tests(top_node["node_id"])
                    rels = []
                    for c in callers:
                        rels.append({"source_symbol": c["symbol"], "relationship": "CALLS", "target_symbol": top_node["symbol"]})
                    for t in tests:
                        rels.append({"source_symbol": t["symbol"], "relationship": "TESTS", "target_symbol": top_node["symbol"]})
                    self.compact_graph_evidence = self._format_compact_evidence(top_node["symbol"], rels)

                obs = f"Graph search '{query}' returned {len(nodes)} nodes. Top match: {nodes[0]['symbol'] if nodes else 'None'}"
                self.state.observations.append(obs)

            elif action == "graph_find_symbol" and self.graph_traversal:
                self.tool_calls_count += 1
                self.graph_queries_count += 1
                sym = args.get("symbol", "")
                nodes = self.graph_traversal.find_symbol(sym)
                self.candidate_nodes_count += len(nodes)
                step_nodes_returned = [n["node_id"] for n in nodes]
                step_graph_queries.append({"symbol": sym, "type": "graph_find_symbol", "count": len(nodes)})
                result = nodes

                if nodes:
                    top_node = nodes[0]
                    self.selected_nodes.append(top_node["node_id"])
                    step_nodes_selected.append(top_node["node_id"])
                    step_nodes_rejected.extend([n["node_id"] for n in nodes[1:]])
                    callers = self.graph_traversal.find_callers(top_node["node_id"])
                    tests = self.graph_traversal.find_tests(top_node["node_id"])
                    rels = []
                    for c in callers:
                        rels.append({"source_symbol": c["symbol"], "relationship": "CALLS", "target_symbol": top_node["symbol"]})
                    for t in tests:
                        rels.append({"source_symbol": t["symbol"], "relationship": "TESTS", "target_symbol": top_node["symbol"]})
                    self.compact_graph_evidence = self._format_compact_evidence(top_node["symbol"], rels)

                obs = f"Graph symbol search for '{sym}' resolved to {len(nodes)} entities."
                self.state.observations.append(obs)

            elif action == "graph_find_tests" and self.graph_traversal:
                self.tool_calls_count += 1
                self.graph_queries_count += 1
                node_id = args.get("node_id", "")
                tests = self.graph_traversal.find_tests(node_id)
                step_nodes_returned = [t["node_id"] for t in tests]
                step_graph_queries.append({"node_id": node_id, "type": "graph_find_tests", "count": len(tests)})
                result = tests
                obs = f"Graph tests query for '{node_id}' found {len(tests)} associated test cases."
                self.state.observations.append(obs)

            elif action == "graph_neighbors" and self.graph_traversal:
                self.tool_calls_count += 1
                self.graph_queries_count += 1
                node_id = args.get("node_id", "")
                nbrs = self.graph_traversal.neighbors(node_id)
                self.candidate_nodes_count += len(nbrs)
                step_nodes_returned = [n["node_id"] for n in nbrs]
                step_graph_queries.append({"node_id": node_id, "type": "graph_neighbors", "count": len(nbrs)})
                result = nbrs
                obs = f"Graph neighbors query for '{node_id}' returned {len(nbrs)} connected entities."
                self.state.observations.append(obs)

            elif action == "graph_subgraph" and self.graph_traversal:
                self.tool_calls_count += 1
                self.graph_queries_count += 1
                node_id = args.get("node_id", "")
                depth = int(args.get("depth", 1))
                sub = self.graph_traversal.subgraph(node_id, depth=depth)
                step_nodes_returned = [n["node_id"] for n in sub["nodes"]]
                step_edges_returned = [e["edge_id"] for e in sub["edges"]]
                step_graph_queries.append({"node_id": node_id, "type": "graph_subgraph", "depth": depth})
                result = sub
                obs = f"Extracted {depth}-hop subgraph around '{node_id}' ({len(sub['nodes'])} nodes, {len(sub['edges'])} edges)."
                self.state.observations.append(obs)

            # 2. Filesystem & Standard Tools
            elif action == "list_files":
                self.tool_calls_count += 1
                files = self.fs_tool.list_files()
                result = files
                obs = f"Listed {len(files)} files in repository: {', '.join(files[:8])}"
                self.state.observations.append(obs)

            elif action == "search_text":
                self.tool_calls_count += 1
                self.search_count += 1
                q = args.get("query", "")
                matches = self.fs_tool.search_text(q)
                result = matches
                self.state.searches.append({"query": q, "matches_count": len(matches)})
                obs = f"Search for '{q}' returned {len(matches)} matches."
                self.state.observations.append(obs)

            elif action == "search_symbol":
                self.tool_calls_count += 1
                self.search_count += 1
                sym = args.get("symbol", "")
                matches = self.fs_tool.search_symbol(sym)
                result = matches
                self.state.searches.append({"symbol": sym, "matches_count": len(matches)})
                obs = f"Symbol search for '{sym}' returned {len(matches)} matches."
                self.state.observations.append(obs)

            elif action == "read_file":
                self.tool_calls_count += 1
                path = args.get("path", "")
                try:
                    content = self.fs_tool.read_file(path)
                    result = f"Read {len(content.splitlines())} lines from {path}."
                    self.file_contents_cache[path] = content
                    if path not in self.state.files_inspected:
                        self.state.files_inspected.append(path)
                    obs = f"Inspected file {path} ({len(content.splitlines())} lines)."
                except Exception as e:
                    result = f"Error reading {path}: {e}"
                    obs = result
                self.state.observations.append(obs)

            elif action in ("formulate_hypothesis", "recover"):
                is_recovery = (action == "recover")
                context = {
                    "phase": "RECOVERY" if is_recovery else "INITIAL",
                    "test_failure": last_test_output,
                    "inspected_files": self.file_contents_cache,
                    "graph_evidence": self.compact_graph_evidence,
                    "resource_evidence": self.compact_resource_evidence,
                }
                hyp = self.model.reason(self.state.task, context)
                step_confidence = hyp.get("confidence", step_confidence)
                self.state.hypotheses.append(hyp)
                result = hyp
                if is_recovery:
                    self.state.recovery_attempts += 1
                    obs = f"Formulated recovery hypothesis #{self.state.recovery_attempts}: {hyp.get('suspected_cause', hyp_summary)}"
                else:
                    obs = f"Formulated hypothesis: {hyp.get('suspected_cause', hyp_summary)}"
                self.state.observations.append(obs)

            elif action == "modify_code":
                self.tool_calls_count += 1
                self.state.patch_attempts += 1
                path = args.get("path", "")
                old_str = args.get("old_str", "")
                new_str = args.get("new_str", "")
                success = self.fs_tool.replace_in_file(path, old_str, new_str)
                if path not in self.files_modified:
                    self.files_modified.append(path)
                if success:
                    try:
                        self.file_contents_cache[path] = self.fs_tool.read_file(path)
                    except Exception:
                        pass
                result = {"success": success, "file": path, "attempt": self.state.patch_attempts}
                self.state.actions.append({"action": "modify_code", "file": path, "attempt": self.state.patch_attempts, "success": success})
                obs = f"Applied code modification attempt #{self.state.patch_attempts} to {path} (success: {success})."
                self.state.observations.append(obs)

                # Test execution following patch
                self.tool_calls_count += 1
                self.test_runs_count += 1
                test_res = self.test_tool.run_tests(test_target=self.test_target)
                current_test_result = test_res
                last_test_output = test_res.get("stdout", "")
                self.state.test_results.append({
                    "attempt": self.state.patch_attempts,
                    "passed": test_res.get("passed", False),
                    "summary": test_res.get("summary", ""),
                })
                if not test_res.get("passed", False):
                    self.state.failures.append({
                        "attempt": self.state.patch_attempts,
                        "summary": test_res.get("summary", ""),
                        "output": test_res.get("stdout", ""),
                    })
                    self.state.observations.append(f"Post-patch tests failed: {test_res.get('summary')}")
                else:
                    self.state.failures = []
                    self.state.current_phase = "VERIFY"
                    self.state.observations.append(f"Post-patch tests PASSED: {test_res.get('summary')}. Ready for verification.")

            elif action == "write_file":
                self.tool_calls_count += 1
                self.state.patch_attempts += 1
                path = args.get("path", "")
                content = args.get("content", "")
                if path not in self.files_modified:
                    self.files_modified.append(path)
                try:
                    self.fs_tool.write_file(path, content)
                    self.file_contents_cache[path] = content
                    success = True
                except Exception:
                    success = False
                result = {"success": success, "file": path, "attempt": self.state.patch_attempts}
                self.state.actions.append({"action": "write_file", "file": path, "attempt": self.state.patch_attempts, "success": success})
                obs = f"Wrote file attempt #{self.state.patch_attempts} to {path} (success: {success})."
                self.state.observations.append(obs)

                # Test execution following write
                self.tool_calls_count += 1
                self.test_runs_count += 1
                test_res = self.test_tool.run_tests(test_target=self.test_target)
                current_test_result = test_res
                last_test_output = test_res.get("stdout", "")
                self.state.test_results.append({
                    "attempt": self.state.patch_attempts,
                    "passed": test_res.get("passed", False),
                    "summary": test_res.get("summary", ""),
                })
                if not test_res.get("passed", False):
                    self.state.failures.append({
                        "attempt": self.state.patch_attempts,
                        "summary": test_res.get("summary", ""),
                        "output": test_res.get("stdout", ""),
                    })
                    self.state.observations.append(f"Post-write tests failed: {test_res.get('summary')}")
                else:
                    self.state.failures = []
                    self.state.current_phase = "VERIFY"
                    self.state.observations.append(f"Post-write tests PASSED: {test_res.get('summary')}. Ready for verification.")

            elif action == "run_tests":
                self.tool_calls_count += 1
                self.test_runs_count += 1
                test_res = self.test_tool.run_tests(test_target=self.test_target)
                result = test_res
                current_test_result = test_res
                last_test_output = test_res.get("stdout", "")
                self.state.test_results.append({
                    "attempt": self.state.patch_attempts,
                    "passed": test_res.get("passed", False),
                    "summary": test_res.get("summary", ""),
                })
                if not test_res.get("passed", False):
                    self.state.failures.append({
                        "attempt": self.state.patch_attempts,
                        "summary": test_res.get("summary", ""),
                        "output": test_res.get("stdout", ""),
                    })
                    obs = f"Test run failed: {test_res.get('summary')}"
                else:
                    self.state.failures = []
                    self.state.current_phase = "VERIFY"
                    obs = f"Test run passed: {test_res.get('summary')}. Ready for verification."
                    result["passed"] = True
                self.state.observations.append(obs)

            elif action == "verify":
                self.tool_calls_count += 1
                v_res = self.verifier.verify()
                result = v_res
                current_verification = v_res
                self.state.verification = v_res
                obs = f"Verification completed with status: {v_res.get('status')}"
                self.state.observations.append(obs)
                if v_res.get("success", False):
                    self.state.current_phase = "COMPLETED"

            elif action == "stop":
                result = "Agent stopped."
                obs = f"Agent stopped: {args.get('reason', 'completed')}"
                self.state.observations.append(obs)
                self.state.current_phase = "STOPPED"

            # Record step in trajectory
            obs_text = self.state.observations[-1] if self.state.observations else ""
            # Record step in trajectory
            obs_text = self.state.observations[-1] if self.state.observations else ""
            if self.trajectory_mode in ("M3", "M4"):
                self._record_adaptive_step(
                    step_id=self.step_counter,
                    observation=obs_text,
                    action=action,
                    tool=tool_name,
                    arguments=args,
                    result=result,
                    hypothesis_summary=hyp_summary or thought_summary,
                    confidence=step_confidence,
                    files_read=list(self.state.files_inspected),
                    files_modified=list(self.files_modified),
                    searches_count=self.search_count,
                    test_runs_count=self.test_runs_count,
                    recovery_attempts=self.state.recovery_attempts,
                    test_result=current_test_result,
                )

        # Determine final status
        tests_after = self.test_tool.run_tests(test_target=self.test_target)
        verification = self.verifier.verify()
        self.state.verification = verification
        task_success = verification.get("success", False)
        final_status = "SUCCESS" if task_success else "FAILED"
        files_changed = self.diff_tool.get_modified_files()
        failure_reason = None
        if not task_success:
            if self.state.verification:
                failure_reason = "; ".join(self.state.verification.get("failure_reasons", []))
            else:
                failure_reason = "Verification did not execute or failed."

        # Terminal record
        if self.trajectory_mode in ("M3", "M4"):
            self._record_adaptive_step(
                step_id=self.step_counter + 1,
                observation=f"Task terminated with status {final_status}.",
                action="finalize_trajectory",
                tool="none",
                arguments={},
                result={"final_status": final_status, "patch_applied": len(self.state.final_patch.strip()) > 0},
                hypothesis_summary="Final evaluation, containment check, and task completion verified.",
                confidence=1.0 if task_success else 0.0,
                files_read=list(self.state.files_inspected),
                files_modified=list(self.files_modified),
                searches_count=self.search_count,
                test_runs_count=self.test_runs_count,
                recovery_attempts=self.state.recovery_attempts,
                test_result=tests_after,
                verification=self.state.verification,
            )
        elif self.trajectory_mode == "M2":
            model_name = self.model.get_model_info().get("model_name", "unknown")
            cond = "GRAPH_EXPERIENCE" if (self.enable_graph_guidance and self.enable_experience) else ("GRAPH" if self.enable_graph_guidance else ("EXPERIENCE" if self.enable_experience else "STATELESS"))
            self.recorder.record_m2_step(
                model=model_name,
                task=self.task_id,
                condition=cond,
                repository_version=self._get_repo_version(),
                step_id=self.step_counter + 1,
                observation=f"Task terminated with status {final_status}.",
                action="finalize_trajectory",
                tool="none",
                arguments={},
                result={"final_status": final_status, "patch_applied": len(self.state.final_patch.strip()) > 0},
                hypothesis_summary="Final evaluation, containment check, and task completion verified.",
                confidence=1.0 if task_success else 0.0,
                files_read=list(self.state.files_inspected),
                files_modified=list(self.files_modified),
                searches_count=self.search_count,
                test_runs_count=self.test_runs_count,
                recovery_attempts=self.state.recovery_attempts,
                graph_retrieval_query=self.state.task if self.enable_graph_guidance else "",
                candidate_nodes=[c.get("node_id", "") for c in self.retrieval_result.candidate_nodes[:10]] if self.retrieval_result else [],
                selected_nodes=[n.get("node_id", "") for n in self.retrieval_result.selected_nodes] if self.retrieval_result else [],
                selected_edges=[e.get("edge_id", "") for e in self.retrieval_result.selected_edges] if self.retrieval_result else [],
                ranking_scores={c.get("node_id", ""): c.get("relevance_score", 0.0) for c in self.retrieval_result.candidate_nodes[:10]} if self.retrieval_result else {},
                context_injected=self.compact_graph_evidence,
                experiences_retrieved=[e.experience_id for e in self.experience_result.selected_experiences] if self.experience_result else [],
                experience_scores=self.experience_result.ranking_scores if self.experience_result else {},
                experience_reasons=self.experience_result.selection_reasons if self.experience_result else {},
                experience_stale_statuses=self.experience_result.stale_statuses if self.experience_result else {},
                experience_context_injected=self.compact_experience_evidence,
                experience_influence=self._determine_experience_influence(),
                test_result=tests_after,
                verification=self.state.verification,
            )
        elif self.trajectory_mode == "M1C":
            model_name = self.model.get_model_info().get("model_name", "unknown")
            cond = "GRAPH_GUIDED" if self.enable_graph_guidance else "BASELINE"
            self.recorder.record_m1c_step(
                model=model_name,
                task=self.task_id,
                condition=cond,
                repository_version=self.repo_path.name,
                step_id=self.step_counter + 1,
                observation=f"Task terminated with status {final_status}.",
                action="finalize_trajectory",
                tool="none",
                arguments={},
                result={"final_status": final_status, "patch_applied": len(self.state.final_patch.strip()) > 0},
                hypothesis_summary="Final evaluation, containment check, and task completion verified.",
                confidence=1.0 if task_success else 0.0,
                files_read=list(self.state.files_inspected),
                files_modified=list(self.files_modified),
                searches_count=self.search_count,
                test_runs_count=self.test_runs_count,
                recovery_attempts=self.state.recovery_attempts,
                graph_retrieval_query=self.state.task if self.enable_graph_guidance else "",
                candidate_nodes=[c.get("node_id", "") for c in self.retrieval_result.candidate_nodes[:10]] if self.retrieval_result else [],
                selected_nodes=[n.get("node_id", "") for n in self.retrieval_result.selected_nodes] if self.retrieval_result else [],
                selected_edges=[e.get("edge_id", "") for e in self.retrieval_result.selected_edges] if self.retrieval_result else [],
                ranking_scores={c.get("node_id", ""): c.get("relevance_score", 0.0) for c in self.retrieval_result.candidate_nodes[:10]} if self.retrieval_result else {},
                context_injected=self.compact_graph_evidence,
                test_result=tests_after,
                verification=self.state.verification,
            )
        elif self.trajectory_mode == "M1B":
            model_name = self.model.get_model_info().get("model_name", "unknown")
            self.recorder.record_m1b_step(
                model=model_name,
                task=self.task_id,
                observation=f"Task terminated with status {final_status}.",
                action="finalize_trajectory",
                tool="none",
                arguments={},
                result={"final_status": final_status, "patch_applied": len(self.state.final_patch.strip()) > 0},
                hypothesis_summary="Final evaluation, containment check, and graph localization complete.",
                confidence=1.0 if task_success else 0.0,
                graph_queries=[],
                graph_nodes_returned=[],
                graph_edges_returned=[],
                graph_nodes_selected=self.selected_nodes,
                graph_nodes_rejected=[],
                reason_for_graph_query="",
                test_result=tests_after,
                verification=self.state.verification,
            )
        elif self.trajectory_mode == "M1A":
            model_name = self.model.get_model_info().get("model_name", "unknown")
            self.recorder.record_m1a_step(
                model=model_name,
                task=self.task_id,
                observation=f"Task terminated with status {final_status}.",
                action="finalize_trajectory",
                tool="none",
                arguments={},
                result={"final_status": final_status, "patch_applied": len(self.state.final_patch.strip()) > 0},
                hypothesis_summary="Final evaluation and containment check complete.",
                confidence=1.0 if task_success else 0.0,
                test_result=tests_after,
                verification=self.state.verification,
            )
        else:
            self.recorder.record_final(
                final_status=final_status,
                patch=self.state.final_patch,
                tests=tests_after,
                verification=self.state.verification or {},
                failure_reason=failure_reason,
                files_changed=files_changed,
            )


        # M2: Store verified experience in persistent store
        if self.store_experience_on_completion and self.experience_store:
            exp_id = f"EXP-{self.task_id}-{int(time.time())}"
            file_hashes = {}
            for fpath in list(set(self.files_modified + self.state.files_inspected)):
                full_p = self.repo_path / fpath
                if full_p.exists() and full_p.is_file():
                    file_hashes[fpath] = ExperienceRecord.compute_file_hash(full_p)

            hyp_str = ""
            if self.state.hypotheses:
                hyp_str = self.state.hypotheses[-1].get("hypothesis") or self.state.hypotheses[-1].get("thought_summary", "")

            status_val = VerificationStatus.VERIFIED.value if task_success else VerificationStatus.FAILED.value
            exp_rec = ExperienceRecord(
                experience_id=exp_id,
                task_id=self.task_id,
                repository_id=self.repo_path.name,
                repository_version=self._get_repo_version(),
                task_description=self.state.task,
                task_category=self.task_category,
                relevant_nodes=[n.get("node_id", "") for n in (self.retrieval_result.selected_nodes if self.retrieval_result else [])],
                relevant_edges=[e.get("edge_id", "") for e in (self.retrieval_result.selected_edges if self.retrieval_result else [])],
                files_inspected=list(self.state.files_inspected),
                files_modified=list(self.files_modified),
                symbols_modified=[],
                hypothesis=hyp_str,
                actions=[{"step": s.get("step_id"), "action": s.get("action"), "tool": s.get("tool")} for s in self.recorder.steps[:10]],
                observations=self.state.observations[-3:],
                patch_summary=f"Modified {len(files_changed)} file(s): {', '.join(files_changed)}" if files_changed else "",
                final_patch=self.state.final_patch,
                tests_run=[{"summary": tests_after.get("summary", ""), "passed": tests_after.get("passed", False)}],
                verification_result=self.state.verification or {},
                success=task_success,
                failure_reason=failure_reason,
                recovery_attempts=self.state.recovery_attempts,
                tool_usage={"tool_calls": self.tool_calls_count, "searches": self.search_count, "test_runs": self.test_runs_count},
                confidence=1.0 if task_success else 0.5,
                timestamp=datetime.now(timezone.utc).isoformat(),
                provenance={
                    "trajectory_file": str(self.recorder.output_path),
                    "model": self.model.get_model_info().get("model_name", "unknown"),
                    "git_commit": self._get_repo_version(),
                },
                verification_status=status_val,
                file_hashes=file_hashes,
            )
            if self.experience_store:
                self.experience_store.insert(exp_rec)
                self.stored_experience_id = exp_id

            # M3: Update experience overlay if enabled and verified
            if self.experience_graph_overlay and task_success and self.graph_index:
                # Extract modified symbols
                extracted_symbols = set()
                for fpath in files_changed:
                    for node in self.graph_index.find_by_path(fpath):
                        if node.node_type in ("function", "method", "class"):
                            if node.symbol and node.symbol in self.state.final_patch:
                                extracted_symbols.add(node.symbol)
                exp_rec.symbols_modified = list(extracted_symbols)
                self.experience_graph_overlay.update_from_experience(exp_rec, self.graph_index)

        # M4: Negative experience learning on failure
        if self.store_negative_experience_on_failure and not task_success and self.negative_graph_overlay:
            try:
                neg_records = FailureAttributor.analyze_failure(
                    task_id=self.task_id,
                    task_description=self.state.task,
                    task_category=self.task_category,
                    repo_path=self.repo_path,
                    repo_version=repo_version,
                    files_inspected=list(self.state.files_inspected),
                    files_modified=files_changed,
                    hypotheses=self.state.hypotheses,
                    actions=self.state.actions_taken,
                    test_results=[{"summary": "Verification or test failure", "output": str(self.state.test_history[-1]) if self.state.test_history else ""}],
                    verification=verification,
                    graph_index=self.graph_index if self.graph_index else None,
                    file_hashes=file_hashes,
                    tool_calls_count=self.tool_calls_count,
                    max_loop_iterations=self.planner.max_iterations,
                )
                for neg_rec in neg_records:
                    self.negative_graph_overlay.update_from_negative_experience(neg_rec, self.graph_index)
                    self.stored_negative_experience_ids.append(neg_rec.experience_id)
            except Exception as e:
                pass

        execution_time = round(time.time() - start_time, 3)

        # Documented repository localization efficiency:
        target_files = set(self.verifier.expected_files)
        inspected_set = set(self.state.files_inspected)
        efficiency = (
            len(target_files.intersection(inspected_set)) / len(inspected_set)
            if inspected_set
            else 0.0
        )

        metrics = {
            "task_success": task_success,
            "patch_applied": len(self.state.final_patch.strip()) > 0,
            "patch_correctness": task_success and len(self.state.final_patch.strip()) > 0,
            "tests_before": tests_before,
            "tests_after": tests_after,
            "test_passed": tests_after["passed"],
            "files_inspected": list(self.state.files_inspected),
            "files_read": len(self.state.files_inspected),
            "search_count": self.search_count,
            "tool_calls": self.tool_calls_count,
            "test_runs": self.test_runs_count,
            "graph_queries": self.graph_queries_count,
            "graph_nodes_retrieved": len(self.retrieval_result.selected_nodes) if self.retrieval_result else 0,
            "graph_edges_retrieved": len(self.retrieval_result.selected_edges) if self.retrieval_result else 0,
            "candidate_nodes": self.candidate_nodes_count,
            "selected_nodes": len(self.selected_nodes),
            "patch_attempts": self.state.patch_attempts,
            "recovery_attempts": self.state.recovery_attempts,
            "repository_localization_efficiency": round(efficiency, 3),
            "execution_time": execution_time,
            "verification_status": self.state.verification.get("status") if self.state.verification else "NOT_VERIFIED",
            "experiences_retrieved": [e.experience_id for e in self.experience_result.selected_experiences] if self.experience_result else [],
            "experience_count": len(self.experience_result.selected_experiences) if self.experience_result else 0,
            "experience_stored": self.stored_experience_id,
            "experience_influence": self._determine_experience_influence(),
            "experience_stale_count": sum(1 for st in (self.experience_result.stale_statuses.values() if self.experience_result else []) if st != "VALID"),
            "experience_guided_edge_utilization": self.adaptive_retrieval_result.experience_guided_edge_utilization if self.adaptive_retrieval_result else 0.0,
            "experience_supported_edges": self.adaptive_retrieval_result.experience_supported_edges if self.adaptive_retrieval_result else [],
            "experience_edges_count": len(self.adaptive_retrieval_result.experience_supported_edges) if self.adaptive_retrieval_result else 0,
            "penalized_edges": self.adaptive_retrieval_result.penalized_edges if self.adaptive_retrieval_result else [],
            "penalized_edges_count": len(self.adaptive_retrieval_result.penalized_edges) if self.adaptive_retrieval_result else 0,
            "negative_avoidance_count": self.adaptive_retrieval_result.negative_avoidance_count if self.adaptive_retrieval_result else 0,
            "stored_negative_experience_ids": self.stored_negative_experience_ids,
        }

        return {
            "status": final_status,
            "metrics": metrics,
            "state": self.state.to_dict(),
            "trajectory_file": str(self.recorder.output_path),
            "model_info": self.model.get_model_info(),
            "retrieval_result": self.retrieval_result.to_dict() if self.retrieval_result else None,
            "experience_result": self.experience_result.to_dict() if self.experience_result else None,
            "resource_result": self.resource_retrieval_result.to_dict() if self.resource_retrieval_result else None,
            "resource_evidence": self.compact_resource_evidence if self.enable_resource_graph else None,
        }
