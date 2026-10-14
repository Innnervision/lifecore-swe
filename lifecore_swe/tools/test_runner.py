"""Test runner tool for executing pytest within target repository."""

import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


class TestRunnerTool:
    """Executes pytest suites within repository boundary and parses results."""

    __test__ = False

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def run_tests(self, test_target: Optional[str] = None) -> Dict[str, Any]:
        """Execute pytest and capture structured output."""
        cmd = ["pytest", "-v"]
        if test_target:
            cmd.append(test_target)

        res = subprocess.run(
            cmd,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=False,
        )

        stdout = res.stdout
        stderr = res.stderr
        exit_code = res.returncode
        passed = (exit_code == 0)

        # Parse test metrics
        summary_line = ""
        for line in stdout.splitlines():
            if "passed" in line or "failed" in line:
                summary_line = line.strip()

        return {
            "command": " ".join(cmd),
            "exit_code": exit_code,
            "passed": passed,
            "stdout": stdout,
            "stderr": stderr,
            "summary": summary_line,
        }
