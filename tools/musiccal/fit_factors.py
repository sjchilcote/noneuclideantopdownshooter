"""tools/musiccal/fit_factors.py — the calibration farm's analysis pass.

METHODOLOGY (director's correction, 2026-07-13, ratified — supersedes the
original brief's pre-selected hazard bins): "we're running the tests
capturing all possible data, calculating those north star values that can
only be calculated from the total of all runs, then using them with the
raw events of the run to run factor analysis to determine what factors
allow us to determine the probability of death at this given moment during
live gameplay."

Pipeline:
  1. Load every run's raw per-tick telemetry (tools/musiccal/run_farm.py's
     gzip JSONL sidecars) and join in static polygon facts (area, portal
     count, light count, zone) from levels/gauntlet_cal.json +
     gauntlet_meta.json.
  2. Compute a WIDE derived-feature matrix from the raw stream ONLY —
     rolling damage/kill/shot windows, aggro composition, polygon statics,
     loadout — never a hand-picked shortlist.
  3. Compute north-star labels that need the FULL ensemble / whole-run
     knowledge unavailable to any single tick: death-within-horizon
     (3s/5s/10s), correctly censoring the tail of timeout runs.
  4. Factor discovery: PCA on the standardized feature matrix (loadings —
     which raw observables move together) PLUS a sparse (L1) logistic
     regression predicting death-within-3s, regularization strength
     selected by group-aware (per-RUN) cross-validation, evaluated on a
     held-out RUN split never touched during fitting (out-of-sample AUC +
     calibration curve). A single-feature "weighted threat only" logistic
     model is fit the same way as the ORIGINAL brief's baseline comparison.
  5. STALWART = the fitted P(death-in-3s), percentile-ranked against the
     training population's own distribution (the brief's CDF-normalization
     survives the methodology correction). CONTEMPT (kills/sec) and PRAYER
     (1/(1+n_aggro)) stay directly-observed, per the correction.
  6. Saturation: the per-position (per-polygon) hazard estimate and its
     standard error, recomputed on cumulative run-count prefixes (a valid
     stand-in for "rerunning at each batch size", since seeds are i.i.d.).
  7. Sanity statistics computed here (once, on the full/real dataset) and
     pinned by game/tests/test_gauntlet_calibration.py: hazard higher in
     combat than corridor/loot (with a shuffled-label permutation control
     that must NOT show the effect), prayer ~1 in loot polygons. CONTEMPT
     trash-vs-heavy uses a small auxiliary full-density batch (see
     `_contempt_trash_vs_heavy_aux`) because the density needed for a ~50%
     clear rate pruned every brute/shrieker/warden out of the tuned
     gauntlet — a real, reportable contradiction of the brief's implicit
     assumption that density scaling would preserve the full roster mix
     (see FITTING_REPORT.md's caveats).

Output: tools/musiccal/factor_model.json (the fitted model + curves + raw
stats + sanity results) and FITTING_REPORT.md + hazard_by_position.png
(written by report.py's companion pass — see `write_report`).

Usage:
    uv run python tools/musiccal/fit_factors.py --runs-dir tools/musiccal/runs
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from perihelion.levels import load_level  # noqa: E402
from perihelion.sim import ENEMIES  # noqa: E402

SCORE = {k: v["score"] for k, v in ENEMIES.items()}
WEAK_KINDS = {k for k, v in ENEMIES.items() if v["score"] <= 1}  # husk, mite
HEAVY_KINDS = {"brute", "shrieker", "warden"}  # matches build_gauntlet.py's
# segment-level HEAVY_KINDS exactly, for a per-tick condition precise enough
# to distinguish "fighting the elite" from "in an elite-tagged segment but
# currently only engaging its accompanying trash"
AGGRO_STATES = {"hunt", "ambush"}

WINDOWS = {"1s": 60, "3s": 180, "10s": 600}
HORIZONS = {"3s": 180, "5s": 300, "10s": 600}
PRIMARY_HORIZON = "3s"

WEAPON_DUMMIES = ["knife", "pistol", "smg", "shotgun"]

# The wide model-feature set (see module docstring step 2). Excludes raw
# identifiers (t, polygon id, weapon string) and things that don't generalize
# beyond this one level (a specific segment tag) -- those stay as grouping
# metadata for the sanity checks, never as model inputs.
FEATURES = [
    "hp", "total_ammo", "ammo_9mm", "ammo_shell", "ammo_cell", "n_weapons",
    "dmgtaken_1s", "dmgtaken_3s", "dmgtaken_10s",
    "kills_1s", "kills_3s", "kills_10s",
    "shots_3s", "hits_3s", "accuracy_3s", "fire_1s",
    "n_aggro", "n_aggro_same_polygon", "weak_aggro_same_polygon",
    "weighted_threat_active", "min_enemy_dist_capped", "has_same_polygon_threat",
    "n_pickups_polygon", "speed", "time_in_polygon",
    "area", "n_portals", "n_lights", "is_combat_zone", "is_loot_zone",
] + [f"weapon_is_{w}" for w in WEAPON_DUMMIES]

BASELINE_FEATURES = ["weighted_threat_active"]  # the original brief's pre-selected knob


# ---------------------------------------------------------------------------
# polygon statics
# ---------------------------------------------------------------------------

def _shoelace_area(verts: list[tuple[float, float]]) -> float:
    n = len(verts)
    a = 0.0
    for i in range(n):
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


def load_polygon_features(level_path: Path, meta_path: Path) -> dict[int, dict]:
    level = load_level(level_path)
    meta = json.loads(meta_path.read_text())
    zones = meta["zones"]
    out: dict[int, dict] = {}
    n_portals = {i: 0 for i in range(len(level.polygon_verts))}
    for a, _, bb, _ in level.connects:
        n_portals[a] += 1
        n_portals[bb] += 1
    n_lights = {i: 0 for i in range(len(level.polygon_verts))}
    for lt in level.lights:
        n_lights[lt.polygon] += 1
    for i, verts in enumerate(level.polygon_verts):
        z = zones.get(str(i), {"zone": "unknown"})
        out[i] = dict(area=_shoelace_area(verts), n_portals=n_portals[i],
                      n_lights=n_lights[i], zone=z["zone"],
                      segment=z.get("segment"), is_heavy=bool(z.get("is_heavy", False)))
    return out, meta


# ---------------------------------------------------------------------------
# per-run raw -> wide feature rows
# ---------------------------------------------------------------------------

def iter_run_files(runs_dir: Path):
    for p in sorted(runs_dir.glob("*.jsonl.gz")):
        yield p


def _read_run(path: Path):
    header = None
    rows = []
    footer = None
    with gzip.open(path, "rt") as fh:
        for line in fh:
            obj = json.loads(line)
            if header is None:
                header = obj
                continue
            if isinstance(obj, dict) and obj.get("footer"):
                footer = obj
                continue
            rows.append(obj)
    return header, rows, footer


def _rolling_sum(arr: np.ndarray, w: int) -> np.ndarray:
    n = len(arr)
    c = np.concatenate((np.zeros(1, dtype=arr.dtype), np.cumsum(arr)))
    hi = np.arange(1, n + 1)
    lo = np.maximum(0, hi - w)
    return (c[hi] - c[lo]).astype(arr.dtype, copy=False)


def process_run(path: Path, polygon_features: dict[int, dict]) -> dict[str, np.ndarray]:
    """Returns a dict of equal-length 1-D numpy arrays (one entry per
    FEATURES name plus label/grouping/zone columns), one row per tick."""
    header, rows, footer = _read_run(path)
    fields = header["fields"]
    idx = {name: i for i, name in enumerate(fields)}
    n = len(rows)
    if n == 0:
        return None

    def col(name, dtype=np.float32):
        return np.array([r[idx[name]] for r in rows], dtype=dtype)

    hp = col("hp")
    polygon = col("polygon", np.int32)
    x = col("x")
    y = col("y")
    dmgtaken = col("dmgtaken_d")
    kills = col("kills_d")
    shots = col("shots_d")
    hits = col("hits_d")
    fire = col("fire")
    ammo9 = col("ammo_9mm")
    ammoshell = col("ammo_shell")
    ammocell = col("ammo_cell")
    nweap = col("n_weapons")
    weapon = [r[idx["weapon"]] for r in rows]
    ts = col("t", np.int32)

    dmgtaken_1s = _rolling_sum(dmgtaken, WINDOWS["1s"])
    dmgtaken_3s = _rolling_sum(dmgtaken, WINDOWS["3s"])
    dmgtaken_10s = _rolling_sum(dmgtaken, WINDOWS["10s"])
    kills_1s = _rolling_sum(kills, WINDOWS["1s"])
    kills_3s = _rolling_sum(kills, WINDOWS["3s"])
    kills_10s = _rolling_sum(kills, WINDOWS["10s"])
    shots_3s = _rolling_sum(shots, WINDOWS["3s"])
    hits_3s = _rolling_sum(hits, WINDOWS["3s"])
    fire_1s = _rolling_sum(fire, WINDOWS["1s"])
    accuracy_3s = np.divide(hits_3s, shots_3s,
                            out=np.zeros(n, dtype=np.float32), where=shots_3s > 0)

    same_polygon = np.concatenate(([False], polygon[1:] == polygon[:-1]))
    idxs = np.arange(n)
    reset_idx = np.where(~same_polygon, idxs, 0)
    last_reset = np.maximum.accumulate(reset_idx)
    time_in_polygon = idxs - last_reset
    dx = np.diff(x, prepend=x[0])
    dy = np.diff(y, prepend=y[0])
    dist = np.hypot(dx, dy)
    speed = np.where(same_polygon, dist * 60.0, 0.0)

    n_aggro = np.zeros(n, dtype=np.int16)
    n_aggro_same_polygon = np.zeros(n, dtype=np.int16)
    weak_aggro_same_polygon = np.zeros(n, dtype=np.int16)
    heavy_aggro_same_polygon = np.zeros(n, dtype=np.int16)
    weighted_threat_active = np.zeros(n, dtype=np.float32)
    min_enemy_dist = np.full(n, np.nan, dtype=np.float32)
    n_pickups_polygon = np.zeros(n, dtype=np.int16)

    ecol, pcol = idx["enemies"], idx["pickups"]
    xcol, ycol = idx["x"], idx["y"]
    for i, r in enumerate(rows):
        agg = agg_same = weak_same = heavy_same = 0
        wt = 0.0
        mind = None
        px, py = r[xcol], r[ycol]
        for eid, kind, ehp, state, hops, ex, ey in r[ecol]:
            if state not in AGGRO_STATES:
                continue
            agg += 1
            wt += SCORE.get(kind, 1) / (1.0 + hops)
            if hops == 0:
                agg_same += 1
                if kind in WEAK_KINDS:
                    weak_same += 1
                if kind in HEAVY_KINDS:
                    heavy_same += 1
                d = math.hypot(ex - px, ey - py)
                if mind is None or d < mind:
                    mind = d
        n_aggro[i] = agg
        n_aggro_same_polygon[i] = agg_same
        weak_aggro_same_polygon[i] = weak_same
        heavy_aggro_same_polygon[i] = heavy_same
        weighted_threat_active[i] = wt
        min_enemy_dist[i] = mind if mind is not None else np.nan
        n_pickups_polygon[i] = sum(1 for p in r[pcol] if p[2] == 0)

    has_same_polygon_threat = (~np.isnan(min_enemy_dist)).astype(np.float32)
    min_enemy_dist_capped = np.where(np.isnan(min_enemy_dist), np.float32(500.0),
                                     np.minimum(min_enemy_dist, np.float32(500.0)))

    # Polygon statics are constant per polygon id -- resolve through a small
    # per-polygon lookup array (one entry per distinct polygon, not per tick) so
    # the run's dominant memory cost stays the per-tick numeric columns.
    n_polygons = max(polygon_features) + 1
    zone_lut = np.array([polygon_features.get(r, {}).get("zone", "unknown")
                         for r in range(n_polygons)], dtype=object)
    area_lut = np.array([polygon_features.get(r, {}).get("area", 0.0)
                         for r in range(n_polygons)], dtype=np.float32)
    portals_lut = np.array([polygon_features.get(r, {}).get("n_portals", 0)
                            for r in range(n_polygons)], dtype=np.int16)
    lights_lut = np.array([polygon_features.get(r, {}).get("n_lights", 0)
                           for r in range(n_polygons)], dtype=np.int16)
    segment_lut = np.array([polygon_features.get(r, {}).get("segment")
                            for r in range(n_polygons)], dtype=object)
    heavy_lut = np.array([bool(polygon_features.get(r, {}).get("is_heavy", False))
                          for r in range(n_polygons)])
    zone = zone_lut[polygon]
    area = area_lut[polygon]
    n_portals = portals_lut[polygon]
    n_lights = lights_lut[polygon]
    segment = segment_lut[polygon]
    is_heavy = heavy_lut[polygon]

    out = dict(
        run_id=np.array([header["run_id"]] * n, dtype=object),
        seed=np.full(n, header["seed"], dtype=np.int32),
        t=ts, polygon=polygon.astype(np.int16), zone=zone, segment=segment,
        is_heavy_segment=is_heavy,
        hp=hp, total_ammo=ammo9 + ammoshell + ammocell,
        ammo_9mm=ammo9, ammo_shell=ammoshell, ammo_cell=ammocell, n_weapons=nweap,
        dmgtaken_1s=dmgtaken_1s, dmgtaken_3s=dmgtaken_3s, dmgtaken_10s=dmgtaken_10s,
        kills_1s=kills_1s, kills_3s=kills_3s, kills_10s=kills_10s,
        shots_3s=shots_3s, hits_3s=hits_3s, accuracy_3s=accuracy_3s, fire_1s=fire_1s,
        n_aggro=n_aggro, n_aggro_same_polygon=n_aggro_same_polygon,
        weak_aggro_same_polygon=weak_aggro_same_polygon,
        heavy_aggro_same_polygon=heavy_aggro_same_polygon,
        weighted_threat_active=weighted_threat_active,
        min_enemy_dist_capped=min_enemy_dist_capped,
        has_same_polygon_threat=has_same_polygon_threat,
        n_pickups_polygon=n_pickups_polygon, speed=speed.astype(np.float32),
        time_in_polygon=time_in_polygon.astype(np.int16),
        area=area, n_portals=n_portals, n_lights=n_lights,
        is_combat_zone=(zone == "combat").astype(np.float32),
        is_loot_zone=(zone == "loot").astype(np.float32),
    )
    for w in WEAPON_DUMMIES:
        out[f"weapon_is_{w}"] = np.array([1.0 if wp == w else 0.0 for wp in weapon],
                                         dtype=np.float32)

    outcome = footer["outcome"] if footer else "error"
    end_tick = footer["ticks"] if footer else (rows[-1][idx["t"]] if rows else 0)
    out["outcome"] = np.array([outcome] * n, dtype=object)
    for name, h in HORIZONS.items():
        if outcome == "died":
            lab = ((end_tick - ts) <= h).astype(np.float32)
            valid = np.ones(n, dtype=bool)
        elif outcome == "complete":
            lab = np.zeros(n, dtype=np.float32)
            valid = np.ones(n, dtype=bool)
        else:  # timeout / error: censor the tail we can't confirm survives
            lab = np.zeros(n, dtype=np.float32)
            valid = (end_tick - ts) >= h
        out[f"death_in_{name}"] = lab
        out[f"valid_{name}"] = valid.astype(np.float32)
    return out


def load_all_runs(runs_dir: Path, polygon_features: dict[int, dict]) -> list[dict]:
    """Process every run file exactly once; callers concatenate prefixes of
    the returned list for saturation batches instead of reprocessing."""
    out = []
    for p in iter_run_files(runs_dir):
        d = process_run(p, polygon_features)
        if d is not None:
            out.append(d)
    return out


def concat(run_dicts: list[dict]) -> dict:
    if not run_dicts:
        return {}
    keys = run_dicts[0].keys()
    return {k: np.concatenate([d[k] for d in run_dicts]) for k in keys}


def run_outcomes(run_dicts: list[dict]) -> dict:
    from collections import Counter

    c = Counter(d["outcome"][0] for d in run_dicts)
    n = sum(c.values())
    return dict(n_runs=n, outcomes=dict(c),
               clear_rate=c.get("complete", 0) / n if n else 0.0)


# ---------------------------------------------------------------------------
# modeling: PCA (interpretability) + L1 logistic (the STALWART predictor)
# ---------------------------------------------------------------------------

MAX_FIT_ROWS = 200_000  # kept modest: this box runs several other memory-
# hungry processes concurrently (desktop apps, other agent sessions) --
# 200k rows x ~29 features is <50MB either way, plenty for a stable L1 fit
SPLIT_SEED = 20260713
# liblinear grid: kept small because this shared box is CPU-contended (load
# average consistently >10 on 32 cores from unrelated desktop/agent work)
# -- 5 Cs x 3 folds = 15 fits/model instead of 8x5=40, tol relaxed from
# liblinear's 1e-4 default so a fit that would otherwise burn max_iter
# grinding for a fourth decimal place of convergence stops sooner.
CS_GRID = 5
CV_FOLDS = 3
MAX_ITER = 800


def _feature_matrix_at(data: dict, feature_names: list[str], row_idx: np.ndarray) -> np.ndarray:
    """Builds the dense model matrix for ONLY `row_idx` rows -- never
    materializes a full (potentially multi-million-row) dense copy first.
    Callers subsample indices, then call this, not the other way round."""
    X = np.column_stack([data[f][row_idx] for f in feature_names]).astype(float)
    return np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)


def _subsample(n: int, cap: int, seed: int) -> np.ndarray:
    if n <= cap:
        return np.arange(n)
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(n, size=cap, replace=False))


def fit_logistic(data: dict, feature_names: list[str], horizon_key: str,
                  label: str, test_frac: float = 0.25, seed: int = SPLIT_SEED) -> dict:
    """L1 logistic regression predicting death-within-`horizon_key`, C chosen
    by group-(run)-aware CV on the train split, evaluated on a held-out
    RUN split never touched while fitting. Returns fitted objects + the
    out-of-sample AUC/calibration curve the report cites."""
    from sklearn.calibration import calibration_curve
    from sklearn.linear_model import LogisticRegressionCV
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold, GroupShuffleSplit
    from sklearn.preprocessing import StandardScaler

    valid_idx = np.flatnonzero(data[f"valid_{horizon_key}"] > 0.5)
    sub = _subsample(len(valid_idx), MAX_FIT_ROWS, seed)
    row_idx = valid_idx[sub]
    y = data[f"death_in_{horizon_key}"][row_idx]
    groups = data["run_id"][row_idx]
    X = _feature_matrix_at(data, feature_names, row_idx)

    gss = GroupShuffleSplit(n_splits=1, test_size=test_frac, random_state=seed)
    train_idx, test_idx = next(gss.split(X, y, groups))
    if y[train_idx].sum() < 2 or y[test_idx].sum() < 2:
        return dict(label=label, feature_names=feature_names, error="too few positive labels")

    scaler = StandardScaler().fit(X[train_idx])
    Xtr, Xte = scaler.transform(X[train_idx]), scaler.transform(X[test_idx])
    ytr, yte = y[train_idx], y[test_idx]
    inner_cv = list(GroupKFold(n_splits=CV_FOLDS).split(Xtr, ytr, groups[train_idx]))

    clf = LogisticRegressionCV(
        Cs=CS_GRID, cv=inner_cv, penalty="l1", solver="liblinear", scoring="roc_auc",
        max_iter=MAX_ITER, tol=1e-3, random_state=seed,
    ).fit(Xtr, ytr)

    p_test = clf.predict_proba(Xte)[:, 1]
    auc = float(roc_auc_score(yte, p_test)) if len(np.unique(yte)) > 1 else float("nan")
    frac_pos, mean_pred = calibration_curve(yte, p_test, n_bins=10, strategy="quantile")

    p_all = clf.predict_proba(scaler.transform(X))[:, 1]

    return dict(
        label=label, feature_names=feature_names, horizon=horizon_key,
        n_train=int(len(ytr)), n_test=int(len(yte)),
        train_positive_rate=float(ytr.mean()), test_positive_rate=float(yte.mean()),
        C_selected=float(clf.C_[0]), auc=auc,
        coefficients={f: float(c) for f, c in zip(feature_names, clf.coef_[0])},
        intercept=float(clf.intercept_[0]),
        n_nonzero_coefficients=int(np.sum(np.abs(clf.coef_[0]) > 1e-9)),
        calibration=dict(mean_predicted=[float(v) for v in mean_pred],
                         frac_positive=[float(v) for v in frac_pos]),
        scaler_mean={f: float(v) for f, v in zip(feature_names, scaler.mean_)},
        scaler_scale={f: float(v) for f, v in zip(feature_names, scaler.scale_)},
        _p_all=p_all,
    )


def compute_pca(data: dict, feature_names: list[str], seed: int = SPLIT_SEED) -> dict:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    n = len(data[feature_names[0]])
    sub = _subsample(n, 100_000, seed)
    X = _feature_matrix_at(data, feature_names, sub)
    Xs = StandardScaler().fit_transform(X)
    n_comp = min(8, X.shape[1])
    pca = PCA(n_components=n_comp, random_state=seed).fit(Xs)
    components = []
    for i in range(n_comp):
        loadings = {f: float(pca.components_[i, j]) for j, f in enumerate(feature_names)}
        top = sorted(loadings.items(), key=lambda kv: -abs(kv[1]))[:6]
        components.append(dict(
            component=i + 1,
            explained_variance_ratio=float(pca.explained_variance_ratio_[i]),
            loadings=loadings, top_loadings=dict(top),
        ))
    return dict(n_samples=int(len(sub)), total_explained_variance_first_8=
                float(np.sum(pca.explained_variance_ratio_)), components=components)


def _cdf_reference_points(values: np.ndarray, n_points: int = 101) -> list[float]:
    if len(values) == 0:
        return [0.0] * n_points
    s = np.sort(values)
    idxs = np.round(np.linspace(0, len(s) - 1, n_points)).astype(int)
    return [float(s[i]) for i in idxs]


def percentile_rank(value: float, cdf_reference: list[float]) -> float:
    """Map a raw score to its 0-1 percentile against `cdf_reference` (a
    101-point sorted lookup from _cdf_reference_points) via interpolation —
    the STALWART/CONTEMPT normalization the brief specifies."""
    ref = np.asarray(cdf_reference)
    pct = np.searchsorted(ref, value, side="left") / (len(ref) - 1)
    return float(np.clip(pct, 0.0, 1.0))


# ---------------------------------------------------------------------------
# CONTEMPT / PRAYER (directly observed, per the correction)
# ---------------------------------------------------------------------------

def compute_contempt(data: dict) -> dict:
    wac = np.minimum(data["weak_aggro_same_polygon"], 4)
    kills_per_sec = data["kills_3s"] / (WINDOWS["3s"] / 60.0)
    table = []
    for b in range(5):
        m = wac == b
        n = int(m.sum())
        rate = float(kills_per_sec[m].mean()) if n else 0.0
        se = float(kills_per_sec[m].std(ddof=1) / math.sqrt(n)) if n > 1 else None
        table.append(dict(weak_aggro_same_polygon=("4+" if b == 4 else int(b)),
                          n_ticks=n, kills_per_sec=rate, se=se))
    engaged = wac > 0
    ref = kills_per_sec[engaged] if engaged.any() else np.array([0.0])
    return dict(formula="kills in trailing 3s / 3.0, binned by weak (husk/mite) "
                        "same-polygon aggro count", table=table,
               cdf_reference=_cdf_reference_points(ref))


def compute_prayer(data: dict) -> dict:
    prayer = 1.0 / (1.0 + data["n_aggro"])
    # Diagnostic-only variant using the SAME-POLYGON aggro count instead of the
    # brief's specified global count -- see the "contradicts the brief"
    # writeup in FITTING_REPORT.md: sim.py's `_enemy_ai` has no de-aggro
    # path for standard enemies once state=="hunt" (only `flicker` disengages,
    # see `_flicker_ai`); a hunting enemy pathfinds toward the player's
    # CURRENT polygon via `next_edge(polygon, ppolygon)` forever, so the brief's
    # literal "1/(1+n_aggro)" (global) does not return to ~1.0 in a safe
    # polygon once anything upstream has been aggro'd and left alive. This
    # local variant is reported for comparison ONLY; PRAYER's official
    # value below still uses the brief's literal global formula.
    prayer_local = 1.0 / (1.0 + data["n_aggro_same_polygon"])
    out = dict(formula="1/(1+n_aggro)", mean_overall=float(prayer.mean()),
               diagnostic_local_formula="1/(1+n_aggro_same_polygon) -- NOT the "
                                        "official value, see comment above")
    for zname in ("loot", "corridor", "combat"):
        m = data["zone"] == zname
        out[f"mean_in_{zname}"] = float(prayer[m].mean()) if m.any() else None
        out[f"n_ticks_{zname}"] = int(m.sum())
        out[f"mean_in_{zname}_local"] = float(prayer_local[m].mean()) if m.any() else None
    return out


# ---------------------------------------------------------------------------
# sanity checks (fail-first)
# ---------------------------------------------------------------------------

PERMUTATION_MAX_ROWS = 250_000  # the full corpus is multi-million-row; 2000
# shuffles of the whole thing (confirmed: it blew a 400s budget at 600 runs/
# 4.2M ticks) is wasted precision for a permutation p-value -- a few hundred
# thousand rows already resolves p to well under the 0.05 decision boundary


def sanity_hazard_combat_vs_corridor(data: dict, horizon_key: str = PRIMARY_HORIZON,
                                      n_shuffles: int = 2000, seed: int = SPLIT_SEED) -> dict:
    """Real hazard(combat) vs hazard(corridor+loot), plus a permutation
    (shuffled-zone-label) control that must show ~no effect -- proof the
    real comparison isn't a methodological artifact."""
    valid_idx = np.flatnonzero(data[f"valid_{horizon_key}"] > 0.5)
    sub = _subsample(len(valid_idx), PERMUTATION_MAX_ROWS, seed)
    row_idx = valid_idx[sub]
    y = data[f"death_in_{horizon_key}"][row_idx]
    is_combat = (data["zone"][row_idx] == "combat")

    def diff(mask):
        a, b = y[mask].mean() if mask.any() else 0.0, y[~mask].mean() if (~mask).any() else 0.0
        return float(a - b)

    observed = diff(is_combat)
    rng = np.random.default_rng(seed)
    shuffled_diffs = np.empty(n_shuffles)
    for i in range(n_shuffles):
        perm = rng.permutation(is_combat)
        shuffled_diffs[i] = diff(perm)
    p_value = float(np.mean(np.abs(shuffled_diffs) >= abs(observed)))
    return dict(
        hazard_combat=float(y[is_combat].mean()) if is_combat.any() else None,
        hazard_corridor_or_loot=float(y[~is_combat].mean()) if (~is_combat).any() else None,
        observed_diff=observed, n_shuffles=n_shuffles,
        shuffled_diff_mean=float(shuffled_diffs.mean()),
        shuffled_diff_std=float(shuffled_diffs.std()),
        permutation_p_value=p_value,
        passes=bool(observed > 0 and p_value < 0.05),
    )


def sanity_contempt_trash_vs_heavy(aux_data: dict | None,
                                    heavy_data: dict | None = None) -> dict:
    """`aux_data`: the full-density (all 6 segments) auxiliary batch, used
    for the TRASH rate (segments B/A/C/D give it a large sample quickly).
    `heavy_data`: an optional SEPARATE, heavy-segments-only probe batch
    (tools/musiccal/aux/build_heavy_probe.py) for the HEAVY rate -- the
    full-density batch alone gives heavy segments almost no sample, because
    HumanBot's ~0% clear rate at density=1.0 means most runs die in the
    earlier segments and never reach E/F at all (measured: 34 ticks across
    80 runs). Falls back to `aux_data` alone if no dedicated probe is given."""
    if aux_data is None:
        return dict(available=False,
                    reason="no auxiliary full-density batch supplied")
    heavy_source = heavy_data if heavy_data is not None else aux_data

    def rate(data, mask):
        kills_per_sec = data["kills_3s"] / (WINDOWS["3s"] / 60.0)
        return (float(kills_per_sec[mask].mean()) if mask.any() else None,
                int(mask.sum()))

    # "engaged" is conditioned on the SPECIFIC kind class currently aggro'd
    # in-polygon, not just "somewhere in a segment tagged trash/heavy" -- E/F
    # mix husk/mite/spitter alongside their brute/shrieker, so a segment-
    # level condition would count plain husk kills inside a "heavy" segment
    # as heavy-rate evidence. weak_aggro_same_polygon / heavy_aggro_same_polygon
    # are per-tick, kind-specific counts (see process_run) for exactly this.
    trash_mask = (aux_data["weak_aggro_same_polygon"] > 0) & (aux_data["zone"] == "combat")
    trash_rate, n_trash = rate(aux_data, trash_mask)

    heavy_mask = (heavy_source["heavy_aggro_same_polygon"] > 0) & (heavy_source["zone"] == "combat")
    heavy_rate, n_heavy = rate(heavy_source, heavy_mask)

    return dict(
        available=True,
        note="trash rate from the full-density 6-segment auxiliary batch; "
             "heavy rate from a DEDICATED heavy-segments-only probe "
             f"({'used' if heavy_data is not None else 'NOT supplied, fell '
                'back to the same batch -- see n_heavy_ticks'})"
             " -- the tuned 50%-clear-rate corpus itself has zero "
             "brute/shrieker/warden presence (see caveats)",
        trash_kills_per_sec=trash_rate, heavy_kills_per_sec=heavy_rate,
        n_trash_ticks=n_trash, n_heavy_ticks=n_heavy,
        passes=bool(trash_rate is not None and heavy_rate is not None
                    and trash_rate > heavy_rate),
    )


def sanity_prayer_loot_polygons(prayer_stats: dict, tolerance: float = 0.1) -> dict:
    mean_loot = prayer_stats.get("mean_in_loot")
    passes = mean_loot is not None and abs(mean_loot - 1.0) <= tolerance
    return dict(mean_prayer_in_loot_polygons=mean_loot, tolerance=tolerance, passes=bool(passes))


# ---------------------------------------------------------------------------
# per-polygon hazard (saturation table + the per-position sanity plot)
# ---------------------------------------------------------------------------

def polygon_hop_order(level_path: Path) -> dict[int, int]:
    """polygon_id -> hop distance from the player spawn, along the gauntlet's
    connects graph -- an approximate but adequate "position along the run"
    axis for the diagnostic plot (segment F has one branch off its hub
    polygon, so no single polygon ever visits ALL polygons in strict sequence;
    hop-from-spawn still orders the run correctly end to end)."""
    from perihelion.sim import GameSession

    level = load_level(level_path)
    s = GameSession(level, seed=0)
    for d in s.doors:
        if not d["open"]:
            s.sim.connect(d["a"], d["ea"], d["b"], d["eb"])
    return {r: s.sim.hop_distance(level.player_polygon, r) for r in range(s.sim.num_polygons())}


def per_polygon_hazard(data: dict, horizon_key: str = PRIMARY_HORIZON) -> dict[int, dict]:
    valid = data[f"valid_{horizon_key}"] > 0.5
    polygons = data["polygon"][valid]
    labels = data[f"death_in_{horizon_key}"][valid]
    out = {}
    for r in np.unique(polygons):
        m = polygons == r
        n = int(m.sum())
        p = float(labels[m].mean())
        se = math.sqrt(max(p * (1 - p), 0.0) / n) if n > 0 else float("nan")
        out[int(r)] = dict(n_ticks=n, hazard=p, se=se,
                           se_pct_of_estimate=(se / p * 100.0) if p > 0 else None)
    return out


def evaluate_saturation(batches: list[dict]) -> dict:
    """batches: [{frac, n_runs, per_polygon}, ...] in increasing order. Applies
    the brief's criterion: SE < 15% of estimate for bins covering >=95% of
    bot-time, AND the last doubling shifts no such bin's hazard by >15%."""
    last = batches[-1]
    prev = batches[-2] if len(batches) > 1 else None
    per_polygon = last["per_polygon"]
    total_ticks = sum(v["n_ticks"] for v in per_polygon.values())
    ranked = sorted(per_polygon.items(), key=lambda kv: -kv[1]["n_ticks"])
    cum = 0
    covered = []
    for rid, v in ranked:
        if cum >= 0.95 * total_ticks:
            break
        covered.append(rid)
        cum += v["n_ticks"]
    se_ok = all((per_polygon[r]["se_pct_of_estimate"] is None or
                per_polygon[r]["se_pct_of_estimate"] < 15.0) for r in covered)
    shift_ok = True
    max_shift = 0.0
    if prev is not None:
        for r in covered:
            pv = prev["per_polygon"].get(r)
            if pv and per_polygon[r]["hazard"] > 0:
                shift = abs(per_polygon[r]["hazard"] - pv["hazard"]) / per_polygon[r]["hazard"]
                max_shift = max(max_shift, shift)
                if shift > 0.15:
                    shift_ok = False
    return dict(n_covered_polygons=len(covered), coverage_frac=cum / total_ticks if total_ticks else 0.0,
               se_criterion_met=bool(se_ok), shift_criterion_met=bool(shift_ok),
               max_shift_last_doubling=max_shift, saturated=bool(se_ok and shift_ok))


def compute_saturation_table(all_runs: list[dict], fractions=(1/16, 1/8, 1/4, 1/2, 1.0)) -> list[dict]:
    n_total = len(all_runs)
    table = []
    for frac in fractions:
        k = max(1, round(n_total * frac))
        merged = concat(all_runs[:k])
        table.append(dict(frac=frac, n_runs=k, n_ticks=int(len(merged["t"])),
                          per_polygon=per_polygon_hazard(merged)))
    return table


# ---------------------------------------------------------------------------
# plot
# ---------------------------------------------------------------------------

def plot_per_position_hazard(per_polygon: dict, hop_order: dict[int, int],
                              polygon_features: dict[int, dict], out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    zone_color = {"combat": "#c0392b", "corridor": "#2980b9", "loot": "#27ae60",
                 "unknown": "#7f7f7f"}
    polygons = sorted(per_polygon, key=lambda r: hop_order.get(r, 1e9))
    xs = [hop_order.get(r, 0) for r in polygons]
    ys = [per_polygon[r]["hazard"] for r in polygons]
    errs = [per_polygon[r]["se"] for r in polygons]
    colors = [zone_color.get(polygon_features[r]["zone"], "#7f7f7f") for r in polygons]

    fig, ax = plt.subplots(figsize=(11, 5), dpi=150)
    ax.errorbar(xs, ys, yerr=errs, fmt="none", ecolor="#999999", elinewidth=1, zorder=1)
    ax.scatter(xs, ys, c=colors, s=42, zorder=2, edgecolors="white", linewidths=0.6)
    for zname, c in zone_color.items():
        if zname == "unknown":
            continue
        ax.scatter([], [], c=c, label=zname, s=42)
    ax.legend(loc="upper left", frameon=False)
    ax.set_xlabel("hop distance from spawn (approximate position along the gauntlet)")
    ax.set_ylabel(f"P(death within {PRIMARY_HORIZON}) — instantaneous hazard")
    ax.set_title("STALWART calibration gauntlet: per-position hazard "
                 f"({PRIMARY_HORIZON} horizon)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(f"not JSON serializable: {type(o)}")


def _git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-dir", type=Path, default=ROOT / "tools/musiccal/runs")
    ap.add_argument("--level", type=Path, default=ROOT / "levels/gauntlet_cal.json")
    ap.add_argument("--meta", type=Path, default=ROOT / "tools/musiccal/gauntlet_meta.json")
    ap.add_argument("--aux-runs-dir", type=Path, default=ROOT / "tools/musiccal/aux/runs")
    ap.add_argument("--aux-level", type=Path,
                     default=ROOT / "tools/musiccal/aux/gauntlet_full_density.json")
    ap.add_argument("--aux-meta", type=Path,
                     default=ROOT / "tools/musiccal/aux/gauntlet_full_density_meta.json")
    ap.add_argument("--heavy-runs-dir", type=Path,
                     default=ROOT / "tools/musiccal/aux/runs_heavy")
    ap.add_argument("--heavy-level", type=Path,
                     default=ROOT / "tools/musiccal/aux/gauntlet_heavy_probe.json")
    ap.add_argument("--heavy-meta", type=Path,
                     default=ROOT / "tools/musiccal/aux/gauntlet_heavy_probe_meta.json")
    ap.add_argument("--out", type=Path, default=ROOT / "tools/musiccal/factor_model.json")
    ap.add_argument("--plot-out", type=Path,
                     default=ROOT / "tools/musiccal/hazard_by_position.png")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    polygon_features, meta = load_polygon_features(args.level, args.meta)

    print(f"[fit] loading runs from {args.runs_dir} ...", file=sys.stderr)
    all_runs = load_all_runs(args.runs_dir, polygon_features)
    if not all_runs:
        print(f"[fit] no runs found in {args.runs_dir} — run run_farm.py first",
              file=sys.stderr)
        return 1
    outcomes = run_outcomes(all_runs)
    print(f"[fit] {outcomes}", file=sys.stderr)
    merged = concat(all_runs)
    total_ticks = len(merged["t"])
    print(f"[fit] {total_ticks} ticks across {outcomes['n_runs']} runs "
          f"({total_ticks / 60.0:.0f} bot-seconds)", file=sys.stderr)

    print("[fit] saturation table ...", file=sys.stderr)
    sat_table = compute_saturation_table(all_runs)
    saturation = evaluate_saturation(sat_table)
    print(f"[fit] saturation: {saturation}", file=sys.stderr)

    print("[fit] PCA ...", file=sys.stderr)
    pca = compute_pca(merged, FEATURES)

    print("[fit] L1 logistic (full feature set) ...", file=sys.stderr)
    full_model = fit_logistic(merged, FEATURES, PRIMARY_HORIZON, "full_wide_feature_set")
    print(f"[fit]   AUC={full_model.get('auc')} n_nonzero="
          f"{full_model.get('n_nonzero_coefficients')}", file=sys.stderr)

    print("[fit] L1 logistic (baseline: weighted_threat_active only) ...", file=sys.stderr)
    baseline_model = fit_logistic(merged, BASELINE_FEATURES, PRIMARY_HORIZON,
                                  "baseline_weighted_threat_only")
    print(f"[fit]   AUC={baseline_model.get('auc')}", file=sys.stderr)

    secondary_aucs = {}
    for hk in HORIZONS:
        if hk == PRIMARY_HORIZON:
            continue
        m = fit_logistic(merged, FEATURES, hk, f"full_wide_feature_set_{hk}")
        secondary_aucs[hk] = m.get("auc")
    print(f"[fit] secondary-horizon AUCs: {secondary_aucs}", file=sys.stderr)

    stalwart_cdf = _cdf_reference_points(full_model["_p_all"]) if "_p_all" in full_model else None

    print("[fit] CONTEMPT / PRAYER ...", file=sys.stderr)
    contempt = compute_contempt(merged)
    prayer = compute_prayer(merged)

    print("[fit] sanity checks ...", file=sys.stderr)
    hazard_sanity = sanity_hazard_combat_vs_corridor(merged)
    prayer_sanity = sanity_prayer_loot_polygons(prayer)

    aux_available = args.aux_runs_dir.exists() and any(args.aux_runs_dir.glob("*.jsonl.gz"))
    contempt_sanity = dict(available=False, reason="no auxiliary runs found")
    if aux_available:
        aux_polygon_features, _ = load_polygon_features(args.aux_level, args.aux_meta)
        aux_runs = load_all_runs(args.aux_runs_dir, aux_polygon_features)
        aux_merged = concat(aux_runs) if aux_runs else None
        heavy_merged = None
        if args.heavy_runs_dir.exists() and any(args.heavy_runs_dir.glob("*.jsonl.gz")):
            heavy_polygon_features, _ = load_polygon_features(args.heavy_level, args.heavy_meta)
            heavy_runs = load_all_runs(args.heavy_runs_dir, heavy_polygon_features)
            heavy_merged = concat(heavy_runs) if heavy_runs else None
        contempt_sanity = sanity_contempt_trash_vs_heavy(aux_merged, heavy_merged)
    print(f"[fit] hazard_sanity={hazard_sanity}", file=sys.stderr)
    print(f"[fit] contempt_sanity={contempt_sanity}", file=sys.stderr)
    print(f"[fit] prayer_sanity={prayer_sanity}", file=sys.stderr)

    print("[fit] per-position hazard plot ...", file=sys.stderr)
    hop_order = polygon_hop_order(args.level)
    final_per_polygon = sat_table[-1]["per_polygon"]
    args.plot_out.parent.mkdir(parents=True, exist_ok=True)
    plot_per_position_hazard(final_per_polygon, hop_order, polygon_features, args.plot_out)

    def strip_internal(d):
        return {k: v for k, v in d.items() if not k.startswith("_")}

    import hashlib
    level_sha256 = hashlib.sha256(args.level.read_bytes()).hexdigest()[:16]

    output = dict(
        schema=2, generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        git_rev=_git_rev(), level=str(args.level.relative_to(ROOT)),
        level_sha256=level_sha256, gauntlet_density=meta.get("density"),
        runs_dir=str(args.runs_dir),
        run_metadata=outcomes, total_ticks=total_ticks,
        primary_horizon=PRIMARY_HORIZON, horizons=list(HORIZONS),
        features=FEATURES, baseline_features=BASELINE_FEATURES,
        saturation=dict(criterion="SE<15% of estimate for bins covering >=95% of "
                                   "bot-time AND last doubling shifts no such bin >15%",
                        batches=[{k: v for k, v in b.items() if k != "per_polygon"}
                                 for b in sat_table],
                        evaluation=saturation),
        pca=pca,
        stalwart=dict(
            description="STALWART = L1 logistic P(death within "
                        f"{PRIMARY_HORIZON}) on the wide feature set, "
                        "percentile-ranked against the fitted population "
                        "(ensemble CDF, 101-point reference table).",
            model=strip_internal(full_model),
            baseline_model=strip_internal(baseline_model),
            secondary_horizon_aucs=secondary_aucs,
            cdf_reference=stalwart_cdf,
        ),
        contempt=contempt,
        prayer=prayer,
        sanity_checks=dict(
            hazard_combat_vs_corridor=hazard_sanity,
            contempt_trash_vs_heavy=contempt_sanity,
            prayer_loot_polygons=prayer_sanity,
        ),
        per_polygon_hazard_final_batch=final_per_polygon,
        polygon_hop_order=hop_order,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=1, default=_json_default))
    dt = time.perf_counter() - t0
    print(f"[fit] wrote {args.out} in {dt:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
