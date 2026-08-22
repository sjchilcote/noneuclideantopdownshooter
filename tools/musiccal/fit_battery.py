"""fit_battery — turn the corpus into deployable battery constants.

The deployed battery may use ONLY sim-observable signals (a human
player has no bot internals): enemy counts by kind/state/polygon-distance,
min hunter distance, aggro influx, damage taken, kill flow, the
player's own firing, scream recency, hp.

Fits nonnegative ridge models per truth on those features, then maps
the coefficients onto the music.py battery form (kind weights incl. a
separate ADJACENT table, influx and firing terms) and reports held-out
Spearman vs the old battery.

    uv run python tools/musiccal/fit_battery.py CORPUS_DIR OUT.json
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np

KINDS = ("husk", "mite", "spitter", "shrieker", "brute", "warden",
         "flicker")
HORIZON_DMG = 50
HORIZON_KILL = 30

# the deployable feature set (sim-observable only)
def rows_to_feats(rows):
    n = len(rows)
    def col(fn):
        return np.array([fn(r) for r in rows], dtype=np.float32)
    feats = {}
    for k in KINDS:
        feats[f"{k}_hunt_co"] = col(lambda r, k=k:
                                    r.get(f"{k}_hunt_co", 0)
                                    + r.get(f"{k}_ambush_co", 0))
        feats[f"{k}_hunt_adj"] = col(lambda r, k=k:
                                     r.get(f"{k}_hunt_adj", 0)
                                     + r.get(f"{k}_ambush_adj", 0))
        feats[f"{k}_idle_near"] = col(lambda r, k=k:
                                      r.get(f"{k}_idle_co", 0)
                                      + r.get(f"{k}_idle_adj", 0))
    feats["min_hunt_dist"] = col(lambda r: r["min_hunt_dist"]
                                 if r["min_hunt_dist"] >= 0 else 600.0)
    feats["crowd_pressure"] = col(lambda r: r["crowd_pressure"])
    feats["new_aggro"] = col(lambda r: r["new_aggro"])
    feats["dmg_rate"] = col(lambda r: r["dmg_rate"])
    feats["kills_delta"] = col(lambda r: r["kills_delta"])
    feats["fire_duty"] = col(lambda r: r["fire_duty"])
    feats["hp_deficit"] = col(lambda r: (100.0 - r["hp"]) / 100.0)
    feats["scream_recent"] = col(lambda r:
                                 max(0.0, 1.0 - r["since_scream"] / 300.0))
    # short trailing means for the volatile ones
    for k in ("new_aggro", "dmg_rate", "kills_delta", "crowd_pressure"):
        for w, tag in ((10, "1s"), (30, "3s")):
            kern = np.ones(w, dtype=np.float32) / w
            feats[f"{k}_m{tag}"] = np.convolve(
                feats[k], kern, mode="full")[:n].astype(np.float32)
    return feats


def main():
    corpus = Path(sys.argv[1])
    out = Path(sys.argv[2])
    X_parts, Y_parts, CUR_parts, RID = [], [], [], []
    ri = 0
    names = None
    for f in sorted(corpus.glob("run_*.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            lines = fh.read().splitlines()
        rows = [json.loads(l) for l in lines[1:]]
        if len(rows) <= HORIZON_DMG + 10:
            continue
        n = len(rows)
        feats = rows_to_feats(rows)
        if names is None:
            names = sorted(feats)
        M = np.column_stack([feats[k] for k in names])
        dmg = feats["dmg_rate"]
        kd = feats["kills_delta"]
        hunters = sum(feats[f"{k}_hunt_co"] + feats[f"{k}_hunt_adj"]
                      for k in KINDS)
        fut_dmg = np.array([dmg[i + 1:i + 1 + HORIZON_DMG].sum()
                            for i in range(n)], dtype=np.float32)
        fut_kill = np.array([kd[i + 1:i + 1 + HORIZON_KILL].sum()
                             for i in range(n)], dtype=np.float32)
        mowing = fut_kill * (fut_dmg < 8.0)
        calm = ((fut_dmg < 1.0) & (hunters < 0.5)).astype(np.float32)
        cut = n - HORIZON_DMG
        X_parts.append(M[:cut])
        Y_parts.append(np.column_stack([fut_dmg[:cut], mowing[:cut],
                                        calm[:cut]]))
        CUR_parts.append(np.array([r["cur_vals"] for r in rows[:cut]],
                                  dtype=np.float32))
        RID.append(np.full(cut, ri, dtype=np.int32))
        ri += 1
    X = np.concatenate(X_parts)
    Y = np.concatenate(Y_parts)
    CUR = np.concatenate(CUR_parts)
    RID = np.concatenate(RID)
    print(f"{ri} runs, {X.shape[0]} rows, {X.shape[1]} deployable feats")

    mu, sd = X.mean(0), X.std(0)
    sd[sd < 1e-9] = 1.0
    Z = (X - mu) / sd
    train = RID % 5 != 0
    test = ~train

    from scipy.stats import spearmanr
    from sklearn.linear_model import Ridge
    result = dict(names=names, mean=[float(v) for v in mu],
                  std=[float(v) for v in sd], fits={})
    for ti, tname in enumerate(("future_damage", "mowing", "calm")):
        y = Y[:, ti]
        model = Ridge(alpha=10.0).fit(Z[train], y[train])
        pred = model.predict(Z[test])
        r_new = spearmanr(pred[::10], y[test][::10]).statistic
        cur_col = CUR[:, {"future_damage": 2, "mowing": 1,
                          "calm": 0}[tname]]
        r_cur = spearmanr(cur_col[test][::10], y[test][::10]).statistic
        coefs = sorted(zip(names, model.coef_.tolist()),
                       key=lambda q: -abs(q[1]))
        result["fits"][tname] = dict(
            spearman_new=round(float(r_new), 3),
            spearman_old_battery=round(float(r_cur), 3),
            intercept=float(model.intercept_),
            coefs={k: round(float(v), 5) for k, v in coefs},
        )
        print(f"{tname}: new {r_new:.3f} vs old {r_cur:.3f} | "
              f"top {[c[0] for c in coefs[:6]]}")
    out.write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
