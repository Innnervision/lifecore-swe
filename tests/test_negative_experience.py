"""Unit tests for M4 Failure-Aware Graph and Negative Experience Learning."""

import tempfile
import time
from pathlib import Path
import pytest

from lifecore_swe.experience.models import ExperienceRecord

from lifecore_swe.codegraph.builder import RepositoryGraphBuilder
from lifecore_swe.codegraph.index import GraphIndex
from lifecore_swe.experience_graph.attributor import FailureAttributor
from lifecore_swe.experience_graph.edge_scorer import DeterministicEdgeScorer
from lifecore_swe.experience_graph.models import (
    AttributionStrength,
    ExperienceEdgeStats,
    ExperienceGraphConfig,
    FailureType,
    FreshnessStatus,
    NegativeEdgeStats,
    NegativeExperienceRecord,
    ScoredEdge,
)
from lifecore_swe.experience_graph.negative_overlay import NegativeGraphOverlay
from lifecore_swe.experience_graph.overlay import ExperienceGraphOverlay
from lifecore_swe.experience_graph.adaptive_traversal import AdaptiveGraphTraversal
from lifecore_swe.experience_graph.adaptive_retriever import AdaptiveGraphRetriever


@pytest.fixture
def sample_graph():
    """Build a mini AST code graph for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
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
        (pkg / "crypto.py").write_text(
            """
class CryptoHelper:
    def sign_payload(self, data: str) -> str:
        return "signed"
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
def temp_overlays():
    """Create temporary positive and negative overlays."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f1:
        pos_db = f1.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f2:
        neg_db = f2.name

    pos_overlay = ExperienceGraphOverlay(db_path=pos_db)
    neg_overlay = NegativeGraphOverlay(db_path=neg_db)

    yield pos_overlay, neg_overlay

    Path(pos_db).unlink(missing_ok=True)
    Path(neg_db).unlink(missing_ok=True)


def test_failure_attributor_classification_and_attribution(sample_graph):
    """Test FailureAttributor correctly identifies failure types and causal attribution."""
    graph, tmp_path = sample_graph

    # Scenario: Agent edited allow_request, and tests failed with AssertionError
    test_results = [{
        "summary": "FAILED tests/test_limiter.py::test_rate_limiter - AssertionError: Burst limit breached",
        "output": "AssertionError: allow_request('client') returned False unexpectedly in allow_request line 14",
    }]
    hypotheses = [{"hypothesis": "Fixing allow_request to allow sub-second burst"}]

    records = FailureAttributor.analyze_failure(
        task_id="TASK-FAIL-1",
        task_description="Fix rate limiter allow_request",
        task_category="bug_fix",
        repo_path=tmp_path,
        repo_version="v1.0",
        files_inspected=["pkg/rate_limiter.py"],
        files_modified=["pkg/rate_limiter.py"],
        hypotheses=hypotheses,
        actions=[{"tool": "edit_file", "arguments": {"file_path": "pkg/rate_limiter.py"}}],
        test_results=test_results,
        graph_index=graph,
    )

    assert len(records) > 0
    primary_rec = records[0]
    assert primary_rec.failure_type == FailureType.TEST_FAILURE.value
    assert primary_rec.attribution_strength in (AttributionStrength.STRONG.value, AttributionStrength.VERIFIED.value)
    assert primary_rec.failed_transition is not None
    assert primary_rec.is_penalizable(attribution_filtering=True) is True


def test_failure_attributor_weak_attribution_when_no_edit(sample_graph):
    """CRITICAL SCIENTIFIC RULE (Section 3): Unattributed failures must not penalize edges."""
    graph, tmp_path = sample_graph

    # Agent inspected file but never edited it; hit tool loop budget
    records = FailureAttributor.analyze_failure(
        task_id="TASK-FAIL-TIMEOUT",
        task_description="Investigate memory leak",
        task_category="bug_fix",
        repo_path=tmp_path,
        repo_version="v1.0",
        files_inspected=["pkg/rate_limiter.py"],
        files_modified=[],  # No edits!
        hypotheses=[],
        actions=[{"tool": "search_text"}],
        test_results=[],
        graph_index=graph,
        tool_calls_count=20,
        max_loop_iterations=20,
    )

    assert len(records) == 1
    assert records[0].failure_type == FailureType.BUDGET_EXHAUSTION.value
    assert records[0].attribution_strength == AttributionStrength.NONE.value
    assert records[0].is_penalizable(attribution_filtering=True) is False


def test_negative_overlay_persistence_and_filtering(temp_overlays):
    """Test NegativeGraphOverlay SQLite persistence and attribution filtering."""
    _, neg_overlay = temp_overlays

    strong_rec = NegativeExperienceRecord(
        experience_id="NEG-001",
        task_id="T1",
        repository_id="test_repo",
        repository_version="v1.0",
        task_category="bug_fix",
        failed_transition="nodeA->CALLS->nodeB",
        source_node="nodeA",
        target_node="nodeB",
        edge_type="CALLS",
        failure_type=FailureType.TEST_FAILURE.value,
        attribution_strength=AttributionStrength.STRONG.value,
        attribution_reason="Direct test assertion failed.",
    )
    neg_overlay.update_from_negative_experience(strong_rec)

    stats = neg_overlay.get_negative_stats("nodeA", "nodeB", "CALLS")
    assert stats is not None
    assert stats.negative_event_count == 1
    assert stats.strongly_attributed_failures == 1
    assert stats.max_attribution_strength == AttributionStrength.STRONG.value
    assert "NEG-001" in stats.source_negative_experiences


def test_deterministic_negative_penalty_scoring():
    """Verify that strongly attributed failures apply deterministic bounded penalties."""
    scorer = DeterministicEdgeScorer(ExperienceGraphConfig(beta_negative=0.80, score_floor=0.15))

    neg_stats = NegativeEdgeStats(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        negative_event_count=2,
        strongly_attributed_failures=2,
        last_failure_timestamp=time.time(),
        confidence=1.0,
        max_attribution_strength=AttributionStrength.STRONG.value,
        target_symbols=["RateLimiter"],
        target_files=["pkg/rate_limiter.py"],
        failure_types={"TEST_FAILURE": 2},
    )

    scored = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        task_text="Fix RateLimiter allow_request logic",
        task_category="bug_fix",
        neg_stats=neg_stats,
    )

    assert scored.base_score == 1.0
    assert scored.negative_score > 0.20
    assert scored.final_score < 1.0
    assert "attributed failure(s)" in scored.selection_reason


def test_safety_against_over_pruning_score_floor():
    """SAFETY (Section 8): Even severe penalties must never drop an edge below score_floor."""
    floor = 0.15
    scorer = DeterministicEdgeScorer(ExperienceGraphConfig(beta_negative=5.0, score_floor=floor))

    neg_stats = NegativeEdgeStats(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        negative_event_count=10,
        strongly_attributed_failures=10,
        last_failure_timestamp=time.time(),
        confidence=1.0,
        max_attribution_strength=AttributionStrength.VERIFIED.value,
        target_symbols=["RateLimiter"],
        target_files=["pkg/rate_limiter.py"],
    )

    scored = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        task_text="Fix RateLimiter",
        task_category="bug_fix",
        neg_stats=neg_stats,
    )

    assert scored.final_score == floor


def test_positive_and_negative_interaction():
    """INTERACTION (Section 9): 5 successes + 1 failure vs 1 success + 5 failures."""
    scorer = DeterministicEdgeScorer(ExperienceGraphConfig(alpha_experience=1.0, beta_negative=0.80, score_floor=0.15))
    now = time.time()

    # Case A: 5 successes, 1 failure -> Should remain net positive
    pos_stats_5 = ExperienceEdgeStats(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        verified_success_count=5, last_success_timestamp=now, confidence=1.0,
        target_symbols=["RateLimiter"], target_files=["pkg/rate_limiter.py"],
    )
    neg_stats_1 = NegativeEdgeStats(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        negative_event_count=1, strongly_attributed_failures=1, last_failure_timestamp=now, confidence=1.0,
        max_attribution_strength=AttributionStrength.STRONG.value,
        target_symbols=["RateLimiter"], target_files=["pkg/rate_limiter.py"],
    )

    scored_a = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        task_text="Fix RateLimiter", task_category="bug_fix", stats=pos_stats_5, neg_stats=neg_stats_1,
    )
    assert scored_a.experience_score > scored_a.negative_score
    assert scored_a.net_experience_score > 0
    assert scored_a.final_score > scored_a.base_score

    # Case B: 1 success, 5 failures -> Should be net negative
    pos_stats_1 = ExperienceEdgeStats(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        verified_success_count=1, last_success_timestamp=now, confidence=1.0,
        target_symbols=["RateLimiter"], target_files=["pkg/rate_limiter.py"],
    )
    neg_stats_5 = NegativeEdgeStats(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        negative_event_count=5, strongly_attributed_failures=5, last_failure_timestamp=now, confidence=1.0,
        max_attribution_strength=AttributionStrength.VERIFIED.value,
        target_symbols=["RateLimiter"], target_files=["pkg/rate_limiter.py"],
    )

    scored_b = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        task_text="Fix RateLimiter", task_category="bug_fix", stats=pos_stats_1, neg_stats=neg_stats_5,
    )
    assert scored_b.negative_score > scored_b.experience_score
    assert scored_b.net_experience_score < 0
    assert scored_b.final_score < scored_b.base_score


def test_task_conditioned_negative_penalty():
    """TASK CONDITIONING (Section 7): Failure in rate_limiter must not penalize crypto tasks."""
    scorer = DeterministicEdgeScorer()
    neg_stats = NegativeEdgeStats(
        edge_id="nodeA->CALLS->nodeB",
        source="nodeA",
        target="nodeB",
        edge_type="CALLS",
        negative_event_count=2,
        strongly_attributed_failures=2,
        last_failure_timestamp=time.time(),
        max_attribution_strength=AttributionStrength.STRONG.value,
        target_symbols=["RateLimiter", "allow_request"],
        target_files=["pkg/rate_limiter.py"],
    )

    # Rate limiter task -> high penalty
    scored_rl = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        task_text="Fix RateLimiter allow_request", task_category="bug_fix", neg_stats=neg_stats,
    )

    # Crypto task -> suppressed penalty
    scored_crypto = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        task_text="Refactor sign_payload in crypto module", task_category="refactor", neg_stats=neg_stats,
    )

    assert scored_rl.negative_score > scored_crypto.negative_score


def test_stale_negative_suppression(sample_graph):
    """STALENESS (Section 10): If target file was modified or deleted since failure, penalty decays/suppresses."""
    graph, tmp_path = sample_graph
    scorer = DeterministicEdgeScorer()

    target_file = tmp_path / "pkg" / "rate_limiter.py"
    initial_hash = scorer._compute_file_hash(target_file)

    neg_stats = NegativeEdgeStats(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        negative_event_count=2, strongly_attributed_failures=2, last_failure_timestamp=time.time(),
        max_attribution_strength=AttributionStrength.STRONG.value,
        target_symbols=["RateLimiter"], target_files=["pkg/rate_limiter.py"],
        file_hashes={"pkg/rate_limiter.py": initial_hash},
    )

    # Fresh state
    fresh_scored = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        task_text="Fix RateLimiter", neg_stats=neg_stats, repo_path=tmp_path,
    )

    # File modified -> Stale failure penalty damped
    target_file.write_text("# Live code edited since failure\n", encoding="utf-8")
    stale_scored = scorer.score_edge(
        edge_id="nodeA->CALLS->nodeB", source="nodeA", target="nodeB", edge_type="CALLS",
        task_text="Fix RateLimiter", neg_stats=neg_stats, repo_path=tmp_path,
    )

    assert stale_scored.negative_score < fresh_scored.negative_score


def test_adaptive_traversal_penalized_demotion(sample_graph, temp_overlays):
    """Adaptive traversal demotes penalized failure edges below unpenalized edges."""
    graph, tmp_path = sample_graph
    pos_overlay, neg_overlay = temp_overlays

    # Find RateLimiter node
    nodes = graph.find_by_symbol("RateLimiter")
    rl_node = nodes[0]

    # Add negative failure experience to one of the methods
    neg_rec = NegativeExperienceRecord(
        experience_id="NEG-FAIL-DEMOTE",
        task_id="T_FAIL",
        repository_id="test_repo",
        repository_version="v1.0",
        task_category="bug_fix",
        failed_transition=f"{rl_node.node_id}->DEFINES->method:pkg/rate_limiter.py::RateLimiter.reset",
        source_node=rl_node.node_id,
        target_node="method:pkg/rate_limiter.py::RateLimiter.reset",
        edge_type="DEFINES",
        attribution_strength=AttributionStrength.STRONG.value,
        attribution_reason="Agent attempted reset refactor that caused regressions.",
    )
    neg_overlay.update_from_negative_experience(neg_rec, graph)

    traversal = AdaptiveGraphTraversal(index=graph, overlay=pos_overlay, negative_overlay=neg_overlay)
    neighbors = traversal.experience_guided_neighbors(
        node_id=rl_node.node_id,
        task_text="Fix RateLimiter",
        task_category="bug_fix",
    )

    # Verify that the penalized edge is demoted and reflects negative_score
    penalized_found = [e for e, _ in neighbors if e.negative_score > 0.0]
    assert len(penalized_found) > 0
    assert penalized_found[0].negative_score > 0.0
    assert penalized_found[0].final_score < penalized_found[0].base_score


def test_adaptive_retriever_with_penalized_edges(sample_graph, temp_overlays):
    """AdaptiveGraphRetriever identifies and surfaces penalized edges."""
    graph, tmp_path = sample_graph
    pos_overlay, neg_overlay = temp_overlays

    # Insert verified positive and attributed negative
    pos_rec = ExperienceRecord(
        experience_id="EXP-P1",
        task_id="T_POS",
        repository_id="test_repo",
        repository_version="v1.0",
        task_description="Fix RateLimiter allow_request",
        task_category="bug_fix",
        symbols_modified=["allow_request"],
        success=True,
        verification_status="VERIFIED",
    )
    pos_overlay.update_from_experience(pos_rec, graph)

    neg_rec = NegativeExperienceRecord(
        experience_id="NEG-N1",
        task_id="T_NEG",
        repository_id="test_repo",
        repository_version="v1.0",
        task_category="bug_fix",
        failed_transition="method:pkg/rate_limiter.py::RateLimiter.reset->CALLS->pkg/rate_limiter.py",
        source_node="method:pkg/rate_limiter.py::RateLimiter.reset",
        target_node="pkg/rate_limiter.py",
        edge_type="CALLS",
        attribution_strength=AttributionStrength.STRONG.value,
    )
    neg_overlay.update_from_negative_experience(neg_rec, graph)

    retriever = AdaptiveGraphRetriever(
        index=graph,
        overlay=pos_overlay,
        negative_overlay=neg_overlay,
    )
    result = retriever.retrieve(
        task_text="Fix RateLimiter allow_request",
        task_category="bug_fix",
        repo_path=tmp_path,
    )

    assert result.experience_guided_edge_utilization > 0.0
    assert "EXPERIENCE-CONDITIONED REPOSITORY GRAPH EVIDENCE" in result.compact_context
