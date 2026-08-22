"""boss_stems — the reserved over-the-top layer (director 2026-07-16).

Two stems per track that exist ONLY above the stalwart thresholds:
  drums_boss   (>=0.8): the serious kit -- the track's own drum lane
               plus 16th hats, doubled kick on the 8ths, and a crash
               on every 4-bar downbeat. Subdivision is the loudest
               "this is different now" signal there is.
  overlay_boss (>=0.88): sub-octave root double (register expansion
               downward) + a quiet tritone dread pedal -- the boss
               dissonance you cannot get from gain.

Also patches every bank.json with the track's SECTION MAP so the
engine can steer the form (jump to PEAK at the boss, return to vigil
becalmed).

    uv run python tools/musicgen/boss_stems.py [melody|all]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import tutti as T                    # noqa: E402
import tr909_kit as K                # noqa: E402
import harmony                       # noqa: E402
import vital_bank as VB              # noqa: E402
from tutti_bank import _write, _fold_tail   # noqa: E402

SR, BAR, STEP = T.SR, T.BAR, T.STEP
ROOT = Path(__file__).resolve().parents[2]
BANKS = ROOT / "out/banks"
SHIPPED = ROOT / "game/assets/music"


def sections_of(rec) -> list:
    out, pos = [], 0
    for stype, bars, _prog in rec["form"]:
        out.append([stype, pos, pos + bars])
        pos += bars
    return out


def build(mel: str):
    rec = T.RECIPES[mel]
    total_bars = sum(b for _, b, _ in rec["form"])
    n = int(total_bars * BAR * SR)
    outdir = BANKS / f"album_{mel}"
    print(f"[{rec['title']}] boss stems -> {outdir}", flush=True)

    # --- drums_boss: FORM-WIDE base kit + subdivision + crash grid
    # (matches the bank's form-wide drums stem; the album lane is
    # composed-silent in calm sections) ---
    rngd = np.random.default_rng(rec["seeds"][2])
    dh_full = T.drums(rec, total_bars, rngd,
                      fills_at=tuple(range(7, total_bars, 8)))
    base_kit = np.zeros(n + int(BAR * SR))
    T.place(base_kit, T.drum_bus(dh_full) * 0.7, 0)
    rng = np.random.default_rng(rec["seeds"][0])
    over = np.zeros(len(base_kit), dtype=np.float64)
    for bar in range(total_bars):
        t0 = bar * BAR
        for s16 in range(16):
            tt = t0 + s16 * STEP
            if s16 % 2 == 1:                        # offbeat 16th hats
                T.place(over, K.hit("chh", 0.5 + 0.1 * rng.random(),
                                    rng), tt)
        for e8 in range(8):                          # kick on the 8ths
            T.place(over, K.hit("kick", 0.75, rng), t0 + e8 * 2 * STEP,
                    0.8)
        if bar % 4 == 0:
            T.place(over, K.hit("crash", 0.9, rng), t0, 0.9)
    drums_boss = base_kit * 0.9 + over * 0.55
    _write(outdir / "drums_boss.wav", _fold_tail(drums_boss, n), n)

    # --- overlay_boss: sub-octave roots + tritone dread pedal ---
    roots = []
    for stype, bars, prog in rec["form"]:
        roots += harmony.roots_16(prog, bars)[::16]
    sub_seq, dread_seq = [], []
    for bar, r in enumerate(roots):
        t0 = bar * BAR
        sub_seq.append((26 + r, t0, BAR * 0.95, 112))          # sub root
        sub_seq.append((26 + r, t0 + BAR / 2, BAR * 0.45, 100))
        if bar % 2 == 0:
            # octave pedal, not tritone: Gemini comparative judge
            # (overlay_iter.py, 2026-07-16) scored the tritone
            # coherence 3/10 ('mix-ruining dissonant mud' -- exactly
            # the clash the director heard) and the octave 10/10
            # coherence, 9/10 menace, zero clash
            dread_seq.append((38 + r + 12, t0, BAR * 1.9, 84))
    sub = VB.render_seq(*rec["bass"], sub_seq, total_bars * BAR, 0.6)
    dread = VB.render_seq(*rec["wall"], dread_seq, total_bars * BAR, 0.5)
    sub = sub / (np.abs(sub).max() + 1e-9)
    dread = dread / (np.abs(dread).max() + 1e-9)
    L = max(len(sub), len(dread), n)
    overlay = np.zeros(L, dtype=np.float64)
    overlay[:len(sub)] += sub * 0.75
    overlay[:len(dread)] += dread * 0.22
    _write(outdir / "overlay_boss.wav", _fold_tail(overlay, n), n)

    # (sting is OWNED by bell_sting.py / tutti_bank now: the deep
    # on-key chapel bell behind a trimmed swell -- rebuilding the old
    # crash+synth-bell here would silently clobber it)

    # --- stab: the 4-bar boss hit. Crash + kick + low tom -- NO BELL
    # (the sting carries the bell; stabbing it every 4 bars read as
    # "someone spamming a bell sample over the music", director) ---
    stab = np.zeros(int(1.5 * BAR * SR))
    T.place(stab, K.hit("crash", 1.0, rng), 0, 0.9)
    T.place(stab, K.hit("kick", 1.0, rng), 0, 1.0)
    T.place(stab, K.hit("kick", 0.9, rng), 0.02, 0.8)
    T.place(stab, K.hit("snare", 0.8, rng), 0.012, 0.5)
    _write(outdir / "stab.wav", stab, len(stab))

    # --- section map into bank.json (dev + shipped) ---
    secs = sections_of(rec)
    for d in (outdir, SHIPPED / f"album_{mel}"):
        bj = d / "bank.json"
        if not bj.exists():
            continue
        meta = json.loads(bj.read_text())
        assert int(meta["bars"]) == total_bars, (mel, d)
        meta["sections"] = secs
        bj.write_text(json.dumps(meta))
    print(f"  sections: {secs}", flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    mels = list(T.RECIPES) if which == "all" else [which]
    for m in mels:
        build(m)
