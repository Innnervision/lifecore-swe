"""M1C Condition A (Baseline without Graph Guidance) on TASK-201 (Scaled Repo)."""

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from lifecore_swe.agent.agent import SWEAgent
from lifecore_swe.agent.gemma_adapter import GemmaModelAdapter
from lifecore_swe.tools.test_runner import TestRunnerTool

repo_path = "/lifecore-swe/fixtures/scaled_repo"
task_file = f"{repo_path}/tasks/TASK-201.md"
traj_path = "/lifecore-swe/experiments/trajectories/m1c_baseline_task201.jsonl"
results_file = "/lifecore-swe/experiments/results/m1c_baseline_task201.json"
test_target = "tests/test_rate_limiter.py"
expected_files = ["hydra_mesh/ingest/rate_limiter.py"]

print("=== Restoring pristine baseline in scaled_repo ===")
subprocess.run(["git", "restore", "."], cwd=repo_path, check=True)
subprocess.run(["git", "clean", "-fd"], cwd=repo_path, check=True)

runner = TestRunnerTool(repo_path)
b_res = runner.run_tests(test_target=test_target)
assert not b_res["passed"], "Baseline check failed! Test unexpectedly passed."
print("Baseline confirmed failing:", b_res["summary"])

task_text = Path(task_file).read_text(encoding="utf-8")

print("=== Executing Condition A (Gemma Baseline) on TASK-201 ===")
adapter = GemmaModelAdapter(model_name="gemma-4-26b-a4b-it", temperature=0.1)
agent = SWEAgent(
    repo_path=repo_path,
    task_id="M1C-BASE-TASK201",
    model_adapter=adapter,
    trajectory_output=traj_path,
    trajectory_mode="M1C",
    enable_graph=False,
    enable_graph_guidance=False,
    expected_files=expected_files,
    test_target=test_target,
)
result = agent.run(task_description=task_text)

print(f"Condition A status: {result['status']}")
print("Metrics:", json.dumps(result['metrics'], indent=2))

Path(results_file).write_text(json.dumps(result, indent=2), encoding="utf-8")
print(f"Saved results to {results_file}")
