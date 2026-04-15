"""REST client for the STS2_MCP mod (localhost:15526).

Mirrors every POST action exposed in mcp/server.py so we can drive
the game directly without going through an MCP process.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx


class GameClient:
    def __init__(self, base_url: str = "http://127.0.0.1:15526", multiplayer: bool = False, timeout: float = 15.0):
        self.base_url = base_url
        self.prefix = "/api/v1/multiplayer" if multiplayer else "/api/v1/singleplayer"
        self.timeout = timeout

    @property
    def _url(self) -> str:
        return f"{self.base_url}{self.prefix}"

    def get_state(self, fmt: str = "json") -> Dict[str, Any] | str:
        r = httpx.get(self._url, params={"format": fmt}, timeout=self.timeout)
        r.raise_for_status()
        if fmt == "json":
            return r.json()
        return r.text

    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        r = httpx.post(self._url, json=body, timeout=self.timeout)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": "ok", "raw": r.text}

    # ---- dispatch: map tool-name -> POST action body ----
    # Each key is the "tool" name an agent returns. Values describe how to
    # translate (params) into the REST body the mod expects.
    _TOOL_MAP = {
        # General
        "use_potion":         lambda p: {"action": "use_potion", "slot": p["slot"], **({"target": p["target"]} if p.get("target") else {})},
        "discard_potion":     lambda p: {"action": "discard_potion", "slot": p["slot"]},
        "proceed":            lambda p: {"action": "proceed"},
        # Combat
        "play_card":          lambda p: {"action": "play_card", "card_index": p["card_index"], **({"target": p["target"]} if p.get("target") else {})},
        "end_turn":           lambda p: {"action": "end_turn"},
        "combat_select_card": lambda p: {"action": "combat_select_card", "card_index": p["card_index"]},
        "combat_confirm":     lambda p: {"action": "combat_confirm_selection"},
        # Rewards
        "claim_reward":       lambda p: {"action": "claim_reward", "index": p["index"]},
        "pick_card_reward":   lambda p: {"action": "select_card_reward", "card_index": p["card_index"]},
        "skip_card_reward":   lambda p: {"action": "skip_card_reward"},
        # Map / Rest / Shop / Event
        "choose_map_node":    lambda p: {"action": "choose_map_node", "index": p["index"]},
        "choose_rest":        lambda p: {"action": "choose_rest_option", "index": p["index"]},
        "shop_purchase":      lambda p: {"action": "shop_purchase", "index": p["index"]},
        "choose_event":       lambda p: {"action": "choose_event_option", "index": p["index"]},
        "advance_dialogue":   lambda p: {"action": "advance_dialogue"},
        # Deck overlays
        "select_card":        lambda p: {"action": "select_card", "index": p["index"]},
        "confirm_selection":  lambda p: {"action": "confirm_selection"},
        "cancel_selection":   lambda p: {"action": "cancel_selection"},
        # Bundle
        "select_bundle":      lambda p: {"action": "select_bundle", "index": p["index"]},
        "confirm_bundle":     lambda p: {"action": "confirm_bundle_selection"},
        "cancel_bundle":      lambda p: {"action": "cancel_bundle_selection"},
        # Relic / Treasure
        "select_relic":       lambda p: {"action": "select_relic", "index": p["index"]},
        "skip_relic":         lambda p: {"action": "skip_relic_selection"},
        "claim_treasure":     lambda p: {"action": "claim_treasure_relic", "index": p["index"]},
        # Crystal sphere
        "crystal_set_tool":   lambda p: {"action": "crystal_sphere_set_tool", "tool": p["tool"]},
        "crystal_click":      lambda p: {"action": "crystal_sphere_click_cell", "x": p["x"], "y": p["y"]},
        "crystal_proceed":    lambda p: {"action": "crystal_sphere_proceed"},
    }

    def execute(self, tool: str, params: Optional[Dict[str, Any]] = None,
                state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute an agent's chosen action. `tool` is one of the keys in _TOOL_MAP.

        If `state` is provided, common LLM mistakes are auto-corrected:
        - play_card: card_id -> card_index via state.player.hand lookup
        - pick_card_reward / select_card: card_id / name -> index
        - target='Self'|'self'|'player' -> removed (no target)
        - tool/state_type mismatch (combat_select_card during normal combat -> play_card, etc.)
        """
        params = dict(params or {})
        if state is not None:
            tool, params = _correct_tool_for_state(tool, params, state)
            params = _normalize_params(tool, params, state)
        if tool not in self._TOOL_MAP:
            return {"status": "error", "message": f"Unknown tool '{tool}'"}
        try:
            body = self._TOOL_MAP[tool](params)
        except KeyError as e:
            return {"status": "error", "message": f"missing required param for {tool}: {e}"}
        return self._post(body)

    def wait_for_state_change(self, current_type: str, max_wait: float = 5.0, poll: float = 0.3) -> Dict[str, Any]:  # noqa: E501
        """Poll until state_type changes or timeout. Useful after actions that trigger animations."""
        deadline = time.time() + max_wait
        last = None
        while time.time() < deadline:
            last = self.get_state("json")
            if isinstance(last, dict) and last.get("state_type") != current_type:
                return last
            time.sleep(poll)
        return last or {}


_SELF_TARGETS = {"self", "player", "hero", "me"}

_COMBAT_STATES = {"monster", "elite", "boss"}


def _correct_tool_for_state(tool: str, params: Dict[str, Any], state: Dict[str, Any]):
    """Fix common tool/state mismatches before the request hits the mod."""
    st = state.get("state_type")
    # LLMs often mix these up:
    if tool == "combat_select_card" and st in _COMBAT_STATES:
        return "play_card", params
    if tool == "play_card" and st == "hand_select":
        return "combat_select_card", {k: v for k, v in params.items() if k != "target"}
    # "proceed" is accepted on many screens; if we're on map, they probably want choose_map_node 0
    if tool == "proceed" and st == "map":
        return "choose_map_node", {"index": params.get("index", 0)}
    # rewards screen: agent sometimes jumps to pick_card_reward; must claim_reward first
    if tool == "pick_card_reward" and st == "rewards":
        idx = params.get("index")
        if idx is None:
            idx = params.get("card_index", 0)
        return "claim_reward", {"index": idx}
    # card_reward screen: claim_reward doesn't apply; it's pick_card_reward
    if tool == "claim_reward" and st == "card_reward":
        idx = params.get("card_index", params.get("index", 0))
        return "pick_card_reward", {"card_index": idx}
    return tool, params


def _match_card(cards, key):
    """Return index of the first card in `cards` whose id/name/title matches `key`."""
    if not isinstance(cards, list) or key is None:
        return None
    k = str(key).lower()
    for i, c in enumerate(cards):
        if not isinstance(c, dict):
            continue
        for field in ("id", "card_id", "name", "title", "display_name"):
            v = c.get(field)
            if v is not None and str(v).lower() == k:
                return i
    return None


def _normalize_params(tool: str, params: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params)

    # "Self" target means no target
    tgt = p.get("target")
    if isinstance(tgt, str) and tgt.lower() in _SELF_TARGETS:
        p.pop("target", None)

    hand = (state.get("player") or {}).get("hand") or []

    if tool == "play_card":
        if "card_index" not in p:
            idx = _match_card(hand, p.get("card_id") or p.get("name") or p.get("card"))
            if idx is not None:
                p["card_index"] = idx
        p.pop("card_id", None); p.pop("name", None); p.pop("card", None)
        # Auto-target: if the card needs a target but none provided, pick first living enemy
        ci = p.get("card_index")
        if isinstance(ci, int) and 0 <= ci < len(hand):
            card = hand[ci] or {}
            ttype = (card.get("target_type") or "").lower()
            if ttype in ("anyenemy", "enemy", "singleenemy") and not p.get("target"):
                enemies = ((state.get("battle") or {}).get("enemies")) or []
                for e in enemies:
                    if (e or {}).get("hp", 0) > 0 and e.get("entity_id"):
                        p["target"] = e["entity_id"]
                        break
            # Self / AoE cards: target must be absent
            if ttype in ("self", "none", "allenemies", "all_enemies", "area"):
                p.pop("target", None)

    elif tool == "combat_select_card":
        if "card_index" not in p:
            idx = _match_card(hand, p.get("card_id") or p.get("name"))
            if idx is not None:
                p["card_index"] = idx
        p.pop("card_id", None); p.pop("name", None)

    elif tool == "pick_card_reward":
        if "card_index" not in p:
            cards = (state.get("card_reward") or {}).get("cards") or []
            idx = _match_card(cards, p.get("card_id") or p.get("name"))
            if idx is not None:
                p["card_index"] = idx
        p.pop("card_id", None); p.pop("name", None)

    elif tool == "select_card":
        if "index" not in p:
            cards = (state.get("card_select") or {}).get("cards") or []
            idx = _match_card(cards, p.get("card_id") or p.get("name"))
            if idx is not None:
                p["index"] = idx
        p.pop("card_id", None); p.pop("name", None)

    elif tool in ("use_potion", "discard_potion"):
        if "slot" not in p:
            alt = p.get("potion_index", p.get("index", p.get("potion_slot")))
            if alt is not None:
                p["slot"] = alt
        p.pop("potion_index", None); p.pop("index", None); p.pop("potion_slot", None)

    elif tool == "claim_reward":
        if "index" not in p:
            items = (state.get("rewards") or {}).get("items") or []
            priority = {"card": 0, "relic": 1, "potion": 2, "gold": 3}
            best_idx, best_rank = None, 99
            for i, it in enumerate(items):
                if not isinstance(it, dict):
                    continue
                kind = str(it.get("type") or it.get("kind") or "").lower()
                rank = priority.get(kind, 50)
                if rank < best_rank:
                    best_rank, best_idx = rank, i
            if best_idx is None and items:
                best_idx = 0
            if best_idx is not None:
                p["index"] = best_idx

    return p
