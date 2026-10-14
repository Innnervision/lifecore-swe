"""M2 Controlled Stale Experience Experiment (Section 17)."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from lifecore_swe.experience.models import (
    ExperienceRecord,
    ExperienceRetrievalConfig,
    StaleStatus,
    VerificationStatus,
)
from lifecore_swe.experience.store import ExperienceStore
from lifecore_swe.experience.retriever import ExperienceRetriever

REPO_PATH = Path("/lifecore-swe/fixtures/scaled_repo").resolve()
RESULTS_FILE = Path("/lifecore-swe/experiments/results/m2_stale_experiment.json")

def restore_repo():
    subprocess.run(["git", "restore", "."], cwd=str(REPO_PATH), check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=str(REPO_PATH), check=True)

def run_stale_experiment():
    print("=== M2 Controlled Stale Experience Experiment ===")
    restore_repo()

    target_file = REPO_PATH / "hydra_mesh/ingest/rate_limiter.py"
    initial_content = target_file.read_text(encoding="utf-8")
    initial_hash = ExperienceRecord.compute_file_hash(target_file)

    # Temporary isolated experience store for stale experiment
    db_file = Path("/lifecore-swe/experiments/experience/stale_experiment.db")
    db_file.unlink(missing_ok=True)
    store = ExperienceStore(db_path=str(db_file))
    retriever = ExperienceRetriever(store=store)

    exp_rec = ExperienceRecord(
        experience_id="EXP-STALE-001",
        task_id="SEQ-TASK-1",
        repository_id="scaled_repo",
        repository_version="v1.0.0",
        task_description="Fix burst allowance in SlidingWindowLimiter to prevent premature throttling.",
        task_category="bug_fix",
        relevant_nodes=["SlidingWindowLimiter.allow_request"],
        files_inspected=["hydra_mesh/ingest/rate_limiter.py"],
        files_modified=["hydra_mesh/ingest/rate_limiter.py"],
        symbols_modified=["SlidingWindowLimiter.allow_request"],
        hypothesis="Limit check dropped requests at max_requests instead of max_requests + burst_allowance.",
        patch_summary="limit = self.max_requests + self.burst_allowance",
        final_patch="--- a/rate_limiter.py\n+++ b/rate_limiter.py\n+ limit = self.max_requests + self.burst_allowance",
        tests_run=[{"summary": "2 passed", "passed": True}],
        verification_result={"status": "PASSED", "success": True},
        success=True,
        confidence=1.0,
        timestamp="2026-09-27T10:00:00Z",
        provenance={"git_commit": "585e0ab"},
        verification_status=VerificationStatus.VERIFIED.value,
        file_hashes={"hydra_mesh/ingest/rate_limiter.py": initial_hash},
    )
    store.insert(exp_rec)
    print("Initial verified experience inserted into store.")

    experiment_log = []

    # Phase 1: Clean Baseline -> VALID
    res1 = retriever.retrieve(
        task_text="Administrative rate limiter reset and burst allowance",
        repo_path=str(REPO_PATH),
        repo_id="scaled_repo",
        repo_version="v1.0.0",
    )
    status1 = res1.stale_statuses.get("EXP-STALE-001")
    detail1 = res1.stale_details.get("EXP-STALE-001")
    print(f"Phase 1 (Clean baseline): {status1} - {detail1}")
    assert status1 == StaleStatus.VALID.value
    experiment_log.append({"phase": "1_clean_baseline", "status": status1, "detail": detail1, "detected_correctly": True})

    # Phase 2: Controlled File Modification -> STALE
    print("Applying controlled modification to rate_limiter.py...")
    modified_content = initial_content + "\n# Modified by concurrent team commit\n"
    target_file.write_text(modified_content, encoding="utf-8")

    res2 = retriever.retrieve(
        task_text="Administrative rate limiter reset and burst allowance",
        repo_path=str(REPO_PATH),
        repo_id="scaled_repo",
        repo_version="v1.0.0",
    )
    status2 = res2.stale_statuses.get("EXP-STALE-001")
    detail2 = res2.stale_details.get("EXP-STALE-001")
    print(f"Phase 2 (File modified): {status2} - {detail2}")
    assert status2 == StaleStatus.STALE.value
    assert "Files modified since task verified" in detail2
    experiment_log.append({"phase": "2_file_modified", "status": status2, "detail": detail2, "detected_correctly": True})

    # Phase 3: File Deletion/Relocation -> CONTRADICTED
    print("Simulating file deletion/rename...")
    target_file.unlink()

    res3 = retriever.retrieve(
        task_text="Administrative rate limiter reset and burst allowance",
        repo_path=str(REPO_PATH),
        repo_id="scaled_repo",
        repo_version="v1.0.0",
    )
    status3 = res3.stale_statuses.get("EXP-STALE-001")
    detail3 = res3.stale_details.get("EXP-STALE-001")
    print(f"Phase 3 (File missing): {status3} - {detail3}")
    assert status3 == StaleStatus.CONTRADICTED.value
    assert "Files no longer exist" in detail3
    experiment_log.append({"phase": "3_file_missing", "status": status3, "detail": detail3, "detected_correctly": True})

    # Phase 4: Version Bumping with Pristine Content -> REVALIDATED
    print("Restoring pristine content with updated repository version...")
    target_file.write_text(initial_content, encoding="utf-8")

    res4 = retriever.retrieve(
        task_text="Administrative rate limiter reset and burst allowance",
        repo_path=str(REPO_PATH),
        repo_id="scaled_repo",
        repo_version="v2.0.0",  # Changed version!
    )
    status4 = res4.stale_statuses.get("EXP-STALE-001")
    detail4 = res4.stale_details.get("EXP-STALE-001")
    print(f"Phase 4 (Version bump): {status4} - {detail4}")
    assert status4 == StaleStatus.REVALIDATED.value
    experiment_log.append({"phase": "4_version_bump", "status": status4, "detail": detail4, "detected_correctly": True})

    restore_repo()

    report_data = {
        "experiment": "M2_CONTROLLED_STALE_EXPERIENCE",
        "target_file": "hydra_mesh/ingest/rate_limiter.py",
        "initial_file_hash": initial_hash,
        "phases": experiment_log,
        "summary": "All 4 freshness phases (VALID, STALE, CONTRADICTED, REVALIDATED) were deterministically identified.",
    }

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"Saved stale experience experiment report to {RESULTS_FILE}")

if __name__ == "__main__":
    run_stale_experiment()
