"""Git and unified diff utilities restricted to repository boundary."""

import subprocess
from pathlib import Path
from typing import Dict, List


class DiffTool:
    """Computes differences within the repository."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def get_diff(self) -> Dict[str, any]:
        """Compute git diff against current HEAD / initial state."""
        try:
            res = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            raw_diff = res.stdout
            # Extract modified files
            file_names: List[str] = []
            res_names = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if res_names.stdout:
                file_names = [line.strip() for line in res_names.stdout.splitlines() if line.strip()]

            return {
                "diff": raw_diff,
                "files_changed": file_names,
                "lines_added": raw_diff.count("\n+") - raw_diff.count("\n+++"),
                "lines_deleted": raw_diff.count("\n-") - raw_diff.count("\n---"),
            }
        except Exception as e:
            return {
                "diff": "",
                "files_changed": [],
                "error": str(e),
            }

    def get_modified_files(self) -> List[str]:
        """Return list of modified file paths relative to repository root."""
        return self.get_diff().get("files_changed", [])
