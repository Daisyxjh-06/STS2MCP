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


def _parse_energy(energy_raw: Any) -> int:
    """Extract current energy as int regardless of API shape."""
    if isinstance(energy_raw, int):
        return energy_raw
    if isinstance(energy_raw, dict):
        return int(energy_raw.get("current") or 0)
    try:
        return int(energy_raw)
    except (TypeError, ValueError):
        return 0


def _annotate_hand(hand: Any, energy: int) -> Any:
    """Add/correct can_play flag for each card.

    The game API already sends can_play + unplayable_reason. We trust it for
    non-energy reasons (e.g. a curse that must be played first locks other
    cards with unplayable_reason='Unplayable'). We only recompute can_play
    when the reason is purely energy — the API value may lag one frame.
    """
    if not isinstance(hand, list):
        return hand
    result = []
    for card in hand:
        if isinstance(card, dict):
            game_can_play = card.get("can_play")
            reason = card.get("unplayable_reason")
            # If the game marks a card unplayable for a non-energy reason,
            # keep that verdict — don't let our energy check flip it to true.
            if game_can_play is False and reason not in (None, "NotEnoughEnergy"):
                result.append(card)
                continue
            cost_raw = card.get("cost")
            try:
                cost = int(cost_raw)
                can_play = cost <= energy
            except (TypeError, ValueError):
                can_play = True  # X-cost or unknown — let LLM decide
            result.append({**card, "can_play": can_play})
        else:
            result.append(card)
    return result


def _player_combat(p: Dict[str, Any]) -> Dict[str, Any]:
    base = _player_core(p)
    energy = _parse_energy(p.get("energy"))
    base.update({
        "energy": energy,
        "hand": _annotate_hand(p.get("hand"), energy),
        "deck": p.get("deck"),
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
    """Combat agent: hand, energy, enemies, player powers/orbs/potions.
    Also receives map when routing, so it can prefer rest sites when HP is low."""
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
    # include screen-specific blobs only when relevant
    st = state.get("state_type", "")
    for k in ("hand_select", "ascension", "rest_site"):
        if k in state:
            view[k] = state[k]
    # map data only when actually on the map screen
    if st == "map" and "map" in state:
        view["map"] = state["map"]
    return view


# Map from state_type to the single screen data key each agent should receive.
# Only the active screen's data is included — prevents agents from confusing
# background data (e.g. map is always present) with the current decision context.
_SCREEN_KEY: Dict[str, str] = {
    "map":          "map",
    "rewards":      "rewards",
    "card_reward":  "card_reward",
    "card_select":  "card_select",
    "bundle_select":"bundle_select",
    "relic_select": "relic_select",
    "treasure":     "treasure",
    "event":        "event",
    "rest_site":    "rest_site",
    "shop":         "shop",
    "fake_merchant":"fake_merchant",
    "crystal_sphere":"crystal_sphere",
    "hand_select":  "hand_select",
}


def for_strategic(state: Dict[str, Any]) -> Dict[str, Any]:
    """Strategic agent: deck, map, relics, rewards/card choices, events."""
    view = _copy_common(state)
    p = state.get("player", {})
    core = _player_core(p)
    core["deck"] = p.get("deck")
    core["potions"] = p.get("potions")
    view["player"] = core
    # Only include data for the current active screen.
    k = _SCREEN_KEY.get(state.get("state_type", ""))
    if k and k in state:
        raw = state[k]
        view[k] = _filter_shop(raw) if k in ("shop", "fake_merchant") else raw
    return view


def _filter_shop(shop: Any) -> Any:
    """Remove sold-out items so agents never attempt to purchase them.

    Handles both flat shop objects {"items": [...]} and the fake_merchant
    wrapper {"shop": {"items": [...]}, ...}.
    """
    if not isinstance(shop, dict):
        return shop
    # Flat shop: {"items": [...], "can_proceed": ...}
    items = shop.get("items")
    if isinstance(items, list):
        return {**shop, "items": [it for it in items if it.get("is_stocked", True)]}
    # Fake merchant wrapper: {"shop": {...}, "event_name": ..., ...}
    nested = shop.get("shop")
    if isinstance(nested, dict):
        return {**shop, "shop": _filter_shop(nested)}
    return shop


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
        "deck": p.get("deck"),
    }
    # Only include data for the current active screen.
    k = _SCREEN_KEY.get(state.get("state_type", ""))
    if k and k in state:
        raw = state[k]
        view[k] = _filter_shop(raw) if k in ("shop", "fake_merchant") else raw
    return view


def for_baseline(state: Dict[str, Any]) -> Dict[str, Any]:
    """Baseline gets everything, but with the same hand annotation as combat agent."""
    st = state.get("state_type", "")
    if st not in ("monster", "elite", "boss", "hand_select"):
        return state
    # Deep-copy only the player subtree so we don't mutate the original state.
    import copy
    view = dict(state)
    p = copy.copy(state.get("player") or {})
    energy = _parse_energy(p.get("energy"))
    p["hand"] = _annotate_hand(p.get("hand"), energy)
    view["player"] = p
    return view


VIEWS = {
    "combat": for_combat,
    "strategic": for_strategic,
    "economy": for_economy,
    "baseline": for_baseline,
}
