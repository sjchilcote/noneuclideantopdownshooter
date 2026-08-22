"""tools/musiccal/run_farm.py — headless calibration run farm.

Drives `GameSession` directly (no renderer, no app.py render loop — the human
bot's perception model reads `session.snapshot()`/`session` engine state,
never pixels, so nothing is lost by skipping rendering; see
`perihelion.testkit.humanbot`) with `--bot human` by default, falling back
to `--bot aggro` only if human-bot runs prove unstable (none observed in
this repo's own test_human_bot.py suite or in this tool's own smoke runs).

METHODOLOGY (per the director's correction, 2026-07-13, superseding the
original brief's pre-selected hazard bins): "capture EVERYTHING per tick...
We don't know what factors will matter yet, the entire point of this
experiment is to find that out." This script is therefore a *raw, complete*
recorder and does NO feature engineering — no rolling windows, no weighted-
threat composites, no aggro/same-polygon booleans. Every tick's PRE-tick state
(what the bot observed when it chose its action) is logged verbatim,
alongside that tick's action and the resulting instantaneous metric deltas.
All derived features (rolling damage/kill windows, weighted threat, PCA
factors, the logistic hazard model...) are computed later, from this raw
stream, by `fit_factors.py` — never here.

Sidecar format: one `<out_dir>/<bot>_<seed>.jsonl.gz` per run. Line 1 is a
JSON *object* header (schema, run metadata, field order). Every subsequent
line is a JSON *array* (positional, matching the header's `fields` order) —
plain per-tick dicts would repeat ~20 string keys a few thousand times per
run; arrays keep the raw-and-complete capture cheap to write and to gzip.
The final line is a JSON object footer (outcome, tick count, wall clock).

Player loadout: GameSession's own default player_state is a fresh-spawn
loadout (knife+pistol, 48 9mm, no shell/cell) — wrong for segments copied
from l04-l07, which a real player reaches only after l02 (smg) and l03
(shotgun). `MID_GAME_STATE` below stands in for that campaign progress;
it's a run_farm concern (per-run simulated state), not baked into the
level, so the gauntlet level itself stays reusable at any assumed loadout.

Usage:
    uv run python tools/musiccal/run_farm.py --n-runs 200 --workers 32 \\
        --out-dir tools/musiccal/runs --bot human
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))

from perihelion.levels import load_level  # noqa: E402
from perihelion.sim import GameSession  # noqa: E402
from perihelion.testkit.bots import AggroBot  # noqa: E402
from perihelion.testkit.humanbot import DEFAULT_SKILL, HumanBot  # noqa: E402

DEFAULT_LEVEL = ROOT / "levels" / "gauntlet_cal.json"
DEFAULT_MAX_TICKS = 60 * 1200  # 20000 ticks ~= 333 sim-seconds; the gauntlet
# is long (7 corridors + 6 segments) so this is generous versus the 5-minute
# default elsewhere in the codebase.

# A plausible "just past l03" loadout — see module docstring. Never touched
# by density tuning; only the level's enemy counts are tuning knobs.
MID_GAME_STATE = dict(
    hp=100, max_hp=100,
    ammo={"9mm": 60, "shell": 16, "cell": 0},
    weapons=["knife", "pistol", "smg", "shotgun"],
    weapon="smg",
)

TICK_FIELDS = [
    "t", "hp", "polygon", "x", "y", "mx", "my", "fire", "alt",
    "ammo_9mm", "ammo_shell", "ammo_cell", "weapon", "n_weapons",
    "dead", "complete",
    "kills_d", "dmgtaken_d", "dmgdealt_d", "shots_d", "hits_d", "pickups_d",
    "enemies", "pickups",
]
ENEMY_FIELDS = ["id", "kind", "hp", "state", "hops", "x", "y"]
PICKUP_FIELDS = ["id", "kind", "hops", "x", "y"]


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _level_sha(level_path: Path) -> str:
    return hashlib.sha256(level_path.read_bytes()).hexdigest()[:16]


def run_one(level_path: str, seed: int, bot_name: str, skill: float,
            max_ticks: int, out_dir: str) -> dict:
    """Drive one run to completion/death/timeout, writing the full raw
    per-tick telemetry to a gzip JSONL sidecar. Returns a small summary
    dict (also embedded as the sidecar's footer line)."""
    t_wall0 = time.perf_counter()
    level_path = Path(level_path)
    level = load_level(level_path)
    state = dict(MID_GAME_STATE)
    if level_path.name == "gauntlet_cal2.json":
        import json as _j
        meta = _j.loads((Path(__file__).parent /
                         "gauntlet2_meta.json").read_text())
        lo = meta["loadout"]
        state = dict(weapons=["knife", "pistol", "smg", "shotgun", "rail",
                              "lightning", "tau", "hole", "scrap",
                              "gland"],
                     ammo=dict(lo["ammo"]), max_hp=lo["hp"], hp=lo["hp"],
                     dmg_taken_mul=lo["dmg_taken_mul"])
    session = GameSession(level, seed=seed, player_state=state)
    if bot_name == "human":
        bot = HumanBot(seed, skill=skill)
    elif bot_name == "aggro":
        bot = AggroBot(seed)
    else:
        raise ValueError(f"unknown bot {bot_name!r}")

    run_id = f"{bot_name}_{seed}"
    out_path = Path(out_dir) / f"{run_id}.jsonl.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = dict(
        schema=1, run_id=run_id, seed=seed, bot=bot_name,
        skill=skill if bot_name == "human" else None,
        level=str(level_path.relative_to(ROOT)) if level_path.is_absolute()
        else str(level_path),
        level_sha256=_level_sha(level_path), player_state=state,
        max_hp=state["max_hp"], fields=TICK_FIELDS,
        enemy_fields=ENEMY_FIELDS, pickup_fields=PICKUP_FIELDS,
        git_rev=_git_rev(), max_ticks=max_ticks,
    )

    error = None
    try:
        with gzip.open(out_path, "wt") as fh:
            fh.write(json.dumps(header) + "\n")
            prev_m = dict(session.metrics)
            t = 0
            while t < max_ticks and not session.dead and not session.complete:
                snap = session.snapshot()
                inp = bot.step(snap, session)
                session.tick(inp)
                t += 1
                m = session.metrics
                px, py = snap["pos"]
                enemies = [
                    [e["id"], e["kind"], round(e["hp"], 2), e["state"],
                     e["hops"], round(e["pos"][0], 1), round(e["pos"][1], 1)]
                    for e in snap["enemies"]
                ]
                pickups = [
                    [p["id"], p["kind"], p["hops"],
                     round(p["pos"][0], 1), round(p["pos"][1], 1)]
                    for p in snap["pickups"]
                ]
                row = [
                    session.tick_count, round(snap["hp"], 2), snap["polygon"],
                    round(px, 1), round(py, 1),
                    round(inp.mx, 3), round(inp.my, 3), int(inp.fire), int(inp.alt),
                    snap["ammo"].get("9mm", 0), snap["ammo"].get("shell", 0),
                    snap["ammo"].get("cell", 0), snap["weapon"], len(snap["weapons"]),
                    int(session.dead), int(session.complete),
                    m["kills"] - prev_m["kills"],
                    round(m["dmg_taken"] - prev_m["dmg_taken"], 3),
                    round(m["dmg_dealt"] - prev_m["dmg_dealt"], 3),
                    m["shots"] - prev_m["shots"], m["hits"] - prev_m["hits"],
                    m["pickups"] - prev_m["pickups"],
                    enemies, pickups,
                ]
                fh.write(json.dumps(row) + "\n")
                prev_m = dict(m)

            outcome = "complete" if session.complete else (
                "died" if session.dead else "timeout")
            footer = dict(footer=True, outcome=outcome, ticks=session.tick_count,
                          kills=session.metrics["kills"],
                          wallclock_s=round(time.perf_counter() - t_wall0, 3))
            fh.write(json.dumps(footer) + "\n")
    except Exception as exc:  # isolate one bad seed from the rest of the farm
        error = f"{type(exc).__name__}: {exc}"
        outcome = "error"
        footer = dict(footer=True, outcome=outcome, ticks=getattr(session, "tick_count", 0),
                      kills=0, wallclock_s=round(time.perf_counter() - t_wall0, 3))

    return dict(run_id=run_id, seed=seed, bot=bot_name, outcome=outcome,
                ticks=footer["ticks"], kills=footer["kills"],
                wallclock_s=footer["wallclock_s"], error=error, path=str(out_path))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", type=Path, default=DEFAULT_LEVEL)
    ap.add_argument("--n-runs", type=int, default=200)
    ap.add_argument("--seed0", type=int, default=0, help="first seed; seeds are seed0..seed0+n-1")
    ap.add_argument("--bot", choices=["human", "aggro"], default="human")
    ap.add_argument("--skill", type=float, default=DEFAULT_SKILL)
    ap.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "tools/musiccal/runs")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--summary-out", type=Path, default=None,
                     help="write the run-summary table as JSON here too")
    args = ap.parse_args(argv)

    seeds = list(range(args.seed0, args.seed0 + args.n_runs))
    t0 = time.perf_counter()
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, str(args.level), s, args.bot, args.skill,
                          args.max_ticks, str(args.out_dir)): s for s in seeds}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if r["error"]:
                print(f"[run_farm] seed={r['seed']} ERROR: {r['error']}", file=sys.stderr)
            if done % max(1, len(seeds) // 20) == 0 or done == len(seeds):
                print(f"[run_farm] {done}/{len(seeds)} runs done", file=sys.stderr)

    dt = time.perf_counter() - t0
    outcomes = {}
    for r in results:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    n = len(results)
    clear = outcomes.get("complete", 0) / n if n else 0.0
    print(f"\n[run_farm] {n} runs in {dt:.1f}s ({n / dt:.1f} runs/s) "
          f"bot={args.bot} level={args.level}")
    print(f"[run_farm] outcomes: {outcomes}  clear_rate={clear:.3f}")

    summary = dict(n_runs=n, bot=args.bot, level=str(args.level),
                   seed0=args.seed0, wallclock_s=round(dt, 2),
                   outcomes=outcomes, clear_rate=clear, results=results)
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(summary, indent=1))
    else:
        print(json.dumps(dict(n_runs=n, outcomes=outcomes, clear_rate=clear)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
