"""Negative Experience Overlay for Repository Graph (M4).

Maintains a persistent, reversible overlay of attributed failure events on repository
graph transitions without mutating the base AST code graph.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..codegraph.index import GraphIndex
from .models import (
    AttributionStrength,
    FreshnessStatus,
    NegativeEdgeStats,
    NegativeExperienceRecord,
)


class NegativeGraphOverlay:
    """Manages persistent negative failure statistics on repository graph transitions."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._memory_store: Dict[str, NegativeEdgeStats] = {}
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._init_sqlite()
            self._load_from_sqlite()

    def _init_sqlite(self) -> None:
        """Initialize SQLite schema for negative edge overlay."""
        assert self.db_path is not None
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS negative_edge_experience (
                edge_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                negative_event_count INTEGER DEFAULT 0,
                strongly_attributed_failures INTEGER DEFAULT 0,
                failed_task_ids TEXT,
                failure_types TEXT,
                last_failure_timestamp REAL,
                repository_versions TEXT,
                confidence REAL DEFAULT 1.0,
                max_attribution_strength TEXT,
                source_negative_experiences TEXT,
                target_files TEXT,
                target_symbols TEXT,
                file_hashes TEXT,
                last_attribution_reason TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_neg_src ON negative_edge_experience(source)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_neg_tgt ON negative_edge_experience(target)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_neg_type ON negative_edge_experience(edge_type)")
        conn.commit()
        conn.close()

    def _load_from_sqlite(self) -> None:
        """Load records from SQLite into memory cache."""
        assert self.db_path is not None
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM negative_edge_experience")
        for row in cur.fetchall():
            stats = NegativeEdgeStats(
                edge_id=row[0],
                source=row[1],
                target=row[2],
                edge_type=row[3],
                negative_event_count=row[4],
                strongly_attributed_failures=row[5],
                failed_task_ids=json.loads(row[6]) if row[6] else [],
                failure_types=json.loads(row[7]) if row[7] else {},
                last_failure_timestamp=row[8] or 0.0,
                repository_versions=json.loads(row[9]) if row[9] else [],
                confidence=row[10] if row[10] is not None else 1.0,
                max_attribution_strength=row[11] or AttributionStrength.NONE.value,
                source_negative_experiences=json.loads(row[12]) if row[12] else [],
                target_files=json.loads(row[13]) if row[13] else [],
                target_symbols=json.loads(row[14]) if row[14] else [],
                file_hashes=json.loads(row[15]) if row[15] else {},
                last_attribution_reason=row[16] or "",
            )
            self._memory_store[stats.edge_id] = stats
        conn.close()

    def _persist_stat(self, stats: NegativeEdgeStats) -> None:
        """Persist single negative edge stat to SQLite."""
        self._memory_store[stats.edge_id] = stats
        if not self.db_path:
            return

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO negative_edge_experience (
                edge_id, source, target, edge_type,
                negative_event_count, strongly_attributed_failures,
                failed_task_ids, failure_types, last_failure_timestamp,
                repository_versions, confidence, max_attribution_strength,
                source_negative_experiences, target_files, target_symbols,
                file_hashes, last_attribution_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                negative_event_count = excluded.negative_event_count,
                strongly_attributed_failures = excluded.strongly_attributed_failures,
                failed_task_ids = excluded.failed_task_ids,
                failure_types = excluded.failure_types,
                last_failure_timestamp = excluded.last_failure_timestamp,
                repository_versions = excluded.repository_versions,
                confidence = excluded.confidence,
                max_attribution_strength = excluded.max_attribution_strength,
                source_negative_experiences = excluded.source_negative_experiences,
                target_files = excluded.target_files,
                target_symbols = excluded.target_symbols,
                file_hashes = excluded.file_hashes,
                last_attribution_reason = excluded.last_attribution_reason
            """,
            (
                stats.edge_id,
                stats.source,
                stats.target,
                stats.edge_type,
                stats.negative_event_count,
                stats.strongly_attributed_failures,
                json.dumps(stats.failed_task_ids),
                json.dumps(stats.failure_types),
                stats.last_failure_timestamp,
                json.dumps(stats.repository_versions),
                stats.confidence,
                stats.max_attribution_strength,
                json.dumps(stats.source_negative_experiences),
                json.dumps(stats.target_files),
                json.dumps(stats.target_symbols),
                json.dumps(stats.file_hashes),
                stats.last_attribution_reason,
            ),
        )
        conn.commit()
        conn.close()

    def get_negative_stats(self, source: str, target: str, edge_type: str) -> Optional[NegativeEdgeStats]:
        """Lookup negative stats for an edge."""
        edge_id = f"{source}->{edge_type}->{target}"
        return self._memory_store.get(edge_id)

    def get_stats_by_id(self, edge_id: str) -> Optional[NegativeEdgeStats]:
        """Lookup negative stats by canonical edge ID."""
        return self._memory_store.get(edge_id)

    def all_stats(self) -> List[NegativeEdgeStats]:
        """Return all negative edge stats."""
        return list(self._memory_store.values())

    def update_from_negative_experience(
        self,
        rec: NegativeExperienceRecord,
        index: Optional[GraphIndex] = None,
    ) -> Optional[str]:
        """Update negative overlay with a failure record.

        CRITICAL SCIENTIFIC RULE (Section 3):
        Only apply negative evidence when there is sufficient attribution evidence.
        Records without specific transition or with attribution NONE do not penalize edges.
        """
        if not rec.failed_transition:
            return None

        edge_id = rec.failed_transition
        parts = edge_id.split("->")
        if len(parts) != 3:
            return None

        src, etype, tgt = parts[0].strip(), parts[1].strip(), parts[2].strip()
        stats = self._memory_store.get(edge_id)

        target_files = set(stats.target_files if stats else [])
        target_symbols = set(stats.target_symbols if stats else [])

        if index:
            src_node = index.get_node(src)
            tgt_node = index.get_node(tgt)
            if src_node:
                if src_node.path:
                    target_files.add(src_node.path)
                if src_node.symbol:
                    target_symbols.add(src_node.symbol)
            if tgt_node:
                if tgt_node.path:
                    target_files.add(tgt_node.path)
                if tgt_node.symbol:
                    target_symbols.add(tgt_node.symbol)

        is_strong = rec.is_penalizable(attribution_filtering=True)

        if not stats:
            stats = NegativeEdgeStats(
                edge_id=edge_id,
                source=src,
                target=tgt,
                edge_type=etype,
                negative_event_count=1,
                strongly_attributed_failures=1 if is_strong else 0,
                failed_task_ids=[rec.task_id],
                failure_types={rec.failure_type: 1},
                last_failure_timestamp=rec.timestamp or time.time(),
                repository_versions=[rec.repository_version] if rec.repository_version else [],
                confidence=rec.confidence,
                max_attribution_strength=rec.attribution_strength,
                source_negative_experiences=[rec.experience_id],
                target_files=sorted(list(target_files)),
                target_symbols=sorted(list(target_symbols)),
                file_hashes=rec.file_hashes or {},
                last_attribution_reason=rec.attribution_reason,
            )
        else:
            stats.negative_event_count += 1
            if is_strong:
                stats.strongly_attributed_failures += 1
            if rec.task_id not in stats.failed_task_ids:
                stats.failed_task_ids.append(rec.task_id)
            stats.failure_types[rec.failure_type] = stats.failure_types.get(rec.failure_type, 0) + 1
            stats.last_failure_timestamp = rec.timestamp or time.time()
            if rec.repository_version and rec.repository_version not in stats.repository_versions:
                stats.repository_versions.append(rec.repository_version)
            stats.confidence = (stats.confidence + rec.confidence) / 2.0
            # Higher attribution strength takes precedence
            order = [AttributionStrength.NONE.value, AttributionStrength.WEAK.value, AttributionStrength.MODERATE.value, AttributionStrength.STRONG.value, AttributionStrength.VERIFIED.value]
            curr_idx = order.index(stats.max_attribution_strength) if stats.max_attribution_strength in order else 0
            new_idx = order.index(rec.attribution_strength) if rec.attribution_strength in order else 0
            if new_idx > curr_idx:
                stats.max_attribution_strength = rec.attribution_strength
            if rec.experience_id not in stats.source_negative_experiences:
                stats.source_negative_experiences.append(rec.experience_id)
            stats.target_files = sorted(list(target_files))
            stats.target_symbols = sorted(list(target_symbols))
            stats.last_attribution_reason = rec.attribution_reason

        self._persist_stat(stats)
        return edge_id
