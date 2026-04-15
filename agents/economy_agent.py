from base_agent import Agent
from state_filter import for_economy


class EconomyAgent(Agent):
    name = "economy"
    prompt_file = "economy"

    def view(self, state):
        return for_economy(state)
