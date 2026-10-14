"""Benchmark evaluation of retrieval conditions across all 5 tasks."""

import json
from pathlib import Path
from lifecore_swe.codegraph.builder import RepositoryGraphBuilder
from lifecore_swe.codegraph.index import GraphIndex
from lifecore_swe.retrieval.graph_retriever import GraphRetriever
from lifecore_swe.retrieval.models import RetrievalConfig

# Task definitions and ground truth target files/symbols
TASKS = [
    {
        "task_id": "TASK-101",
        "repo_path": "/lifecore-swe/fixtures/buggy_repo",
        "repo_id": "buggy_repo",
        "task_file": "/lifecore-swe/fixtures/buggy_repo/TASK.md",
        "ground_truth_files": ["event_processor/filters.py"],
        "ground_truth_symbols": ["EventFilter.is_in_window", "EventFilter.should_retain"],
        "test_target": "tests/test_pipeline.py",
    },
    {
        "task_id": "TASK-201",
        "repo_path": "/lifecore-swe/fixtures/scaled_repo",
        "repo_id": "scaled_repo",
        "task_file": "/lifecore-swe/fixtures/scaled_repo/tasks/TASK-201.md",
        "ground_truth_files": ["hydra_mesh/ingest/rate_limiter.py"],
        "ground_truth_symbols": ["SlidingWindowLimiter.allow_request"],
        "test_target": "tests/test_rate_limiter.py",
    },
    {
        "task_id": "TASK-202",
        "repo_path": "/lifecore-swe/fixtures/scaled_repo",
        "repo_id": "scaled_repo",
        "task_file": "/lifecore-swe/fixtures/scaled_repo/tasks/TASK-202.md",
        "ground_truth_files": ["hydra_mesh/connectors/http_sink.py"],
        "ground_truth_symbols": ["HttpSink.prepare_headers"],
        "test_target": "tests/test_http_sink.py",
    },
    {
        "task_id": "TASK-203",
        "repo_path": "/lifecore-swe/fixtures/scaled_repo",
        "repo_id": "scaled_repo",
        "task_file": "/lifecore-swe/fixtures/scaled_repo/tasks/TASK-203.md",
        "ground_truth_files": ["hydra_mesh/pipeline/transformer.py"],
        "ground_truth_symbols": ["EventTransformer.transform_event"],
        "test_target": "tests/test_dead_letter.py",
    },
    {
        "task_id": "TASK-204",
        "repo_path": "/lifecore-swe/fixtures/scaled_repo",
        "repo_id": "scaled_repo",
        "task_file": "/lifecore-swe/fixtures/scaled_repo/tasks/TASK-204.md",
        "ground_truth_files": ["hydra_mesh/storage/buffer.py"],
        "ground_truth_symbols": ["RingBuffer.push"],
        "test_target": "tests/test_buffer_eviction.py",
    },
]

def run_retrieval_benchmark():
    out_dir = Path("/lifecore-swe/experiments/retrievals")
    out_dir.mkdir(parents=True, exist_ok=True)
    results_summary = []

    # Cache graph indices per repo
    graph_indices = {}
    for t in TASKS:
        repo_path = t["repo_path"]
        if repo_path not in graph_indices:
            builder = RepositoryGraphBuilder(repo_path, repo_id=t["repo_id"])
            nodes, edges = builder.build()
            graph_indices[repo_path] = GraphIndex(nodes, edges)

    for task_info in TASKS:
        tid = task_info["task_id"]
        repo_path = task_info["repo_path"]
        task_text = Path(task_info["task_file"]).read_text(encoding="utf-8")
        gt_files = set(task_info["ground_truth_files"])
        gt_symbols = set(task_info["ground_truth_symbols"])
        index = graph_indices[repo_path]
        retriever = GraphRetriever(index)

        # Condition B: Full Graph-Guided Retrieval (with relationship expansion)
        cfg_b = RetrievalConfig(enable_relationship_expansion=True, expansion_depth=1)
        res_b = retriever.retrieve(task_text, config=cfg_b)

        # Condition C (Ablation): Graph-Guided Retrieval WITHOUT relationship expansion
        cfg_c = RetrievalConfig(enable_relationship_expansion=False, expansion_depth=0)
        res_c = retriever.retrieve(task_text, config=cfg_c)

        # Measure recall & localization efficiency
        retrieved_files_b = set(res_b.relevant_files)
        file_recall_b = len(gt_files.intersection(retrieved_files_b)) / len(gt_files)
        loc_eff_b = len(gt_files.intersection(retrieved_files_b)) / len(retrieved_files_b) if retrieved_files_b else 0.0

        retrieved_files_c = set(res_c.relevant_files)
        file_recall_c = len(gt_files.intersection(retrieved_files_c)) / len(gt_files)
        loc_eff_c = len(gt_files.intersection(retrieved_files_c)) / len(retrieved_files_c) if retrieved_files_c else 0.0

        # Save individual retrieval artifacts
        (out_dir / f"{tid.lower()}_graph_retrieval.json").write_text(
            json.dumps(res_b.to_dict(), indent=2), encoding="utf-8"
        )
        (out_dir / f"{tid.lower()}_ablation_retrieval.json").write_text(
            json.dumps(res_c.to_dict(), indent=2), encoding="utf-8"
        )

        task_res = {
            "task_id": tid,
            "repo": task_info["repo_id"],
            "ground_truth_files": list(gt_files),
            "condition_b_full_graph": {
                "relevant_files": res_b.relevant_files,
                "file_recall": round(file_recall_b, 3),
                "localization_efficiency": round(loc_eff_b, 3),
                "selected_nodes": len(res_b.selected_nodes),
                "selected_edges": len(res_b.selected_edges),
                "associated_tests": len(res_b.associated_tests),
                "latency_ms": res_b.latency_ms,
                "context_chars": len(res_b.compact_context),
            },
            "condition_c_no_expansion": {
                "relevant_files": res_c.relevant_files,
                "file_recall": round(file_recall_c, 3),
                "localization_efficiency": round(loc_eff_c, 3),
                "selected_nodes": len(res_c.selected_nodes),
                "selected_edges": len(res_c.selected_edges),
                "associated_tests": len(res_c.associated_tests),
                "latency_ms": res_c.latency_ms,
                "context_chars": len(res_c.compact_context),
            },
        }
        results_summary.append(task_res)
        print(f"[{tid}] Graph Retrieval: recall={file_recall_b}, eff={loc_eff_b}, nodes={len(res_b.selected_nodes)}, edges={len(res_b.selected_edges)}, latency={res_b.latency_ms}ms")

    # Save summary
    summary_path = Path("/lifecore-swe/experiments/results/retrieval_benchmark_summary.json")
    summary_path.write_text(json.dumps(results_summary, indent=2), encoding="utf-8")
    # Mirror summary
    Path("/experiments/results/retrieval_benchmark_summary.json").write_text(json.dumps(results_summary, indent=2), encoding="utf-8")
    print("\nRetrieval benchmark summary saved to", summary_path)

if __name__ == "__main__":
    run_retrieval_benchmark()
