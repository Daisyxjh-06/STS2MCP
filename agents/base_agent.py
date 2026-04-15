"""Base class for all specialized agents."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from llm_client import LLMClient

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
        query = (
            "Current local game state (JSON):\n"
            f"{json.dumps(local, ensure_ascii=False)[:12000]}\n\n"
            "Return ONLY a JSON object with keys: action, confidence, justification.\n"
            "action must have shape: {\"tool\": \"<tool_name>\", \"params\": { ... }}.\n"
            "confidence is a float between 0 and 1."
        )
        session = f"{self.run_id}-{self.name}"
        try:
            out = self.llm.generate_json(self.system_prompt, query, session_id=session, lastk=2)
        except Exception as e:
            return {
                "action": {"tool": "noop", "params": {}},
                "confidence": 0.0,
                "justification": f"LLM error: {e}",
            }
        # Normalize shape defensively.
        action = out.get("action") or {}
        if not isinstance(action, dict) or "tool" not in action:
            return {
                "action": {"tool": "noop", "params": {}},
                "confidence": 0.0,
                "justification": f"Bad action shape from LLM: {out}",
            }
        return {
            "action": {"tool": action["tool"], "params": action.get("params") or {}},
            "confidence": float(out.get("confidence", 0.5)),
            "justification": str(out.get("justification", ""))[:400],
        }
