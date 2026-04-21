"""Thin wrapper around LLMProxy with JSON extraction + retry."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

_LLM_TIMEOUT = 45.0  # seconds per request attempt

from dotenv import load_dotenv
from llmproxy import LLMProxy

# Load .env from the agents/ dir regardless of cwd.
_AGENTS_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_AGENTS_DIR / ".env", override=False)

_DEFAULT_MODEL = "4o-mini"

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_OBJECT = re.compile(r"(\{.*\})", re.DOTALL)


class LLMClient:
    def __init__(self, model: str = _DEFAULT_MODEL):
        self.model = model
        self._proxy = LLMProxy()

    def generate(self, system: str, query: str, session_id: str,
                 temperature: Optional[float] = 0.3, lastk: int = 0,
                 _retry: int = 3) -> str:
        for attempt in range(_retry):
            result: list = [None]
            error: list = [None]

            def _call():
                try:
                    result[0] = self._proxy.generate(
                        model=self.model,
                        system=system,
                        query=query,
                        temperature=temperature,
                        lastk=lastk,
                        session_id=session_id,
                        rag_usage=False,
                    )
                except Exception as e:
                    error[0] = e

            t = threading.Thread(target=_call, daemon=True)
            t.start()
            t.join(timeout=_LLM_TIMEOUT)
            if t.is_alive():
                raise RuntimeError(f"LLM request timed out after {_LLM_TIMEOUT}s")
            if error[0]:
                raise error[0]
            res = result[0]
            if isinstance(res, dict):
                if "error" in res:
                    err_str = str(res.get("error", ""))
                    if "429" in err_str and attempt < _retry - 1:
                        wait = 5.0 * (attempt + 1)
                        print(f"[llm] 429 rate limit, retrying in {wait}s (attempt {attempt+1}/{_retry})")
                        time.sleep(wait)
                        continue
                    raise RuntimeError(f"LLMProxy error: {res}")
                return res.get("result") or res.get("response") or ""
            return str(res)
        raise RuntimeError("generate: exhausted retries")

    def generate_json(self, system: str, query: str, session_id: str,
                      max_retries: int = 2, **kw) -> Dict[str, Any]:
        """Ask LLM to return JSON. Tolerates code fences / prose wrapping."""
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                text = self.generate(system, query, session_id, **kw)
                return extract_json(text)
            except Exception as e:
                last_err = e
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Failed to get JSON after {max_retries + 1} tries: {last_err}")


def extract_json(text: str) -> Dict[str, Any]:
    """Pull a JSON object out of an LLM response."""
    if not text:
        raise ValueError("empty LLM response")

    # Try fenced block first.
    m = _JSON_BLOCK.search(text)
    if m:
        return json.loads(m.group(1))

    # Try to find the outermost {...} by bracket matching.
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object found in: {text[:200]!r}")
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"unbalanced JSON braces in: {text[:200]!r}")
