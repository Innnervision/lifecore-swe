"""Experience Overlay for Repository Graph.

Maintains an independent, persistent overlay of verified historical transitions
without modifying the underlying AST/code graph ground truth.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..codegraph.index import GraphIndex
from ..experience.models import ExperienceRecord
from .models import ExperienceEdgeStats, FreshnessStatus


class ExperienceGraphOverlay:
    """Manages persistent experience weights associated with repository graph edges."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._memory_store: Dict[str, ExperienceEdgeStats] = {}
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._init_sqlite()
            self._load_from_sqlite()

    def _init_sqlite(self) -> None:
        """Initialize SQLite schema for edge experience overlay."""
        assert self.db_path is not None
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_experience (
                edge_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                verified_success_count INTEGER DEFAULT 0,
                verified_failure_count INTEGER DEFAULT 0,
                task_categories TEXT,
                last_success_timestamp REAL,
                confidence REAL DEFAULT 1.0,
                repository_versions TEXT,
                source_experiences TEXT,
                target_files TEXT,
                target_symbols TEXT,
                file_hashes TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edge_src ON edge_experience(source)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edge_tgt ON edge_experience(target)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edge_type ON edge_experience(edge_type)")
        conn.commit()
        conn.close()

    def _load_from_sqlite(self) -> None:
        """Load overlay records from SQLite into memory cache."""
        assert self.db_path is not None
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM edge_experience")
        for row in cur.fetchall():
            stats = ExperienceEdgeStats(
                edge_id=row[0],
                source=row[1],
                target=row[2],
                edge_type=row[3],
                verified_success_count=row[4],
                verified_failure_count=row[5],
                task_categories=json.loads(row[6]) if row[6] else {},
                last_success_timestamp=row[7] or 0.0,
                confidence=row[8] if row[8] is not None else 1.0,
                repository_versions=json.loads(row[9]) if row[9] else [],
                source_experiences=json.loads(row[10]) if row[10] else [],
                target_files=json.loads(row[11]) if row[11] else [],
                target_symbols=json.loads(row[12]) if row[12] else [],
                file_hashes=json.loads(row[13]) if row[13] else {},
            )
            self._memory_store[stats.edge_id] = stats
        conn.close()

    def _persist_stat(self, stats: ExperienceEdgeStats) -> None:
        """Persist single edge stat to SQLite."""
        self._memory_store[stats.edge_id] = stats
        if not self.db_path:
            return

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO edge_experience (
                edge_id, source, target, edge_type,
                verified_success_count, verified_failure_count,
                task_categories, last_success_timestamp, confidence,
                repository_versions, source_experiences, target_files,
                target_symbols, file_hashes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                verified_success_count = excluded.verified_success_count,
                verified_failure_count = excluded.verified_failure_count,
                task_categories = excluded.task_categories,
                last_success_timestamp = excluded.last_success_timestamp,
                confidence = excluded.confidence,
                repository_versions = excluded.repository_versions,
                source_experiences = excluded.source_experiences,
                target_files = excluded.target_files,
                target_symbols = excluded.target_symbols,
                file_hashes = excluded.file_hashes
            """,
            (
                stats.edge_id,
                stats.source,
                stats.target,
                stats.edge_type,
                stats.verified_success_count,
                stats.verified_failure_count,
                json.dumps(stats.task_categories),
                stats.last_success_timestamp,
                stats.confidence,
                json.dumps(stats.repository_versions),
                json.dumps(stats.source_experiences),
                json.dumps(stats.target_files),
                json.dumps(stats.target_symbols),
                json.dumps(stats.file_hashes),
            ),
        )
        conn.commit()
        conn.close()

    def get_edge_stats(self, source: str, target: str, edge_type: str) -> Optional[ExperienceEdgeStats]:
        """Lookup experience stats for an edge."""
        edge_id = f"{source}->{edge_type}->{target}"
        return self._memory_store.get(edge_id)

    def get_stats_by_id(self, edge_id: str) -> Optional[ExperienceEdgeStats]:
        """Lookup experience stats by canonical edge ID."""
        return self._memory_store.get(edge_id)

    def all_stats(self) -> List[ExperienceEdgeStats]:
        """Return all edge experience stats."""
        return list(self._memory_store.values())

    def update_from_experience(
        self,
        exp: ExperienceRecord,
        index: GraphIndex,
    ) -> List[str]:
        """Extract edge evidence from verified trajectory and update experience overlay.

        CRITICAL REQUIREMENT (Section 14):
        Only VERIFIED trajectories can modify positive experience weights.
        FAILED trajectories do NOT increase positive weight.
        """
        if not exp.is_verified:
            return []

        updated_edge_ids: List[str] = []
        now = time.time()

        # Step A: Discover edges from explicit relevant_edges
        edge_candidates: Set[Tuple[str, str, str]] = set()

        for edge_str in exp.relevant_edges:
            # Parse formats like "source->type->target"
            parts = edge_str.split("->")
            if len(parts) == 3:
                edge_candidates.add((parts[0].strip(), parts[1].strip(), parts[2].strip()))

        # Step B: Discover structural edges linking modified symbols and tests
        all_symbols = set(exp.symbols_modified)
        for act in exp.actions:
            sym = act.get("arguments", {}).get("symbol")
            if sym:
                all_symbols.add(sym)

        # For each modified symbol, find AST nodes
        for sym in all_symbols:
            matching_nodes = index.find_by_symbol(sym)
            for m_node in matching_nodes:
                nid = m_node.node_id
                # Incoming CALLS, TESTS, DEFINES
                for inc in index.get_incoming(nid, edge_type="CALLS"):
                    edge_candidates.add((inc.source, inc.edge_type, inc.target))
                for inc in index.get_incoming(nid, edge_type="TESTS"):
                    edge_candidates.add((inc.source, inc.edge_type, inc.target))
                for inc in index.get_incoming(nid, edge_type="DEFINES"):
                    edge_candidates.add((inc.source, inc.edge_type, inc.target))
                # Outgoing CALLS and DEFINES
                for out in index.get_outgoing(nid, edge_type="CALLS"):
                    edge_candidates.add((out.source, out.edge_type, out.target))
                for out in index.get_outgoing(nid, edge_type="DEFINES"):
                    edge_candidates.add((out.source, out.edge_type, out.target))

        # Also connect test runner executions
        for t_info in exp.tests_run:
            t_target = t_info.get("test_target", "")
            if "::" in t_target:
                t_func = t_target.split("::")[-1]
                t_nodes = index.find_by_symbol(t_func)
                for tn in t_nodes:
                    for out in index.get_outgoing(tn.node_id, edge_type="TESTS"):
                        edge_candidates.add((out.source, out.edge_type, out.target))
                    for inc in index.get_incoming(tn.node_id, edge_type="TESTS"):
                        edge_candidates.add((inc.source, inc.edge_type, inc.target))

        # Step C: Update or create ExperienceEdgeStats for each candidate edge
        for src, etype, tgt in edge_candidates:
            edge_id = f"{src}->{etype}->{tgt}"
            stats = self._memory_store.get(edge_id)

            src_node = index.get_node(src)
            tgt_node = index.get_node(tgt)

            t_files = set(stats.target_files if stats else [])
            t_symbols = set(stats.target_symbols if stats else [])

            if src_node:
                if src_node.path:
                    t_files.add(src_node.path)
                if src_node.symbol:
                    t_symbols.add(src_node.symbol)
            if tgt_node:
                if tgt_node.path:
                    t_files.add(tgt_node.path)
                if tgt_node.symbol:
                    t_symbols.add(tgt_node.symbol)

            # File hashes from exp
            f_hashes = dict(stats.file_hashes if stats else {})
            for fpath, fhash in exp.file_hashes.items():
                if fpath in t_files:
                    f_hashes[fpath] = fhash

            if not stats:
                stats = ExperienceEdgeStats(
                    edge_id=edge_id,
                    source=src,
                    target=tgt,
                    edge_type=etype,
                    verified_success_count=1,
                    verified_failure_count=0,
                    task_categories={exp.task_category: 1},
                    last_success_timestamp=now,
                    confidence=exp.confidence,
                    repository_versions=[exp.repository_version] if exp.repository_version else [],
                    source_experiences=[exp.experience_id],
                    target_files=sorted(list(t_files)),
                    target_symbols=sorted(list(t_symbols)),
                    file_hashes=f_hashes,
                )
            else:
                stats.verified_success_count += 1
                stats.task_categories[exp.task_category] = stats.task_categories.get(exp.task_category, 0) + 1
                stats.last_success_timestamp = now
                stats.confidence = (stats.confidence + exp.confidence) / 2.0
                if exp.repository_version and exp.repository_version not in stats.repository_versions:
                    stats.repository_versions.append(exp.repository_version)
                if exp.experience_id not in stats.source_experiences:
                    stats.source_experiences.append(exp.experience_id)
                stats.target_files = sorted(list(t_files))
                stats.target_symbols = sorted(list(t_symbols))
                stats.file_hashes = f_hashes

            self._persist_stat(stats)
            updated_edge_ids.append(edge_id)

        return updated_edge_ids
