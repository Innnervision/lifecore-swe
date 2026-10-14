"""M2 Sequential Benchmark Runner across Conditions A, B, and C."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

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
from lifecore_swe.retrieval.models import RetrievalConfig
from lifecore_swe.tools.test_runner import TestRunnerTool

REPO_PATH = Path("/lifecore-swe/fixtures/scaled_repo").resolve()

BENCHMARK_TASKS = [
    {
        "task_id": "SEQ-TASK-1",
        "task_file": "tasks/SEQ-TASK-1.md",
        "category": "bug_fix",
        "expected_files": ["hydra_mesh/ingest/rate_limiter.py"],
        "test_target": "tests/test_rate_limiter.py::test_rate_limiter_burst_allowance",
        "related_to": ["rate_limiter"],
    },
    {
        "task_id": "SEQ-TASK-2",
        "task_file": "tasks/SEQ-TASK-2.md",
        "category": "behavior_modification",
        "expected_files": ["hydra_mesh/ingest/rate_limiter.py"],
        "test_target": "tests/test_rate_limiter.py::test_rate_limiter_reset",
        "related_to": ["rate_limiter", "SEQ-TASK-1"],
    },
    {
        "task_id": "SEQ-TASK-3",
        "task_file": "tasks/SEQ-TASK-3.md",
        "category": "test_change",
        "expected_files": ["tests/test_rate_limiter.py"],
        "test_target": "tests/test_rate_limiter.py::test_rate_limiter_client_isolation",
        "related_to": ["rate_limiter", "SEQ-TASK-1", "SEQ-TASK-2"],
    },
    {
        "task_id": "SEQ-TASK-4",
        "task_file": "tasks/SEQ-TASK-4.md",
        "category": "cross_module",
        "expected_files": ["hydra_mesh/pipeline/transformer.py"],
        "test_target": "tests/test_dead_letter.py::test_transformer_missing_schema_routes_to_dlq",
        "related_to": ["pipeline", "transformer", "dead_letter"],
    },
    {
        "task_id": "SEQ-TASK-5",
        "task_file": "tasks/SEQ-TASK-5.md",
        "category": "cross_module_architecture",
        "expected_files": ["hydra_mesh/pipeline/transformer.py"],
        "test_target": "tests/test_dead_letter.py::test_transformer_rate_limited_to_dlq",
        "related_to": ["rate_limiter", "pipeline", "transformer", "dead_letter", "SEQ-TASK-1", "SEQ-TASK-4"],
    },
]


def restore_repo():
    """Clean reset of scaled_repo working tree."""
    subprocess.run(["git", "restore", "."], cwd=str(REPO_PATH), check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=str(REPO_PATH), check=True)


def run_task(task_def, condition, store_path=None, model_adapter=None):
    """Run a single task under specified condition."""
    task_id = task_def["task_id"]
    print(f"\n==================================================")
    print(f"Executing {task_id} under CONDITION {condition}")
    print(f"==================================================")

    restore_repo()

    runner = TestRunnerTool(str(REPO_PATH))
    b_res = runner.run_tests(test_target=task_def["test_target"])
    assert not b_res["passed"], f"Baseline failed: {task_id} test unexpectedly passed!"
    print(f"Baseline confirmed failing: {b_res['summary']}")

    task_text = (REPO_PATH / task_def["task_file"]).read_text(encoding="utf-8")
    adapter = model_adapter or GemmaModelAdapter(model_name="gemma-4-26b-a4b-it", temperature=0.1)

    enable_graph = False
    enable_graph_guidance = False
    enable_experience = False
    experience_store = None

    traj_filename = f"m2_{condition.lower()}_{task_id.lower()}.jsonl"
    traj_path = f"/lifecore-swe/experiments/trajectories/{traj_filename}"
    results_file = f"/lifecore-swe/experiments/results/m2_{condition.lower()}_{task_id.lower()}.json"

    if condition == "STATELESS":
        enable_graph_guidance = False
        enable_experience = False
    elif condition == "GRAPH":
        enable_graph_guidance = True
        enable_experience = False
    elif condition == "GRAPH_EXPERIENCE":
        enable_graph_guidance = True
        enable_experience = True
        if store_path:
            experience_store = ExperienceStore(db_path=store_path)

    agent = SWEAgent(
        repo_path=str(REPO_PATH),
        task_id=f"M2-{condition}-{task_id}",
        model_adapter=adapter,
        trajectory_output=traj_path,
        trajectory_mode="M2",
        enable_graph=enable_graph,
        enable_graph_guidance=enable_graph_guidance,
        enable_experience=enable_experience,
        experience_store=experience_store,
        experience_config=ExperienceRetrievalConfig(max_experiences=3, max_context_chars=2500),
        task_category=task_def["category"],
        store_experience_on_completion=True,
        expected_files=task_def["expected_files"],
        test_target=task_def["test_target"],
    )

    result = agent.run(task_description=task_text)

    print(f"Result for {task_id} ({condition}): {result['status']}")
    print("Metrics:", json.dumps(result["metrics"], indent=2))

    Path(results_file).parent.mkdir(parents=True, exist_ok=True)
    Path(results_file).write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", choices=["STATELESS", "GRAPH", "GRAPH_EXPERIENCE"], required=True)
    parser.add_argument("--task-id", choices=[t["task_id"] for t in BENCHMARK_TASKS] + ["all"], default="all")
    parser.add_argument("--store", default="/lifecore-swe/experiments/experience/m2_condition_c.db")
    args = parser.parse_args()

    tasks_to_run = BENCHMARK_TASKS if args.task_id == "all" else [t for t in BENCHMARK_TASKS if t["task_id"] == args.task_id]

    adapter = GemmaModelAdapter(model_name="gemma-4-26b-a4b-it", temperature=0.1)

    for t_def in tasks_to_run:
        run_task(t_def, condition=args.condition, store_path=args.store, model_adapter=adapter)
