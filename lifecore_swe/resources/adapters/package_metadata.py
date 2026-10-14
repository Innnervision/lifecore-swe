"""Offline adapter for software package metadata.

Parses offline package metadata representations into ResourceRecord and ProvenanceRecord.
Adheres strictly to the invariant: RETRIEVED != VERIFIED.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, Optional, Union

from ..models import (
    ResourceRecord,
    ResourceType,
    ResourceVerificationStatus,
    compute_content_hash,
    generate_deterministic_resource_id,
    normalize_url,
)
from ..provenance import (
    ProvenanceRecord,
    RetrievalMethod,
    SourceType,
    TrustLevel,
    generate_provenance_id,
)
from .base import AdapterIngestionResult, BaseResourceAdapter


class PackageMetadataAdapter(BaseResourceAdapter):
    """Adapter for offline package registry metadata (e.g., PyPI or npm metadata schemas)."""

    def __init__(
        self,
        source_name: str = "pypi",
        default_trust_level: TrustLevel = TrustLevel.MEDIUM,
    ) -> None:
        super().__init__(
            adapter_name="PackageMetadataAdapter",
            source_type=SourceType.PACKAGE_REGISTRY,
            default_trust_level=default_trust_level,
            default_retrieval_method=RetrievalMethod.OFFLINE_CACHE,
        )
        self.source_name = source_name

    def ingest(
        self,
        payload: Union[Dict[str, Any], str],
        retrieved_at: Optional[str] = None,
        notes: str = "Ingested from offline package metadata fixture",
        custom_metadata: Optional[Dict[str, Any]] = None,
    ) -> AdapterIngestionResult:
        """Parse package metadata payload into ResourceRecord and ProvenanceRecord."""
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except Exception:
                data = {"name": "unknown_package", "description": payload}
        elif isinstance(payload, dict):
            data = payload
        else:
            raise TypeError(f"Unsupported payload type: {type(payload)}")

        # Support PyPI-style nested dictionary {"info": {...}} or flat dictionary
        info = data.get("info", data)

        pkg_name = (info.get("name") or info.get("package_name") or "unknown_package").strip().lower()
        version = info.get("version") or data.get("version")
        summary = info.get("summary") or info.get("description") or ""
        license_str = info.get("license") or info.get("license_expression")
        author = info.get("author") or info.get("author_email")
        home_page = info.get("home_page") or info.get("project_url") or f"https://pypi.org/project/{pkg_name}/"
        requires_dist = info.get("requires_dist") or info.get("dependencies") or []
        published_at = info.get("published_at") or data.get("upload_time")

        # Deterministic serialization for hashing
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
        content_hash = compute_content_hash(content)
        ret_time = retrieved_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

        norm_url = normalize_url(home_page)
        res_type = ResourceType.PACKAGE_VERSION if version else ResourceType.PACKAGE

        res_id = generate_deterministic_resource_id(
            resource_type=res_type,
            source=self.source_name,
            url=norm_url,
            package_name=pkg_name,
            version=version,
        )

        prov_id = generate_provenance_id(
            source_type=self.source_type,
            source_name=self.source_name,
            source_url=norm_url,
            content_hash=content_hash,
            declared_version=version,
        )

        metadata = {
            "dependencies": requires_dist,
            "dependency_count": len(requires_dist),
            "classifiers": info.get("classifiers", []),
            **(custom_metadata or {}),
        }

        provenance = ProvenanceRecord(
            provenance_id=prov_id,
            source_type=self.source_type,
            source_name=self.source_name,
            source_url=norm_url,
            retrieved_at=ret_time,
            retrieval_method=self.default_retrieval_method,
            content_hash=content_hash,
            declared_version=version,
            observed_version=version,
            license=license_str,
            trust_level=self.default_trust_level,
            notes=notes,
            metadata={"adapter": self.adapter_name},
        )

        record = ResourceRecord.create(
            custom_id=res_id,
            resource_type=res_type,
            source=self.source_name,
            url=norm_url,
            title=f"Package: {pkg_name} ({version})" if version else f"Package: {pkg_name}",
            description=summary,
            package_name=pkg_name,
            version=version,
            content_hash=content_hash,
            retrieved_at=ret_time,
            published_at=published_at,
            license=license_str,
            author_or_owner=author,
            provenance_id=prov_id,
            verification_status=ResourceVerificationStatus.RETRIEVED,  # RETRIEVED != VERIFIED
            metadata=metadata,
        )

        return AdapterIngestionResult(
            record=record,
            provenance=provenance,
            raw_content=content,
            extraction_metadata={
                "package_name": pkg_name,
                "version": version,
                "dependency_count": len(requires_dist),
            },
            is_successful=True,
        )
