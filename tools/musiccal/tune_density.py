"""tools/musiccal/tune_density.py — clear-rate tuning loop (director's brief
step 3): "keep adjusting it so the total clear rate is maybe 50%."

Bisects the gauntlet's `--density` (enemy-count scale factor) against
HumanBot clear rate: clear_rate(density) is monotonically non-increasing
(more enemies never makes a level easier), so bisection on [DENSITY_LO,
DENSITY_HI] converges to the 45-55% band in O(log) iterations. Each
candidate is rebuilt via build_gauntlet.py and evaluated with a modest
probe batch (PROBE_RUNS, human bot, fixed seed block distinct from the
final calibration seeds so tuning never leaks into the fitted data); the
winning density gets one larger CONFIRM_RUNS pass to confirm the band
before the level is committed.

Writes tools/musiccal/tuning_log.json (the per-iteration convergence
table the report cites) and leaves levels/gauntlet_cal.json built at the
chosen density.

Usage: uv run python tools/musiccal/tune_density.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "tools/musiccal/build_gauntlet.py"
RUN_FARM = ROOT / "tools/musiccal/run_farm.py"
LEVEL = ROOT / "levels/gauntlet_cal.json"
TUNE_RUNS_DIR = ROOT / "tools/musiccal/runs_tuning"
LOG_PATH = ROOT / "tools/musiccal/tuning_log.json"

TARGET_LO, TARGET_HI = 0.45, 0.55
DENSITY_LO, DENSITY_HI = 0.08, 1.0
PROBE_RUNS = 60
CONFIRM_RUNS = 150
MAX_ITERS = 10
# tuning-probe seeds live in a block below the calibration run's seed0
# (10_000_000+ in run the final farm uses) so probe data is never mixed
# into the fitted corpus even though the level file it validated is reused.
PROBE_SEED0 = 500_000


def build(density: float) -> dict:
    out = subprocess.run(
        [sys.executable, str(BUILD), "--density", f"{density:.5f}", "--out", str(LEVEL)],
        cwd=ROOT, capture_output=True, text=True, check=True)
    print(out.stdout.strip())
    return out.stdout


def probe(density: float, n_runs: int, seed0: int) -> dict:
    out = subprocess.run(
        [sys.executable, str(RUN_FARM), "--level", str(LEVEL), "--n-runs", str(n_runs),
         "--seed0", str(seed0), "--bot", "human", "--out-dir", str(TUNE_RUNS_DIR)],
        cwd=ROOT, capture_output=True, text=True, check=True)
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"no summary line in run_farm output:\n{out.stdout}\n{out.stderr}")


def main() -> int:
    lo, hi = DENSITY_LO, DENSITY_HI
    log = []
    t_start = time.perf_counter()

    for it in range(1, MAX_ITERS + 1):
        density = (lo + hi) / 2.0
        build(density)
        seed0 = PROBE_SEED0 + it * 10_000
        res = probe(density, PROBE_RUNS, seed0)
        clear = res["clear_rate"]
        entry = dict(iter=it, density=round(density, 5), n_runs=PROBE_RUNS,
                     clear_rate=clear, outcomes=res["outcomes"],
                     lo=round(lo, 5), hi=round(hi, 5))
        log.append(entry)
        print(f"[tune] iter={it} density={density:.4f} clear_rate={clear:.3f} "
              f"(n={PROBE_RUNS}) band=[{lo:.4f},{hi:.4f}]")

        if TARGET_LO <= clear <= TARGET_HI:
            print(f"[tune] density={density:.4f} lands in [{TARGET_LO},{TARGET_HI}] "
                  f"after {it} iterations; confirming with {CONFIRM_RUNS} runs")
            break
        if clear < TARGET_LO:
            hi = density  # too hard -> need fewer enemies
        else:
            lo = density  # too easy -> need more enemies
    else:
        print(f"[tune] hit MAX_ITERS={MAX_ITERS} without landing in band; "
              f"using the closest-to-50% iteration")
        entry = min(log, key=lambda e: abs(e["clear_rate"] - 0.5))
        density = entry["density"]
        build(density)

    confirm_seed0 = PROBE_SEED0 + 999_000
    confirm = probe(density, CONFIRM_RUNS, confirm_seed0)
    confirm_entry = dict(iter="confirm", density=round(density, 5), n_runs=CONFIRM_RUNS,
                         clear_rate=confirm["clear_rate"], outcomes=confirm["outcomes"])
    log.append(confirm_entry)
    print(f"[tune] CONFIRM density={density:.4f} clear_rate={confirm['clear_rate']:.3f} "
          f"(n={CONFIRM_RUNS})")

    LOG_PATH.write_text(json.dumps(dict(
        target=[TARGET_LO, TARGET_HI], final_density=density,
        final_clear_rate=confirm["clear_rate"], iterations=log,
        wallclock_s=round(time.perf_counter() - t_start, 1),
    ), indent=1))
    print(f"[tune] wrote {LOG_PATH}")
    in_band = TARGET_LO <= confirm["clear_rate"] <= TARGET_HI
    print(f"[tune] {'IN BAND' if in_band else 'OUT OF BAND (see log)'}: "
          f"final density={density:.4f}")
    return 0 if in_band else 1


if __name__ == "__main__":
    raise SystemExit(main())
