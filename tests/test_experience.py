"""Unit tests for the M2 persistent experience and memory subsystem."""

import tempfile
from pathlib import Path
import pytest

from lifecore_swe.experience.models import (
    ExperienceRecord,
    ExperienceRetrievalConfig,
    StaleStatus,
    VerificationStatus,
)
from lifecore_swe.experience.store import ExperienceStore
from lifecore_swe.experience.ranker import ExperienceRanker
from lifecore_swe.experience.retriever import ExperienceRetriever
from lifecore_swe.experience.context_builder import ExperienceContextBuilder


@pytest.fixture
def temp_store():
    """Create a temporary SQLite experience store."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = ExperienceStore(db_path=db_path)
    yield store
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_experience():
    """Create a verified sample experience record."""
    return ExperienceRecord(
        experience_id="EXP-TEST-001",
        task_id="TASK-201",
        repository_id="scaled_repo",
        repository_version="v1.0.0",
        task_description="Fix burst allowance in SlidingWindowLimiter to prevent premature throttling.",
        task_category="bug_fix",
        relevant_nodes=["SlidingWindowLimiter.allow_request"],
        relevant_edges=["SlidingWindowLimiter--DEFINES-->allow_request"],
        files_inspected=["hydra_mesh/ingest/rate_limiter.py"],
        files_modified=["hydra_mesh/ingest/rate_limiter.py"],
        symbols_modified=["SlidingWindowLimiter.allow_request"],
        hypothesis="Limit check dropped requests at max_requests instead of max_requests + burst_allowance.",
        actions=[{"tool": "filesystem", "action": "modify_code"}],
        observations=["Post-patch tests PASSED."],
        patch_summary="limit = self.max_requests + self.burst_allowance",
        final_patch="--- a/rate_limiter.py\n+++ b/rate_limiter.py\n+ limit = self.max_requests + self.burst_allowance",
        tests_run=[{"command": "pytest", "passed": True, "summary": "2 passed"}],
        verification_result={"status": "PASSED", "success": True},
        success=True,
        tool_usage={"tool_calls": 5, "searches": 0},
        confidence=0.95,
        timestamp="2026-09-27T12:00:00Z",
        provenance={"trajectory_file": "m1c_graph_task201.jsonl", "model": "gemma-4-26b-a4b-it"},
        verification_status=VerificationStatus.VERIFIED.value,
        file_hashes={"hydra_mesh/ingest/rate_limiter.py": "abc123hash"},
    )


def test_experience_creation_and_properties(sample_experience):
    """Test experience model serialization, verification, and property queries."""
    assert sample_experience.is_verified is True
    assert sample_experience.is_failed is False
    assert sample_experience.verification_status == "VERIFIED"

    data = sample_experience.to_dict()
    reconstructed = ExperienceRecord.from_dict(data)
    assert reconstructed.experience_id == sample_experience.experience_id
    assert reconstructed.files_modified == ["hydra_mesh/ingest/rate_limiter.py"]
    assert reconstructed.provenance["model"] == "gemma-4-26b-a4b-it"


def test_store_persistence_and_duplicate_prevention(temp_store, sample_experience):
    """Test inserting, updating, retrieving, and deduplicating experience records."""
    assert temp_store.count() == 0

    # Insert
    temp_store.insert(sample_experience)
    assert temp_store.count() == 1

    # Duplicate insertion updates instead of duplicating
    dup = ExperienceRecord.from_dict(sample_experience.to_dict())
    dup.confidence = 0.99
    temp_store.insert(dup)
    assert temp_store.count() == 1

    fetched = temp_store.get(sample_experience.experience_id)
    assert fetched is not None
    assert fetched.confidence == 0.99


def test_store_verification_state_lifecycle(temp_store, sample_experience):
    """Test updating verification states: PROPOSED -> TESTED -> VERIFIED -> REVERTED."""
    sample_experience.verification_status = VerificationStatus.PROPOSED.value
    sample_experience.success = False
    temp_store.insert(sample_experience)

    rec = temp_store.get(sample_experience.experience_id)
    assert rec.is_verified is False

    # Transition to VERIFIED
    temp_store.update_verification_status(
        sample_experience.experience_id,
        status=VerificationStatus.VERIFIED.value,
        verification_result={"status": "PASSED"},
    )
    rec2 = temp_store.get(sample_experience.experience_id)
    assert rec2.verification_status == "VERIFIED"
    assert rec2.is_verified is True

    # Transition to REVERTED
    temp_store.update_verification_status(
        sample_experience.experience_id,
        status=VerificationStatus.REVERTED.value,
    )
    rec3 = temp_store.get(sample_experience.experience_id)
    assert rec3.verification_status == "REVERTED"
    assert rec3.is_verified is False


def test_store_repository_and_category_filtering(temp_store, sample_experience):
    """Test querying store by repository, task category, and verification status."""
    temp_store.insert(sample_experience)

    exp2 = ExperienceRecord.from_dict(sample_experience.to_dict())
    exp2.experience_id = "EXP-TEST-002"
    exp2.task_id = "TASK-101"
    exp2.repository_id = "buggy_repo"
    exp2.task_category = "bug_fix"
    temp_store.insert(exp2)

    exp3 = ExperienceRecord.from_dict(sample_experience.to_dict())
    exp3.experience_id = "EXP-TEST-003"
    exp3.task_id = "TASK-202"
    exp3.repository_id = "scaled_repo"
    exp3.task_category = "security_sanitization"
    temp_store.insert(exp3)

    assert temp_store.count() == 3
    assert len(temp_store.list_all(repository_id="scaled_repo")) == 2
    assert len(temp_store.list_all(repository_id="buggy_repo")) == 1
    assert len(temp_store.list_all(task_category="security_sanitization")) == 1


def test_store_file_and_symbol_queries(temp_store, sample_experience):
    """Test retrieving experiences by inspected/modified files and symbols."""
    temp_store.insert(sample_experience)

    by_file = temp_store.find_by_files(["hydra_mesh/ingest/rate_limiter.py"])
    assert len(by_file) == 1
    assert by_file[0].experience_id == sample_experience.experience_id

    empty_file = temp_store.find_by_files(["nonexistent/path.py"])
    assert len(empty_file) == 0

    by_sym = temp_store.find_by_symbols(["SlidingWindowLimiter.allow_request"])
    assert len(by_sym) == 1


def test_deterministic_ranking_and_reasons(sample_experience):
    """Test multi-signal ranking determinism and explanation generation."""
    ranker = ExperienceRanker()
    score, reasons = ranker.score(
        candidate=sample_experience,
        query_text="Fix burst allowance in SlidingWindowLimiter",
        target_repository="scaled_repo",
        target_version="v1.0.0",
        graph_files=["hydra_mesh/ingest/rate_limiter.py"],
        graph_symbols=["SlidingWindowLimiter.allow_request"],
    )

    assert score > 0.7
    assert any("Repository match" in r for r in reasons)
    assert any("Overlapping files" in r for r in reasons)
    assert any("Verified solution" in r for r in reasons)

    # Identical inputs yield identical output
    score2, reasons2 = ranker.score(
        candidate=sample_experience,
        query_text="Fix burst allowance in SlidingWindowLimiter",
        target_repository="scaled_repo",
        target_version="v1.0.0",
        graph_files=["hydra_mesh/ingest/rate_limiter.py"],
        graph_symbols=["SlidingWindowLimiter.allow_request"],
    )
    assert score == score2
    assert reasons == reasons2


def test_retriever_staleness_detection(temp_store, sample_experience, tmp_path):
    """Test staleness detection on file modification, version mismatch, and file deletion."""
    test_file = tmp_path / "hydra_mesh" / "ingest" / "rate_limiter.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("initial code content", encoding="utf-8")

    initial_hash = ExperienceRecord.compute_file_hash(test_file)
    sample_experience.file_hashes = {"hydra_mesh/ingest/rate_limiter.py": initial_hash}
    sample_experience.repository_version = "v1.0"
    temp_store.insert(sample_experience)

    retriever = ExperienceRetriever(store=temp_store)

    # 1. Baseline matches -> VALID
    stale_st, desc = retriever.check_staleness(sample_experience, tmp_path, current_version="v1.0")
    assert stale_st == StaleStatus.VALID.value

    # 2. File content changed -> STALE
    test_file.write_text("modified code content that changed the hash", encoding="utf-8")
    stale_st2, desc2 = retriever.check_staleness(sample_experience, tmp_path, current_version="v1.0")
    assert stale_st2 == StaleStatus.STALE.value
    assert "Files modified since task verified" in desc2

    # 3. File removed -> CONTRADICTED
    test_file.unlink()
    stale_st3, desc3 = retriever.check_staleness(sample_experience, tmp_path, current_version="v1.0")
    assert stale_st3 == StaleStatus.CONTRADICTED.value


def test_context_construction_and_budget(sample_experience):
    """Test context formatting and strict character budget truncation."""
    reasons = {sample_experience.experience_id: ["Repository match", "File overlap"]}
    scores = {sample_experience.experience_id: 0.92}
    stale = {sample_experience.experience_id: StaleStatus.VALID.value}
    details = {sample_experience.experience_id: "Matches"}

    ctx = ExperienceContextBuilder.build_context(
        experiences=[sample_experience],
        selection_reasons=reasons,
        ranking_scores=scores,
        stale_statuses=stale,
        stale_details=details,
        max_chars=2000,
    )

    assert "VERIFIED EPISODIC EXPERIENCE" in ctx
    assert "CURRENT REPOSITORY STATE AND TESTS ALWAYS TAKE PRECEDENCE" in ctx
    assert sample_experience.experience_id in ctx
    assert "SlidingWindowLimiter.allow_request" in ctx
    assert len(ctx) <= 2000

    # Test small budget cutoff
    small_ctx = ExperienceContextBuilder.build_context(
        experiences=[sample_experience],
        selection_reasons=reasons,
        ranking_scores=scores,
        stale_statuses=stale,
        stale_details=details,
        max_chars=300,
    )
    assert len(small_ctx) <= 300
    assert "... [Experience Context Truncated]" in small_ctx


def test_failed_experience_handling(temp_store, sample_experience):
    """Test that failed experiences are excluded by default, but retrievable when requested."""
    sample_experience.experience_id = "EXP-FAIL-001"
    sample_experience.verification_status = VerificationStatus.FAILED.value
    sample_experience.success = False
    sample_experience.failure_reason = "AssertionError: burst capacity exceeded"
    temp_store.insert(sample_experience)

    retriever = ExperienceRetriever(store=temp_store)

    # Default config excludes failed experiences
    cfg_default = ExperienceRetrievalConfig(include_failed=False)
    res_default = retriever.retrieve(
        task_text="Fix burst allowance",
        repo_path="/lifecore-swe/fixtures/scaled_repo",
        repo_id="scaled_repo",
        config=cfg_default,
    )
    assert len(res_default.selected_experiences) == 0

    # Explicit config includes failure memory
    cfg_include_failed = ExperienceRetrievalConfig(include_failed=True)
    res_failed = retriever.retrieve(
        task_text="Fix burst allowance",
        repo_path="/lifecore-swe/fixtures/scaled_repo",
        repo_id="scaled_repo",
        config=cfg_include_failed,
    )
    assert len(res_failed.selected_experiences) == 1
    assert res_failed.selected_experiences[0].experience_id == "EXP-FAIL-001"
    assert "FAILURE MEMORY" in res_failed.compact_context
