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


_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m",
    "cyan": "\033[36m", "yellow": "\033[33m", "green": "\033[32m",
    "red": "\033[31m", "magenta": "\033[35m", "dim": "\033[2m",
}

_AGENT_COLORS = {
    "combat": "\033[31m",    # red
    "strategic": "\033[34m", # blue
    "economy": "\033[32m",   # green
    "baseline": "\033[36m",  # cyan
}


def _print_step(step: int, system: str, st: str, summary: Dict[str, Any],
                proposals: Dict[str, Any], chosen: Dict[str, Any], agreement: bool) -> None:
    R, B, DIM = _ANSI["reset"], _ANSI["bold"], _ANSI["dim"]
    C, Y, G = _ANSI["cyan"], _ANSI["yellow"], _ANSI["green"]

    floor = summary.get("floor", "?")
    hp    = summary.get("hp", "?")
    maxhp = summary.get("max_hp", "?")
    gold  = summary.get("gold", "?")

    print(f"\n{B}{'─'*60}{R}")
    print(f"{B}Step {step:>4}{R}  {C}{st:<18}{R}  "
          f"Floor {floor}  HP {hp}/{maxhp}  Gold {gold}")
    print(f"{DIM}system: {system}{R}")

    for agent_name, prop in proposals.items():
        color = _AGENT_COLORS.get(agent_name, "")
        action = prop.get("action", {})
        conf   = prop.get("confidence", "?")
        just   = prop.get("justification", "")
        tool   = action.get("tool", "?")
        params = action.get("params") or {}
        param_str = "  ".join(f"{k}={v}" for k, v in params.items()) if params else ""
        marker = f"{G}✓{R}" if action == chosen else f"{DIM}·{R}"
        print(f"  {marker} {color}{B}{agent_name:<12}{R}  "
              f"[conf={conf}]  {Y}{tool}{R}({param_str})")
        if just:
            print(f"    {DIM}{just[:120]}{R}")

    if len(proposals) > 1:
        agree_str = f"{G}agree{R}" if agreement else f"\033[31mdisagree{R}"
        chosen_agent = next(
            (n for n, p in proposals.items() if p.get("action") == chosen), "?")
        print(f"  → chosen: {Y}{B}{chosen.get('tool')}{R}  "
              f"({agree_str}, picked from {chosen_agent})")


def run_one(system: str, run_id: str, out_dir: Path, model: str,
            max_steps: int = 2000, poll_interval: float = 1.0,
            verbose: bool = False) -> Dict[str, Any]:
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
            # card_select / hand_select need confirm after a few selections
            if stuck_counter == 5 and st in ("card_select", "hand_select"):
                print(f"[runner] auto-confirming {st} after {stuck_counter} steps")
                try:
                    game.execute("confirm_selection", {}, state=state)
                except Exception:
                    pass
                time.sleep(poll_interval)
                continue
            # Combat states stay as "monster"/"elite"/"boss" for the entire
            # multi-turn fight — same_action_count already handles truly stuck
            # combat, so don't abort based on state_type repetition alone.
            if stuck_counter > 30 and st not in _COMBAT_STATES_RUNNER:
                print(f"[runner] stuck at state {st} — aborting")
                break
        else:
            stuck_counter = 0
            last_state_type = st

        if st in _AUTO_ADVANCE:
            time.sleep(poll_interval)
            continue

        # Skip the agent entirely during the enemy turn — the mod will reject
        # any player action with "Not in play phase" until IsPlayPhase flips
        # back. state_type alone ("monster"/"elite"/"boss") doesn't distinguish
        # player vs. enemy turn, so check battle.is_play_phase directly.
        if st in _COMBAT_STATES_RUNNER:
            battle = state.get("battle") or {}
            play_phase = battle.get("is_play_phase")
            turn = battle.get("turn")
            if play_phase is False or (isinstance(turn, str) and turn.lower() == "enemy"):
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
        if verbose:
            _print_step(logger.n_steps, system, st, summary,
                        proposals, chosen, agreement)
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
            elif st == "event":
                tool, params = "choose_event", {"index": 0}
            elif st == "rest_site":
                tool, params = "choose_rest", {"index": 0}
            elif st == "shop":
                tool, params = "proceed", {}
            elif st == "card_reward":
                tool, params = "skip_card_reward", {}
            elif st == "relic_select":
                tool, params = "skip_relic", {}
            elif st == "treasure":
                can_proceed = bool((state.get("treasure") or {}).get("can_proceed"))
                if can_proceed:
                    tool, params = "proceed", {}
                else:
                    tool, params = "claim_treasure", {"index": 0}
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
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Print per-step decision summary to stdout")
    args = ap.parse_args()

    run_one(args.system, args.run_id, Path(args.out_dir), args.model,
            max_steps=args.max_steps, verbose=args.verbose)


if __name__ == "__main__":
    main()
