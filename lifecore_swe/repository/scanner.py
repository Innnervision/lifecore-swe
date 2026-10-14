"""Repository scanner to discover file tree and structure."""

import os
from pathlib import Path
from typing import List


class RepositoryScanner:
    """Scans and lists files in a controlled repository."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.exists() or not self.repo_path.is_dir():
            raise ValueError(f"Invalid repository path: {repo_path}")

    def list_files(self, exclude_hidden: bool = True) -> List[str]:
        """List all relative file paths within the repository."""
        file_paths = []
        for root, dirs, files in os.walk(self.repo_path):
            if exclude_hidden:
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for f in sorted(files):
                if exclude_hidden and (f.startswith(".") or f.endswith(".pyc")):
                    continue
                full_path = Path(root) / f
                rel_path = full_path.relative_to(self.repo_path)
                file_paths.append(str(rel_path))
        return sorted(file_paths)
