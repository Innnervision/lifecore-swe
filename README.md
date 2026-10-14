# LIFECORE-SWE

**Experience-Conditioned Code Graphs for Autonomous Software Engineering**

Research prototype accompanying the paper:
> *LIFECORE-SWE: Encoding Verified Agent Trajectories as Structural Priors Over Repository Graph Edges*
> Submitted to the Google DeepMind Gemma 4 Developer Agent Paper Track (Kaggle, 2026)

---

## Overview

LIFECORE-SWE investigates whether verified software-engineering agent experience can be encoded directly as weighted structural edges in a repository's AST code graph — replacing token-expensive narrative text injection with a latency-free structural prior.

The system is built in **5 research milestones**, each independently validated:

| Milestone | Contribution | Key Result |
|---|---|---|
| **M1C** | Deterministic AST graph-guided pre-retrieval | 0% → 100% task success on scaled repo; 3.7× speedup |
| **M2** | Persistent episodic experience memory | 75% experience reuse rate; 0 stale-memory regressions |
| **M3** | Experience-conditioned graph edge scoring | Structural-only memory (no text) matches accuracy at 36% lower latency |
| **M4** | Failure-aware negative edge penalties | −14.8% tool calls; ablation proves attribution filtering is critical |
| **M5** | Provenance-aware external resource graph | 121/121 tests passing; strict truth-boundary architecture |

---

## Repository Structure

```
lifecore-swe/
├── lifecore_swe/               # Core source packages
│   ├── agent/                  # SWEAgent loop, state machine, action dispatch
│   ├── codegraph/              # AST parser, GraphIndex, node/edge types
│   ├── experience/             # Episodic store, retriever, ranker (M2)
│   ├── experience_graph/       # Experience overlay, edge scorer (M3)
│   │   └── negative/          # Failure taxonomy, attribution, negative overlay (M4)
│   ├── retrieval/              # Deterministic graph retriever, context builder (M1C)
│   ├── resources/              # External resource graph, adapters, validator (M5)
│   ├── tools/                  # Agent tool sandbox (filesystem, test runner, verifier)
│   ├── trajectory/             # JSONL trajectory logger
│   └── verification/           # Independent patch verifier
├── tests/                      # 121 unit tests across all milestones
│   ├── test_codegraph.py       # M1B AST graph (8 tests)
│   ├── test_retrieval.py       # M1C graph retrieval (8 tests)
│   ├── test_experience.py      # M2 episodic memory (9 tests)
│   ├── test_experience_graph.py# M3 experience overlay (10 tests)
│   ├── test_negative_experience.py  # M4 negative overlay (10 tests)
│   ├── test_resources.py       # M5-A resource foundation (24 tests)
│   ├── test_adapters_and_validation.py  # M5-B ingestion (15 tests)
│   ├── test_resource_graph.py  # M5-C resource graph (15 tests)
│   └── test_resource_context_and_reasoning.py  # M5-D context (11 tests)
├── scripts/                    # Reproduction scripts for each milestone
│   ├── run_m1c_task201_baseline.py
│   ├── run_m1c_task201_graph.py
│   ├── run_m2_sequence_experiment.py
│   ├── run_m3_sequence_experiment.py
│   ├── run_m4_failure_benchmark.py
│   └── eval_retrieval_benchmark.py
├── fixtures/                   # Controlled test repositories
│   ├── buggy_repo/             # 4-file event pipeline (M0.1, M1C)
│   └── scaled_repo/            # 59-file hydra_mesh (M1C–M4)
│       └── hydra_mesh/         # 7-subsystem distributed pipeline framework
└── experiments/                # All experiment outputs
    ├── results/                # JSON summaries per milestone/condition
    ├── experience/             # SQLite experience stores (M2)
    └── experience_graph/       # SQLite overlay DBs (M3, M4)
```

---

## Setup

**Requirements:** Python 3.12+, pip

```bash
# Clone / navigate to the project
cd lifecore-swe

# Install in editable mode (no external dependencies required)
pip install -e .

# Run the full test suite (121 tests, ~5 seconds)
PYTHONPATH=. pytest -v tests/
```

No GPU, no cloud API key, and no internet access are required to run the test suite or inspect experiment artifacts.

To reproduce benchmark runs that invoke Gemma 4, a Google GenAI API key is required:

```bash
export GOOGLE_API_KEY="your-key-here"
```

---

## Reproducing Experiments

### M1C — Graph-Guided Retrieval Benchmark

```bash
# Deterministic retrieval benchmark (no LLM, sub-3ms latency)
PYTHONPATH=. python scripts/eval_retrieval_benchmark.py

# End-to-end: baseline vs graph-guided on 59-file repo
PYTHONPATH=. python scripts/run_m1c_task201_baseline.py
PYTHONPATH=. python scripts/run_m1c_task201_graph.py
```

### M2 — Persistent Experience Memory

```bash
# Full 5-task sequential benchmark (3 conditions)
PYTHONPATH=. python scripts/run_m2_sequence_experiment.py

# Stale experience lifecycle test
PYTHONPATH=. python scripts/run_m2_stale_experiment.py
```

### M3 — Experience-Conditioned Graph

```bash
# 5 conditions × 5 tasks (Condition E is the key ablation)
PYTHONPATH=. python scripts/run_m3_sequence_experiment.py --condition EXP_CONDITIONED_GRAPH
PYTHONPATH=. python scripts/run_m3_sequence_experiment.py --condition EXP_GRAPH_NO_TEXT
```

### M4 — Failure-Aware Graph

```bash
# 5 conditions × 4 tasks + 2 ablations
PYTHONPATH=. python scripts/run_m4_failure_benchmark.py
```

---

## Key Experimental Artifacts

All pre-computed results are included and do not require re-running:

| File | Contents |
|---|---|
| `experiments/results/m3_summary.json` | M3 full per-task, per-condition results |
| `experiments/results/m4_summary.json` | M4 results including ablation conditions |
| `experiments/results/retrieval_benchmark_summary.json` | M1C retrieval latency and recall |
| `experiments/experience_graph/m3_exp_conditioned_graph_overlay.db` | SQLite: Condition D overlay (M3) |
| `experiments/experience_graph/m3_exp_graph_no_text_overlay.db` | SQLite: Condition E overlay (M3) |
| `experiments/experience_graph/m4_positive_overlay.db` | SQLite: M4 positive edge weights |
| `experiments/experience_graph/m4_negative_overlay.db` | SQLite: M4 negative edge penalties |
| `experiments/experience/m2_condition_c.db` | SQLite: M2 episodic experience store |

---

## Central Finding

**Condition E (Experience-Conditioned Graph, No Text)** achieves 100% task success across all 5 sequential SWE tasks with:
- Zero filesystem search queries
- 115.5s average execution time (vs 136.5s for static graph, vs 141.9s for graph+text)
- No raw experience text injected into the LLM prompt

This demonstrates that verified agent experience can be encoded as structural graph weights rather than narrative prompt context — achieving the same accuracy at significantly lower latency and token overhead.

---

## Model

All benchmark conditions use **Gemma 4** (`models/gemma-4-26b-a4b-it`) via Google GenAI SDK 2.25.0, temperature=0.1, structured JSON output.

---

## Citation

If you build on this work, please cite:

```
LIFECORE-SWE: Experience-Conditioned Code Graphs for Autonomous Software Engineering.
Submitted to the Google DeepMind Gemma 4 Developer Agent Paper Track, Kaggle, 2026.
```
