"""Unit tests for M5-C: Provenance-Aware Resource Graph & Deterministic Retrieval.

Validates:
- Entity and relationship schemas
- ResourceGraph associative indexing and bidirectional traversal
- ResourceGraphBuilder structural relationship inference
- Multi-attribute ResourceRanker (relevance, authority, version, freshness, trust, status)
- Bounded ResourceGraphRetriever and multi-hop expansion
- Provenance, freshness, and version filtering
- Strict security boundary invariance (no mutation of code graph or experience overlays)
"""

from __future__ import annotations

import pytest

from lifecore_swe.resources.models import (
    FreshnessStatus,
    ResourceRecord,
    ResourceType,
    ResourceVerificationStatus,
)
from lifecore_swe.resources.provenance import (
    ProvenanceRecord,
    RetrievalMethod,
    SourceType,
    TrustLevel,
)
from lifecore_swe.resources.registry import ResourceRegistry
from lifecore_swe.resources.graph import (
    ResourceEdge,
    ResourceEdgeType,
    ResourceGraph,
    ResourceGraphBuilder,
    ResourceGraphRetriever,
    ResourceNode,
    ResourceNodeType,
    ResourceRanker,
    ResourceRetrievalConfig,
)
from lifecore_swe.codegraph.schema import Node, Edge
from lifecore_swe.codegraph.index import GraphIndex
from lifecore_swe.experience_graph.overlay import ExperienceGraphOverlay
from lifecore_swe.experience_graph.negative_overlay import NegativeGraphOverlay


@pytest.fixture
def sample_records():
    """Create a set of realistic resource records for graph testing."""
    r_doc = ResourceRecord.create(
        custom_id="res_ast_doc",
        resource_type=ResourceType.DOCUMENTATION,
        source="python-docs",
        package_name="ast",
        version="3.12.0",
        title="ast — Abstract Syntax Trees",
        description="Official documentation for the Python ast module.",
        content="parse(source) dump(node) Visitor",
        verification_status=ResourceVerificationStatus.VERIFIED,
        freshness=FreshnessStatus.FRESH,
        confidence=0.98,
        metadata={"symbols": ["parse", "dump", "NodeVisitor"]},
    )
    r_api = ResourceRecord.create(
        custom_id="res_ast_api",
        resource_type=ResourceType.API_REFERENCE,
        source="python-docs",
        package_name="ast",
        version="3.12.0",
        title="ast.parse API Specification",
        description="API contract for ast.parse function.",
        content="def parse(source, filename='<unknown>', mode='exec'): ...",
        verification_status=ResourceVerificationStatus.VERIFIED,
        freshness=FreshnessStatus.FRESH,
        confidence=1.0,
        parent_resource_id="res_ast_doc",
    )
    r_ex = ResourceRecord.create(
        custom_id="res_ast_ex",
        resource_type=ResourceType.CODE_EXAMPLE,
        source="cookbook",
        package_name="ast",
        version="3.12.0",
        title="AST Visitor Example",
        description="Code example demonstrating AST traversal.",
        content="import ast\nclass V(ast.NodeVisitor): pass\n",
        verification_status=ResourceVerificationStatus.VALIDATED,
        freshness=FreshnessStatus.FRESH,
        confidence=0.90,
    )
    r_pkg = ResourceRecord.create(
        custom_id="res_requests_pkg",
        resource_type=ResourceType.PACKAGE_VERSION,
        source="pypi",
        package_name="requests",
        version="2.31.0",
        title="Requests Package 2.31.0",
        description="HTTP library for Python.",
        content="requests 2.31.0 metadata",
        verification_status=ResourceVerificationStatus.VALIDATED,
        freshness=FreshnessStatus.AGING,
        confidence=0.95,
        metadata={"dependencies": ["urllib3<3,>=1.21.1", "certifi>=2017.4.17"]},
    )
    r_stale = ResourceRecord.create(
        custom_id="res_stale_dep",
        resource_type=ResourceType.DOCUMENTATION,
        source="old-wiki",
        package_name="urllib3",
        version="1.10.0",
        title="Outdated urllib3 Guide",
        description="Legacy notes from 2018.",
        content="ancient urllib3 docs",
        verification_status=ResourceVerificationStatus.STALE,
        freshness=FreshnessStatus.STALE,
        confidence=0.50,
    )
    r_contradicted = ResourceRecord.create(
        custom_id="res_contradicted_pkg",
        resource_type=ResourceType.PACKAGE_VERSION,
        source="unverified-mirror",
        package_name="requests",
        version="1.0.0",
        title="Contradictory Requests Package",
        description="Claims requests 1.0.0 has features from 2.31.",
        content="contradictory assertions",
        verification_status=ResourceVerificationStatus.CONTRADICTED,
        freshness=FreshnessStatus.STALE,
        confidence=0.20,
    )

    prov_ast = ProvenanceRecord.create(
        source_type=SourceType.DOCUMENTATION_SITE,
        source_name="python-docs",
        declared_version="3.12.0",
        trust_level=TrustLevel.HIGH,
        custom_id="prov_ast",
    )
    prov_req = ProvenanceRecord.create(
        source_type=SourceType.PACKAGE_REGISTRY,
        source_name="pypi",
        declared_version="2.31.0",
        trust_level=TrustLevel.HIGH,
        custom_id="prov_req",
    )
    prov_untrusted = ProvenanceRecord.create(
        source_type=SourceType.COMMUNITY_FORUM,
        source_name="unverified-mirror",
        trust_level=TrustLevel.UNTRUSTED,
        custom_id="prov_untrusted",
    )

    r_doc.provenance_id = "prov_ast"
    r_api.provenance_id = "prov_ast"
    r_pkg.provenance_id = "prov_req"
    r_contradicted.provenance_id = "prov_untrusted"

    return [r_doc, r_api, r_ex, r_pkg, r_stale, r_contradicted], [prov_ast, prov_req, prov_untrusted]


# 1. Entity and relationship schema tests
def test_resource_node_and_edge_schema():
    node = ResourceNode(
        node_id="res_node_1",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="Test Documentation",
        source="python-docs",
        verification_status=ResourceVerificationStatus.VALIDATED,
        freshness=FreshnessStatus.FRESH,
    )
    assert node.node_id == "res_node_1"
    assert node.node_type == ResourceNodeType.DOCUMENTATION
    assert node.verification_status == ResourceVerificationStatus.VALIDATED

    edge = ResourceEdge(
        edge_id="e1",
        source_id="res_node_1",
        target_id="package:ast",
        edge_type=ResourceEdgeType.DOCUMENTS,
    )
    assert edge.edge_type == ResourceEdgeType.DOCUMENTS
    d = edge.to_dict()
    assert d["edge_type"] == "DOCUMENTS"


# 2. ResourceGraph index and adjacency queries
def test_resource_graph_index_operations():
    graph = ResourceGraph()
    n1 = ResourceNode(node_id="n1", node_type=ResourceNodeType.PACKAGE, title="N1", source="pypi", package_name="pkg1")
    n2 = ResourceNode(node_id="n2", node_type=ResourceNodeType.DOCUMENTATION, title="N2", source="docs", package_name="pkg1")
    graph.add_node(n1)
    graph.add_node(n2)

    e1 = ResourceEdge(edge_id="e1", source_id="n2", target_id="n1", edge_type=ResourceEdgeType.DOCUMENTS)
    graph.add_edge(e1)

    assert graph.count_nodes() == 2
    assert graph.count_edges() == 1
    assert len(graph.find_by_package("pkg1")) == 2
    assert len(graph.find_by_type(ResourceNodeType.DOCUMENTATION)) == 1

    neighbors_out = graph.get_neighbors("n2", direction="out")
    assert len(neighbors_out) == 1
    assert neighbors_out[0][0].node_id == "n1"

    neighbors_in = graph.get_neighbors("n1", direction="in")
    assert len(neighbors_in) == 1
    assert neighbors_in[0][0].node_id == "n2"


# 3. Serialization and deserialization
def test_resource_graph_serialization_roundtrip():
    graph = ResourceGraph()
    n = ResourceNode(node_id="n_test", node_type=ResourceNodeType.API, title="API Test", source="docs")
    graph.add_node(n)
    e = ResourceEdge(edge_id="e_test", source_id="n_test", target_id="n_other", edge_type=ResourceEdgeType.REFERENCES)
    graph.add_edge(e)

    data = graph.to_dict()
    restored = ResourceGraph.from_dict(data)

    assert restored.count_nodes() == 1
    assert restored.count_edges() == 1
    assert restored.get_node("n_test").title == "API Test"
    assert restored.get_edge("e_test").edge_type == ResourceEdgeType.REFERENCES


# 4. ResourceGraphBuilder structural relationship inference
def test_resource_graph_builder(sample_records):
    records, provenances = sample_records
    builder = ResourceGraphBuilder()
    graph = builder.build_from_records(records, provenances)

    # Check that structural entities were automatically synthesized
    assert graph.get_node("source:python-docs") is not None
    assert graph.get_node("source:pypi") is not None
    assert graph.get_node("package:ast") is not None
    assert graph.get_node("package:requests") is not None
    assert graph.get_node("package:urllib3") is not None  # from dependencies!

    # Check structural edge generation
    assert graph.get_edge("res_ast_doc--SOURCED_FROM-->source:python-docs") is not None
    assert graph.get_edge("res_ast_doc--DOCUMENTS-->package:ast") is not None
    assert graph.get_edge("res_requests_pkg--VERSION_OF-->package:requests") is not None
    assert graph.get_edge("res_ast_ex--EXAMPLE_FOR-->package:ast") is not None
    assert graph.get_edge("res_ast_api--REFERENCES-->res_ast_doc") is not None
    assert graph.get_edge("res_requests_pkg--DEPENDS_ON-->package:urllib3") is not None


# 5. Builder integration with ResourceRegistry
def test_resource_graph_builder_from_registry(sample_records):
    records, provenances = sample_records
    reg = ResourceRegistry(db_path=":memory:")
    prov_map = {p.provenance_id: p for p in provenances}

    for r in records:
        prov = prov_map.get(r.provenance_id)
        reg.register_resource(r, provenance=prov)

    builder = ResourceGraphBuilder()
    graph = builder.build_from_registry(reg)

    assert graph.count_nodes() >= len(records)
    assert graph.get_node("package:requests") is not None
    reg.close()


# 6. Multi-attribute ranking: Task relevance and symbol matching
def test_ranker_task_relevance():
    ranker = ResourceRanker()
    node_match = ResourceNode(
        node_id="n_ast",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="ast parsing guide",
        source="python-docs",
        package_name="ast",
        description="Guide on how to parse python code with ast module",
    )
    node_unrelated = ResourceNode(
        node_id="n_crypto",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="cryptography cipher docs",
        source="python-docs",
        package_name="cryptography",
        description="AES and RSA cipher encryption",
    )

    scored_match = ranker.score(node_match, query_text="how to parse ast nodes")
    scored_unrelated = ranker.score(node_unrelated, query_text="how to parse ast nodes")

    assert scored_match.score > scored_unrelated.score
    assert scored_match.sub_scores["relevance"] > scored_unrelated.sub_scores["relevance"]


# 7. Multi-attribute ranking: Source authority
def test_ranker_source_authority():
    ranker = ResourceRanker()
    node_official = ResourceNode(
        node_id="n_off",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="Official Docs",
        source="python-docs",
    )
    node_forum = ResourceNode(
        node_id="n_forum",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="Forum Post",
        source="community-forum",
    )

    score_off = ranker.score(node_official)
    score_forum = ranker.score(node_forum)

    assert score_off.sub_scores["authority"] > score_forum.sub_scores["authority"]


# 8. Multi-attribute ranking: Version compatibility
def test_ranker_version_compatibility():
    ranker = ResourceRanker()
    node_v312 = ResourceNode(
        node_id="n_v312",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="Python 3.12 Docs",
        source="python-docs",
        version="3.12.0",
    )
    node_v27 = ResourceNode(
        node_id="n_v27",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="Python 2.7 Docs",
        source="python-docs",
        version="2.7.0",
    )

    score_match = ranker.score(node_v312, target_version="3.12.0")
    score_mismatch = ranker.score(node_v27, target_version="3.12.0")

    assert score_match.sub_scores["version"] == 1.0
    assert score_mismatch.sub_scores["version"] < 0.2


# 9. Multi-attribute ranking: Hard penalty for REJECTED and CONTRADICTED
def test_ranker_rejection_penalty():
    ranker = ResourceRanker()
    node_contradicted = ResourceNode(
        node_id="n_bad",
        node_type=ResourceNodeType.PACKAGE,
        title="Bad Package",
        source="mirror",
        verification_status=ResourceVerificationStatus.CONTRADICTED,
    )
    scored = ranker.score(node_contradicted, query_text="package")
    assert scored.score == 0.0
    assert any("Penalty applied" in r for r in scored.reasons)


# 10. Multi-hop graph expansion in ResourceGraphRetriever
def test_retriever_multi_hop_expansion(sample_records):
    records, provenances = sample_records
    builder = ResourceGraphBuilder()
    graph = builder.build_from_records(records, provenances)

    retriever = ResourceGraphRetriever(graph=graph)
    # Query targets 'ast'
    result = retriever.retrieve("ast parse abstract syntax trees", config=ResourceRetrievalConfig(max_depth=2))

    assert len(result.items) > 0
    # Seed was ast, traversal reached ast.parse API ref and example
    retrieved_ids = {item.node.node_id for item in result.items}
    assert "res_ast_doc" in retrieved_ids
    assert "res_ast_api" in retrieved_ids


# 11. Provenance filtering
def test_retriever_provenance_trust_filtering(sample_records):
    records, provenances = sample_records
    builder = ResourceGraphBuilder()
    graph = builder.build_from_records(records, provenances)

    prov_map = {p.provenance_id: p for p in provenances}
    retriever = ResourceGraphRetriever(graph=graph, provenance_records=prov_map)

    # Require HIGH trust
    cfg = ResourceRetrievalConfig(min_trust_level=TrustLevel.HIGH)
    result = retriever.retrieve("requests package", config=cfg)

    # Should not include untrusted items
    for item in result.items:
        if item.node.provenance_id and item.node.provenance_id in prov_map:
            assert prov_map[item.node.provenance_id].trust_level in (TrustLevel.HIGH, TrustLevel.VERIFIED_INTERNAL)


# 12. Freshness filtering
def test_retriever_freshness_filtering(sample_records):
    records, provenances = sample_records
    builder = ResourceGraphBuilder()
    graph = builder.build_from_records(records, provenances)

    retriever = ResourceGraphRetriever(graph=graph)

    # Disallow stale resources
    cfg_no_stale = ResourceRetrievalConfig(allow_stale=False)
    result_no_stale = retriever.retrieve("urllib3", config=cfg_no_stale)
    stale_ids = [item.node.node_id for item in result_no_stale.items if item.node.freshness == FreshnessStatus.STALE]
    assert len(stale_ids) == 0

    # Allow stale resources
    cfg_allow_stale = ResourceRetrievalConfig(allow_stale=True, min_score=0.0)
    result_stale = retriever.retrieve("urllib3", config=cfg_allow_stale)
    item_ids = [item.node.node_id for item in result_stale.items]
    assert "res_stale_dep" in item_ids


# 13. Bounded evidence selection and formatting
def test_retriever_bounded_evidence_and_context(sample_records):
    records, provenances = sample_records
    builder = ResourceGraphBuilder()
    graph = builder.build_from_records(records, provenances)

    retriever = ResourceGraphRetriever(graph=graph)
    cfg = ResourceRetrievalConfig(max_resources=2)
    result = retriever.retrieve("ast python", config=cfg)

    # Respects upper bound
    assert len(result.items) <= 2

    # Context formatting contains required metadata
    context_text = result.format_compact_context()
    assert "EXTERNAL RESOURCE EVIDENCE:" in context_text
    assert "Verification Status:" in context_text
    assert "Relevance Score:" in context_text
    assert "Source:" in context_text


# 14. Target version filtering
def test_retriever_target_version_prioritization(sample_records):
    records, provenances = sample_records
    builder = ResourceGraphBuilder()
    graph = builder.build_from_records(records, provenances)

    retriever = ResourceGraphRetriever(graph=graph)
    cfg = ResourceRetrievalConfig(target_package="requests", target_version="2.31.0")
    result = retriever.retrieve("requests library", config=cfg)

    assert len(result.items) > 0
    top_item = result.items[0]
    assert top_item.node.package_name == "requests"
    assert top_item.node.version == "2.31.0"


# 15. Security boundary isolation: No mutation of Code Graph or Experience Overlays
def test_security_boundary_isolation_from_resource_graph(sample_records):
    # 1. Setup internal code graph
    n1 = Node(node_id="node_fn", node_type="function", repository_id="repo1", path="utils.py", symbol="helper")
    n2 = Node(node_id="node_cls", node_type="class", repository_id="repo1", path="utils.py", symbol="HelperClass")
    e1 = Edge(edge_id="e_call", source="node_fn", target="node_cls", edge_type="CALLS")
    code_graph = GraphIndex(nodes={"node_fn": n1, "node_cls": n2}, edges={"e_call": e1})

    # 2. Setup experience overlays
    pos_overlay = ExperienceGraphOverlay()
    neg_overlay = NegativeGraphOverlay()

    initial_code_nodes = len(code_graph.nodes)
    initial_code_edges = len(code_graph.edges)
    initial_pos_stats = len(pos_overlay._memory_store)
    initial_neg_stats = len(neg_overlay._memory_store)

    # 3. Perform external Resource Graph operations
    records, provenances = sample_records
    builder = ResourceGraphBuilder()
    res_graph = builder.build_from_records(records, provenances)

    retriever = ResourceGraphRetriever(graph=res_graph)
    result = retriever.retrieve("ast parse python requests", config=ResourceRetrievalConfig(max_resources=5))

    assert len(result.items) > 0

    # 4. Assert strict invariance on all internal structures
    assert len(code_graph.nodes) == initial_code_nodes
    assert len(code_graph.edges) == initial_code_edges
    assert "node_fn" in code_graph.nodes
    assert "package:requests" not in code_graph.nodes
    assert "res_ast_doc" not in code_graph.nodes

    assert len(pos_overlay._memory_store) == initial_pos_stats
    assert len(neg_overlay._memory_store) == initial_neg_stats
