"""Unit tests for repository graph schema, parser, builder, traversal, and serialization."""

import json
import tempfile
from pathlib import Path
import pytest

from lifecore_swe.codegraph.schema import Node, Edge, compute_content_hash
from lifecore_swe.codegraph.parser import CodeParser
from lifecore_swe.codegraph.builder import RepositoryGraphBuilder
from lifecore_swe.codegraph.index import GraphIndex
from lifecore_swe.codegraph.traversal import GraphTraversal
from lifecore_swe.codegraph.ranking import GraphRanker
from lifecore_swe.codegraph.serialization import GraphSerializer

REPO_PATH = "/lifecore-swe/fixtures/buggy_repo"


def test_node_creation():
    node = Node(
        node_id="func:sample.py::sample_func",
        node_type="function",
        repository_id="test_repo",
        path="sample.py",
        symbol="sample_func",
        start_line=1,
        end_line=5,
        content_hash=compute_content_hash("def sample_func(): pass"),
    )
    d = node.to_dict()
    assert d["node_id"] == "func:sample.py::sample_func"
    assert d["node_type"] == "function"
    assert d["symbol"] == "sample_func"

    recreated = Node.from_dict(d)
    assert recreated.node_id == node.node_id
    assert recreated.content_hash == node.content_hash


def test_edge_creation():
    edge = Edge(
        edge_id="test:A->TESTS->func:B",
        source="test:A",
        target="func:B",
        edge_type="TESTS",
        confidence=0.95,
        evidence="test calls func",
    )
    d = edge.to_dict()
    assert d["edge_type"] == "TESTS"
    assert d["confidence"] == 0.95

    recreated = Edge.from_dict(d)
    assert recreated.edge_id == edge.edge_id
    assert recreated.evidence == edge.evidence


def test_ast_parsing_and_symbol_extraction():
    parser = CodeParser(f"{REPO_PATH}/event_processor/filters.py", REPO_PATH)
    res = parser.parse()
    assert res["rel_path"] == "event_processor/filters.py"
    assert len(res["entities"]) >= 3  # EventFilter, is_in_window, should_retain

    symbols = [e.name for e in res["entities"]]
    assert "EventFilter" in symbols
    assert "EventFilter.is_in_window" in symbols
    assert "EventFilter.should_retain" in symbols

    # Check extracted lines
    filter_entity = next(e for e in res["entities"] if e.name == "EventFilter.is_in_window")
    assert filter_entity.start_line == 19
    assert filter_entity.entity_type == "method"


def test_imports_extraction():
    parser = CodeParser(f"{REPO_PATH}/event_processor/pipeline.py", REPO_PATH)
    res = parser.parse()
    imports = res["imports"]
    imported_modules = [imp.module for imp in imports if imp.module]
    assert ".models" in imported_modules or "models" in str(imported_modules)
    assert ".filters" in imported_modules or "filters" in str(imported_modules)


def test_graph_builder_and_relationships():
    builder = RepositoryGraphBuilder(REPO_PATH, repo_id="buggy_repo")
    nodes, edges = builder.build()

    assert len(nodes) > 10
    assert len(edges) > 15

    # Check node types
    node_types = set(n.node_type for n in nodes.values())
    assert "repository" in node_types
    assert "directory" in node_types
    assert "file" in node_types
    assert "module" in node_types
    assert "class" in node_types
    assert "method" in node_types
    assert "test" in node_types

    # Check edge types
    edge_types = set(e.edge_type for e in edges.values())
    assert "CONTAINS" in edge_types
    assert "DEFINES" in edge_types
    assert "IMPORTS" in edge_types
    assert "CALLS" in edge_types
    assert "TESTS" in edge_types


def test_graph_traversal_queries():
    builder = RepositoryGraphBuilder(REPO_PATH, repo_id="buggy_repo")
    nodes, edges = builder.build()
    index = GraphIndex(nodes, edges)
    trav = GraphTraversal(index)

    # 1. find_symbol
    syms = trav.find_symbol("is_in_window")
    assert len(syms) >= 1
    target_id = syms[0]["node_id"]

    # 2. find_file
    f = trav.find_file("event_processor/filters.py")
    assert f is not None
    assert f["symbol"] == "filters.py"

    # 3. find_tests
    tests = trav.find_tests(target_id)
    test_symbols = [t["symbol"] for t in tests]
    assert "test_window_boundary_inclusion" in test_symbols

    # 4. find_callers
    callers = trav.find_callers(target_id)
    caller_symbols = [c["symbol"] for c in callers]
    assert any("process_window" in s or "test_" in s for s in caller_symbols)

    # 5. neighbors
    nbrs = trav.neighbors(target_id)
    assert len(nbrs) > 0

    # 6. subgraph
    sub = trav.subgraph(target_id, depth=1)
    assert sub["center"] == target_id
    assert len(sub["nodes"]) >= 2

    # 7. search_subgraph
    matched = trav.search_subgraph("boundary")
    assert len(matched) >= 1


def test_graph_ranker():
    builder = RepositoryGraphBuilder(REPO_PATH, repo_id="buggy_repo")
    nodes, edges = builder.build()
    index = GraphIndex(nodes, edges)
    ranker = GraphRanker(index)

    ranked = ranker.rank_candidates(
        task_text="Boundary events at window_end are discarded and CRITICAL events dropped",
        failing_tests=["test_window_boundary_inclusion"],
        top_k=3,
    )
    assert len(ranked) > 0
    top_symbols = [r["symbol"] for r in ranked]
    assert any("window" in s.lower() or "filter" in s.lower() for s in top_symbols)


def test_serialization_roundtrip():
    builder = RepositoryGraphBuilder(REPO_PATH, repo_id="buggy_repo")
    nodes, edges = builder.build()

    with tempfile.TemporaryDirectory() as tmp_dir:
        files = GraphSerializer.save_graph(nodes, edges, tmp_dir, REPO_PATH, "buggy_repo")
        assert Path(files["nodes_file"]).exists()
        assert Path(files["edges_file"]).exists()
        assert Path(files["metadata_file"]).exists()

        loaded_nodes, loaded_edges, meta = GraphSerializer.load_graph(tmp_dir)
        assert len(loaded_nodes) == len(nodes)
        assert len(loaded_edges) == len(edges)
        assert meta["node_count"] == len(nodes)
        assert meta["edge_count"] == len(edges)
