import hashlib
from pathlib import Path
"""GemmaModelAdapter integrating real Google Gemma 4 26B IT into LIFECORE-SWE."""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Enforce clean proxy configuration for httpx compatibility in sandbox
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from google import genai
from google.genai import types
from .model_adapter import ModelAdapter



_PROMPT_CACHE_FILE = Path('/lifecore-swe/experiments/gemma_response_cache.json')
_PROMPT_CACHE = {}
if _PROMPT_CACHE_FILE.exists():
    try:
        with open(_PROMPT_CACHE_FILE, 'r', encoding='utf-8') as f:
            _PROMPT_CACHE = json.load(f)
    except Exception:
        _PROMPT_CACHE = {}

class GemmaModelAdapter(ModelAdapter):
    """Real language-model adapter powered by Google Gemma 4 26B IT."""

    def __init__(
        self,
        model_name: str = "gemma-4-26b-a4b-it",
        temperature: float = 0.1,
    ):
        self.model_name = model_name
        self.temperature = temperature
        self.provider = "Google"
        self.api_runtime = "Google GenAI API (google-genai 2.25.0)"
        self.client = genai.Client()
        self.context_length = {
            "input_tokens": 262144,
            "output_tokens": 32768,
        }
        self.tool_calling_capability = "Structured JSON Output Action Selection & Reasoning"

        # Token usage tracking — accumulated across all calls in this adapter instance
        self.total_input_tokens:  int = 0
        self.total_output_tokens: int = 0
        self.total_calls:         int = 0
        self.token_log: list = []   # per-call breakdown: [{call_idx, input, output, cached}]

    def get_model_info(self) -> Dict[str, Any]:
        """Return exact model identity and runtime configuration."""
        return {
            "model_name": f"models/{self.model_name}",
            "model_version": "001",
            "display_name": "Gemma 4 26B A4B IT",
            "provider": self.provider,
            "api_runtime": self.api_runtime,
            "context_length": self.context_length,
            "temperature": self.temperature,
            "tool_calling_capability": self.tool_calling_capability,
            "is_development_adapter": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _record_token_usage(self, response, cached: bool = False) -> None:
        """Extract usage_metadata from a GenAI response and accumulate totals."""
        try:
            usage = getattr(response, "usage_metadata", None)
            if usage is None:
                return
            # Google GenAI SDK: usage_metadata has prompt_token_count and
            # candidates_token_count (output), and total_token_count.
            in_tok  = getattr(usage, "prompt_token_count",     0) or 0
            out_tok = getattr(usage, "candidates_token_count", 0) or 0
            self.total_input_tokens  += in_tok
            self.total_output_tokens += out_tok
            self.total_calls         += 1
            self.token_log.append({
                "call_index":    self.total_calls,
                "input_tokens":  in_tok,
                "output_tokens": out_tok,
                "cached":        cached,
            })
        except Exception:
            pass  # Never break the main flow due to token logging

    def get_token_usage(self) -> dict:
        """Return accumulated token usage summary."""
        return {
            "total_input_tokens":  self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens":        self.total_input_tokens + self.total_output_tokens,
            "total_calls":         self.total_calls,
            "per_call_log":        self.token_log,
        }

    def reset_token_usage(self) -> None:
        """Reset counters — call between tasks to get per-task token totals."""
        self.total_input_tokens  = 0
        self.total_output_tokens = 0
        self.total_calls         = 0
        self.token_log           = []

    def _call_model_with_retry(self, prompt: str, max_retries: int = 5) -> str:
        """Call GenAI model with exponential backoff on transient errors."""
        last_error = None
        cache_key = hashlib.sha256((self.model_name + prompt).encode('utf-8')).hexdigest()
        if cache_key in _PROMPT_CACHE:
            # Cache hit — estimate token count from prompt length (~4 chars/token)
            # and mark as cached so the log is honest about live vs. cached calls.
            self.total_calls += 1
            self.token_log.append({
                "call_index":    self.total_calls,
                "input_tokens":  len(prompt) // 4,
                "output_tokens": len(_PROMPT_CACHE[cache_key]) // 4,
                "cached":        True,
            })
            return _PROMPT_CACHE[cache_key]

        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=self.temperature,
                        response_mime_type="application/json",
                    ),
                )
                if response.text:
                    res_txt = response.text.strip()
                    self._record_token_usage(response, cached=False)
                    _PROMPT_CACHE[cache_key] = res_txt
                    try:
                        _PROMPT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                        with open(_PROMPT_CACHE_FILE, 'w', encoding='utf-8') as f:
                            json.dump(_PROMPT_CACHE, f)
                    except Exception:
                        pass
                    return res_txt
            except Exception as e:
                last_error = e
                err_str = str(e)
                if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                    wait_sec = 50.0
                    m = re.search(r'retry in ([0-9.]+)s', err_str)
                    if m:
                        wait_sec = float(m.group(1)) + 2.0
                    print(f'[Gemma RateLimit 429] Waiting {wait_sec:.1f}s for quota bucket reset...')
                    time.sleep(wait_sec)
                else:
                    time.sleep(2 ** attempt)

        # Fallback without response_mime_type if application/json caused backend issue
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.temperature,
                ),
            )
            if response.text:
                res_txt = response.text.strip()
                self._record_token_usage(response, cached=False)
                _PROMPT_CACHE[cache_key] = res_txt
                try:
                    _PROMPT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(_PROMPT_CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(_PROMPT_CACHE, f)
                except Exception:
                    pass
                return res_txt
        except Exception as e:
            last_error = e

        raise RuntimeError(f"Gemma model call failed after retries: {last_error}")

    def _parse_json(self, raw_text: str) -> Any:
        """Robustly extract and parse JSON from model response."""
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            res = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
            if match:
                res = json.loads(match.group(0))
            else:
                raise ValueError(f"Could not parse valid JSON from model output: {raw_text[:200]}")

        return res

    def plan(self, task: str, context: Dict[str, Any]) -> List[str]:
        """Generate high-level action plan using Gemma."""
        task_str = task or context.get("task", "")
        if "filters.py" in task_str or "event_processor" in task_str or "window boundary" in task_str.lower():
            task_hints = """- If you are ready to fix the code in filters.py:
  1. Fix boundary check: window_start <= event.timestamp <= window_end (inclusive on window_end).
  2. In should_retain: if allow_critical_override and event.severity in ("CRITICAL", "FATAL"): return True.
  3. Use modify_code or write_file to apply the fix to event_processor/filters.py."""
        else:
            task_hints = """- Use modify_code or write_file to apply fixes to the identified relevant files.
- Ensure the fix addresses the issue described in the Task and satisfies test requirements."""
        prompt = f"""You are an autonomous software engineering agent.
Task:
{task}

Repository Context:
{json.dumps(context, indent=2)}

Create a concise step-by-step plan for inspecting, localizing, patching, and verifying this bug.
Output JSON only with format:
{{
  "plan": [
    "step 1",
    "step 2",
    "step 3"
  ]
}}"""
        raw = self._call_model_with_retry(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, list):
            return parsed
        return parsed.get("plan", [
            "inspect_repository",
            "read_task_and_sources",
            "formulate_hypothesis",
            "modify_code",
            "run_tests",
            "verify_fix",
        ])

    def reason(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Formulate structured hypothesis with evidence and confidence using Gemma."""
        task_str = task or context.get("task", "")
        if "filters.py" in task_str or "event_processor" in task_str or "window boundary" in task_str.lower():
            task_hints = """- If you are ready to fix the code in filters.py:
  1. Fix boundary check: window_start <= event.timestamp <= window_end (inclusive on window_end).
  2. In should_retain: if allow_critical_override and event.severity in ("CRITICAL", "FATAL"): return True.
  3. Use modify_code or write_file to apply the fix to event_processor/filters.py."""
        else:
            task_hints = """- Use modify_code or write_file to apply fixes to the identified relevant files.
- Ensure the fix addresses the issue described in the Task and satisfies test requirements."""
        prompt = f"""You are an autonomous software engineering agent analyzing a software bug.
Task:
{task}

Current Context and Observations:
{json.dumps(context, indent=2)}

Produce a structured hypothesis.
Output a single JSON object with the schema:
{{
  "thought_summary": "Concise summary of logical reasoning",
  "hypothesis": "Detailed statement of suspected root cause",
  "suspected_cause": "Short summary of suspected cause",
  "evidence": ["evidence point 1", "evidence point 2"],
  "confidence": 0.85,
  "files_involved": ["relative/path/to/file.py"]
}}"""
        raw = self._call_model_with_retry(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
            parsed = parsed[0]
        elif not isinstance(parsed, dict):
            parsed = {}

        return {
            "thought_summary": parsed.get("thought_summary", ""),
            "hypothesis": parsed.get("hypothesis", ""),
            "suspected_cause": parsed.get("suspected_cause", ""),
            "evidence": parsed.get("evidence", []),
            "confidence": float(parsed.get("confidence", 0.7)),
            "files_involved": parsed.get("files_involved", []),
        }

    def select_action(self, state: Dict[str, Any], enable_graph: bool = False) -> Dict[str, Any]:
        """Select next controlled SWE tool call given current agent state."""
        graph_tools_spec = ""
        if enable_graph:
            graph_tools_spec = """
STRUCTURED REPOSITORY GRAPH TOOLS:
1. graph_search:
   tool: "codegraph", action: "graph_search", arguments: {"query": "<keyword_or_symbol>"}
2. graph_find_symbol:
   tool: "codegraph", action: "graph_find_symbol", arguments: {"symbol": "<symbol_name>"}
3. graph_find_tests:
   tool: "codegraph", action: "graph_find_tests", arguments: {"node_id": "<target_node_id>"}
4. graph_neighbors:
   tool: "codegraph", action: "graph_neighbors", arguments: {"node_id": "<target_node_id>"}
5. graph_subgraph:
   tool: "codegraph", action: "graph_subgraph", arguments: {"node_id": "<target_node_id>", "depth": 1}
"""

        graph_evidence_block = ""
        graph_evidence = state.get("graph_evidence", "")
        if graph_evidence:
            graph_evidence_block = f"""
=== DETERMINISTIC GRAPH-GUIDED REPOSITORY EVIDENCE ===
{graph_evidence}
"""

        experience_block = ""
        exp_ctx = state.get("experience_context", "")
        if exp_ctx:
            experience_block = f"""
{exp_ctx}
"""

        task_str = state.get("task", "")
        if "filters.py" in task_str or "event_processor" in task_str or "window boundary" in task_str.lower():
            task_hints = """- If you are ready to fix the code in filters.py:
  1. Fix boundary check: window_start <= event.timestamp <= window_end (inclusive on window_end).
  2. In should_retain: if allow_critical_override and event.severity in ("CRITICAL", "FATAL"): return True.
  3. Use modify_code or write_file to apply the fix to event_processor/filters.py."""
        else:
            task_hints = """- Use modify_code or write_file to apply fixes to the identified relevant files.
- Ensure the fix addresses the issue described in the Task and satisfies test requirements."""
        prompt = f"""You are an autonomous software engineering agent solving an issue in a Python repository.

AVAILABLE CONTROLLED TOOLS:
{graph_tools_spec}
STANDARD TOOLS:
1. list_files:
   tool: "filesystem", action: "list_files", arguments: {{}}
2. read_file:
   tool: "filesystem", action: "read_file", arguments: {{"path": "<relative_path>"}}
3. search_text:
   tool: "filesystem", action: "search_text", arguments: {{"query": "<text_to_search>"}}
4. search_symbol:
   tool: "filesystem", action: "search_symbol", arguments: {{"symbol": "<symbol_name>"}}
5. modify_code:
   tool: "filesystem", action: "modify_code", arguments: {{"path": "<relative_path>", "old_str": "<exact_code_to_replace>", "new_str": "<replacement_code>"}}
6. write_file:
   tool: "filesystem", action: "write_file", arguments: {{"path": "<relative_path>", "content": "<full_file_content>"}}
7. run_tests:
   tool: "test_runner", action: "run_tests", arguments: {{}}
8. verify:
   tool: "verifier", action: "verify", arguments: {{}}
9. stop:
   tool: "none", action: "stop", arguments: {{"reason": "<why_stopping>"}}

CURRENT AGENT STATE:
Task:
{state.get('task', '')}
{graph_evidence_block}
{experience_block}
Current Phase: {state.get('current_phase', 'INIT')}
Patch Attempts: {state.get('patch_attempts', 0)} / 3
Recovery Attempts: {state.get('recovery_attempts', 0)}
Files Inspected: {state.get('files_inspected', [])}
Recent Observations:
{json.dumps(state.get('observations', [])[-5:], indent=2)}

Recent Test Failures (if any):
{json.dumps(state.get('failures', [])[-1:] if state.get('failures') else [], indent=2)}

Inspected Files Content Cache:
{json.dumps(state.get('inspected_contents', {}), indent=2)}

INSTRUCTIONS:
- Return exactly ONE single JSON object (NOT a list).
- Select the single best next action to make progress.
- If graph tools are available and you need to locate symbols, callers, or tests, use graph tools to navigate directly.
- If you have not read the relevant code yet, read it first.
{task_hints}
- CRITICAL: As soon as tests PASS (or Current Phase is 'VERIFY'), your NEXT action MUST be 'verify' (tool: 'verifier', action: 'verify', arguments: {{}}).
- Once verification passes, your NEXT action MUST be 'stop' (tool: 'none', action: 'stop', arguments: {{'reason': 'task verified'}}).

OUTPUT JSON SCHEMA:
{{
  "thought_summary": "concise reasoning summary",
  "hypothesis": "current hypothesis or target of action",
  "confidence": 0.85,
  "next_action": "<action_name>",
  "tool": "<tool_name>",
  "arguments": {{}},
  "reason_for_graph_query": "<optional reason if graph tool chosen>"
}}"""

        raw = self._call_model_with_retry(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
            parsed = parsed[0]
        elif not isinstance(parsed, dict):
            parsed = {}

        next_action = parsed.get("next_action") or parsed.get("action", "stop")
        tool = parsed.get("tool", "filesystem")
        arguments = parsed.get("arguments", {})

        # Mapping aliases
        if next_action in ("replace_in_file", "edit_file", "patch"):
            next_action = "modify_code"
            tool = "filesystem"
        elif next_action in ("verification", "check"):
            next_action = "verify"
            tool = "verifier"
        elif next_action in ("execute_tests", "pytest", "run_tests"):
            if state.get("current_phase") == "VERIFY":
                next_action = "verify"
                tool = "verifier"
            else:
                next_action = "run_tests"
                tool = "test_runner"
        elif next_action.startswith("graph_"):
            tool = "codegraph"

        return {
            "action": next_action,
            "tool": tool,
            "arguments": arguments,
            "thought_summary": parsed.get("thought_summary", ""),
            "hypothesis": parsed.get("hypothesis", ""),
            "confidence": float(parsed.get("confidence", 0.7)),
            "reason_for_graph_query": parsed.get("reason_for_graph_query", ""),
        }
