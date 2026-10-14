"""Offline adapters for external software resource ingestion (M5-B)."""

from .base import AdapterIngestionResult, BaseResourceAdapter
from .python_docs import PythonDocsAdapter
from .package_metadata import PackageMetadataAdapter
from .mock_sources import (
    MOCK_API_REFERENCE_PARSE,
    MOCK_CODE_EXAMPLE_SYNTAX_ERROR,
    MOCK_CODE_EXAMPLE_VALID,
    MOCK_CONTRADICTORY_VERSION,
    MOCK_FORBIDDEN_LICENSE,
    MOCK_PACKAGE_REQUESTS,
    MOCK_PYTHON_DOCS_AST,
    MOCK_REPOSITORY_METADATA,
    MOCK_TAMPERED_HASH_PAYLOAD,
    MockResourceAdapter,
)

__all__ = [
    "BaseResourceAdapter",
    "AdapterIngestionResult",
    "PythonDocsAdapter",
    "PackageMetadataAdapter",
    "MockResourceAdapter",
    "MOCK_PYTHON_DOCS_AST",
    "MOCK_PACKAGE_REQUESTS",
    "MOCK_API_REFERENCE_PARSE",
    "MOCK_CODE_EXAMPLE_VALID",
    "MOCK_CODE_EXAMPLE_SYNTAX_ERROR",
    "MOCK_REPOSITORY_METADATA",
    "MOCK_CONTRADICTORY_VERSION",
    "MOCK_FORBIDDEN_LICENSE",
    "MOCK_TAMPERED_HASH_PAYLOAD",
]
