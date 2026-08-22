"""tune_pass_rate — measure bot pass rate on a gauntlet config.

    uv run python tools/musiccal/tune_pass_rate.py --level levels/gauntlet_cal2.json --k 20

Target (director 2026-07-16): 50% completion by the human bot, reached
by MOVING/spreading enemies and BUFFING the player — never by thinning
the population. Player runs FULL loadout (all weapons, deep ammo).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))

from perihelion.testkit.loadouts import FULL_LOADOUT  # noqa: E402


def one(args):
    level_path, seed, skill, max_ticks, hp_buff, resist = args
    from perihelion.levels import load_level
    from perihelion.sim import GameSession
    from perihelion.testkit.humanbot import HumanBot
    state = dict(FULL_LOADOUT)
    state["max_hp"] = state["hp"] = FULL_LOADOUT["max_hp"] + hp_buff
    state["dmg_taken_mul"] = resist
    level = load_level(Path(level_path))
    # CAMERA PARITY (2026-07-16): HumanBot perception is the renderer's
    # own portal-visibility query -- it sees exactly the camera frustum.
    # Farming at the sim default (480x270, zoom 1.35) measured a
    # different bot than the shipped camera (640x360, zoom 0.45, the
    # director's 3x-zoomed-out order): seed 1011 complete/176 kills at
    # the narrow camera, timeout/103 at the real one. Calibration runs
    # AT the shipping camera or it calibrates nothing.
    s = GameSession(level, seed=seed, player_state=state,
                    screen=(640, 360), zoom=0.45)
    bot = HumanBot(seed, skill=skill)
    t = 0
    import collections
    weapon_ticks = collections.Counter()
    while t < max_ticks and not s.dead and not s.complete:
        snap = s.snapshot()
        inp = bot.step(snap, s)
        s.tick(inp)
        t += 1
        weapon_ticks[snap["weapon"]] += 1
    snap = s.snapshot()
    near = {}
    for e in snap["enemies"]:
        if e["hops"] == 0:
            near[e["kind"]] = near.get(e["kind"], 0) + 1
    return dict(seed=seed, outcome="complete" if s.complete else
                ("death" if s.dead else "timeout"),
                hp=round(getattr(s, "hp", 0.0), 1),
                ticks=t, kills=s.metrics["kills"],
                dmg_taken=round(s.metrics["dmg_taken"], 1),
                polygon=snap["polygon"], near=near,
                ammo=snap["ammo"], weapons_used=dict(weapon_ticks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="levels/gauntlet_cal2.json")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--skill", type=float, default=None)
    ap.add_argument("--max-ticks", type=int, default=60 * 60 * 8)
    ap.add_argument("--hp-buff", type=int, default=0)
    ap.add_argument("--resist", type=float, default=1.0)
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args()
    if a.skill is None:
        from perihelion.testkit.humanbot import DEFAULT_SKILL
        a.skill = DEFAULT_SKILL
    jobs = [(a.level, 1000 + i, a.skill, a.max_ticks, a.hp_buff, a.resist)
            for i in range(a.k)]
    results = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(one, j) for j in jobs]
        for f in as_completed(futs):
            results.append(f.result())
    n = len(results)
    comp = sum(1 for r in results if r["outcome"] == "complete")
    death = sum(1 for r in results if r["outcome"] == "death")
    to = n - comp - death
    kills = sorted(r["kills"] for r in results)
    print(f"pass rate: {comp}/{n} = {comp/n:.0%}  "
          f"(death {death}, timeout {to})")
    print(f"kills median {kills[n//2]}, min {kills[0]}, max {kills[-1]}")
    import collections
    polygons = collections.Counter(r["polygon"] for r in results
                                if r["outcome"] == "death")
    print("death polygons:", dict(polygons.most_common(6)))
    nears = collections.Counter()
    for r in results:
        for k, v in r.get("near", {}).items():
            nears[k] += v
    print("kinds present at deaths:", dict(nears.most_common()))
    ticks = sorted(r["ticks"] for r in results)
    print("death ticks: min", ticks[0], "median", ticks[len(ticks)//2])
    wu = collections.Counter()
    for r in results:
        for w, n_ in r.get("weapons_used", {}).items():
            wu[w] += n_
    print("weapon usage (ticks):", dict(wu.most_common()))
    print("ammo at death (first 3):",
          [r["ammo"] for r in results[:3]])


if __name__ == "__main__":
    main()
