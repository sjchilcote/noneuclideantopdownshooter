"""tools/musiccal/saturation_stream.py — memory-bounded per-polygon hazard
saturation evaluator.

fit_factors.py keeps every run's full feature arrays in memory (needed for
the model fit); at 2400+ runs that footprint (~5GB+) doesn't fit this
box's contended RAM. The saturation trajectory only needs per-polygon
(tick count, death-labeled tick count) sums, which stream in O(polygons)
memory: this script reads each run file once, extracts (polygon, t) per tick
plus the death outcome from the footer, applies the same 3s-horizon
labeling rule as fit_factors.process_run (died: last HORIZON ticks are
positive; complete: all negative; timeout: tail censored), and accumulates
per-polygon sums per seed-ordered batch prefix.

It ALSO reports the honest uncertainty unit the tick-level SEs hide:
estimated deaths-per-polygon (= positive ticks / HORIZON — each death paints
up to HORIZON consecutive positive ticks, so tick-level binomial SEs
overstate precision by ~sqrt(HORIZON); see FITTING_REPORT.md's saturation
section). For each doubling it evaluates the brief's literal criterion and
prints the observed vs Poisson-predicted shift so the "shifts are just
death-count noise" claim is falsifiable.

Usage:
    uv run python tools/musiccal/saturation_stream.py \\
        --runs-dir tools/musiccal/runs --out tools/musiccal/saturation_extended.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HORIZON = 180  # ticks; == fit_factors.HORIZONS[fit_factors.PRIMARY_HORIZON]
FRACTIONS = (1 / 32, 1 / 16, 1 / 8, 1 / 4, 1 / 2, 1.0)


def stream_run(path: Path) -> dict[int, tuple[int, int]] | None:
    """(ticks, positive_ticks) per polygon for one run, labels per
    fit_factors.process_run's rule."""
    header = None
    rows = []  # (polygon, t)
    footer = None
    with gzip.open(path, "rt") as fh:
        for line in fh:
            obj = json.loads(line)
            if header is None:
                header = obj
                polygon_i = header["fields"].index("polygon")
                t_i = header["fields"].index("t")
                continue
            if isinstance(obj, dict) and obj.get("footer"):
                footer = obj
                continue
            rows.append((obj[polygon_i], obj[t_i]))
    if not rows or footer is None:
        return None
    outcome = footer["outcome"]
    end_tick = footer["ticks"]
    acc: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for polygon, t in rows:
        if outcome == "died":
            valid, pos = True, (end_tick - t) <= HORIZON
        elif outcome == "complete":
            valid, pos = True, False
        else:  # timeout/error: censor the unconfirmable tail
            valid, pos = (end_tick - t) >= HORIZON, False
        if valid:
            a = acc[polygon]
            a[0] += 1
            a[1] += int(pos)
    return {r: (v[0], v[1]) for r, v in acc.items()}


def evaluate(per_polygon_batches: list[dict], n_runs_list: list[int]) -> list[dict]:
    out = []
    for i in range(1, len(per_polygon_batches)):
        cur, prev = per_polygon_batches[i], per_polygon_batches[i - 1]
        total = sum(v[0] for v in cur.values())
        ranked = sorted(cur.items(), key=lambda kv: -kv[1][0])
        cum, covered = 0, []
        for rid, v in ranked:
            if cum >= 0.95 * total:
                break
            covered.append(rid)
            cum += v[0]
        lit_se = True
        worst_se = None
        shifts = []
        for r in covered:
            n, pos = cur[r]
            p = pos / n if n else 0.0
            se = math.sqrt(max(p * (1 - p), 0.0) / n) if n else 0.0
            if p > 0 and se / p >= 0.15:
                lit_se = False
                worst_se = (r, p, se / p)
            pv = prev.get(r)
            if pv and pv[0]:
                p_prev = pv[1] / pv[0]
                if p > 0:
                    rel = abs(p - p_prev) / p
                    d_cur = pos / HORIZON  # est deaths
                    d_prev = pv[1] / HORIZON
                    pred = math.sqrt((1.0 / d_cur if d_cur > 0 else 0.0)
                                     + (1.0 / d_prev if d_prev > 0 else 0.0))
                    shifts.append((rel, pred, r))
        lit_shift = all(rel <= 0.15 for rel, _, _ in shifts)
        max_shift = max(shifts, key=lambda s: s[0]) if shifts else (0, 0, None)
        # how well do observed shifts track the Poisson death-count prediction?
        ratios = sorted(rel / pred for rel, pred, _ in shifts if pred > 0)
        med_ratio = ratios[len(ratios) // 2] if ratios else None
        out.append(dict(
            step=f"{n_runs_list[i - 1]}->{n_runs_list[i]}",
            covered=len(covered), coverage=cum / total,
            literal_se=lit_se, literal_shift=lit_shift,
            literal_saturated=bool(lit_se and lit_shift),
            worst_se_polygon=worst_se,
            max_rel_shift=max_shift[0], max_shift_polygon=max_shift[2],
            median_observed_to_predicted_shift_ratio=med_ratio,
            n_bins_shifted_over_15pct=sum(1 for rel, _, _ in shifts if rel > 0.15),
        ))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-dir", type=Path, default=ROOT / "tools/musiccal/runs")
    ap.add_argument("--out", type=Path,
                     default=ROOT / "tools/musiccal/saturation_extended.json")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    # seed order = the i.i.d. arrival order for prefix batches
    # (name is <bot>_<seed>.jsonl.gz; .stem only strips the .gz)
    files = sorted(args.runs_dir.glob("*.jsonl.gz"),
                   key=lambda p: int(p.name.split("_")[-1].split(".")[0]))
    n = len(files)
    print(f"[sat] streaming {n} runs ...", file=sys.stderr)

    cut_at = [max(1, round(n * f)) for f in FRACTIONS]
    acc: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    batches: list[dict] = []
    n_runs_list: list[int] = []
    done = 0
    for path in files:
        pr = stream_run(path)
        done += 1
        if pr:
            for r, (ticks, pos) in pr.items():
                a = acc[r]
                a[0] += ticks
                a[1] += pos
        if done in cut_at:
            batches.append({r: (v[0], v[1]) for r, v in acc.items()})
            n_runs_list.append(done)
            print(f"[sat] batch snapshot at {done} runs "
                  f"({time.perf_counter() - t0:.0f}s)", file=sys.stderr)

    evals = evaluate(batches, n_runs_list)
    for e in evals:
        print(f"[sat] {e['step']}: literal_saturated={e['literal_saturated']} "
              f"max_rel_shift={e['max_rel_shift']:.2f} (polygon {e['max_shift_polygon']}) "
              f"bins>15%={e['n_bins_shifted_over_15pct']} "
              f"obs/pred={e['median_observed_to_predicted_shift_ratio'] and round(e['median_observed_to_predicted_shift_ratio'], 2)}",
              file=sys.stderr)

    final = batches[-1]
    per_polygon_final = {
        str(r): dict(n_ticks=v[0], hazard=(v[1] / v[0] if v[0] else 0.0),
                     est_deaths=round(v[1] / HORIZON, 1))
        for r, v in sorted(final.items())
    }
    out = dict(horizon_ticks=HORIZON, n_runs=n, fractions=list(FRACTIONS),
               n_runs_per_batch=n_runs_list,
               batches=[{str(r): [v[0], v[1]] for r, v in b.items()} for b in batches],
               evaluations=evals, per_polygon_final=per_polygon_final,
               note="streaming per-polygon 3s-hazard saturation over the full farm; "
                    "est_deaths = positive_ticks/HORIZON is the honest sample-size "
                    "unit (tick SEs are ~sqrt(HORIZON) optimistic; see "
                    "FITTING_REPORT.md saturation section)")
    args.out.write_text(json.dumps(out, indent=1))
    print(f"[sat] wrote {args.out} in {time.perf_counter() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
