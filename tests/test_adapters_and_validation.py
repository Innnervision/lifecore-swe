"""Unit tests for M5-B: Offline Resource Ingestion & Validation Pipeline.

Validates adapters, mock sources, schema validation, content hashing,
syntax validation, license verification, and contradiction detection.
"""

from __future__ import annotations

import json
import pytest

from lifecore_swe.resources.adapters import (
    AdapterIngestionResult,
    BaseResourceAdapter,
    MockResourceAdapter,
    PackageMetadataAdapter,
    PythonDocsAdapter,
    MOCK_API_REFERENCE_PARSE,
    MOCK_CODE_EXAMPLE_SYNTAX_ERROR,
    MOCK_CODE_EXAMPLE_VALID,
    MOCK_CONTRADICTORY_VERSION,
    MOCK_FORBIDDEN_LICENSE,
    MOCK_PACKAGE_REQUESTS,
    MOCK_PYTHON_DOCS_AST,
    MOCK_REPOSITORY_METADATA,
    MOCK_TAMPERED_HASH_PAYLOAD,
)
from lifecore_swe.resources.models import (
    ResourceRecord,
    ResourceType,
    ResourceVerificationStatus,
    compute_content_hash,
)
from lifecore_swe.resources.provenance import (
    ProvenanceRecord,
    RetrievalMethod,
    SourceType,
    TrustLevel,
)
from lifecore_swe.resources.registry import ResourceRegistry
from lifecore_swe.resources.validator import ResourceValidator, ValidationResult


@pytest.fixture
def validator():
    """Create a default ResourceValidator instance."""
    return ResourceValidator()


@pytest.fixture
def temp_registry():
    """Create an isolated in-memory registry."""
    reg = ResourceRegistry(db_path=":memory:")
    yield reg
    reg.close()


# 1. Base adapter contract
def test_base_adapter_contract():
    class DummyAdapter(BaseResourceAdapter):
        def ingest(self, payload, **kwargs):
            return super().ingest(payload, **kwargs)

    dummy = DummyAdapter(
        adapter_name="dummy",
        source_type=SourceType.OTHER,
    )
    with pytest.raises(NotImplementedError):
        dummy.ingest({"some": "data"})


# 2. Python docs adapter
def test_python_docs_adapter():
    adapter = PythonDocsAdapter()
    result = adapter.ingest(MOCK_PYTHON_DOCS_AST)

    assert result.is_successful is True
    assert result.record.resource_type == ResourceType.DOCUMENTATION
    assert result.record.package_name == "ast"
    assert result.record.version == "3.12.0"
    assert result.record.license == "PSF-2.0"
    assert result.record.verification_status == ResourceVerificationStatus.RETRIEVED
    assert result.provenance.source_type == SourceType.DOCUMENTATION_SITE
    assert result.provenance.retrieval_method == RetrievalMethod.OFFLINE_CACHE
    assert result.extraction_metadata["symbols_extracted"] == 3


# 3. Package metadata adapter
def test_package_metadata_adapter():
    adapter = PackageMetadataAdapter()
    result = adapter.ingest(MOCK_PACKAGE_REQUESTS)

    assert result.is_successful is True
    assert result.record.resource_type == ResourceType.PACKAGE_VERSION
    assert result.record.package_name == "requests"
    assert result.record.version == "2.31.0"
    assert result.record.author_or_owner == "Kenneth Reitz"
    assert result.record.license == "Apache-2.0"
    assert result.record.verification_status == ResourceVerificationStatus.RETRIEVED
    assert result.provenance.source_type == SourceType.PACKAGE_REGISTRY
    assert len(result.record.metadata["dependencies"]) == 4


# 4. Mock sources adapter for API reference
def test_mock_adapter_api_reference():
    adapter = MockResourceAdapter(source_name="ast-docs", source_type=SourceType.DOCUMENTATION_SITE)
    result = adapter.ingest(MOCK_API_REFERENCE_PARSE)

    assert result.is_successful is True
    assert result.record.resource_type == ResourceType.API_REFERENCE
    assert result.record.package_name == "ast"
    assert result.record.verification_status == ResourceVerificationStatus.RETRIEVED


# 5. Mock sources adapter for code example
def test_mock_adapter_code_example():
    adapter = MockResourceAdapter(source_name="cookbook", source_type=SourceType.COMMUNITY_FORUM)
    result = adapter.ingest(MOCK_CODE_EXAMPLE_VALID)

    assert result.is_successful is True
    assert result.record.resource_type == ResourceType.CODE_EXAMPLE
    assert result.record.verification_status == ResourceVerificationStatus.RETRIEVED
    assert "import ast" in result.raw_content


# 6. Invariant: RETRIEVED != VERIFIED
def test_retrieved_not_equal_verified():
    adapter = PythonDocsAdapter()
    result = adapter.ingest(MOCK_PYTHON_DOCS_AST)

    # Must be RETRIEVED, never VERIFIED upon ingestion
    assert result.record.verification_status == ResourceVerificationStatus.RETRIEVED
    assert result.record.verification_status != ResourceVerificationStatus.VERIFIED


# 7. Schema correctness validation
def test_schema_validation(validator):
    # Valid record
    rec_valid = ResourceRecord.create(
        resource_type=ResourceType.DOCUMENTATION,
        source="python-docs",
        content="some doc content",
        license="PSF-2.0",
    )
    val_result = validator.validate(rec_valid, content="some doc content")
    assert val_result.is_valid is True
    assert val_result.status == ResourceVerificationStatus.VALIDATED

    # Invalid record (corrupted resource_id and hash)
    rec_invalid = ResourceRecord(
        resource_id="bad_id_without_prefix",
        resource_type=ResourceType.DOCUMENTATION,
        source="python-docs",
        content_hash="too_short_hash",
        license="MIT",
    )
    val_result_bad = validator.validate(rec_invalid)
    assert val_result_bad.is_valid is False
    assert val_result_bad.status == ResourceVerificationStatus.REJECTED
    assert any("resource_id format" in v for v in val_result_bad.violations)
    assert any("content_hash" in v for v in val_result_bad.violations)


# 8. Content hash integrity validation
def test_content_hash_integrity(validator):
    adapter = MockResourceAdapter()
    ingestion = adapter.ingest(MOCK_CODE_EXAMPLE_VALID)

    # Valid content matching record's hash
    val_ok = validator.validate(
        record=ingestion.record,
        content=ingestion.raw_content,
        provenance=ingestion.provenance,
    )
    assert val_ok.is_valid is True
    assert val_ok.status == ResourceVerificationStatus.VALIDATED

    # Tampered content should be caught and rejected
    val_tampered = validator.validate(
        record=ingestion.record,
        content="MALICIOUS TAMPERED CODE SNIPPET",
        provenance=ingestion.provenance,
    )
    assert val_tampered.is_valid is False
    assert val_tampered.status == ResourceVerificationStatus.REJECTED
    assert any("Content hash mismatch" in v for v in val_tampered.violations)


# 9. Version consistency validation
def test_version_consistency(validator):
    adapter = MockResourceAdapter()
    ingestion = adapter.ingest(MOCK_CONTRADICTORY_VERSION)

    # The mock has declared_version 3.12.0 and observed_version 2.7.0
    val_result = validator.validate(
        record=ingestion.record,
        content=ingestion.raw_content,
        provenance=ingestion.provenance,
    )
    assert val_result.is_valid is False
    assert val_result.status == ResourceVerificationStatus.CONTRADICTED
    assert any("Version contradiction" in v for v in val_result.violations)


# 10. Source identity validation
def test_source_identity_validation(validator):
    adapter = PythonDocsAdapter(source_name="python-docs")
    ingestion = adapter.ingest(MOCK_PYTHON_DOCS_AST)

    # Forged provenance with mismatched source_name
    forged_prov = ProvenanceRecord(
        provenance_id="prov_forged_1",
        source_type=SourceType.COMMUNITY_FORUM,
        source_name="untrusted-forum",
        content_hash=ingestion.record.content_hash,
    )
    val_result = validator.validate(
        record=ingestion.record,
        content=ingestion.raw_content,
        provenance=forged_prov,
    )
    assert val_result.is_valid is False
    assert val_result.status == ResourceVerificationStatus.REJECTED
    assert any("Source identity mismatch" in v for v in val_result.violations)


# 11. License metadata compliance
def test_license_compliance(validator):
    adapter = MockResourceAdapter()

    # Disallowed / toxic license
    toxic_ingest = adapter.ingest(MOCK_FORBIDDEN_LICENSE)
    val_toxic = validator.validate(toxic_ingest.record, content=toxic_ingest.raw_content)
    assert val_toxic.is_valid is False
    assert val_toxic.status == ResourceVerificationStatus.REJECTED
    assert any("Forbidden or hazardous license" in v for v in val_toxic.violations)

    # Missing license when required
    unlicensed_rec = ResourceRecord.create(
        resource_type=ResourceType.DOCUMENTATION,
        source="internal",
        content="unlicensed doc",
        license=None,
    )
    val_unlicensed = validator.validate(unlicensed_rec, content="unlicensed doc")
    assert val_unlicensed.is_valid is False
    assert any("License metadata is missing" in v for v in val_unlicensed.violations)


# 12. Syntax validation for Python code examples
def test_syntax_validation(validator):
    adapter = MockResourceAdapter()

    # Valid syntax passes
    valid_ingest = adapter.ingest(MOCK_CODE_EXAMPLE_VALID)
    val_valid = validator.validate(valid_ingest.record, content=valid_ingest.raw_content)
    assert val_valid.is_valid is True
    assert val_valid.status == ResourceVerificationStatus.VALIDATED

    # Syntax error fails and is rejected
    broken_ingest = adapter.ingest(MOCK_CODE_EXAMPLE_SYNTAX_ERROR)
    val_broken = validator.validate(broken_ingest.record, content=broken_ingest.raw_content)
    assert val_broken.is_valid is False
    assert val_broken.status == ResourceVerificationStatus.REJECTED
    assert any("Syntax validation error" in v for v in val_broken.violations)


# 13. Ground truth contradiction check
def test_ground_truth_contradiction(validator):
    adapter = PackageMetadataAdapter()
    ingest = adapter.ingest(MOCK_PACKAGE_REQUESTS)

    # Ground truth asserts version should be 3.0.0, but package is 2.31.0
    ground_truth_contradictory = {
        "package_version": "3.0.0",
    }
    val_res = validator.validate(
        record=ingest.record,
        content=ingest.raw_content,
        ground_truth=ground_truth_contradictory,
    )
    assert val_res.is_valid is False
    assert val_res.status == ResourceVerificationStatus.CONTRADICTED
    assert any("Ground truth contradiction" in v for v in val_res.violations)


# 14. Elevation to VERIFIED with verified ground truth
def test_ground_truth_elevation_to_verified(validator):
    adapter = PythonDocsAdapter()
    ingest = adapter.ingest(MOCK_PYTHON_DOCS_AST)

    ground_truth_confirmed = {
        "package_version": "3.12.0",
        "verified_by_repository": True,
    }
    val_res = validator.validate(
        record=ingest.record,
        content=ingest.raw_content,
        provenance=ingest.provenance,
        ground_truth=ground_truth_confirmed,
    )
    assert val_res.is_valid is True
    assert val_res.status == ResourceVerificationStatus.VERIFIED


# 15. Registry validate_and_register integration
def test_registry_validate_and_register(temp_registry):
    adapter = PythonDocsAdapter()
    ingestion = adapter.ingest(MOCK_PYTHON_DOCS_AST)

    # Initial status is RETRIEVED
    assert ingestion.record.verification_status == ResourceVerificationStatus.RETRIEVED

    registered_rec, val_result = temp_registry.validate_and_register(
        record=ingestion.record,
        content=ingestion.raw_content,
        provenance=ingestion.provenance,
    )
    assert val_result.is_valid is True
    assert val_result.status == ResourceVerificationStatus.VALIDATED
    assert registered_rec.verification_status == ResourceVerificationStatus.VALIDATED

    # Verify persistence in SQLite store
    stored = temp_registry.get_resource(registered_rec.resource_id)
    assert stored is not None
    assert stored.verification_status == ResourceVerificationStatus.VALIDATED
    assert stored.package_name == "ast"
