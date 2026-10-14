"""Unit tests for the M3 Experience-Conditioned Code Graph Subsystem."""

import tempfile
from pathlib import Path
import pytest

from lifecore_swe.codegraph.builder import RepositoryGraphBuilder
from lifecore_swe.codegraph import GraphIndex
from lifecore_swe.experience.models import ExperienceRecord, VerificationStatus
from lifecore_swe.experience_graph.adaptive_retriever import AdaptiveGraphRetriever
from lifecore_swe.experience_graph.adaptive_traversal import AdaptiveGraphTraversal
from lifecore_swe.experience_graph.context_builder import AdaptiveContextBuilder
from lifecore_swe.experience_graph.edge_scorer import DeterministicEdgeScorer
from lifecore_swe.experience_graph.models import (
    ExperienceEdgeStats,
    ExperienceGraphConfig,
    FreshnessStatus,
    ScoredEdge,
)
from lifecore_swe.experience_graph.overlay import ExperienceGraphOverlay


@pytest.fixture
def sample_graph():
    """Build a mini AST code graph for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Create a mini codebase
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "rate_limiter.py").write_text(
            """
class RateLimiter:
    def allow_request(self, client_id: str) -> bool:
        return True

    def reset(self, client_id: str = None) -> None:
        pass
""",
            encoding="utf-8",
        )
        (pkg / "transformer.py").write_text(
            """
from .rate_limiter import RateLimiter

class Transformer:
    def __init__(self, limiter: RateLimiter = None):
        self.limiter = limiter

    def transform(self, data):
        if self.limiter:
            self.limiter.allow_request("client")
        return data
""",
            encoding="utf-8",
        )
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_limiter.py").write_text(
            """
from pkg.rate_limiter import RateLimiter

def test_rate_limiter():
    r = RateLimiter()
    assert r.allow_request("c1")
""",
            encoding="utf-8",
        )

        builder = RepositoryGraphBuilder(str(tmp_path), repo_id="test_repo")
        nodes, edges = builder.build()
        graph = GraphIndex(nodes, edges)
        yield graph, tmp_path


@pytest.fixture
def temp_overlay():
    """Create a temporary SQLite experience overlay."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    overlay = ExperienceGraphOverlay(db_path=db_path)
    yield overlay
    Path(db_path).unlink(missing_ok=True)


def test_edge_stats_creation_and_persistence(temp_overlay):
    """Test inserting and loading ExperienceEdgeStats in the overlay."""
    stats = ExperienceEdgeStats(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        verified_success_count=2,
        task_categories={"bug_fix": 2},
        last_success_timestamp=1700000000.0,
        confidence=0.95,
        repository_versions=["v1.0"],
        source_experiences=["EXP-001", "EXP-002"],
        target_files=["pkg/rate_limiter.py"],
        target_symbols=["RateLimiter"],
        file_hashes={"pkg/rate_limiter.py": "abc12345"},
    )
    temp_overlay._persist_stat(stats)

    loaded = temp_overlay.get_edge_stats("nodeA", "nodeB", "CALLS")
    assert loaded is not None
    assert loaded.edge_id == "nodeA->CALLS->nodeB"
    assert loaded.verified_success_count == 2
    assert "bug_fix" in loaded.task_categories
    assert "EXP-001" in loaded.source_experiences


def test_cold_start_edge_scoring():
    """Verify that unvisited edges receive exact static base scores under cold start."""
    scorer = DeterministicEdgeScorer()
    scored = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        task_text="Fix bug in RateLimiter",
        stats=None,  # No experience
    )
    assert scored.base_score == 1.0
    assert scored.experience_score == 0.0
    assert scored.final_score == 1.0
    assert "Base structural edge" in scored.selection_reason
    assert scored.contributing_experiences == []


def test_task_conditioned_edge_scoring():
    """Verify edge score boosts when task matches historical experience and stays low when unrelated."""
    scorer = DeterministicEdgeScorer()
    stats = ExperienceEdgeStats(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        verified_success_count=3,
        task_categories={"bug_fix": 3},
        last_success_timestamp=1700000000.0,
        confidence=1.0,
        source_experiences=["EXP-001"],
        target_files=["pkg/rate_limiter.py"],
        target_symbols=["RateLimiter", "allow_request"],
    )

    # Related task: should get a meaningful boost
    scored_related = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        task_text="Fix bug in RateLimiter allow_request logic",
        task_category="bug_fix",
        stats=stats,
    )
    assert scored_related.experience_score > 0.4
    assert scored_related.final_score > 1.4
    assert "EXP-001" in scored_related.contributing_experiences

    # Unrelated task: should receive lower task relevance and smaller boost
    scored_unrelated = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        task_text="Refactor cryptographic hashing subsystem in crypto_core",
        task_category="refactor",
        stats=stats,
    )
    assert scored_unrelated.task_relevance < scored_related.task_relevance
    assert scored_unrelated.final_score < scored_related.final_score


def test_stale_experience_suppression(sample_graph, temp_overlay):
    """Test that file modifications trigger STALE state and lower experience boost."""
    graph, tmp_path = sample_graph
    scorer = DeterministicEdgeScorer()

    target_file = tmp_path / "pkg" / "rate_limiter.py"
    initial_hash = scorer._compute_file_hash(target_file)

    stats = ExperienceEdgeStats(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        verified_success_count=2,
        task_categories={"bug_fix": 2},
        last_success_timestamp=1700000000.0,
        confidence=1.0,
        source_experiences=["EXP-001"],
        target_files=["pkg/rate_limiter.py"],
        target_symbols=["RateLimiter"],
        file_hashes={"pkg/rate_limiter.py": initial_hash},
    )

    # 1. Fresh state: VALID
    fresh_scored = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        task_text="Fix RateLimiter",
        stats=stats,
        repo_path=tmp_path,
    )
    assert fresh_scored.freshness_status == FreshnessStatus.VALID.value
    assert fresh_scored.freshness_factor == 1.0

    # 2. Modify file: STALE
    target_file.write_text("# Modified file content\n", encoding="utf-8")
    stale_scored = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        task_text="Fix RateLimiter",
        stats=stats,
        repo_path=tmp_path,
    )
    assert stale_scored.freshness_status == FreshnessStatus.STALE.value
    assert stale_scored.freshness_factor < 0.5
    assert stale_scored.final_score < fresh_scored.final_score

    # 3. Delete file: CONTRADICTED
    target_file.unlink()
    contra_scored = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        task_text="Fix RateLimiter",
        stats=stats,
        repo_path=tmp_path,
    )
    assert contra_scored.freshness_status == FreshnessStatus.CONTRADICTED.value
    assert contra_scored.freshness_factor == 0.0
    assert contra_scored.experience_score == 0.0
    assert contra_scored.final_score == contra_scored.base_score


def test_failed_experience_exclusion(sample_graph, temp_overlay):
    """CRITICAL: Failed trajectories must not update positive edge weights."""
    graph, _ = sample_graph

    failed_exp = ExperienceRecord(
        experience_id="EXP-FAIL-001",
        task_id="TASK-FAIL",
        repository_id="test_repo",
        repository_version="v1.0",
        task_description="Failed attempt to fix rate limiter",
        symbols_modified=["RateLimiter.allow_request"],
        success=False,
        verification_status=VerificationStatus.FAILED.value,
    )

    updated = temp_overlay.update_from_experience(failed_exp, graph)
    assert updated == []
    assert len(temp_overlay.all_stats()) == 0


def test_verified_experience_updates_overlay(sample_graph, temp_overlay):
    """Verified successful trajectory correctly discovers and updates relevant edges."""
    graph, tmp_path = sample_graph

    verified_exp = ExperienceRecord(
        experience_id="EXP-PASS-001",
        task_id="TASK-PASS",
        repository_id="test_repo",
        repository_version="v1.0",
        task_description="Successfully fixed RateLimiter.allow_request",
        task_category="bug_fix",
        symbols_modified=["allow_request", "RateLimiter"],
        files_modified=["pkg/rate_limiter.py"],
        success=True,
        verification_status=VerificationStatus.VERIFIED.value,
        tests_run=[{"test_target": "tests/test_limiter.py::test_rate_limiter"}],
    )

    updated = temp_overlay.update_from_experience(verified_exp, graph)
    assert len(updated) > 0
    all_stats = temp_overlay.all_stats()
    assert len(all_stats) > 0
    assert any("allow_request" in s.edge_id or "RateLimiter" in s.edge_id for s in all_stats)


def test_adaptive_traversal_prioritization(sample_graph, temp_overlay):
    """Adaptive traversal ranks experience-reinforced edges ahead of equal unreinforced edges."""
    graph, tmp_path = sample_graph

    # Reinforce allow_request in the overlay
    verified_exp = ExperienceRecord(
        experience_id="EXP-T1",
        task_id="SEQ-TASK-1",
        repository_id="test_repo",
        repository_version="v1.0",
        task_description="Fix RateLimiter allow_request",
        task_category="bug_fix",
        symbols_modified=["allow_request"],
        success=True,
        verification_status=VerificationStatus.VERIFIED.value,
    )
    temp_overlay.update_from_experience(verified_exp, graph)

    traversal = AdaptiveGraphTraversal(index=graph, overlay=temp_overlay)
    # Find RateLimiter node
    nodes = graph.find_by_symbol("RateLimiter")
    assert len(nodes) > 0
    rl_node = nodes[0]

    neighbors = traversal.experience_guided_neighbors(
        node_id=rl_node.node_id,
        task_text="Fix RateLimiter allow_request logic",
        task_category="bug_fix",
    )
    assert len(neighbors) > 0
    # Top neighbor edge should have positive experience score
    top_edge, _ = neighbors[0]
    assert top_edge.experience_score > 0.0
    assert top_edge.final_score > top_edge.base_score


def test_adaptive_retriever_end_to_end(sample_graph, temp_overlay):
    """AdaptiveGraphRetriever produces structured results with edge utilization metrics."""
    graph, tmp_path = sample_graph

    # Inject verified experience
    verified_exp = ExperienceRecord(
        experience_id="EXP-E2E",
        task_id="TASK-E2E",
        repository_id="test_repo",
        repository_version="v1.0",
        task_description="Fix allow_request in RateLimiter",
        task_category="bug_fix",
        symbols_modified=["allow_request"],
        success=True,
        verification_status=VerificationStatus.VERIFIED.value,
    )
    temp_overlay.update_from_experience(verified_exp, graph)

    retriever = AdaptiveGraphRetriever(index=graph, overlay=temp_overlay)
    result = retriever.retrieve(
        task_text="Fix RateLimiter allow_request burst handling",
        task_category="bug_fix",
        repo_path=tmp_path,
    )

    assert result.experience_guided_edge_utilization > 0.0
    assert len(result.experience_supported_edges) > 0
    assert "EXPERIENCE-CONDITIONED REPOSITORY GRAPH EVIDENCE" in result.compact_context
    assert len(result.traversal_log) > 0


def test_context_builder_ablation_mode():
    """Verify that AdaptiveContextBuilder correctly formats graph transitions with score explanations."""
    scored = ScoredEdge(
        edge_id="RateLimiter->CALLS->allow_request",
        source="RateLimiter",
        target="allow_request",
        edge_type="CALLS",
        source_symbol="RateLimiter",
        target_symbol="allow_request",
        base_score=1.0,
        experience_score=0.45,
        final_score=1.45,
        contributing_experiences=["EXP-001"],
        selection_reason="Verified prior task traversed this edge (+0.45)",
    )
    ctx = AdaptiveContextBuilder.build_context(
        relevant_files=["pkg/rate_limiter.py"],
        selected_nodes=[{"node_id": "n1", "node_type": "class", "symbol": "RateLimiter", "path": "pkg/rate_limiter.py"}],
        scored_edges=[scored],
        associated_tests=[],
        experience_supported_edges=["RateLimiter->CALLS->allow_request"],
        include_raw_experience_text=False,  # Condition E (ablation)
    )
    assert "Base: 1.00, Exp: +0.45, Final: 1.45" in ctx
    assert "Reason: Verified prior task traversed this edge (+0.45)" in ctx
    assert "CURRENT REPOSITORY STATE ALWAYS WINS" in ctx


def test_agent_experience_graph_integration(sample_graph, temp_overlay):
    """Test SWEAgent configured with enable_experience_graph runs retrieval cleanly."""
    from lifecore_swe.agent.agent import SWEAgent
    from lifecore_swe.agent.model_adapter import RuleBasedDevAdapter

    graph, tmp_path = sample_graph
    agent = SWEAgent(
        repo_path=str(tmp_path),
        task_id="TEST-AGENT-M3",
        model_adapter=RuleBasedDevAdapter(),
        enable_experience_graph=True,
        experience_graph_overlay=temp_overlay,
        expected_files=["pkg/rate_limiter.py"],
        test_target="tests/test_limiter.py::test_rate_limiter",
    )
    assert agent.enable_experience_graph is True
    assert agent.trajectory_mode == "M3"
    assert agent.adaptive_graph_retriever is not None
