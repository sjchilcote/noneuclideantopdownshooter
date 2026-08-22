"""tune_battery2 — replay the corpus through the STRUCTURED new battery
and tune its constants until it approaches the ridge ceiling.

The new battery form (interpretable, engine-computable, sim-observable):

  danger  = sum_k W[kind, co|adj] + CROWD_W*crowd + INFLUX_W*influx_ema
            + SCREAM_W*scream_recent + DMG_W*dmg_ema
  stalwart = 1 - exp(-danger / KNEE)
  mow_drive = KILL_W*kill_ema + FIRE_W*firing + TRASH_W*trash_near
  contempt = (1-exp(-mow_drive/MOW_KNEE)) * (1-stalwart)
             * (1 - min(1, influx_ema/WAVE_CUT)) * (0.5+0.5*hp/100)
  prayer  = max(FLOOR, 1 - min(1, danger/ENGAGE_KNEE + FIRE_PRAY*firing))

    uv run python tools/musiccal/tune_battery2.py CORPUS_DIR
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

KINDS = ("husk", "mite", "spitter", "shrieker", "brute", "warden",
         "flicker")
HORIZON_DMG = 50
HORIZON_KILL = 30

# corpus-derived structure (per-unit ridge ratios, husk_co = 1)
W_CO = dict(warden=12.0, brute=1.0, flicker=1.9, husk=1.0, mite=0.8,
            spitter=0.6, shrieker=0.15)
W_ADJ = dict(warden=8.5, brute=0.3, flicker=0.2, husk=0.8, mite=0.3,
             spitter=0.3, shrieker=0.1)
P = dict(CROWD_W=11.0, INFLUX_W=6.0, SCREAM_W=2.2, DMG_W=1.5,
         FIRED_W=1.5, KNEE=14.0, KILL_W=1.0, FIRE_W=0.5, TRASH_W=0.15,
         MOW_KNEE=1.5, WAVE_CUT=1.5, ENGAGE_KNEE=3.5, FIRE_PRAY=0.4,
         FLOOR=0.12)


def ema(x, tau_rows):
    out = np.empty_like(x)
    a = 1.0 / tau_rows
    acc = 0.0
    for i, v in enumerate(x):
        acc += a * (v - acc)
        out[i] = acc
    return out


def battery(rows, p):
    n = len(rows)
    g = lambda k: np.array([r.get(k, 0) for r in rows], dtype=np.float32)
    danger = np.zeros(n, dtype=np.float32)
    trash = np.zeros(n, dtype=np.float32)
    for k in KINDS:
        co = g(f"{k}_hunt_co") + g(f"{k}_ambush_co")
        adj = g(f"{k}_hunt_adj") + g(f"{k}_ambush_adj")
        danger += W_CO[k] * co + W_ADJ[k] * adj
        if k in ("mite", "husk"):
            trash += co + g(f"{k}_idle_co")
    fire = g("fire_duty")
    crowd = g("crowd_pressure")
    influx = ema(g("new_aggro"), 30.0)
    scream = np.maximum(0.0, 1.0 - g("since_scream") / 300.0)
    dmg = ema(g("dmg_rate"), 30.0)
    kill = ema(g("kills_delta"), 30.0)
    hp = g("hp")
    danger = danger + p["CROWD_W"] * crowd + p["INFLUX_W"] * influx * 10 \
        + 0.0 * scream + p["DMG_W"] * dmg * 10 \
        + p["FIRED_W"] * fire
    stal = 1.0 - np.exp(-danger / p["KNEE"])
    mow = p["KILL_W"] * kill * 10 + p["FIRE_W"] * fire \
        + p["TRASH_W"] * trash
    cont = 1.0 - np.exp(-mow / p["MOW_KNEE"])   # independent axis:
    #   no (1-stal) crush, no wave guard, no hp scale (director)
    pray = np.maximum(p["FLOOR"],
                      1.0 - np.minimum(1.0, danger / p["ENGAGE_KNEE"]
                                       + p["FIRE_PRAY"] * fire))
    return pray, cont, stal


def main():
    corpus = Path(sys.argv[1])
    packs = []
    for f in sorted(corpus.glob("run_*.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            lines = fh.read().splitlines()
        rows = [json.loads(l) for l in lines[1:]]
        if len(rows) <= HORIZON_DMG + 10:
            continue
        n = len(rows)
        dmg = np.array([r["dmg_rate"] for r in rows], dtype=np.float32)
        kd = np.array([r["kills_delta"] for r in rows], dtype=np.float32)
        hunters = np.zeros(n, dtype=np.float32)
        for r_i, r in enumerate(rows):
            hunters[r_i] = sum(v for k, v in r.items()
                               if ("_hunt_" in k or "_ambush_" in k))
        fut_dmg = np.array([dmg[i + 1:i + 1 + HORIZON_DMG].sum()
                            for i in range(n)], dtype=np.float32)
        fut_kill = np.array([kd[i + 1:i + 1 + HORIZON_KILL].sum()
                             for i in range(n)], dtype=np.float32)
        mowing = fut_kill    # director 2026-07-16: CONTEMPT is damage
        #   OUTPUT, ungated -- a boss fight is stalwart AND contempt
        calm = ((fut_dmg < 1.0) & (hunters < 0.5)).astype(np.float32)
        cut = n - HORIZON_DMG
        old = np.array([r["cur_vals"] for r in rows[:cut]],
                       dtype=np.float32)
        packs.append((rows[:cut], fut_dmg[:cut], mowing[:cut],
                      calm[:cut], old))

    def score(p):
        preds = {0: [], 1: [], 2: []}
        Ys = {0: [], 1: [], 2: []}
        for rows, fd, mw, cl, _old in packs:
            pr, ct, st = battery(rows, p)
            for i, (v, y) in enumerate(((st, fd), (ct, mw), (pr, cl))):
                preds[i].append(v)
                Ys[i].append(y)
        out = []
        for i in range(3):
            v = np.concatenate(preds[i])[::7]
            y = np.concatenate(Ys[i])[::7]
            out.append(spearmanr(v, y).statistic)
        return out

    base = score(P)
    print(f"NEW battery: stalwart~dmg {base[0]:.3f}  contempt~mow "
          f"{base[1]:.3f}  prayer~calm {base[2]:.3f}")
    olds = [np.concatenate([o[:, j] for *_x, o in packs])[::7]
            for j in (2, 1, 0)]
    ys = [np.concatenate([p[1] for p in packs])[::7],
          np.concatenate([p[2] for p in packs])[::7],
          np.concatenate([p[3] for p in packs])[::7]]
    for nm, o, y in zip(("stalwart", "contempt", "prayer"), olds, ys):
        print(f"OLD {nm}: {spearmanr(o, y).statistic:.3f}")

    # per-channel coordinate descent: the channels own disjoint knobs,
    # so optimize each on its own truth instead of trading them off
    CH_KEYS = {0: ("CROWD_W", "INFLUX_W", "SCREAM_W", "DMG_W",
                   "FIRED_W", "KNEE"),
               1: ("KILL_W", "FIRE_W", "TRASH_W", "MOW_KNEE",
                   "WAVE_CUT"),
               2: ("ENGAGE_KNEE", "FIRE_PRAY")}
    best = dict(P)
    for ch in (0, 1, 2):
        bestv = score(best)[ch]
        for _round in range(3):
            for key in CH_KEYS[ch]:
                for mul in (0.4, 0.6, 0.8, 1.25, 1.7, 2.5):
                    q = dict(best)
                    q[key] = best[key] * mul
                    v = score(q)[ch]
                    if v > bestv + 1e-4:
                        best, bestv = q, v
    fin = score(best)
    print(f"TUNED: stalwart {fin[0]:.3f}  contempt {fin[1]:.3f}  "
          f"prayer {fin[2]:.3f}")
    print("constants:", json.dumps({k: round(v, 3)
                                    for k, v in best.items()}))


if __name__ == "__main__":
    main()
