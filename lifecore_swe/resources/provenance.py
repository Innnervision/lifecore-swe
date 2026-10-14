"""Provenance tracking for external software resources in LIFECORE-SWE.

Tracks where external information originated, how it was ingested,
licensing, and the initial trust classification.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Union

from .models import normalize_url


class SourceType(str, Enum):
    """Classification of the external resource source."""
    DOCUMENTATION_SITE = "DOCUMENTATION_SITE"
    PACKAGE_REGISTRY = "PACKAGE_REGISTRY"
    CODE_HOSTING = "CODE_HOSTING"
    PAPER_REPOSITORY = "PAPER_REPOSITORY"
    BENCHMARK_SUITE = "BENCHMARK_SUITE"
    ISSUE_TRACKER = "ISSUE_TRACKER"
    COMMUNITY_FORUM = "COMMUNITY_FORUM"
    OTHER = "OTHER"


class TrustLevel(str, Enum):
    """Initial trust assignment for external provenance.

    External resources are never trusted by default.
    """
    UNTRUSTED = "UNTRUSTED"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERIFIED_INTERNAL = "VERIFIED_INTERNAL"


class RetrievalMethod(str, Enum):
    """Mechanism by which the external resource metadata was obtained."""
    OFFLINE_CACHE = "OFFLINE_CACHE"
    MANUAL_IMPORT = "MANUAL_IMPORT"
    FIXTURE = "FIXTURE"
    API = "API"
    WEB_CRAWL = "WEB_CRAWL"
    OTHER = "OTHER"


def generate_provenance_id(
    source_type: Union[SourceType, str],
    source_name: str,
    source_url: Optional[str] = None,
    content_hash: str = "",
    declared_version: Optional[str] = None,
) -> str:
    """Deterministically derive a provenance record identifier."""
    s_type = source_type.value if isinstance(source_type, SourceType) else str(source_type)
    s_name = (source_name or "").strip().lower()
    norm_url = normalize_url(source_url) if source_url else ""
    c_hash = (content_hash or "").strip()
    d_ver = (declared_version or "").strip()

    components = [s_type, s_name, norm_url, c_hash, d_ver]
    digest = hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()
    return f"prov_{digest[:16]}"


@dataclass
class ProvenanceRecord:
    """Provenance metadata tracking origin, method, and audit chain."""
    provenance_id: str
    source_type: SourceType
    source_name: str
    source_url: Optional[str] = None
    retrieved_at: Optional[str] = None
    retrieval_method: RetrievalMethod = RetrievalMethod.OFFLINE_CACHE
    content_hash: str = ""
    declared_version: Optional[str] = None
    observed_version: Optional[str] = None
    license: Optional[str] = None
    parent_resource_id: Optional[str] = None
    trust_level: TrustLevel = TrustLevel.LOW
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.source_type, str):
            self.source_type = SourceType(self.source_type)
        if isinstance(self.retrieval_method, str):
            self.retrieval_method = RetrievalMethod(self.retrieval_method)
        if isinstance(self.trust_level, str):
            self.trust_level = TrustLevel(self.trust_level)

        if self.source_url:
            self.source_url = normalize_url(self.source_url)

        if not self.created_at:
            self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    @classmethod
    def create(
        cls,
        source_type: Union[SourceType, str],
        source_name: str,
        source_url: Optional[str] = None,
        retrieved_at: Optional[str] = None,
        retrieval_method: Union[RetrievalMethod, str] = RetrievalMethod.OFFLINE_CACHE,
        content_hash: str = "",
        declared_version: Optional[str] = None,
        observed_version: Optional[str] = None,
        license: Optional[str] = None,
        parent_resource_id: Optional[str] = None,
        trust_level: Union[TrustLevel, str] = TrustLevel.LOW,
        notes: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        custom_id: Optional[str] = None,
    ) -> ProvenanceRecord:
        """Create a provenance record with deterministic ID generation."""
        s_type = SourceType(source_type) if isinstance(source_type, str) else source_type
        r_method = RetrievalMethod(retrieval_method) if isinstance(retrieval_method, str) else retrieval_method
        t_level = TrustLevel(trust_level) if isinstance(trust_level, str) else trust_level
        norm_url = normalize_url(source_url) if source_url else None

        p_id = custom_id or generate_provenance_id(
            source_type=s_type,
            source_name=source_name,
            source_url=norm_url,
            content_hash=content_hash,
            declared_version=declared_version,
        )

        return cls(
            provenance_id=p_id,
            source_type=s_type,
            source_name=source_name,
            source_url=norm_url,
            retrieved_at=retrieved_at,
            retrieval_method=r_method,
            content_hash=content_hash,
            declared_version=declared_version,
            observed_version=observed_version,
            license=license,
            parent_resource_id=parent_resource_id,
            trust_level=t_level,
            notes=notes,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize provenance record to dictionary."""
        d = asdict(self)
        d["source_type"] = self.source_type.value
        d["retrieval_method"] = self.retrieval_method.value
        d["trust_level"] = self.trust_level.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProvenanceRecord:
        """Deserialize provenance record from dictionary."""
        d = dict(data)
        d["source_type"] = SourceType(d["source_type"])
        d["retrieval_method"] = RetrievalMethod(d.get("retrieval_method", RetrievalMethod.OFFLINE_CACHE.value))
        d["trust_level"] = TrustLevel(d.get("trust_level", TrustLevel.LOW.value))
        return cls(**d)

    def to_canonical_json(self) -> str:
        """Serialize provenance record to canonical JSON."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
