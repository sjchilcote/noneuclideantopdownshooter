"""collect_corpus — the factor-refit corpus (task #34).

Director 2026-07-16: "capture _all possible data_ and actually run the
factor analysis - it's likely that surprising things will act as
indicators!" One row every 6 ticks (10Hz), RAW observables — not the
current battery's outputs (those are logged too, but only for
comparison). Camera parity, full loadout: the exact substrate the
music will run on.

    uv run python tools/musiccal/collect_corpus.py SEED OUT.jsonl.gz
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))

from perihelion.levels import load_level                    # noqa: E402
from perihelion.sim import GameSession                     # noqa: E402
from perihelion.testkit.humanbot import HumanBot           # noqa: E402
from perihelion.testkit.loadouts import FULL_LOADOUT       # noqa: E402
from perihelion.music import read_inputs, values           # noqa: E402

KINDS = ("husk", "mite", "spitter", "shrieker", "brute", "warden",
         "flicker")
STATES = ("idle", "waking", "hunt", "lurk", "ambush")
SAMPLE_EVERY = 6


def run(seed: int, out_path: Path,
        level_path: str = "levels/gauntlet_cal3.json",
        max_ticks: int = 60 * 60 * 15) -> dict:
    import copy
    level = load_level(ROOT / level_path)
    s = GameSession(level, seed=seed,
                    player_state=copy.deepcopy(FULL_LOADOUT),
                    screen=(640, 360), zoom=0.45)
    bot = HumanBot(seed)
    rows = []
    prev_hp = 100.0
    prev_kills = 0
    prev_hunt_ids: set = set()
    prev_min_dist = None
    fire_win = []          # fire flags, last second
    scream_tick = -10_000
    t = 0
    while t < max_ticks and not s.dead and not s.complete:
        snap = s.snapshot()
        inp = bot.step(snap, s)
        # scream events pass through fx before the app drains them --
        # nobody drains in this harness, so scan the tail cheaply
        for ev in s.fx[-8:]:
            if ev and ev[0] == "scream":
                scream_tick = t
        s.tick(inp)
        t += 1
        fire_win.append(1 if inp.fire else 0)
        if len(fire_win) > 60:
            fire_win.pop(0)
        if t % SAMPLE_EVERY:
            continue

        px, py = snap["pos"]
        ppolygon = snap["polygon"]
        counts = {f"{k}_{st}_{loc}": 0 for k in KINDS for st in STATES
                  for loc in ("co", "adj")}
        min_hunt_d = None
        sum_inv_d = 0.0
        hunt_ids = set()
        n_visible = 0
        for e in snap["enemies"]:
            hops = e["hops"]
            if not 0 <= hops <= 1:
                continue
            loc = "co" if hops == 0 else "adj"
            key = f'{e["kind"]}_{e["state"]}_{loc}'
            if key in counts:
                counts[key] += 1
            if e["state"] in ("hunt", "ambush"):
                hunt_ids.add(e["id"])
            if hops == 0:
                n_visible += 1
                d = math.hypot(e["pos"][0] - px, e["pos"][1] - py)
                if e["state"] in ("hunt", "ambush"):
                    min_hunt_d = d if min_hunt_d is None \
                        else min(min_hunt_d, d)
                    sum_inv_d += 1.0 / max(d, 10.0)
        new_aggro = len(hunt_ids - prev_hunt_ids)
        prev_hunt_ids = hunt_ids
        closing = 0.0
        if min_hunt_d is not None and prev_min_dist is not None:
            closing = (prev_min_dist - min_hunt_d) / SAMPLE_EVERY * 60.0
        prev_min_dist = min_hunt_d

        sentries_near = sum(
            1 for tid in s.sentries
            if s.sim.exists(tid) and
            0 <= s.sim.hop_distance(s.sim.get_polygon(tid), ppolygon) <= 1)

        row = dict(
            t=t,
            hp=snap["hp"],
            dmg_rate=max(0.0, prev_hp - snap["hp"]),
            kills_delta=s.metrics["kills"] - prev_kills,
            fire_duty=sum(fire_win) / max(1, len(fire_win)),
            weapon=snap["weapon"],
            lightning_ready=int(snap["lightning_ready"]),
            min_hunt_dist=min_hunt_d if min_hunt_d is not None else -1.0,
            closing_speed=closing,
            crowd_pressure=round(sum_inv_d, 4),
            new_aggro=new_aggro,
            since_scream=min(600, t - scream_tick),
            sentries_near=sentries_near,
            retreat_gain=round(getattr(bot, "_retreat_gain", 0.0), 3),
            planted=int(getattr(bot, "_planted", False)),
            entry_caution=int(getattr(bot, "_entry_caution", False)),
            escape=int(getattr(bot, "_escape_ticks", 0) > 0),
            # the CURRENT battery, for comparison only
            cur_vals=list(values(read_inputs(s))),
            **{k: v for k, v in counts.items() if v},
        )
        prev_hp = snap["hp"]
        prev_kills = s.metrics["kills"]
        rows.append(row)

    meta = dict(seed=seed,
                outcome="complete" if s.complete else
                ("death" if s.dead else "timeout"),
                ticks=t, kills=s.metrics["kills"],
                dmg_taken=round(s.metrics["dmg_taken"], 1))
    with gzip.open(out_path, "wt") as f:
        f.write(json.dumps(meta) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return meta


if __name__ == "__main__":
    meta = run(int(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(meta))
