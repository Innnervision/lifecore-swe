"""Deterministic mock sources and test fixtures for offline resource ingestion.

Provides realistic representations of:
- Official documentation
- Package metadata
- API references
- Code examples (valid and syntactically invalid)
- Repository metadata
- Adversarial / corrupted / contradictory payloads for validation testing
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional, Union

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


# 1. Official Documentation Mock
MOCK_PYTHON_DOCS_AST: Dict[str, Any] = {
    "module": "ast",
    "title": "ast — Abstract Syntax Trees",
    "version": "3.12.0",
    "license": "PSF-2.0",
    "url": "https://docs.python.org/3/library/ast.html",
    "summary": "The ast module helps Python applications to process trees of the Python abstract syntax grammar.",
    "published_at": "2023-10-02T00:00:00Z",
    "body": (
        "The ast module helps Python applications to process trees of the Python abstract syntax grammar. "
        "The abstract syntax itself might change with each Python release; this module helps to find out "
        "programmatically what the current grammar looks like."
    ),
    "symbols": [
        {"name": "parse", "kind": "function", "signature": "parse(source, filename='<unknown>', mode='exec')"},
        {"name": "dump", "kind": "function", "signature": "dump(node, annotate_fields=True, include_attributes=False)"},
        {"name": "NodeVisitor", "kind": "class", "signature": "class NodeVisitor()"},
    ],
}

# 2. Package Metadata Mock
MOCK_PACKAGE_REQUESTS: Dict[str, Any] = {
    "info": {
        "name": "requests",
        "version": "2.31.0",
        "summary": "Python HTTP for Humans.",
        "license": "Apache-2.0",
        "author": "Kenneth Reitz",
        "home_page": "https://requests.readthedocs.io",
        "project_url": "https://pypi.org/project/requests/",
        "requires_dist": [
            "charset-normalizer<4,>=2",
            "idna<4,>=2.5",
            "urllib3<3,>=1.21.1",
            "certifi>=2017.4.17",
        ],
        "classifiers": [
            "Development Status :: 5 - Production/Stable",
            "Intended Audience :: Developers",
            "License :: OSI Approved :: Apache Software License",
            "Programming Language :: Python :: 3",
        ],
        "published_at": "2023-05-22T00:00:00Z",
    }
}

# 3. API Reference Mock
MOCK_API_REFERENCE_PARSE: Dict[str, Any] = {
    "module": "ast",
    "symbol": "ast.parse",
    "title": "ast.parse API Reference",
    "version": "3.12.0",
    "license": "PSF-2.0",
    "url": "https://docs.python.org/3/library/ast.html#ast.parse",
    "is_api_reference": True,
    "summary": "Parse the source into an AST node.",
    "signature": "ast.parse(source, filename='<unknown>', mode='exec', *, type_comments=False, feature_version=None)",
    "parameters": [
        {"name": "source", "type": "str | bytes", "description": "Python source code"},
        {"name": "filename", "type": "str", "default": "'<unknown>'"},
        {"name": "mode", "type": "str", "default": "'exec'"},
    ],
    "returns": {"type": "ast.AST", "description": "The root AST node"},
}

# 4. Code Examples Mock (Valid and Invalid)
MOCK_CODE_EXAMPLE_VALID: Dict[str, Any] = {
    "title": "AST Node Visitor Example",
    "language": "python",
    "version": "3.12.0",
    "license": "MIT",
    "source_name": "python-cookbook",
    "url": "https://cookbook.example.org/ast_visitor",
    "code": (
        "import ast\n"
        "\n"
        "class FunctionCallCounter(ast.NodeVisitor):\n"
        "    def __init__(self):\n"
        "        self.count = 0\n"
        "    def visit_Call(self, node):\n"
        "        self.count += 1\n"
        "        self.generic_visit(node)\n"
    ),
    "description": "Demonstrates counting function calls using an ast.NodeVisitor.",
}

MOCK_CODE_EXAMPLE_SYNTAX_ERROR: Dict[str, Any] = {
    "title": "Broken Python Example",
    "language": "python",
    "version": "3.12.0",
    "license": "MIT",
    "source_name": "broken-cookbook",
    "url": "https://cookbook.example.org/broken",
    "code": (
        "def broken_function(\n"
        "    print('unterminated parenthesis'\n"
    ),
    "description": "Example containing intentional syntax errors for negative validation testing.",
}

# 5. Repository Metadata Mock
MOCK_REPOSITORY_METADATA: Dict[str, Any] = {
    "repository": "psf/requests",
    "title": "Requests Repository",
    "source_name": "github",
    "url": "https://github.com/psf/requests",
    "license": "Apache-2.0",
    "default_branch": "main",
    "stars": 50000,
    "open_issues": 120,
    "description": "A simple, yet elegant, HTTP library.",
    "version": "2.31.0",
}

# 6. Adversarial & Contradictory Payloads for Validation Testing
MOCK_CONTRADICTORY_VERSION: Dict[str, Any] = {
    "module": "ast",
    "title": "ast — Abstract Syntax Trees (Contradictory)",
    "declared_version": "3.12.0",
    "observed_version": "2.7.0",  # Deliberate contradiction
    "license": "PSF-2.0",
    "url": "https://docs.python.org/3/library/ast.html",
    "summary": "Contradictory version payload for validation testing.",
    "content": "ast docs for 3.12 claiming to be 2.7",
}

MOCK_FORBIDDEN_LICENSE: Dict[str, Any] = {
    "name": "toxic_dependency",
    "version": "1.0.0",
    "license": "PROPRIETARY_UNLICENSED_MALWARE",
    "summary": "Payload with non-permissive or disallowed license.",
    "url": "https://example.org/unlicensed",
}

MOCK_TAMPERED_HASH_PAYLOAD: Dict[str, Any] = {
    "title": "Tampered Content",
    "module": "security_test",
    "content": "Authentic content originally signed",
    "forged_content": "Injected malicious alteration",
}


class MockResourceAdapter(BaseResourceAdapter):
    """General mock adapter for transforming arbitrary mock fixture dictionaries into ResourceRecords."""

    def __init__(
        self,
        source_name: str = "mock-source",
        source_type: SourceType = SourceType.OTHER,
        default_trust_level: TrustLevel = TrustLevel.LOW,
    ) -> None:
        super().__init__(
            adapter_name="MockResourceAdapter",
            source_type=source_type,
            default_trust_level=default_trust_level,
            default_retrieval_method=RetrievalMethod.FIXTURE,
        )
        self.source_name = source_name

    def ingest(
        self,
        payload: Union[Dict[str, Any], str],
        retrieved_at: Optional[str] = None,
        notes: str = "Ingested from offline mock fixture",
        custom_metadata: Optional[Dict[str, Any]] = None,
    ) -> AdapterIngestionResult:
        """Parse arbitrary mock fixture payload into ResourceRecord and ProvenanceRecord."""
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except Exception:
                data = {"content": payload, "title": "Raw Mock Resource"}
        elif isinstance(payload, dict):
            data = payload
        else:
            raise TypeError(f"Unsupported payload type: {type(payload)}")

        # Determine ResourceType
        if "code" in data:
            res_type = ResourceType.CODE_EXAMPLE
        elif data.get("is_api_reference") or "signature" in data:
            res_type = ResourceType.API_REFERENCE
        elif "requires_dist" in data or "package_name" in data or ("info" in data and "version" in data["info"]):
            res_type = ResourceType.PACKAGE_VERSION if data.get("version") or (data.get("info", {}).get("version")) else ResourceType.PACKAGE
        elif "repository" in data and not data.get("module"):
            res_type = ResourceType.REPOSITORY
        else:
            res_type = ResourceType.DOCUMENTATION

        info = data.get("info", data)
        pkg_name = info.get("name") or data.get("module") or data.get("package_name")
        repo_name = data.get("repository")
        version = info.get("version") or data.get("version") or data.get("declared_version")
        url = info.get("url") or info.get("home_page") or info.get("project_url") or data.get("url")
        norm_url = normalize_url(url)
        title = data.get("title") or info.get("title") or f"Mock Resource ({res_type.value})"
        desc = data.get("description") or info.get("summary") or info.get("description") or ""
        lic = info.get("license") or data.get("license")
        pub = data.get("published_at") or info.get("published_at")

        content = data.get("code") or data.get("content") or data.get("body")
        if content is None:
            content = json.dumps(data, sort_keys=True, ensure_ascii=False)

        c_hash = compute_content_hash(content)
        ret_time = retrieved_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

        res_id = generate_deterministic_resource_id(
            resource_type=res_type,
            source=self.source_name,
            url=norm_url,
            package_name=pkg_name,
            repository=repo_name,
            version=version,
        )

        observed_ver = data.get("observed_version") or version
        prov_id = generate_provenance_id(
            source_type=self.source_type,
            source_name=self.source_name,
            source_url=norm_url,
            content_hash=c_hash,
            declared_version=version,
        )

        prov = ProvenanceRecord(
            provenance_id=prov_id,
            source_type=self.source_type,
            source_name=self.source_name,
            source_url=norm_url,
            retrieved_at=ret_time,
            retrieval_method=self.default_retrieval_method,
            content_hash=c_hash,
            declared_version=version,
            observed_version=observed_ver,
            license=lic,
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
            description=desc,
            repository=repo_name,
            package_name=pkg_name,
            version=version,
            content_hash=c_hash,
            retrieved_at=ret_time,
            published_at=pub,
            license=lic,
            provenance_id=prov_id,
            verification_status=ResourceVerificationStatus.RETRIEVED,  # RETRIEVED != VERIFIED
            metadata={**(custom_metadata or {}), "raw_keys": list(data.keys())},
        )

        return AdapterIngestionResult(
            record=record,
            provenance=prov,
            raw_content=content,
            extraction_metadata={"resource_type": res_type.value, "version": version},
            is_successful=True,
        )
