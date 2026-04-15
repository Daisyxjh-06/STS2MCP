"""Aggregate runs/*_summary.json + *_steps.jsonl into charts and metric tables.

Usage:
    python -m experiments.analyze --runs-dir runs --out-dir runs/analysis
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _load_summaries(runs_dir: Path) -> List[Dict[str, Any]]:
    out = []
    for p in runs_dir.glob("*_summary.json"):
        try:
            out.append(json.loads(p.read_text()))
        except Exception as e:
            print(f"[analyze] skipping {p.name}: {e}")
    return out


def _load_steps(runs_dir: Path, run_id: str) -> List[Dict[str, Any]]:
    p = runs_dir / f"{run_id}_steps.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _stats(xs: List[float]) -> Dict[str, float]:
    if not xs:
        return {"n": 0, "mean": 0.0, "std": 0.0}
    return {"n": len(xs), "mean": round(mean(xs), 2),
            "std": round(pstdev(xs), 2) if len(xs) > 1 else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out-dir", default="runs/analysis")
    args = ap.parse_args()

    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = _load_summaries(runs_dir)
    if not summaries:
        print(f"[analyze] no summaries in {runs_dir}")
        return

    by_system: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in summaries:
        by_system[s.get("system", "unknown")].append(s)

    # ---- Metrics table ----
    metrics: Dict[str, Dict[str, Any]] = {}
    for sys_name, rows in by_system.items():
        floors = [r.get("final", {}).get("floor") or 0 for r in rows]
        wins = [1 if r.get("won") else 0 for r in rows]
        steps = [r.get("total_steps") or 0 for r in rows]
        metrics[sys_name] = {
            "runs": len(rows),
            "floor": _stats(floors),
            "win_rate": round(sum(wins) / len(wins), 3) if wins else 0.0,
            "steps": _stats(steps),
        }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print("[analyze] metrics:", json.dumps(metrics, indent=2))

    # ---- Floor comparison bar ----
    if by_system:
        fig, ax = plt.subplots(figsize=(6, 4))
        names = list(by_system.keys())
        means = [metrics[n]["floor"]["mean"] for n in names]
        stds = [metrics[n]["floor"]["std"] for n in names]
        ax.bar(names, means, yerr=stds, capsize=5, color=["#4c72b0", "#dd8452"][: len(names)])
        ax.set_ylabel("Final floor reached (mean ± std)")
        ax.set_title("Floor reached: baseline vs MAS")
        fig.tight_layout()
        fig.savefig(out_dir / "floor_comparison.png", dpi=140)
        plt.close(fig)

    # ---- Win rate bar ----
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(list(metrics.keys()),
           [metrics[n]["win_rate"] for n in metrics],
           color=["#4c72b0", "#dd8452"][: len(metrics)])
    ax.set_ylabel("Win rate")
    ax.set_ylim(0, 1)
    ax.set_title("Win rate: baseline vs MAS")
    fig.tight_layout()
    fig.savefig(out_dir / "win_rate.png", dpi=140)
    plt.close(fig)

    # ---- Agreement / conflict (MAS only) ----
    mas_rows = by_system.get("mas", [])
    if mas_rows:
        agreement_counts = Counter()
        total = 0
        action_dist = Counter()
        for r in mas_rows:
            steps = _load_steps(runs_dir, r["run_id"])
            for s in steps:
                if s.get("agreement") is None:
                    continue
                agreement_counts["agree" if s["agreement"] else "conflict"] += 1
                total += 1
                tool = (s.get("chosen") or {}).get("tool", "noop")
                action_dist[tool] += 1
        if total:
            rates = {k: round(v / total, 3) for k, v in agreement_counts.items()}
            (out_dir / "coordination.json").write_text(json.dumps({
                "rates": rates, "total_multi_agent_steps": total,
                "action_distribution": dict(action_dist.most_common()),
            }, indent=2))
            # action dist pie
            top = action_dist.most_common(10)
            fig, ax = plt.subplots(figsize=(6, 6))
            ax.pie([c for _, c in top], labels=[k for k, _ in top], autopct="%1.0f%%")
            ax.set_title("Chosen action distribution (MAS, top 10)")
            fig.tight_layout()
            fig.savefig(out_dir / "action_distribution.png", dpi=140)
            plt.close(fig)

    print(f"[analyze] wrote charts + metrics to {out_dir}")


if __name__ == "__main__":
    main()
