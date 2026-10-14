# LIFECORE-SWE M5-D Experiment Report

## Milestone M5-D: Integrating Verified Resource Evidence into Reasoning & Multi-Stream Context

**Status**: COMPLETED  
**Date**: September 30, 2026  
**System**: LIFECORE-SWE Multi-Stream Reasoning & Context Integration Layer  
**Test Suite Status**: 121/121 tests passing (110 existing M0–M5-C tests + 11 new M5-D tests)  

---

### 1. Objective

Milestone **M5-D** implements the evidence synthesis and context integration layer that bridges external software resources into the autonomous agent's reasoning loop.

M5-D establishes explicit **truth boundaries** between four distinct knowledge streams:
1. Internal code ground truth (Repository AST Code Graph)
2. Verified positive experience (Reinforced edge priors)
3. Attributed negative experience (Failure anti-priors)
4. External software resources (Advisory documentation, specifications, and examples)

The core requirement is ensuring that Gemma 4 never confuses advisory external documentation with verified repository code facts, and that unverified external resources are never represented as authoritative truth.

---

### 2. Research Question

> *"Can external software resource evidence be formatted, bounded, and injected into the agent reasoning context with unambiguous truth boundaries so that Gemma 4 distinguishes internal code facts, positive experiences, negative failure anti-priors, and external advisory documentation without treating unverified resources as ground truth?"*

**Findings**:
Yes. By designing `ResourceContextBuilder` and `UnifiedWorldModelContextBuilder`, external knowledge items retrieved from the Resource Graph (M5-C) are formatted with explicit, machine-readable headers, verification states, confidence ratings, provenance audit markers, and prominent disclaimers. If a resource is unverified (`UNVERIFIED` or `RETRIEVED`), an advisory warning is embedded directly in its section; if contradictory, a quarantine warning is raised. The unified context cleanly demarks internal code ground truth from external advisory material.

---

### 3. Scope & Absolute Separation Rule

- **Included**:
  - `ResourceContextBuilder` formatting external evidence with truth boundary warnings, provenance, version, status, and budget truncation.
  - `UnifiedWorldModelContextBuilder` assembling the 4 distinct knowledge streams into a coherent prompt context.
  - Integration with `SWEAgent` (`enable_resource_graph`, pre-retrieval, state observation injection, and hypothesis context injection).
  - Explicit warning mechanisms for unverified resources (`UNVERIFIED` / `RETRIEVED`) and contradicted resources (`CONTRADICTED`).
  - Unit tests verifying truth boundaries, formatting, budget limits, agent execution, and security isolation.
- **Explicitly Excluded**:
  - **NO live internet / network fetching** in this milestone (reserved for M5-E).
  - **NO arbitrary web search or package downloads**.
  - **NO fine-tuning or modification of Gemma model weights**.
  - **NO mutation of AST code graph, positive experience overlay, or negative failure overlay**.

---

### 4. Architecture: 4-Stream Truth Boundary

The unified reasoning architecture synthesizes four separate trust domains before presenting evidence to the model:

```
                          TASK QUERY
                              │
       ┌──────────────────────┼──────────────────────┐
       │                      │                      │
       ▼                      ▼                      ▼
[INTERNAL CODE]       [SWE EXPERIENCE]       [EXTERNAL RESOURCES]
AST Code Graph        Experience Overlays    Resource Graph
• Repository files    • Positive priors      • Official docs
• Class / functions   • Negative penalties   • Package specs
• Calls / imports     • Failure attribution  • Code examples
       │                      │                      │
       ▼                      ▼                      ▼
  (Stream 1)             (Streams 2 & 3)        (Stream 4)
Internal Code          Verified Positive      External Resource
Evidence               & Negative Prior       Advisory Evidence
       │                      │                      │
       └──────────────────────┬──────────────────────┘
                              ▼
           UnifiedWorldModelContextBuilder
           [Strict Truth Boundary Disclaimer]
           1. Live code is absolute ground truth.
           2. Positive experience gives structural priors.
           3. Negative experience gives failure avoidance.
           4. External resources are strictly advisory.
                              │
                              ▼
                           GEMMA 4
                (Planning / Action / Reasoning)
```

---

### 5. Context Builder Implementation

Implemented in `lifecore_swe/resources/context_builder.py`:

#### 1. `ResourceContextBuilder`
Formats external evidence items returned by `ResourceGraphRetriever`:
- **Truth Boundary Header**:
  ```
  === EXTERNAL RESOURCE EVIDENCE ===
  TRUTH BOUNDARY: External resources are advisory reference material. Internal repository code and ground truth ALWAYS supersede external references.
  STATUS INVARIANT: Unverified external documentation is NOT verified internal code.
  ```
- **Item Fields**:
  - `TITLE`: Human-readable entity title
  - `TYPE`: `ResourceNodeType` (e.g. `API`, `DOCUMENTATION`, `PACKAGE`)
  - `VERSION`: Declared or observed version
  - `STATUS`: Lifecycle state (`VERIFIED`, `VALIDATED`, `RETRIEVED`, `STALE`, `CONTRADICTED`)
  - `SOURCE`: Upstream source identifier (`python-docs`, `pypi`)
  - `CONFIDENCE`: Exact confidence $[0.0, 1.0]$
  - `RELEVANCE`: Calculated relevance score $[0.0, 1.0]$
  - `PROVENANCE`: Audit chain (ID, source type, retrieval method, trust level)
  - `FRESHNESS`: Freshness rating (`FRESH`, `AGING`, `STALE`, `UNKNOWN`)
  - `RELATIONSHIPS`: Connected graph edges (e.g. `DOCUMENTS->package:ast`)
- **Warning Invariants**:
  - If status is `UNVERIFIED` or `RETRIEVED`:
    `WARNING: Resource is UNVERIFIED / RETRIEVED only. Do NOT treat as ground-truth repository behavior.`
  - If status is `CONTRADICTED`:
    `CRITICAL WARNING: CONTRADICTION DETECTED. Resource asserts claims conflicting with verified ground truth.`
  - If status is `VERIFIED`:
    `VERIFICATION NOTE: Resource has been explicitly validated against repository ground truth.`
- **Budget Control**: Cleanly enforces character limits (`max_chars`, default: 2500) and appends truncation notices if budget is exceeded.

#### 2. `UnifiedWorldModelContextBuilder`
Synthesizes all 4 evidence streams into a structured prompt context with explicit section dividers:
- `### STREAM 1: INTERNAL CODE EVIDENCE (AST REPOSITORY GRAPH)`
- `### STREAM 2: VERIFIED POSITIVE EXPERIENCE`
- `### STREAM 3: ATTRIBUTED NEGATIVE EXPERIENCE (FAILURE AVOIDANCE)`
- `### STREAM 4: EXTERNAL RESOURCE EVIDENCE (PROVENANCE & VERSION AWARE)`

---

### 6. Agent Integration & Reasoning Flow

Integrated into `SWEAgent` (`lifecore_swe/agent/agent.py`):
1. **Parameter Integration**: `SWEAgent` supports `enable_resource_graph: bool = False`, `resource_graph: Optional[ResourceGraph]`, `resource_retriever: Optional[ResourceGraphRetriever]`.
2. **Pre-Reasoning Retrieval**: When `enable_resource_graph=True`, the agent queries `resource_retriever.retrieve(...)` prior to entering the execution loop.
3. **Observation & State Injection**: The formatted context is recorded in `state.observations` and passed to `select_action` in `state_dict["resource_evidence"]`.
4. **Hypothesis Formulation**: In `formulate_hypothesis` and `recover`, `context["resource_evidence"]` is supplied to `model.reason(...)`.
5. **Final Trajectory & Results**: `result["resource_result"]` and `result["resource_evidence"]` capture complete external citations for reproducibility.

---

### 7. Security Boundary Isolation Guarantees

In accordance with core LIFECORE-SWE principles:
- Running `SWEAgent` with `enable_resource_graph=True` produces **ZERO** side-effects on:
  - Repository AST nodes and edges in `GraphIndex`
  - Persistent positive experience overlay (`ExperienceGraphOverlay`)
  - Attributed negative failure overlay (`NegativeGraphOverlay`)
  - Local repository files (unless explicitly edited by an action)
- Unit test `test_agent_security_boundary_invariance` explicitly confirms that code graph node counts and overlay memory stores remain identical before and after resource-augmented agent runs.

---

### 8. Unit Test Results

Unit tests for M5-D are implemented in `tests/test_resource_context_and_reasoning.py`:

| # | Test Name | Target Subsystem / Property | Status |
|---|---|---|---|
| 1 | `test_resource_context_builder_empty` | Clean fallback formatting on empty result | PASSED |
| 2 | `test_resource_context_builder_formatting` | Exact display of title, type, version, status, source, confidence, relevance | PASSED |
| 3 | `test_resource_context_builder_unverified_warning` | Unverified advisory warning display | PASSED |
| 4 | `test_resource_context_builder_contradiction_warning` | Contradiction critical warning display | PASSED |
| 5 | `test_resource_context_builder_verified_note` | Ground-truth verification note display | PASSED |
| 6 | `test_resource_context_builder_budget_enforcement` | Character budget limit & clean truncation | PASSED |
| 7 | `test_unified_world_model_context_builder_streams` | 4-stream evidence separation & core principles | PASSED |
| 8 | `test_unified_world_model_context_builder_budget` | Total unified context budget enforcement | PASSED |
| 9 | `test_agent_resource_graph_integration` | SWEAgent end-to-end execution with resource graph | PASSED |
| 10 | `test_agent_truth_labeling_isolation` | Observation log contains explicit truth boundary | PASSED |
| 11 | `test_agent_security_boundary_invariance` | Code graph & experience overlay invariance | PASSED |

**M5-D Test Suite**: 11 passed, 0 failed.

---

### 9. Historical M0–M5-C Regression Results

Running the entire test suite confirms complete backward compatibility:

| Milestone | Subsystem Tested | Tests Passed | Status |
|---|---|---|---|
| M0 | Bootstrap & SWE Tool Sandbox (`test_core.py`, `test_agent.py`, `test_tools.py`) | 9 | PASSED |
| M1 | Gemma 4 Adapter & AST Code Graph (`test_gemma_adapter.py`, `test_codegraph.py`, `test_retrieval.py`) | 18 | PASSED |
| M2 | Persistent Episodic Experience Memory (`test_experience.py`) | 9 | PASSED |
| M3 | Experience-Conditioned Graph Overlay (`test_experience_graph.py`) | 10 | PASSED |
| M4 | Failure-Aware Negative Overlay (`test_negative_experience.py`) | 10 | PASSED |
| M5-A | Resource Intelligence Foundation (`test_resources.py`) | 24 | PASSED |
| M5-B | Offline Ingestion & Validation (`test_adapters_and_validation.py`) | 15 | PASSED |
| M5-C | Resource Graph & Relational Retrieval (`test_resource_graph.py`) | 15 | PASSED |
| **M5-D** | **Context Building & Reasoning Integration (`test_resource_context_and_reasoning.py`)** | **11** | **PASSED** |
| **Total** | **All Milestones (M0 through M5-D)** | **121 / 121** | **ALL GREEN** |

Execution time: **4.86 seconds**.

---

### 10. Known Limitations & Scientific Boundaries

1. **Context Window Allocation**: External resource evidence is allocated a bounded character budget (default: 2500 chars) to prevent context flooding and ensure repository code evidence receives priority.
2. **Deterministic Offline Knowledge**: All external evidence currently stems from validated offline graphs and mock adapters; live network access remains disabled.
3. **Rule-Based Truth Boundary**: Truth boundaries rely on explicit prompt formatting and warning disclaimers; adversarial prompt injections from malicious third-party docs remain an open research topic.

---

### 11. What M5-D Does NOT Claim

- M5-D does **NOT** claim that external resources universally solve software bugs.
- M5-D does **NOT** enable live network or internet access (reserved for M5-E).
- M5-D does **NOT** alter model weights or fine-tune Gemma.
- M5-D is strictly an **evidence formatting, truth-labeling, and context integration layer**.

---

### 12. Recommendation for M5-E

With multi-stream context integration and truth boundaries verified:
- **M5-E Proposed Focus**: Controlled Network & Resource Evaluation.
  - Test permission policy enforcement during controlled network requests.
  - Implement a `ControlledNetworkFetcher` gated strictly by `PermissionPolicy` (Level 0 default deny, Level 1 approved docs, Level 2 approved repos).
  - Ensure cloud metadata endpoints (`169.254.169.254`) and loopbacks remain strictly blocked.
  - Verify network safety under attempted privilege escalation.

---

*Report generated and verified on 2026-09-30 under /lifecore-swe/experiments/M5_D.md.*
