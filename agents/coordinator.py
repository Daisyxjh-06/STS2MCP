"""Coordinator: routes state types to relevant agents and arbitrates."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from combat_agent import CombatAgent
from economy_agent import EconomyAgent
from strategic_agent import StrategicAgent

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
ROUTING: Dict[str, List[str]] = {
    # Pure combat — only combat agent has relevant expertise
    "monster":       ["combat"],
    "elite":         ["combat"],
    "boss":          ["combat"],
    "hand_select":   ["combat"],
    # Map routing — all three agents vote (core coordination scenario)
    "map":           ["combat", "strategic", "economy"],
    # Rest site — combat cares about healing, strategic about smithing
    "rest_site":     ["combat", "strategic"],
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
        self.agents = {
            "combat": CombatAgent(llm, run_id),
            "strategic": StrategicAgent(llm, run_id),
            "economy": EconomyAgent(llm, run_id),
        }
        self._executor = ThreadPoolExecutor(max_workers=3)

    def relevant_agents(self, state_type: str) -> List[str]:
        return ROUTING.get(state_type, ["strategic"])

    def decide(self, state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], bool]:
        """Returns (chosen_action, all_proposals, agreement_flag)."""
        state_type = state.get("state_type", "unknown")
        names = self.relevant_agents(state_type)

        if len(names) == 1:
            prop = self.agents[names[0]].propose(state)
            return prop["action"], {names[0]: prop}, True

        # Parallel calls
        futures = {n: self._executor.submit(self.agents[n].propose, state) for n in names}
        proposals = {n: f.result() for n, f in futures.items()}

        # Arbitration: pick highest confidence. Agreement = all agents chose same tool.
        chosen_name = max(proposals, key=lambda n: proposals[n]["confidence"])
        chosen = proposals[chosen_name]["action"]
        tools = {p["action"]["tool"] for p in proposals.values()}
        agreement = len(tools) == 1
        return chosen, proposals, agreement
