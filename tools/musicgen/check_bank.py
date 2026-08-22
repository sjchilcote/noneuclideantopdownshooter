"""check_bank — validate a delivered/authored bank folder against the
authoring contract (MUSIC_AUTHORING.md §4-5) before it goes anywhere
near the build or the engine.

    uv run python tools/musicgen/check_bank.py BANK_DIR

Mirrors the tutti_bank build validators but parameterized by the bank's
OWN bank.json (the build's constants assume the in-house 110bpm forms),
so an artist bank at any tempo/length checks against its own grid.
Prints a per-stem report; exits nonzero if any ERROR. WARNs are
judgment calls for a human ear, never silently ignored defects.

Known limitation, stated where it applies: the chant bar-pair coverage
law (§5.3) is checked here on the prayer COMPOSITE, which historically
masked composed voice rests -- a passing check is necessary, not
sufficient; the voice-level check needs the compose-time monksig lane
(in-house banks) or a listen (delivered banks).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "game"))

from perihelion.music import load_bank_meta   # noqa: E402  THE loader

SR = 44100
WEAPONS = ("pistol", "smg", "shotgun", "rail", "scrap", "knife",
           "lightning", "gland", "hole", "tau")
ENEMIES = ("mite", "husk", "spitter", "shrieker", "brute", "warden",
           "flicker")
ONE_SHOTS = {"riser", "riser_half", "sting", "stab", "prayer_tail"}
REQUIRED = {"prayer", "contempt", "stalwart"}
KNOWN = (REQUIRED | ONE_SHOTS | {"drums", "drums_boss", "overlay_boss"}
         | {f"bed_t{t}" for t in range(1, 5)}
         | {f"lead_{w}" for w in WEAPONS}
         | {f"bass_{k}" for k in ENEMIES})
BASS_RATIO = 3.0        # tutti_bank law: low band dominates 3:1
QUIET_DB = -15.0        # rel-median silent-bar floor
DC_MAX = 0.003          # residual DC after 10Hz highpass


def _load(fn: Path):
    x, sr = sf.read(str(fn), dtype="float32")
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    return x, sr


def _bar_db(x, n_bar: int, n_bars: int):
    rms = np.array([np.sqrt((x[i * n_bar:(i + 1) * n_bar] ** 2).mean()
                            + 1e-12) for i in range(n_bars)])
    med = float(np.median(rms)) or 1e-12
    return 20 * np.log10(rms / med)


def _silent_runs(db):
    runs, start = [], None
    for i, v in enumerate(db):
        if v < QUIET_DB and start is None:
            start = i
        elif v >= QUIET_DB and start is not None:
            if i - start >= 2:
                runs.append((start, i - 1))
            start = None
    if start is not None and len(db) - start >= 2:
        runs.append((start, len(db) - 1))
    return runs


def _residual_dc(x) -> float:
    from scipy.signal import butter, sosfilt
    sos = butter(2, 10.0, btype="highpass", fs=SR, output="sos")
    y = np.stack([sosfilt(sos, x[:, 0]), sosfilt(sos, x[:, 1])], axis=1)
    return float(np.abs(y.mean(axis=0)).max())


def _band_ratio(x) -> float:
    seg = x[: int(20 * SR)].mean(axis=1)
    F = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    fr = np.fft.rfftfreq(len(seg), 1 / SR)
    lo = float(F[(fr >= 40) & (fr < 180)].sum())
    mid = float(F[(fr >= 180) & (fr < 1200)].sum())
    return lo / (mid + 1e-9)


def main(bank_dir: Path) -> int:
    errors, warns = [], []

    def err(m):
        errors.append(m)
        print(f"  ERROR {m}", flush=True)

    def warn(m):
        warns.append(m)
        print(f"  warn  {m}", flush=True)

    print(f"[check_bank] {bank_dir}", flush=True)
    try:
        meta = load_bank_meta(bank_dir)
    except Exception as exc:
        print(f"  ERROR bank.json rejected by the engine loader: {exc}")
        return 1
    n_bar = int(round(meta.bar_s * SR))
    n = n_bar * meta.n_bars
    print(f"  form: {meta.n_bars} bars x {meta.bar_s:.4f}s "
          f"({[s for s, _, _ in meta.sections]})", flush=True)
    stypes = {s for s, _, _ in meta.sections}
    if not stypes & {"vigil", "ritual"}:
        warn("no vigil/ritual section: no calm home to loop or return to")
    if not stypes & {"develop", "entry"}:
        warn("no develop/entry section: ordinary fights have no loop")
    if "peak" not in stypes:
        warn("no peak section: bosses have no material to pull to")

    files = {f.stem: f for f in sorted(bank_dir.glob("*.wav"))}
    for f in sorted(bank_dir.glob("*.ogg")):
        files.setdefault(f.stem, f)
    for name in sorted(set(files) - KNOWN):
        warn(f"{name}: unknown stem name (typo?) -- the engine will "
             f"slice it and never play it")
    for name in sorted(REQUIRED - set(files)):
        err(f"{name} missing -- the engine cannot load this bank")
    for name in sorted(KNOWN - ONE_SHOTS - REQUIRED - set(files)):
        warn(f"{name} missing -- that slot plays SILENCE in game")
    for name in sorted(ONE_SHOTS - set(files)):
        warn(f"{name} missing -- that gesture will not sound")

    for name, fn in sorted(files.items()):
        x, sr = _load(fn)
        if sr != SR:
            err(f"{name}: sample rate {sr}, must be {SR}")
            continue
        dc = _residual_dc(x)
        if dc > DC_MAX:
            err(f"{name}: residual DC {dc:.4f} > {DC_MAX} after 10Hz "
                f"highpass -- pops on every gain step (§5.5)")
        if name in ONE_SHOTS:
            if name == "prayer_tail" and \
                    abs(len(x) - n_bar) > 0.05 * n_bar:
                warn(f"prayer_tail: {len(x)/SR:.2f}s, expected exactly "
                     f"one bar ({n_bar/SR:.2f}s)")
            continue
        # form-wide stems: exact form length (the artist loop-folds the
        # tail into bar 0 themselves -- MUSIC_AUTHORING.md §2.2)
        if abs(len(x) - (n + n_bar)) <= 0.005 * n:
            warn(f"{name}: delivered with a +1-bar tail ({len(x)} "
                 f"samples). Fold the tail into bar 0 and trim to "
                 f"{n} (§2.2); the build can fold it for you, but "
                 f"form-length is the contract")
        elif abs(len(x) - n) > 0.005 * n:
            err(f"{name}: {len(x)} samples; the form is exactly {n} "
                f"({meta.n_bars} bars x {meta.bar_s:.4f}s at 44100)")
            continue
        db = _bar_db(x[:n], n_bar, meta.n_bars)
        runs = _silent_runs(db)
        if runs and name.startswith("lead_"):
            # the lead is PHRASE material: the reference banks rest
            # bars 2-3 of every 4-bar phrase cycle and judged fine --
            # a composed call-and-rest, not a dropout. Human call.
            warn(f"{name}: phrase rests at {runs} -- fine if composed "
                 f"(reference leads do this); a listen decides (§5.2)")
        elif runs:
            err(f"{name}: silent 2+ bars at {runs} "
                f"(<{QUIET_DB}dB rel median, §5.2)")
        if name.startswith("bass_"):
            r = _band_ratio(x)
            if r < BASS_RATIO:
                err(f"{name}: low/mid band ratio {r:.2f} < {BASS_RATIO}"
                    f" -- not sounding in the bass register (§5.4)")
        if name == "prayer":
            pairs = [i for i in range(meta.n_bars - 1)
                     if db[i] < QUIET_DB and db[i + 1] < QUIET_DB]
            if pairs:
                err(f"prayer: chant coverage holes at bar pairs {pairs}"
                    f" (§5.3)")
            else:
                print("  note  prayer bar-pair coverage passed on the "
                      "COMPOSITE -- confirm the VOICE itself by ear "
                      "(§5.3 limitation)", flush=True)

    print(f"[check_bank] {len(errors)} error(s), {len(warns)} warning(s)",
          flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
