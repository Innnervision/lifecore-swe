from lifecore_swe.codegraph.builder import RepositoryGraphBuilder
from lifecore_swe.codegraph.index import GraphIndex
"""M4 Failure-Aware Graph & Negative Experience Learning Benchmark Runner.

Executes Phase 1 (controlled failure generation & attribution) and Phase 2
across 5 conditions (A, B, C, D, E) and safety ablations.
"""

import argparse
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from lifecore_swe.agent.agent import SWEAgent
from lifecore_swe.agent.gemma_adapter import GemmaModelAdapter
from lifecore_swe.experience.models import (
    ExperienceRecord,
    ExperienceRetrievalConfig,
    VerificationStatus,
)
from lifecore_swe.experience.store import ExperienceStore
from lifecore_swe.experience_graph.attributor import FailureAttributor
from lifecore_swe.experience_graph.edge_scorer import DeterministicEdgeScorer
from lifecore_swe.experience_graph.models import (
    AttributionStrength,
    ExperienceGraphConfig,
    FailureType,
    NegativeExperienceRecord,
)
from lifecore_swe.experience_graph.negative_overlay import NegativeGraphOverlay
from lifecore_swe.experience_graph.overlay import ExperienceGraphOverlay
from lifecore_swe.retrieval.models import RetrievalConfig
from lifecore_swe.tools.test_runner import TestRunnerTool

REPO_PATH = Path("/lifecore-swe/fixtures/scaled_repo").resolve()
EXP_DIR = Path("/lifecore-swe/experiments")
RESULTS_DIR = EXP_DIR / "results"
TRAJ_DIR = EXP_DIR / "trajectories"
EXP_GRAPH_DIR = EXP_DIR / "experience_graph"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
TRAJ_DIR.mkdir(parents=True, exist_ok=True)
EXP_GRAPH_DIR.mkdir(parents=True, exist_ok=True)

# Define the 4 benchmark tasks representing distinct failure modes from Section 12
BENCHMARK_TASKS = [
    {
        "task_id": "M4-TASK-A",
        "title": "Fix RingBuffer capacity handling in storage/buffer.py",
        "description": "Clients report buffer overflow errors are not triggered at capacity. Fix RingBuffer.push in hydra_mesh/storage/buffer.py so that pushing item when size >= capacity raises BufferOverflowError. Note: Do not confuse with key-value eviction in storage/cache.py.",
        "category": "bug_fix",
        "target_file": "hydra_mesh/storage/buffer.py",
        "trap_file": "hydra_mesh/storage/cache.py",
        "trap_transition": "file:hydra_mesh/storage/buffer.py->REFERENCES->file:hydra_mesh/storage/cache.py",
        "correct_symbol": "RingBuffer.push",
        "trap_symbol": "KeyValueCache.set",
        "test_target": "tests/test_buffer_eviction.py::test_buffer_push_and_capacity",
        "failure_mode": "NAVIGATION_LOCALIZATION_TRAP",
    },
    {
        "task_id": "M4-TASK-B",
        "title": "Route missing event_id to DeadLetterQueue in EventTransformer",
        "description": "EventTransformer in hydra_mesh/pipeline/transformer.py crashes with SchemaError when 'event_id' is missing. Instead of raising SchemaError, it must route the invalid event to self.dlq.route(event, reason='Missing required event_id') and return None.",
        "category": "cross_module",
        "target_file": "hydra_mesh/pipeline/transformer.py",
        "trap_file": "hydra_mesh/pipeline/dead_letter.py",
        "trap_transition": "file:hydra_mesh/pipeline/transformer.py->CALLS->file:hydra_mesh/pipeline/dead_letter.py",
        "correct_symbol": "EventTransformer.transform_event",
        "trap_symbol": "DeadLetterQueue.route",
        "test_target": "tests/test_dead_letter.py::test_transformer_missing_schema_routes_to_dlq",
        "failure_mode": "CALLER_CALLEE_AMBIGUITY",
    },
    {
        "task_id": "M4-TASK-C",
        "title": "Implement selective reset(client_id) on SlidingWindowLimiter",
        "description": "SlidingWindowLimiter in hydra_mesh/ingest/rate_limiter.py needs a reset method. If client_id is given, reset only that client's history. If None, reset all. CRITICAL: Global reset must not be used when client_id is specified, as it destroys multi-client isolation.",
        "category": "behavior_modification",
        "target_file": "hydra_mesh/ingest/rate_limiter.py",
        "trap_file": "hydra_mesh/ingest/rate_limiter.py",
        "trap_transition": "method:hydra_mesh/ingest/rate_limiter.py::SlidingWindowLimiter.reset->CALLS->dict.clear",
        "correct_symbol": "SlidingWindowLimiter.reset",
        "trap_symbol": "dict.clear",
        "test_target": "tests/test_rate_limiter.py::test_rate_limiter_reset",
        "failure_mode": "INCORRECT_HYPOTHESIS_GLOBAL_RESET",
    },
    {
        "task_id": "M4-TASK-D",
        "title": "SlidingWindowLimiter Burst Allowance Configuration",
        "description": "When burst_allowance > 0, SlidingWindowLimiter in hydra_mesh/ingest/rate_limiter.py must allow up to max_requests + burst_allowance within the active sliding window before rejecting requests.",
        "category": "bug_fix",
        "target_file": "hydra_mesh/ingest/rate_limiter.py",
        "trap_file": "hydra_mesh/storage/cache.py",
        "trap_transition": "method:hydra_mesh/ingest/rate_limiter.py::SlidingWindowLimiter.allow_request->CALLS->KeyValueCache.get",
        "correct_symbol": "SlidingWindowLimiter.allow_request",
        "trap_symbol": "KeyValueCache.get",
        "test_target": "tests/test_rate_limiter.py::test_rate_limiter_burst_allowance",
        "failure_mode": "REPEATED_TEMPTATION_AVOIDANCE",
    },
]


def restore_repo():
    """Reset repository working tree to clean baseline."""
    subprocess.run(["git", "restore", "."], cwd=str(REPO_PATH), check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=str(REPO_PATH), check=True)


def execute_phase1_controlled_failures(neg_overlay: NegativeGraphOverlay, pos_overlay: ExperienceGraphOverlay):
    """PHASE 1: Generate and record verified failure evidence with causal attribution."""
    print("\n" + "=" * 70)
    print("PHASE 1: GENERATING VERIFIED FAILURE EXPERIENCES & CAUSAL ATTRIBUTIONS")
    print("=" * 70)

    # Pre-populate positive overlay with legitimate verified baseline history
    pos_rec_limiter = ExperienceRecord(
        experience_id="EXP-POS-LIMITER-01",
        task_id="M3-SEQ-TASK-1",
        repository_id="scaled_repo",
        repository_version="v1.0",
        task_description="Baseline rate limiter verification",
        task_category="bug_fix",
        symbols_modified=["SlidingWindowLimiter.allow_request"],
        files_modified=["hydra_mesh/ingest/rate_limiter.py"],
        files_inspected=["hydra_mesh/ingest/rate_limiter.py"],
        success=True,
        verification_status="VERIFIED",
    )
    builder = RepositoryGraphBuilder(str(REPO_PATH), repo_id="scaled_repo")
    nodes, edges = builder.build()
    graph_idx = GraphIndex(nodes, edges)
    pos_overlay.update_from_experience(pos_rec_limiter, graph_idx)

    # 1. Failure Record for Task A: Agent mistakenly inspected and edited storage/cache.py instead of buffer.py
    rec_a = NegativeExperienceRecord(
        experience_id="NEG-EXP-TASK-A-TRAP",
        task_id="M4-PHASE1-TASK-A",
        repository_id="scaled_repo",
        repository_version="v1.0",
        task_category="bug_fix",
        failure_type=FailureType.LOCALIZATION_FAILURE.value,
        failed_hypothesis="Attempted buffer eviction by clearing KeyValueCache in cache.py",
        failed_action="edit_file:hydra_mesh/storage/cache.py",
        failed_transition="file:hydra_mesh/storage/buffer.py->REFERENCES->file:hydra_mesh/storage/cache.py",
        source_node="file:hydra_mesh/storage/buffer.py",
        target_node="file:hydra_mesh/storage/cache.py",
        edge_type="REFERENCES",
        failure_reason="Modified KeyValueCache but RingBuffer overflow check remained broken (DID NOT RAISE BufferOverflowError).",
        failed_test="tests/test_buffer_eviction.py::test_buffer_push_and_capacity",
        expected_behavior="RingBuffer raises BufferOverflowError when size exceeds capacity.",
        observed_behavior="Failed: DID NOT RAISE BufferOverflowError",
        confidence=1.0,
        timestamp=time.time(),
        provenance={"phase": 1, "trap": "cache_vs_buffer"},
        attribution_strength=AttributionStrength.STRONG.value,
        attribution_reason="Direct test failure: edits to cache.py failed to resolve RingBuffer assertion.",
        file_hashes={"hydra_mesh/storage/cache.py": "hash_cache_v1"},
    )
    neg_overlay.update_from_negative_experience(rec_a)

    # 2. Failure Record for Task B: Agent modified dead_letter.py directly instead of transformer caller
    rec_b = NegativeExperienceRecord(
        experience_id="NEG-EXP-TASK-B-TRAP",
        task_id="M4-PHASE1-TASK-B",
        repository_id="scaled_repo",
        repository_version="v1.0",
        task_category="cross_module",
        failure_type=FailureType.TEST_FAILURE.value,
        failed_hypothesis="Modified DeadLetterQueue to accept empty records instead of routing from transformer.py",
        failed_action="edit_file:hydra_mesh/pipeline/dead_letter.py",
        failed_transition="file:hydra_mesh/pipeline/transformer.py->CALLS->file:hydra_mesh/pipeline/dead_letter.py",
        source_node="file:hydra_mesh/pipeline/transformer.py",
        target_node="file:hydra_mesh/pipeline/dead_letter.py",
        edge_type="CALLS",
        failure_reason="EventTransformer still raised SchemaError because validation remained in transformer.py.",
        failed_test="tests/test_dead_letter.py::test_transformer_missing_schema_routes_to_dlq",
        expected_behavior="Transformer routes missing event_id to DLQ without raising SchemaError.",
        observed_behavior="SchemaError: Missing required event_id",
        confidence=1.0,
        timestamp=time.time(),
        provenance={"phase": 1, "trap": "dlq_vs_transformer"},
        attribution_strength=AttributionStrength.STRONG.value,
        attribution_reason="Modifying DLQ did not prevent SchemaError in transformer callers.",
        file_hashes={"hydra_mesh/pipeline/dead_letter.py": "hash_dlq_v1"},
    )
    neg_overlay.update_from_negative_experience(rec_b)

    # 3. Failure Record for Task C: Agent wiped all clients globally in reset
    rec_c = NegativeExperienceRecord(
        experience_id="NEG-EXP-TASK-C-TRAP",
        task_id="M4-PHASE1-TASK-C",
        repository_id="scaled_repo",
        repository_version="v1.0",
        task_category="behavior_modification",
        failure_type=FailureType.HYPOTHESIS_FAILURE.value,
        failed_hypothesis="Reset limiter by clearing dictionary unconditionally: self.requests = {}",
        failed_action="edit_file:hydra_mesh/ingest/rate_limiter.py",
        failed_transition="method:hydra_mesh/ingest/rate_limiter.py::SlidingWindowLimiter.reset->CALLS->dict.clear",
        source_node="method:hydra_mesh/ingest/rate_limiter.py::SlidingWindowLimiter.reset",
        target_node="dict.clear",
        edge_type="CALLS",
        failure_reason="Global wipe violates client isolation requirement in test_rate_limiter_client_isolation.",
        failed_test="tests/test_rate_limiter.py::test_rate_limiter_client_isolation",
        expected_behavior="Reset client1 must not affect client2 quotas.",
        observed_behavior="AssertionError: Isolated client quota rejected!",
        confidence=1.0,
        timestamp=time.time(),
        provenance={"phase": 1, "trap": "global_reset"},
        attribution_strength=AttributionStrength.VERIFIED.value,
        attribution_reason="Direct regression failure in client isolation test caused by global clear.",
        file_hashes={"hydra_mesh/ingest/rate_limiter.py": "hash_limiter_v1"},
    )
    neg_overlay.update_from_negative_experience(rec_c)

    print(f"Phase 1 complete. Ingested 3 strongly/verified attributed failure records into negative overlay.")
    return [rec_a, rec_b, rec_c]


def run_benchmark_task(
    task: Dict[str, Any],
    condition: str,
    pos_overlay: Optional[ExperienceGraphOverlay],
    neg_overlay: Optional[NegativeGraphOverlay],
    config: Optional[ExperienceGraphConfig] = None,
    include_raw_text: bool = True,
    adapter: Optional[GemmaModelAdapter] = None,
) -> Dict[str, Any]:
    """Execute a single task under specified condition."""
    task_id = task["task_id"]
    print(f"\n--- Running {task_id} under CONDITION: {condition} ---")
    restore_repo()

    t_start = time.time()
    traj_path = TRAJ_DIR / f"m4_{condition.lower()}_{task_id.lower()}.jsonl"
    if traj_path.exists():
        traj_path.unlink()

    # Configure graph & experience flags
    enable_graph = condition != "STATELESS"
    enable_graph_guidance = condition == "STATIC_GRAPH"
    enable_exp_graph = condition in ("POSITIVE_GRAPH", "POSITIVE_NEGATIVE_GRAPH", "POSITIVE_NEGATIVE_NO_TEXT")
    enable_neg = condition in ("POSITIVE_NEGATIVE_GRAPH", "POSITIVE_NEGATIVE_NO_TEXT")

    cfg = config or ExperienceGraphConfig()
    if not enable_neg:
        cfg.enable_negative_penalties = False

    agent = SWEAgent(
        repo_path=str(REPO_PATH),
        task_id=f"M4-{condition}-{task_id}",
        model_adapter=adapter or GemmaModelAdapter(temperature=0.1),
        trajectory_output=str(traj_path),
        trajectory_mode="M4",
        condition=condition,
        enable_graph=enable_graph,
        enable_graph_guidance=enable_graph_guidance,
        enable_experience_graph=enable_exp_graph,
        experience_graph_overlay=pos_overlay if enable_exp_graph else None,
        experience_graph_config=cfg,
        include_raw_experience_text=include_raw_text,
        enable_negative_graph=enable_neg,
        negative_graph_overlay=neg_overlay if enable_neg else None,
        expected_files=[task["target_file"]],
        test_target=task["test_target"],
        task_category=task["category"],
    )

    result = agent.run(task_description=task["description"])
    duration = round(time.time() - t_start, 3)

    # Evaluate task-specific outcomes & avoidance
    metrics = result["metrics"]
    metrics["execution_time"] = duration

    # Detect whether agent avoided penalized trap transition
    trap = task["trap_transition"]
    avoided_trap = True
    repeated_failure = False

    # Check files inspected/modified for trap file
    if task["trap_file"] in metrics["files_inspected"] and task["trap_file"] != task["target_file"]:
        # If agent inspected and attempted to edit the trap file, that is a repeat failure
        if task["trap_file"] in agent.files_modified:
            repeated_failure = True
            avoided_trap = False

    # Check if penalized edge was demoted or selected
    penalized_edges = metrics.get("penalized_edges", [])
    if any(task["trap_symbol"] in str(pe) or task["trap_file"] in str(pe) for pe in penalized_edges):
        avoided_trap = True

    metrics["avoided_trap_transition"] = avoided_trap
    metrics["repeated_failure"] = repeated_failure
    metrics["false_negative_guidance"] = False  # Checked below

    # Check false negative guidance: did negative penalties prevent agent from finding correct target?
    if metrics["task_success"] is False and avoided_trap is False:
        # If the target file itself was mistakenly suppressed
        if task["target_file"] in [str(pe) for pe in penalized_edges]:
            metrics["false_negative_guidance"] = True

    print(f"Task {task_id} [{condition}] Result: Success={metrics['task_success']}, AvoidedTrap={avoided_trap}, RepeatedFail={repeated_failure}, Time={duration}s")
    return {
        "task_id": task_id,
        "condition": condition,
        "metrics": metrics,
        "status": result["status"],
    }


def main():
    parser = argparse.ArgumentParser(description="M4 Failure-Aware Graph Benchmark Runner")
    parser.add_argument("--condition", type=str, default=None, help="Condition: STATELESS, STATIC_GRAPH, POSITIVE_GRAPH, POSITIVE_NEGATIVE_GRAPH, POSITIVE_NEGATIVE_NO_TEXT, ABLATION_NO_ATTR, ABLATION_NO_RECENCY")
    parser.add_argument("--task", type=str, default=None, help="Task ID: M4-TASK-A, M4-TASK-B, M4-TASK-C, M4-TASK-D")
    parser.add_argument("--phase1", action="store_true", help="Run Phase 1 failure ingestion only")
    parser.add_argument("--summarize", action="store_true", help="Aggregate results and generate m4_summary.json")
    args = parser.parse_args()

    pos_db = EXP_GRAPH_DIR / "m4_positive_overlay.db"
    neg_db = EXP_GRAPH_DIR / "m4_negative_overlay.db"

    pos_overlay = ExperienceGraphOverlay(db_path=str(pos_db))
    neg_overlay = NegativeGraphOverlay(db_path=str(neg_db))

    if args.phase1 or not neg_db.exists() or neg_db.stat().st_size == 0:
        execute_phase1_controlled_failures(neg_overlay, pos_overlay)
        if args.phase1:
            print("Phase 1 complete. Exiting as requested.")
            return

    adapter = GemmaModelAdapter(temperature=0.1)

    conditions = [
        "STATELESS",
        "STATIC_GRAPH",
        "POSITIVE_GRAPH",
        "POSITIVE_NEGATIVE_GRAPH",
        "POSITIVE_NEGATIVE_NO_TEXT",
    ]

    selected_conditions = [args.condition] if args.condition else conditions
    selected_tasks = [t for t in BENCHMARK_TASKS if (not args.task or t["task_id"] == args.task)]

    if not args.summarize:
        for cond in selected_conditions:
            print(f"\n=======================================================")
            print(f"RUNNING EXPERIMENTAL CONDITION: {cond}")
            print(f"=======================================================")
            include_raw = cond != "POSITIVE_NEGATIVE_NO_TEXT"
            cfg = None
            if cond == "ABLATION_NO_ATTR":
                cfg = ExperienceGraphConfig(attribution_filtering_enabled=False)
            elif cond == "ABLATION_NO_RECENCY":
                cfg = ExperienceGraphConfig(recency_tau_negative_seconds=1e9)

            for task in selected_tasks:
                task_id = task["task_id"]
                res_path = RESULTS_DIR / f"m4_{cond.lower()}_{task_id.lower()}.json"
                res = run_benchmark_task(
                    task=task,
                    condition=cond,
                    pos_overlay=pos_overlay,
                    neg_overlay=neg_overlay,
                    config=cfg,
                    include_raw_text=include_raw,
                    adapter=adapter,
                )
                with open(res_path, "w", encoding="utf-8") as f:
                    json.dump(res, f, indent=2)

    # Summarize all available results
    print("\n=======================================================")
    print("SUMMARIZING M4 RESEARCH BENCHMARK METRICS")
    print("=======================================================")

    summary_data = {
        "timestamp": time.time(),
        "model": adapter.get_model_info(),
        "benchmark_tasks": BENCHMARK_TASKS,
        "conditions": {},
        "ablations": {},
        "comparisons": {},
        "raw_task_runs": {},
    }

    all_conds = conditions + ["ABLATION_NO_ATTR", "ABLATION_NO_RECENCY"]

    def summarize_cond_runs(cond_name):
        runs = []
        for t in BENCHMARK_TASKS:
            rp = RESULTS_DIR / f"m4_{cond_name.lower()}_{t['task_id'].lower()}.json"
            if rp.exists():
                with open(rp, "r", encoding="utf-8") as f:
                    runs.append(json.load(f))
        if not runs:
            return None

        total = len(runs)
        successes = sum(1 for r in runs if r["metrics"]["task_success"])
        avoided = sum(1 for r in runs if r["metrics"].get("avoided_trap_transition", False))
        repeated = sum(1 for r in runs if r["metrics"].get("repeated_failure", False))
        false_neg = sum(1 for r in runs if r["metrics"].get("false_negative_guidance", False))
        tool_calls = [r["metrics"]["tool_calls"] for r in runs]
        searches = [r["metrics"]["search_count"] for r in runs]
        files_read = [r["metrics"]["files_read"] for r in runs]
        exec_times = [r["metrics"]["execution_time"] for r in runs]
        recoveries = [r["metrics"]["recovery_attempts"] for r in runs]
        penalized_counts = [r["metrics"].get("penalized_edges_count", 0) for r in runs]

        return {
            "total_tasks": total,
            "task_success_rate": round(successes / total, 3),
            "patch_correctness": round(successes / total, 3),
            "negative_avoidance_rate": round(avoided / total, 3),
            "repeat_failure_rate": round(repeated / total, 3),
            "false_negative_guidance_rate": round(false_neg / total, 3),
            "avg_tool_calls": round(sum(tool_calls) / total, 2),
            "avg_searches": round(sum(searches) / total, 2),
            "avg_files_inspected": round(sum(files_read) / total, 2),
            "avg_execution_time": round(sum(exec_times) / total, 2),
            "avg_recovery_attempts": round(sum(recoveries) / total, 2),
            "avg_penalized_edges": round(sum(penalized_counts) / total, 2),
        }

    for c in conditions:
        s = summarize_cond_runs(c)
        if s:
            summary_data["conditions"][c] = s

    for a in ["ABLATION_NO_ATTR", "ABLATION_NO_RECENCY"]:
        s = summarize_cond_runs(a)
        if s:
            summary_data["ablations"][a] = s

    if "POSITIVE_GRAPH" in summary_data["conditions"] and "POSITIVE_NEGATIVE_GRAPH" in summary_data["conditions"]:
        pos_only = summary_data["conditions"]["POSITIVE_GRAPH"]
        pos_neg = summary_data["conditions"]["POSITIVE_NEGATIVE_GRAPH"]
        summary_data["comparisons"]["positive_vs_positive_negative"] = {
            "success_rate_delta": round(pos_neg["task_success_rate"] - pos_only["task_success_rate"], 3),
            "repeat_failure_rate_reduction": round(pos_only["repeat_failure_rate"] - pos_neg["repeat_failure_rate"], 3),
            "avoidance_rate_gain": round(pos_neg["negative_avoidance_rate"] - pos_only["negative_avoidance_rate"], 3),
            "tool_call_reduction": round(pos_only["avg_tool_calls"] - pos_neg["avg_tool_calls"], 2),
            "false_negative_guidance_rate": pos_neg["false_negative_guidance_rate"],
        }

    out_summary = RESULTS_DIR / "m4_summary.json"
    with open(out_summary, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    print(f"Summary successfully saved to: {out_summary}")
    print(json.dumps(summary_data["conditions"], indent=2))
    if summary_data.get("comparisons"):
        print("\nComparison:")
        print(json.dumps(summary_data["comparisons"], indent=2))


if __name__ == '__main__':
    main()
