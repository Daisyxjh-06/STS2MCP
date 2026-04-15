from base_agent import Agent
from state_filter import for_strategic


class StrategicAgent(Agent):
    name = "strategic"
    prompt_file = "strategic"

    def view(self, state):
        return for_strategic(state)
