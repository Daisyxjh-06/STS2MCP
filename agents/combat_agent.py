from base_agent import Agent
from state_filter import for_combat


class CombatAgent(Agent):
    name = "combat"
    prompt_file = "combat"

    def view(self, state):
        return for_combat(state)
