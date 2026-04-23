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

# Guard choose_map_node only when NOT on a screen where game_client can
# correct it (rest_site corrects it to proceed).
# All other mismatches are handled by game_client._correct_tool_for_state.
_MAP_TOOL_ALLOWED_STATES = {"map", "rest_site"}


def _player_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    p = state.get("player") or {}
    run = state.get("run") or {}
    return {
        "floor": run.get("floor"),
        "act": run.get("act"),
        "hp": p.get("hp"),
        "max_hp": p.get("max_hp"),
        "gold": p.get("gold"),
        "deck_size": len(p.get("deck") or []) or p.get("deck_size") or 0,
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
        action   = prop.get("action", {})
        conf     = prop.get("confidence", "?")
        just     = prop.get("justification", "")
        strategy = prop.get("strategy", "")
        tool     = action.get("tool", "?")
        params   = action.get("params") or {}
        param_str = "  ".join(f"{k}={v}" for k, v in params.items()) if params else ""
        marker = f"{G}✓{R}" if action == chosen else f"{DIM}·{R}"
        print(f"  {marker} {color}{B}{agent_name:<12}{R}  "
              f"[conf={conf}]  {Y}{tool}{R}({param_str})")
        if strategy:
            print(f"    {DIM}strategy: {strategy[:120]}{R}")
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
    prev_state_type = None
    stuck_counter = 0
    last_action_key = None
    same_action_count = 0
    last_summary: Dict[str, Any] = {}
    last_full_state: Dict[str, Any] = {}

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
            prev_state_type = last_state_type
            last_state_type = st

        if st in _AUTO_ADVANCE:
            time.sleep(poll_interval)
            continue

        # After rest_site the map screen has a loading animation — wait before acting.
        if st == "map" and prev_state_type == "rest_site":
            time.sleep(2.5)

        # Skip the agent entirely during the enemy turn — the mod will reject
        # any player action with "Not in play phase" until IsPlayPhase flips
        # back. state_type alone ("monster"/"elite"/"boss") doesn't distinguish
        # player vs. enemy turn, so check battle.is_play_phase / turn.
        if st in _COMBAT_STATES_RUNNER:
            battle = state.get("battle") or {}
            play_phase = battle.get("is_play_phase")
            turn = battle.get("turn")
            if play_phase is False or (isinstance(turn, str) and turn.lower() == "enemy"):
                time.sleep(poll_interval)
                continue
            # If no card in hand is playable, skip the agent entirely and end
            # the turn. Otherwise the LLM keeps proposing invalid card_indexes
            # and the same-action fallback can't catch it (each index differs).
            hand = (state.get("player") or {}).get("hand") or []
            any_playable = any(c.get("can_play") is True for c in hand)
            if not any_playable:
                print(f"[runner] no playable cards (hand={len(hand)}) — auto end_turn")
                try:
                    game.execute("end_turn", {}, state=state)
                except Exception as e:
                    print(f"[runner] auto end_turn error: {e}")
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
        last_summary = summary
        last_full_state = state
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

        # If the agent returned noop because of an LLM error (e.g. 429),
        # don't count it toward same_action_count — that would trigger the
        # forced-fallback logic mid-combat and waste a player turn. Just
        # back off and let the next tick try again.
        if tool == "noop":
            _just = ""
            for _p in proposals.values():
                _just = (_p.get("justification") or "")
                if "LLM error" in _just or "LLMProxy error" in _just:
                    break
            if "LLM error" in _just or "LLMProxy error" in _just:
                print(f"[runner] LLM-error noop, sleeping 15s before retry")
                time.sleep(15.0)
                continue

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
            elif st in ("rewards", "rest_site", "treasure",
                        "card_reward", "relic_select", "bundle_select"):
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

        # Guard: only block choose_map_node on screens where game_client
        # cannot correct it (i.e. not map and not rest_site).
        if tool == "choose_map_node" and st not in _MAP_TOOL_ALLOWED_STATES:
            print(f"[runner] dropping 'choose_map_node': current state is {st!r}")
            fallback_tool, fallback_params = None, {}
            for _name, _prop in sorted(proposals.items(),
                                       key=lambda x: -x[1].get("confidence", 0)):
                _t = (_prop.get("action") or {}).get("tool", "noop")
                _p = (_prop.get("action") or {}).get("params") or {}
                if _t not in ("noop", "choose_map_node"):
                    fallback_tool, fallback_params = _t, _p
                    print(f"[runner] fallback to {_t!r} from {_name}")
                    break
            if fallback_tool:
                tool, params = fallback_tool, fallback_params
            else:
                time.sleep(poll_interval)
                continue

        try:
            resp = game.execute(tool, params, state=state)
            if isinstance(resp, dict) and resp.get("status") == "error":
                print(f"[runner] action rejected: {resp}")
                err = str(resp.get("error", ""))
                if "Map screen is not open" in err:
                    time.sleep(2.5)
                elif "EnergyCostTooHigh" in err and st in _COMBAT_STATES_RUNNER:
                    # Agent proposed a card it can't afford — end turn instead.
                    game.execute("end_turn", {}, state=state)
                elif "sold out" in err.lower() and st in ("shop", "fake_merchant"):
                    # Item was already purchased — proceed out of shop.
                    print(f"[runner] sold-out fallback: proceeding from {st}")
                    game.execute("proceed", {}, state=state)
        except Exception as e:
            print(f"[runner] execute error: {e}")
        time.sleep(poll_interval)

    # Final summary — use last recorded state rather than re-querying the game,
    # which may have already returned to menu with no run data.
    won = bool(last_full_state.get("run", {}).get("won"))
    logger.write_summary(
        final=last_summary,
        final_state_type=last_state_type,
        won=won,
        model=model,
    )
    print(f"[runner] done: steps={logger.n_steps} final={last_summary}")
    return last_summary


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
