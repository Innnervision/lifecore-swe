"""Resource Validator: Offline validation and verification pipeline for external software resources.

Enforces:
    RETRIEVED != VERIFIED
    Validation checks:
    - Schema correctness
    - Content hash integrity
    - Declared vs observed version consistency
    - Source identity alignment
    - License metadata compliance
    - Syntax correctness (AST parsing for code examples)
    - Contradiction detection against verified ground truth
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Union

from .models import (
    ResourceRecord,
    ResourceType,
    ResourceVerificationStatus,
    compute_content_hash,
)
from .provenance import ProvenanceRecord


PERMISSIVE_LICENSES: Set[str] = {
    "MIT",
    "APACHE-2.0",
    "APACHE 2.0",
    "PSF-2.0",
    "PYTHON-2.0",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "ISC",
    "MPL-2.0",
    "LGPL-3.0-ONLY",
    "GPL-3.0-ONLY",
    "CC0-1.0",
    "UNLICENSE",
}

DISALLOWED_LICENSES: Set[str] = {
    "PROPRIETARY_UNLICENSED_MALWARE",
    "MALWARE",
    "FORBIDDEN",
    "UNLICENSED_PROPRIETARY",
}


@dataclass
class ValidationResult:
    """Outcome of validating an external resource."""
    is_valid: bool
    status: ResourceVerificationStatus
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks_run: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "status": self.status.value,
            "violations": self.violations,
            "warnings": self.warnings,
            "checks_run": self.checks_run,
            "notes": self.notes,
        }


class ResourceValidator:
    """Deterministic validation pipeline for external software resources."""

    def __init__(
        self,
        allowed_licenses: Optional[Set[str]] = None,
        disallowed_licenses: Optional[Set[str]] = None,
        require_license: bool = True,
        enforce_syntax_check: bool = True,
    ) -> None:
        self.allowed_licenses = {lic.upper() for lic in (allowed_licenses or PERMISSIVE_LICENSES)}
        self.disallowed_licenses = {lic.upper() for lic in (disallowed_licenses or DISALLOWED_LICENSES)}
        self.require_license = require_license
        self.enforce_syntax_check = enforce_syntax_check

    def validate(
        self,
        record: ResourceRecord,
        content: Optional[Union[str, bytes]] = None,
        provenance: Optional[ProvenanceRecord] = None,
        ground_truth: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Run complete validation pipeline.

        Elevates status from RETRIEVED to:
        - VERIFIED (if verified against ground truth or verified internal tests)
        - VALIDATED (if passes all integrity, schema, syntax, and licensing checks)
        - CONTRADICTED (if conflicts with verified ground truth or observed versions)
        - REJECTED (if fails schema, content hash, syntax, or security/licensing rules)
        """
        violations: List[str] = []
        warnings: List[str] = []
        checks_run: List[str] = []

        # 1. Schema Correctness
        checks_run.append("schema_correctness")
        self._check_schema(record, violations)

        # 2. Content Hash Integrity
        if content is not None:
            checks_run.append("content_hash_integrity")
            self._check_content_hash(record, content, violations)

        # 3. Version Consistency (Declared vs Observed)
        checks_run.append("version_consistency")
        is_contradicted = self._check_version_consistency(record, provenance, violations, warnings)

        # 4. Source Identity Alignment
        if provenance is not None:
            checks_run.append("source_identity_alignment")
            self._check_source_identity(record, provenance, violations, warnings)

        # 5. License Metadata Compliance
        checks_run.append("license_metadata_compliance")
        self._check_license(record, violations, warnings)

        # 6. Syntax Correctness (for Code Examples)
        if self.enforce_syntax_check:
            checks_run.append("content_syntax_correctness")
            self._check_syntax(record, content, violations)

        # 7. Contradiction Detection against Ground Truth
        if ground_truth is not None:
            checks_run.append("ground_truth_consistency")
            gt_contradicted = self._check_ground_truth_contradiction(record, ground_truth, violations, warnings)
            if gt_contradicted:
                is_contradicted = True

        # Determine Final Status
        if violations:
            if is_contradicted:
                final_status = ResourceVerificationStatus.CONTRADICTED
            else:
                final_status = ResourceVerificationStatus.REJECTED
            is_valid = False
            notes = f"Validation failed with {len(violations)} violation(s)."
        elif is_contradicted:
            final_status = ResourceVerificationStatus.CONTRADICTED
            is_valid = False
            notes = "Resource metadata contradicts verified ground truth."
        else:
            is_valid = True
            # If ground truth was supplied and verified, elevate to VERIFIED; otherwise VALIDATED
            if ground_truth is not None and ground_truth.get("verified_by_repository"):
                final_status = ResourceVerificationStatus.VERIFIED
            else:
                final_status = ResourceVerificationStatus.VALIDATED
            notes = f"Validation succeeded: status elevated to {final_status.value}."

        return ValidationResult(
            is_valid=is_valid,
            status=final_status,
            violations=violations,
            warnings=warnings,
            checks_run=checks_run,
            notes=notes,
        )

    def _check_schema(self, record: ResourceRecord, violations: List[str]) -> None:
        if not record.resource_id or not record.resource_id.startswith("res_"):
            violations.append(f"Invalid resource_id format: '{record.resource_id}'. Must start with 'res_'.")
        if not isinstance(record.resource_type, ResourceType):
            violations.append(f"Invalid resource_type: '{record.resource_type}'. Must be a valid ResourceType enum.")
        if not record.source or not record.source.strip():
            violations.append("Resource source is empty or missing.")
        if not record.content_hash or len(record.content_hash) != 64:
            violations.append(f"Invalid content_hash '{record.content_hash}'. Must be a 64-character SHA-256 hex string.")

    def _check_content_hash(
        self,
        record: ResourceRecord,
        content: Union[str, bytes],
        violations: List[str],
    ) -> None:
        computed = compute_content_hash(content)
        if computed != record.content_hash:
            violations.append(
                f"Content hash mismatch: record specifies '{record.content_hash}', "
                f"but computed hash of payload is '{computed}'."
            )

    def _check_version_consistency(
        self,
        record: ResourceRecord,
        provenance: Optional[ProvenanceRecord],
        violations: List[str],
        warnings: List[str],
    ) -> bool:
        """Check if declared version contradicts observed version."""
        if provenance is None:
            return False

        d_ver = provenance.declared_version
        o_ver = provenance.observed_version
        r_ver = record.version

        # If declared and observed versions exist and differ significantly
        if d_ver and o_ver and d_ver.strip().lower() != o_ver.strip().lower():
            violations.append(
                f"Version contradiction in provenance: declared '{d_ver}' contradicts observed '{o_ver}'."
            )
            return True

        # If record version differs from provenance declared version
        if r_ver and d_ver and r_ver.strip().lower() != d_ver.strip().lower():
            violations.append(
                f"Version contradiction: record specifies '{r_ver}', but provenance declared '{d_ver}'."
            )
            return True

        return False

    def _check_source_identity(
        self,
        record: ResourceRecord,
        provenance: ProvenanceRecord,
        violations: List[str],
        warnings: List[str],
    ) -> None:
        if record.source.strip().lower() != provenance.source_name.strip().lower():
            violations.append(
                f"Source identity mismatch: record source '{record.source}' "
                f"does not match provenance source_name '{provenance.source_name}'."
            )

    def _check_license(
        self,
        record: ResourceRecord,
        violations: List[str],
        warnings: List[str],
    ) -> None:
        lic = (record.license or "").strip().upper()
        if not lic:
            if self.require_license:
                violations.append("License metadata is missing.")
            else:
                warnings.append("License metadata is missing.")
            return

        if lic in self.disallowed_licenses:
            violations.append(f"Forbidden or hazardous license detected: '{record.license}'.")
            return

        # Check if license matches known permissive licenses (fuzzy or exact)
        matched = False
        for allowed in self.allowed_licenses:
            if allowed in lic or lic in allowed:
                matched = True
                break

        if not matched:
            warnings.append(f"License '{record.license}' is not in standard permissive allowlist.")

    def _check_syntax(
        self,
        record: ResourceRecord,
        content: Optional[Union[str, bytes]],
        violations: List[str],
    ) -> None:
        """Check Python syntax for code-bearing resources."""
        code_str: Optional[str] = None

        if record.resource_type == ResourceType.CODE_EXAMPLE:
            if isinstance(content, str):
                code_str = content
            elif isinstance(content, bytes):
                try:
                    code_str = content.decode("utf-8")
                except UnicodeDecodeError:
                    violations.append("Binary payload cannot be decoded as utf-8 Python source.")
                    return
            elif "code" in record.metadata:
                code_str = str(record.metadata["code"])

        if code_str is not None:
            try:
                ast.parse(code_str)
            except SyntaxError as e:
                violations.append(f"Syntax validation error in code example: {e.msg} at line {e.lineno}.")

    def _check_ground_truth_contradiction(
        self,
        record: ResourceRecord,
        ground_truth: Dict[str, Any],
        violations: List[str],
        warnings: List[str],
    ) -> bool:
        """Check if resource claims contradict ground truth."""
        # 1. Package version ground truth
        if "package_version" in ground_truth and record.version:
            expected_ver = str(ground_truth["package_version"]).strip().lower()
            actual_ver = record.version.strip().lower()
            if actual_ver != expected_ver:
                violations.append(
                    f"Ground truth contradiction: expected version '{expected_ver}', "
                    f"resource claims '{actual_ver}'."
                )
                return True

        # 2. Known symbols ground truth
        if "forbidden_symbols" in ground_truth:
            forbidden = set(ground_truth["forbidden_symbols"])
            meta_symbols = set(record.metadata.get("symbols", []))
            clash = forbidden.intersection(meta_symbols)
            if clash:
                violations.append(
                    f"Ground truth contradiction: resource advertises forbidden/removed symbol(s): {clash}."
                )
                return True

        return False
