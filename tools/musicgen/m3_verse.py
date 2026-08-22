"""M3 — one assembled verse, track-01 grammar (Album Mode v2).

Source grammar (RAW_BLOCK_NOTES, track 01 blk00-01): cavernous 100%-wet
choir/drone open; the band CRASHES in at once ("the mix instantly
contracts into a tight, aggressive, in-your-face field"); half-time
drums + palm-muted wall; the chant persists over the band.

Instruments: only director-passed ones (M1 monk, M2 909, probe-passed
raw chug kit, Dragonfly factory hall). Surge drone rides as the bed —
the one designed-not-preset element (open item in the design doc).
No synth bass yet (preset selection parked): the wall carries low-mid;
noted, not hidden.

    uv run python tools/musicgen/m3_verse.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soundgen"))
import synth as sy                    # noqa: E402
import gordon_chain as gc             # noqa: E402  (sidechain duck only)
import tr909_kit as K                 # noqa: E402
import voices                         # noqa: E402  (chug kit)
from delay_lama import render_vocal   # noqa: E402
from chants import DIES_IRAE_STROPHE  # noqa: E402
import surge_bank                     # noqa: E402

SR = 44100
BPM = 110.0
BAR = 240.0 / BPM
STEP = BAR / 16
ENTRY_BAR = 8                      # the band crashes in here
N_BARS = 26
TOTAL = N_BARS * BAR
DRAGONFLY = next((voices.SCRATCH / "dragonfly-reverb-3.2.10")
                 .rglob("DragonflyHallReverb.vst3"))
LARGE_VOCAL_HALL = dict(
    dry_level=80.0, early_level=10.0, late_level=20.0, size_m=40.0,
    width=80.0, predelay_ms=12.0, diffuse=80.0, low_cut_hz=4.0,
    low_cross_hz=700.0, low_mult_x=2.25, high_cut_hz=6250.0,
    high_cross_hz=4600.0, high_mult_x=0.30, spin_hz=2.1, wander_ms=17.0,
    decay_s=2.4, early_send=20.0, modulation=10.0)


def hall(x: np.ndarray, wet_scale: float = 1.0) -> np.ndarray:
    import pedalboard
    rv = pedalboard.load_plugin(str(DRAGONFLY))
    for k, v in LARGE_VOCAL_HALL.items():
        setattr(rv, k, v)
    rv.early_level = LARGE_VOCAL_HALL["early_level"] * wet_scale
    rv.late_level = LARGE_VOCAL_HALL["late_level"] * wet_scale
    st = np.stack([x, x]).astype(np.float32)
    y = rv(st, SR)
    return y.mean(axis=0).astype(np.float64)


def place(out, x, t_s, g=1.0):
    i = int(t_s * SR)
    if 0 <= i < len(out):
        seg = x[:len(out) - i]
        out[i:i + len(seg)] += seg * g


def main():
    rng = np.random.default_rng(3)
    n = int((TOTAL + 4.0) * SR)

    # --- the monk: full strophe across the verse, solemn grid ----------
    chant_step = 60.0 / 72.0 / 4
    vows = []
    for i, (svv, d) in enumerate(DIES_IRAE_STROPHE):
        nxt_rest = (i + 1 < len(DIES_IRAE_STROPHE)
                    and DIES_IRAE_STROPHE[i + 1][0] is None)
        vows.append(None if svv is None else
                    (-0.6 if (nxt_rest or d >= 8) else 0.2))
    monk_dry = render_vocal(DIES_IRAE_STROPHE, chant_step, base_midi=50,
                            vowels=vows)
    monk_dry /= np.abs(monk_dry).max() + 1e-9
    # pre-entry: cavernous (full wet); post-entry: the mix contracts —
    # drier monk, still above the band
    entry_t = ENTRY_BAR * BAR
    split = int(entry_t * SR)
    pre = hall(monk_dry[:split], wet_scale=1.6)
    post = hall(monk_dry[split:], wet_scale=0.55)
    monk = np.zeros(n)
    place(monk, pre, 0.0)
    place(monk, post, entry_t)

    # --- bed: Surge drone, low, present throughout ---------------------
    drone = surge_bank.render_notes("drone", [38, 50], TOTAL * 0.6,
                                    tail_s=2.0)
    reps = int(np.ceil(n / len(drone)))
    bed = np.tile(drone, reps)[:n] * 0.35

    # --- bell: tolls at the chant's line ends (pre-entry only) ---------
    bell = np.zeros(n)
    from parts import bell_hit
    for t_bar in (3.2, 6.6):
        place(bell, bell_hit(0.5), t_bar * BAR)
    bell = hall(bell[:int((entry_t + 4) * SR)], wet_scale=1.3)
    bellbuf = np.zeros(n)
    place(bellbuf, bell, 0.0)

    # --- band entry: 909 half-time + chug wall (two takes, wide) -------
    band_bars = N_BARS - ENTRY_BAR
    drums = np.zeros(int(band_bars * BAR * SR) + SR)
    kick = K.kick_knob(25, 25, 50)
    for bar in range(band_bars):
        for pos, vel, inst in [(0, 1.0, "kick"), (8, .95, "snare"),
                               (4, .85, "kick"), (12, .5, "kick")]:
            v = float(np.clip(vel * (1 + rng.normal(0, .05)), .05, 1.))
            x = kick * (0.6 + 0.4 * v) if inst == "kick" else K.hit("snare", v, rng)
            K.place(drums, x, bar * BAR + pos * STEP + rng.normal(0, .003))
        for pos in range(0, 16, 2):
            acc = .75 if pos % 8 == 4 else (.5 if pos % 4 == 0 else .35)
            K.place(drums, K.hit("chh", acc, rng),
                    bar * BAR + pos * STEP + rng.normal(0, .002))
        if bar % 2 == 1:
            K.place(drums, K.hit("ohh", .7, rng), bar * BAR + 14 * STEP)

    def wall_take(seed):
        r = np.random.default_rng(seed)
        out = np.zeros(int(band_bars * BAR * SR) + SR)
        for bar in range(band_bars):
            roots = [0, 0] if bar % 2 == 0 else [-2, 0]
            for half, root in enumerate(roots):
                for e8 in range(4):
                    mute = 0.0 if e8 == 0 else 0.85
                    vel = (1.0 if e8 == 0 else .55) * (1 + r.normal(0, .05))
                    h = voices.chug_note(r, root, STEP * 1.9 * (1.6 - mute),
                                         mute, vel)
                    K.place(out, h, bar * BAR + (half * 8 + e8 * 2) * STEP
                            + r.normal(0, .005))
        return out

    wl, wr = wall_take(11), wall_take(22)

    # --- mix (ALBUM_TECHNIQUES): drums/monk center; wall wide; pump ----
    L = np.zeros(n)
    R = np.zeros(n)
    drums_g = np.zeros(n)
    place(drums_g, drums, entry_t)
    wlb = np.zeros(n)
    wrb = np.zeros(n)
    place(wlb, wl, entry_t)
    place(wrb, wr, entry_t)
    bed_d = gc.sidechain_duck(bed, drums_g, amount=0.4, release_s=0.12)
    wlb = gc.sidechain_duck(wlb, drums_g, amount=0.35, release_s=0.1)
    wrb = gc.sidechain_duck(wrb, drums_g, amount=0.35, release_s=0.1)

    center = monk * 1.0 + bed_d * 1.0 + bellbuf * 0.9 + drums_g * 0.85
    L = center + wlb * 0.75
    R = center + wrb * 0.75
    st = np.stack([L, R], axis=1)
    st = np.tanh(st * 0.8) / np.tanh(0.8)
    g = 10 ** ((-15.0 - voices.lufs(st.mean(axis=1))) / 20.0)
    st *= g
    pk = np.abs(st).max()
    if pk > 10 ** (-1.0 / 20):
        st *= 10 ** (-1.0 / 20) / pk
    Path("out").mkdir(exist_ok=True)
    sf.write("out/m3_verse.wav", st.astype(np.float32), SR)
    print(f"M3 verse: {len(st)/SR:.1f}s, entry at {entry_t:.1f}s "
          f"-> out/m3_verse.wav")


if __name__ == "__main__":
    main()
