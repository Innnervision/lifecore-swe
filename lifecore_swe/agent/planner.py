"""Planner coordinating patch loop state transitions."""

from typing import Dict, Any


class PatchLoopPlanner:
    """Manages progression through the SWE patch loop."""

    MAX_PATCH_ATTEMPTS = 3

    def transition(self, current_phase: str, action: str, result: Any, state: Dict[str, Any]) -> str:
        """Determine next phase in the loop."""
        if action == "list_files":
            return "LISTED"
        elif action == "search_text" or action == "search_symbol":
            return "SEARCHED"
        elif action == "read_file":
            return "READ"
        elif action == "formulate_hypothesis":
            return "HYPOTHESIZED"
        elif action == "recover":
            return "RECOVERY_HYPOTHESIZED"
        elif action == "modify_code":
            return "PATCHED"
        elif action == "run_tests":
            passed = result.get("passed", False) if isinstance(result, dict) else False
            if passed:
                return "VERIFY"
            else:
                return "TEST_FAILED"
        elif action == "verify":
            return "COMPLETED"
        elif action == "stop":
            return "STOPPED"

        return current_phase
