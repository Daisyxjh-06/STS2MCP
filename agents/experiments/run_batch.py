"""Run a batch of games for one system (mas or baseline).

Between runs the user must manually restart the run in the game with the
next seed (STS2 does not expose seed via the mod API). The script pauses
and waits for a fresh `menu` → non-menu transition before starting each run.

Usage:
    python -m experiments.run_batch --system mas --seeds 1,2,3,4,5
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make parent importable when run from this directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game_client import GameClient      # noqa: E402
from runner import run_one              # noqa: E402


def wait_for_run_start(game: GameClient, max_wait: float = 600) -> bool:
    """Block until the game exits the menu (i.e., a run has started)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            state = game.get_state("json")
        except Exception:
            state = None
        if isinstance(state, dict) and state.get("state_type") not in (None, "menu", "unknown"):
            return True
        time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=["mas", "baseline"], required=True)
    ap.add_argument("--seeds", required=True, help="comma-separated seed labels, e.g. 1,2,3")
    ap.add_argument("--out-dir", default="runs")
    ap.add_argument("--model", default="4o-mini")
    ap.add_argument("--max-steps", type=int, default=2000)
    args = ap.parse_args()

    seeds = [s.strip() for s in args.seeds.split(",") if s.strip()]
    out_dir = Path(args.out_dir)
    game = GameClient()

    for seed in seeds:
        run_id = f"{args.system}_{seed}"
        print(f"\n=== {run_id} — start a new run in the game with seed {seed} ===")
        print("(Waiting for the game to leave the main menu...)")
        if not wait_for_run_start(game):
            print("[batch] timed out waiting for run start; skipping.")
            continue
        print(f"[batch] run detected; playing {run_id}")
        try:
            run_one(args.system, run_id, out_dir, args.model, max_steps=args.max_steps)
        except Exception as e:
            print(f"[batch] run {run_id} crashed: {e}")
        # Give a moment to settle, then expect the user to manually return to menu / start next
        time.sleep(3)


if __name__ == "__main__":
    main()
