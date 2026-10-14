"""Search utilities for finding text and symbols within repository."""

import ast
import os
from pathlib import Path
from typing import Any, Dict, List


class RepositorySearch:
    """Provides search functionality restricted to repository boundary."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def search_text(self, query: str) -> List[Dict[str, Any]]:
        """Search text query across all text files in the repository."""
        results = []
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for file_name in sorted(files):
                if file_name.startswith(".") or file_name.endswith(".pyc"):
                    continue
                file_path = Path(root) / file_name
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        for line_num, line in enumerate(f, start=1):
                            if query.lower() in line.lower():
                                rel_path = file_path.relative_to(self.repo_path)
                                results.append({
                                    "file": str(rel_path),
                                    "line_number": line_num,
                                    "line": line.rstrip("\n"),
                                })
                except Exception:
                    continue
        return results

    def search_symbol(self, symbol_name: str) -> List[Dict[str, Any]]:
        """Search for class or function definitions matching symbol_name."""
        matches = []
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for file_name in sorted(files):
                if not file_name.endswith(".py"):
                    continue
                file_path = Path(root) / file_name
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=str(file_path))
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if symbol_name.lower() in node.name.lower():
                                rel_path = file_path.relative_to(self.repo_path)
                                matches.append({
                                    "file": str(rel_path),
                                    "symbol": node.name,
                                    "type": "class" if isinstance(node, ast.ClassDef) else "function",
                                    "line_number": node.lineno,
                                })
                except Exception:
                    continue
        return matches
