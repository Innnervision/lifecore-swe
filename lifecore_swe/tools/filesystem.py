"""Filesystem tool wrapper enforcing repository sandbox containment."""

from pathlib import Path
from typing import Any, Dict, List, Optional
from ..repository.scanner import RepositoryScanner
from ..repository.search import RepositorySearch
from ..repository.reader import RepositoryReader
from ..repository.editor import RepositoryEditor


class ControlledFileSystemTool:
    """Provides controlled and audited filesystem operations."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self.scanner = RepositoryScanner(str(self.repo_path))
        self.searcher = RepositorySearch(str(self.repo_path))
        self.reader = RepositoryReader(str(self.repo_path))
        self.editor = RepositoryEditor(str(self.repo_path))

    def list_files(self) -> List[str]:
        return self.scanner.list_files()

    def read_file(self, rel_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        return self.reader.read_file(rel_path, start_line, end_line)

    def search_text(self, query: str) -> List[Dict[str, Any]]:
        return self.searcher.search_text(query)

    def search_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        return self.searcher.search_symbol(symbol)

    def write_file(self, rel_path: str, content: str) -> None:
        self.editor.write_file(rel_path, content)

    def replace_in_file(self, rel_path: str, old_str: str, new_str: str) -> bool:
        return self.editor.replace_in_file(rel_path, old_str, new_str)
