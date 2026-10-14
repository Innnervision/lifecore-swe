"""Tests for agent state, model adapter, and planner transitions."""

from lifecore_swe.agent.state import AgentState
from lifecore_swe.agent.planner import PatchLoopPlanner
from lifecore_swe.agent.model_adapter import RuleBasedDevAdapter


def test_agent_state_initialization():
    state = AgentState(task="Fix bug in repository")
    assert state.task == "Fix bug in repository"
    assert state.recovery_attempts == 0
    d = state.to_dict()
    assert "current_phase" in d
    assert d["current_phase"] == "INIT"


def test_planner_transitions():
    planner = PatchLoopPlanner()
    state = AgentState()

    # Step transitions
    phase = planner.transition("INIT", "list_files", ["a.py"], state.to_dict())
    assert phase == "LISTED"

    phase = planner.transition(phase, "search_text", [], state.to_dict())
    assert phase == "SEARCHED"

    phase = planner.transition(phase, "read_file", "content", state.to_dict())
    assert phase == "READ"

    phase = planner.transition(phase, "formulate_hypothesis", {}, state.to_dict())
    assert phase == "HYPOTHESIZED"

    phase = planner.transition(phase, "modify_code", {"success": True}, state.to_dict())
    assert phase == "PATCHED"

    # Test failure leads to TEST_FAILED
    phase = planner.transition(phase, "run_tests", {"passed": False}, state.to_dict())
    assert phase == "TEST_FAILED"

    # Recovery leads to RECOVERY_HYPOTHESIZED
    phase = planner.transition(phase, "recover", {}, state.to_dict())
    assert phase == "RECOVERY_HYPOTHESIZED"

    # Patch and test passing leads to VERIFY
    phase = planner.transition(phase, "modify_code", {"success": True}, state.to_dict())
    assert phase == "PATCHED"

    phase = planner.transition(phase, "run_tests", {"passed": True}, state.to_dict())
    assert phase == "VERIFY"

    # Verification leads to COMPLETED
    phase = planner.transition(phase, "verify", {"success": True}, state.to_dict())
    assert phase == "COMPLETED"


def test_model_adapter_contract():
    adapter = RuleBasedDevAdapter()
    info = adapter.get_model_info()
    assert info["is_development_adapter"] is True
    assert "RuleBasedDevAdapter" in info["model_name"]

    hyp = adapter.reason("test task", {"phase": "INITIAL"})
    assert "hypothesis" in hyp
    assert "evidence" in hyp
    assert "confidence" in hyp
    assert "files_involved" in hyp
    assert isinstance(hyp["confidence"], float)
    assert 0.0 <= hyp["confidence"] <= 1.0
