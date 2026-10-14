# LIFECORE-SWE M5-A Experiment Report

## Milestone M5-A: Resource Intelligence Foundation — Provenance, Permissions & Persistent Resource Model

**Status**: COMPLETED  
**Date**: September 30, 2026  
**System**: LIFECORE-SWE External Resource Intelligence Subsystem  
**Test Suite Status**: 80/80 tests passing (56 existing M0–M4 regression tests + 24 new M5-A tests)  

---

### 1. Objective

The primary objective of milestone **M5-A** is to establish the foundational data architecture and deterministic safety boundary for representing external software resources within the LIFECORE-SWE autonomous engineering agent.

M5-A provides the structural schema, identity canonicalization, audit provenance chain, version history tracking, and offline network permission evaluation engine needed before any external data ingestion can safely take place in subsequent milestones.

---

### 2. Research Question

> *"Can external software resources be represented as persistent, provenance-aware, version-aware, permission-controlled entities that can later be integrated into the LIFECORE-SWE world model without contaminating the verified internal code graph?"*

**Findings**:
Yes. By designing an explicit separation between the **Internal Verified World** (repository AST, code graph, execution tests, positive/negative experience overlays) and the **External Resource World** (documentation, package metadata, issues, external references), external entities can be deterministically modeled, deduplicated, and tracked without mutating or corrupting internal code reasoning.

---

### 3. Scope

M5-A is strictly **foundation only**:
- **Included**:
  - `ResourceType` enum (13 resource categories)
  - `ResourceRecord` dataclass and canonical serialization
  - Deterministic SHA-256 identity generation and content hashing
  - `ProvenanceRecord` audit model with source classifications and trust levels
  - Explicit 7-stage verification lifecycle (`RETRIEVED != VERIFIED`)
  - Configurable `FreshnessPolicy` with deterministic timestamp evaluation
  - Hierarchical 7-level `NetworkPermissionLevel` model with default deny
  - Controlled source allowlists and blocked security targets
  - SQLite persistence store (`ResourceStore`) with transactions and indexes
  - Central `ResourceRegistry` with deduplication and version archiving
  - Strict security isolation assertions ensuring zero graph contamination
- **Explicitly Excluded (NO live network access)**:
  - Live internet requests, HTTP clients (`urllib.request`, `requests`, `httpx`, `aiohttp`)
  - Search engine queries, Google Search API, GitHub API integration
  - Package/model downloads
  - Browser automation
  - Code graph mutation from external data
  - Agent prompting / LLM invocation on external resources
  - M5 benchmark runs

---

### 4. Architecture

M5-A introduces the following clean, modular structure under `lifecore_swe/resources/`:

```
lifecore_swe/resources/
├── __init__.py         # Public exports (ResourceRecord, ProvenanceRecord, ResourceStore, ResourceRegistry, PermissionPolicy)
├── models.py           # ResourceType, ResourceVerificationStatus, FreshnessStatus, FreshnessPolicy, ResourceRecord, hashing
├── provenance.py       # SourceType, TrustLevel, RetrievalMethod, ProvenanceRecord, generate_provenance_id
├── permissions.py      # NetworkPermissionLevel (0-6), NetworkRequest, PermissionDecision, PermissionPolicy
├── store.py            # SQLite relational storage (resources, provenance, resource_versions) with indexes and transactions
└── registry.py         # ResourceRegistry (deduplication, version tracking, freshness evaluation, security verification)
```

The data flow enforces a strict unidirectional pipeline:

```
External Resource Metadata
            ↓
  Provenance Record (Origin, Method, Initial Trust)
            ↓
  Permission Policy Check (Default Deny, Level Allowlist)
            ↓
  Resource Registry (Deduplication, Version Archiving)
            ↓
  SQLite Resource Store (resources.db)
            ↓
  Future Verification Pipeline (M5-B+)
            ↓
  Isolated Integration (Never direct AST graph mutation)
```

---

### 5. Resource Model

Defined in `lifecore_swe/resources/models.py`:

- **ResourceType**:
  - `DOCUMENTATION`: Official API documentation or reference manuals
  - `PACKAGE`: Software package entity
  - `PACKAGE_VERSION`: Specific release version of a library
  - `REPOSITORY`: External source code repository
  - `API_REFERENCE`: Function/method signatures and contracts
  - `CODE_EXAMPLE`: Code snippets, cookbooks, examples
  - `ISSUE`: Bug tracker issue descriptions
  - `COMMIT`: Version control revision
  - `PULL_REQUEST`: Code change proposals and review threads
  - `PAPER`: Academic literature or research publications
  - `BENCHMARK`: Evaluation datasets and problem benchmarks
  - `WEB_RESOURCE`: General verified web references
  - `OTHER`: Uncategorized external artifacts

- **ResourceRecord**:
  - `resource_id`: Deterministic SHA-256 identifier (`res_{digest[:16]}`) computed from canonical representation of `(resource_type, source, normalized_url, package_name, repository, version)`.
  - `resource_type`: `ResourceType`
  - `source`: Source identifier (e.g., `python-docs`, `pypi`, `github`)
  - `url`: Canonical normalized URL (scheme/host lowercased, default ports removed, trailing slashes trimmed, query parameters sorted)
  - `title`: Short human-readable title
  - `description`: Textual summary
  - `repository`: Repository locator string
  - `package_name`: Canonical package name
  - `version`: Canonical version string
  - `content_hash`: SHA-256 digest of content payload
  - `retrieved_at`: ISO 8601 timestamp
  - `published_at`: ISO 8601 timestamp
  - `license`: Explicit licensing string (e.g., `MIT`, `Apache-2.0`, `PSF`)
  - `author_or_owner`: Author or maintaining organization
  - `parent_resource_id`: Hierarchy linkage
  - `provenance_id`: Link to associated `ProvenanceRecord`
  - `confidence`: Confidence score in [0.0, 1.0]
  - `freshness`: `FreshnessStatus`
  - `verification_status`: `ResourceVerificationStatus`
  - `metadata`: Arbitrary JSON-serializable dictionary
  - `created_at` / `updated_at`: Ingestion timestamps

---

### 6. Provenance Model

Defined in `lifecore_swe/resources/provenance.py`:

- **SourceType**:
  `DOCUMENTATION_SITE`, `PACKAGE_REGISTRY`, `CODE_HOSTING`, `PAPER_REPOSITORY`, `BENCHMARK_SUITE`, `ISSUE_TRACKER`, `COMMUNITY_FORUM`, `OTHER`
- **TrustLevel**:
  `UNTRUSTED`, `LOW`, `MEDIUM`, `HIGH`, `VERIFIED_INTERNAL`
  *(External resources default to `LOW` or `UNTRUSTED`)*
- **RetrievalMethod**:
  `OFFLINE_CACHE`, `MANUAL_IMPORT`, `FIXTURE`, `API`, `WEB_CRAWL`, `OTHER`
- **ProvenanceRecord**:
  - `provenance_id`: Deterministic ID (`prov_{digest[:16]}`) based on source type, name, URL, content hash, and declared version
  - Complete audit trail tracking retrieval time, method, observed license, declared vs. observed version, and auditor notes.

---

### 7. Verification Lifecycle

Core architectural invariant: **`RETRIEVED != VERIFIED`**.

Under no circumstances does obtaining or storing an external resource mark it as verified. The verification lifecycle enforces 7 distinct states:

1. `UNVERIFIED`: Initial state upon creation without confirmed retrieval.
2. `RETRIEVED`: Successfully fetched or ingested, but contents have not undergone structural validation or semantic checking.
3. `VALIDATED`: Syntactically checked, license compatible, and schema verified.
4. `VERIFIED`: Explicitly vetted against internal repository constraints or test suites by a dedicated validation mechanism.
5. `STALE`: Previously valid but superseded by updated versions or expired freshness.
6. `CONTRADICTED`: Found to conflict with verified repository behavior or ground truth.
7. `REJECTED`: Fails licensing, security, or integrity checks.

---

### 8. Freshness Model

Defined in `lifecore_swe/resources/models.py`:

- **FreshnessStatus**: `FRESH`, `AGING`, `STALE`, `UNKNOWN`
- **FreshnessPolicy**:
  - Evaluates age using `published_at` (or `retrieved_at` fallback) against configurable thresholds:
    - Default: age ≤ 30 days → `FRESH`
    - 30 days < age ≤ 180 days → `AGING`
    - age > 180 days → `STALE`
    - Missing/unparseable timestamps → `UNKNOWN`
  - Evaluated deterministically against an explicit reference timestamp in unit tests, ensuring complete reproducibility without relying on system clock.

---

### 9. Permission Architecture

Defined in `lifecore_swe/resources/permissions.py`:

- **NetworkPermissionLevel**:
  - `LEVEL_0_NO_NETWORK` (0): Strict isolation; zero outbound network activity allowed (default).
  - `LEVEL_1_APPROVED_DOCUMENTATION` (1): Read access to explicitly allowlisted documentation domains (e.g. `docs.python.org`).
  - `LEVEL_2_APPROVED_PUBLIC_REPOSITORIES` (2): Read access to allowlisted public repositories (`github.com`, `gitlab.com`).
  - `LEVEL_3_PACKAGE_MODEL_DOWNLOADS` (3): Ingestion from allowlisted package registries (`pypi.org`, `files.pythonhosted.org`).
  - `LEVEL_4_EXTERNAL_APIS` (4): Approved external API endpoints (`api.github.com`).
  - `LEVEL_5_AUTHENTICATED_SERVICES` (5): Services requiring credentials (requires level ≥ 5 and explicit operator confirmation).
  - `LEVEL_6_SENSITIVE_PRIVATE_INFRASTRUCTURE` (6): Internal corporate networks/intranets (requires level 6 and operator confirmation).

- **Permission Safety Rules**:
  - **Default Deny**: Any request without an explicit allowlist match is denied.
  - **Escalation Prevention**: A request specifying `requested_level > policy_level` is denied with an explicit audit log reason.
  - **Blocked Targets**: Cloud metadata IP (`169.254.169.254`), loopbacks (`127.0.0.1`, `localhost`), and unapproved private IPv4/IPv6 ranges are denied unconditionally.
  - **Zero Execution**: The permission layer does NOT initiate network sockets; it operates purely as an offline policy gatekeeper.

---

### 10. SQLite Persistence Schema

Defined in `lifecore_swe/resources/store.py`:

```sql
CREATE TABLE IF NOT EXISTS resources (
    resource_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    title TEXT,
    description TEXT,
    repository TEXT,
    package_name TEXT,
    version TEXT,
    content_hash TEXT,
    retrieved_at TEXT,
    published_at TEXT,
    license TEXT,
    author_or_owner TEXT,
    parent_resource_id TEXT,
    provenance_id TEXT,
    confidence REAL DEFAULT 1.0,
    freshness TEXT DEFAULT 'UNKNOWN',
    verification_status TEXT DEFAULT 'UNVERIFIED',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provenance (
    provenance_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT,
    retrieved_at TEXT,
    retrieval_method TEXT,
    content_hash TEXT,
    declared_version TEXT,
    observed_version TEXT,
    license TEXT,
    parent_resource_id TEXT,
    trust_level TEXT,
    notes TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_versions (
    version_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id TEXT NOT NULL,
    version TEXT,
    content_hash TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(resource_id) REFERENCES resources(resource_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_resources_type ON resources(resource_type);
CREATE INDEX IF NOT EXISTS idx_resources_source ON resources(source);
CREATE INDEX IF NOT EXISTS idx_resources_pkg ON resources(package_name);
CREATE INDEX IF NOT EXISTS idx_resources_repo ON resources(repository);
CREATE INDEX IF NOT EXISTS idx_resources_status ON resources(verification_status);
CREATE INDEX IF NOT EXISTS idx_resources_content_hash ON resources(content_hash);
CREATE INDEX IF NOT EXISTS idx_resources_url ON resources(url);
CREATE INDEX IF NOT EXISTS idx_provenance_source ON provenance(source_name);
CREATE INDEX IF NOT EXISTS idx_provenance_hash ON provenance(content_hash);
CREATE INDEX IF NOT EXISTS idx_versions_res_id ON resource_versions(resource_id);
```

---

### 11. Security Boundary

A core principle of LIFECORE-SWE is the preservation of repository integrity:

$$\text{Internal Verified Knowledge} \cap \text{External Resource Store} = \emptyset \quad (\text{by default})$$

- External resources reside exclusively in `ResourceStore` / `ResourceRegistry`.
- Neither `ResourceRecord` nor `ResourceRegistry` possesses write access or mutate methods on:
  - Static AST repository graph (`GraphIndex`)
  - Positive experience overlay (`ExperienceGraphOverlay`)
  - Negative failure overlay (`NegativeGraphOverlay`)
  - Local repository filesystem / source code
  - Model parameters / Gemma weights
- Tests `test_no_mutation_of_code_graph` and `test_no_mutation_of_experience_graph` explicitly verify that creating, registering, updating, and querying external resources produces **zero changes** in internal code graph nodes, edges, experience weights, and failure penalties.

---

### 12. Unit Test Results

Unit tests for M5-A are implemented in `tests/test_resources.py` and run under `pytest`:

| # | Test Name | Target Functionality | Status |
|---|---|---|---|
| 1 | `test_resource_type_enum` | ResourceType 13 enum members verification | PASSED |
| 2 | `test_resource_record_creation` | ResourceRecord creation and defaults | PASSED |
| 3 | `test_deterministic_resource_identity` | URL normalization & deterministic SHA-256 IDs | PASSED |
| 4 | `test_content_hashing` | SHA-256 content hashing determinism | PASSED |
| 5 | `test_provenance_creation` | ProvenanceRecord creation and ID generation | PASSED |
| 6 | `test_verification_states` | Verification lifecycle & RETRIEVED != VERIFIED rule | PASSED |
| 7 | `test_freshness_states` | Freshness evaluation against fixed timestamps | PASSED |
| 8 | `test_resource_deduplication` | Registry deduplication & version history archiving | PASSED |
| 9 | `test_sqlite_persistence` | CRUD persistence in SQLite store | PASSED |
| 10 | `test_resource_retrieval` | Pagination (limit/offset) and counting | PASSED |
| 11 | `test_resource_update` | In-place record update and metadata persistence | PASSED |
| 12 | `test_source_filtering` | Filter queries by source identifier | PASSED |
| 13 | `test_package_version_filtering` | Package and version lookup filtering | PASSED |
| 14 | `test_permission_levels` | Hierarchical ordering of permission levels (0-6) | PASSED |
| 15 | `test_default_deny` | Default deny on Level 0 policy | PASSED |
| 16 | `test_allowlisted_source` | Allowlist matching vs. unapproved domain denial | PASSED |
| 17 | `test_permission_escalation_prevention` | Denial when requested level > policy level | PASSED |
| 18 | `test_authenticated_service_protection` | Auth protection & cloud metadata blockage | PASSED |
| 19 | `test_stale_resource_handling` | Transition to STALE status and freshness | PASSED |
| 20 | `test_no_mutation_of_code_graph` | Code graph invariance during resource operations | PASSED |
| 21 | `test_no_mutation_of_experience_graph` | Experience graph overlay invariance | PASSED |
| 22 | `test_deterministic_serialization` | Canonical JSON serialization with sorted keys | PASSED |
| 23 | `test_restart_persistence` | Store persistence across connection restarts | PASSED |
| 24 | `test_invalid_input_handling` | Handling malformed URLs and ID clash prevention | PASSED |

**M5-A Test Summary**: 24 passed, 0 failed.

---

### 13. Existing M0–M4 Regression Results

The entire pre-existing test suite was executed to ensure zero regression across completed milestones:

| Test File | Milestone Coverage | Tests Passed | Status |
|---|---|---|---|
| `test_core.py` | Bootstrap & Environment | 1 | PASSED |
| `test_agent.py` | M0.1 SWE Agent Architecture | 3 | PASSED |
| `test_tools.py` | M0.1 Tool Sandbox & Boundary Checks | 5 | PASSED |
| `test_gemma_adapter.py` | M1A Model Adapter Integration | 2 | PASSED |
| `test_codegraph.py` | M1B AST Repository Graph | 8 | PASSED |
| `test_retrieval.py` | M1C Graph-Guided Retrieval | 8 | PASSED |
| `test_experience.py` | M2 Persistent Episodic Experience | 9 | PASSED |
| `test_experience_graph.py` | M3 Experience-Conditioned Graph Overlay | 10 | PASSED |
| `test_negative_experience.py` | M4 Failure-Aware Graph & Penalties | 10 | PASSED |
| `test_resources.py` | **M5-A Resource Intelligence Foundation** | **24** | **PASSED** |
| **Total** | **All Milestones (M0.1 through M5-A)** | **80 / 80** | **ALL GREEN** |

Execution time: **1.82 seconds**.

---

### 14. Known Limitations

1. **No Live Fetching**: M5-A implements schema and permission evaluation only; it cannot retrieve live web content or external repository files over the wire.
2. **Offline Allowlist**: Domain allowlists and permission policies are statically configured rather than dynamically loaded from authenticated enterprise profiles.
3. **No Automated Semantic Verification**: While verification states (`VALIDATED`, `VERIFIED`, `CONTRADICTED`, `REJECTED`) are modeled, automated validation routines (e.g. executing external code snippets in an isolated micro-sandbox or checking AST compatibility) belong to future research.
4. **No LLM Integration**: Gemma 4 is not yet exposed to external resource metadata in prompts or retrieval context.

---

### 15. What M5-A Does NOT Claim

- M5-A does **NOT** claim to improve benchmark pass rates or task completion efficiency over M4.
- M5-A does **NOT** claim that external resources are automatically trustworthy or safe to execute.
- M5-A does **NOT** claim to have resolved multi-modal resource ingestion (e.g. diagrams or video tutorials).
- M5-A is exclusively a **foundational infrastructure and security layer**.

---

### 16. Recommendation for M5-B

With the persistent resource schema, provenance tracking, and permission policies verified:
- **M5-B Proposed Focus**: Deterministic Offline Resource Ingestion & Controlled Mock Caching.
  - Implement fixture-based offline ingestion adapters for official Python documentation and package metadata.
  - Develop the validation pipeline to promote `RETRIEVED` resources to `VALIDATED` using local AST parsing.
  - Test that mock-retrieved documentation snippets can be surfaced to retrieval layers under strict permission gating.
- Maintain strict default-deny network enforcement and never allow unverified resources to alter internal code graph weights.

---

*Report generated and verified on 2026-09-30 under /lifecore-swe/experiments/M5_A.md.*
