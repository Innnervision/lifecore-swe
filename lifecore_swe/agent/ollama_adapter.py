"""
OllamaModelAdapter — drop-in replacement for GemmaModelAdapter using local Ollama.

DEFAULT MODEL: gemma4:31b
  This is the exact model used in the Google DeepMind Gemma 4 Developer Agent
  competition (gemma-4-31b-it-qat-w4a16-ct), available free via Ollama.

Requires Ollama to be running locally:
  1. Install: https://ollama.com/download
  2. Pull the competition model: ollama pull gemma4:31b   (~20 GB, needs 24 GB RAM)
     Or a lighter alternative:   ollama pull gemma4:12b  (~8 GB, needs 12 GB RAM)
  3. Start server: ollama serve   (runs on http://localhost:11434 by default)

Usage in benchmark scripts:
    from lifecore_swe.agent.ollama_adapter import OllamaModelAdapter
    adapter = OllamaModelAdapter()                    # uses gemma4:31b
    adapter = OllamaModelAdapter(model_name="gemma4:12b")  # lighter option

Supported models (free, local, ranked by competition relevance):
  gemma4:31b    — 20 GB  COMPETITION MODEL (gemma-4-31b-it-qat-w4a16-ct)
  gemma4:12b    — 8 GB   Good quality, half the RAM
  gemma4:4b     — 3 GB   Fast, lower quality
  gemma2:27b    — 16 GB  Previous generation, good fallback
  gemma2:9b     — 5.5 GB Lightweight fallback
  codellama:7b  — 3.8 GB Code-specialized fallback

The adapter implements the same ModelAdapter interface as GemmaModelAdapter,
including token usage tracking (estimated from prompt/response length).
"""

import hashlib
import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model_adapter import ModelAdapter

_PROMPT_CACHE_FILE = Path("experiments/ollama_response_cache.json")
_PROMPT_CACHE: Dict[str, str] = {}
if _PROMPT_CACHE_FILE.exists():
    try:
        with open(_PROMPT_CACHE_FILE, "r", encoding="utf-8") as f:
            _PROMPT_CACHE = json.load(f)
    except Exception:
        _PROMPT_CACHE = {}

# ~4 characters per token — rough but consistent estimate for token logging
_CHARS_PER_TOKEN = 4


class OllamaModelAdapter(ModelAdapter):
    """
    Local model adapter using Ollama REST API.
    Default model: gemma4:31b — the exact competition model (free via Ollama).
    Drop-in replacement for GemmaModelAdapter — same interface, zero API cost.
    """

    # Competition model identifier — matches gemma-4-31b-it-qat-w4a16-ct
    COMPETITION_MODEL = "gemma4:31b"

    def __init__(
        self,
        model_name: str = "gemma4:31b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        timeout: int = 180,
    ):
        self.model_name   = model_name
        self.base_url     = base_url.rstrip("/")
        self.temperature  = temperature
        self.timeout      = timeout
        self.provider     = "Ollama (local)"
        self.api_runtime  = f"Ollama local inference ({model_name})"
        self.context_length = {"input_tokens": 8192, "output_tokens": 4096}
        self.tool_calling_capability = "Structured JSON Output via Ollama generate"

        # Token usage tracking (mirrors GemmaModelAdapter interface)
        self.total_input_tokens:  int  = 0
        self.total_output_tokens: int  = 0
        self.total_calls:         int  = 0
        self.token_log:           list = []

    # ── ModelAdapter interface ─────────────────────────────────────────────

    def get_model_info(self) -> Dict[str, Any]:
        # Map Ollama short names to canonical competition identifiers
        canonical = {
            "gemma4:31b":  "gemma-4-31b-it-qat-w4a16-ct",
            "gemma4:12b":  "gemma-4-12b-it",
            "gemma4:4b":   "gemma-4-4b-it",
            "gemma2:27b":  "gemma-2-27b-it",
            "gemma2:9b":   "gemma-2-9b-it",
            "gemma2:2b":   "gemma-2-2b-it",
        }
        canonical_name = canonical.get(self.model_name, self.model_name)
        return {
            "model_name":              canonical_name,
            "ollama_model_name":       self.model_name,
            "model_version":           "local-qat",
            "display_name":            f"Gemma 4 31B IT QAT (via Ollama)",
            "provider":                self.provider,
            "api_runtime":             self.api_runtime,
            "context_length":          self.context_length,
            "temperature":             self.temperature,
            "tool_calling_capability": self.tool_calling_capability,
            "is_development_adapter":  False,
            "is_competition_model":    self.model_name == self.COMPETITION_MODEL,
            "timestamp":               datetime.now(timezone.utc).isoformat(),
        }

    def plan(self, task: str, context: Dict[str, Any]) -> List[str]:
        prompt = f"""You are an autonomous software engineering agent.
Task:
{task}

Repository Context:
{json.dumps(context, indent=2)}

Create a concise step-by-step plan for inspecting, localizing, patching, and
verifying this bug. Output JSON only:
{{
  "plan": ["step 1", "step 2", "step 3"]
}}"""
        raw    = self._call_with_retry(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, list):
            return parsed
        return parsed.get("plan", [
            "inspect_repository", "read_task_and_sources",
            "formulate_hypothesis", "modify_code", "run_tests", "verify_fix",
        ])

    def reason(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""You are an autonomous software engineering agent analyzing a bug.
Task:
{task}

Current Context:
{json.dumps(context, indent=2)}

Output a single JSON object:
{{
  "thought_summary": "...",
  "hypothesis": "...",
  "suspected_cause": "...",
  "evidence": ["..."],
  "confidence": 0.85,
  "files_involved": ["relative/path.py"]
}}"""
        raw    = self._call_with_retry(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if not isinstance(parsed, dict):
            parsed = {}
        return {
            "thought_summary": parsed.get("thought_summary", ""),
            "hypothesis":      parsed.get("hypothesis", ""),
            "suspected_cause": parsed.get("suspected_cause", ""),
            "evidence":        parsed.get("evidence", []),
            "confidence":      float(parsed.get("confidence", 0.7)),
            "files_involved":  parsed.get("files_involved", []),
        }

    def select_action(self, state: Dict[str, Any],
                      enable_graph: bool = False) -> Dict[str, Any]:
        graph_evidence = state.get("graph_evidence", "")
        graph_block    = f"\n=== GRAPH EVIDENCE ===\n{graph_evidence}\n" if graph_evidence else ""
        exp_context    = state.get("experience_context", "")
        exp_block      = f"\n{exp_context}\n" if exp_context else ""

        prompt = f"""You are an autonomous software engineering agent.

AVAILABLE TOOLS:
1. list_files        — tool: filesystem, action: list_files, arguments: {{}}
2. read_file         — tool: filesystem, action: read_file, arguments: {{"path": "<rel_path>"}}
3. search_text       — tool: filesystem, action: search_text, arguments: {{"query": "<text>"}}
4. search_symbol     — tool: filesystem, action: search_symbol, arguments: {{"symbol": "<name>"}}
5. modify_code       — tool: filesystem, action: modify_code, arguments: {{"path": "<rel>", "old_str": "<old>", "new_str": "<new>"}}
6. write_file        — tool: filesystem, action: write_file, arguments: {{"path": "<rel>", "content": "<full_content>"}}
7. run_tests         — tool: test_runner, action: run_tests, arguments: {{}}
8. verify            — tool: verifier, action: verify, arguments: {{}}
9. stop              — tool: none, action: stop, arguments: {{"reason": "<why>"}}

CURRENT STATE:
Task: {state.get('task', '')}
{graph_block}{exp_block}
Phase: {state.get('current_phase', 'INIT')}
Patch attempts: {state.get('patch_attempts', 0)}/3
Files inspected: {state.get('files_inspected', [])}
Recent observations: {json.dumps(state.get('observations', [])[-3:], indent=2)}
Recent failures: {json.dumps(state.get('failures', [])[-1:], indent=2)}

INSTRUCTIONS:
- Return exactly ONE JSON object (not a list).
- Read the relevant file before editing it.
- Use modify_code to apply targeted fixes.
- Once tests PASS, immediately call verify.
- Once verification passes, call stop.

OUTPUT SCHEMA:
{{
  "thought_summary": "...",
  "hypothesis": "...",
  "confidence": 0.85,
  "next_action": "<action>",
  "tool": "<tool>",
  "arguments": {{}}
}}"""

        raw    = self._call_with_retry(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if not isinstance(parsed, dict):
            parsed = {}

        next_action = parsed.get("next_action") or parsed.get("action", "stop")
        tool        = parsed.get("tool", "filesystem")
        arguments   = parsed.get("arguments", {})

        # Normalize aliases
        action_map = {
            "replace_in_file": "modify_code", "edit_file": "modify_code",
            "patch": "modify_code", "verification": "verify",
            "check": "verify", "execute_tests": "run_tests", "pytest": "run_tests",
        }
        next_action = action_map.get(next_action, next_action)

        if next_action in ("run_tests", "verify") and state.get("current_phase") == "VERIFY":
            next_action = "verify"
            tool = "verifier"

        return {
            "thought_summary": parsed.get("thought_summary", ""),
            "hypothesis":      parsed.get("hypothesis", ""),
            "confidence":      float(parsed.get("confidence", 0.7)),
            "next_action":     next_action,
            "tool":            tool,
            "arguments":       arguments,
        }

    # ── Token usage (mirrors GemmaModelAdapter) ───────────────────────────

    def get_token_usage(self) -> Dict[str, Any]:
        return {
            "total_input_tokens":  self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens":        self.total_input_tokens + self.total_output_tokens,
            "total_calls":         self.total_calls,
            "per_call_log":        self.token_log,
        }

    def reset_token_usage(self) -> None:
        self.total_input_tokens  = 0
        self.total_output_tokens = 0
        self.total_calls         = 0
        self.token_log           = []

    def _record_tokens(self, prompt: str, response: str, cached: bool) -> None:
        in_tok  = len(prompt)   // _CHARS_PER_TOKEN
        out_tok = len(response) // _CHARS_PER_TOKEN
        self.total_input_tokens  += in_tok
        self.total_output_tokens += out_tok
        self.total_calls         += 1
        self.token_log.append({
            "call_index":    self.total_calls,
            "input_tokens":  in_tok,
            "output_tokens": out_tok,
            "cached":        cached,
        })

    # ── Ollama HTTP call ──────────────────────────────────────────────────

    def _call_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        cache_key = hashlib.sha256(
            (self.model_name + prompt).encode("utf-8")).hexdigest()
        if cache_key in _PROMPT_CACHE:
            self._record_tokens(prompt, _PROMPT_CACHE[cache_key], cached=True)
            return _PROMPT_CACHE[cache_key]

        url     = f"{self.base_url}/api/generate"
        payload = json.dumps({
            "model":  self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": 1024,
            },
            "format": "json",
        }).encode("utf-8")

        last_err = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body   = json.loads(resp.read().decode("utf-8"))
                    result = body.get("response", "").strip()
                    if result:
                        self._record_tokens(prompt, result, cached=False)
                        _PROMPT_CACHE[cache_key] = result
                        try:
                            _PROMPT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                            with open(_PROMPT_CACHE_FILE, "w", encoding="utf-8") as f:
                                json.dump(_PROMPT_CACHE, f)
                        except Exception:
                            pass
                        return result
            except urllib.error.URLError as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        raise RuntimeError(
            f"Ollama call failed after {max_retries} attempts. "
            f"Is Ollama running? (ollama serve)\n"
            f"Last error: {last_err}"
        )

    def _parse_json(self, raw: str) -> Any:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            lines = lines[1:] if lines[0].startswith("```") else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
        return {}

    # ── Utility ───────────────────────────────────────────────────────────

    @staticmethod
    def check_ollama_running(base_url: str = "http://localhost:11434") -> bool:
        """Return True if Ollama server is reachable."""
        try:
            with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3):
                return True
        except Exception:
            return False

    @staticmethod
    def list_available_models(
            base_url: str = "http://localhost:11434") -> List[str]:
        """Return list of locally available model names."""
        try:
            with urllib.request.urlopen(
                    f"{base_url}/api/tags", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
