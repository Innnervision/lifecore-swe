"""Unit tests for M5-A: External Resource Intelligence Foundation.

Validates provenance tracking, network permission policies, versioning,
persistent SQLite storage, and security boundary isolation.
"""

from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path
import pytest

from lifecore_swe.resources.models import (
    FreshnessPolicy,
    FreshnessStatus,
    ResourceRecord,
    ResourceType,
    ResourceVerificationStatus,
    compute_content_hash,
    generate_deterministic_resource_id,
    normalize_url,
)
from lifecore_swe.resources.permissions import (
    NetworkPermissionLevel,
    NetworkRequest,
    PermissionDecision,
    PermissionPolicy,
)
from lifecore_swe.resources.provenance import (
    ProvenanceRecord,
    RetrievalMethod,
    SourceType,
    TrustLevel,
    generate_provenance_id,
)
from lifecore_swe.resources.registry import ResourceRegistry
from lifecore_swe.resources.store import ResourceStore
from lifecore_swe.codegraph.schema import Node, Edge
from lifecore_swe.codegraph.index import GraphIndex
from lifecore_swe.experience_graph.overlay import ExperienceGraphOverlay
from lifecore_swe.experience_graph.negative_overlay import NegativeGraphOverlay


@pytest.fixture
def temp_store():
    """Create a temporary SQLite resource store."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = ResourceStore(db_path=db_path)
    yield store
    store.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def temp_registry():
    """Create an isolated registry with in-memory store."""
    registry = ResourceRegistry(db_path=":memory:")
    yield registry
    registry.close()


# 1. ResourceType
def test_resource_type_enum():
    expected_types = {
        "DOCUMENTATION",
        "PACKAGE",
        "PACKAGE_VERSION",
        "REPOSITORY",
        "API_REFERENCE",
        "CODE_EXAMPLE",
        "ISSUE",
        "COMMIT",
        "PULL_REQUEST",
        "PAPER",
        "BENCHMARK",
        "WEB_RESOURCE",
        "OTHER",
    }
    actual_types = {t.value for t in ResourceType}
    assert expected_types.issubset(actual_types)
    assert ResourceType.DOCUMENTATION.value == "DOCUMENTATION"


# 2. ResourceRecord creation
def test_resource_record_creation():
    rec = ResourceRecord.create(
        resource_type=ResourceType.DOCUMENTATION,
        source="python-docs",
        url="https://docs.python.org/3/library/ast.html",
        title="ast — Abstract Syntax Trees",
        description="Official documentation for the Python ast module.",
        content="AST tree parsing documentation content",
        published_at="2024-01-15T00:00:00Z",
    )
    assert rec.resource_id.startswith("res_")
    assert rec.resource_type == ResourceType.DOCUMENTATION
    assert rec.source == "python-docs"
    assert rec.url == "https://docs.python.org/3/library/ast.html"
    assert rec.content_hash != ""
    assert rec.verification_status == ResourceVerificationStatus.UNVERIFIED
    assert rec.freshness == FreshnessStatus.UNKNOWN


# 3. Deterministic resource identity
def test_deterministic_resource_identity():
    id1 = generate_deterministic_resource_id(
        resource_type=ResourceType.PACKAGE,
        source="pypi",
        url="https://pypi.org/project/requests/",
        package_name="requests",
        version="2.31.0",
    )
    id2 = generate_deterministic_resource_id(
        resource_type=ResourceType.PACKAGE,
        source="pypi",
        url="https://pypi.org/project/requests",  # Trailing slash difference normalized
        package_name="requests",
        version="2.31.0",
    )
    # Different version must yield distinct ID
    id3 = generate_deterministic_resource_id(
        resource_type=ResourceType.PACKAGE,
        source="pypi",
        url="https://pypi.org/project/requests/",
        package_name="requests",
        version="2.32.0",
    )
    assert id1 == id2
    assert id1 != id3


# 4. Content hashing
def test_content_hashing():
    content_a = "def foo(): return 42\n"
    content_b = "def foo(): return 43\n"
    hash_a1 = compute_content_hash(content_a)
    hash_a2 = compute_content_hash(content_a)
    hash_b = compute_content_hash(content_b)

    assert hash_a1 == hash_a2
    assert hash_a1 != hash_b
    assert len(hash_a1) == 64  # SHA-256 hex string


# 5. Provenance creation
def test_provenance_creation():
    prov = ProvenanceRecord.create(
        source_type=SourceType.DOCUMENTATION_SITE,
        source_name="Python Docs",
        source_url="https://docs.python.org/3/",
        retrieval_method=RetrievalMethod.OFFLINE_CACHE,
        content_hash="abc123hash",
        declared_version="3.12",
        trust_level=TrustLevel.LOW,
        notes="Imported from offline fixture.",
    )
    assert prov.provenance_id.startswith("prov_")
    assert prov.source_type == SourceType.DOCUMENTATION_SITE
    assert prov.trust_level == TrustLevel.LOW
    assert prov.retrieval_method == RetrievalMethod.OFFLINE_CACHE


# 6. Verification states
def test_verification_states():
    # Verify that RETRIEVED is distinct from VERIFIED
    assert ResourceVerificationStatus.RETRIEVED != ResourceVerificationStatus.VERIFIED
    assert ResourceVerificationStatus.UNVERIFIED.value == "UNVERIFIED"

    rec = ResourceRecord.create(
        resource_type=ResourceType.API_REFERENCE,
        source="github-api",
        content="API doc",
        verification_status=ResourceVerificationStatus.RETRIEVED,
    )
    assert rec.verification_status == ResourceVerificationStatus.RETRIEVED
    assert rec.verification_status != ResourceVerificationStatus.VERIFIED


# 7. Freshness states
def test_freshness_states():
    policy = FreshnessPolicy(fresh_threshold_days=30.0, aging_threshold_days=180.0)
    fixed_now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    # 10 days old -> FRESH
    t_fresh = "2025-05-22T12:00:00Z"
    assert policy.evaluate(retrieved_at=t_fresh, as_of_time=fixed_now) == FreshnessStatus.FRESH

    # 60 days old -> AGING
    t_aging = "2025-04-02T12:00:00Z"
    assert policy.evaluate(retrieved_at=t_aging, as_of_time=fixed_now) == FreshnessStatus.AGING

    # 250 days old -> STALE
    t_stale = "2024-09-24T12:00:00Z"
    assert policy.evaluate(retrieved_at=t_stale, as_of_time=fixed_now) == FreshnessStatus.STALE

    # No timestamp -> UNKNOWN
    assert policy.evaluate(retrieved_at=None, as_of_time=fixed_now) == FreshnessStatus.UNKNOWN


# 8. Resource deduplication
def test_resource_deduplication(temp_registry):
    rec1 = ResourceRecord.create(
        resource_type=ResourceType.PACKAGE,
        source="pypi",
        package_name="pytest",
        version="8.0.0",
        content="pytest 8.0.0 metadata initial",
    )
    saved1, is_new1 = temp_registry.register_resource(rec1)
    assert is_new1 is True

    # Register identical content
    saved2, is_new2 = temp_registry.register_resource(rec1)
    assert is_new2 is False
    assert saved2.resource_id == saved1.resource_id

    # Register updated content for same resource_id
    rec_updated = ResourceRecord.create(
        resource_type=ResourceType.PACKAGE,
        source="pypi",
        package_name="pytest",
        version="8.0.0",
        content="pytest 8.0.0 metadata revised",
        custom_id=saved1.resource_id,
    )
    saved3, is_new3 = temp_registry.register_resource(rec_updated)
    assert is_new3 is False
    assert saved3.content_hash == rec_updated.content_hash

    # Check version history
    versions = temp_registry.store.get_versions(saved1.resource_id)
    assert len(versions) >= 2


# 9. SQLite persistence
def test_sqlite_persistence(temp_store):
    rec = ResourceRecord.create(
        resource_type=ResourceType.REPOSITORY,
        source="github",
        repository="owner/repo",
        description="A test repository",
    )
    assert temp_store.insert_resource(rec) is True

    fetched = temp_store.get_resource(rec.resource_id)
    assert fetched is not None
    assert fetched.repository == "owner/repo"
    assert fetched.resource_type == ResourceType.REPOSITORY


# 10. Resource retrieval
def test_resource_retrieval(temp_store):
    for i in range(5):
        rec = ResourceRecord.create(
            resource_type=ResourceType.CODE_EXAMPLE,
            source="cookbook",
            title=f"Example {i}",
            custom_id=f"res_test_{i}",
        )
        temp_store.insert_resource(rec)

    assert temp_store.count_resources() == 5
    page1 = temp_store.list_resources(limit=3, offset=0)
    page2 = temp_store.list_resources(limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2


# 11. Resource update
def test_resource_update(temp_store):
    rec = ResourceRecord.create(
        resource_type=ResourceType.PAPER,
        source="arxiv",
        title="Original Title",
        custom_id="res_paper_1",
    )
    temp_store.insert_resource(rec)

    rec.title = "Updated Title"
    rec.metadata["keywords"] = ["swe", "agents"]
    assert temp_store.update_resource(rec) is True

    fetched = temp_store.get_resource("res_paper_1")
    assert fetched.title == "Updated Title"
    assert fetched.metadata["keywords"] == ["swe", "agents"]


# 12. Source filtering
def test_source_filtering(temp_store):
    rec1 = ResourceRecord.create(resource_type=ResourceType.DOCUMENTATION, source="pypi-docs", custom_id="res_s1")
    rec2 = ResourceRecord.create(resource_type=ResourceType.DOCUMENTATION, source="official-docs", custom_id="res_s2")
    temp_store.insert_resource(rec1)
    temp_store.insert_resource(rec2)

    results = temp_store.query_resources(source="pypi-docs")
    assert len(results) == 1
    assert results[0].resource_id == "res_s1"


# 13. Package and version filtering
def test_package_version_filtering(temp_registry):
    r1 = ResourceRecord.create(resource_type=ResourceType.PACKAGE, source="pypi", package_name="numpy", version="1.26.0")
    r2 = ResourceRecord.create(resource_type=ResourceType.PACKAGE, source="pypi", package_name="numpy", version="2.0.0")
    r3 = ResourceRecord.create(resource_type=ResourceType.PACKAGE, source="pypi", package_name="scipy", version="1.11.0")

    temp_registry.register_resource(r1)
    temp_registry.register_resource(r2)
    temp_registry.register_resource(r3)

    all_numpy = temp_registry.find_by_package("numpy")
    assert len(all_numpy) == 2

    numpy_v2 = temp_registry.find_by_package("numpy", version="2.0.0")
    assert len(numpy_v2) == 1
    assert numpy_v2[0].version == "2.0.0"


# 14. Permission levels
def test_permission_levels():
    assert NetworkPermissionLevel.LEVEL_0_NO_NETWORK == 0
    assert NetworkPermissionLevel.LEVEL_1_APPROVED_DOCUMENTATION == 1
    assert NetworkPermissionLevel.LEVEL_2_APPROVED_PUBLIC_REPOSITORIES == 2
    assert NetworkPermissionLevel.LEVEL_3_PACKAGE_MODEL_DOWNLOADS == 3
    assert NetworkPermissionLevel.LEVEL_4_EXTERNAL_APIS == 4
    assert NetworkPermissionLevel.LEVEL_5_AUTHENTICATED_SERVICES == 5
    assert NetworkPermissionLevel.LEVEL_6_SENSITIVE_PRIVATE_INFRASTRUCTURE == 6
    assert NetworkPermissionLevel.LEVEL_0_NO_NETWORK < NetworkPermissionLevel.LEVEL_6_SENSITIVE_PRIVATE_INFRASTRUCTURE


# 15. Default deny
def test_default_deny():
    policy = PermissionPolicy()  # Default level: LEVEL_0_NO_NETWORK
    req = NetworkRequest(
        requested_level=NetworkPermissionLevel.LEVEL_1_APPROVED_DOCUMENTATION,
        target_url="https://docs.python.org/3/",
        resource_type=ResourceType.DOCUMENTATION,
        source_name="python-docs",
    )
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert "Default deny" in decision.reason or "escalation" in decision.reason


# 16. Allowlisted source
def test_allowlisted_source():
    policy = PermissionPolicy(
        policy_level=NetworkPermissionLevel.LEVEL_1_APPROVED_DOCUMENTATION,
        approved_doc_domains={"docs.python.org"},
    )
    req_allowed = NetworkRequest(
        requested_level=NetworkPermissionLevel.LEVEL_1_APPROVED_DOCUMENTATION,
        target_url="https://docs.python.org/3/library/json.html",
        resource_type=ResourceType.DOCUMENTATION,
        source_name="python-docs",
    )
    dec_allowed = policy.evaluate(req_allowed)
    assert dec_allowed.allowed is True

    req_denied = NetworkRequest(
        requested_level=NetworkPermissionLevel.LEVEL_1_APPROVED_DOCUMENTATION,
        target_url="https://random-docs.unapproved.org/guide",
        resource_type=ResourceType.DOCUMENTATION,
        source_name="unapproved-docs",
    )
    dec_denied = policy.evaluate(req_denied)
    assert dec_denied.allowed is False


# 17. Permission escalation prevention
def test_permission_escalation_prevention():
    # Policy allows only documentation (Level 1)
    policy = PermissionPolicy(policy_level=NetworkPermissionLevel.LEVEL_1_APPROVED_DOCUMENTATION)
    # Request attempts to download package (Level 3)
    req = NetworkRequest(
        requested_level=NetworkPermissionLevel.LEVEL_3_PACKAGE_MODEL_DOWNLOADS,
        target_url="https://pypi.org/simple/requests/",
        resource_type=ResourceType.PACKAGE,
        source_name="pypi",
    )
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert "escalation denied" in decision.reason


# 18. Authenticated service protection & metadata blockage
def test_authenticated_service_protection():
    policy = PermissionPolicy(policy_level=NetworkPermissionLevel.LEVEL_4_EXTERNAL_APIS)

    # Request requiring authentication when policy is level 4
    req_auth = NetworkRequest(
        requested_level=NetworkPermissionLevel.LEVEL_5_AUTHENTICATED_SERVICES,
        target_url="https://internal-api.example.com",
        resource_type=ResourceType.API_REFERENCE,
        source_name="internal-api",
        requires_authentication=True,
    )
    decision = policy.evaluate(req_auth)
    assert decision.allowed is False

    # Blocked cloud metadata service request
    req_metadata = NetworkRequest(
        requested_level=NetworkPermissionLevel.LEVEL_1_APPROVED_DOCUMENTATION,
        target_url="http://169.254.169.254/computeMetadata/v1/",
        resource_type=ResourceType.OTHER,
        source_name="cloud-metadata",
    )
    dec_meta = policy.evaluate(req_metadata)
    assert dec_meta.allowed is False
    assert "Blocked security target" in dec_meta.reason


# 19. Stale resource handling
def test_stale_resource_handling(temp_registry):
    rec = ResourceRecord.create(
        resource_type=ResourceType.DOCUMENTATION,
        source="docs",
        title="FastAPI Guide",
        verification_status=ResourceVerificationStatus.VERIFIED,
    )
    temp_registry.register_resource(rec)

    updated = temp_registry.mark_stale(rec.resource_id)
    assert updated is not None
    assert updated.verification_status == ResourceVerificationStatus.STALE
    assert updated.freshness == FreshnessStatus.STALE


# 20. No mutation of code graph
def test_no_mutation_of_code_graph(temp_registry):
    n1 = Node(node_id="n1", node_type="function", repository_id="repo1", path="foo.py", symbol="foo")
    n2 = Node(node_id="n2", node_type="function", repository_id="repo1", path="bar.py", symbol="bar")
    e1 = Edge(edge_id="e1", source="n1", target="n2", edge_type="CALLS")
    graph = GraphIndex(nodes={"n1": n1, "n2": n2}, edges={"e1": e1})

    initial_node_count = len(graph.nodes)
    initial_edge_count = len(graph.edges)

    # Perform external resource operations
    rec = ResourceRecord.create(
        resource_type=ResourceType.CODE_EXAMPLE,
        source="stackoverflow",
        content="def external_helper(): pass",
    )
    temp_registry.register_resource(rec)
    temp_registry.find_by_type(ResourceType.CODE_EXAMPLE)

    # Assert code graph is strictly invariant
    assert len(graph.nodes) == initial_node_count
    assert len(graph.edges) == initial_edge_count
    assert "external_helper" not in graph.nodes
    assert temp_registry.verify_security_boundary(graph_index=graph) is True


# 21. No mutation of experience graph
def test_no_mutation_of_experience_graph(temp_registry):
    pos_overlay = ExperienceGraphOverlay()
    neg_overlay = NegativeGraphOverlay()

    initial_pos_count = len(pos_overlay._memory_store)
    initial_neg_count = len(neg_overlay._memory_store)

    # Perform external resource operations
    prov = ProvenanceRecord.create(
        source_type=SourceType.COMMUNITY_FORUM,
        source_name="forum",
        notes="External troubleshooting snippet",
    )
    rec = ResourceRecord.create(
        resource_type=ResourceType.ISSUE,
        source="github-issues",
        provenance_id=prov.provenance_id,
        content="Issue #100 description",
    )
    temp_registry.register_resource(rec, provenance=prov)

    # Assert experience overlays are invariant
    assert len(pos_overlay._memory_store) == initial_pos_count
    assert len(neg_overlay._memory_store) == initial_neg_count
    assert temp_registry.verify_security_boundary(
        positive_overlay=pos_overlay, negative_overlay=neg_overlay
    ) is True


# 22. Deterministic serialization
def test_deterministic_serialization():
    rec = ResourceRecord.create(
        resource_type=ResourceType.BENCHMARK,
        source="humaneval",
        title="HumanEval Benchmark",
        metadata={"b": 2, "a": 1, "z": [3, 2, 1]},
        retrieved_at="2025-01-01T00:00:00Z",
        custom_id="res_deterministic_test",
    )
    json_1 = rec.to_canonical_json()
    json_2 = rec.to_canonical_json()

    assert json_1 == json_2
    parsed = json.loads(json_1)
    assert parsed["resource_id"] == "res_deterministic_test"
    # Ensure keys in metadata were sorted
    assert list(parsed["metadata"].keys()) == ["a", "b", "z"]


# 23. Restart persistence
def test_restart_persistence():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Session 1: write resource and provenance
        store1 = ResourceStore(db_path=db_path)
        prov = ProvenanceRecord.create(
            source_type=SourceType.PACKAGE_REGISTRY,
            source_name="PyPI",
            declared_version="1.0.0",
            custom_id="prov_persist_1",
        )
        rec = ResourceRecord.create(
            resource_type=ResourceType.PACKAGE_VERSION,
            source="pypi",
            package_name="test-pkg",
            version="1.0.0",
            provenance_id=prov.provenance_id,
            custom_id="res_persist_1",
        )
        store1.insert_provenance(prov)
        store1.insert_resource(rec)
        store1.close()

        # Session 2: reopen store
        store2 = ResourceStore(db_path=db_path)
        fetched_rec = store2.get_resource("res_persist_1")
        fetched_prov = store2.get_provenance("prov_persist_1")

        assert fetched_rec is not None
        assert fetched_rec.package_name == "test-pkg"
        assert fetched_prov is not None
        assert fetched_prov.source_name == "PyPI"
        store2.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


# 24. Invalid input handling
def test_invalid_input_handling(temp_registry):
    # Malformed URL normalization
    norm = normalize_url(None)
    assert norm == ""

    # Register resource
    rec1 = ResourceRecord.create(
        resource_type=ResourceType.DOCUMENTATION,
        source="docs",
        custom_id="res_clash_test",
    )
    temp_registry.register_resource(rec1)

    # Attempt to register resource with same ID but incompatible ResourceType
    rec_incompatible = ResourceRecord.create(
        resource_type=ResourceType.PACKAGE,
        source="docs",
        custom_id="res_clash_test",
    )
    with pytest.raises(ValueError, match="Resource identity clash"):
        temp_registry.register_resource(rec_incompatible)
