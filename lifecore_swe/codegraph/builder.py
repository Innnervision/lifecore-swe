"""Deterministic Repository Graph Builder."""

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from .schema import Node, Edge, compute_content_hash
from .parser import CodeParser


class RepositoryGraphBuilder:
    """Builds a deterministic structural graph of a repository."""

    def __init__(self, repo_path: str, repo_id: Optional[str] = None):
        self.repo_path = Path(repo_path).resolve()
        self.repo_id = repo_id or self.repo_path.name
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}

    def build(self) -> Tuple[Dict[str, Node], Dict[str, Edge]]:
        """Execute deterministic graph construction."""
        self.nodes.clear()
        self.edges.clear()

        # 1. Root Repository Node
        root_hash = compute_content_hash(str(self.repo_path))
        repo_node = Node(
            node_id=f"repo:{self.repo_id}",
            node_type="repository",
            repository_id=self.repo_id,
            path="",
            symbol=self.repo_id,
            language="python",
            content_hash=root_hash,
            metadata={"abs_path": str(self.repo_path)},
        )
        self._add_node(repo_node)

        # 2. File & Directory Hierarchy
        py_files: List[Path] = []
        dir_nodes: Dict[str, Node] = {"": repo_node}

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            rel_dir = os.path.relpath(root, self.repo_path)
            if rel_dir == ".":
                rel_dir = ""

            # Ensure Directory Node exists
            if rel_dir and rel_dir not in dir_nodes:
                parent_dir = os.path.dirname(rel_dir)
                d_node = Node(
                    node_id=f"dir:{rel_dir}",
                    node_type="directory",
                    repository_id=self.repo_id,
                    path=rel_dir,
                    symbol=os.path.basename(rel_dir),
                    language="filesystem",
                    content_hash=compute_content_hash(rel_dir),
                )
                self._add_node(d_node)
                dir_nodes[rel_dir] = d_node

                parent_node = dir_nodes.get(parent_dir, repo_node)
                self._add_edge(
                    source=parent_node.node_id,
                    target=d_node.node_id,
                    edge_type="CONTAINS",
                    confidence=1.0,
                    evidence=f"Directory hierarchy: {parent_dir or 'root'} contains {rel_dir}",
                )

            current_dir_node = dir_nodes.get(rel_dir, repo_node)

            for file_name in sorted(files):
                if file_name.startswith(".") or file_name.endswith(".pyc"):
                    continue
                file_rel = os.path.normpath(os.path.join(rel_dir, file_name)) if rel_dir else file_name
                file_path = self.repo_path / file_rel
                content_hash = ""
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        content_hash = compute_content_hash(f.read())
                except Exception:
                    pass

                f_node = Node(
                    node_id=f"file:{file_rel}",
                    node_type="file",
                    repository_id=self.repo_id,
                    path=file_rel,
                    symbol=file_name,
                    language="python" if file_name.endswith(".py") else "text",
                    content_hash=content_hash,
                )
                self._add_node(f_node)
                self._add_edge(
                    source=current_dir_node.node_id,
                    target=f_node.node_id,
                    edge_type="CONTAINS",
                    confidence=1.0,
                    evidence=f"Filesystem containment: {rel_dir or 'root'} contains {file_name}",
                )

                if file_name.endswith(".py"):
                    py_files.append(file_path)

        # 3. Code Entity Extraction & Internal AST Analysis
        parsed_results: Dict[str, Dict] = {}
        symbol_to_nodes: Dict[str, List[Node]] = {}

        for py_path in py_files:
            rel = str(py_path.relative_to(self.repo_path))
            parser = CodeParser(str(py_path), str(self.repo_path))
            parsed = parser.parse()
            parsed_results[rel] = parsed

            file_node_id = f"file:{rel}"
            # Module Node
            mod_symbol = rel.replace("/", ".").replace(".py", "")
            mod_node = Node(
                node_id=f"module:{mod_symbol}",
                node_type="module",
                repository_id=self.repo_id,
                path=rel,
                symbol=mod_symbol,
                start_line=1,
                end_line=parsed["lines"],
                language="python",
                content_hash=parsed["file_hash"],
            )
            self._add_node(mod_node)
            self._add_edge(
                source=file_node_id,
                target=mod_node.node_id,
                edge_type="DEFINES",
                confidence=1.0,
                evidence=f"File {rel} defines module {mod_symbol}",
            )

            # Class, Function, Method, and Test Nodes
            for entity in parsed["entities"]:
                e_id = f"{entity.entity_type}:{rel}::{entity.name}"
                e_node = Node(
                    node_id=e_id,
                    node_type=entity.entity_type,
                    repository_id=self.repo_id,
                    path=rel,
                    symbol=entity.name,
                    start_line=entity.start_line,
                    end_line=entity.end_line,
                    language="python",
                    content_hash=entity.content_hash,
                    metadata={
                        "calls": entity.calls,
                        "references": entity.references,
                        "parent": entity.parent,
                    },
                )
                self._add_node(e_node)

                # Edge from module or class
                if entity.parent:
                    parent_id = f"class:{rel}::{entity.parent}"
                    if parent_id in self.nodes:
                        self._add_edge(
                            source=parent_id,
                            target=e_id,
                            edge_type="DEFINES",
                            confidence=1.0,
                            evidence=f"Class {entity.parent} defines method {entity.name}",
                        )
                    else:
                        self._add_edge(
                            source=mod_node.node_id,
                            target=e_id,
                            edge_type="DEFINES",
                            confidence=1.0,
                            evidence=f"Module {mod_symbol} defines {entity.name}",
                        )
                else:
                    self._add_edge(
                        source=mod_node.node_id,
                        target=e_id,
                        edge_type="DEFINES",
                        confidence=1.0,
                        evidence=f"Module {mod_symbol} defines {entity.name}",
                    )

                # Index symbol mapping
                short_name = entity.name.split(".")[-1]
                symbol_to_nodes.setdefault(entity.name, []).append(e_node)
                symbol_to_nodes.setdefault(short_name, []).append(e_node)

        # 4. Imports Resolution
        for rel, parsed in parsed_results.items():
            mod_symbol = rel.replace("/", ".").replace(".py", "")
            src_mod_id = f"module:{mod_symbol}"

            for imp in parsed["imports"]:
                if imp.module:
                    # Check if internal module
                    matched_mod = None
                    for m_node in self.nodes.values():
                        if m_node.node_type == "module" and (
                            m_node.symbol == imp.module or m_node.symbol.endswith(f".{imp.module}")
                        ):
                            matched_mod = m_node
                            break

                    if matched_mod:
                        self._add_edge(
                            source=src_mod_id,
                            target=matched_mod.node_id,
                            edge_type="IMPORTS",
                            confidence=0.95,
                            evidence=f"Import statement in {rel}: from {imp.module} import {', '.join(imp.names)}",
                        )
                else:
                    for name in imp.names:
                        matched_mod = None
                        for m_node in self.nodes.values():
                            if m_node.node_type == "module" and m_node.symbol.endswith(name):
                                matched_mod = m_node
                                break
                        if matched_mod:
                            self._add_edge(
                                source=src_mod_id,
                                target=matched_mod.node_id,
                                edge_type="IMPORTS",
                                confidence=0.90,
                                evidence=f"Import statement in {rel}: import {name}",
                            )

        # 5. CALLS & REFERENCES Resolution
        for node in list(self.nodes.values()):
            if node.node_type in ("function", "method", "test"):
                calls = node.metadata.get("calls", [])
                refs = node.metadata.get("references", [])

                for call_name in calls:
                    candidates = symbol_to_nodes.get(call_name, [])
                    for cand in candidates:
                        if cand.node_id != node.node_id and cand.node_type in ("function", "method", "class"):
                            self._add_edge(
                                source=node.node_id,
                                target=cand.node_id,
                                edge_type="CALLS",
                                confidence=0.88,
                                evidence=f"AST call expression: {node.symbol} invokes {call_name}",
                            )

                for ref_name in refs:
                    candidates = symbol_to_nodes.get(ref_name, [])
                    for cand in candidates:
                        if cand.node_id != node.node_id and cand.node_type in ("class", "function", "method"):
                            edge_key = f"{node.node_id}->CALLS->{cand.node_id}"
                            if edge_key not in self.edges:
                                self._add_edge(
                                    source=node.node_id,
                                    target=cand.node_id,
                                    edge_type="REFERENCES",
                                    confidence=0.75,
                                    evidence=f"AST attribute or name reference: {node.symbol} references {ref_name}",
                                )

        # 6. TESTS Resolution
        for node in list(self.nodes.values()):
            if node.node_type == "test":
                calls = node.metadata.get("calls", [])
                refs = node.metadata.get("references", [])

                # Target functions or classes invoked by the test
                tested_targets: Set[str] = set()
                for c in calls + refs:
                    cands = symbol_to_nodes.get(c, [])
                    for cand in cands:
                        if cand.node_type in ("function", "method", "class") and cand.path != node.path:
                            tested_targets.add(cand.node_id)

                # If test calls process_window (Pipeline), and pipeline calls is_in_window (Filter),
                # propagate TESTS relation with transitive evidence
                for target_id in list(tested_targets):
                    target_node = self.nodes.get(target_id)
                    if not target_node:
                        continue

                    self._add_edge(
                        source=node.node_id,
                        target=target_node.node_id,
                        edge_type="TESTS",
                        confidence=0.92,
                        evidence=f"Test verification: {node.symbol} directly executes/asserts {target_node.symbol}",
                    )

                    # 1-hop transitive call targets (e.g. process_window -> is_in_window, should_retain)
                    target_calls = target_node.metadata.get("calls", [])
                    for sub_call in target_calls:
                        sub_cands = symbol_to_nodes.get(sub_call, [])
                        for sub_cand in sub_cands:
                            if sub_cand.node_type in ("function", "method"):
                                self._add_edge(
                                    source=node.node_id,
                                    target=sub_cand.node_id,
                                    edge_type="TESTS",
                                    confidence=0.85,
                                    evidence=f"Transitive test execution: {node.symbol} calls {target_node.symbol} which calls {sub_cand.symbol}",
                                )

        return self.nodes, self.edges

    def _add_node(self, node: Node) -> None:
        self.nodes[node.node_id] = node

    def _add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        confidence: float = 1.0,
        evidence: str = "",
    ) -> None:
        edge_id = f"{source}->{edge_type}->{target}"
        edge = Edge(
            edge_id=edge_id,
            source=source,
            target=target,
            edge_type=edge_type,
            confidence=confidence,
            evidence=evidence,
        )
        self.edges[edge_id] = edge
