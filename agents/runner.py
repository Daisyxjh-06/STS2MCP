"""Main runner: loops get_state -> decide -> execute until the run ends.

Usage:
    python runner.py --system mas       --run-id mas_01
    python runner.py --system baseline  --run-id bl_01
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict

from baseline_agent import BaselineAgent
from coordinator import Coordinator
from game_client import GameClient
from llm_client import LLMClient
from logger import RunLogger

# Terminal state_types — if we see this we stop.
_TERMINAL = {"menu", "unknown"}

# State types where the only meaningful action is to proceed automatically.
# For `event` we still let the agent choose, as there may be dialogue branches.
# `unknown` is usually a transient inter-room state — wait for it to resolve.
_AUTO_ADVANCE = {"overlay", "unknown"}

_COMBAT_STATES_RUNNER = {"monster", "elite", "boss"}


def _player_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    p = state.get("player") or {}
    run = state.get("run") or {}
    return {
        "floor": run.get("floor"),
        "act": run.get("act"),
        "hp": p.get("hp"),
        "max_hp": p.get("max_hp"),
        "gold": p.get("gold"),
        "deck_size": len(p.get("deck", []) or []),
    }


def run_one(system: str, run_id: str, out_dir: Path, model: str,
            max_steps: int = 2000, poll_interval: float = 1.0) -> Dict[str, Any]:
    llm = LLMClient(model=model)
    game = GameClient()
    logger = RunLogger(out_dir, run_id, system)

    if system == "mas":
        coordinator = Coordinator(llm, run_id)
        baseline = None
    else:
        coordinator = None
        baseline = BaselineAgent(llm, run_id)

    consecutive_errors = 0
    last_state_type = None
    stuck_counter = 0
    last_action_key = None
    same_action_count = 0

    while logger.n_steps < max_steps:
        try:
            state = game.get_state("json")
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors > 5:
                print(f"[runner] giving up after repeated get_state errors: {e}")
                break
            time.sleep(2.0)
            continue
        consecutive_errors = 0

        if not isinstance(state, dict):
            time.sleep(poll_interval)
            continue

        st = state.get("state_type", "unknown")

        if st == "menu":
            # Run ended (dead or otherwise back at menu).
            break

        # Detect getting stuck in the same state
        if st == last_state_type:
            stuck_counter += 1
            if stuck_counter > 30:
                print(f"[runner] stuck at state {st} — aborting")
                break
        else:
            stuck_counter = 0
            last_state_type = st

        if st in _AUTO_ADVANCE:
            time.sleep(poll_interval)
            continue

        # Decide
        if coordinator is not None:
            chosen, proposals, agreement = coordinator.decide(state)
        else:
            prop = baseline.propose(state)
            chosen = prop["action"]
            proposals = {"baseline": prop}
            agreement = True

        summary = _player_summary(state)
        logger.log_step(
            state_type=st,
            floor=summary["floor"],
            hp=summary["hp"],
            gold=summary["gold"],
            proposals=proposals,
            chosen=chosen,
            agreement=agreement,
        )

        tool = chosen.get("tool", "noop")
        params = chosen.get("params") or {}

        # Break repeated-same-action loops by forcing a safe fallback.
        action_key = (tool, repr(sorted((params or {}).items())))
        if action_key == last_action_key:
            same_action_count += 1
        else:
            same_action_count = 0
            last_action_key = action_key
        if same_action_count >= 3:
            if st in _COMBAT_STATES_RUNNER:
                tool, params = "end_turn", {}
            elif st == "rewards":
                tool, params = "proceed", {}
            elif st == "map":
                tool, params = "choose_map_node", {"index": 0}
            print(f"[runner] forcing fallback after repeated {action_key}: -> {tool}({params})")
            same_action_count = 0
            last_action_key = (tool, repr(sorted(params.items())))

        if tool == "noop":
            time.sleep(poll_interval)
            continue

        try:
            resp = game.execute(tool, params, state=state)
            if isinstance(resp, dict) and resp.get("status") == "error":
                print(f"[runner] action rejected: {resp}")
        except Exception as e:
            print(f"[runner] execute error: {e}")
        time.sleep(poll_interval)

    # Final summary
    try:
        final = game.get_state("json")
    except Exception:
        final = {}
    final_summary = _player_summary(final) if isinstance(final, dict) else {}
    won = isinstance(final, dict) and final.get("run", {}).get("won") is True
    logger.write_summary(
        final=final_summary,
        final_state_type=(final.get("state_type") if isinstance(final, dict) else None),
        won=won,
        model=model,
    )
    print(f"[runner] done: steps={logger.n_steps} final={final_summary}")
    return final_summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=["mas", "baseline"], required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out-dir", default="runs")
    ap.add_argument("--model", default="4o-mini")
    ap.add_argument("--max-steps", type=int, default=2000)
    args = ap.parse_args()

    run_one(args.system, args.run_id, Path(args.out_dir), args.model,
            max_steps=args.max_steps)


if __name__ == "__main__":
    main()
