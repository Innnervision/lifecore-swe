"""Trajectory recorder for saving execution traces as JSONL."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class TrajectoryRecorder:
    """Records step-by-step agent trajectory into structured JSONL."""

    def __init__(self, task_id: str, output_path: str):
        self.task_id = task_id
        self.output_path = Path(output_path).resolve()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.steps: List[Dict[str, Any]] = []

    def record_step(
        self,
        step_id: int,
        agent_state: str,
        action: str,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        confidence: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Record an individual action step (M0.1 schema)."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task_id,
            "step_id": step_id,
            "agent_state": agent_state,
            "action": action,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "confidence": confidence,
        }
        self.steps.append(entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + chr(10))
        return entry

    def record_m1a_step(
        self,
        model: str,
        task: str,
        observation: Any,
        action: str,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        hypothesis_summary: Optional[str] = None,
        confidence: Optional[float] = None,
        test_result: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an individual action step following M1A schema."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "task": task,
            "observation": observation,
            "action": action,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "hypothesis_summary": hypothesis_summary,
            "confidence": confidence,
            "test_result": test_result,
            "verification": verification,
        }
        self.steps.append(entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + chr(10))
        return entry

    def record_m1b_step(
        self,
        model: str,
        task: str,
        observation: Any,
        action: str,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        hypothesis_summary: Optional[str] = None,
        confidence: Optional[float] = None,
        graph_queries: Optional[List[Dict[str, Any]]] = None,
        graph_nodes_returned: Optional[List[str]] = None,
        graph_edges_returned: Optional[List[str]] = None,
        graph_nodes_selected: Optional[List[str]] = None,
        graph_nodes_rejected: Optional[List[str]] = None,
        reason_for_graph_query: Optional[str] = None,
        test_result: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an individual action step following M1B graph-aware schema."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "task": task,
            "observation": observation,
            "action": action,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "hypothesis_summary": hypothesis_summary,
            "confidence": confidence,
            "graph_queries": graph_queries or [],
            "graph_nodes_returned": graph_nodes_returned or [],
            "graph_edges_returned": graph_edges_returned or [],
            "graph_nodes_selected": graph_nodes_selected or [],
            "graph_nodes_rejected": graph_nodes_rejected or [],
            "reason_for_graph_query": reason_for_graph_query or "",
            "test_result": test_result,
            "verification": verification,
        }
        self.steps.append(entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + chr(10))
        return entry

    def record_m1c_step(
        self,
        model: str,
        task: str,
        condition: str,
        repository_version: str,
        step_id: int,
        observation: Any,
        action: str,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        hypothesis_summary: Optional[str] = None,
        confidence: Optional[float] = None,
        files_read: Optional[List[str]] = None,
        files_modified: Optional[List[str]] = None,
        searches_count: int = 0,
        test_runs_count: int = 0,
        recovery_attempts: int = 0,
        graph_retrieval_query: Optional[str] = None,
        candidate_nodes: Optional[List[str]] = None,
        selected_nodes: Optional[List[str]] = None,
        selected_edges: Optional[List[str]] = None,
        ranking_scores: Optional[Dict[str, float]] = None,
        context_injected: Optional[str] = None,
        test_result: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record a comprehensive step following the M1C specification."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task_id,
            "step_id": step_id,
            "condition": condition,
            "repository_version": repository_version,
            "model": model,
            "action": action,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "observation": observation,
            "hypothesis_summary": hypothesis_summary,
            "confidence": confidence,
            "files_read": files_read or [],
            "files_modified": files_modified or [],
            "searches_count": searches_count,
            "test_runs_count": test_runs_count,
            "recovery_attempts": recovery_attempts,
            "graph_retrieval_query": graph_retrieval_query or "",
            "candidate_nodes": candidate_nodes or [],
            "selected_nodes": selected_nodes or [],
            "selected_edges": selected_edges or [],
            "ranking_scores": ranking_scores or {},
            "context_injected": context_injected or "",
            "test_result": test_result,
            "verification": verification,
        }
        self.steps.append(entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + chr(10))
        return entry

    def record_final(
        self,
        final_status: str,
        patch: str,
        tests: Dict[str, Any],
        verification: Dict[str, Any],
        failure_reason: Optional[str] = None,
        files_changed: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Record terminal outcome entry."""
        final_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task_id,
            "step_id": len(self.steps) + 1,
            "agent_state": "COMPLETED",
            "action": "finalize_trajectory",
            "tool": "none",
            "arguments": {},
            "result": "task_concluded",
            "confidence": 1.0 if final_status == "SUCCESS" else 0.0,
            "final_status": final_status,
            "patch": patch,
            "tests": tests,
            "verification": verification,
            "failure_reason": failure_reason,
            "files_changed": files_changed or [],
        }
        self.steps.append(final_entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(final_entry, default=str) + "\n")
        return final_entry

    def record_m2_step(
        self,
        model: str,
        task: str,
        condition: str,
        repository_version: str,
        step_id: int,
        observation: Any,
        action: str,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        hypothesis_summary: Optional[str] = None,
        confidence: Optional[float] = None,
        files_read: Optional[List[str]] = None,
        files_modified: Optional[List[str]] = None,
        searches_count: int = 0,
        test_runs_count: int = 0,
        recovery_attempts: int = 0,
        graph_retrieval_query: Optional[str] = None,
        candidate_nodes: Optional[List[str]] = None,
        selected_nodes: Optional[List[str]] = None,
        selected_edges: Optional[List[str]] = None,
        ranking_scores: Optional[Dict[str, float]] = None,
        context_injected: Optional[str] = None,
        experiences_retrieved: Optional[List[str]] = None,
        experience_scores: Optional[Dict[str, float]] = None,
        experience_reasons: Optional[Dict[str, List[str]]] = None,
        experience_stale_statuses: Optional[Dict[str, str]] = None,
        experience_context_injected: Optional[str] = None,
        experience_influence: Optional[str] = None,
        test_result: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an M2 step logging both graph and persistent experience evidence."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task_id,
            "step_id": step_id,
            "condition": condition,
            "repository_version": repository_version,
            "model": model,
            "action": action,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "observation": observation,
            "hypothesis_summary": hypothesis_summary,
            "confidence": confidence,
            "files_read": files_read or [],
            "files_modified": files_modified or [],
            "searches_count": searches_count,
            "test_runs_count": test_runs_count,
            "recovery_attempts": recovery_attempts,
            "graph_retrieval_query": graph_retrieval_query or "",
            "candidate_nodes": candidate_nodes or [],
            "selected_nodes": selected_nodes or [],
            "selected_edges": selected_edges or [],
            "ranking_scores": ranking_scores or {},
            "context_injected": context_injected or "",
            "experiences_retrieved": experiences_retrieved or [],
            "experience_scores": experience_scores or {},
            "experience_reasons": experience_reasons or {},
            "experience_stale_statuses": experience_stale_statuses or {},
            "experience_context_injected": experience_context_injected or "",
            "experience_influence": experience_influence or "NONE",
            "test_result": test_result,
            "verification": verification,
        }
        self.steps.append(entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + chr(10))
        return entry

    def record_m3_step(
        self,
        model: str,
        task: str,
        condition: str,
        repository_version: str,
        step_id: int,
        observation: Any,
        action: str,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        hypothesis_summary: Optional[str] = None,
        confidence: Optional[float] = None,
        files_read: Optional[List[str]] = None,
        files_modified: Optional[List[str]] = None,
        searches_count: int = 0,
        test_runs_count: int = 0,
        recovery_attempts: int = 0,
        graph_retrieval_query: Optional[str] = None,
        candidate_nodes: Optional[List[str]] = None,
        selected_nodes: Optional[List[str]] = None,
        selected_edges: Optional[List[str]] = None,
        scored_edges: Optional[List[Dict[str, Any]]] = None,
        ranking_scores: Optional[Dict[str, float]] = None,
        context_injected: Optional[str] = None,
        experiences_retrieved: Optional[List[str]] = None,
        experience_scores: Optional[Dict[str, float]] = None,
        experience_reasons: Optional[Dict[str, List[str]]] = None,
        experience_stale_statuses: Optional[Dict[str, str]] = None,
        experience_context_injected: Optional[str] = None,
        experience_influence: Optional[str] = None,
        experience_guided_edge_utilization: float = 0.0,
        experience_supported_edges: Optional[List[str]] = None,
        structural_experience_gain: float = 0.0,
        traversal_log: Optional[List[Dict[str, Any]]] = None,
        test_result: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an M3 step logging experience-conditioned graph traversal and scoring decisions."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "milestone": "M3",
            "task_id": self.task_id,
            "step_id": step_id,
            "condition": condition,
            "repository_version": repository_version,
            "model": model,
            "action": action,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "observation": observation,
            "hypothesis_summary": hypothesis_summary,
            "confidence": confidence,
            "files_read": files_read or [],
            "files_modified": files_modified or [],
            "searches_count": searches_count,
            "test_runs_count": test_runs_count,
            "recovery_attempts": recovery_attempts,
            "graph_retrieval_query": graph_retrieval_query or "",
            "candidate_nodes": candidate_nodes or [],
            "selected_nodes": selected_nodes or [],
            "selected_edges": selected_edges or [],
            "scored_edges": scored_edges or [],
            "ranking_scores": ranking_scores or {},
            "context_injected": context_injected or "",
            "experiences_retrieved": experiences_retrieved or [],
            "experience_scores": experience_scores or {},
            "experience_reasons": experience_reasons or {},
            "experience_stale_statuses": experience_stale_statuses or {},
            "experience_context_injected": experience_context_injected or "",
            "experience_influence": experience_influence or "NONE",
            "experience_guided_edge_utilization": experience_guided_edge_utilization,
            "experience_supported_edges": experience_supported_edges or [],
            "structural_experience_gain": structural_experience_gain,
            "traversal_log": traversal_log or [],
            "test_result": test_result,
            "verification": verification,
        }
        self.steps.append(entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + chr(10))
        return entry

    def record_m4_step(
        self,
        model: str,
        task: str,
        condition: str,
        repository_version: str,
        step_id: int,
        observation: Any,
        action: str,
        tool: str,
        arguments: Dict[str, Any],
        result: Any,
        hypothesis_summary: Optional[str] = None,
        confidence: Optional[float] = None,
        files_read: Optional[List[str]] = None,
        files_modified: Optional[List[str]] = None,
        searches_count: int = 0,
        test_runs_count: int = 0,
        recovery_attempts: int = 0,
        graph_retrieval_query: Optional[str] = None,
        candidate_nodes: Optional[List[str]] = None,
        selected_nodes: Optional[List[str]] = None,
        selected_edges: Optional[List[str]] = None,
        scored_edges: Optional[List[Dict[str, Any]]] = None,
        ranking_scores: Optional[Dict[str, float]] = None,
        context_injected: Optional[str] = None,
        experiences_retrieved: Optional[List[str]] = None,
        experience_scores: Optional[Dict[str, float]] = None,
        experience_reasons: Optional[Dict[str, List[str]]] = None,
        experience_stale_statuses: Optional[Dict[str, str]] = None,
        experience_context_injected: Optional[str] = None,
        experience_influence: Optional[str] = None,
        experience_guided_edge_utilization: float = 0.0,
        experience_supported_edges: Optional[List[str]] = None,
        structural_experience_gain: float = 0.0,
        penalized_edges: Optional[List[str]] = None,
        negative_avoidance_count: int = 0,
        negative_experiences_retrieved: Optional[List[str]] = None,
        negative_edge_penalties: Optional[Dict[str, float]] = None,
        repeat_failure_detected: bool = False,
        false_negative_guidance_detected: bool = False,
        traversal_log: Optional[List[Dict[str, Any]]] = None,
        test_result: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an M4 step logging positive/negative experience graph traversal, penalties, and avoidance."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "milestone": "M4",
            "task_id": self.task_id,
            "step_id": step_id,
            "condition": condition,
            "repository_version": repository_version,
            "model": model,
            "action": action,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "observation": observation,
            "hypothesis_summary": hypothesis_summary,
            "confidence": confidence,
            "files_read": files_read or [],
            "files_modified": files_modified or [],
            "searches_count": searches_count,
            "test_runs_count": test_runs_count,
            "recovery_attempts": recovery_attempts,
            "graph_retrieval_query": graph_retrieval_query or "",
            "candidate_nodes": candidate_nodes or [],
            "selected_nodes": selected_nodes or [],
            "selected_edges": selected_edges or [],
            "scored_edges": scored_edges or [],
            "ranking_scores": ranking_scores or {},
            "context_injected": context_injected or "",
            "experiences_retrieved": experiences_retrieved or [],
            "experience_scores": experience_scores or {},
            "experience_reasons": experience_reasons or {},
            "experience_stale_statuses": experience_stale_statuses or {},
            "experience_context_injected": experience_context_injected or "",
            "experience_influence": experience_influence or "NONE",
            "experience_guided_edge_utilization": experience_guided_edge_utilization,
            "experience_supported_edges": experience_supported_edges or [],
            "structural_experience_gain": structural_experience_gain,
            "penalized_edges": penalized_edges or [],
            "negative_avoidance_count": negative_avoidance_count,
            "negative_experiences_retrieved": negative_experiences_retrieved or [],
            "negative_edge_penalties": negative_edge_penalties or {},
            "repeat_failure_detected": repeat_failure_detected,
            "false_negative_guidance_detected": false_negative_guidance_detected,
            "traversal_log": traversal_log or [],
            "test_result": test_result,
            "verification": verification,
        }
        self.steps.append(entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + chr(10))
        return entry
