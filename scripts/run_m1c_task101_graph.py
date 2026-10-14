"""M1C Condition B (Graph-Guided Retrieval) on TASK-101."""

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
from lifecore_swe.retrieval.models import RetrievalConfig

repo_path = "/lifecore-swe/fixtures/buggy_repo"
traj_path = "/lifecore-swe/experiments/trajectories/m1c_graph_task101.jsonl"
results_file = "/lifecore-swe/experiments/results/m1c_graph_task101.json"
retrieval_output = "/lifecore-swe/experiments/retrievals/task-101_agent_graph_retrieval.json"

print("=== Restoring pristine baseline in buggy_repo ===")
subprocess.run(["git", "restore", "."], cwd=repo_path, check=True)
subprocess.run(["git", "clean", "-fd"], cwd=repo_path, check=True)

runner = TestRunnerTool(repo_path)
b_res = runner.run_tests()
assert not b_res["passed"], "Baseline check failed!"
print("Baseline confirmed:", b_res["summary"])

print("=== Executing Condition B (Gemma + Graph-Guided Retrieval) on TASK-101 ===")
adapter = GemmaModelAdapter(model_name="gemma-4-26b-a4b-it", temperature=0.1)
agent = SWEAgent(
    repo_path=repo_path,
    task_id="M1C-GRAPH-TASK101",
    model_adapter=adapter,
    trajectory_output=traj_path,
    trajectory_mode="M1C",
    enable_graph=False,  # Graph tools NOT exposed to agent directly
    enable_graph_guidance=True,  # Deterministic graph pre-retrieval injected
    retrieval_config=RetrievalConfig(
        max_nodes=15,
        max_edges=25,
        max_files=5,
        max_tests=5,
        enable_relationship_expansion=True,
    ),
    retrieval_output=retrieval_output,
    expected_files=["event_processor/filters.py"],
)
result = agent.run()

print(f"Condition B status: {result['status']}")
print("Metrics:", json.dumps(result['metrics'], indent=2))

Path(results_file).write_text(json.dumps(result, indent=2), encoding="utf-8")
print(f"Saved results to {results_file}")
