"""Unit tests for GemmaModelAdapter interface and parsing."""

import pytest
from lifecore_swe.agent.gemma_adapter import GemmaModelAdapter


def test_gemma_adapter_model_info():
    adapter = GemmaModelAdapter()
    info = adapter.get_model_info()
    assert info["provider"] == "Google"
    assert "gemma" in info["model_name"]
    assert info["is_development_adapter"] is False
    assert "input_tokens" in info["context_length"]
    assert info["context_length"]["input_tokens"] == 262144


def test_gemma_adapter_json_parsing():
    adapter = GemmaModelAdapter()
    raw_fence = "```json\n{\"action\": \"list_files\", \"tool\": \"filesystem\"}\n```"
    parsed = adapter._parse_json(raw_fence)
    assert parsed["action"] == "list_files"

    raw_array = "[{\"thought_summary\": \"read\", \"next_action\": \"read_file\"}]"
    parsed_arr = adapter._parse_json(raw_array)
    assert parsed_arr[0]["next_action"] == "read_file"
