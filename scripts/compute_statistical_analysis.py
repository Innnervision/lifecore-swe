"""
compute_statistical_analysis.py

Computes mean±std and pairwise statistical significance tests across
LIFECORE-SWE benchmark conditions.

Works in two modes:
  1. EXISTING data mode (default): loads the pre-computed M3 per-task JSON
     result files already in experiments/results/ and runs statistics over them.
     Each condition has 5 observations (one per sequential task).

  2. MULTI-RUN mode (--runs N): assumes run_real_repo_benchmark.py or
     run_m3_sequence_experiment.py was executed with --runs N, giving N
     independent replicates per task/condition.

Statistical tests performed:
  - Welch's t-test (unequal variance) between every condition pair
  - Wilcoxon signed-rank test (non-parametric, paired) between Condition B
    and Condition E on execution time and tool calls
  - Cohen's d effect size for all significant pairs
  - Bonferroni correction for multiple comparisons

Outputs:
  - Printed table of mean±std per condition
  - Printed significance matrix (p-values)
  - JSON file: experiments/results/statistical_analysis.json

Usage:
    # Analyse existing M3 results (no extra runs needed)
    python scripts/compute_statistical_analysis.py

    # Analyse real-repo multi-run results
    python scripts/compute_statistical_analysis.py --source real_repo --runs 3
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT   = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "experiments" / "results"

# ---------------------------------------------------------------------------
# Statistical helpers (stdlib only — no scipy required)
# ---------------------------------------------------------------------------

def mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def variance(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def std(xs: List[float]) -> float:
    return math.sqrt(variance(xs))


def welch_t_test(a: List[float], b: List[float]) -> Tuple[float, float]:
    """
    Welch's t-test for two independent samples with unequal variances.
    Returns (t_statistic, p_value).
    Uses a normal approximation for the p-value (accurate for n>=5).
    """
    if len(a) < 2 or len(b) < 2:
        return (float("nan"), float("nan"))

    m_a, m_b   = mean(a), mean(b)
    var_a, var_b = variance(a), variance(b)
    n_a, n_b   = len(a), len(b)

    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        return (0.0, 1.0)

    t = (m_a - m_b) / se

    # Welch-Satterthwaite degrees of freedom
    num   = (var_a / n_a + var_b / n_b) ** 2
    denom = ((var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1))
    df    = num / denom if denom > 0 else min(n_a, n_b) - 1

    # Two-tailed p-value via normal approximation (good for df > 10)
    # Using complementary error function approximation
    p = _t_to_p(t, df)
    return (round(t, 4), round(p, 4))


def wilcoxon_signed_rank(a: List[float], b: List[float]) -> Tuple[float, float]:
    """
    Wilcoxon signed-rank test (non-parametric, paired).
    Returns (W_statistic, p_value).
    """
    if len(a) != len(b) or len(a) < 4:
        return (float("nan"), float("nan"))

    diffs = [x - y for x, y in zip(a, b) if x != y]
    if not diffs:
        return (0.0, 1.0)

    abs_diffs = sorted(enumerate(abs(d) for d in diffs), key=lambda x: x[1])
    ranks = {i: r + 1 for r, (i, _) in enumerate(abs_diffs)}

    W_plus  = sum(ranks[i] for i, d in enumerate(diffs) if d > 0)
    W_minus = sum(ranks[i] for i, d in enumerate(diffs) if d < 0)
    W       = min(W_plus, W_minus)
    n       = len(diffs)

    # Normal approximation (valid for n >= 10; use with caution for small n)
    mu    = n * (n + 1) / 4
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    if sigma == 0:
        return (W, 1.0)

    z = (W - mu) / sigma
    p = 2 * _norm_sf(abs(z))   # two-tailed
    return (round(W, 4), round(p, 4))


def cohens_d(a: List[float], b: List[float]) -> float:
    """Cohen's d effect size."""
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    pooled_std = math.sqrt((variance(a) + variance(b)) / 2)
    if pooled_std == 0:
        return 0.0
    return round((mean(a) - mean(b)) / pooled_std, 4)


def _norm_sf(z: float) -> float:
    """Survival function (1 - CDF) of standard normal using erfc."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def _t_to_p(t: float, df: float) -> float:
    """Two-tailed p-value from t-statistic using normal approximation."""
    # For large df, t approaches normal
    if df > 30:
        return 2 * _norm_sf(abs(t))
    # For smaller df, use a simple polynomial approximation of the t-CDF
    # (accurate to ~0.01 for df >= 5)
    x = df / (df + t * t)
    # Regularized incomplete beta function approximation
    p = _ibeta(df / 2, 0.5, x)
    return min(1.0, max(0.0, round(p, 4)))


def _ibeta(a: float, b: float, x: float) -> float:
    """Rough regularized incomplete beta function via continued fraction (6 terms)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta  = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front  = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta)
    # Lentz continued fraction
    cf = _betacf(a, b, x)
    return front * cf / a


def _betacf(a: float, b: float, x: float, iters: int = 100) -> float:
    """Continued fraction for incomplete beta via modified Lentz."""
    FPMIN = 1e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, iters + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-7:
            break
    return h


def bonferroni_threshold(n_tests: int, alpha: float = 0.05) -> float:
    return alpha / n_tests


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

CONDITION_FILES = {
    "A_STATELESS": [
        f"m2_stateless_seq-task-{i}.json" for i in range(1, 6)
    ],
    "B_STATIC_GRAPH": [
        f"m2_graph_seq-task-{i}.json" for i in range(1, 6)
    ],
    "C_GRAPH_EXP_TEXT": [
        f"m2_graph_experience_seq-task-{i}.json" for i in range(1, 6)
    ],
    "D_EXP_CONDITIONED": [
        f"m3_exp_conditioned_graph_seq-task-{i}.json" for i in range(1, 6)
    ],
    "E_EXP_GRAPH_NO_TEXT": [
        f"m3_exp_graph_no_text_seq-task-{i}.json" for i in range(1, 6)
    ],
}

METRICS_OF_INTEREST = [
    "execution_time",
    "tool_calls",
    "search_count",
    "total_input_tokens",
    "total_output_tokens",
    "repository_localization_efficiency",
]


def load_m3_data() -> Dict[str, Dict[str, List[float]]]:
    """Load per-task M3 result JSONs and extract metrics per condition."""
    data: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

    for cond, files in CONDITION_FILES.items():
        for fname in files:
            fpath = RESULTS_DIR / fname
            if not fpath.exists():
                continue
            try:
                rec = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue

            # Results may be nested under "metrics" or flat
            metrics = rec.get("metrics", rec)
            for metric in METRICS_OF_INTEREST:
                val = metrics.get(metric)
                if val is not None:
                    try:
                        data[cond][metric].append(float(val))
                    except (TypeError, ValueError):
                        pass

    return data


def load_real_repo_data(n_runs: int) -> Dict[str, Dict[str, List[float]]]:
    """Load real_repo multi-run results."""
    real_dir  = RESULTS_DIR / "real_repo"
    data: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

    if not real_dir.exists():
        print(f"[WARN] Real repo results not found at {real_dir}")
        return data

    for fpath in sorted(real_dir.glob("real_*.json")):
        if "summary" in fpath.name:
            continue
        try:
            rec = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            continue

        cond    = rec.get("condition", "UNKNOWN")
        metrics = rec.get("metrics", rec)
        for metric in METRICS_OF_INTEREST:
            val = metrics.get(metric)
            if val is not None:
                try:
                    data[cond][metric].append(float(val))
                except (TypeError, ValueError):
                    pass

    return data


# ---------------------------------------------------------------------------
# Analysis runner
# ---------------------------------------------------------------------------

def run_analysis(data: Dict[str, Dict[str, List[float]]],
                 label: str) -> Dict:
    """Run full statistical analysis on loaded data."""
    conditions = sorted(data.keys())
    print(f"\n{'='*70}")
    print(f"  Statistical Analysis: {label}")
    print(f"{'='*70}")

    # ── 1. Descriptive statistics ──────────────────────────────────────────
    descriptive: Dict[str, Dict[str, Dict]] = {}
    for cond in conditions:
        descriptive[cond] = {}
        for metric in METRICS_OF_INTEREST:
            vals = data[cond].get(metric, [])
            if not vals:
                descriptive[cond][metric] = {"n": 0}
                continue
            descriptive[cond][metric] = {
                "n":    len(vals),
                "mean": round(mean(vals), 3),
                "std":  round(std(vals), 3),
                "min":  round(min(vals), 3),
                "max":  round(max(vals), 3),
            }

    # Print execution_time and tool_calls summary
    print(f"\n{'─'*70}")
    print(f"  Descriptive Statistics")
    print(f"{'─'*70}")
    for metric in ["execution_time", "tool_calls", "total_input_tokens"]:
        print(f"\n  {metric}:")
        print(f"    {'Condition':<28} {'n':>4} {'mean':>9} {'±std':>9} {'min':>9} {'max':>9}")
        print(f"    {'─'*62}")
        for cond in conditions:
            d = descriptive[cond].get(metric, {})
            if d.get("n", 0) == 0:
                print(f"    {cond:<28} {'N/A':>4}")
                continue
            print(f"    {cond:<28} {d['n']:>4} {d['mean']:>9.2f} {d['std']:>9.2f} "
                  f"{d['min']:>9.2f} {d['max']:>9.2f}")

    # ── 2. Pairwise significance tests ────────────────────────────────────
    pairs = [(a, b) for i, a in enumerate(conditions)
             for b in conditions[i+1:]]
    n_tests = len(pairs)
    bonf    = bonferroni_threshold(n_tests)

    significance: Dict[str, Dict] = {}
    print(f"\n{'─'*70}")
    print(f"  Pairwise Welch t-tests (Bonferroni α={bonf:.4f} for {n_tests} tests)")
    print(f"{'─'*70}")

    for metric in ["execution_time", "tool_calls"]:
        print(f"\n  {metric}:")
        print(f"    {'Pair':<45} {'t':>8} {'p':>8} {'d':>7} {'sig':>5}")
        print(f"    {'─'*73}")
        for (ca, cb) in pairs:
            vals_a = data[ca].get(metric, [])
            vals_b = data[cb].get(metric, [])
            t, p   = welch_t_test(vals_a, vals_b)
            d      = cohens_d(vals_a, vals_b)
            sig    = "***" if p < bonf else ("*" if p < 0.05 else "ns")
            pair_key = f"{ca} vs {cb}"
            significance.setdefault(metric, {})[pair_key] = {
                "t": t, "p": p, "cohens_d": d, "significant": p < 0.05
            }
            if math.isnan(t):
                print(f"    {pair_key:<45} {'N/A':>8}")
                continue
            print(f"    {pair_key:<45} {t:>8.3f} {p:>8.4f} {d:>7.3f} {sig:>5}")

    # ── 3. Wilcoxon signed-rank: B vs E (the key comparison) ─────────────
    print(f"\n{'─'*70}")
    print(f"  Wilcoxon Signed-Rank Test: B_STATIC_GRAPH vs E_EXP_GRAPH_NO_TEXT")
    print(f"  (non-parametric, paired by task — key paper claim)")
    print(f"{'─'*70}")

    wilcoxon_results: Dict[str, Dict] = {}
    for metric in ["execution_time", "tool_calls", "search_count"]:
        b_vals = data.get("B_STATIC_GRAPH", {}).get(metric, [])
        e_vals = data.get("E_EXP_GRAPH_NO_TEXT", {}).get(metric, [])
        if not b_vals or not e_vals:
            print(f"  {metric}: insufficient data")
            continue
        # Align lengths
        n = min(len(b_vals), len(e_vals))
        W, p = wilcoxon_signed_rank(b_vals[:n], e_vals[:n])
        sig  = "***" if p < 0.05 else "ns"
        d    = cohens_d(b_vals[:n], e_vals[:n])
        wilcoxon_results[metric] = {"W": W, "p": p, "cohens_d": d,
                                     "n_pairs": n, "significant": p < 0.05}
        b_m, e_m = mean(b_vals[:n]), mean(e_vals[:n])
        direction = "E faster" if e_m < b_m else "B faster"
        print(f"  {metric:<35}  W={W:6.1f}  p={p:.4f}  d={d:+.3f}  {sig}  "
              f"({direction}:  B={b_m:.1f} → E={e_m:.1f})")

    # ── 4. Token count comparison: C vs E ─────────────────────────────────
    print(f"\n{'─'*70}")
    print(f"  Token Count Comparison: C_GRAPH_EXP_TEXT vs E_EXP_GRAPH_NO_TEXT")
    print(f"  (core efficiency claim: structural memory uses fewer tokens)")
    print(f"{'─'*70}")

    token_comparison: Dict[str, Dict] = {}
    for metric in ["total_input_tokens", "total_output_tokens"]:
        c_vals = data.get("C_GRAPH_EXP_TEXT", {}).get(metric, [])
        e_vals = data.get("E_EXP_GRAPH_NO_TEXT", {}).get(metric, [])
        if not c_vals or not e_vals:
            # Provide a note if token data isn't populated yet
            print(f"  {metric}: not yet available (requires live Gemma 4 runs with "
                  f"token logging enabled)")
            continue
        n = min(len(c_vals), len(e_vals))
        t, p = welch_t_test(c_vals[:n], e_vals[:n])
        d    = cohens_d(c_vals[:n], e_vals[:n])
        sig  = "***" if p < 0.05 else "ns"
        c_m, e_m = mean(c_vals[:n]), mean(e_vals[:n])
        reduction = ((c_m - e_m) / c_m * 100) if c_m > 0 else 0.0
        token_comparison[metric] = {
            "C_mean": c_m, "E_mean": e_m,
            "reduction_pct": round(reduction, 1),
            "t": t, "p": p, "cohens_d": d,
        }
        print(f"  {metric:<35}  C={c_m:.0f}  E={e_m:.0f}  "
              f"reduction={reduction:.1f}%  p={p:.4f}  {sig}")

    # ── 5. Assemble output ─────────────────────────────────────────────────
    output = {
        "label":              label,
        "conditions_analysed": conditions,
        "n_observations_per_condition": {
            c: {m: len(data[c].get(m, [])) for m in METRICS_OF_INTEREST}
            for c in conditions
        },
        "bonferroni_alpha": bonf,
        "n_comparisons":    n_tests,
        "descriptive":      descriptive,
        "welch_t_tests":    significance,
        "wilcoxon_b_vs_e":  wilcoxon_results,
        "token_comparison": token_comparison,
    }

    return output


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LIFECORE-SWE Statistical Analysis")
    parser.add_argument(
        "--source",
        choices=["m3", "real_repo", "both"],
        default="both",
        help="Which results to analyse (default: both)")
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per condition (for real_repo multi-run mode)")
    args = parser.parse_args()

    all_outputs = {}

    if args.source in ("m3", "both"):
        m3_data = load_m3_data()
        if m3_data:
            out = run_analysis(m3_data, "M3 Sequential Benchmark (hydra_mesh)")
            all_outputs["m3_hydra_mesh"] = out
        else:
            print("[WARN] No M3 data found in experiments/results/")

    if args.source in ("real_repo", "both"):
        rr_data = load_real_repo_data(args.runs)
        if rr_data:
            out = run_analysis(rr_data, "Real Repository Benchmark (Flask v3.0.3)")
            all_outputs["real_repo_flask"] = out
        else:
            print("[INFO] No real_repo data yet — run setup_real_repo_benchmark.py "
                  "then run_real_repo_benchmark.py first")

    # Save to JSON
    out_path = RESULTS_DIR / "statistical_analysis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_outputs, indent=2, default=str),
                        encoding="utf-8")

    print(f"\n{'='*70}")
    print(f"  Results saved: {out_path}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
