"""Verification module for patch integrity and test suite validation."""

from pathlib import Path
from typing import Any, Dict, List, Optional
from ..tools.test_runner import TestRunnerTool
from ..tools.diff import DiffTool


class Verifier:
    """Verifies that patched code satisfies correctness and containment criteria."""

    def __init__(self, repo_path: str, expected_files: Optional[List[str]] = None, test_target: Optional[str] = None):
        self.test_target = test_target
        self.repo_path = Path(repo_path).resolve()
        self.expected_files = expected_files or ["event_processor/filters.py"]
        self.test_runner = TestRunnerTool(str(self.repo_path))
        self.diff_tool = DiffTool(str(self.repo_path))

    def verify(self) -> Dict[str, Any]:
        """Perform comprehensive verification:
        
        1. Patch presence and diff containment.
        2. Test suite execution.
        3. Strict assertion of criteria.
        """
        diff_info = self.diff_tool.get_diff()
        files_changed = diff_info.get("files_changed", [])
        raw_diff = diff_info.get("diff", "")

        # Check 1: Patch exists
        patch_applied = len(raw_diff.strip()) > 0 and len(files_changed) > 0

        # Check 2: No unintended files modified
        unintended_files = [f for f in files_changed if f not in self.expected_files]
        containment_ok = (len(unintended_files) == 0 and patch_applied)

        # Check 3: Full test suite execution
        test_result = self.test_runner.run_tests(test_target=self.test_target)
        tests_passed = test_result.get("passed", False)

        all_passed = patch_applied and containment_ok and tests_passed

        status = "PASSED" if all_passed else "FAILED"
        failure_reasons = []
        if not patch_applied:
            failure_reasons.append("No patch detected in working tree.")
        if not containment_ok:
            failure_reasons.append(f"Unintended files modified: {unintended_files}")
        if not tests_passed:
            failure_reasons.append(f"Tests failed: {test_result.get('summary')}")

        return {
            "status": status,
            "success": all_passed,
            "patch_applied": patch_applied,
            "containment_ok": containment_ok,
            "unintended_files": unintended_files,
            "files_changed": files_changed,
            "test_command": test_result.get("command"),
            "test_summary": test_result.get("summary"),
            "test_exit_code": test_result.get("exit_code"),
            "test_output": test_result.get("stdout"),
            "failure_reasons": failure_reasons,
        }
