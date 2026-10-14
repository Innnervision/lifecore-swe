"""
run_real_repo_benchmark.py

Runs the LIFECORE-SWE 5-condition benchmark on a real open-source repository
(Flask v3.0.3) to validate generalizability beyond the synthetic hydra_mesh fixture.

Conditions:
  A  STATELESS          — Gemma 4 + standard tools only
  B  STATIC_GRAPH       — Gemma 4 + deterministic AST graph pre-retrieval (M1C)
  C  GRAPH_EXP_TEXT     — Gemma 4 + graph + episodic experience text (M2/M3)
  D  EXP_CONDITIONED    — Gemma 4 + experience-conditioned graph + text (M3 Cond D)
  E  EXP_GRAPH_NO_TEXT  — Gemma 4 + experience-conditioned graph, NO text (M3 Cond E)

Usage:
    # Run all conditions, all tasks
    python scripts/run_real_repo_benchmark.py

    # Run specific condition only
    python scripts/run_real_repo_benchmark.py --condition EXP_GRAPH_NO_TEXT

    # Run specific task in one condition
    python scripts/run_real_repo_benchmark.py --condition STATIC_GRAPH --task-id REAL-TASK-1

    # Run N times per task/condition for statistical analysis
    python scripts/run_real_repo_benchmark.py --condition EXP_GRAPH_NO_TEXT --runs 3

Prerequisites:
    python scripts/setup_real_repo_benchmark.py   # clone and plant bugs
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

REPO_ROOT   = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "fixtures" / "real_repo_flask"
TASKS_DIR   = FIXTURE_DIR / "lifecore_tasks"
RESULTS_DIR = REPO_ROOT / "experiments" / "results" / "real_repo"
TRAJ_DIR    = REPO_ROOT / "experiments" / "trajectories" / "real_repo"
EXP_DIR     = REPO_ROOT / "experiments" / "experience_graph" / "real_repo"

# ---------------------------------------------------------------------------
# Lazy imports (avoid import errors if setup hasn't been run)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(REPO_ROOT))

from lifecore_swe.agent.agent import SWEAgent
from lifecore_swe.agent.gemma_adapter import GemmaModelAdapter
from lifecore_swe.codegraph.builder import RepositoryGraphBuilder
from lifecore_swe.codegraph.index import GraphIndex
from lifecore_swe.experience.models import ExperienceRetrievalConfig
from lifecore_swe.experience.store import ExperienceStore
from lifecore_swe.experience_graph.models import ExperienceGraphConfig
from lifecore_swe.experience_graph.overlay import ExperienceGraphOverlay
from lifecore_swe.retrieval.models import RetrievalConfig
from lifecore_swe.tools.test_runner import TestRunnerTool

# ---------------------------------------------------------------------------
# Benchmark task definitions
# (mirrors setup_real_repo_benchmark.py — must stay in sync)
# ---------------------------------------------------------------------------

BENCHMARK_TASKS = [
    {
        "task_id":        "REAL-TASK-1",
        "task_file":      "lifecore_tasks/REAL-TASK-1.md",
        "category":       "bug_fix",
        "expected_files": ["src/flask/app.py"],
        "test_target":    "tests/test_basic.py::test_url_mapping",
        "bug_patch": {
            "file":    "src/flask/app.py",
            "search":  "        if provide_automatic_options is None:",
            "replace": "        if provide_automatic_options is not None:",
        },
    },
    {
        "task_id":        "REAL-TASK-2",
        "task_file":      "lifecore_tasks/REAL-TASK-2.md",
        "category":       "bug_fix",
        "expected_files": ["src/flask/ctx.py"],
        "test_target":    "tests/test_reqctx.py::test_teardown_request_handler_error",
        "bug_patch": {
            "file":    "src/flask/ctx.py",
            "search":  "            rv = _cv_tokens.get(None)",
            "replace": "            rv = None  # BUG: token lookup disabled",
        },
    },
    {
        "task_id":        "REAL-TASK-3",
        "task_file":      "lifecore_tasks/REAL-TASK-3.md",
        "category":       "bug_fix",
        "expected_files": ["src/flask/json/provider.py"],
        "test_target":    "tests/test_basic.py::test_jsonify_basic_types",
        "bug_patch": {
            "file":    "src/flask/json/provider.py",
            "search":  '    mimetype = "application/json"',
            "replace": '    mimetype = "text/plain"  # BUG: wrong mimetype',
        },
    },
    {
        "task_id":        "REAL-TASK-4",
        "task_file":      "lifecore_tasks/REAL-TASK-4.md",
        "category":       "behavior_modification",
        "expected_files": ["src/flask/blueprints.py"],
        "test_target":    "tests/test_blueprints.py::test_blueprint_url_prefix",
        "bug_patch": {
            "file":    "src/flask/blueprints.py",
            "search":  "        if url_prefix is not None:",
            "replace": "        if url_prefix is None:  # BUG: inverted condition",
        },
    },
    {
        "task_id":        "REAL-TASK-5",
        "task_file":      "lifecore_tasks/REAL-TASK-5.md",
        "category":       "bug_fix",
        "expected_files": ["src/flask/sessions.py"],
        "test_target":    "tests/test_basic.py::test_session_cookie_setting",
        "bug_patch": {
            "file":    "src/flask/sessions.py",
            "search":  "        samesite = session_interface.get_cookie_samesite(app)",
            "replace": "        samesite = None  # BUG: samesite always suppressed",
        },
    },
]

CONDITIONS = ["STATELESS", "STATIC_GRAPH", "GRAPH_EXP_TEXT",
              "EXP_CONDITIONED", "EXP_GRAPH_NO_TEXT"]


# ---------------------------------------------------------------------------
# Repository management
# ---------------------------------------------------------------------------

def restore_repo():
    """Reset Flask fixture to clean baseline."""
    subprocess.run(["git", "restore", "."],
                   cwd=str(FIXTURE_DIR), check=True, capture_output=True)
    subprocess.run(["git", "clean", "-fd"],
                   cwd=str(FIXTURE_DIR), check=True, capture_output=True)


def plant_bug(task_def: Dict) -> bool:
    """Apply the bug patch for a task. Returns True if patch was applied."""
    patch = task_def["bug_patch"]
    target = FIXTURE_DIR / patch["file"]
    if not target.exists():
        print(f"  [WARN] Target file not found: {patch['file']}")
        return False
    content = target.read_text(encoding="utf-8")
    if patch["search"] not in content:
        print(f"  [WARN] Search string not found in {patch['file']} — version mismatch?")
        return False
    patched = content.replace(patch["search"], patch["replace"], 1)
    target.write_text(patched, encoding="utf-8")
    return True


def confirm_baseline_fails(task_def: Dict) -> bool:
    """Verify the planted bug breaks the target test."""
    runner = TestRunnerTool(str(FIXTURE_DIR))
    result = runner.run_tests(test_target=task_def["test_target"])
    return not result["passed"]


# ---------------------------------------------------------------------------
# Condition setup helpers
# ---------------------------------------------------------------------------

def make_paths(condition: str, task_id: str, run_idx: int) -> Dict[str, str]:
    run_suffix = f"_run{run_idx}" if run_idx > 0 else ""
    cond_low   = condition.lower()
    task_low   = task_id.lower()
    return {
        "traj":    str(TRAJ_DIR   / f"real_{cond_low}_{task_low}{run_suffix}.jsonl"),
        "result":  str(RESULTS_DIR / f"real_{cond_low}_{task_low}{run_suffix}.json"),
        "store":   str(EXP_DIR    / f"real_{cond_low}_store.db"),
        "overlay": str(EXP_DIR    / f"real_{cond_low}_overlay.db"),
    }


def build_agent(task_def: Dict, condition: str, paths: Dict[str, str],
                adapter: GemmaModelAdapter) -> SWEAgent:
    """Construct SWEAgent with the correct flags for the given condition."""
    common = dict(
        repo_path              = str(FIXTURE_DIR),
        task_id                = f"REAL-{condition}-{task_def['task_id']}",
        model_adapter          = adapter,
        trajectory_output      = paths["traj"],
        trajectory_mode        = "M3",
        expected_files         = task_def["expected_files"],
        test_target            = task_def["test_target"],
        task_category          = task_def["category"],
        store_experience_on_completion = True,
        condition              = condition,
    )

    if condition == "STATELESS":
        return SWEAgent(
            **common,
            enable_graph          = False,
            enable_graph_guidance = False,
            enable_experience     = False,
            enable_experience_graph = False,
        )

    elif condition == "STATIC_GRAPH":
        return SWEAgent(
            **common,
            enable_graph          = False,
            enable_graph_guidance = True,
            enable_experience     = False,
            enable_experience_graph = False,
            retrieval_config      = RetrievalConfig(
                max_nodes=15, max_edges=25, max_files=5, max_tests=5,
                max_context_chars=4000, expansion_depth=1,
                enable_relationship_expansion=True,
            ),
        )

    elif condition == "GRAPH_EXP_TEXT":
        exp_store = ExperienceStore(db_path=paths["store"])
        return SWEAgent(
            **common,
            enable_graph          = False,
            enable_graph_guidance = True,
            enable_experience     = True,
            experience_store      = exp_store,
            experience_config     = ExperienceRetrievalConfig(
                max_experiences=3, max_context_chars=2500),
            enable_experience_graph = False,
            retrieval_config      = RetrievalConfig(
                max_nodes=15, max_edges=25, max_context_chars=4000,
            ),
        )

    elif condition == "EXP_CONDITIONED":
        exp_store   = ExperienceStore(db_path=paths["store"])
        exp_overlay = ExperienceGraphOverlay(db_path=paths["overlay"])
        return SWEAgent(
            **common,
            enable_graph              = False,
            enable_graph_guidance     = False,
            enable_experience_graph   = True,
            experience_graph_overlay  = exp_overlay,
            experience_graph_config   = ExperienceGraphConfig(
                max_nodes=15, max_edges=25,
                max_context_chars=3500, enable_experience_text=True,
            ),
            include_raw_experience_text = True,
            enable_experience         = True,
            experience_store          = exp_store,
            experience_config         = ExperienceRetrievalConfig(
                max_experiences=3, max_context_chars=2500),
        )

    elif condition == "EXP_GRAPH_NO_TEXT":
        exp_store   = ExperienceStore(db_path=paths["store"])
        exp_overlay = ExperienceGraphOverlay(db_path=paths["overlay"])
        return SWEAgent(
            **common,
            enable_graph              = False,
            enable_graph_guidance     = False,
            enable_experience_graph   = True,
            experience_graph_overlay  = exp_overlay,
            experience_graph_config   = ExperienceGraphConfig(
                max_nodes=15, max_edges=25,
                max_context_chars=3500, enable_experience_text=False,
            ),
            include_raw_experience_text = False,
            enable_experience           = False,
            experience_store            = exp_store,
        )

    else:
        raise ValueError(f"Unknown condition: {condition}")


# ---------------------------------------------------------------------------
# Core task runner
# ---------------------------------------------------------------------------

def run_task(task_def: Dict, condition: str, adapter: GemmaModelAdapter,
             run_idx: int = 0) -> Dict[str, Any]:
    """Run a single task under a single condition. Returns the result dict."""
    task_id = task_def["task_id"]
    print(f"\n{'='*60}")
    print(f"  {task_id}  |  Condition: {condition}  |  Run: {run_idx}")
    print(f"{'='*60}")

    # 1. Reset repo and plant bug
    restore_repo()
    ok = plant_bug(task_def)
    if not ok:
        print(f"  [SKIP] Could not plant bug for {task_id}")
        return {"status": "SKIPPED", "task_id": task_id, "condition": condition}

    # 2. Confirm baseline fails
    if not confirm_baseline_fails(task_def):
        print(f"  [WARN] Bug patch did not break target test — skipping")
        restore_repo()
        return {"status": "SKIPPED", "task_id": task_id, "condition": condition}

    print(f"  Baseline confirmed FAILING: {task_def['test_target']}")

    # 3. Read task description
    task_text = (FIXTURE_DIR / task_def["task_file"]).read_text(encoding="utf-8")

    # 4. Build paths and agent
    paths = make_paths(condition, task_id, run_idx)
    for d in [RESULTS_DIR, TRAJ_DIR, EXP_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # Reset per-task token counters so each result JSON records accurate token usage
    if hasattr(adapter, "reset_token_usage"):
        adapter.reset_token_usage()

    agent = build_agent(task_def, condition, paths, adapter)

    # 5. Run agent
    start = time.time()
    result = agent.run(task_description=task_text)
    elapsed = time.time() - start

    # 6. Enrich result with benchmark metadata
    result["benchmark"]  = "REAL_REPO_FLASK"
    result["task_id"]    = task_id
    result["condition"]  = condition
    result["run_index"]  = run_idx
    result["repository"] = "pallets/flask"
    result["tag"]        = "3.0.3"

    # 7. Save result
    Path(paths["result"]).write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8")

    status_str = result.get("status", "UNKNOWN")
    metrics    = result.get("metrics", {})
    print(f"  Result: {status_str}")
    print(f"  Tool calls: {metrics.get('tool_calls', '?')}  |  "
          f"Searches: {metrics.get('search_count', '?')}  |  "
          f"Time: {elapsed:.1f}s")

    # 8. Restore repo to clean state after run
    restore_repo()

    return result


# ---------------------------------------------------------------------------
# Summary generator
# ---------------------------------------------------------------------------

def generate_summary(all_results: List[Dict]) -> Dict:
    """Aggregate per-condition metrics across all tasks and runs."""
    from collections import defaultdict
    import statistics

    cond_data: Dict[str, Dict[str, List]] = defaultdict(lambda: defaultdict(list))

    for r in all_results:
        if r.get("status") == "SKIPPED":
            continue
        cond = r.get("condition", "UNKNOWN")
        m    = r.get("metrics", {})
        ok   = r.get("status") == "SUCCESS"
        cond_data[cond]["success"].append(1 if ok else 0)
        cond_data[cond]["tool_calls"].append(m.get("tool_calls", 0))
        cond_data[cond]["searches"].append(m.get("search_count", 0))
        cond_data[cond]["exec_time"].append(m.get("execution_time", 0))
        cond_data[cond]["input_tokens"].append(
            m.get("total_input_tokens", 0))
        cond_data[cond]["output_tokens"].append(
            m.get("total_output_tokens", 0))
        cond_data[cond]["model_calls"].append(
            m.get("model_calls", 0))

    def agg(vals):
        if not vals:
            return {"mean": 0, "std": 0, "n": 0}
        return {
            "mean": round(statistics.mean(vals), 3),
            "std":  round(statistics.stdev(vals) if len(vals) > 1 else 0.0, 3),
            "n":    len(vals),
        }

    summary = {
        "benchmark":   "REAL_REPO_FLASK",
        "repository":  "pallets/flask",
        "tag":         "3.0.3",
        "conditions":  {},
    }

    for cond, data in cond_data.items():
        n = len(data["success"])
        summary["conditions"][cond] = {
            "n_runs":             n,
            "task_success_rate":  agg(data["success"]),
            "avg_tool_calls":     agg(data["tool_calls"]),
            "avg_searches":       agg(data["searches"]),
            "avg_execution_time": agg(data["exec_time"]),
            "avg_input_tokens":   agg(data["input_tokens"]),
            "avg_output_tokens":  agg(data["output_tokens"]),
            "avg_model_calls":    agg(data.get("model_calls", [])),
        }

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LIFECORE-SWE Real Repository Benchmark (Flask v3.0.3)")
    parser.add_argument(
        "--condition",
        choices=CONDITIONS + ["all"],
        default="all",
        help="Which condition(s) to run (default: all)")
    parser.add_argument(
        "--task-id",
        choices=[t["task_id"] for t in BENCHMARK_TASKS] + ["all"],
        default="all",
        help="Which task(s) to run (default: all)")
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per task/condition for statistical analysis (default: 1)")
    args = parser.parse_args()

    if not FIXTURE_DIR.exists():
        print("ERROR: Flask fixture not found.")
        print("Run setup first:  python scripts/setup_real_repo_benchmark.py")
        sys.exit(1)

    conditions_to_run = CONDITIONS if args.condition == "all" else [args.condition]
    tasks_to_run = (BENCHMARK_TASKS if args.task_id == "all"
                    else [t for t in BENCHMARK_TASKS if t["task_id"] == args.task_id])

    print("=" * 60)
    print("LIFECORE-SWE Real Repository Benchmark")
    print(f"  Repository:  pallets/flask v3.0.3")
    print(f"  Conditions:  {conditions_to_run}")
    print(f"  Tasks:       {[t['task_id'] for t in tasks_to_run]}")
    print(f"  Runs each:   {args.runs}")
    print("=" * 60)

    adapter = GemmaModelAdapter(model_name="gemma-4-26b-a4b-it", temperature=0.1)
    all_results = []

    for condition in conditions_to_run:
        print(f"\n{'─'*60}")
        print(f"  Running condition: {condition}")
        print(f"{'─'*60}")

        for run_idx in range(args.runs):
            for task_def in tasks_to_run:
                result = run_task(task_def, condition, adapter, run_idx)
                all_results.append(result)

    # Write summary
    summary = generate_summary(all_results)
    summary_path = RESULTS_DIR / "real_repo_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print("BENCHMARK COMPLETE")
    print(f"  Summary: {summary_path}")
    print(f"  Results: {RESULTS_DIR}")
    print()
    for cond, data in summary.get("conditions", {}).items():
        sr = data["task_success_rate"]
        tc = data["avg_tool_calls"]
        et = data["avg_execution_time"]
        tok = data["avg_input_tokens"]
        print(f"  {cond:<22}  success={sr['mean']*100:.0f}%  "
              f"tool_calls={tc['mean']:.1f}±{tc['std']:.1f}  "
              f"time={et['mean']:.0f}s±{et['std']:.0f}  "
              f"tokens={tok['mean']:.0f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
