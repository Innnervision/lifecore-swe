# LIFECORE-SWE M5-C Experiment Report

## Milestone M5-C: Provenance-Aware Resource Graph & Deterministic Resource Retrieval

**Status**: COMPLETED  
**Date**: September 30, 2026  
**System**: LIFECORE-SWE External Resource Graph & Retrieval Subsystem  
**Test Suite Status**: 110/110 tests passing (95 existing M0–M5-B tests + 15 new M5-C tests)  

---

### 1. Objective

Milestone **M5-C** implements the **Resource Graph** and deterministic, bounded resource retrieval for external software knowledge within LIFECORE-SWE.

Building on the provenance data model (M5-A) and offline validation pipeline (M5-B), M5-C structures validated external software entities into a dedicated relational graph with typed entities and relationships, multi-attribute ranking, graph expansion, and bounded evidence context generation.

---

### 2. Research Question

> *"Can external software knowledge be represented as a provenance-aware, version-aware graph and retrieved as bounded evidence without contaminating the internal repository, positive-experience, or negative-experience graphs?"*

**Findings**:
Yes. External knowledge can be completely structured into an associative relational graph (`ResourceGraph`) containing discrete entity nodes (`PACKAGE`, `DOCUMENTATION`, `API`, `EXAMPLE`, `SOURCE`) and explicit directed edges (`SOURCED_FROM`, `DOCUMENTS`, `VERSION_OF`, `EXAMPLE_FOR`, `DEPENDS_ON`, `REFERENCES`). By employing deterministic multi-signal ranking and graph traversal, the agent retrieves bounded, high-relevance evidence without any direct mutation or contamination of the internal repository AST code graph (`GraphIndex`), positive experience graph, or negative failure penalties.

---

### 3. Scope & Absolute Separation Rule

- **Included**:
  - Entity schema (`ResourceNodeType` with 12 node types, `ResourceNode`)
  - Relational schema (`ResourceEdgeType` with 10 edge types, `ResourceEdge`)
  - In-memory relational index with bidirectional adjacency (`ResourceGraph`)
  - Automated relational graph constructor (`ResourceGraphBuilder`)
  - Multi-attribute deterministic ranker (`ResourceRanker`) integrating 7 scoring signals
  - Deterministic graph retriever (`ResourceGraphRetriever`) supporting multi-hop expansion
  - Provenance, freshness, version, and status filtering
  - Bounded context formatting (`format_compact_context`)
  - Security boundary assertions verifying internal graph invariance
- **Explicitly Excluded**:
  - **NO LLM / Gemma integration** in this milestone (reserved for M5-D).
  - **NO live internet / network fetching** (reserved for M5-E).
  - **NO mutation of internal repository code graph or experience overlays**.
  - **NO benchmark modifications**.

---

### 4. Resource Graph Architecture

The Resource Graph maintains complete structural separation from the internal repository code graph:

```
                    TASK QUERY
                        │
         ┌──────────────┴──────────────┐
         ▼                             ▼
    [INTERNAL WORLD]             [EXTERNAL WORLD]
   Static AST Code Graph         Resource Graph (M5-C)
         │                             │
   Experience Overlays                 ├─► Seed Node Matching
   (Positive / Negative)               ├─► Multi-Hop Graph Traversal
                                       ├─► Multi-Signal Ranking
                                       ├─► Provenance & Freshness Filtering
                                       └─► Bounded Evidence Selection
                                               │
                                               ▼
                                      Bounded External Context
```

---

### 5. Entity Types and Relational Edges

Implemented in `lifecore_swe/resources/graph/schema.py`:

- **Entity Types (`ResourceNodeType`)**:
  - `RESOURCE`: Generic external software asset.
  - `SOURCE`: Upstream source provider (e.g., `source:pypi`, `source:python-docs`).
  - `PACKAGE`: Software package entity (e.g., `package:requests`, `package:ast`).
  - `PACKAGE_VERSION`: Specific release version of a package.
  - `REPOSITORY`: External code repository (e.g., `repo:psf/requests`).
  - `DOCUMENTATION`: General API or module documentation.
  - `API`: Discrete function, method, or class contract reference.
  - `EXAMPLE`: Standalone code snippet or cookbook tutorial.
  - `ISSUE`: Issue tracker or bug report thread.
  - `COMMIT`: Version control revision.
  - `PAPER`: Research publication.
  - `BENCHMARK`: Evaluation suite or task set.

- **Relationship Types (`ResourceEdgeType`)**:
  - `SOURCED_FROM`: Links resource to its upstream origin source.
  - `DOCUMENTS`: Links documentation or API specs to target packages or repositories.
  - `VERSION_OF`: Links specific release versions to parent packages.
  - `REFERENCES`: Links nested or child resources to parent references.
  - `EXAMPLE_FOR`: Links illustrative code examples to functions or packages.
  - `DEPENDS_ON`: Links packages or resources to declared upstream dependencies.
  - `RELATED_TO`: General associative relationship.
  - `SUPERSEDES`: Links updated versions to obsolete or superseded records.
  - `CONTRADICTS`: Explicitly links conflicting assertions for quarantine.
  - `VALIDATED_BY`: Links resources to validating test suites or verifiers.

---

### 6. Graph Construction (`ResourceGraphBuilder`)

Implemented in `lifecore_swe/resources/graph/builder.py`:

The `ResourceGraphBuilder` converts discrete `ResourceRecord` and `ProvenanceRecord` sets into an indexed `ResourceGraph`:
1. Synthesizes canonical entity nodes for upstream sources (`source:{name}`), packages (`package:{name}`), and repositories (`repo:{name}`).
2. Injects discrete resource nodes mapping `record.resource_type` to `ResourceNodeType`.
3. Inters structural edges:
   - `SOURCED_FROM` linking each resource to its origin source.
   - `DOCUMENTS`, `VERSION_OF`, or `EXAMPLE_FOR` linking resources to package entities.
   - `DEPENDS_ON` linking packages to declared dependencies extracted from package metadata.
   - `REFERENCES` linking resources to parent hierarchy IDs.
   - `CONTRADICTS` or `SUPERSEDES` linking lifecycle transitions.

---

### 7. Deterministic Multi-Signal Ranking (`ResourceRanker`)

Implemented in `lifecore_swe/resources/graph/ranking.py`:

The ranking algorithm computes a normalized score in $[0.0, 1.0]$ across 7 deterministic dimensions:

$$\text{Score} = w_{\text{rel}} \cdot S_{\text{rel}} + w_{\text{auth}} \cdot S_{\text{auth}} + w_{\text{ver}} \cdot S_{\text{ver}} + w_{\text{fresh}} \cdot S_{\text{fresh}} + w_{\text{trust}} \cdot S_{\text{trust}} + w_{\text{stat}} \cdot S_{\text{stat}} + w_{\text{conf}} \cdot S_{\text{conf}}$$

Default weights:
- $w_{\text{rel}} = 0.30$: Lexical and symbol token overlap with task query.
- $w_{\text{auth}} = 0.15$: Authority tier (Official docs: 1.0, Package registry: 0.85, Verified repo: 0.75, Forums: 0.50).
- $w_{\text{ver}} = 0.15$: Version compatibility (Exact match: 1.0, Minor match: 0.85, Unversioned: 0.6, Mismatch: 0.1).
- $w_{\text{fresh}} = 0.10$: Freshness state (`FRESH`: 1.0, `AGING`: 0.6, `UNKNOWN`: 0.4, `STALE`: 0.1).
- $w_{\text{trust}} = 0.10$: Provenance trust (`VERIFIED_INTERNAL`: 1.0, `HIGH`: 0.9, `MEDIUM`: 0.7, `LOW`: 0.4, `UNTRUSTED`: 0.0).
- $w_{\text{stat}} = 0.15$: Verification status (`VERIFIED`: 1.0, `VALIDATED`: 0.85, `RETRIEVED`: 0.50, `UNVERIFIED`: 0.30, `STALE`: 0.20).
- $w_{\text{conf}} = 0.05$: Base confidence score $[0.0, 1.0]$.

**Critical Safety Penalty**:
Any resource marked `REJECTED` or `CONTRADICTED` is clamped strictly to $\text{Score} = 0.0$.

---

### 8. Bounded Evidence Retrieval (`ResourceGraphRetriever`)

Implemented in `lifecore_swe/resources/graph/retriever.py`:

The retrieval pipeline proceeds in 5 deterministic steps:
1. **Seed Identification**: Matches query tokens and target package against node titles, descriptions, and package symbols.
2. **Graph Expansion**: Recursively traverses forward and backward edges up to `max_depth` (default: 2 hops) to discover related documentation, dependencies, and code examples.
3. **Filtering**: Excludes unapproved node types, stale resources (if `allow_stale=False`), untrusted provenance (below `min_trust_level`), and contradicted/rejected entities.
4. **Scoring & Sorting**: Evaluates candidates via `ResourceRanker` and sorts descending by score with deterministic tie-breaking on `node_id`.
5. **Bounded Selection**: Returns at most `max_resources` (default: 5) items, formatted with compact context labels and provenance indicators.

---

### 9. Security Boundary Isolation Guarantees

In accordance with core LIFECORE-SWE principles:
- External resource graph construction, indexing, and retrieval operations are executed in an isolated memory space.
- Unit test `test_security_boundary_isolation_from_resource_graph` explicitly verifies that:
  - Repository AST nodes and edges in `GraphIndex` remain strictly invariant.
  - Positive experience weights in `ExperienceGraphOverlay` remain unchanged.
  - Negative failure penalties in `NegativeGraphOverlay` remain unchanged.
  - External entities (e.g. `package:requests`, `res_ast_doc`) are never inserted into the code graph.

---

### 10. Unit Test Results

Unit tests for M5-C are implemented in `tests/test_resource_graph.py`:

| # | Test Name | Target Subsystem / Property | Status |
|---|---|---|---|
| 1 | `test_resource_node_and_edge_schema` | Entity/edge schemas and serialization | PASSED |
| 2 | `test_resource_graph_index_operations` | Graph indexing, type queries, and neighbor traversal | PASSED |
| 3 | `test_resource_graph_serialization_roundtrip` | Full graph serialization/deserialization | PASSED |
| 4 | `test_resource_graph_builder` | Structural entity synthesis & relationship inference | PASSED |
| 5 | `test_resource_graph_builder_from_registry` | Construction from ResourceRegistry database | PASSED |
| 6 | `test_ranker_task_relevance` | Task relevance lexical/symbol scoring | PASSED |
| 7 | `test_ranker_source_authority` | Source authority tier discrimination | PASSED |
| 8 | `test_ranker_version_compatibility` | Version matching vs mismatch penalty | PASSED |
| 9 | `test_ranker_rejection_penalty` | Zero score clamping for CONTRADICTED / REJECTED | PASSED |
| 10 | `test_retriever_multi_hop_expansion` | Multi-hop seed expansion across graph edges | PASSED |
| 11 | `test_retriever_provenance_trust_filtering` | Minimum provenance trust level enforcement | PASSED |
| 12 | `test_retriever_freshness_filtering` | Stale resource suppression | PASSED |
| 13 | `test_retriever_bounded_evidence_and_context` | Budgeted bounding & compact context formatting | PASSED |
| 14 | `test_retriever_target_version_prioritization` | Target version prioritization | PASSED |
| 15 | `test_security_boundary_isolation_from_resource_graph` | Code graph & experience overlay invariance | PASSED |

**M5-C Test Suite**: 15 passed, 0 failed.

---

### 11. Historical M0–M5-B Regression Results

Executing the full regression test suite confirms complete backward compatibility:

| Milestone | Subsystem Tested | Tests Passed | Status |
|---|---|---|---|
| M0 | Bootstrap & SWE Tool Sandbox (`test_core.py`, `test_agent.py`, `test_tools.py`) | 9 | PASSED |
| M1 | Gemma 4 Adapter & AST Code Graph (`test_gemma_adapter.py`, `test_codegraph.py`, `test_retrieval.py`) | 18 | PASSED |
| M2 | Persistent Episodic Experience Memory (`test_experience.py`) | 9 | PASSED |
| M3 | Experience-Conditioned Graph Overlay (`test_experience_graph.py`) | 10 | PASSED |
| M4 | Failure-Aware Negative Overlay (`test_negative_experience.py`) | 10 | PASSED |
| M5-A | Resource Intelligence Foundation (`test_resources.py`) | 24 | PASSED |
| M5-B | Offline Ingestion & Validation (`test_adapters_and_validation.py`) | 15 | PASSED |
| **M5-C** | **Resource Graph & Deterministic Retrieval (`test_resource_graph.py`)** | **15** | **PASSED** |
| **Total** | **All Milestones (M0 through M5-C)** | **110 / 110** | **ALL GREEN** |

Execution time: **2.17 seconds**.

---

### 12. Known Limitations & Scientific Boundaries

1. **Graph Traversal Scope**: Graph expansion is bounded by depth (`max_depth <= 3`) and breadth; long indirect dependency paths are omitted for computational efficiency.
2. **Deterministic Token Matching**: Relevance ranking utilizes deterministic tokenization and symbol matching; dense neural embeddings were intentionally omitted to maintain full offline determinism and zero dependency overhead.
3. **No Model Interaction**: External resource evidence has not yet been presented to Gemma 4 in prompts.

---

### 13. What M5-C Does NOT Claim

- M5-C does **NOT** claim to improve agent task solving rates over M4.
- M5-C does **NOT** enable live internet fetching or API crawling.
- M5-C does **NOT** present external evidence to Gemma 4 (reserved for M5-D).
- M5-C is strictly a **graph representation and deterministic retrieval layer**.

---

### 14. Recommendation for M5-D

With the Resource Graph and deterministic retrieval operational:
- **M5-D Proposed Focus**: Integrating Verified Resource Evidence into Gemma 4 Reasoning.
  - Implement the `ResourceContextBuilder` to combine:
    - Internal Code Graph Evidence
    - Verified Positive Experience
    - Attributed Negative Experience
    - Bounded External Resource Evidence (clearly labeled with provenance, version, and status)
  - Enforce strict truth labeling so Gemma distinguishes internal code facts from external suggestions.

---

*Report generated and verified on 2026-09-30 under /lifecore-swe/experiments/M5_C.md.*
