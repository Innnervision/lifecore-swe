"""Failure Attribution Engine for Negative Experience Learning (M4).

Analyzes failed SWE trajectories to determine failure taxonomy, causal attribution,
and specific repository transitions responsible for test or verification failures.
"""

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..codegraph.index import GraphIndex
from .models import (
    AttributionStrength,
    FailureType,
    FreshnessStatus,
    NegativeExperienceRecord,
)


class FailureAttributor:
    """Analyzes failed trajectories and attributes failure to specific graph transitions."""

    @staticmethod
    def analyze_failure(
        task_id: str,
        task_description: str,
        task_category: str,
        repo_path: Path,
        repo_version: str,
        files_inspected: List[str],
        files_modified: List[str],
        hypotheses: List[Dict[str, Any]],
        actions: List[Dict[str, Any]],
        test_results: List[Dict[str, Any]],
        verification: Optional[Dict[str, Any]] = None,
        graph_index: Optional[GraphIndex] = None,
        file_hashes: Optional[Dict[str, str]] = None,
        tool_calls_count: int = 0,
        max_loop_iterations: int = 20,
    ) -> List[NegativeExperienceRecord]:
        """Produce structured negative experience records with rigorous causal attribution."""
        records: List[NegativeExperienceRecord] = []
        now = time.time()
        f_hashes = file_hashes or {}

        # Step 1: Classify primary failure type
        last_test = test_results[-1] if test_results else {}
        test_summary = str(last_test.get("summary", ""))
        test_output = str(last_test.get("output", ""))
        combined_test_text = f"{test_summary}\n{test_output}"

        failure_reasons = []
        if verification:
            failure_reasons = verification.get("failure_reasons", [])

        # Categorization logic
        failure_type = FailureType.OTHER
        if "SyntaxError" in combined_test_text or "IndentationError" in combined_test_text:
            failure_type = FailureType.PATCH_FAILURE
        elif "AssertionError" in combined_test_text:
            failure_type = FailureType.TEST_FAILURE
        elif any("regressed" in r.lower() for r in failure_reasons):
            failure_type = FailureType.VERIFICATION_FAILURE
        elif tool_calls_count >= max_loop_iterations and not files_modified:
            failure_type = FailureType.BUDGET_EXHAUSTION
        elif not files_modified and files_inspected:
            failure_type = FailureType.LOCALIZATION_FAILURE
        elif files_modified:
            failure_type = FailureType.HYPOTHESIS_FAILURE

        last_hyp = ""
        if hypotheses:
            last_hyp = hypotheses[-1].get("hypothesis", "") or hypotheses[-1].get("thought_summary", "")

        # Step 2: Identify specific target symbols and transitions
        failed_symbols: Set[str] = set()

        # Extract symbols mentioned in assertion/traceback
        trace_symbols = set(re.findall(r"\b([A-Za-z0-9_]+)\b", combined_test_text))
        stop_words = {"def", "assert", "self", "return", "class", "test", "in", "for", "none", "true", "false", "where"}
        candidate_syms = {s for s in trace_symbols if s.lower() not in stop_words and len(s) >= 4}

        # Intersect with symbols from modified files if graph is available
        candidate_edges: List[Tuple[str, str, str, str, str]] = []  # (src, etype, tgt, sym, reason)

        if graph_index and files_modified:
            for fpath in files_modified:
                nodes_in_file = graph_index.find_by_path(fpath)
                for node in nodes_in_file:
                    if node.node_type in ("function", "method", "class"):
                        simple_sym = node.symbol.split(".")[-1]
                        # If symbol is mentioned in hypothesis or test failure trace
                        if (node.symbol in candidate_syms or simple_sym in candidate_syms) or (last_hyp and (node.symbol in last_hyp or simple_sym in last_hyp)):
                            failed_symbols.add(node.symbol)
                            # Find incident edges
                            for inc in graph_index.get_incoming(node.node_id, edge_type="CALLS"):
                                candidate_edges.append((inc.source, inc.edge_type, inc.target, node.symbol, f"Failed execution flow invoking {node.symbol}"))
                            for inc in graph_index.get_incoming(node.node_id, edge_type="TESTS"):
                                candidate_edges.append((inc.source, inc.edge_type, inc.target, node.symbol, f"Failed test asserting on {node.symbol}"))
                            # Also check incoming DEFINES or outgoing CALLS if no incoming calls/tests
                            if not candidate_edges:
                                for inc in graph_index.get_incoming(node.node_id, edge_type="DEFINES"):
                                    candidate_edges.append((inc.source, inc.edge_type, inc.target, node.symbol, f"Defines transition for failed symbol {node.symbol}"))

        # Step 3: Attribution strength assignment (Section 4 & 17)
        # Only assign STRONG or VERIFIED when direct causal connection exists
        if not candidate_edges:
            # Fallback: create general negative record without specific edge penalty
            rec = NegativeExperienceRecord(
                experience_id=f"NEG-EXP-{task_id}-{int(now)}",
                task_id=task_id,
                repository_id=repo_path.name,
                repository_version=repo_version,
                task_category=task_category,
                failure_type=failure_type.value,
                failed_hypothesis=last_hyp,
                failed_action="general_task_failure",
                failed_transition=None,
                source_node="",
                target_node="",
                edge_type="",
                failure_reason="; ".join(failure_reasons) or "Task failed without specific edge attribution.",
                failed_test=test_summary,
                expected_behavior="Expected tests and independent verification to pass.",
                observed_behavior=combined_test_text[:300],
                confidence=1.0,
                timestamp=now,
                provenance={"task_id": task_id, "git_commit": repo_version},
                attribution_strength=AttributionStrength.NONE.value,
                attribution_reason="Failure occurred without unequivocal link to a specific structural transition.",
                stale_status=FreshnessStatus.VALID.value,
                file_hashes=f_hashes,
            )
            records.append(rec)
            return records

        for src, etype, tgt, sym, reason in candidate_edges[:5]:
            edge_id = f"{src}->{etype}->{tgt}"

            # Determine attribution strength
            # If the test directly failed on this assertion AND the agent patched it: VERIFIED
            # If the agent formed a hypothesis about this transition and it failed: STRONG
            # If only incidental edit: MODERATE
            simple_s = sym.split(".")[-1]
            if failure_type in (FailureType.TEST_FAILURE, FailureType.VERIFICATION_FAILURE) and (sym in combined_test_text or simple_s in combined_test_text):
                attr_strength = AttributionStrength.STRONG.value
                attr_reason = f"Direct test assertion failure involving modified symbol '{sym}' on transition {edge_id}."
            elif last_hyp and (sym in last_hyp or simple_s in last_hyp):
                attr_strength = AttributionStrength.STRONG.value
                attr_reason = f"Agent hypothesis explicitly targeted '{sym}', but patch resulted in failure."
            else:
                attr_strength = AttributionStrength.MODERATE.value
                attr_reason = f"Transition involves modified symbol '{sym}', but causal link to failure is indirect."

            rec = NegativeExperienceRecord(
                experience_id=f"NEG-EXP-{task_id}-{int(now)}-{len(records)}",
                task_id=task_id,
                repository_id=repo_path.name,
                repository_version=repo_version,
                task_category=task_category,
                failure_type=failure_type.value,
                failed_hypothesis=last_hyp,
                failed_action="edit_and_test",
                failed_transition=edge_id,
                source_node=src,
                target_node=tgt,
                edge_type=etype,
                failure_reason="; ".join(failure_reasons) or f"Test failure in {sym}: {test_summary}",
                failed_test=test_summary,
                expected_behavior="Tests expected to pass without assertion or regression failures.",
                observed_behavior=combined_test_text[:300],
                confidence=1.0,
                timestamp=now,
                provenance={"task_id": task_id, "git_commit": repo_version, "symbol": sym},
                attribution_strength=attr_strength,
                attribution_reason=attr_reason,
                stale_status=FreshnessStatus.VALID.value,
                file_hashes=f_hashes,
            )
            records.append(rec)

        return records
