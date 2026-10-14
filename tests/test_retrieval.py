"""Unit tests for the M1C Graph-Guided Retrieval Layer."""

import pytest
from lifecore_swe.codegraph.builder import RepositoryGraphBuilder
from lifecore_swe.codegraph.index import GraphIndex
from lifecore_swe.retrieval.models import RetrievalConfig, RetrievalResult
from lifecore_swe.retrieval.context_builder import ContextBuilder
from lifecore_swe.retrieval.graph_retriever import GraphRetriever

REPO_PATH = "/lifecore-swe/fixtures/buggy_repo"


@pytest.fixture(scope="module")
def graph_index():
    builder = RepositoryGraphBuilder(REPO_PATH, repo_id="buggy_repo")
    nodes, edges = builder.build()
    return GraphIndex(nodes, edges)


def test_retrieval_candidate_retrieval_and_ranking(graph_index):
    retriever = GraphRetriever(graph_index)
    task = "Fix boundary drop in window_end for EventFilter and critical override"
    res = retriever.retrieve(task)

    assert len(res.candidate_nodes) > 0
    top_cand = res.candidate_nodes[0]
    assert "relevance_score" in top_cand
    assert top_cand["relevance_score"] > 0
    assert any("window" in c["symbol"].lower() or "filter" in c["symbol"].lower() for c in res.candidate_nodes[:3])


def test_graph_expansion_and_test_association(graph_index):
    retriever = GraphRetriever(graph_index)
    task = "EventFilter.is_in_window drops boundary events"
    cfg = RetrievalConfig(enable_relationship_expansion=True, expansion_depth=1)
    res = retriever.retrieve(task, config=cfg)

    # Should find associated tests via TESTS edges
    assert len(res.associated_tests) > 0
    test_symbols = [t["symbol"] for t in res.associated_tests]
    assert "test_window_boundary_inclusion" in test_symbols

    # Should contain TESTS edges
    edge_types = {e["edge_type"] for e in res.selected_edges}
    assert "TESTS" in edge_types or "CALLS" in edge_types


def test_deterministic_results(graph_index):
    retriever = GraphRetriever(graph_index)
    task = "Fix ingestion discrepancies in EventPipeline.process_window"
    cfg = RetrievalConfig()

    run1 = retriever.retrieve(task, config=cfg)
    run2 = retriever.retrieve(task, config=cfg)

    assert run1.relevant_files == run2.relevant_files
    assert [n["node_id"] for n in run1.selected_nodes] == [n["node_id"] for n in run2.selected_nodes]
    assert [e["edge_id"] for e in run1.selected_edges] == [e["edge_id"] for e in run2.selected_edges]
    assert run1.compact_context == run2.compact_context


def test_context_construction_and_budget(graph_index):
    retriever = GraphRetriever(graph_index)
    task = "EventPipeline and EventFilter windowing logic"
    max_chars = 500
    cfg = RetrievalConfig(max_context_chars=max_chars)
    res = retriever.retrieve(task, config=cfg)

    assert len(res.compact_context) <= max_chars
    assert "GRAPH-GUIDED REPOSITORY EVIDENCE" in res.compact_context


def test_node_and_edge_limits(graph_index):
    retriever = GraphRetriever(graph_index)
    task = "event pipeline window boundary severity fatal info"
    cfg = RetrievalConfig(max_nodes=2, max_edges=3, max_files=1)
    res = retriever.retrieve(task, config=cfg)

    assert len(res.selected_nodes) <= 2
    assert len(res.selected_edges) <= 3
    assert len(res.relevant_files) <= 1


def test_empty_query_behavior(graph_index):
    retriever = GraphRetriever(graph_index)
    res = retriever.retrieve("")
    assert isinstance(res, RetrievalResult)
    assert len(res.selected_nodes) > 0  # Fallback to key nodes
    assert res.latency_ms >= 0.0


def test_unknown_symbol_behavior(graph_index):
    retriever = GraphRetriever(graph_index)
    res = retriever.retrieve("NonExistentComponentZ99999")
    assert isinstance(res, RetrievalResult)
    assert len(res.selected_nodes) > 0  # Gracefully handles unknown symbol


def test_duplicate_node_elimination(graph_index):
    retriever = GraphRetriever(graph_index)
    res = retriever.retrieve("EventFilter is_in_window is_in_window EventFilter")
    node_ids = [n["node_id"] for n in res.selected_nodes]
    assert len(node_ids) == len(set(node_ids))
