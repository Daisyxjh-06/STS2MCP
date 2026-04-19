"""
Supervisor: 自动运行 runner，检测卡住状态并自动解锁，崩溃后自动重启。

用法:
    python3 supervisor.py --system mas --run-id mas_01
    python3 supervisor.py --system baseline --run-id bl_01
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:15526/api/v1/singleplayer"

# 每个 state 允许停留的最大步数，超过就强制解锁
STUCK_LIMITS = {
    "card_reward":  6,
    "card_select":  8,
    "rewards":      8,
    "rest_site":    6,
    "map":          6,
    "shop":         6,
    "event":       10,
    "monster":     40,
    "elite":       40,
    "boss":        60,
}
DEFAULT_STUCK_LIMIT = 15

# 各 state 卡住时的解锁动作（按顺序尝试）
UNLOCK_ACTIONS = {
    "card_reward":  [{"action": "skip_card_reward"}],
    "card_select":  [{"action": "confirm_selection"}, {"action": "cancel_selection"}],
    "rewards":      [{"action": "proceed"}],
    "rest_site":    [{"action": "choose_rest_option", "index": 0}],
    "map":          [{"action": "choose_map_node", "index": 0}],
    "shop":         [{"action": "proceed"}],
    "event":        [{"action": "choose_event_option", "index": 0}],
    "monster":      [{"action": "end_turn"}],
    "elite":        [{"action": "end_turn"}],
    "boss":         [{"action": "end_turn"}],
}


def get_state() -> dict | None:
    try:
        r = httpx.get(BASE_URL, params={"format": "json"}, timeout=5)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def post_action(body: dict) -> dict | None:
    try:
        r = httpx.post(BASE_URL, json=body, timeout=5)
        return r.json()
    except Exception:
        return None


def unlock(state_type: str) -> bool:
    actions = UNLOCK_ACTIONS.get(state_type, [])
    for action in actions:
        result = post_action(action)
        print(f"[supervisor] unlock {state_type} → {action}: {result}", flush=True)
        time.sleep(1)
        new = get_state()
        if new and new.get("state_type") != state_type:
            return True
    return False


def run_supervisor(system: str, run_id: str, out_dir: str, model: str,
                   max_steps: int, max_restarts: int) -> None:
    run_count = 0
    while run_count < max_restarts:
        run_count += 1
        log_path = Path(f"/tmp/mas_supervisor_run{run_count}.log")
        cmd = [
            sys.executable, "-u", "runner.py",
            "--system", system,
            "--run-id", f"{run_id}_{run_count}",
            "--out-dir", out_dir,
            "--model", model,
            "--max-steps", str(max_steps),
            "--verbose",
        ]
        print(f"\n[supervisor] ── 启动 runner (attempt {run_count}) ──", flush=True)
        print(f"[supervisor] 日志: {log_path}", flush=True)

        with open(log_path, "w") as logf:
            proc = subprocess.Popen(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                cwd=Path(__file__).parent,
            )

        # 监控循环
        stuck_counter: dict[str, int] = {}
        last_state_type = None

        while proc.poll() is None:
            state = get_state()
            if state is None:
                time.sleep(2)
                continue

            st = state.get("state_type", "unknown")
            floor = (state.get("run") or {}).get("floor", "?")
            hp = (state.get("player") or {}).get("hp", "?")

            if st == last_state_type:
                stuck_counter[st] = stuck_counter.get(st, 0) + 1
                limit = STUCK_LIMITS.get(st, DEFAULT_STUCK_LIMIT)
                if stuck_counter[st] >= limit:
                    print(f"[supervisor] 卡住 {stuck_counter[st]} 轮 @ {st} | floor={floor} hp={hp}，尝试解锁…", flush=True)
                    unlocked = unlock(st)
                    stuck_counter[st] = 0
                    if not unlocked:
                        print(f"[supervisor] 解锁失败，终止 runner", flush=True)
                        proc.terminate()
                        break
            else:
                if last_state_type:
                    stuck_counter[last_state_type] = 0
                last_state_type = st

            time.sleep(2)

        ret = proc.wait()
        print(f"[supervisor] runner 退出 (code={ret})", flush=True)

        # 检查游戏是否还在跑（menu = 局结束，可以重开）
        state = get_state()
        st = (state or {}).get("state_type", "unknown")
        if st == "menu":
            print(f"[supervisor] 游戏回到菜单，本局结束。", flush=True)
            break

        if run_count < max_restarts:
            print(f"[supervisor] 3 秒后重启…", flush=True)
            time.sleep(3)

    print(f"[supervisor] 完成，共运行 {run_count} 次", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=["mas", "baseline"], required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out-dir", default="runs")
    ap.add_argument("--model", default="4o-mini")
    ap.add_argument("--max-steps", type=int, default=2000)
    ap.add_argument("--max-restarts", type=int, default=5,
                    help="卡死后最多重启次数")
    args = ap.parse_args()
    run_supervisor(args.system, args.run_id, args.out_dir, args.model,
                   args.max_steps, args.max_restarts)


if __name__ == "__main__":
    main()
