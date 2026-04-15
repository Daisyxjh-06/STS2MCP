from base_agent import Agent
from state_filter import for_baseline


class BaselineAgent(Agent):
    """Single-agent baseline: sees everything, decides everything."""
    name = "baseline"
    prompt_file = "baseline"

    def view(self, state):
        return for_baseline(state)
