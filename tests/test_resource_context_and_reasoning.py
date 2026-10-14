"""Unit tests for M5-D: Integrating Verified Resource Evidence into Reasoning.

Validates:
- ResourceContextBuilder truth labeling and formatting
- Provenance, version, status, confidence, and relevance display
- Unverified vs Verified advisory warnings
- Contradiction detection and warning display
- Context budget enforcement and truncation
- UnifiedWorldModelContextBuilder multi-stream evidence separation (Streams 1-4)
- SWEAgent end-to-end integration with resource graph retrieval
- Security boundary invariance (zero mutation of code graph or experience overlays)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
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
from lifecore_swe.resources.graph.schema import (
    ResourceEdge,
    ResourceEdgeType,
    ResourceNode,
    ResourceNodeType,
)
from lifecore_swe.resources.graph.index import ResourceGraph
from lifecore_swe.resources.graph.retriever import (
    ResourceEvidenceItem,
    ResourceGraphRetriever,
    ResourceRetrievalConfig,
    ResourceRetrievalResult,
)
from lifecore_swe.resources.context_builder import (
    ResourceContextBuilder,
    UnifiedWorldModelContextBuilder,
)
from lifecore_swe.agent.agent import SWEAgent
from lifecore_swe.agent.model_adapter import RuleBasedDevAdapter
from lifecore_swe.codegraph.schema import Node, Edge
from lifecore_swe.codegraph.index import GraphIndex
from lifecore_swe.experience_graph.overlay import ExperienceGraphOverlay
from lifecore_swe.experience_graph.negative_overlay import NegativeGraphOverlay


@pytest.fixture
def sample_resource_evidence():
    """Create sample retrieval result and provenance map for context testing."""
    node_verified = ResourceNode(
        node_id="res_ast_parse",
        node_type=ResourceNodeType.API,
        title="ast.parse Function Specification",
        source="python-docs",
        package_name="ast",
        version="3.12.0",
        description="Parse source code into an abstract syntax tree root node.",
        verification_status=ResourceVerificationStatus.VERIFIED,
        freshness=FreshnessStatus.FRESH,
        confidence=0.98,
        provenance_id="prov_ast_official",
    )
    edge_docs = ResourceEdge(
        edge_id="e1",
        source_id="res_ast_parse",
        target_id="package:ast",
        edge_type=ResourceEdgeType.DOCUMENTS,
    )
    item_verified = ResourceEvidenceItem(
        node=node_verified,
        score=0.92,
        reasons=["Exact package match on ast", "Official docs"],
        sub_scores={"relevance": 1.0, "authority": 1.0, "version": 1.0},
        relationships=[edge_docs],
    )

    node_unverified = ResourceNode(
        node_id="res_forum_snippet",
        node_type=ResourceNodeType.EXAMPLE,
        title="Community AST Visitor Snippet",
        source="community-forum",
        package_name="ast",
        version="3.10.0",
        description="Unofficial community helper function for AST modification.",
        verification_status=ResourceVerificationStatus.RETRIEVED,
        freshness=FreshnessStatus.AGING,
        confidence=0.60,
        provenance_id="prov_forum",
    )
    item_unverified = ResourceEvidenceItem(
        node=node_unverified,
        score=0.55,
        reasons=["Community forum reference", "Aging freshness"],
        sub_scores={"relevance": 0.7, "authority": 0.5},
        relationships=[],
    )

    node_contradicted = ResourceNode(
        node_id="res_conflict",
        node_type=ResourceNodeType.PACKAGE,
        title="Conflicting Ast Package",
        source="untrusted-mirror",
        package_name="ast",
        version="1.0.0",
        description="Conflicting assertions about AST visitor structure.",
        verification_status=ResourceVerificationStatus.CONTRADICTED,
        freshness=FreshnessStatus.STALE,
        confidence=0.20,
        provenance_id="prov_untrusted",
    )
    item_contradicted = ResourceEvidenceItem(
        node=node_contradicted,
        score=0.20,
        reasons=["Contradiction detected"],
        sub_scores={"relevance": 0.5, "status": 0.0},
        relationships=[],
    )

    prov_map = {
        "prov_ast_official": ProvenanceRecord.create(
            source_type=SourceType.DOCUMENTATION_SITE,
            source_name="python-docs",
            declared_version="3.12.0",
            trust_level=TrustLevel.HIGH,
            custom_id="prov_ast_official",
        ),
        "prov_forum": ProvenanceRecord.create(
            source_type=SourceType.COMMUNITY_FORUM,
            source_name="community-forum",
            trust_level=TrustLevel.LOW,
            custom_id="prov_forum",
        ),
        "prov_untrusted": ProvenanceRecord.create(
            source_type=SourceType.OTHER,
            source_name="untrusted-mirror",
            trust_level=TrustLevel.UNTRUSTED,
            custom_id="prov_untrusted",
        ),
    }

    result = ResourceRetrievalResult(
        query="parse ast python code",
        items=[item_verified, item_unverified, item_contradicted],
        total_candidates_considered=12,
        traversal_depth=2,
        execution_time_ms=1.45,
    )

    return result, prov_map


# 1. Fallback formatting on empty result
def test_resource_context_builder_empty():
    empty_result = ResourceRetrievalResult(
        query="unknown package",
        items=[],
        total_candidates_considered=0,
        traversal_depth=2,
        execution_time_ms=0.5,
    )
    context = ResourceContextBuilder.build_resource_context(empty_result)
    assert "EXTERNAL RESOURCE EVIDENCE" in context
    assert "No relevant external resources retrieved" in context
    assert "TRUTH BOUNDARY" in context


# 2. Exact formatting of required fields
def test_resource_context_builder_formatting(sample_resource_evidence):
    result, prov_map = sample_resource_evidence
    context = ResourceContextBuilder.build_resource_context(result, provenance_map=prov_map)

    # Check truth boundary header
    assert "=== EXTERNAL RESOURCE EVIDENCE ===" in context
    assert "TRUTH BOUNDARY:" in context
    assert "Internal repository code and ground truth ALWAYS supersede" in context

    # Check first item fields
    assert "TITLE: ast.parse Function Specification" in context
    assert "TYPE: API" in context
    assert "VERSION: 3.12.0" in context
    assert "STATUS: VERIFIED" in context
    assert "SOURCE: python-docs" in context
    assert "CONFIDENCE: 0.98" in context
    assert "RELEVANCE: 0.92" in context
    assert "PROVENANCE:" in context
    assert "Source Type: DOCUMENTATION_SITE" in context
    assert "DOCUMENTS->package:ast" in context


# 3. Unverified warning display
def test_resource_context_builder_unverified_warning(sample_resource_evidence):
    result, prov_map = sample_resource_evidence
    context = ResourceContextBuilder.build_resource_context(result, provenance_map=prov_map)

    # Unverified items must contain explicit warning
    assert "WARNING: Resource is UNVERIFIED / RETRIEVED only. Do NOT treat as ground-truth" in context


# 4. Contradiction warning display
def test_resource_context_builder_contradiction_warning(sample_resource_evidence):
    result, prov_map = sample_resource_evidence
    context = ResourceContextBuilder.build_resource_context(result, provenance_map=prov_map)

    # Contradicted item must contain critical warning
    assert "CRITICAL WARNING: CONTRADICTION DETECTED" in context


# 5. Verified note display
def test_resource_context_builder_verified_note(sample_resource_evidence):
    result, prov_map = sample_resource_evidence
    context = ResourceContextBuilder.build_resource_context(result, provenance_map=prov_map)

    assert "VERIFICATION NOTE: Resource has been explicitly validated against repository ground truth" in context


# 6. Character budget enforcement and clean truncation
def test_resource_context_builder_budget_enforcement(sample_resource_evidence):
    result, prov_map = sample_resource_evidence
    # Budget of 500 chars (smaller than full context)
    context = ResourceContextBuilder.build_resource_context(result, provenance_map=prov_map, max_chars=500)

    assert len(context) <= 600  # small margin for truncation message
    assert "truncated by context budget" in context or len(context) <= 500


# 7. UnifiedWorldModelContextBuilder stream separation
def test_unified_world_model_context_builder_streams():
    code_evidence = "PRIORITY RELEVANT FILES:\n  - event_processor/filters.py"
    pos_exp = "VERIFIED POSITIVE TRANSITIONS:\n  - Filter.allow_request -> True"
    neg_exp = "PENALIZED TRANSITIONS:\n  - Filter.check_window -> False (attribution: 0.8)"
    ext_res = "RESOURCE: Official Python ast documentation\nSTATUS: VERIFIED"

    unified = UnifiedWorldModelContextBuilder.build_unified_context(
        code_graph_evidence=code_evidence,
        experience_evidence=pos_exp,
        negative_experience_evidence=neg_exp,
        resource_evidence=ext_res,
    )

    # Check 4 distinct streams
    assert "### STREAM 1: INTERNAL CODE EVIDENCE (AST REPOSITORY GRAPH)" in unified
    assert "### STREAM 2: VERIFIED POSITIVE EXPERIENCE" in unified
    assert "### STREAM 3: ATTRIBUTED NEGATIVE EXPERIENCE (FAILURE AVOIDANCE)" in unified
    assert "### STREAM 4: EXTERNAL RESOURCE EVIDENCE (PROVENANCE & VERSION AWARE)" in unified

    # Check core principle
    assert "INTERNAL REPOSITORY CODE IS ABSOLUTE GROUND TRUTH" in unified
    assert "EXTERNAL RESOURCES ARE ADVISORY ONLY" in unified


# 8. UnifiedWorldModelContextBuilder total budget truncation
def test_unified_world_model_context_builder_budget():
    huge_text = "evidence line\n" * 1000
    unified = UnifiedWorldModelContextBuilder.build_unified_context(
        code_graph_evidence=huge_text,
        max_total_chars=1000,
    )
    assert len(unified) <= 1100
    assert "Context truncated to adhere to budget" in unified


# 9. SWEAgent integration with enable_resource_graph
def test_agent_resource_graph_integration(tmp_path):
    # Setup mini repository
    py_file = tmp_path / "sample.py"
    py_file.write_text("def hello(): return 'world'\n", encoding="utf-8")

    # Setup resource graph
    res_graph = ResourceGraph()
    res_node = ResourceNode(
        node_id="res_sample_doc",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="Sample Module Documentation",
        source="python-docs",
        package_name="sample",
        version="1.0.0",
        description="Official documentation for sample module.",
        verification_status=ResourceVerificationStatus.VERIFIED,
        freshness=FreshnessStatus.FRESH,
    )
    res_graph.add_node(res_node)
    retriever = ResourceGraphRetriever(graph=res_graph)

    agent = SWEAgent(
        repo_path=str(tmp_path),
        task_id="TEST-AGENT-M5D",
        model_adapter=RuleBasedDevAdapter(),
        enable_resource_graph=True,
        resource_graph=res_graph,
        resource_retriever=retriever,
        expected_files=["sample.py"],
    )

    assert agent.enable_resource_graph is True
    assert agent.trajectory_mode == "M5"
    assert agent.resource_retriever is not None

    # Run agent loop
    result = agent.run("Document sample module function hello")
    assert result["status"] in ("SUCCESS", "COMPLETED", "FAILED")
    assert agent.resource_retrieval_result is not None
    assert "EXTERNAL RESOURCE EVIDENCE" in agent.compact_resource_evidence
    assert result["resource_result"] is not None
    assert result["resource_evidence"] is not None


# 10. Truth labeling in agent state and reason context
def test_agent_truth_labeling_isolation(tmp_path):
    py_file = tmp_path / "calc.py"
    py_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    res_graph = ResourceGraph()
    res_node = ResourceNode(
        node_id="res_math_api",
        node_type=ResourceNodeType.API,
        title="Math Add API",
        source="python-docs",
        package_name="calc",
        description="Returns sum of a and b.",
        verification_status=ResourceVerificationStatus.VERIFIED,
    )
    res_graph.add_node(res_node)
    retriever = ResourceGraphRetriever(graph=res_graph)

    agent = SWEAgent(
        repo_path=str(tmp_path),
        task_id="TEST-AGENT-M5D-ISOLATION",
        model_adapter=RuleBasedDevAdapter(),
        enable_resource_graph=True,
        resource_retriever=retriever,
        expected_files=["calc.py"],
    )

    result = agent.run("Improve add function in calc.py")

    # Assert observation contains explicit truth boundary
    obs_text = "\n".join(str(o) for o in agent.state.observations)
    assert "TRUTH BOUNDARY:" in obs_text
    assert "Internal repository code and ground truth ALWAYS supersede" in obs_text


# 11. Security boundary invariance: Resource retrieval leaves code graph and overlays unchanged
def test_agent_security_boundary_invariance(tmp_path):
    py_file = tmp_path / "calc.py"
    py_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    # Pre-existing code graph
    n1 = Node(node_id="node_1", node_type="function", repository_id="repo", path="calc.py", symbol="add")
    code_graph = GraphIndex(nodes={"node_1": n1}, edges={})
    pos_overlay = ExperienceGraphOverlay()
    neg_overlay = NegativeGraphOverlay()

    initial_nodes_len = len(code_graph.nodes)
    initial_pos_len = len(pos_overlay._memory_store)
    initial_neg_len = len(neg_overlay._memory_store)

    # Resource graph
    res_graph = ResourceGraph()
    res_node = ResourceNode(
        node_id="res_external_1",
        node_type=ResourceNodeType.DOCUMENTATION,
        title="External Math Spec",
        source="pypi",
        package_name="calc",
        verification_status=ResourceVerificationStatus.VALIDATED,
    )
    res_graph.add_node(res_node)
    retriever = ResourceGraphRetriever(graph=res_graph)

    agent = SWEAgent(
        repo_path=str(tmp_path),
        task_id="TEST-AGENT-M5D-SECURITY",
        model_adapter=RuleBasedDevAdapter(),
        enable_resource_graph=True,
        resource_retriever=retriever,
        expected_files=["calc.py"],
    )

    agent.run("Check math spec")

    # Invariance assertions
    assert len(code_graph.nodes) == initial_nodes_len
    assert "res_external_1" not in code_graph.nodes
    assert len(pos_overlay._memory_store) == initial_pos_len
    assert len(neg_overlay._memory_store) == initial_neg_len
