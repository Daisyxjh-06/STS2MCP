"""REST client for the STS2_MCP mod (localhost:15526).

Mirrors every POST action exposed in mcp/server.py so we can drive
the game directly without going through an MCP process.
"""
from __future__ import annotations

import re
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
            # LLM returned a card ID/name as the tool name (e.g. "DEFEND_IRONCLAD", "survivor")
            # Try to match it against the hand and convert to play_card
            if state is not None and re.match(r'^[A-Za-z][A-Za-z0-9_]+$', tool):
                hand = (state.get("player") or {}).get("hand") or []
                idx = _match_card(hand, tool)
                if idx is not None:
                    tool = "play_card"
                    params = {"card_index": idx}
                    params = _normalize_params(tool, params, state)
                else:
                    return {"status": "error", "message": f"Unknown tool '{tool}' (card not found in hand)"}
            else:
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


_NON_COMBAT_END_TURN_FALLBACK = {
    "rest_site":   ("proceed", {}),
    "rewards":     ("proceed", {}),
    "shop":        ("proceed", {}),
    "fake_merchant": ("proceed", {}),
    "event":       ("proceed", {}),
    "card_reward": ("skip_card_reward", {}),
    "relic_select": ("skip_relic", {}),
    "treasure":    ("proceed", {}),
    "map":         ("choose_map_node", {"index": 0}),
}


def _correct_tool_for_state(tool: str, params: Dict[str, Any], state: Dict[str, Any]):
    """Fix common tool/state mismatches before the request hits the mod."""
    st = state.get("state_type")
    # end_turn is combat-only. Outside combat, LLM usually means "I'm done,
    # move on" — remap to the screen's natural dismiss action.
    if tool == "end_turn" and st not in _COMBAT_STATES and st in _NON_COMBAT_END_TURN_FALLBACK:
        return _NON_COMBAT_END_TURN_FALLBACK[st]
    # LLMs often mix these up:
    if tool == "combat_select_card" and st in _COMBAT_STATES:
        return "play_card", params
    if tool == "play_card" and st == "hand_select":
        return "combat_select_card", {k: v for k, v in params.items() if k != "target"}
    # "proceed" is accepted on many screens; if we're on map, they probably want choose_map_node 0
    if tool == "proceed" and st == "map":
        return "choose_map_node", {"index": params.get("index", 0)}
    # On non-map screens, "move forward" tools that don't belong should become proceed
    _PROCEED_SCREENS = {"rest_site", "treasure", "rewards", "card_reward",
                        "relic_select", "bundle_select"}
    if st in _PROCEED_SCREENS and tool in ("choose_map_node", "advance_dialogue"):
        return "proceed", {}
    # event screen: advance_dialogue only works when in_dialogue=True; otherwise use choose_event
    if tool == "advance_dialogue" and st == "event":
        in_dialogue = (state.get("event") or {}).get("in_dialogue", False)
        if not in_dialogue:
            idx = params.get("index", 0)
            return "choose_event", {"index": idx}
    # LLMs often collapse the tool name to the state_type ("event") or use
    # alternate verbs like "choose" / "select". Remap those on the event screen.
    if st == "event" and tool in ("event", "choose", "select", "choose_option", "select_event"):
        idx = params.get("index",
              params.get("choose_event",
              params.get("option_index",
              params.get("choice",
              params.get("option", 0)))))
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = 0
        return "choose_event", {"index": idx}
    # rewards screen: agent sometimes jumps to pick_card_reward; must claim_reward first
    if tool == "pick_card_reward" and st == "rewards":
        idx = params.get("index")
        if idx is None:
            idx = params.get("card_index", 0)
        return "claim_reward", {"index": idx}
    # card_reward screen: remap wrong tools to pick_card_reward
    if st == "card_reward":
        if tool == "claim_reward":
            idx = params.get("card_index", params.get("index", 0))
            return "pick_card_reward", {"card_index": idx}
        if tool in ("select_card", "confirm_selection"):
            # agent used card_select tool on card_reward screen —
            # try to resolve by card_id/name; fall back to index 0
            cards = (state.get("card_reward") or {}).get("cards") or []
            card_id = params.get("card_id") or params.get("name") or params.get("card")
            idx = _match_card(cards, card_id) if card_id else params.get("index", params.get("card_index", 0))
            if idx is None:
                idx = 0
            return "pick_card_reward", {"card_index": idx}
        if tool == "cancel_selection":
            return "skip_card_reward", {}
    # card_select screen: pick_card_reward / skip_card_reward don't apply; use select_card
    if st == "card_select":
        if tool in ("pick_card_reward", "skip_card_reward"):
            idx = params.get("card_index", params.get("index", 0))
            return "select_card", {"index": idx}
        # LLM often collapses tool to the state name ("card_select") or uses
        # ad-hoc verbs like "pick_card" / "select". Remap to select_card.
        if tool in ("card_select", "pick_card", "pick", "select", "choose_card", "choose"):
            idx = params.get("index",
                  params.get("card_index",
                  params.get("choice", 0)))
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = 0
            return "select_card", {"index": idx}
        if tool in ("confirm", "confirm_card_select"):
            return "confirm_selection", {}
        if tool in ("cancel", "cancel_card_select"):
            return "cancel_selection", {}
    # bundle_select screen: similar collapse ("bundle_select" -> select_bundle)
    if st == "bundle_select":
        if tool in ("bundle_select", "pick_bundle", "choose_bundle"):
            idx = params.get("index", params.get("bundle_index", 0))
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = 0
            return "select_bundle", {"index": idx}
    # hand_select screen: common swaps
    if st == "hand_select":
        if tool in ("hand_select", "pick_card", "select"):
            idx = params.get("card_index", params.get("index", 0))
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = 0
            return "combat_select_card", {"card_index": idx}
    # rest_site screen: LLM sometimes reuses choose_map_node or collapses to
    # the state name. The only valid tool here is choose_rest.
    if st == "rest_site":
        if tool in ("choose_map_node", "rest_site", "rest", "choose", "select"):
            idx = params.get("index", params.get("option", params.get("choice", 0)))
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = 0
            return "choose_rest", {"index": idx}
    # shop screen: collapse / alternate verbs -> shop_purchase
    if st == "shop":
        if tool in ("shop", "shop_buy", "buy", "purchase"):
            idx = params.get("index", params.get("item_index", params.get("choice", 0)))
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = 0
            return "shop_purchase", {"index": idx}
    # relic_select / treasure
    if st == "relic_select":
        if tool in ("relic_select", "pick_relic", "choose_relic"):
            idx = params.get("index", params.get("relic_index", 0))
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = 0
            return "select_relic", {"index": idx}
    if st == "treasure":
        treasure_blob = state.get("treasure") or {}
        can_proceed = bool(treasure_blob.get("can_proceed"))
        # advance_dialogue / event tools don't apply in treasure rooms —
        # either we still need to claim, or we're ready to proceed.
        if tool in ("treasure", "claim", "claim_relic", "open_chest",
                    "advance_dialogue", "choose_event", "event"):
            if can_proceed or not treasure_blob.get("relics"):
                return "proceed", {}
            idx = params.get("index", params.get("relic_index", 0))
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = 0
            return "claim_treasure", {"index": idx}
        # If a relic already got claimed, claim_treasure will error with
        # "Relic collection is not visible"; swap to proceed.
        if tool == "claim_treasure" and can_proceed:
            return "proceed", {}
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
            if "index" in p:
                p["card_index"] = p.pop("index")
            else:
                cards = (state.get("card_reward") or {}).get("cards") or []
                idx = _match_card(cards, p.get("card_id") or p.get("name"))
                if idx is not None:
                    p["card_index"] = idx
        p.pop("card_id", None); p.pop("name", None); p.pop("index", None)

    elif tool == "select_card":
        if "index" not in p:
            if "card_index" in p:
                try:
                    p["index"] = int(p["card_index"])
                except (TypeError, ValueError):
                    pass
            if "index" not in p:
                cards = (state.get("card_select") or {}).get("cards") or []
                idx = _match_card(cards, p.get("card_id") or p.get("name"))
                if idx is not None:
                    p["index"] = idx
        p.pop("card_id", None); p.pop("name", None); p.pop("card_index", None)

    elif tool == "choose_rest":
        if "index" not in p:
            options = (state.get("rest_site") or {}).get("options") or []
            # match by id or name if provided, else default to first enabled option
            key = p.get("option") or p.get("id") or p.get("name")
            idx = None
            if key:
                k = str(key).lower()
                for o in options:
                    if str(o.get("id", "")).lower() == k or str(o.get("name", "")).lower() == k:
                        idx = o["index"]
                        break
            if idx is None:
                enabled = [o["index"] for o in options if o.get("is_enabled")]
                idx = enabled[0] if enabled else 0
            p["index"] = idx
        p.pop("option", None); p.pop("id", None); p.pop("name", None)

    elif tool in ("use_potion", "discard_potion"):
        if "slot" not in p:
            alt = p.get("potion_index", p.get("index", p.get("potion_slot")))
            if alt is not None:
                p["slot"] = alt
        p.pop("potion_index", None); p.pop("index", None); p.pop("potion_slot", None)

    elif tool == "choose_event":
        if "index" not in p:
            for k in ("choose_event", "option_index", "choice", "option", "card_index"):
                if k in p:
                    try:
                        p["index"] = int(p[k])
                    except (TypeError, ValueError):
                        pass
                    break
            if "index" not in p:
                p["index"] = 0
        for k in ("choose_event", "option_index", "choice", "option", "card_index"):
            p.pop(k, None)

    elif tool == "choose_map_node":
        # LLMs sometimes use {col, row} (the fields they see in map.next_options)
        # instead of the required {index}. Resolve via lookup.
        if "index" not in p:
            options = (state.get("map") or {}).get("next_options") or []
            col = p.get("col")
            row = p.get("row")
            idx = None
            if col is not None and row is not None:
                for o in options:
                    if o.get("col") == col and o.get("row") == row:
                        idx = o.get("index")
                        break
            if idx is None:
                # Fall back: first option, which matches _NON_COMBAT_END_TURN_FALLBACK.
                idx = (options[0].get("index", 0) if options else 0)
            p["index"] = idx
        p.pop("col", None); p.pop("row", None); p.pop("type", None); p.pop("node", None)

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
