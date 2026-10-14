"""Data models for external software resources in LIFECORE-SWE.

M5-A Resource Intelligence Foundation.
External resources are provenance-aware, version-aware, persistent entities
isolated from the internal verified code graph.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import urllib.parse
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Union


class ResourceType(str, Enum):
    """Categorization of external software resources."""
    DOCUMENTATION = "DOCUMENTATION"
    PACKAGE = "PACKAGE"
    PACKAGE_VERSION = "PACKAGE_VERSION"
    REPOSITORY = "REPOSITORY"
    API_REFERENCE = "API_REFERENCE"
    CODE_EXAMPLE = "CODE_EXAMPLE"
    ISSUE = "ISSUE"
    COMMIT = "COMMIT"
    PULL_REQUEST = "PULL_REQUEST"
    PAPER = "PAPER"
    BENCHMARK = "BENCHMARK"
    WEB_RESOURCE = "WEB_RESOURCE"
    OTHER = "OTHER"


class ResourceVerificationStatus(str, Enum):
    """Verification lifecycle of an external resource.

    Rule: RETRIEVED != VERIFIED.
    A resource is never trusted simply because it was retrieved.
    """
    UNVERIFIED = "UNVERIFIED"
    RETRIEVED = "RETRIEVED"
    VALIDATED = "VALIDATED"
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    CONTRADICTED = "CONTRADICTED"
    REJECTED = "REJECTED"


class FreshnessStatus(str, Enum):
    """Freshness state of an external resource."""
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


def normalize_url(url: Optional[str]) -> str:
    """Deterministically normalize a URL for stable resource identification.

    - Lowercases scheme and host
    - Strips default ports (:80, :443)
    - Strips trailing slash on path
    - Sorts query parameters deterministically
    - Strips fragment identifiers
    """
    if not url:
        return ""

    parsed = urllib.parse.urlsplit(url.strip())
    if not parsed.scheme and not parsed.netloc:
        # Bare string or relative path
        return url.strip().rstrip("/")

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Strip default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = parsed.path.rstrip("/")
    if not path and (scheme or netloc):
        path = ""

    # Sort query parameters
    query_parts = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query_parts.sort(key=lambda x: (x[0], x[1]))
    normalized_query = urllib.parse.urlencode(query_parts) if query_parts else ""

    # Reconstruct without fragment
    normalized = urllib.parse.urlunsplit((scheme, netloc, path, normalized_query, ""))
    return normalized


def compute_content_hash(content: Union[str, bytes]) -> str:
    """Compute deterministic SHA-256 hash of text or binary content."""
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        content_bytes = content
    return hashlib.sha256(content_bytes).hexdigest()


def generate_deterministic_resource_id(
    resource_type: Union[ResourceType, str],
    source: str,
    url: Optional[str] = None,
    package_name: Optional[str] = None,
    repository: Optional[str] = None,
    version: Optional[str] = None,
) -> str:
    """Generate deterministic SHA-256 resource ID from canonical identity components."""
    type_str = resource_type.value if isinstance(resource_type, ResourceType) else str(resource_type)
    norm_url = normalize_url(url)
    norm_source = (source or "").strip().lower()
    norm_pkg = (package_name or "").strip().lower()
    norm_repo = (repository or "").strip().lower()
    norm_ver = (version or "").strip()

    identity_components = [
        type_str,
        norm_source,
        norm_url,
        norm_pkg,
        norm_repo,
        norm_ver,
    ]
    canonical_key = "|".join(identity_components)
    digest = hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()
    return f"res_{digest[:16]}"


@dataclass
class FreshnessPolicy:
    """Configurable evaluation policy for resource freshness."""
    fresh_threshold_days: float = 30.0
    aging_threshold_days: float = 180.0

    def evaluate(
        self,
        retrieved_at: Optional[Union[str, datetime.datetime]] = None,
        published_at: Optional[Union[str, datetime.datetime]] = None,
        as_of_time: Optional[datetime.datetime] = None,
    ) -> FreshnessStatus:
        """Determine freshness state relative to reference time.

        Uses published_at if available; falls back to retrieved_at.
        If neither is provided or parse fails, returns UNKNOWN.
        """
        ref_timestamp = published_at or retrieved_at
        if not ref_timestamp:
            return FreshnessStatus.UNKNOWN

        dt: Optional[datetime.datetime] = None
        if isinstance(ref_timestamp, datetime.datetime):
            dt = ref_timestamp
        elif isinstance(ref_timestamp, str):
            try:
                # Handle ISO string with or without Z
                ts_str = ref_timestamp.replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(ts_str)
            except Exception:
                return FreshnessStatus.UNKNOWN

        if dt is None:
            return FreshnessStatus.UNKNOWN

        now = as_of_time if as_of_time is not None else datetime.datetime.now(datetime.timezone.utc)
        # If dt is naive, assume UTC or match now
        if dt.tzinfo is None and now.tzinfo is not None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        elif dt.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)

        age_seconds = (now - dt).total_seconds()
        if age_seconds < 0:
            # Future timestamp
            return FreshnessStatus.FRESH

        age_days = age_seconds / 86400.0
        if age_days <= self.fresh_threshold_days:
            return FreshnessStatus.FRESH
        elif age_days <= self.aging_threshold_days:
            return FreshnessStatus.AGING
        else:
            return FreshnessStatus.STALE


@dataclass
class ResourceRecord:
    """Persistent, provenance-aware representation of an external software resource."""
    resource_id: str
    resource_type: ResourceType
    source: str
    url: Optional[str] = None
    title: str = ""
    description: str = ""
    repository: Optional[str] = None
    package_name: Optional[str] = None
    version: Optional[str] = None
    content_hash: str = ""
    retrieved_at: Optional[str] = None
    published_at: Optional[str] = None
    license: Optional[str] = None
    author_or_owner: Optional[str] = None
    parent_resource_id: Optional[str] = None
    provenance_id: Optional[str] = None
    confidence: float = 1.0
    freshness: FreshnessStatus = FreshnessStatus.UNKNOWN
    verification_status: ResourceVerificationStatus = ResourceVerificationStatus.UNVERIFIED
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.resource_type, str):
            self.resource_type = ResourceType(self.resource_type)
        if isinstance(self.verification_status, str):
            self.verification_status = ResourceVerificationStatus(self.verification_status)
        if isinstance(self.freshness, str):
            self.freshness = FreshnessStatus(self.freshness)

        # Normalize URL if present
        if self.url:
            self.url = normalize_url(self.url)

        # Ensure timestamps
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now_iso
        if not self.updated_at:
            self.updated_at = self.created_at

    @classmethod
    def create(
        cls,
        resource_type: Union[ResourceType, str],
        source: str,
        url: Optional[str] = None,
        title: str = "",
        description: str = "",
        repository: Optional[str] = None,
        package_name: Optional[str] = None,
        version: Optional[str] = None,
        content: Optional[Union[str, bytes]] = None,
        content_hash: Optional[str] = None,
        retrieved_at: Optional[str] = None,
        published_at: Optional[str] = None,
        license: Optional[str] = None,
        author_or_owner: Optional[str] = None,
        parent_resource_id: Optional[str] = None,
        provenance_id: Optional[str] = None,
        confidence: float = 1.0,
        freshness: Optional[FreshnessStatus] = None,
        verification_status: ResourceVerificationStatus = ResourceVerificationStatus.UNVERIFIED,
        metadata: Optional[Dict[str, Any]] = None,
        custom_id: Optional[str] = None,
    ) -> ResourceRecord:
        """Factory method computing deterministic resource_id and content_hash."""
        r_type = ResourceType(resource_type) if isinstance(resource_type, str) else resource_type
        norm_url = normalize_url(url) if url else None

        c_hash = content_hash or ""
        if content is not None:
            c_hash = compute_content_hash(content)

        r_id = custom_id or generate_deterministic_resource_id(
            resource_type=r_type,
            source=source,
            url=norm_url,
            package_name=package_name,
            repository=repository,
            version=version,
        )

        f_status = freshness or FreshnessStatus.UNKNOWN

        return cls(
            resource_id=r_id,
            resource_type=r_type,
            source=source,
            url=norm_url,
            title=title,
            description=description,
            repository=repository,
            package_name=package_name,
            version=version,
            content_hash=c_hash,
            retrieved_at=retrieved_at,
            published_at=published_at,
            license=license,
            author_or_owner=author_or_owner,
            parent_resource_id=parent_resource_id,
            provenance_id=provenance_id,
            confidence=confidence,
            freshness=f_status,
            verification_status=verification_status,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to JSON-serializable dictionary."""
        d = asdict(self)
        d["resource_type"] = self.resource_type.value
        d["verification_status"] = self.verification_status.value
        d["freshness"] = self.freshness.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourceRecord:
        """Reconstruct record from dictionary."""
        d = dict(data)
        d["resource_type"] = ResourceType(d["resource_type"])
        d["verification_status"] = ResourceVerificationStatus(d.get("verification_status", ResourceVerificationStatus.UNVERIFIED.value))
        d["freshness"] = FreshnessStatus(d.get("freshness", FreshnessStatus.UNKNOWN.value))
        return cls(**d)

    def to_canonical_json(self) -> str:
        """Return deterministic JSON representation sorted by keys."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
