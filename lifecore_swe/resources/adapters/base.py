"""Base adapter definitions for offline external resource ingestion.

Enforces the invariant:
    MOCK/OFFLINE SOURCE -> ADAPTER -> RAW RESOURCE -> PROVENANCE -> HASH -> RETRIEVED
    RETRIEVED != VERIFIED
"""

from __future__ import annotations

import abc
import datetime
from dataclasses import dataclass, field
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


@dataclass
class AdapterIngestionResult:
    """Encapsulates the raw ingested artifact, provenance, and initial record."""
    record: ResourceRecord
    provenance: ProvenanceRecord
    raw_content: str
    extraction_metadata: Dict[str, Any] = field(default_factory=dict)
    is_successful: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "provenance": self.provenance.to_dict(),
            "raw_content_length": len(self.raw_content),
            "extraction_metadata": self.extraction_metadata,
            "is_successful": self.is_successful,
            "error_message": self.error_message,
        }


class BaseResourceAdapter(abc.ABC):
    """Abstract base class for deterministic offline resource ingestion adapters."""

    def __init__(
        self,
        adapter_name: str,
        source_type: SourceType,
        default_trust_level: TrustLevel = TrustLevel.LOW,
        default_retrieval_method: RetrievalMethod = RetrievalMethod.OFFLINE_CACHE,
    ) -> None:
        self.adapter_name = adapter_name
        self.source_type = source_type
        self.default_trust_level = default_trust_level
        self.default_retrieval_method = default_retrieval_method

    @abc.abstractmethod
    def ingest(
        self,
        payload: Union[Dict[str, Any], str],
        retrieved_at: Optional[str] = None,
        notes: str = "",
        custom_metadata: Optional[Dict[str, Any]] = None,
    ) -> AdapterIngestionResult:
        """Parse offline payload into a ResourceRecord and ProvenanceRecord.

        Must set verification_status to RETRIEVED. Never to VERIFIED.
        """
        raise NotImplementedError
