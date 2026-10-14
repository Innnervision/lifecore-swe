"""File reader restricted to repository boundary."""

from pathlib import Path
from typing import Optional


class RepositoryReader:
    """Reads file contents within repository root with boundary verification."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def read_file(self, rel_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        """Read content of a file with boundary validation and optional line slice."""
        target_path = (self.repo_path / rel_path).resolve()
        if not str(target_path).startswith(str(self.repo_path)):
            raise PermissionError(f"Access denied: Path {rel_path} escapes repository boundary.")
        if not target_path.exists():
            raise FileNotFoundError(f"File not found: {rel_path}")
        if not target_path.is_file():
            raise IsADirectoryError(f"Target is not a regular file: {rel_path}")

        with open(target_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if start_line is not None or end_line is not None:
            s = (start_line - 1) if (start_line and start_line > 0) else 0
            e = end_line if (end_line and end_line > 0) else len(lines)
            return "".join(lines[s:e])
        return "".join(lines)
