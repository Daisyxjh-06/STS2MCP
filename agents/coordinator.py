"""Coordinator: routes state types to relevant agents and arbitrates."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from combat_agent import CombatAgent
from economy_agent import EconomyAgent
from strategic_agent import StrategicAgent

# Which agents are relevant for each state_type.
# Combat-heavy screens go to Combat; progression/deck screens go to Strategic;
# gold / shop screens go to Economy. Rewards are multi-agent (Strategic owns
# card choice, Economy owns gold/potion/relic claim order).
ROUTING: Dict[str, List[str]] = {
    "monster": ["combat"],
    "elite": ["combat"],
    "boss": ["combat"],
    "hand_select": ["combat"],
    "rewards": ["strategic", "economy"],
    "card_reward": ["strategic"],
    "card_select": ["strategic"],
    "bundle_select": ["strategic"],
    "relic_select": ["strategic", "economy"],
    "treasure": ["strategic", "economy"],
    "map": ["strategic"],
    "event": ["strategic", "economy"],
    "rest_site": ["strategic"],
    "shop": ["economy", "strategic"],
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
