"""ModelAdapter interface and deterministic development adapter for M0.1."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ModelAdapter(ABC):
    """Abstract base class establishing the model abstraction interface."""

    @abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """Return metadata regarding the model and runtime implementation."""
        pass

    @abstractmethod
    def reason(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Formulate a structured hypothesis given a task and inspection context."""
        pass

    @abstractmethod
    def plan(self, task: str, context: Dict[str, Any]) -> List[str]:
        """Produce an action plan based on task and context."""
        pass

    @abstractmethod
    def select_action(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Select next actionable step given current agent state."""
        pass


class RuleBasedDevAdapter(ModelAdapter):
    """Clearly marked development adapter for M0.1 reproducible execution.
    
    NOTE: This is NOT a Gemma model or LLM. It is a deterministic rule-guided
    development adapter designed for baseline bootstrapping and pipeline validation.
    """

    def __init__(self):
        self.model_name = "RuleBasedDevAdapter"
        self.runtime = "CPython 3.12 Deterministic Engine (Non-LLM Development Adapter)"
        self.is_development_adapter = True

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "runtime": self.runtime,
            "is_development_adapter": self.is_development_adapter,
            "description": "Rule-guided development adapter for M0.1 autonomous loop validation",
        }

    def plan(self, task: str, context: Dict[str, Any]) -> List[str]:
        """Establish standard SWE patch loop plan."""
        return [
            "inspect_repository",
            "search_references",
            "read_candidate_files",
            "formulate_hypothesis",
            "apply_code_modification",
            "execute_tests",
            "analyze_test_failure",
            "attempt_recovery_patch",
            "retest_and_verify",
        ]

    def reason(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Produce structured hypothesis with cause, evidence, confidence, and files."""
        phase = context.get("phase", "INITIAL")
        test_failure = context.get("test_failure", "")

        if phase == "RECOVERY" or "test_critical_event_override" in test_failure:
            return {
                "hypothesis": (
                    "While the window boundary check was fixed, should_retain in filters.py "
                    "completely ignores the allow_critical_override flag. When an event has "
                    "severity CRITICAL or FATAL and allow_critical_override is True, it must "
                    "be retained regardless of min_severity threshold."
                ),
                "suspected_cause": "should_retain ignores allow_critical_override parameter in logic",
                "evidence": [
                    "TASK.md states CRITICAL events must be retained if allow_critical_override is True",
                    f"Test failure output: {test_failure.strip()[:140]}",
                    "filters.py lines 34-39 compare event_rank >= min_rank without checking allow_critical_override",
                ],
                "confidence": 0.94,
                "files_involved": ["event_processor/filters.py"],
            }

        # Initial hypothesis
        return {
            "hypothesis": (
                "EventPipeline drops boundary events because EventFilter.is_in_window uses a strict "
                "inequality (< window_end) instead of an inclusive boundary (<= window_end)."
            ),
            "suspected_cause": "Strict inequality '< window_end' in EventFilter.is_in_window",
            "evidence": [
                "TASK.md specifies: window_start <= event.timestamp <= window_end",
                "test_window_boundary_inclusion failure: 'end_bound' missing from result",
                "filters.py line 24: window_start <= event.timestamp < window_end",
            ],
            "confidence": 0.68,
            "files_involved": ["event_processor/filters.py"],
        }

    def select_action(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Determine next action based on agent state."""
        phase = state.get("current_phase", "INIT")
        patch_attempts = state.get("patch_attempts", 0)

        if phase == "INIT":
            return {"action": "list_files", "tool": "filesystem", "arguments": {}}
        elif phase == "LISTED":
            return {
                "action": "search_text",
                "tool": "filesystem",
                "arguments": {"query": "is_in_window"},
            }
        elif phase == "SEARCHED":
            return {
                "action": "read_file",
                "tool": "filesystem",
                "arguments": {"path": "event_processor/filters.py"},
            }
        elif phase == "READ":
            return {
                "action": "formulate_hypothesis",
                "tool": "reasoning",
                "arguments": {"phase": "INITIAL"},
            }
        elif phase == "HYPOTHESIZED":
            # First patch attempt: Fix boundary condition only
            return {
                "action": "modify_code",
                "tool": "filesystem",
                "arguments": {
                    "path": "event_processor/filters.py",
                    "old_str": "return window_start <= event.timestamp < window_end",
                    "new_str": "return window_start <= event.timestamp <= window_end",
                },
            }
        elif phase == "PATCHED":
            return {"action": "run_tests", "tool": "test_runner", "arguments": {}}
        elif phase == "TEST_FAILED":
            if patch_attempts < 3:
                return {
                    "action": "recover",
                    "tool": "reasoning",
                    "arguments": {"phase": "RECOVERY"},
                }
            else:
                return {"action": "stop", "tool": "none", "arguments": {"reason": "max_attempts_reached"}}
        elif phase == "RECOVERY_HYPOTHESIZED":
            # Second patch attempt: Fix critical retention condition
            old_block = """        event_rank = SEVERITY_LEVELS.get(event.severity, 0)
        min_rank = SEVERITY_LEVELS.get(min_severity, 1)

        # BUG: Ignores allow_critical_override flag for CRITICAL/FATAL events
        return event_rank >= min_rank"""

            new_block = """        if allow_critical_override and event.severity in ("CRITICAL", "FATAL"):
            return True

        event_rank = SEVERITY_LEVELS.get(event.severity, 0)
        min_rank = SEVERITY_LEVELS.get(min_severity, 1)

        return event_rank >= min_rank"""

            return {
                "action": "modify_code",
                "tool": "filesystem",
                "arguments": {
                    "path": "event_processor/filters.py",
                    "old_str": old_block,
                    "new_str": new_block,
                },
            }
        elif phase == "VERIFY":
            return {"action": "verify", "tool": "verifier", "arguments": {}}

        return {"action": "stop", "tool": "none", "arguments": {}}
