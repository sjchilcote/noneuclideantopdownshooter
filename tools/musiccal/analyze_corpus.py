"""analyze_corpus — the actual factor analysis (task #34).

Director: "actually run the factor analysis - it's likely that
surprising things will act as indicators!"

Ground truths the music should express (operationalized):
  DANGER   (stalwart-truth): damage the player actually takes over the
           NEXT 5 seconds — the odds as they truly are.
  MOWING   (contempt-truth): kill rate over the next 3 seconds while
           incoming damage stays low — trash dying to a healthy player.
  CALM     (prayer-truth): no hunters and no damage for the next 5s.

Pipeline: load runs -> feature matrix (raw observables + short trailing
means) -> FactorAnalysis loadings (the latent structure) -> per-feature
predictive screen against each truth (Spearman) -> ridge fit vs the
CURRENT battery's values as baseline -> report + fitted weights JSON.

    uv run python tools/musiccal/analyze_corpus.py CORPUS_DIR OUT.json
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np

HORIZON_DMG = 50      # rows (10Hz) -> 5s
HORIZON_KILL = 30     # 3s


def load_runs(corpus: Path):
    runs = []
    for f in sorted(corpus.glob("run_*.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            lines = fh.read().splitlines()
        meta = json.loads(lines[0])
        rows = [json.loads(l) for l in lines[1:]]
        if len(rows) > 40:
            runs.append((meta, rows))
    return runs


def build_matrix(runs):
    # collect the full key universe (count keys are sparse)
    keys = set()
    for _, rows in runs:
        for r in rows[:: max(1, len(rows) // 50)]:
            keys.update(r.keys())
    drop = {"t", "weapon", "cur_vals"}
    feat_keys = sorted(k for k in keys if k not in drop)

    X_parts, y_parts, cur_parts, run_ids = [], [], [], []
    for ri, (_meta, rows) in enumerate(runs):
        n = len(rows)
        base = np.zeros((n, len(feat_keys)), dtype=np.float32)
        for i, r in enumerate(rows):
            for j, k in enumerate(feat_keys):
                base[i, j] = float(r.get(k, 0.0))
        # trailing means (1s and 3s) for the volatile channels
        vol = [feat_keys.index(k) for k in
               ("dmg_rate", "new_aggro", "kills_delta", "closing_speed",
                "crowd_pressure") if k in feat_keys]
        extras = []
        extra_names = []
        for w, tag in ((10, "1s"), (30, "3s")):
            kern = np.ones(w, dtype=np.float32) / w
            for j in vol:
                sm = np.convolve(base[:, j], kern, mode="full")[:n]
                extras.append(sm.astype(np.float32))
                extra_names.append(f"{feat_keys[j]}_m{tag}")
        X = np.column_stack([base] + [e[:, None] for e in extras])

        dmg = base[:, feat_keys.index("dmg_rate")]
        kills = base[:, feat_keys.index("kills_delta")]
        hunters = np.zeros(n, dtype=np.float32)
        for j, k in enumerate(feat_keys):
            if "_hunt_" in k or "_ambush_" in k:
                hunters += base[:, j]
        fut_dmg = np.array([dmg[i + 1:i + 1 + HORIZON_DMG].sum()
                            for i in range(n)], dtype=np.float32)
        fut_kill = np.array([kills[i + 1:i + 1 + HORIZON_KILL].sum()
                             for i in range(n)], dtype=np.float32)
        mowing = fut_kill * (fut_dmg < 8.0)
        calm = ((fut_dmg < 1.0) & (hunters < 0.5)).astype(np.float32)

        cut = n - HORIZON_DMG          # rows with a full future window
        X_parts.append(X[:cut])
        y_parts.append(np.column_stack([fut_dmg[:cut], mowing[:cut],
                                        calm[:cut]]))
        cur_parts.append(np.array([r["cur_vals"] for r in rows[:cut]],
                                  dtype=np.float32))
        run_ids.append(np.full(cut, ri, dtype=np.int32))
    names = feat_keys + extra_names
    return (np.concatenate(X_parts), np.concatenate(y_parts),
            np.concatenate(cur_parts), np.concatenate(run_ids), names)


def main():
    corpus = Path(sys.argv[1])
    out = Path(sys.argv[2])
    runs = load_runs(corpus)
    print(f"runs: {len(runs)}  "
          f"({sum(1 for m, _ in runs if m['outcome']=='complete')} "
          f"complete)")
    X, Y, CUR, RID, names = build_matrix(runs)
    print(f"matrix: {X.shape[0]} rows x {X.shape[1]} features")

    # standardize (guard dead columns)
    mu, sd = X.mean(0), X.std(0)
    sd[sd < 1e-9] = 1.0
    Z = (X - mu) / sd

    # ---- factor analysis: the latent structure ----
    from sklearn.decomposition import FactorAnalysis
    fa = FactorAnalysis(n_components=6, random_state=0)
    fa.fit(Z[:: max(1, len(Z) // 60000)])
    loadings = fa.components_
    factors = []
    for fi in range(loadings.shape[0]):
        idx = np.argsort(-np.abs(loadings[fi]))[:8]
        factors.append([(names[j], round(float(loadings[fi, j]), 3))
                        for j in idx])

    # ---- per-feature predictive screen (Spearman vs each truth) ----
    from scipy.stats import spearmanr
    sub = slice(None, None, max(1, len(Z) // 80000))
    screens = {}
    for ti, tname in enumerate(("future_damage", "mowing", "calm")):
        rows = []
        for j, nm in enumerate(names):
            r = spearmanr(Z[sub, j], Y[sub, ti]).statistic
            if np.isfinite(r):
                rows.append((nm, round(float(r), 3)))
        rows.sort(key=lambda q: -abs(q[1]))
        screens[tname] = rows[:20]

    # ---- ridge fit vs the current battery (grouped split by run) ----
    from sklearn.linear_model import Ridge
    train = RID % 5 != 0
    test = ~train
    report_fits = {}
    for ti, tname in enumerate(("future_damage", "mowing", "calm")):
        y = Y[:, ti]
        model = Ridge(alpha=10.0).fit(Z[train], y[train])
        pred = model.predict(Z[test])
        ss = 1 - np.sum((pred - y[test]) ** 2) / \
            max(1e-9, np.sum((y[test] - y[test].mean()) ** 2))
        cur_col = CUR[:, {"future_damage": 2, "mowing": 1,
                          "calm": 0}[tname]]
        r_cur = spearmanr(cur_col[test][:: 10], y[test][:: 10]).statistic
        r_new = spearmanr(pred[:: 10], y[test][:: 10]).statistic
        coef_idx = np.argsort(-np.abs(model.coef_))[:12]
        report_fits[tname] = dict(
            r2_ridge=round(float(ss), 3),
            spearman_current_battery=round(float(r_cur), 3),
            spearman_ridge=round(float(r_new), 3),
            top_coefs=[(names[j], round(float(model.coef_[j]), 4))
                       for j in coef_idx],
        )

    result = dict(runs=len(runs), rows=int(X.shape[0]),
                  factors=factors, screens=screens, fits=report_fits,
                  standardization=dict(
                      names=names, mean=[round(float(v), 5) for v in mu],
                      std=[round(float(v), 5) for v in sd]))
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps(dict(fits=report_fits), indent=1))
    print("factors:")
    for fi, fac in enumerate(factors):
        print(f"  F{fi}: {fac[:5]}")
    print("top future_damage indicators:", screens["future_damage"][:8])


if __name__ == "__main__":
    main()
