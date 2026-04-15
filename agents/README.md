# CS150-01 Final — Multi-Agent STS2 Player

Implementation of the mid-report's multi-agent system:
- **Combat Agent** — in-combat decisions.
- **Strategic Agent** — deck, map, events, rests, relics.
- **Economy Agent** — shop, gold, potions.
- **Coordinator** (`coordinator.py`) — routes state to relevant agents and arbitrates by confidence.
- **Baseline** — single agent that sees everything, used as the control condition.

LLM calls go through **LLMProxy** (`llmproxy` package, API key in `.env`). Game actions go through the STS2_MCP mod's REST API at `localhost:15526` — we bypass the MCP server process for scriptability.

## Setup

```bash
# 1. Install the proxy client + requirements
pip install --break-system-packages -e ../LLMProxy-main/py
pip install --break-system-packages -r requirements.txt

# 2. Confirm .env is in this directory
cat .env   # should show LLMPROXY_API_KEY and LLMPROXY_ENDPOINT

# 3. Smoke test (works without the game running)
python test_smoke.py
```

## Running a single game

1. Launch Slay the Spire 2 with the STS2_MCP mod enabled.
2. Start a run (any character, fix the seed if you can).
3. In a terminal:
   ```bash
   python runner.py --system mas      --run-id mas_01
   # or
   python runner.py --system baseline --run-id bl_01
   ```
4. Per-step JSONL + final summary written to `runs/<run_id>_steps.jsonl` and `runs/<run_id>_summary.json`.

## Running a batch

```bash
python -m experiments.run_batch --system baseline --seeds 1,2,3,4,5
python -m experiments.run_batch --system mas      --seeds 1,2,3,4,5
```

The batch runner waits for you to start each run in-game (it detects the menu → non-menu transition).

## Analyzing results

```bash
python -m experiments.analyze --runs-dir runs --out-dir runs/analysis
```

Outputs:
- `runs/analysis/metrics.json` — mean/std floor, win rate per system.
- `runs/analysis/floor_comparison.png`, `win_rate.png`, `action_distribution.png`.
- `runs/analysis/coordination.json` — MAS agreement / conflict rates.

## File layout

```
agents/
├── runner.py            # main game loop
├── coordinator.py       # MAS coordinator (routing + arbitration)
├── base_agent.py        # agent base class
├── combat_agent.py      # ─┐
├── strategic_agent.py   #  │ three specialized agents
├── economy_agent.py     # ─┘
├── baseline_agent.py    # single-agent control
├── game_client.py       # REST wrapper for localhost:15526
├── llm_client.py        # LLMProxy wrapper + JSON parser
├── state_filter.py      # per-agent local state views
├── logger.py            # JSONL step + summary logger
├── prompts/             # system prompts (versioned text)
├── experiments/
│   ├── run_batch.py
│   └── analyze.py
└── test_smoke.py        # sanity checks
```

## Notes

- `4o-mini` is the default model (cheap, fast). Pass `--model <name>` to runner / batch to swap.
- Each agent uses its own `session_id = "<run_id>-<agent_name>"` with `lastk=2` for short-term tactical memory.
- When a state type is routed to multiple agents, the Coordinator picks the highest-confidence proposal and logs `agreement = (all proposals chose the same tool)`.
- `noop` actions and repeated same-state stalls abort the run after 30 unchanged states.
