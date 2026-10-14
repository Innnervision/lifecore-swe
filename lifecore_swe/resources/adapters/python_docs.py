"""Offline adapter for Python documentation structures.

Parses offline documentation dictionaries into ResourceRecord and ProvenanceRecord.
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


class PythonDocsAdapter(BaseResourceAdapter):
    """Adapter for offline Python standard library and third-party documentation."""

    def __init__(
        self,
        source_name: str = "python-docs",
        default_trust_level: TrustLevel = TrustLevel.MEDIUM,
    ) -> None:
        super().__init__(
            adapter_name="PythonDocsAdapter",
            source_type=SourceType.DOCUMENTATION_SITE,
            default_trust_level=default_trust_level,
            default_retrieval_method=RetrievalMethod.OFFLINE_CACHE,
        )
        self.source_name = source_name

    def ingest(
        self,
        payload: Union[Dict[str, Any], str],
        retrieved_at: Optional[str] = None,
        notes: str = "Ingested from offline Python documentation fixture",
        custom_metadata: Optional[Dict[str, Any]] = None,
    ) -> AdapterIngestionResult:
        """Parse doc payload into ResourceRecord and ProvenanceRecord."""
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except Exception as e:
                # Raw text payload
                data = {
                    "title": "Raw Python Documentation",
                    "content": payload,
                    "module": "unknown",
                }
        elif isinstance(payload, dict):
            data = payload
        else:
            raise TypeError(f"Unsupported payload type: {type(payload)}")

        module_name = data.get("module") or data.get("name") or "generic_python"
        title = data.get("title") or f"Python Documentation: {module_name}"
        description = data.get("description") or data.get("summary") or ""
        url = data.get("url") or f"https://docs.python.org/3/library/{module_name}.html"
        version = data.get("version") or data.get("python_version")
        license_str = data.get("license") or "PSF-2.0"
        published_at = data.get("published_at")
        symbols = data.get("symbols", [])
        is_api_ref = bool(data.get("is_api_reference", False) or (symbols and not data.get("body")))

        # Serialize full text content deterministically for hashing
        content = data.get("content") or data.get("body")
        if content is None:
            # Deterministic serialization of the dictionary representation
            content = json.dumps(data, sort_keys=True, ensure_ascii=False)

        content_hash = compute_content_hash(content)
        ret_time = retrieved_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

        res_type = ResourceType.API_REFERENCE if is_api_ref else ResourceType.DOCUMENTATION

        norm_url = normalize_url(url)
        res_id = generate_deterministic_resource_id(
            resource_type=res_type,
            source=self.source_name,
            url=norm_url,
            package_name=module_name,
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
            "module_name": module_name,
            "symbols_count": len(symbols),
            "symbols": symbols,
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
            title=title,
            description=description,
            package_name=module_name,
            version=version,
            content_hash=content_hash,
            retrieved_at=ret_time,
            published_at=published_at,
            license=license_str,
            provenance_id=prov_id,
            verification_status=ResourceVerificationStatus.RETRIEVED,  # RETRIEVED != VERIFIED
            metadata=metadata,
        )

        return AdapterIngestionResult(
            record=record,
            provenance=provenance,
            raw_content=content,
            extraction_metadata={
                "module_name": module_name,
                "symbols_extracted": len(symbols),
                "is_api_reference": is_api_ref,
            },
            is_successful=True,
        )
