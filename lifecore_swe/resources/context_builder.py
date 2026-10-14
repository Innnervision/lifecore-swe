"""Resource Context Builder for LIFECORE-SWE (M5-D).

Formats bounded external resource evidence with strict truth boundaries,
provenance indicators, verification states, confidence, version details,
and contradiction warnings for Gemma 4 reasoning.

Architecture:
    INTERNAL CODE EVIDENCE     -> Verified repository AST
    VERIFIED EXPERIENCE        -> Historic positive SWE trajectories
    NEGATIVE EXPERIENCE        -> Attributed failure transitions
    EXTERNAL RESOURCE          -> Verified/validated external knowledge
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .graph.retriever import ResourceEvidenceItem, ResourceRetrievalResult
from .models import FreshnessStatus, ResourceVerificationStatus
from .provenance import ProvenanceRecord


class ResourceContextBuilder:
    """Constructs formatted external resource evidence contexts with strict truth labeling."""

    @staticmethod
    def build_resource_context(
        retrieval_result: Optional[ResourceRetrievalResult],
        provenance_map: Optional[Dict[str, ProvenanceRecord]] = None,
        max_chars: int = 2500,
    ) -> str:
        """Format bounded external evidence items into an unambiguous reference block."""
        if retrieval_result is None or not retrieval_result.items:
            return (
                "=== EXTERNAL RESOURCE EVIDENCE ===\n"
                "TRUTH BOUNDARY: External resources are advisory. Internal repository code is ground truth.\n"
                "  (No relevant external resources retrieved for this task)\n"
            )

        prov_map = provenance_map or {}
        lines: List[str] = [
            "=== EXTERNAL RESOURCE EVIDENCE ===",
            "TRUTH BOUNDARY: External resources are advisory reference material. Internal repository code and ground truth ALWAYS supersede external references.",
            "STATUS INVARIANT: Unverified external documentation is NOT verified internal code.",
            f"RETRIEVED ITEMS: {len(retrieval_result.items)} (Total candidates considered: {retrieval_result.total_candidates_considered})",
            "",
        ]

        for idx, item in enumerate(retrieval_result.items, 1):
            node = item.node
            item_lines: List[str] = []

            item_lines.append(f"RESOURCE [{idx}]:")
            item_lines.append(f"    TITLE: {node.title}")
            item_lines.append(f"    TYPE: {node.node_type.value}")
            item_lines.append(f"    VERSION: {node.version or 'unversioned'}")
            item_lines.append(f"    STATUS: {node.verification_status.value}")
            item_lines.append(f"    SOURCE: {node.source}")
            item_lines.append(f"    CONFIDENCE: {node.confidence:.2f}")
            item_lines.append(f"    RELEVANCE: {item.score:.2f}")

            # Provenance audit block
            prov = prov_map.get(node.provenance_id) if node.provenance_id else None
            if prov:
                item_lines.append("    PROVENANCE:")
                item_lines.append(f"        ID: {prov.provenance_id}")
                item_lines.append(f"        Source Type: {prov.source_type.value}")
                item_lines.append(f"        Method: {prov.retrieval_method.value}")
                item_lines.append(f"        Trust: {prov.trust_level.value}")
            elif node.provenance_id:
                item_lines.append(f"    PROVENANCE ID: {node.provenance_id}")

            # Freshness
            item_lines.append(f"    FRESHNESS: {node.freshness.value}")

            # Status warnings
            if node.verification_status in (
                ResourceVerificationStatus.UNVERIFIED,
                ResourceVerificationStatus.RETRIEVED,
            ):
                item_lines.append(
                    "    WARNING: Resource is UNVERIFIED / RETRIEVED only. Do NOT treat as ground-truth repository behavior."
                )
            elif node.verification_status == ResourceVerificationStatus.CONTRADICTED:
                item_lines.append(
                    "    CRITICAL WARNING: CONTRADICTION DETECTED. Resource asserts claims conflicting with verified ground truth."
                )
            elif node.verification_status == ResourceVerificationStatus.VERIFIED:
                item_lines.append(
                    "    VERIFICATION NOTE: Resource has been explicitly validated against repository ground truth."
                )

            # Description / content excerpt
            if node.description:
                short_desc = node.description[:200] + ("..." if len(node.description) > 200 else "")
                item_lines.append(f"    SUMMARY: {short_desc}")

            # Associated graph relationships
            if item.relationships:
                rel_strs = [f"{e.edge_type.value}->{e.target_id}" for e in item.relationships[:3]]
                item_lines.append(f"    RELATIONSHIPS: {', '.join(rel_strs)}")

            item_lines.append("")

            # Check character budget
            candidate_text = "\n".join(item_lines)
            if len("\n".join(lines)) + len(candidate_text) > max_chars:
                lines.append("... [Additional external resources truncated by context budget] ...")
                break

            lines.extend(item_lines)

        return "\n".join(lines).strip()


class UnifiedWorldModelContextBuilder:
    """Assembles all 4 LIFECORE-SWE evidence streams into a structured, truth-bounded context.

    Streams:
    1. INTERNAL CODE EVIDENCE: Static AST code graph (files, nodes, symbols, calls)
    2. VERIFIED POSITIVE EXPERIENCE: Reinforced edge transitions and successful patches
    3. ATTRIBUTED NEGATIVE EXPERIENCE: Penalized edge transitions and failure anti-priors
    4. EXTERNAL RESOURCE EVIDENCE: Provenance-aware external documentation and package specs
    """

    @staticmethod
    def build_unified_context(
        code_graph_evidence: str = "",
        experience_evidence: str = "",
        negative_experience_evidence: str = "",
        resource_evidence: str = "",
        max_total_chars: int = 7000,
    ) -> str:
        """Compose the unified multi-stream prompt context with explicit trust boundaries."""
        sections: List[str] = [
            "================================================================================",
            "LIFECORE-SWE VERIFIED WORLD MODEL CONTEXT",
            "================================================================================",
            "CORE REASONING PRINCIPLE:",
            "  1. INTERNAL REPOSITORY CODE IS ABSOLUTE GROUND TRUTH.",
            "  2. VERIFIED POSITIVE EXPERIENCE PROVIDES PROVEN STRUCTURAL PRIORS.",
            "  3. NEGATIVE EXPERIENCE WARNS AGAINST KNOWN FAILED TRANSITIONS.",
            "  4. EXTERNAL RESOURCES ARE ADVISORY ONLY (NEVER TREAT UNVERIFIED SPECS AS GROUND TRUTH).",
            "================================================================================",
            "",
        ]

        if code_graph_evidence:
            sections.append("### STREAM 1: INTERNAL CODE EVIDENCE (AST REPOSITORY GRAPH)")
            sections.append(code_graph_evidence.strip())
            sections.append("")

        if experience_evidence:
            sections.append("### STREAM 2: VERIFIED POSITIVE EXPERIENCE")
            sections.append(experience_evidence.strip())
            sections.append("")

        if negative_experience_evidence:
            sections.append("### STREAM 3: ATTRIBUTED NEGATIVE EXPERIENCE (FAILURE AVOIDANCE)")
            sections.append(negative_experience_evidence.strip())
            sections.append("")

        if resource_evidence:
            sections.append("### STREAM 4: EXTERNAL RESOURCE EVIDENCE (PROVENANCE & VERSION AWARE)")
            sections.append(resource_evidence.strip())
            sections.append("")

        full_text = "\n".join(sections).strip()
        if len(full_text) > max_total_chars:
            return full_text[:max_total_chars] + "\n... [Context truncated to adhere to budget] ..."
        return full_text
