"""Base class for all specialized agents."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from llm_client import LLMClient, extract_json

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


class Agent:
    """Each agent: LLM role + local state view + structured proposal."""

    name: str = "base"          # override
    prompt_file: str = "base"   # override

    def __init__(self, llm: LLMClient, run_id: str):
        self.llm = llm
        self.run_id = run_id
        self.system_prompt = _load_prompt(self.prompt_file)

    def view(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Override in subclasses to filter state."""
        return state

    def propose(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Return {'action': {'tool': str, 'params': {...}}, 'confidence': float, 'justification': str}."""
        local = self.view(state)
        state_type = local.get("state_type", "unknown")
        query = (
            f"Current screen: {state_type}\n"
            "Current local game state (JSON):\n"
            f"{json.dumps(local, ensure_ascii=False)[:12000]}\n\n"
            "Step 1 — write exactly one line:\n"
            "STRATEGY: <one sentence about the deck's current archetype and how it shapes your decision>\n\n"
            f"Step 2 — write ONLY a JSON object using tools valid for the '{state_type}' screen "
            "(no code fences, no other text):\n"
            "{\"action\": {\"tool\": \"<tool_name>\", \"params\": {...}}, "
            "\"confidence\": 0.0-1.0, \"justification\": \"short reason\"}"
        )
        session = f"{self.run_id}-{self.name}"
        try:
            raw = self.llm.generate(self.system_prompt, query, session_id=session, lastk=2)
        except Exception as e:
            return {
                "action": {"tool": "noop", "params": {}},
                "confidence": 0.0,
                "justification": f"LLM error: {e}",
                "strategy": "",
            }

        # Extract STRATEGY line (plain text, safe from JSON parse issues).
        strategy = ""
        for line in raw.splitlines():
            if re.match(r"(?i)strategy\s*:", line):
                strategy = line.split(":", 1)[1].strip()[:400]
                break

        # Extract JSON (action/confidence/justification only).
        try:
            out = extract_json(raw)
        except Exception as e:
            return {
                "action": {"tool": "noop", "params": {}},
                "confidence": 0.0,
                "justification": f"JSON parse error: {e} | raw: {raw[:200]}",
                "strategy": strategy,
            }

        action = out.get("action") or {}
        if not isinstance(action, dict) or "tool" not in action:
            return {
                "action": {"tool": "noop", "params": {}},
                "confidence": 0.0,
                "justification": f"Bad action shape: {out}",
                "strategy": strategy,
            }
        return {
            "action": {"tool": action["tool"], "params": action.get("params") or {}},
            "confidence": float(out.get("confidence", 0.5)),
            "justification": str(out.get("justification", ""))[:400],
            "strategy": strategy,
        }
