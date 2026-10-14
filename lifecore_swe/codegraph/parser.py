"""AST-based code parser for extracting structural entities and references."""

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional
from .schema import compute_content_hash


class ParsedEntity:
    """Represents an extracted structural code element."""

    def __init__(
        self,
        name: str,
        entity_type: str,
        start_line: int,
        end_line: int,
        docstring: Optional[str] = None,
        parent: Optional[str] = None,
        raw_code: str = "",
    ):
        self.name = name
        self.entity_type = entity_type  # class, function, method, test
        self.start_line = start_line
        self.end_line = end_line
        self.docstring = docstring
        self.parent = parent
        self.raw_code = raw_code
        self.calls: List[str] = []
        self.references: List[str] = []
        self.content_hash = compute_content_hash(raw_code) if raw_code else ""


class ParsedImport:
    """Represents an imported module or symbol."""

    def __init__(
        self,
        module: Optional[str],
        names: List[str],
        is_from: bool,
        level: int = 0,
        line: int = 1,
    ):
        self.module = module
        self.names = names
        self.is_from = is_from
        self.level = level
        self.line = line


class CodeParser:
    """Parses a Python source file using AST."""

    def __init__(self, file_path: str, repo_root: str):
        self.file_path = Path(file_path).resolve()
        self.repo_root = Path(repo_root).resolve()
        self.rel_path = str(self.file_path.relative_to(self.repo_root))

    def parse(self) -> Dict[str, Any]:
        """Parse source file and return extracted entities, imports, and calls."""
        if not self.file_path.exists() or not self.file_path.is_file():
            return {"entities": [], "imports": [], "file_hash": "", "lines": 0}

        try:
            with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
                source_code = f.read()
        except Exception:
            return {"entities": [], "imports": [], "file_hash": "", "lines": 0}

        file_hash = compute_content_hash(source_code)
        lines = source_code.splitlines(keepends=True)
        total_lines = len(lines)

        try:
            tree = ast.parse(source_code, filename=str(self.file_path))
        except SyntaxError:
            return {"entities": [], "imports": [], "file_hash": file_hash, "lines": total_lines}

        imports = self._extract_imports(tree)
        entities = self._extract_entities(tree, lines)

        return {
            "rel_path": self.rel_path,
            "entities": entities,
            "imports": imports,
            "file_hash": file_hash,
            "lines": total_lines,
        }

    def _extract_imports(self, tree: ast.AST) -> List[ParsedImport]:
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
                imports.append(ParsedImport(module=None, names=names, is_from=False, line=node.lineno))
            elif isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
                imports.append(
                    ParsedImport(
                        module=node.module,
                        names=names,
                        is_from=True,
                        level=node.level,
                        line=node.lineno,
                    )
                )
        return imports

    def _extract_entities(self, tree: ast.Module, lines: List[str]) -> List[ParsedEntity]:
        entities: List[ParsedEntity] = []

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                c_start = node.lineno
                c_end = getattr(node, "end_lineno", c_start)
                raw_code = "".join(lines[c_start - 1 : c_end])
                c_entity = ParsedEntity(
                    name=node.name,
                    entity_type="class",
                    start_line=c_start,
                    end_line=c_end,
                    docstring=ast.get_docstring(node),
                    raw_code=raw_code,
                )
                self._extract_calls_and_refs(node, c_entity)
                entities.append(c_entity)

                # Methods inside class
                for sub_node in node.body:
                    if isinstance(sub_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_start = sub_node.lineno
                        m_end = getattr(sub_node, "end_lineno", m_start)
                        m_code = "".join(lines[m_start - 1 : m_end])
                        is_test = sub_node.name.startswith("test_") or node.name.startswith("Test")
                        m_type = "test" if is_test else "method"
                        m_entity = ParsedEntity(
                            name=f"{node.name}.{sub_node.name}",
                            entity_type=m_type,
                            start_line=m_start,
                            end_line=m_end,
                            docstring=ast.get_docstring(sub_node),
                            parent=node.name,
                            raw_code=m_code,
                        )
                        self._extract_calls_and_refs(sub_node, m_entity)
                        entities.append(m_entity)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                f_start = node.lineno
                f_end = getattr(node, "end_lineno", f_start)
                raw_code = "".join(lines[f_start - 1 : f_end])
                is_test = node.name.startswith("test_")
                f_type = "test" if is_test else "function"
                f_entity = ParsedEntity(
                    name=node.name,
                    entity_type=f_type,
                    start_line=f_start,
                    end_line=f_end,
                    docstring=ast.get_docstring(node),
                    raw_code=raw_code,
                )
                self._extract_calls_and_refs(node, f_entity)
                entities.append(f_entity)

        return entities

    def _extract_calls_and_refs(self, node: ast.AST, entity: ParsedEntity) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name):
                    entity.calls.append(func.id)
                elif isinstance(func, ast.Attribute):
                    entity.calls.append(func.attr)
            elif isinstance(child, ast.Attribute):
                entity.references.append(child.attr)
            elif isinstance(child, ast.Name):
                entity.references.append(child.id)
        # De-duplicate while preserving order
        entity.calls = list(dict.fromkeys(entity.calls))
        entity.references = list(dict.fromkeys(entity.references))
