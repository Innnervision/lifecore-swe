"""
KaggleModelAdapter — runs gemma-4-31b-it-qat-w4a16-ct inside a Kaggle notebook.

This adapter loads the competition model directly from Kaggle Models storage
(available at /kaggle/input/gemma4/ inside Kaggle notebooks) using the
transformers + bitsandbytes pipeline, or via the Kaggle-provided vLLM engine.

HOW TO USE IN A KAGGLE NOTEBOOK:
  1. In the notebook sidebar, click "Add data" → Models
  2. Search for "gemma 4 31b" → select "google/gemma-4/transformers/gemma-4-31b-it"
     or the QAT variant "google/gemma-4/transformers/gemma-4-31b-it-qat-w4a16"
  3. The model weights will be available at /kaggle/input/gemma4/
  4. In your notebook cell:

     from lifecore_swe.agent.kaggle_adapter import KaggleModelAdapter
     adapter = KaggleModelAdapter()
     # Then run the benchmark as normal

ALTERNATIVELY — use Kaggle's hosted inference API (no GPU quota needed):
     adapter = KaggleModelAdapter(use_inference_api=True,
                                  kaggle_username="your_username",
                                  kaggle_key="your_key")

RAM/GPU requirements on Kaggle:
  - gemma-4-31b-it-qat-w4a16: fits in 1x T4 GPU (16 GB) with 4-bit quantization
  - gemma-4-12b-it: fits in 1x T4 GPU (16 GB) in bfloat16
  - gemma-4-4b-it: fits in 1x T4 GPU even in float32
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model_adapter import ModelAdapter

# Token estimate (4 chars per token — used when exact count unavailable)
_CHARS_PER_TOKEN = 4

# Standard Kaggle model paths
_KAGGLE_MODEL_PATHS = {
    "gemma-4-31b-it-qat": "/kaggle/input/gemma4/transformers/gemma-4-31b-it-qat-w4a16/1",
    "gemma-4-31b-it":     "/kaggle/input/gemma4/transformers/gemma-4-31b-it/1",
    "gemma-4-12b-it":     "/kaggle/input/gemma4/transformers/gemma-4-12b-it/1",
    "gemma-4-4b-it":      "/kaggle/input/gemma4/transformers/gemma-4-4b-it/1",
}


class KaggleModelAdapter(ModelAdapter):
    """
    Runs gemma-4-31b-it-qat-w4a16-ct inside a Kaggle notebook.
    Loads model weights from /kaggle/input/ (Kaggle Models storage).
    Falls back to Kaggle Inference API if local weights unavailable.
    """

    COMPETITION_MODEL_ID = "google/gemma-4/transformers/gemma-4-31b-it-qat-w4a16/1"

    def __init__(
        self,
        model_key:          str  = "gemma-4-31b-it-qat",
        temperature:        float = 0.1,
        max_new_tokens:     int   = 1024,
        use_inference_api:  bool  = False,
        kaggle_username:    Optional[str] = None,
        kaggle_key:         Optional[str] = None,
        device:             str  = "auto",
    ):
        self.model_key         = model_key
        self.temperature       = temperature
        self.max_new_tokens    = max_new_tokens
        self.use_inference_api = use_inference_api
        self.kaggle_username   = kaggle_username or os.environ.get("KAGGLE_USERNAME")
        self.kaggle_key        = kaggle_key       or os.environ.get("KAGGLE_KEY")
        self.device            = device

        # Token usage tracking
        self.total_input_tokens:  int  = 0
        self.total_output_tokens: int  = 0
        self.total_calls:         int  = 0
        self.token_log:           list = []

        # Model pipeline (loaded lazily on first call)
        self._pipeline = None
        self._tokenizer = None

        model_path = _KAGGLE_MODEL_PATHS.get(model_key, "")
        self._model_path = model_path

    # ── ModelAdapter interface ─────────────────────────────────────────────

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name":              self.model_key,
            "model_path":              self._model_path,
            "competition_model_id":    self.COMPETITION_MODEL_ID,
            "model_version":           "qat-w4a16",
            "display_name":            "Gemma 4 31B IT QAT W4A16 (Kaggle)",
            "provider":                "Google / Kaggle Models",
            "api_runtime":             "HuggingFace Transformers / Kaggle GPU",
            "context_length":          {"input_tokens": 131072, "output_tokens": 8192},
            "temperature":             self.temperature,
            "tool_calling_capability": "Structured JSON Output",
            "is_development_adapter":  False,
            "is_competition_model":    True,
            "timestamp":               datetime.now(timezone.utc).isoformat(),
        }

    def plan(self, task: str, context: Dict[str, Any]) -> List[str]:
        prompt = self._build_prompt(
            f"""You are an autonomous software engineering agent.
Task:
{task}

Repository Context:
{json.dumps(context, indent=2)}

Create a concise step-by-step plan. Output JSON only:
{{"plan": ["step 1", "step 2", "step 3"]}}"""
        )
        raw    = self._generate(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, list):
            return parsed
        return parsed.get("plan", [
            "inspect_repository", "read_task_and_sources",
            "formulate_hypothesis", "modify_code", "run_tests", "verify_fix",
        ])

    def reason(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._build_prompt(
            f"""You are an autonomous software engineering agent analyzing a bug.
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
        )
        raw    = self._generate(prompt)
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

        prompt = self._build_prompt(
            f"""You are an autonomous software engineering agent solving a Python bug.

AVAILABLE TOOLS:
1. list_files   — tool: filesystem, action: list_files, arguments: {{}}
2. read_file    — tool: filesystem, action: read_file, arguments: {{"path": "<rel>"}}
3. search_text  — tool: filesystem, action: search_text, arguments: {{"query": "<text>"}}
4. modify_code  — tool: filesystem, action: modify_code, arguments: {{"path": "<rel>", "old_str": "<old>", "new_str": "<new>"}}
5. write_file   — tool: filesystem, action: write_file, arguments: {{"path": "<rel>", "content": "<full>"}}
6. run_tests    — tool: test_runner, action: run_tests, arguments: {{}}
7. verify       — tool: verifier, action: verify, arguments: {{}}
8. stop         — tool: none, action: stop, arguments: {{"reason": "<why>"}}

CURRENT STATE:
Task: {state.get('task', '')}
{graph_block}{exp_block}
Phase: {state.get('current_phase', 'INIT')}
Patch attempts: {state.get('patch_attempts', 0)}/3
Files inspected: {state.get('files_inspected', [])}
Recent observations: {json.dumps(state.get('observations', [])[-3:], indent=2)}
Recent failures: {json.dumps(state.get('failures', [])[-1:], indent=2)}

INSTRUCTIONS:
- Return exactly ONE JSON object.
- Read the relevant file before editing.
- Use modify_code to apply targeted fixes.
- Once tests PASS, immediately call verify.
- Once verify passes, call stop.

OUTPUT SCHEMA:
{{
  "thought_summary": "...",
  "hypothesis": "...",
  "confidence": 0.85,
  "next_action": "<action>",
  "tool": "<tool>",
  "arguments": {{}}
}}"""
        )
        raw    = self._generate(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if not isinstance(parsed, dict):
            parsed = {}

        next_action = parsed.get("next_action") or parsed.get("action", "stop")
        tool        = parsed.get("tool", "filesystem")
        arguments   = parsed.get("arguments", {})

        action_map = {
            "replace_in_file": "modify_code", "edit_file": "modify_code",
            "patch": "modify_code", "verification": "verify",
            "execute_tests": "run_tests", "pytest": "run_tests",
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

    # ── Token usage ────────────────────────────────────────────────────────

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

    def _record_tokens(self, prompt: str, response: str,
                       in_tok: Optional[int] = None,
                       out_tok: Optional[int] = None) -> None:
        in_tok  = in_tok  or (len(prompt)   // _CHARS_PER_TOKEN)
        out_tok = out_tok or (len(response) // _CHARS_PER_TOKEN)
        self.total_input_tokens  += in_tok
        self.total_output_tokens += out_tok
        self.total_calls         += 1
        self.token_log.append({
            "call_index":    self.total_calls,
            "input_tokens":  in_tok,
            "output_tokens": out_tok,
            "cached":        False,
        })

    # ── Gemma 4 instruction format ─────────────────────────────────────────

    def _build_prompt(self, user_text: str) -> str:
        """Format prompt using Gemma 4 instruction template."""
        return (
            "<start_of_turn>user\n"
            f"{user_text}\n"
            "<end_of_turn>\n"
            "<start_of_turn>model\n"
        )

    # ── Model loading and generation ───────────────────────────────────────

    def _load_pipeline(self):
        """Lazy-load the model pipeline on first call."""
        if self._pipeline is not None:
            return

        # Check if running inside Kaggle
        model_path = self._model_path
        if not Path(model_path).exists():
            # Try alternative Kaggle paths
            for alt_key in ["gemma-4-31b-it", "gemma-4-12b-it", "gemma-4-4b-it"]:
                alt_path = _KAGGLE_MODEL_PATHS.get(alt_key, "")
                if Path(alt_path).exists():
                    print(f"[KaggleAdapter] Using {alt_key} at {alt_path}")
                    model_path = alt_path
                    self.model_key = alt_key
                    break
            else:
                raise RuntimeError(
                    f"Model weights not found at {self._model_path}.\n"
                    f"Inside Kaggle: add the model via 'Add data' → Models.\n"
                    f"Outside Kaggle: use OllamaModelAdapter instead."
                )

        try:
            import torch
            from transformers import pipeline, AutoTokenizer

            print(f"[KaggleAdapter] Loading {self.model_key} from {model_path}...")
            self._tokenizer = AutoTokenizer.from_pretrained(model_path)

            load_kwargs: Dict[str, Any] = {
                "model": model_path,
                "tokenizer": self._tokenizer,
                "task": "text-generation",
                "max_new_tokens": self.max_new_tokens,
                "do_sample": self.temperature > 0,
                "temperature": self.temperature if self.temperature > 0 else None,
                "return_full_text": False,
            }

            # Use 4-bit quantization if bitsandbytes available
            try:
                from transformers import BitsAndBytesConfig
                load_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                )
                load_kwargs["device_map"] = "auto"
                print("[KaggleAdapter] Using 4-bit quantization (bitsandbytes)")
            except ImportError:
                load_kwargs["torch_dtype"] = torch.float16
                load_kwargs["device_map"] = self.device
                print("[KaggleAdapter] Using float16 (bitsandbytes not available)")

            self._pipeline = pipeline(**load_kwargs)
            print("[KaggleAdapter] Model loaded successfully.")

        except ImportError as e:
            raise RuntimeError(
                f"transformers or torch not installed: {e}\n"
                f"Install with: pip install transformers torch"
            )

    def _generate(self, prompt: str) -> str:
        """Generate text using the loaded pipeline or inference API."""
        if self.use_inference_api:
            return self._generate_via_api(prompt)

        self._load_pipeline()
        try:
            outputs  = self._pipeline(prompt)
            result   = outputs[0]["generated_text"].strip()

            # Count exact tokens if tokenizer available
            if self._tokenizer:
                try:
                    in_ids  = self._tokenizer.encode(prompt)
                    out_ids = self._tokenizer.encode(result)
                    self._record_tokens(prompt, result,
                                        in_tok=len(in_ids), out_tok=len(out_ids))
                except Exception:
                    self._record_tokens(prompt, result)
            else:
                self._record_tokens(prompt, result)
            return result
        except Exception as e:
            raise RuntimeError(f"Generation failed: {e}")

    def _generate_via_api(self, prompt: str) -> str:
        """Use Kaggle Inference API (no GPU quota needed)."""
        import urllib.request
        import urllib.error

        if not self.kaggle_username or not self.kaggle_key:
            raise RuntimeError(
                "Kaggle credentials required for API mode.\n"
                "Set KAGGLE_USERNAME and KAGGLE_KEY environment variables."
            )

        import base64
        credentials = base64.b64encode(
            f"{self.kaggle_username}:{self.kaggle_key}".encode()
        ).decode()

        url     = f"https://www.kaggle.com/api/v1/models/{self.COMPETITION_MODEL_ID}/inference"
        payload = json.dumps({"inputs": prompt}).encode("utf-8")
        req     = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {credentials}",
            },
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body   = json.loads(resp.read().decode("utf-8"))
                    result = body.get("outputs", [""])[0] if isinstance(
                        body.get("outputs"), list) else body.get("text", "")
                    self._record_tokens(prompt, result)
                    return result.strip()
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise RuntimeError(f"Kaggle API call failed: {e}")
        return ""

    # ── JSON parsing ───────────────────────────────────────────────────────

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

    # ── Utility ────────────────────────────────────────────────────────────

    @staticmethod
    def is_inside_kaggle() -> bool:
        """Return True if running inside a Kaggle notebook environment."""
        return (
            os.environ.get("KAGGLE_KERNEL_RUN_TYPE") is not None
            or Path("/kaggle/input").exists()
        )

    @staticmethod
    def find_available_kaggle_model() -> Optional[str]:
        """Return the path of the best available Gemma 4 model on Kaggle."""
        for key in ["gemma-4-31b-it-qat", "gemma-4-31b-it",
                    "gemma-4-12b-it", "gemma-4-4b-it"]:
            path = _KAGGLE_MODEL_PATHS.get(key, "")
            if Path(path).exists():
                return path
        return None
