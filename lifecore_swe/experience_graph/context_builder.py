"""Compact Evidence Context Builder for Experience-Conditioned Code Graph with Failure Awareness (M4)."""

from typing import Any, Dict, List, Optional
from .models import ExperienceGraphConfig, ScoredEdge


class AdaptiveContextBuilder:
    """Formats deterministic, experience-conditioned graph evidence with positive and negative signals."""

    @staticmethod
    def build_context(
        relevant_files: List[str],
        selected_nodes: List[Dict[str, Any]],
        scored_edges: List[ScoredEdge],
        associated_tests: List[Dict[str, Any]],
        experience_supported_edges: List[str],
        penalized_edges: Optional[List[str]] = None,
        structural_experience_gain: float = 0.0,
        include_raw_experience_text: bool = True,
        max_chars: int = 3500,
    ) -> str:
        """Construct compact, budget-enforcing evidence block."""
        pen_edges = penalized_edges or []
        lines: List[str] = [
            "=== EXPERIENCE-CONDITIONED REPOSITORY GRAPH EVIDENCE ===",
            "NOTE: Repository graph transitions below are ranked by static AST structure + verified positive and negative SWE experience.",
            "CURRENT REPOSITORY STATE ALWAYS WINS: Structural priors and failure penalties guide navigation, but live code is ground truth.",
            "",
            "PRIORITY RELEVANT FILES:",
        ]

        if relevant_files:
            for f in relevant_files:
                lines.append(f"  - {f}")
        else:
            lines.append("  - (No specific file targets localized)")

        lines.append("")
        lines.append(f"KEY CODE SYMBOLS & NODES (Selected: {len(selected_nodes)}):")
        for node in selected_nodes[:8]:
            nid = node.get("node_id", "")
            ntype = node.get("node_type", "")
            sym = node.get("symbol", "")
            path = node.get("path", "")
            lines.append(f"  - [{ntype.upper()}] {sym} ({path})")

        lines.append("")
        lines.append(
            f"EXPERIENCE-CONDITIONED TRANSITIONS (Total: {len(scored_edges)}, "
            f"Reinforced: {len(experience_supported_edges)}, Penalized: {len(pen_edges)}):"
        )

        for edge in scored_edges[:10]:
            src_sym = edge.source_symbol or edge.source
            tgt_sym = edge.target_symbol or edge.target
            exp_str = f"+{edge.experience_score:.2f}" if edge.experience_score > 0 else "0.00"
            neg_str = f"-{edge.negative_score:.2f}" if edge.negative_score > 0 else "0.00"

            neg_part = f", Neg: -{edge.negative_score:.2f}" if edge.negative_score > 0 else ""
            lines.append(
                f"  - {src_sym} --[{edge.edge_type}]--> {tgt_sym} "
                f"[Base: {edge.base_score:.2f}, Exp: {exp_str}{neg_part}, Final: {edge.final_score:.2f}]"
            )
            if edge.experience_score > 0 or edge.negative_score > 0:
                lines.append(f"    Reason: {edge.selection_reason}")

        if associated_tests:
            lines.append("")
            lines.append(f"VERIFICATION TEST TARGETS (Prioritized: {len(associated_tests)}):")
            for t in associated_tests[:4]:
                sym = t.get("symbol", "")
                path = t.get("path", "")
                target_sym = t.get("target_symbol", "")
                lines.append(f"  - {sym} ({path}) verifies {target_sym}")

        lines.append("=========================================================")

        rendered = "\n".join(lines)
        if len(rendered) > max_chars:
            rendered = rendered[:max_chars - 30] + "\n... [Context truncated to budget]"

        return rendered
