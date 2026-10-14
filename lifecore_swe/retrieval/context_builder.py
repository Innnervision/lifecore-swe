"""Formats retrieved graph evidence into compact, Gemma-readable context."""

from typing import Any, Dict, List


class ContextBuilder:
    """Builds concise textual context from graph retrieval results."""

    @classmethod
    def build_context(
        cls,
        relevant_files: List[str],
        selected_nodes: List[Dict[str, Any]],
        selected_edges: List[Dict[str, Any]],
        associated_tests: List[Dict[str, Any]],
        max_chars: int = 4000,
    ) -> str:
        """Construct compact graph context string adhering to length constraints."""
        sections: List[str] = [
            "==================================================",
            "GRAPH-GUIDED REPOSITORY EVIDENCE (AUTOMATIC PRE-RETRIEVAL)",
            "==================================================",
        ]

        # 1. Relevant Files
        if relevant_files:
            sections.append("\n[Relevant Files]")
            for f in relevant_files:
                sections.append(f"- {f}")

        # 2. Key Code Entities / Symbols
        if selected_nodes:
            sections.append("\n[Relevant Symbols & Definitions]")
            for n in selected_nodes:
                ntype = n.get("node_type", "entity")
                symbol = n.get("symbol", "")
                path = n.get("path", "")
                s_line = n.get("start_line")
                e_line = n.get("end_line")
                line_str = f" (lines {s_line}-{e_line})" if s_line and e_line else ""
                sections.append(f"- {symbol} [{ntype}] in {path}{line_str}")

        # 3. Associated Tests
        if associated_tests:
            sections.append("\n[Associated Tests]")
            for t in associated_tests:
                t_sym = t.get("symbol", "")
                t_path = t.get("path", "")
                target = t.get("target_symbol", "")
                target_str = f" -> verifies {target}" if target else ""
                sections.append(f"- {t_sym} ({t_path}){target_str}")

        # 4. Structural Relationships
        if selected_edges:
            sections.append("\n[Graph Relationships]")
            seen_rels = set()
            for e in selected_edges:
                src = e.get("source_symbol") or e.get("source", "")
                rel = e.get("edge_type", "")
                tgt = e.get("target_symbol") or e.get("target", "")
                rel_str = f"- {src} --[{rel}]--> {tgt}"
                if rel_str not in seen_rels:
                    seen_rels.add(rel_str)
                    sections.append(rel_str)

        raw_context = "\n".join(sections).strip()

        # Enforce budget
        if len(raw_context) > max_chars:
            raw_context = raw_context[: max_chars - 30] + "\n... [Context Truncated]"

        return raw_context
