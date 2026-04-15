"""Thin wrapper around LLMProxy with JSON extraction + retry."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

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
                 temperature: Optional[float] = 0.3, lastk: int = 0) -> str:
        res = self._proxy.generate(
            model=self.model,
            system=system,
            query=query,
            temperature=temperature,
            lastk=lastk,
            session_id=session_id,
            rag_usage=False,
        )
        if isinstance(res, dict):
            if "error" in res:
                raise RuntimeError(f"LLMProxy error: {res}")
            return res.get("result") or res.get("response") or ""
        return str(res)

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
