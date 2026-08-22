"""sting_iter — Gemini audit of the stings, in AND out of context.

Director 2026-07-16: "be really careful with your 'stings' - I think
most of them kinda just read as glitchy random noises."

For a bank: clip A = the bare sting; clip B = a combat passage with
the sting landing mid-way (in context); clips C/D = candidate
replacement designs in the same context:
  C: 'swell' -- the bell kept, but entered via a 1-beat cymbal swell
     (reversed crash) so it ARRIVES instead of popping in;
  D: 'lowhit' -- no bell: low piano-register hit + crash, the classic
     orchestral sting.

    uv run python tools/musicgen/sting_iter.py dies_irae
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
import tr909_kit as K                # noqa: E402
from judge_track import _ask_multi, _stereo_mp3   # noqa: E402

SR, BAR = T.SR, T.BAR
ROOT = Path(__file__).resolve().parents[2]
BANKS = ROOT / "out/banks"


def load(bank, name, gain):
    f = bank / f"{name}.wav"
    if not f.exists():
        return None
    x, _ = sf.read(str(f), dtype="float32")
    if x.ndim == 2:
        x = x.mean(axis=1)
    return x * gain


def context_mix(bank) -> np.ndarray:
    parts = [load(bank, "stalwart", 0.85), load(bank, "drums", 0.8),
             load(bank, "prayer", 0.45), load(bank, "bass_shrieker", 0.7),
             load(bank, "lead_smg", 0.55), load(bank, "bed_t3", 0.5)]
    n = min(len(p) for p in parts if p is not None)
    n = min(n, int(24 * BAR * SR))
    mix = np.zeros(n)
    for p in parts:
        if p is not None:
            mix += p[:n]
    return mix


def sting_swell(rec, rng) -> np.ndarray:
    crash = K.hit("crash", 1.0, rng)
    rev = crash[::-1] * np.linspace(0.0, 1.0, len(crash)) ** 1.5
    out = np.zeros(int(2.5 * BAR * SR))
    T.place(out, rev * 0.7, 0)
    T.place(out, K.hit("crash", 1.0, rng), len(rev) / SR * 0.92)
    T.place(out, T.bell_render(rec, 0.8), len(rev) / SR * 0.92)
    return out


def sting_lowhit(rec, rng) -> np.ndarray:
    out = np.zeros(int(2.0 * BAR * SR))
    T.place(out, K.hit("crash", 1.0, rng), 0, 0.9)
    T.place(out, K.hit("kick", 1.0, rng), 0, 1.0)
    T.place(out, K.hit("kick", 0.95, rng), 0.03, 0.9)
    T.place(out, K.hit("snare", 0.7, rng), 0.015, 0.4)
    return out


def main():
    mel = sys.argv[1] if len(sys.argv) > 1 else "dies_irae"
    rec = T.RECIPES[mel]
    bank = BANKS / f"album_{mel}"
    rng = np.random.default_rng(7)
    tmp = Path(tempfile.mkdtemp(prefix="sting_"))

    cur = load(bank, "sting", 1.0)
    ctx = context_mix(bank)
    at = int(10 * BAR * SR)

    def with_sting(s):
        m = ctx.copy()
        m[at:at + len(s)] += s[:len(m) - at] * 0.8
        return m / (np.abs(m).max() + 1e-9) * 0.9

    clips = []
    bare = np.zeros(int(3 * BAR * SR))
    bare[:len(cur)] += cur[:len(bare)]
    for name, x in (("bare", bare / (np.abs(bare).max() + 1e-9) * 0.9),
                    ("current", with_sting(cur)),
                    ("swell", with_sting(sting_swell(rec, rng))),
                    ("lowhit", with_sting(sting_lowhit(rec, rng)))):
        w = tmp / f"{name}.wav"
        sf.write(str(w), x, SR)
        mp3 = tmp / f"{name}.mp3"
        _stereo_mp3(w, mp3, max_s=60.0)
        clips.append(mp3)
    prompt = (
        "Four clips from an industrial-metal game soundtrack. Clip A: a "
        "musical STING (accent hit marking a threat-spike) heard alone. "
        "Clips B, C, D: the same combat passage, with a sting landing "
        "about 22 seconds in -- B uses the sting from A as-is, C enters "
        "it via a reversed-cymbal swell, D replaces it with a low "
        "orchestral hit (no bell). Question: in B, C, D does the sting "
        "read as a MUSICAL event (intentional accent) or as a glitchy "
        "random noise dropped on top? Respond ONLY with JSON: "
        "{\"per_clip\": {\"B\": {\"musical\": 1-10, \"note\": \"..\"}, "
        "\"C\": ..., \"D\": ...}, \"ranking\": [best..worst of B,C,D], "
        "\"bare_sting_quality\": \"one sentence on A alone\", "
        "\"verdict\": \"one sentence\"}")
    res = _ask_multi(clips, prompt)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
