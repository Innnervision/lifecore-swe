"""SQLite persistence store for external software resources and provenance.

Deterministic relational storage for external software resources, audit provenance,
and version histories without contaminating the internal code graph.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .models import FreshnessStatus, ResourceRecord, ResourceType, ResourceVerificationStatus
from .provenance import ProvenanceRecord, RetrievalMethod, SourceType, TrustLevel


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS resources (
    resource_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    title TEXT,
    description TEXT,
    repository TEXT,
    package_name TEXT,
    version TEXT,
    content_hash TEXT,
    retrieved_at TEXT,
    published_at TEXT,
    license TEXT,
    author_or_owner TEXT,
    parent_resource_id TEXT,
    provenance_id TEXT,
    confidence REAL DEFAULT 1.0,
    freshness TEXT DEFAULT 'UNKNOWN',
    verification_status TEXT DEFAULT 'UNVERIFIED',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provenance (
    provenance_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT,
    retrieved_at TEXT,
    retrieval_method TEXT,
    content_hash TEXT,
    declared_version TEXT,
    observed_version TEXT,
    license TEXT,
    parent_resource_id TEXT,
    trust_level TEXT,
    notes TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_versions (
    version_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id TEXT NOT NULL,
    version TEXT,
    content_hash TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(resource_id) REFERENCES resources(resource_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_resources_type ON resources(resource_type);
CREATE INDEX IF NOT EXISTS idx_resources_source ON resources(source);
CREATE INDEX IF NOT EXISTS idx_resources_pkg ON resources(package_name);
CREATE INDEX IF NOT EXISTS idx_resources_repo ON resources(repository);
CREATE INDEX IF NOT EXISTS idx_resources_status ON resources(verification_status);
CREATE INDEX IF NOT EXISTS idx_resources_content_hash ON resources(content_hash);
CREATE INDEX IF NOT EXISTS idx_resources_url ON resources(url);

CREATE INDEX IF NOT EXISTS idx_provenance_source ON provenance(source_name);
CREATE INDEX IF NOT EXISTS idx_provenance_hash ON provenance(content_hash);
CREATE INDEX IF NOT EXISTS idx_versions_res_id ON resource_versions(resource_id);
"""


class ResourceStore:
    """Persistent storage manager for external resources using SQLite."""

    def __init__(self, db_path: Union[str, Path] = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA_SQL)

    def close(self) -> None:
        if self.conn:
            self.conn.close()

    def __enter__(self) -> ResourceStore:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def insert_resource(self, record: ResourceRecord) -> bool:
        """Insert a new resource record. Returns True on success, False if already exists."""
        query = """
        INSERT INTO resources (
            resource_id, resource_type, source, url, title, description,
            repository, package_name, version, content_hash, retrieved_at,
            published_at, license, author_or_owner, parent_resource_id,
            provenance_id, confidence, freshness, verification_status,
            metadata, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?
        )
        """
        try:
            with self.conn:
                self.conn.execute(
                    query,
                    (
                        record.resource_id,
                        record.resource_type.value,
                        record.source,
                        record.url,
                        record.title,
                        record.description,
                        record.repository,
                        record.package_name,
                        record.version,
                        record.content_hash,
                        record.retrieved_at,
                        record.published_at,
                        record.license,
                        record.author_or_owner,
                        record.parent_resource_id,
                        record.provenance_id,
                        record.confidence,
                        record.freshness.value,
                        record.verification_status.value,
                        json.dumps(record.metadata, sort_keys=True),
                        record.created_at,
                        record.updated_at,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_resource(self, resource_id: str) -> Optional[ResourceRecord]:
        """Fetch a single resource by its resource_id."""
        query = "SELECT * FROM resources WHERE resource_id = ?"
        cursor = self.conn.execute(query, (resource_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_resource(row)

    def update_resource(self, record: ResourceRecord) -> bool:
        """Update an existing resource record."""
        query = """
        UPDATE resources SET
            resource_type = ?,
            source = ?,
            url = ?,
            title = ?,
            description = ?,
            repository = ?,
            package_name = ?,
            version = ?,
            content_hash = ?,
            retrieved_at = ?,
            published_at = ?,
            license = ?,
            author_or_owner = ?,
            parent_resource_id = ?,
            provenance_id = ?,
            confidence = ?,
            freshness = ?,
            verification_status = ?,
            metadata = ?,
            updated_at = ?
        WHERE resource_id = ?
        """
        with self.conn:
            cursor = self.conn.execute(
                query,
                (
                    record.resource_type.value,
                    record.source,
                    record.url,
                    record.title,
                    record.description,
                    record.repository,
                    record.package_name,
                    record.version,
                    record.content_hash,
                    record.retrieved_at,
                    record.published_at,
                    record.license,
                    record.author_or_owner,
                    record.parent_resource_id,
                    record.provenance_id,
                    record.confidence,
                    record.freshness.value,
                    record.verification_status.value,
                    json.dumps(record.metadata, sort_keys=True),
                    record.updated_at,
                    record.resource_id,
                ),
            )
            return cursor.rowcount > 0

    def delete_resource(self, resource_id: str) -> bool:
        """Delete a resource by ID."""
        with self.conn:
            cursor = self.conn.execute("DELETE FROM resources WHERE resource_id = ?", (resource_id,))
            return cursor.rowcount > 0

    def list_resources(self, limit: int = 100, offset: int = 0) -> List[ResourceRecord]:
        """List resources ordered by creation date."""
        query = "SELECT * FROM resources ORDER BY created_at ASC LIMIT ? OFFSET ?"
        cursor = self.conn.execute(query, (limit, offset))
        return [self._row_to_resource(row) for row in cursor.fetchall()]

    def count_resources(self) -> int:
        """Count total resources in store."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM resources")
        return cursor.fetchone()[0]

    def query_resources(
        self,
        resource_type: Optional[Union[ResourceType, str]] = None,
        source: Optional[str] = None,
        package_name: Optional[str] = None,
        repository: Optional[str] = None,
        version: Optional[str] = None,
        verification_status: Optional[Union[ResourceVerificationStatus, str]] = None,
        freshness: Optional[Union[FreshnessStatus, str]] = None,
        content_hash: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ResourceRecord]:
        """Query resources with filtering parameters."""
        clauses = []
        params: List[Any] = []

        if resource_type is not None:
            r_type_val = resource_type.value if isinstance(resource_type, ResourceType) else str(resource_type)
            clauses.append("resource_type = ?")
            params.append(r_type_val)

        if source is not None:
            clauses.append("source = ?")
            params.append(source)

        if package_name is not None:
            clauses.append("package_name = ?")
            params.append(package_name)

        if repository is not None:
            clauses.append("repository = ?")
            params.append(repository)

        if version is not None:
            clauses.append("version = ?")
            params.append(version)

        if verification_status is not None:
            v_val = verification_status.value if isinstance(verification_status, ResourceVerificationStatus) else str(verification_status)
            clauses.append("verification_status = ?")
            params.append(v_val)

        if freshness is not None:
            f_val = freshness.value if isinstance(freshness, FreshnessStatus) else str(freshness)
            clauses.append("freshness = ?")
            params.append(f_val)

        if content_hash is not None:
            clauses.append("content_hash = ?")
            params.append(content_hash)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM resources {where_sql} ORDER BY created_at ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = self.conn.execute(query, tuple(params))
        return [self._row_to_resource(row) for row in cursor.fetchall()]

    def insert_provenance(self, record: ProvenanceRecord) -> bool:
        """Insert provenance record."""
        query = """
        INSERT INTO provenance (
            provenance_id, source_type, source_name, source_url,
            retrieved_at, retrieval_method, content_hash, declared_version,
            observed_version, license, parent_resource_id, trust_level,
            notes, metadata, created_at
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?
        )
        """
        try:
            with self.conn:
                self.conn.execute(
                    query,
                    (
                        record.provenance_id,
                        record.source_type.value,
                        record.source_name,
                        record.source_url,
                        record.retrieved_at,
                        record.retrieval_method.value,
                        record.content_hash,
                        record.declared_version,
                        record.observed_version,
                        record.license,
                        record.parent_resource_id,
                        record.trust_level.value,
                        record.notes,
                        json.dumps(record.metadata, sort_keys=True),
                        record.created_at,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_provenance(self, provenance_id: str) -> Optional[ProvenanceRecord]:
        """Fetch provenance record by ID."""
        cursor = self.conn.execute("SELECT * FROM provenance WHERE provenance_id = ?", (provenance_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_provenance(row)

    def list_provenances(self, limit: int = 100, offset: int = 0) -> List[ProvenanceRecord]:
        """List provenance records."""
        cursor = self.conn.execute("SELECT * FROM provenance ORDER BY created_at ASC LIMIT ? OFFSET ?", (limit, offset))
        return [self._row_to_provenance(row) for row in cursor.fetchall()]

    def count_provenances(self) -> int:
        """Count total provenance records."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM provenance")
        return cursor.fetchone()[0]

    def record_version(
        self,
        resource_id: str,
        version: Optional[str],
        content_hash: str,
        verification_status: str,
        updated_at: str,
    ) -> int:
        """Record a historical version entry for a resource."""
        query = """
        INSERT INTO resource_versions (
            resource_id, version, content_hash, verification_status, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """
        with self.conn:
            cursor = self.conn.execute(
                query,
                (resource_id, version, content_hash, verification_status, updated_at),
            )
            return cursor.lastrowid

    def get_versions(self, resource_id: str) -> List[Dict[str, Any]]:
        """Get version history entries for a given resource."""
        query = "SELECT * FROM resource_versions WHERE resource_id = ? ORDER BY version_entry_id ASC"
        cursor = self.conn.execute(query, (resource_id,))
        return [dict(row) for row in cursor.fetchall()]

    def clear(self) -> None:
        """Clear all tables."""
        with self.conn:
            self.conn.execute("DELETE FROM resource_versions")
            self.conn.execute("DELETE FROM resources")
            self.conn.execute("DELETE FROM provenance")

    def _row_to_resource(self, row: sqlite3.Row) -> ResourceRecord:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        return ResourceRecord(
            resource_id=row["resource_id"],
            resource_type=ResourceType(row["resource_type"]),
            source=row["source"],
            url=row["url"],
            title=row["title"] or "",
            description=row["description"] or "",
            repository=row["repository"],
            package_name=row["package_name"],
            version=row["version"],
            content_hash=row["content_hash"] or "",
            retrieved_at=row["retrieved_at"],
            published_at=row["published_at"],
            license=row["license"],
            author_or_owner=row["author_or_owner"],
            parent_resource_id=row["parent_resource_id"],
            provenance_id=row["provenance_id"],
            confidence=float(row["confidence"]),
            freshness=FreshnessStatus(row["freshness"]),
            verification_status=ResourceVerificationStatus(row["verification_status"]),
            metadata=meta,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_provenance(self, row: sqlite3.Row) -> ProvenanceRecord:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        return ProvenanceRecord(
            provenance_id=row["provenance_id"],
            source_type=SourceType(row["source_type"]),
            source_name=row["source_name"],
            source_url=row["source_url"],
            retrieved_at=row["retrieved_at"],
            retrieval_method=RetrievalMethod(row["retrieval_method"]),
            content_hash=row["content_hash"] or "",
            declared_version=row["declared_version"],
            observed_version=row["observed_version"],
            license=row["license"],
            parent_resource_id=row["parent_resource_id"],
            trust_level=TrustLevel(row["trust_level"]),
            notes=row["notes"] or "",
            metadata=meta,
            created_at=row["created_at"],
        )
