"""DSP census of the inspiration-album blocks — measured ground truth.

The johnny move (tracker_playbook.md): count what recurs in the corpus,
derive authoring rules from counts, then RUN THE SAME CENSUS ON OUR OWN
RENDERS — our piece must land inside the album's measured lanes, the way
johnny's covers had to land near 1.29 fx/note.

The round-1 corpus JSON holds Gemini's *descriptions* of each block; this
tool adds *numbers* nobody hallucinated: RMS, crest, spectral centroid,
band balance, onset densities, per-hit articulation variance, tempo.

    uv run python tools/musicgen/album_census.py                # full album census
    uv run python tools/musicgen/album_census.py --wav X.wav    # census one render
    uv run python tools/musicgen/album_census.py --discriminate # census must
        # separate album blocks from the condemned round-1/2 demos, or the
        # census itself is measuring the wrong things (fail-first for metrics)

Blocks live in the session scratchpad (never committed); the census JSON is
committed to tools/musicgen/analysis/album_census.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import stft

ROOT = Path(__file__).resolve().parent
SCRATCH = Path("/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter"
               "/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/musicgen")
CORPUS = ROOT / "analysis/album_block_corpus.json"
OUT = ROOT / "analysis/album_census.json"

# analysis frame: 2048/512 @ 44.1k -> ~86 flux frames/s
NFFT, HOP = 2048, 512

BANDS = {  # name -> (lo_hz, hi_hz)
    "sub": (20, 60),
    "low": (60, 250),      # kick body + chug fundamentals
    "mid": (250, 2000),    # choir/organ/vocal body
    "high": (2000, 8000),  # attacks, hats, presence
    "air": (8000, 16000),
}

TIER_OF = {"low": "restrained", "building": "restrained",
           "high": "high", "peak": "peak"}


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    x, sr = sf.read(str(path), always_2d=True, dtype="float64")
    return x.mean(axis=1), sr


def census_one(path: Path) -> dict:
    x, sr = load_mono(path)
    dur = len(x) / sr
    rms = float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    peak = float(np.abs(x).max() + 1e-12)

    f, _, Z = stft(x, fs=sr, nperseg=NFFT, noverlap=NFFT - HOP, padded=False)
    mag = np.abs(Z)                          # (freq, frames)
    fps = sr / HOP

    pw = mag ** 2
    tot = pw.sum() + 1e-12
    band_frac = {}
    band_flux = {}
    for name, (lo, hi) in BANDS.items():
        sel = (f >= lo) & (f < hi)
        band_frac[name] = float(pw[sel].sum() / tot)
        d = np.diff(mag[sel], axis=1)
        band_flux[name] = np.maximum(d, 0.0).sum(axis=0)  # rectified flux/frame

    full_flux = np.maximum(np.diff(mag, axis=1), 0.0).sum(axis=0)

    def onsets(flux: np.ndarray, gap_s: float = 0.09) -> np.ndarray:
        """Peak-pick: above rolling median * k, local max, min gap."""
        if len(flux) < 8:
            return np.array([], dtype=int)
        med = np.convolve(flux, np.ones(31) / 31, mode="same")
        thr = med * 1.8 + np.percentile(flux, 60) * 0.15
        idx = [i for i in range(1, len(flux) - 1)
               if flux[i] > thr[i] and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]]
        picked, last = [], -10 ** 9
        for i in idx:
            if (i - last) / fps >= gap_s:
                picked.append(i)
                last = i
        return np.array(picked, dtype=int)

    on_full = onsets(full_flux)
    on_low = onsets(band_flux["low"])
    on_high = onsets(band_flux["high"], gap_s=0.05)

    # tempo: autocorrelation of full flux envelope, 60..200 BPM
    env = full_flux - full_flux.mean()
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac[0] = 0
    lags = np.arange(len(ac)) / fps
    tempo_bpm, tempo_strength = 0.0, 0.0
    m = (lags >= 60 / 200) & (lags <= 60 / 60)
    if m.any() and ac.max() > 0:
        best = np.argmax(np.where(m, ac, -np.inf))
        tempo_bpm = 60.0 / lags[best]
        tempo_strength = float(ac[best] / (np.abs(ac[m]).max() + 1e-12))

    # articulation: coefficient of variation of onset strengths (low band =
    # kick/chug hits). Flat velocities = the doorbell.
    lowstr = band_flux["low"][on_low] if len(on_low) else np.array([0.0])
    art_cv = float(np.std(lowstr) / (np.mean(lowstr) + 1e-12))

    # centroid & flatness (perceptual brightness / noisiness)
    cen = (f[:, None] * pw).sum(axis=0) / (pw.sum(axis=0) + 1e-12)
    geo = np.exp(np.mean(np.log(pw + 1e-12), axis=0))
    flat = geo / (pw.mean(axis=0) + 1e-12)

    beats = dur * tempo_bpm / 60 if tempo_bpm else 0.0
    return {
        "path": str(path), "dur_s": round(dur, 2),
        "rms_dbfs": round(20 * np.log10(rms), 2),
        "crest_db": round(20 * np.log10(peak / rms), 2),
        "band_frac": {k: round(v, 4) for k, v in band_frac.items()},
        "centroid_hz": round(float(cen.mean()), 1),
        "flatness": round(float(flat.mean()), 4),
        "tempo_bpm": round(tempo_bpm, 1),
        "tempo_strength": round(tempo_strength, 3),
        "onsets_per_s": round(len(on_full) / dur, 2),
        "low_onsets_per_beat": round(len(on_low) / beats, 2) if beats else None,
        "high_onsets_per_beat": round(len(on_high) / beats, 2) if beats else None,
        "articulation_cv": round(art_cv, 3),
    }


def tier_stats(rows: list[dict]) -> dict:
    keys = ["rms_dbfs", "crest_db", "centroid_hz", "flatness",
            "onsets_per_s", "low_onsets_per_beat", "high_onsets_per_beat",
            "articulation_cv"]
    out = {}
    for k in keys:
        vals = np.array([r[k] for r in rows if r.get(k) is not None], dtype=float)
        if not len(vals):
            continue
        out[k] = {"p25": round(float(np.percentile(vals, 25)), 3),
                  "median": round(float(np.median(vals)), 3),
                  "p75": round(float(np.percentile(vals, 75)), 3)}
    for b in BANDS:
        vals = np.array([r["band_frac"][b] for r in rows])
        out[f"band_{b}"] = {"p25": round(float(np.percentile(vals, 25)), 4),
                            "median": round(float(np.median(vals)), 4),
                            "p75": round(float(np.percentile(vals, 75)), 4)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", type=Path, help="census a single render instead")
    ap.add_argument("--discriminate", action="store_true")
    a = ap.parse_args()

    if a.wav:
        print(json.dumps(census_one(a.wav), indent=1))
        return

    corpus = json.loads(CORPUS.read_text())
    rows, tiers = [], {}
    for b in corpus:
        p = SCRATCH / b["path"]
        if not p.exists():
            print(f"MISSING block audio: {p} — re-split the album first")
            continue
        r = census_one(p)
        r["block"] = b["block"]
        r["intensity_level"] = b["analysis"]["intensity_level"]
        r["tier"] = TIER_OF[b["analysis"]["intensity_level"]]
        rows.append(r)
        tiers.setdefault(r["tier"], []).append(r)

    result = {
        "n_blocks": len(rows),
        "tiers": {t: {"n": len(rs), **tier_stats(rs)} for t, rs in tiers.items()},
        "all": tier_stats(rows),
        "blocks": rows,
    }

    if a.discriminate:
        # The census is only an instrument if it separates the album from the
        # condemned demos. Report each demo against the 'high' tier lanes.
        demos = sorted(SCRATCH.glob("demo_piece_v*.wav"))
        lanes = result["tiers"].get("high", {})
        checks = []
        for d in demos[-3:]:
            r = census_one(d)
            fails = []
            for k in ["articulation_cv", "low_onsets_per_beat", "crest_db",
                      "band_low", "band_sub", "centroid_hz"]:
                lane = lanes.get(k)
                if not lane:
                    continue
                v = r["band_frac"][k[5:]] if k.startswith("band_") else r.get(k)
                if v is None:
                    continue
                lo = lane["p25"] - 1.5 * (lane["p75"] - lane["p25"])
                hi = lane["p75"] + 1.5 * (lane["p75"] - lane["p25"])
                if not (lo <= v <= hi):
                    fails.append(f"{k}={v} outside [{round(lo,3)},{round(hi,3)}]")
            checks.append({"demo": d.name, "n_lane_failures": len(fails),
                           "failures": fails})
        result["discrimination"] = checks
        for c in checks:
            print(f"{c['demo']}: {c['n_lane_failures']} lane failures")
            for fmsg in c["failures"]:
                print(f"   {fmsg}")

    OUT.write_text(json.dumps(result, indent=1))
    print(f"\nwrote {OUT}  ({len(rows)} blocks)")
    for t, st in result["tiers"].items():
        print(f"tier {t:10s} n={st['n']:3d} rms {st['rms_dbfs']['median']} dB  "
              f"crest {st['crest_db']['median']} dB  "
              f"lowhits/beat {st.get('low_onsets_per_beat', {}).get('median')}  "
              f"artCV {st['articulation_cv']['median']}")


if __name__ == "__main__":
    main()
