"""
run_benchmark_local.py

Runs the LIFECORE-SWE Flask benchmark using a FREE local model via Ollama.
No API key required. No cost.

SETUP (one time):
  1. Install Ollama:   https://ollama.com/download  (Windows/Mac/Linux)
  2. Pull a model:     ollama pull gemma2:9b
  3. Start server:     ollama serve   (leave this terminal open)
  4. Run this script:  python scripts/run_benchmark_local.py

MODEL OPTIONS (choose based on your RAM):
  gemma2:2b    2 GB RAM   fast, weaker
  gemma2:9b    5 GB RAM   recommended  ← default
  gemma2:27b   16 GB RAM  best quality
  llama3.2:3b  2 GB RAM   fast fallback
  codellama:7b 4 GB RAM   code-focused

The script runs all 5 conditions (A-E) across all 5 Flask tasks and
saves results to experiments/results/real_repo/ with a summary JSON.

Results are then automatically used to update the paper numbers.
"""

import argparse
import json
import sys
import subprocess
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lifecore_swe.agent.ollama_adapter import OllamaModelAdapter


def check_prereqs(model_name: str, base_url: str) -> bool:
    """Check Ollama is running and the model is available."""
    print("\n[Pre-flight checks]")

    # 1. Is Ollama running?
    if not OllamaModelAdapter.check_ollama_running(base_url):
        print(f"  ✗ Ollama server not reachable at {base_url}")
        print()
        print("  To start Ollama:")
        print("    1. Install from https://ollama.com/download")
        print("    2. Open a new terminal and run:  ollama serve")
        print("    3. Re-run this script")
        return False
    print(f"  ✓ Ollama server running at {base_url}")

    # 2. Is the model available?
    available = OllamaModelAdapter.list_available_models(base_url)
    if not available:
        print(f"  ✗ No models found. Pull one first:")
        print(f"      ollama pull {model_name}")
        return False

    if model_name not in available:
        print(f"  ✗ Model '{model_name}' not found locally.")
        print(f"  Available models: {available}")
        print(f"\n  Pull it with:  ollama pull {model_name}")
        return False
    print(f"  ✓ Model '{model_name}' available")

    # 3. Is Flask fixture set up?
    fixture = REPO_ROOT / "fixtures" / "real_repo_flask"
    if not fixture.exists():
        print(f"  ✗ Flask fixture not found.")
        print(f"  Run setup first:  python scripts/setup_real_repo_benchmark.py")
        return False
    print(f"  ✓ Flask fixture found at {fixture}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Run LIFECORE-SWE Flask benchmark with a free local Ollama model")
    parser.add_argument(
        "--model", default="gemma2:9b",
        help="Ollama model name (default: gemma2:9b). "
             "Run 'ollama list' to see available models.")
    parser.add_argument(
        "--url", default="http://localhost:11434",
        help="Ollama server URL (default: http://localhost:11434)")
    parser.add_argument(
        "--condition",
        choices=["STATELESS", "STATIC_GRAPH", "GRAPH_EXP_TEXT",
                 "EXP_CONDITIONED", "EXP_GRAPH_NO_TEXT", "all"],
        default="all")
    parser.add_argument(
        "--task-id",
        choices=["REAL-TASK-1","REAL-TASK-2","REAL-TASK-3",
                 "REAL-TASK-4","REAL-TASK-5","all"],
        default="all")
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Runs per task/condition for statistical repeats (default: 1, use 3 for stats)")
    args = parser.parse_args()

    print("=" * 60)
    print("LIFECORE-SWE Local Benchmark Runner")
    print(f"  Model:  {args.model} (via Ollama, free)")
    print(f"  Server: {args.url}")
    print("=" * 60)

    if not check_prereqs(args.model, args.url):
        sys.exit(1)

    # Build adapter
    adapter = OllamaModelAdapter(
        model_name=args.model,
        base_url=args.url,
        temperature=0.1,
    )

    # Quick smoke test
    print("\n[Smoke test]")
    try:
        response = adapter.plan(
            "Fix a bug where window_end boundary events are excluded.",
            {"repo": "test", "file": "filters.py"}
        )
        print(f"  ✓ Model responding — plan steps: {len(response)}")
    except Exception as e:
        print(f"  ✗ Model test failed: {e}")
        sys.exit(1)

    # Delegate to run_real_repo_benchmark with our adapter
    print("\n[Starting benchmark]")
    print(f"  Condition(s): {args.condition}")
    print(f"  Task(s):      {args.task_id}")
    print(f"  Runs each:    {args.runs}")
    print()

    # Import and run directly
    from scripts.run_real_repo_benchmark import (
        BENCHMARK_TASKS, CONDITIONS, run_task, generate_summary
    )

    conditions = CONDITIONS if args.condition == "all" else [args.condition]
    tasks = (BENCHMARK_TASKS if args.task_id == "all"
             else [t for t in BENCHMARK_TASKS if t["task_id"] == args.task_id])

    all_results = []
    for condition in conditions:
        for run_idx in range(args.runs):
            for task_def in tasks:
                result = run_task(task_def, condition, adapter, run_idx)
                all_results.append(result)

    # Summary
    summary = generate_summary(all_results)
    # Add model metadata
    summary["model"]    = args.model
    summary["provider"] = "Ollama (local, free)"
    summary["note"]     = (
        f"Results from local {args.model} via Ollama. "
        f"For Gemma 4 (gemma-4-26b-a4b-it) results, use run_real_repo_benchmark.py "
        f"with a Google AI Studio API key."
    )

    out_dir  = REPO_ROOT / "experiments" / "results" / "real_repo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"real_repo_summary_{args.model.replace(':', '_')}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print("BENCHMARK COMPLETE")
    print(f"  Model:   {args.model}")
    print(f"  Summary: {out_path}")
    print()
    for cond, data in summary.get("conditions", {}).items():
        sr = data["task_success_rate"]
        tc = data["avg_tool_calls"]
        et = data["avg_execution_time"]
        print(f"  {cond:<22}  success={sr['mean']*100:.0f}%  "
              f"tool_calls={tc['mean']:.1f}  time={et['mean']:.0f}s")
    print("=" * 60)
    print()
    print("Next step: update PAPER.md with these results")
    print("  python scripts/update_paper_with_results.py "
          f"--source {out_path}")


if __name__ == "__main__":
    main()
