"""Filter the full STS2 game state into per-agent local views.

Each agent only sees the slice of state relevant to its role. This keeps
prompts smaller and enforces the mid-report's bounded-rationality design.
"""
from __future__ import annotations

from typing import Any, Dict

# Fields worth keeping in every view — lightweight run-level context.
_COMMON = ("state_type", "run")


def _player_core(p: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(p, dict):
        return {}
    return {
        "character": p.get("character"),
        "hp": p.get("hp"),
        "max_hp": p.get("max_hp"),
        "block": p.get("block"),
        "gold": p.get("gold"),
        "relics": [r.get("id") if isinstance(r, dict) else r for r in p.get("relics", [])],
    }


def _player_combat(p: Dict[str, Any]) -> Dict[str, Any]:
    base = _player_core(p)
    base.update({
        "energy": p.get("energy"),
        "hand": p.get("hand"),
        "draw_pile_count": p.get("draw_pile_count") or len(p.get("draw_pile", []) or []),
        "discard_pile_count": p.get("discard_pile_count") or len(p.get("discard_pile", []) or []),
        "exhaust_pile_count": p.get("exhaust_pile_count") or len(p.get("exhaust_pile", []) or []),
        "orbs": p.get("orbs"),
        "powers": p.get("powers"),
        "potions": p.get("potions"),
    })
    return base


def _copy_common(state: Dict[str, Any]) -> Dict[str, Any]:
    return {k: state[k] for k in _COMMON if k in state}


def for_combat(state: Dict[str, Any]) -> Dict[str, Any]:
    """Combat agent: hand, energy, enemies, player powers/orbs/potions."""
    view = _copy_common(state)
    view["player"] = _player_combat(state.get("player", {}))
    # Enemies live under state.battle.enemies in STS2.
    battle = state.get("battle") or {}
    view["battle"] = {
        "round": battle.get("round"),
        "turn": battle.get("turn"),
        "is_play_phase": battle.get("is_play_phase"),
        "enemies": battle.get("enemies", []),
    }
    # keep combat-related optional blobs if present
    for k in ("hand_select", "ascension"):
        if k in state:
            view[k] = state[k]
    return view


def for_strategic(state: Dict[str, Any]) -> Dict[str, Any]:
    """Strategic agent: deck, map, relics, rewards/card choices, events."""
    view = _copy_common(state)
    p = state.get("player", {})
    core = _player_core(p)
    core["deck"] = p.get("deck")
    core["potions"] = p.get("potions")
    view["player"] = core
    for k in (
        "map", "rewards", "card_reward", "card_select", "bundle_select",
        "relic_select", "treasure", "event", "rest_site",
    ):
        if k in state:
            view[k] = state[k]
    return view


def for_economy(state: Dict[str, Any]) -> Dict[str, Any]:
    """Economy agent: gold, shop, potions, relics (to value offerings)."""
    view = _copy_common(state)
    p = state.get("player", {})
    view["player"] = {
        "gold": p.get("gold"),
        "hp": p.get("hp"),
        "max_hp": p.get("max_hp"),
        "relics": [r.get("id") if isinstance(r, dict) else r for r in p.get("relics", [])],
        "potions": p.get("potions"),
        "deck_size": len(p.get("deck", []) or []),
    }
    for k in ("shop", "fake_merchant", "rewards"):
        if k in state:
            view[k] = state[k]
    return view


def for_baseline(state: Dict[str, Any]) -> Dict[str, Any]:
    """Baseline gets everything — single-agent condition in the experiment."""
    return state


VIEWS = {
    "combat": for_combat,
    "strategic": for_strategic,
    "economy": for_economy,
    "baseline": for_baseline,
}
