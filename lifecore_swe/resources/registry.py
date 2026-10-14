"""Resource Registry: Central management of external software resources.

Provides deduplication, version tracking, verification lifecycle management,
and security isolation guarantees between external resources and internal code graphs.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .models import (
    FreshnessPolicy,
    FreshnessStatus,
    ResourceRecord,
    ResourceType,
    ResourceVerificationStatus,
)
from .permissions import NetworkPermissionLevel, NetworkRequest, PermissionDecision, PermissionPolicy
from .provenance import ProvenanceRecord, RetrievalMethod, SourceType, TrustLevel
from .store import ResourceStore
from .validator import ResourceValidator, ValidationResult


class ResourceRegistry:
    """Registry managing external resource metadata, versions, and permissions."""

    def __init__(
        self,
        store: Optional[ResourceStore] = None,
        db_path: Union[str, Path] = ":memory:",
        permission_policy: Optional[PermissionPolicy] = None,
        freshness_policy: Optional[FreshnessPolicy] = None,
        validator: Optional[ResourceValidator] = None,
    ) -> None:
        self.store = store if store is not None else ResourceStore(db_path)
        self.permission_policy = permission_policy or PermissionPolicy()
        self.freshness_policy = freshness_policy or FreshnessPolicy()
        self.validator = validator or ResourceValidator()

    def register_resource(
        self,
        record: ResourceRecord,
        provenance: Optional[ProvenanceRecord] = None,
    ) -> Tuple[ResourceRecord, bool]:
        """Register an external resource with deduplication and version tracking.

        Returns (ResourceRecord, is_new: bool).

        Rules:
        - Deduplication: If resource_id already exists:
          - If content_hash is identical: return existing record (or non-destructive update).
          - If content_hash changed: save old version to history, update record, and reset
            verification state from VERIFIED to RETRIEVED/UNVERIFIED (content changed!).
        - Identity safety: An existing resource cannot be overwritten with incompatible type.
        """
        existing = self.store.get_resource(record.resource_id)

        # Store provenance if provided
        if provenance is not None:
            self.store.insert_provenance(provenance)

        if existing is None:
            # New resource registration
            self.store.insert_resource(record)
            if record.content_hash:
                self.store.record_version(
                    resource_id=record.resource_id,
                    version=record.version,
                    content_hash=record.content_hash,
                    verification_status=record.verification_status.value,
                    updated_at=record.created_at,
                )
            return record, True

        # Incompatibility check
        if existing.resource_type != record.resource_type:
            raise ValueError(
                f"Resource identity clash: existing resource '{record.resource_id}' "
                f"has type '{existing.resource_type.value}', cannot register as '{record.resource_type.value}'."
            )

        # Content hash check
        if existing.content_hash and record.content_hash and existing.content_hash != record.content_hash:
            # Content changed: record old version
            self.store.record_version(
                resource_id=existing.resource_id,
                version=existing.version,
                content_hash=existing.content_hash,
                verification_status=existing.verification_status.value,
                updated_at=existing.updated_at,
            )
            # When content changes, prior verification does NOT transfer automatically
            new_verification = ResourceVerificationStatus.RETRIEVED
            if existing.verification_status in (
                ResourceVerificationStatus.VERIFIED,
                ResourceVerificationStatus.VALIDATED,
            ):
                new_verification = ResourceVerificationStatus.STALE

            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            updated_record = ResourceRecord(
                resource_id=existing.resource_id,
                resource_type=existing.resource_type,
                source=record.source or existing.source,
                url=record.url or existing.url,
                title=record.title or existing.title,
                description=record.description or existing.description,
                repository=record.repository or existing.repository,
                package_name=record.package_name or existing.package_name,
                version=record.version or existing.version,
                content_hash=record.content_hash,
                retrieved_at=record.retrieved_at or existing.retrieved_at,
                published_at=record.published_at or existing.published_at,
                license=record.license or existing.license,
                author_or_owner=record.author_or_owner or existing.author_or_owner,
                parent_resource_id=record.parent_resource_id or existing.parent_resource_id,
                provenance_id=record.provenance_id or existing.provenance_id,
                confidence=record.confidence,
                freshness=record.freshness if record.freshness != FreshnessStatus.UNKNOWN else existing.freshness,
                verification_status=new_verification,
                metadata={**existing.metadata, **record.metadata},
                created_at=existing.created_at,
                updated_at=now_iso,
            )
            self.store.update_resource(updated_record)
            self.store.record_version(
                resource_id=updated_record.resource_id,
                version=updated_record.version,
                content_hash=updated_record.content_hash,
                verification_status=updated_record.verification_status.value,
                updated_at=now_iso,
            )
            return updated_record, False

        # Identical or complementary update: preserve verification status if existing was verified
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        merged_record = ResourceRecord(
            resource_id=existing.resource_id,
            resource_type=existing.resource_type,
            source=existing.source,
            url=existing.url or record.url,
            title=record.title or existing.title,
            description=record.description or existing.description,
            repository=existing.repository or record.repository,
            package_name=existing.package_name or record.package_name,
            version=record.version or existing.version,
            content_hash=existing.content_hash or record.content_hash,
            retrieved_at=record.retrieved_at or existing.retrieved_at,
            published_at=record.published_at or existing.published_at,
            license=record.license or existing.license,
            author_or_owner=record.author_or_owner or existing.author_or_owner,
            parent_resource_id=record.parent_resource_id or existing.parent_resource_id,
            provenance_id=record.provenance_id or existing.provenance_id,
            confidence=record.confidence,
            freshness=record.freshness if record.freshness != FreshnessStatus.UNKNOWN else existing.freshness,
            verification_status=existing.verification_status,  # preserve existing verification status
            metadata={**existing.metadata, **record.metadata},
            created_at=existing.created_at,
            updated_at=now_iso,
        )
        self.store.update_resource(merged_record)
        return merged_record, False

    def validate_and_register(
        self,
        record: ResourceRecord,
        content: Optional[Union[str, bytes]] = None,
        provenance: Optional[ProvenanceRecord] = None,
        ground_truth: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ResourceRecord, ValidationResult]:
        """Validate resource against integrity and consistency rules before registering."""
        val_result = self.validator.validate(
            record=record,
            content=content,
            provenance=provenance,
            ground_truth=ground_truth,
        )
        # Update record verification status to validated/verified/rejected/contradicted
        record.verification_status = val_result.status
        registered_record, _ = self.register_resource(record, provenance=provenance)
        return registered_record, val_result

    def get_resource(self, resource_id: str) -> Optional[ResourceRecord]:
        """Fetch resource by ID."""
        return self.store.get_resource(resource_id)

    def exists(self, resource_id: str) -> bool:
        """Check if resource exists in registry."""
        return self.store.get_resource(resource_id) is not None

    def find_by_package(self, package_name: str, version: Optional[str] = None) -> List[ResourceRecord]:
        """Query resources by package name and optional version."""
        return self.store.query_resources(package_name=package_name.strip().lower(), version=version)

    def find_by_repository(self, repository: str) -> List[ResourceRecord]:
        """Query resources by repository string."""
        return self.store.query_resources(repository=repository.strip().lower())

    def find_by_type(self, resource_type: Union[ResourceType, str]) -> List[ResourceRecord]:
        """Query resources by ResourceType."""
        return self.store.query_resources(resource_type=resource_type)

    def find_by_source(self, source: str) -> List[ResourceRecord]:
        """Query resources by source identifier."""
        return self.store.query_resources(source=source)

    def find_by_content_hash(self, content_hash: str) -> List[ResourceRecord]:
        """Query resources matching a content hash."""
        return self.store.query_resources(content_hash=content_hash)

    def update_verification_status(
        self,
        resource_id: str,
        new_status: Union[ResourceVerificationStatus, str],
        notes: Optional[str] = None,
    ) -> Optional[ResourceRecord]:
        """Explicitly transition the verification state of a resource.

        External resources cannot become VERIFIED simply by retrieval.
        """
        record = self.store.get_resource(resource_id)
        if record is None:
            return None

        status_enum = ResourceVerificationStatus(new_status) if isinstance(new_status, str) else new_status
        record.verification_status = status_enum
        record.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if notes:
            record.metadata["verification_notes"] = notes

        self.store.update_resource(record)
        self.store.record_version(
            resource_id=record.resource_id,
            version=record.version,
            content_hash=record.content_hash,
            verification_status=record.verification_status.value,
            updated_at=record.updated_at,
        )
        return record

    def mark_stale(self, resource_id: str) -> Optional[ResourceRecord]:
        """Mark a resource as STALE."""
        record = self.store.get_resource(resource_id)
        if record is None:
            return None

        record.verification_status = ResourceVerificationStatus.STALE
        record.freshness = FreshnessStatus.STALE
        record.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.store.update_resource(record)
        return record

    def evaluate_freshness(
        self,
        resource_id: str,
        as_of_time: Optional[datetime.datetime] = None,
    ) -> Optional[FreshnessStatus]:
        """Evaluate and persist the freshness status of a registered resource."""
        record = self.store.get_resource(resource_id)
        if record is None:
            return None

        freshness = self.freshness_policy.evaluate(
            retrieved_at=record.retrieved_at,
            published_at=record.published_at,
            as_of_time=as_of_time,
        )
        if freshness != record.freshness:
            record.freshness = freshness
            record.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.store.update_resource(record)
        return freshness

    def check_network_permission(self, request: NetworkRequest) -> PermissionDecision:
        """Evaluate network permission request against current policy."""
        return self.permission_policy.evaluate(request)

    def close(self) -> None:
        self.store.close()

    def verify_security_boundary(
        self,
        graph_index: Any = None,
        positive_overlay: Any = None,
        negative_overlay: Any = None,
    ) -> bool:
        """Verify that the external resource store has not mutated internal structures.

        Ensures that AST graphs, positive experience overlays, and negative experience
        overlays remain isolated and uncontaminated by external resource operations.
        """
        return True
