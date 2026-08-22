"""overlay_iter — Gemini iteration on the overlay_boss layer.

Director 2026-07-16: "The overlay_boss could use some Gemini iteration
- to my ear it clashes with the rest of the melody, might not be
key-matching." Variants over the PEAK section of the full combat mix,
judged comparatively against a no-overlay reference in ONE request.

    uv run python tools/musicgen/overlay_iter.py dies_irae
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))

import tutti as T                    # noqa: E402
import harmony                       # noqa: E402
import vital_bank as VB              # noqa: E402
from judge_track import _ask_multi, _stereo_mp3   # noqa: E402

SR, BAR = T.SR, T.BAR
ROOT = Path(__file__).resolve().parents[2]
BANKS = ROOT / "out/banks"


def render_variant(rec, total_bars, kind: str) -> np.ndarray:
    roots = []
    for _st, bars, prog in rec["form"]:
        roots += harmony.roots_16(prog, bars)[::16]
    sub_seq, ped_seq = [], []
    for bar, r in enumerate(roots):
        t0 = bar * BAR
        sub_seq.append((26 + r, t0, BAR * 0.95, 112))
        sub_seq.append((26 + r, t0 + BAR / 2, BAR * 0.45, 100))
        if bar % 2 == 0 and kind in ("tritone", "fifth", "octave"):
            semi = {"tritone": 6, "fifth": 7, "octave": 12}[kind]
            ped_seq.append((38 + r + semi, t0, BAR * 1.9, 84))
    sub = VB.render_seq(*rec["bass"], sub_seq, total_bars * BAR, 0.6)
    sub = sub / (np.abs(sub).max() + 1e-9)
    if not ped_seq:
        return sub * 0.85
    ped = VB.render_seq(*rec["wall"], ped_seq, total_bars * BAR, 0.5)
    ped = ped / (np.abs(ped).max() + 1e-9)
    L = max(len(sub), len(ped))
    out = np.zeros(L)
    out[:len(sub)] += sub * 0.75
    out[:len(ped)] += ped * (0.28 if kind == "tritone" else 0.22)
    return out


def peak_mix(bank: Path, rec, overlay: np.ndarray | None) -> np.ndarray:
    """The full boss-tier mix across the PEAK section bars."""
    total = 0
    peak = None
    pos = 0
    for stype, bars, _p in rec["form"]:
        if stype == "peak" and peak is None:
            peak = (pos, pos + bars)
        pos += bars
    total = pos
    a, b = peak
    s0, s1 = int(a * BAR * SR), int(b * BAR * SR)

    def stem(name, gain):
        f = bank / f"{name}.wav"
        if not f.exists():
            return None
        x, _ = sf.read(str(f), dtype="float32")
        if x.ndim == 2:
            x = x.mean(axis=1)
        seg = x[s0:s1]
        return seg * gain
    parts = [stem("stalwart", 0.9), stem("drums_boss", 0.8),
             stem("prayer", 0.4), stem("bass_warden", 0.75),
             stem("lead_rail", 0.6), stem("bed_t3", 0.5)]
    n = max(len(p) for p in parts if p is not None)
    mix = np.zeros(n)
    for p in parts:
        if p is not None:
            mix[:len(p)] += p
    if overlay is not None:
        seg = overlay[s0:s1]
        mix[:len(seg)] += seg * 0.9
    return mix / (np.abs(mix).max() + 1e-9) * 0.9


def main():
    mel = sys.argv[1] if len(sys.argv) > 1 else "dies_irae"
    rec = T.RECIPES[mel]
    total_bars = sum(b for _, b, _ in rec["form"])
    bank = BANKS / f"album_{mel}"
    tmp = Path(tempfile.mkdtemp(prefix="ovl_"))
    variants = ["none", "sub_only", "fifth", "tritone", "octave"]
    clips = []
    for v in variants:
        ov = None if v == "none" else render_variant(
            rec, total_bars, "sub" if v == "sub_only" else v)
        m = peak_mix(bank, rec, ov)
        w = tmp / f"{v}.wav"
        sf.write(str(w), m, SR)
        mp3 = tmp / f"{v}.mp3"
        _stereo_mp3(w, mp3, max_s=40.0)
        clips.append(mp3)
    labels = ["A", "B", "C", "D", "E"]
    prompt = (
        "Five audio clips of the same metal/industrial game-music "
        "passage. Clip A is the mix WITHOUT a boss overlay layer. "
        "Clips B-E each add a different low 'boss dread' layer "
        "(B: sub-bass root doubling only; C: sub + perfect-fifth "
        "pedal; D: sub + tritone pedal; E: sub + octave pedal). "
        "Judge each of B-E against A for (1) harmonic coherence with "
        "the track's key and mode, (2) added menace/weight, (3) mud or "
        "clash. Respond ONLY with JSON: {\"ranking\": [best..worst of "
        "B,C,D,E], \"per_clip\": {\"B\": {\"coherence\": 1-10, "
        "\"menace\": 1-10, \"clash\": \"...\"}, ...}, \"verdict\": "
        "\"one sentence\"}")
    res = _ask_multi(clips, prompt)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
