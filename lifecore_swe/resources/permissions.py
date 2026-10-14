"""Deterministic permission and security boundary model for external resources.

Enforces network access policies purely offline.
The permission system does NOT perform network access; it determines whether
a network request is permissible under the active policy.

Default rule: strictly DENY.
"""

from __future__ import annotations

import ipaddress
import urllib.parse
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any, Dict, Optional, Set, Union

from .models import ResourceType


class NetworkPermissionLevel(IntEnum):
    """Hierarchical network permission levels."""
    LEVEL_0_NO_NETWORK = 0
    LEVEL_1_APPROVED_DOCUMENTATION = 1
    LEVEL_2_APPROVED_PUBLIC_REPOSITORIES = 2
    LEVEL_3_PACKAGE_MODEL_DOWNLOADS = 3
    LEVEL_4_EXTERNAL_APIS = 4
    LEVEL_5_AUTHENTICATED_SERVICES = 5
    LEVEL_6_SENSITIVE_PRIVATE_INFRASTRUCTURE = 6


BLOCKED_HOSTS_AND_IPS: Set[str] = {
    "169.254.169.254",  # Cloud metadata service
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
}


@dataclass
class NetworkRequest:
    """Specification of an attempted external network operation."""
    requested_level: NetworkPermissionLevel
    target_url: str
    resource_type: Union[ResourceType, str]
    source_name: str
    purpose: str = ""
    requires_authentication: bool = False
    is_private_infrastructure: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.requested_level, int) and not isinstance(self.requested_level, NetworkPermissionLevel):
            self.requested_level = NetworkPermissionLevel(self.requested_level)
        if isinstance(self.resource_type, str):
            try:
                self.resource_type = ResourceType(self.resource_type)
            except ValueError:
                self.resource_type = ResourceType.OTHER


@dataclass
class PermissionDecision:
    """Result of policy evaluation for a network request."""
    allowed: bool
    requested_level: NetworkPermissionLevel
    policy_level: NetworkPermissionLevel
    reason: str
    resource_or_source: str
    requires_confirmation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requested_level": int(self.requested_level),
            "requested_level_name": self.requested_level.name,
            "policy_level": int(self.policy_level),
            "policy_level_name": self.policy_level.name,
            "reason": self.reason,
            "resource_or_source": self.resource_or_source,
            "requires_confirmation": self.requires_confirmation,
        }


def extract_host(target_url: str) -> str:
    """Extract and normalize hostname from target URL."""
    if not target_url:
        return ""
    if "://" not in target_url:
        target_url = f"https://{target_url}"
    parsed = urllib.parse.urlsplit(target_url)
    host = parsed.hostname or ""
    return host.lower()


def is_private_ip(host: str) -> bool:
    """Check if host is a private/loopback/link-local IP address."""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return False


@dataclass
class PermissionPolicy:
    """Controlled source allowlists and deterministic policy enforcement."""
    policy_level: NetworkPermissionLevel = NetworkPermissionLevel.LEVEL_0_NO_NETWORK
    approved_doc_domains: Set[str] = field(default_factory=lambda: {
        "docs.python.org",
        "packaging.python.org",
        "peps.python.org",
    })
    approved_repo_hosts: Set[str] = field(default_factory=lambda: {
        "github.com",
        "gitlab.com",
    })
    approved_package_registries: Set[str] = field(default_factory=lambda: {
        "pypi.org",
        "files.pythonhosted.org",
    })
    approved_external_apis: Set[str] = field(default_factory=lambda: {
        "api.github.com",
    })
    approved_authenticated_services: Set[str] = field(default_factory=set)
    approved_private_hosts: Set[str] = field(default_factory=set)

    def evaluate(self, request: NetworkRequest) -> PermissionDecision:
        """Deterministically evaluate whether a network request is allowed.

        Follows strict default-deny.
        """
        source_label = request.target_url or request.source_name
        host = extract_host(request.target_url)

        # 1. Check unconditionally blocked targets (e.g. cloud metadata, loopback)
        if host in BLOCKED_HOSTS_AND_IPS or host == "169.254.169.254":
            return PermissionDecision(
                allowed=False,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason=f"Blocked security target: '{host}' is prohibited.",
                resource_or_source=source_label,
            )

        # 2. Check private IPs (unless Level 6 and explicitly permitted)
        if is_private_ip(host):
            if self.policy_level < NetworkPermissionLevel.LEVEL_6_SENSITIVE_PRIVATE_INFRASTRUCTURE or host not in self.approved_private_hosts:
                return PermissionDecision(
                    allowed=False,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason=f"Access to private IP '{host}' denied.",
                    resource_or_source=source_label,
                )

        # 3. Check requested level against active policy level
        if request.requested_level > self.policy_level:
            return PermissionDecision(
                allowed=False,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason=(
                    f"Permission escalation denied: requested level {request.requested_level.name} "
                    f"exceeds active policy level {self.policy_level.name}."
                ),
                resource_or_source=source_label,
            )

        # 4. Check Level 0 (strictly NO network)
        if self.policy_level == NetworkPermissionLevel.LEVEL_0_NO_NETWORK:
            return PermissionDecision(
                allowed=False,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason="Default deny: Network access is disabled (LEVEL_0_NO_NETWORK).",
                resource_or_source=source_label,
            )

        # 5. Check authentication requirements
        if request.requires_authentication:
            if self.policy_level < NetworkPermissionLevel.LEVEL_5_AUTHENTICATED_SERVICES:
                return PermissionDecision(
                    allowed=False,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason="Authenticated services require LEVEL_5_AUTHENTICATED_SERVICES or higher.",
                    resource_or_source=source_label,
                )
            if host not in self.approved_authenticated_services:
                return PermissionDecision(
                    allowed=False,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason=f"Host '{host}' is not in approved authenticated services allowlist.",
                    resource_or_source=source_label,
                )
            return PermissionDecision(
                allowed=True,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason="Authenticated service access approved with confirmation required.",
                resource_or_source=source_label,
                requires_confirmation=True,
            )

        # 6. Check private infrastructure requirements
        if request.is_private_infrastructure:
            if self.policy_level < NetworkPermissionLevel.LEVEL_6_SENSITIVE_PRIVATE_INFRASTRUCTURE:
                return PermissionDecision(
                    allowed=False,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason="Private infrastructure requires LEVEL_6_SENSITIVE_PRIVATE_INFRASTRUCTURE.",
                    resource_or_source=source_label,
                )
            if host not in self.approved_private_hosts:
                return PermissionDecision(
                    allowed=False,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason=f"Host '{host}' is not in approved private infrastructure allowlist.",
                    resource_or_source=source_label,
                )
            return PermissionDecision(
                allowed=True,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason="Private infrastructure access approved with confirmation required.",
                resource_or_source=source_label,
                requires_confirmation=True,
            )

        # 7. Check specific level allowlists
        if request.requested_level == NetworkPermissionLevel.LEVEL_1_APPROVED_DOCUMENTATION:
            if host in self.approved_doc_domains:
                return PermissionDecision(
                    allowed=True,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason=f"Host '{host}' matched approved documentation allowlist.",
                    resource_or_source=source_label,
                )
            return PermissionDecision(
                allowed=False,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason=f"Host '{host}' is not in approved documentation allowlist.",
                resource_or_source=source_label,
            )

        if request.requested_level == NetworkPermissionLevel.LEVEL_2_APPROVED_PUBLIC_REPOSITORIES:
            if host in self.approved_repo_hosts:
                return PermissionDecision(
                    allowed=True,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason=f"Host '{host}' matched approved public repository allowlist.",
                    resource_or_source=source_label,
                )
            return PermissionDecision(
                allowed=False,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason=f"Host '{host}' is not in approved public repository allowlist.",
                resource_or_source=source_label,
            )

        if request.requested_level == NetworkPermissionLevel.LEVEL_3_PACKAGE_MODEL_DOWNLOADS:
            if host in self.approved_package_registries:
                return PermissionDecision(
                    allowed=True,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason=f"Host '{host}' matched approved package registry allowlist.",
                    resource_or_source=source_label,
                )
            return PermissionDecision(
                allowed=False,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason=f"Host '{host}' is not in approved package registry allowlist.",
                resource_or_source=source_label,
            )

        if request.requested_level == NetworkPermissionLevel.LEVEL_4_EXTERNAL_APIS:
            if host in self.approved_external_apis:
                return PermissionDecision(
                    allowed=True,
                    requested_level=request.requested_level,
                    policy_level=self.policy_level,
                    reason=f"Host '{host}' matched approved external API allowlist.",
                    resource_or_source=source_label,
                )
            return PermissionDecision(
                allowed=False,
                requested_level=request.requested_level,
                policy_level=self.policy_level,
                reason=f"Host '{host}' is not in approved external API allowlist.",
                resource_or_source=source_label,
            )

        # Fallback deny
        return PermissionDecision(
            allowed=False,
            requested_level=request.requested_level,
            policy_level=self.policy_level,
            reason="Unrecognized or unhandled request type: denied by default.",
            resource_or_source=source_label,
        )
