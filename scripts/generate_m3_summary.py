"""Generate M3 machine-readable summary comparing Conditions A, B, C, D, and E."""

import json
from pathlib import Path

RESULTS_DIR = Path("/lifecore-swe/experiments/results")

with open(RESULTS_DIR / "m2_summary.json") as f:
    m2_summary = json.load(f)

tasks = ["seq-task-1", "seq-task-2", "seq-task-3", "seq-task-4", "seq-task-5"]

cond_d_runs = {}
cond_e_runs = {}

for t in tasks:
    with open(RESULTS_DIR / f"m3_exp_conditioned_graph_{t}.json") as f:
        cond_d_runs[t] = json.load(f)
    with open(RESULTS_DIR / f"m3_exp_graph_no_text_{t}.json") as f:
        cond_e_runs[t] = json.load(f)


def compute_condition_stats(runs_dict):
    success_count = sum(1 for r in runs_dict.values() if r["metrics"]["task_success"])
    total = len(runs_dict)
    tool_calls = [r["metrics"]["tool_calls"] for r in runs_dict.values()]
    searches = [r["metrics"]["search_count"] for r in runs_dict.values()]
    files_inspected = [r["metrics"]["files_read"] for r in runs_dict.values()]
    test_runs = [r["metrics"]["test_runs"] for r in runs_dict.values()]
    exec_times = [r["metrics"]["execution_time"] for r in runs_dict.values()]
    loc_eff = [r["metrics"]["repository_localization_efficiency"] for r in runs_dict.values()]
    edge_util = [r["metrics"].get("experience_guided_edge_utilization", 0.0) for r in runs_dict.values()]
    exp_reused = sum(1 for r in runs_dict.values() if r["metrics"].get("experience_influence") in ("REFERENCED", "USED", "VERIFIED_USEFUL"))

    return {
        "success_count": success_count,
        "total_tasks": total,
        "success_rate": round(success_count / total, 3),
        "patch_correctness": round(success_count / total, 3),
        "avg_tool_calls": round(sum(tool_calls) / total, 2),
        "avg_searches": round(sum(searches) / total, 2),
        "avg_files_inspected": round(sum(files_inspected) / total, 2),
        "avg_test_runs": round(sum(test_runs) / total, 2),
        "avg_execution_time": round(sum(exec_times) / total, 2),
        "avg_localization_efficiency": round(sum(loc_eff) / total, 3),
        "avg_experience_edge_utilization": round(sum(edge_util) / total, 3),
        "experience_reused_count": exp_reused,
        "experience_reuse_rate": round(exp_reused / 4.0, 3),  # 4 tasks had prior experience
    }


stats_d = compute_condition_stats(cond_d_runs)
stats_e = compute_condition_stats(cond_e_runs)

# Static graph baseline loc efficiency from M2
static_graph_loc_eff = m2_summary["conditions"]["GRAPH"]["avg_localization_efficiency"]

# Structural Experience Gain: LocEff(D or E) - LocEff(B)
stats_d["structural_experience_gain"] = round(stats_d["avg_localization_efficiency"] - static_graph_loc_eff, 3)
stats_e["structural_experience_gain"] = round(stats_e["avg_localization_efficiency"] - static_graph_loc_eff, 3)

summary = {
    "benchmark": "M3_EXPERIENCE_CONDITIONED_CODE_GRAPH_BENCHMARK",
    "model": "models/gemma-4-26b-a4b-it",
    "repository": "scaled_repo (hydra_mesh, 59 files)",
    "task_count": 5,
    "conditions": {
        "A_STATELESS": m2_summary["conditions"]["STATELESS"],
        "B_STATIC_GRAPH": m2_summary["conditions"]["GRAPH"],
        "C_GRAPH_EXP_CONTEXT": m2_summary["conditions"]["GRAPH_EXPERIENCE"],
        "D_EXP_CONDITIONED_GRAPH": stats_d,
        "E_EXP_GRAPH_NO_TEXT": stats_e,
    },
    "per_task_results": {},
}

for t in tasks:
    m2_t = m2_summary["per_task_results"][t]
    d_m = cond_d_runs[t]["metrics"]
    e_m = cond_e_runs[t]["metrics"]

    summary["per_task_results"][t] = {
        "A_STATELESS": m2_t.get("STATELESS"),
        "B_STATIC_GRAPH": m2_t.get("GRAPH"),
        "C_GRAPH_EXP_CONTEXT": m2_t.get("GRAPH_EXPERIENCE"),
        "D_EXP_CONDITIONED_GRAPH": {
            "status": cond_d_runs[t]["status"],
            "success": d_m["task_success"],
            "tool_calls": d_m["tool_calls"],
            "searches": d_m["search_count"],
            "files_inspected": d_m["files_read"],
            "test_runs": d_m["test_runs"],
            "execution_time": d_m["execution_time"],
            "localization_efficiency": d_m["repository_localization_efficiency"],
            "experience_edge_utilization": d_m.get("experience_guided_edge_utilization", 0.0),
            "experience_edges_count": d_m.get("experience_edges_count", 0),
            "experience_influence": d_m.get("experience_influence", "NONE"),
        },
        "E_EXP_GRAPH_NO_TEXT": {
            "status": cond_e_runs[t]["status"],
            "success": e_m["task_success"],
            "tool_calls": e_m["tool_calls"],
            "searches": e_m["search_count"],
            "files_inspected": e_m["files_read"],
            "test_runs": e_m["test_runs"],
            "execution_time": e_m["execution_time"],
            "localization_efficiency": e_m["repository_localization_efficiency"],
            "experience_edge_utilization": e_m.get("experience_guided_edge_utilization", 0.0),
            "experience_edges_count": e_m.get("experience_edges_count", 0),
            "experience_influence": e_m.get("experience_influence", "NONE"),
        },
    }

out_path = RESULTS_DIR / "m3_summary.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2)

print(f"Generated {out_path} successfully.")
print("Condition D Stats:", json.dumps(stats_d, indent=2))
print("Condition E Stats:", json.dumps(stats_e, indent=2))
