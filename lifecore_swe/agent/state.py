"""Structured state for LIFECORE-SWE agent."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentState:
    """Maintains the full execution state of the SWE agent."""
    task: str = ""
    observations: List[str] = field(default_factory=list)
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    files_inspected: List[str] = field(default_factory=list)
    searches: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    test_results: List[Dict[str, Any]] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)
    recovery_attempts: int = 0
    patch_attempts: int = 0
    final_patch: str = ""
    verification: Optional[Dict[str, Any]] = None
    graph_evidence: str = ""
    experience_context: str = ""
    experiences_retrieved: List[str] = field(default_factory=list)
    current_phase: str = "INIT"

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to a serializable dictionary."""
        return {
            "task": self.task,
            "observations": list(self.observations),
            "hypotheses": list(self.hypotheses),
            "files_inspected": list(self.files_inspected),
            "searches": list(self.searches),
            "actions": list(self.actions),
            "test_results": list(self.test_results),
            "failures": list(self.failures),
            "recovery_attempts": self.recovery_attempts,
            "patch_attempts": self.patch_attempts,
            "final_patch": self.final_patch,
            "verification": self.verification,
            "graph_evidence": self.graph_evidence,
            "experience_context": self.experience_context,
            "experiences_retrieved": list(self.experiences_retrieved),
            "current_phase": self.current_phase,
        }
