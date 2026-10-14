"""Persistent local store for verified SWE experiences."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from .models import ExperienceRecord, VerificationStatus


class ExperienceStore:
    """SQLite-backed persistent store for verified task experiences."""

    def __init__(self, db_path: str = "/lifecore-swe/experiments/experience/store.db"):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database schema and indices."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    repository_id TEXT NOT NULL,
                    repository_version TEXT NOT NULL,
                    task_category TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_repo ON experiences(repository_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON experiences(verification_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_category ON experiences(task_category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task ON experiences(task_id)")
            conn.commit()

    def insert(self, record: ExperienceRecord) -> bool:
        """Insert or update an experience record. Deduplicates by experience_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            data_json = json.dumps(record.to_dict())
            cursor.execute("""
                INSERT OR REPLACE INTO experiences (
                    experience_id, task_id, repository_id, repository_version,
                    task_category, verification_status, success, timestamp, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.experience_id,
                record.task_id,
                record.repository_id,
                record.repository_version,
                record.task_category,
                record.verification_status,
                1 if record.success else 0,
                record.timestamp,
                data_json,
            ))
            conn.commit()
            return True

    def update_verification_status(
        self,
        experience_id: str,
        status: str,
        verification_result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update the explicit verification status of an existing record."""
        rec = self.get(experience_id)
        if not rec:
            return False
        rec.verification_status = status
        if status == VerificationStatus.VERIFIED.value:
            rec.success = True
        elif status in (VerificationStatus.FAILED.value, VerificationStatus.REVERTED.value):
            rec.success = False
        if verification_result is not None:
            rec.verification_result = verification_result

        return self.insert(rec)

    def get(self, experience_id: str) -> Optional[ExperienceRecord]:
        """Retrieve a specific experience record by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT record_json FROM experiences WHERE experience_id = ?", (experience_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return ExperienceRecord.from_dict(json.loads(row["record_json"]))

    def list_all(
        self,
        repository_id: Optional[str] = None,
        verification_status: Optional[str] = None,
        task_category: Optional[str] = None,
    ) -> List[ExperienceRecord]:
        """List experiences matching optional filter criteria."""
        query = "SELECT record_json FROM experiences WHERE 1=1"
        params: List[Any] = []
        if repository_id:
            query += " AND repository_id = ?"
            params.append(repository_id)
        if verification_status:
            query += " AND verification_status = ?"
            params.append(verification_status)
        if task_category:
            query += " AND task_category = ?"
            params.append(task_category)
        query += " ORDER BY timestamp DESC"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [ExperienceRecord.from_dict(json.loads(r["record_json"])) for r in rows]

    def find_by_files(
        self,
        files: List[str],
        repository_id: Optional[str] = None,
        verification_status: Optional[str] = None,
    ) -> List[ExperienceRecord]:
        """Retrieve experiences that inspected or modified any of the specified files."""
        all_recs = self.list_all(repository_id=repository_id, verification_status=verification_status)
        matched = []
        file_set = set(files)
        for rec in all_recs:
            rec_files = set(rec.files_inspected + rec.files_modified)
            if rec_files.intersection(file_set):
                matched.append(rec)
        return matched

    def find_by_symbols(
        self,
        symbols: List[str],
        repository_id: Optional[str] = None,
        verification_status: Optional[str] = None,
    ) -> List[ExperienceRecord]:
        """Retrieve experiences touching any of the specified symbol names."""
        all_recs = self.list_all(repository_id=repository_id, verification_status=verification_status)
        matched = []
        sym_set = set(s.lower() for s in symbols)
        for rec in all_recs:
            rec_syms = set(s.lower() for s in rec.symbols_modified + rec.relevant_nodes)
            if rec_syms.intersection(sym_set):
                matched.append(rec)
        return matched

    def count(self, repository_id: Optional[str] = None) -> int:
        """Count total stored experiences."""
        query = "SELECT COUNT(*) as cnt FROM experiences"
        params: List[Any] = []
        if repository_id:
            query += " WHERE repository_id = ?"
            params.append(repository_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def clear(self) -> None:
        """Delete all stored experiences."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM experiences")
            conn.commit()
