"""hunt_winner — find seeds where the human bot CLEARS the gauntlet.

Director 2026-07-17: "re-generate the video with a _winning session_".
Streams per-seed outcomes as they finish (tune_pass_rate only prints
aggregates); exits once `--want` winning seeds are found.

    uv run python tools/musiccal/hunt_winner.py --k 240 --workers 24
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))
sys.path.insert(0, str(Path(__file__).parent))

from tune_pass_rate import one  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="levels/gauntlet_cal3.json")
    ap.add_argument("--start", type=int, default=1000)
    ap.add_argument("--k", type=int, default=240)
    ap.add_argument("--want", type=int, default=3)
    ap.add_argument("--max-ticks", type=int, default=60 * 60 * 12)
    ap.add_argument("--workers", type=int, default=24)
    a = ap.parse_args()
    from perihelion.testkit.humanbot import DEFAULT_SKILL
    jobs = [(a.level, a.start + i, DEFAULT_SKILL, a.max_ticks, 0, 1.0)
            for i in range(a.k)]
    winners, done = [], 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, j): j[1] for j in jobs}
        for f in as_completed(futs):
            r = f.result()
            done += 1
            line = (f"{r['seed']} {r['outcome']:8s} ticks={r['ticks']}"
                    f" kills={r['kills']} polygon={r['polygon']}"
                    f" hp={r.get('hp', '?')}")
            print(line, flush=True)
            if r["outcome"] == "complete":
                winners.append(r["seed"])
                print(f"*** WINNER {r['seed']} "
                      f"({len(winners)}/{a.want}) ***", flush=True)
                if len(winners) >= a.want:
                    for g in futs:
                        g.cancel()
                    break
    print(f"done={done} winners={winners}", flush=True)


if __name__ == "__main__":
    main()
