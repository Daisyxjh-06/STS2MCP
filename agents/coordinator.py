"""Coordinator: routes state types to relevant agents and arbitrates."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from combat_agent import CombatAgent
from economy_agent import EconomyAgent
from strategic_agent import StrategicAgent

_COMBAT_STATES = {"monster", "elite", "boss"}

_DECK_ANALYST_SYSTEM = (
    "You are an expert Slay the Spire 2 deck analyst. "
    "Be concise and specific about card names and mechanics."
)


# Which agents participate in each state_type decision.
#
# Design follows the proposal:
#   - Combat: short-term survival, prefers rest sites when HP is low
#   - Strategic: long-term deck strength, prefers elites and card rewards
#   - Economy: resource efficiency, prefers shops and gold
#
# All three agents vote on map routing because their objectives directly
# conflict there (combat→rest, strategic→elite, economy→shop).
# The Coordinator picks the highest-confidence proposal.
# Tools that are meaningful on each state_type. Used during arbitration to
# filter out proposals whose tool the mod will reject on the current screen
# (e.g. combat agent suggesting choose_map_node while on rest_site).
VALID_TOOLS: Dict[str, set] = {
    "monster":       {"play_card", "end_turn", "use_potion", "discard_potion"},
    "elite":         {"play_card", "end_turn", "use_potion", "discard_potion"},
    "boss":          {"play_card", "end_turn", "use_potion", "discard_potion"},
    "hand_select":   {"combat_select_card", "combat_confirm", "cancel_selection"},
    "map":           {"choose_map_node"},
    "rest_site":     {"choose_rest", "proceed"},
    "rewards":       {"claim_reward", "proceed"},
    "card_reward":   {"pick_card_reward", "skip_card_reward", "proceed"},
    "card_select":   {"select_card", "confirm_selection", "cancel_selection"},
    "bundle_select": {"select_bundle", "confirm_bundle", "cancel_bundle"},
    "relic_select":  {"select_relic", "skip_relic", "proceed"},
    "treasure":      {"claim_treasure", "proceed"},
    "event":         {"choose_event", "advance_dialogue", "proceed"},
    "shop":          {"shop_purchase", "proceed"},
    "fake_merchant": {"shop_purchase", "proceed"},
    "crystal_sphere": {"crystal_set_tool", "crystal_click", "crystal_proceed"},
}


ROUTING: Dict[str, List[str]] = {
    # Pure combat — only combat agent has relevant expertise
    "monster":       ["combat"],
    "elite":         ["combat"],
    "boss":          ["combat"],
    "hand_select":   ["combat"],
    # Map routing — all three agents vote (core coordination scenario)
    "map":           ["combat", "strategic", "economy"],
    # Rest site — purely a strategic decision (heal vs upgrade); combat agent
    # has no valid rest_site tools and consistently hallucinates choose_map_node
    "rest_site":     ["strategic"],
    # Post-combat rewards — strategic picks cards, economy manages order
    "rewards":       ["strategic", "economy"],
    "card_reward":   ["strategic"],
    "card_select":   ["strategic"],
    "bundle_select": ["strategic"],
    # Relic / treasure — both strategic value and economy cost matter
    "relic_select":  ["strategic", "economy"],
    "treasure":      ["strategic", "economy"],
    # Events — may offer gold, HP, or cards
    "event":         ["strategic", "economy"],
    # Shop — economy leads, strategic advises on card purchases
    "shop":          ["economy", "strategic"],
    "fake_merchant": ["economy", "strategic"],
    "crystal_sphere": ["strategic"],
}


class Coordinator:
    def __init__(self, llm, run_id: str):
        self.run_id = run_id
        self.llm = llm
        self.agents = {
            "combat": CombatAgent(llm, run_id),
            "strategic": StrategicAgent(llm, run_id),
            "economy": EconomyAgent(llm, run_id),
        }
        self._executor = ThreadPoolExecutor(max_workers=3)
        self._last_combat_floor: int = -1

    def _generate_deck_summary(self, state: Dict[str, Any]) -> str:
        player = state.get("player") or {}
        deck = player.get("deck") or []
        relics = [r.get("id") if isinstance(r, dict) else r for r in player.get("relics") or []]
        floor = (state.get("run") or {}).get("floor", "?")
        query = (
            f"Floor {floor} combat starting.\n"
            f"Full deck: {json.dumps(deck, ensure_ascii=False)}\n"
            f"Relics: {json.dumps(relics, ensure_ascii=False)}\n\n"
            "In 3 sentences max, summarize: "
            "(1) the deck's archetype and win condition, "
            "(2) key synergies or combo lines to execute, "
            "(3) any card ordering constraints — cards that must be played before others "
            "can be played or that unlock/enable other cards."
        )
        try:
            summary = self.llm.generate(
                _DECK_ANALYST_SYSTEM, query,
                session_id=f"{self.run_id}-deck-analysis",
            )
            return summary.strip()[:800]
        except Exception as e:
            print(f"[coordinator] deck summary failed: {e}")
            return ""

    def relevant_agents(self, state_type: str) -> List[str]:
        return ROUTING.get(state_type, ["strategic"])

    def decide(self, state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], bool]:
        """Returns (chosen_action, all_proposals, agreement_flag)."""
        state_type = state.get("state_type", "unknown")

        # Generate deck summary once per new combat floor so the combat agent
        # doesn't re-analyze the deck every single step.
        if state_type in _COMBAT_STATES:
            floor = (state.get("run") or {}).get("floor", -1)
            if floor != self._last_combat_floor:
                self._last_combat_floor = floor
                print(f"[coordinator] new combat at floor {floor} — generating deck summary")
                self.agents["combat"].extra_context = self._generate_deck_summary(state)

        names = self.relevant_agents(state_type)

        if len(names) == 1:
            prop = self.agents[names[0]].propose(state)
            return prop["action"], {names[0]: prop}, True

        # Parallel calls
        futures = {n: self._executor.submit(self.agents[n].propose, state) for n in names}
        proposals = {n: f.result() for n, f in futures.items()}

        # Arbitration: prefer proposals whose tool is valid on this state_type;
        # among those, pick highest confidence. Falls back to raw max-confidence
        # if no proposal uses a valid tool (so the auto-correct layer in
        # game_client can still try to salvage it).
        valid = VALID_TOOLS.get(state_type)
        candidates = proposals
        if valid:
            ok = {n: p for n, p in proposals.items()
                  if p.get("action", {}).get("tool") in valid}
            if ok:
                candidates = ok
        chosen_name = max(candidates, key=lambda n: candidates[n]["confidence"])
        chosen = proposals[chosen_name]["action"]
        tools = {p["action"]["tool"] for p in proposals.values()}
        agreement = len(tools) == 1
        return chosen, proposals, agreement
