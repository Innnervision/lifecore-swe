# LIFECORE-SWE M5-B Experiment Report

## Milestone M5-B: Controlled Offline Resource Ingestion & Validation Pipeline

**Status**: COMPLETED  
**Date**: September 30, 2026  
**System**: LIFECORE-SWE Offline Resource Ingestion & Validation Pipeline  
**Test Suite Status**: 95/95 tests passing (80 existing M0–M5-A tests + 15 new M5-B tests)  

---

### 1. Objective

Milestone **M5-B** implements the controlled offline ingestion and rigorous validation pipeline for external software resources within LIFECORE-SWE. 

Following the data foundation established in M5-A, M5-B delivers deterministic adapters capable of parsing offline representations of documentation, package metadata, API specifications, and code snippets, coupled with a 7-stage validation engine that enforces strict cryptographic, syntactic, licensing, and contradiction checks before any resource enters the persistent registry.

---

### 2. Research Question

> *"Can external software resources be ingested via deterministic offline adapters and rigorously validated against schema, cryptographic integrity, licensing, and ground truth contradictions before being accepted into the registry, without automatic elevation to trusted status?"*

**Findings**:
Yes. By designing an adapter pipeline that strictly generates records in the `RETRIEVED` state, paired with an offline `ResourceValidator` that performs independent SHA-256 integrity verification, AST syntax checks, license compliance auditing, and contradiction analysis against internal ground truth, the agent safely quarantines external artifacts and blocks malformed, forged, or contradictory data from masquerading as verified knowledge.

---

### 3. Scope & Constraints

- **Scope**:
  - Deterministic offline ingestion adapters (`BaseResourceAdapter`, `PythonDocsAdapter`, `PackageMetadataAdapter`, `MockResourceAdapter`).
  - Realistic deterministic fixtures (`MOCK_PYTHON_DOCS_AST`, `MOCK_PACKAGE_REQUESTS`, `MOCK_API_REFERENCE_PARSE`, `MOCK_CODE_EXAMPLE_VALID`).
  - Adversarial negative test fixtures (`MOCK_TAMPERED_HASH_PAYLOAD`, `MOCK_CONTRADICTORY_VERSION`, `MOCK_FORBIDDEN_LICENSE`, `MOCK_CODE_EXAMPLE_SYNTAX_ERROR`).
  - Independent `ResourceValidator` implementing 7 validation stages.
  - Integration with `ResourceRegistry` (`validate_and_register`).
- **Strict Invariant**:
  - **`RETRIEVED != VERIFIED`**: Adapters exclusively assign `ResourceVerificationStatus.RETRIEVED`. Elevation to `VALIDATED` or `VERIFIED` occurs only after passing the validation pipeline.
- **Strict Exclusions**:
  - **ZERO live internet or network fetching** was executed. All data originates from controlled offline sources and fixtures.
  - No LLM/Gemma prompting on external resources was performed.
  - No direct AST graph mutation or experience overlay modification occurred.
  - M5-C (Resource Graph) was NOT started.

---

### 4. Ingestion Pipeline Architecture

The ingestion and validation pipeline operates deterministically:

```
Controlled Offline Source / Fixture Payload
                   │
                   ▼
         Resource Adapter
         (BaseResourceAdapter)
                   │
                   ▼
  Raw Content + Retrievable Record (Status: RETRIEVED)
  + Provenance (Declared vs Observed Version, Source)
                   │
                   ▼
         Resource Validator
         (ResourceValidator)
                   │
   ┌───────────────┼───────────────┐
   ▼               ▼               ▼
[Cryptographic  [Syntactic &    [Contradiction
 Integrity]     Licensing]      Detection]
   │               │               │
   └───────────────┬───────────────┘
                   ▼
          Validation Outcome:
    ┌──────────────┴──────────────┐
    ▼                             ▼
 Passed:                      Failed:
 • VALIDATED (general pass)    • REJECTED (tampered, syntax err, license)
 • VERIFIED (ground truth)     • CONTRADICTED (conflicts with truth)
                   │
                   ▼
           ResourceRegistry
      (Persistent SQLite Store)
```

---

### 5. Adapters Implemented

Located in `lifecore_swe/resources/adapters/`:

1. **`BaseResourceAdapter`** (`base.py`):
   - Abstract contract defining `ingest(payload, ...) -> AdapterIngestionResult`.
   - Produces `AdapterIngestionResult` bundling the `ResourceRecord` (in `RETRIEVED` status), `ProvenanceRecord`, raw content string, and metadata.
2. **`PythonDocsAdapter`** (`python_docs.py`):
   - Ingests Python standard library and documentation payloads.
   - Extracts module names, canonical documentation URLs, Python versions, PSF licensing, summaries, and symbol signatures.
3. **`PackageMetadataAdapter`** (`package_metadata.py`):
   - Ingests PyPI/wheel package metadata dictionaries.
   - Extracts normalized package names, versions, license expressions, project URLs, author details, and declared dependencies (`requires_dist`).
4. **`MockResourceAdapter`** (`mock_sources.py`):
   - Universal adapter for offline fixtures covering all `ResourceType` categories (documentation, API reference, package version, code example, repository metadata).

---

### 6. Validation Pipeline & Rules

Implemented in `lifecore_swe/resources/validator.py`:

The `ResourceValidator` applies 7 deterministic checks:

1. **Schema Correctness**:
   - Asserts valid ID format (`res_` prefix, 16+ hex characters).
   - Validates `ResourceType` enum membership.
   - Validates non-empty source name and 64-character SHA-256 hex content hash.
2. **Content Hash Cryptographic Integrity**:
   - Independently recalculates `SHA-256(raw_content)`.
   - If computed hash differs from `record.content_hash`, immediately flags violation and marks `REJECTED`.
3. **Version Consistency**:
   - Compares declared version vs. observed version in provenance and record.
   - If declared version contradicts observed version (e.g., claiming 3.12 while observed as 2.7), flags `CONTRADICTED`.
4. **Source Identity Alignment**:
   - Asserts record's `source` matches provenance's `source_name`.
   - Rejects forged provenance with identity mismatches.
5. **License Metadata Compliance**:
   - Checks license against permissive allowlist (`MIT`, `Apache-2.0`, `PSF-2.0`, `BSD`, `ISC`).
   - Flags missing license (if required) or immediately rejects forbidden/hazardous licenses (`PROPRIETARY_UNLICENSED_MALWARE`, `MALWARE`).
6. **Syntax Correctness (AST Parsing)**:
   - For `CODE_EXAMPLE` resources, runs `ast.parse(code_content)`.
   - If syntax errors occur, captures error message and line number, rejecting the payload.
7. **Contradiction Detection against Ground Truth**:
   - Compares resource claims against verified repository ground truth (e.g., package versions or active symbols).
   - If resource claims an incompatible version or advertises removed/forbidden symbols, transitions status to `CONTRADICTED`.

---

### 7. Invariant: `RETRIEVED != VERIFIED`

M5-B strictly operationalizes the core trust principle:
- When an adapter ingests an external payload, the resulting `ResourceRecord` is stamped with `ResourceVerificationStatus.RETRIEVED`.
- Even if the payload contains authoritative documentation, it cannot be promoted to `VALIDATED` or `VERIFIED` without executing `ResourceValidator.validate(...)`.
- `VALIDATED` indicates the resource is syntactically sound, cryptographically intact, and license-compliant.
- `VERIFIED` is reserved exclusively for resources whose assertions have been checked against internal repository ground truth.

---

### 8. Unit Test Results

Unit tests for M5-B are implemented in `tests/test_adapters_and_validation.py`:

| # | Test Name | Tested Subsystem / Invariant | Status |
|---|---|---|---|
| 1 | `test_base_adapter_contract` | Abstract adapter interface enforcement | PASSED |
| 2 | `test_python_docs_adapter` | Python documentation parsing & metadata extraction | PASSED |
| 3 | `test_package_metadata_adapter` | Package metadata parsing & dependency extraction | PASSED |
| 4 | `test_mock_adapter_api_reference` | API reference fixture ingestion | PASSED |
| 5 | `test_mock_adapter_code_example` | Code example fixture ingestion | PASSED |
| 6 | `test_retrieved_not_equal_verified` | Rule enforcement: adapters produce RETRIEVED | PASSED |
| 7 | `test_schema_validation` | Schema check: valid passes, corrupt schema rejected | PASSED |
| 8 | `test_content_hash_integrity` | Cryptographic check: hash mismatch rejected | PASSED |
| 9 | `test_version_consistency` | Version check: declared vs observed contradiction | PASSED |
| 10 | `test_source_identity_validation` | Provenance source mismatch rejection | PASSED |
| 11 | `test_license_compliance` | Disallowed/toxic license rejection & license audit | PASSED |
| 12 | `test_syntax_validation` | AST syntax check: broken Python examples rejected | PASSED |
| 13 | `test_ground_truth_contradiction` | Conflict with repository ground truth flagged | PASSED |
| 14 | `test_ground_truth_elevation_to_verified` | Elevation to VERIFIED via ground truth confirmation | PASSED |
| 15 | `test_registry_validate_and_register` | End-to-end registry validation & SQLite persistence | PASSED |

**M5-B Test Suite**: 15 passed, 0 failed.

---

### 9. Historical M0–M5-A Regression Results

Running the entire test suite confirms zero regressions:

| Milestone | Subsystem Tested | Test Count | Status |
|---|---|---|---|
| M0 | Bootstrap & Tool Sandbox (`test_core.py`, `test_agent.py`, `test_tools.py`) | 9 | PASSED |
| M1 | Gemma 4 Integration & AST Code Graph (`test_gemma_adapter.py`, `test_codegraph.py`, `test_retrieval.py`) | 18 | PASSED |
| M2 | Persistent Episodic Experience Memory (`test_experience.py`) | 9 | PASSED |
| M3 | Experience-Conditioned Graph Overlay (`test_experience_graph.py`) | 10 | PASSED |
| M4 | Failure-Aware Negative Overlay & Penalties (`test_negative_experience.py`) | 10 | PASSED |
| M5-A | Resource Intelligence Foundation (`test_resources.py`) | 24 | PASSED |
| **M5-B** | **Offline Ingestion & Validation Pipeline (`test_adapters_and_validation.py`)** | **15** | **PASSED** |
| **Total** | **All Milestones (M0 through M5-B)** | **95 / 95** | **ALL GREEN** |

Execution time: **2.24 seconds**.

---

### 10. Known Limitations & Scientific Boundaries

1. **Deterministic Offline Only**: Ingestion is restricted to offline fixtures and local mock dictionaries. No network sockets or remote crawling were enabled.
2. **Heuristic License Matching**: License auditing compares SPDX identifiers and common variants; complex multi-license expressions are flagged for manual review.
3. **Single-Language Syntax Validation**: Syntax checking currently validates Python ASTs (`ast.parse`); non-Python code examples pass schema validation but bypass AST checks.

---

### 11. What M5-B Does NOT Claim

- M5-B does **NOT** claim that external resources improve agent task completion rates.
- M5-B does **NOT** enable live internet retrieval.
- M5-B does **NOT** construct relational resource graphs (reserved for M5-C).
- M5-B does **NOT** supply external resources to Gemma 4 context prompts (reserved for M5-D).

---

### 12. Recommendation for M5-C

With deterministic adapters and validation pipelines verified:
- **M5-C Proposed Focus**: The Resource Graph.
  - Implement relational graph structures over external resources (`SOURCED_FROM`, `DOCUMENTS`, `VERSION_OF`, `REFERENCES`, `DEPENDS_ON`, `SUPERSEDES`).
  - Implement bounded resource retrieval, multi-attribute ranking (relevance, authority, freshness, confidence), and graph traversal.
  - Preserve strict separation from the repository AST code graph.

---

*Report generated and verified on 2026-09-30 under /lifecore-swe/experiments/M5_B.md.*
