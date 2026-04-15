"""JSONL logger for per-step decisions and run summaries."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional


class RunLogger:
    def __init__(self, run_dir: Path, run_id: str, system: str, seed: Optional[int] = None):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.system = system  # "mas" or "baseline"
        self.seed = seed
        self.steps_path = self.run_dir / f"{run_id}_steps.jsonl"
        self.summary_path = self.run_dir / f"{run_id}_summary.json"
        self.t0 = time.time()
        self.n_steps = 0
        # truncate prior file if any
        self.steps_path.write_text("")

    def log_step(self,
                 state_type: str,
                 floor: Optional[int],
                 hp: Optional[int],
                 gold: Optional[int],
                 proposals: Dict[str, Dict[str, Any]],
                 chosen: Dict[str, Any],
                 agreement: Optional[bool] = None) -> None:
        rec = {
            "step": self.n_steps,
            "t": round(time.time() - self.t0, 2),
            "state_type": state_type,
            "floor": floor,
            "hp": hp,
            "gold": gold,
            "proposals": proposals,
            "chosen": chosen,
            "agreement": agreement,
        }
        with self.steps_path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.n_steps += 1

    def write_summary(self, **kw) -> None:
        data = {
            "run_id": self.run_id,
            "system": self.system,
            "seed": self.seed,
            "total_steps": self.n_steps,
            "wall_seconds": round(time.time() - self.t0, 1),
            **kw,
        }
        self.summary_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
