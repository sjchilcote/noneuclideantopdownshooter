"""Album-mode bank generator — one melody -> the full dynamic-stem set.

    uv run python tools/musicgen/generate_bank.py <melody> [outdir]

Produces the bank the extended MusicSystem consumes (all stems the SAME
loop length, 110 bpm, stereo 16-bit, LUFS-aligned):

    prayer.wav        monk in the sanctuary + choir + church organ + bell
    contempt.wav      dismissive groove: 909 four-on-floor, FM bass,
                      melody-fragment stabs (pump baked in)
    stalwart.wav      half-time 909 spine + hard-panned chug wall + deep
                      bass + the monk held above (melody-continuity law)
    riser.wav         tension riser loop
    sting.wav         one-shot wall hit (crash + bell + chug)
    bed_t1..t4.wav    stage drones (Odin2 factory Drones, by descent)
    lead_<weapon>.wav melody on the weapon's voice (10 weapons)
    bass_<enemy>.wav  per-enemy bassline cells (7 kinds)

Instruments are factory presets throughout (presets-first law); the chug
wall is the probe-passed sample kit. Space grammar per ALBUM_TECHNIQUES:
holy = far/wet (Dragonfly hall), violence = dry/close; drums pump the
sustained lanes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soundgen"))

import gordon_chain as gc               # noqa: E402
import tr909_kit as K                   # noqa: E402
import voices                           # noqa: E402
from parts import bell_hit              # noqa: E402
from delay_lama import render_vocal     # noqa: E402
from chants import DIES_IRAE_STROPHE    # noqa: E402
from chants_data import MELODY_MENU     # noqa: E402
import odin2_host as o2                 # noqa: E402
import dexed_host as dx                 # noqa: E402

SR = 44100
BPM = 110.0
BAR = 240.0 / BPM
STEP = BAR / 16

MELODIES = {"dies_irae": DIES_IRAE_STROPHE, **MELODY_MENU}

# major-family tunes clash with the album's minor/phrygian register
# (director's ear + pitch-content classification, 2026-07-14): offer a
# parallel-mode recast of each alongside the original for A/B
from harmony import recast as _recast          # noqa: E402
_BRIGHT = ["requiem_introit", "veni_creator", "viderunt_omnes",
           "old_100th", "ein_feste_burg", "ad_mortem"]
for _n in _BRIGHT:
    MELODIES[_n + "_dark"] = _recast(MELODIES[_n], "aeolian")

# ---- preset tables (presets-first law) ------------------------------------
CHOIR = ("Pads", "Choir Aahs 1 [RS]")
ORGAN_HOLY = ("Organ", "Church Organ")
ORGAN_DEFIANT = ("Organ", "666-001-Organ")
BASS_DEEP = ("Bass", "DeepBass [Photonic]")
BASS_FM = ("Bass", "Growly FM Bass [XR]")
BEDS = {1: ("Drones", "Alone in the Subway"),
        2: ("Drones", "Creep ATMO [psylion]"),
        3: ("Drones", "S&H harsh "),
        4: ("Drones", "The Sound of Agony [psylion]")}
WEAPON_LEADS = {
    "knife": ("odin", ("Leads", "Karplus Lead"), 0),
    "pistol": ("dexed", 13, 0),             # -ANALOG 1-
    "smg": ("odin", ("Leads", "Lead Squarepusher"), 0),
    "shotgun": ("odin", ("Stabs", "Lead Hit 1"), 0),
    "rail": ("odin", ("Leads", "Lead Rusty"), 0),
    "lightning": ("odin", ("Leads", "Filter LFO Lead"), 0),
    "tau": ("dexed", 16, 12),                # ARP 2600, 8va
    "hole": ("odin", ("Organ", "Phazzy Organ"), 0),
    "scrap": ("odin", ("Stabs", "Metallic (vel)"), 0),
    "gland": ("odin", ("Leads", "Glide Comb Lead"), -12),
}
# enemy kind -> (pattern positions in 16ths, semis rel root, dur_steps)
ENEMY_CELLS = {
    "mite": ([(0, 12, 1), (4, 12, 1), (8, 12, 1), (12, 12, 1)], BASS_FM),
    "husk": ([(0, 0, 2), (4, 0, 2), (8, 0, 2), (12, 0, 2)], BASS_FM),
    "spitter": ([(0, 0, 2), (6, 1, 2), (10, 0, 2)], BASS_FM),
    "shrieker": ([(0, 6, 2), (8, 6, 2), (14, 7, 1)], BASS_FM),
    "brute": ([(0, 0, 8), (8, 7, 8)], BASS_DEEP),
    "warden": ([(0, -12, 16)], BASS_DEEP),
    "flicker": ([(6, 1, 1), (14, 13, 1)], BASS_FM),
}

DRAGONFLY = next((voices.SCRATCH / "dragonfly-reverb-3.2.10")
                 .rglob("DragonflyHallReverb.vst3"))
HALL = dict(dry_level=80.0, early_level=10.0, late_level=20.0, size_m=40.0,
            width=80.0, predelay_ms=12.0, diffuse=80.0, low_cut_hz=4.0,
            low_cross_hz=700.0, low_mult_x=2.25, high_cut_hz=6250.0,
            high_cross_hz=4600.0, high_mult_x=0.30, spin_hz=2.1,
            wander_ms=17.0, decay_s=2.4, early_send=20.0, modulation=10.0)


def hall(x, wet_scale=1.0):
    import pedalboard
    rv = pedalboard.load_plugin(str(DRAGONFLY))
    for k, v in HALL.items():
        setattr(rv, k, v)
    rv.early_level = HALL["early_level"] * wet_scale
    rv.late_level = HALL["late_level"] * wet_scale
    if x.ndim == 1:
        x = np.stack([x, x])
    return rv(x.astype(np.float32), SR).astype(np.float64)


def _odin_patch(cat_name):
    cat, name = cat_name
    for p in o2.factory_patches(cat):
        if p.stem == name:
            return p
    raise FileNotFoundError(f"Odin2 factory patch {cat}/{name}")


def place(out, x, t_s, g=1.0):
    i = int(t_s * SR)
    if x.ndim == 1 and out.ndim == 2:
        x = np.stack([x, x], axis=1)
    if 0 <= i < len(out):
        seg = x[:len(out) - i]
        out[i:i + len(seg)] += seg * g


def melody_bars(events) -> int:
    n = sum(d for _, d in events) / 16
    bars = int(np.ceil(n / 2) * 2)
    return max(4, bars)


def bar_roots(events, n_bars) -> list[int]:
    """Per-bar root = first sounding melody note in the bar (semis rel
    final), folded into a bass-friendly octave."""
    roots, t = {}, 0
    for p, d in events:
        bar = t // 16
        if p is not None and bar not in roots:
            roots[bar] = ((p + 6) % 12) - 6
        t += d
    out = []
    last = 0
    for b in range(n_bars):
        last = roots.get(b, last)
        out.append(last)
    return out


def phrase_on(events, render_note, gap=0.02):
    """Render a melody event list through render_note(midi_off, dur_s)."""
    total = sum(d for _, d in events) * STEP
    out = np.zeros(int((total + 3.0) * SR))
    t = 0.0
    for p, d in events:
        if p is not None:
            x = render_note(p, d * STEP - gap)
            place_mono(out, x, t)
        t += d * STEP
    return out


def place_mono(out, x, t_s, g=1.0):
    i = int(t_s * SR)
    if 0 <= i < len(out):
        seg = x[:len(out) - i]
        out[i:i + len(seg)] += seg * g


def loopify(x, n, edge=0.01):
    """Cut to n samples, fold the tail back onto the start (ring becomes
    part of the loop), tiny edge fades."""
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    y = x[:n].copy()
    if len(y) < n:
        y = np.vstack([y, np.zeros((n - len(y), x.shape[1]))])
    tail = x[n:n + SR * 2]
    if len(tail):
        y[:len(tail)] += tail
    e = int(edge * SR)
    y[:e] *= np.linspace(0, 1, e)[:, None]
    y[-e:] *= np.linspace(1, 0, e)[:, None]
    return y


def norm_lufs(x, target=-15.0):
    mono = x.mean(axis=1) if x.ndim == 2 else x
    g = 10 ** ((target - voices.lufs(mono)) / 20.0)
    y = x * g
    pk = np.abs(y).max()
    if pk > 10 ** (-1.0 / 20):
        y *= 10 ** (-1.0 / 20) / pk
    return y


def write(path, x):
    import soundfile as sf
    x = np.clip(x, -1, 1)
    sf.write(str(path), (x * 32767).astype(np.int16), SR, subtype="PCM_16")
    print(f"  {path.name:22s} {len(x)/SR:6.1f}s")


# ---------------------------------------------------------------------------

def gen_bank(mel_name: str, outdir: Path):
    events = MELODIES[mel_name]
    chant_step_s = 60.0 / 72.0 / 4
    chant_dur = sum(d for _, d in events) * chant_step_s
    n_bars = max(4, int(np.ceil(chant_dur / BAR / 2) * 2))
    n = int(n_bars * BAR * SR)
    roots = bar_roots(events, n_bars)
    rng = np.random.default_rng(7)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[{mel_name}] {n_bars} bars @ {BPM:.0f}bpm -> {outdir}")

    # ---- monk (shared by prayer + stalwart) -------------------------------
    # The chant rides its own solemn grid (M1's 72bpm quarter-syllable —
    # the director-approved rendering; at the 110bpm 16th grid the voice
    # warbles and the contour is lost). The holy lane floats over the
    # band's clock per the album grammar.
    vows = [None if p is None else (-0.5 if d >= 8 else 0.2)
            for p, d in events]
    monk = render_vocal(events, chant_step_s, base_midi=50, vowels=vows)
    monk /= np.abs(monk).max() + 1e-9

    # ---- PRAYER: sanctuary -------------------------------------------------
    choir_ev = [(r, 16) for r in roots]
    choir = phrase_on(choir_ev, lambda p, d: o2.render_notes(
        _odin_patch(CHOIR), [50 + p, 57 + p], d, tail_s=1.5), gap=0.1)
    organ = phrase_on(choir_ev, lambda p, d: o2.render_notes(
        _odin_patch(ORGAN_HOLY), [38 + p, 45 + p], d, tail_s=1.0), gap=0.1)
    bells = np.zeros(n + 4 * SR)
    t = 0
    for p, d in events:
        if p is None and d >= 4:
            place_mono(bells, bell_hit(0.4), t * chant_step_s)
        t += d
    pr = np.zeros((n + 4 * SR, 2))
    place(pr, hall(monk, 1.6).T, 0, 1.0)
    place(pr, hall(choir, 1.4).T, 0, 0.5)
    place(pr, hall(organ, 1.2).T, 0, 0.35)
    place(pr, hall(bells, 1.3).T, 0, 0.5)
    write(outdir / "prayer.wav", norm_lufs(loopify(pr, n), -16))

    # ---- drums ------------------------------------------------------------
    def drums_half():
        d = np.zeros(n + SR)
        kick = K.kick_knob(25, 25, 50)
        for bar in range(n_bars):
            for pos, vel, inst in [(0, 1.0, "kick"), (8, .95, "snare"),
                                   (4, .85, "kick"), (12, .5, "kick")]:
                x = kick * (0.6 + 0.4 * vel) if inst == "kick" \
                    else K.hit("snare", vel, rng)
                K.place(d, x, bar * BAR + pos * STEP + rng.normal(0, .003))
            for pos in range(0, 16, 2):
                acc = .75 if pos % 8 == 4 else (.5 if pos % 4 == 0 else .35)
                K.place(d, K.hit("chh", acc, rng),
                        bar * BAR + pos * STEP + rng.normal(0, .002))
            if bar % 2 == 1:
                K.place(d, K.hit("ohh", .7, rng), bar * BAR + 14 * STEP)
        return d

    def drums_groove():
        d = np.zeros(n + SR)
        kick = K.kick_knob(25, 25, 25)
        for bar in range(n_bars):
            for pos in (0, 4, 8, 12):
                K.place(d, kick * (0.9 + 0.1 * rng.random()),
                        bar * BAR + pos * STEP + rng.normal(0, .002))
            for pos in (4, 12):
                K.place(d, K.hit("clap", .8, rng), bar * BAR + pos * STEP)
            for pos in range(0, 16):
                acc = .6 if pos % 4 == 2 else .3
                K.place(d, K.hit("chh", acc, rng),
                        bar * BAR + pos * STEP + rng.normal(0, .0015))
        return d

    # ---- CONTEMPT: the dismissive groove -----------------------------------
    dg = drums_groove()
    fmbass = np.zeros(n + SR)
    patch_fm = _odin_patch(BASS_FM)
    for bar, r in enumerate(roots):
        for pos in (0, 3, 6, 8, 11, 14):
            x = o2.render_notes(patch_fm, [38 + r], STEP * 1.6, tail_s=0.2)
            place_mono(fmbass, x, bar * BAR + pos * STEP)
    frag = [e for e in events if e[0] is not None][:6]
    stabs = np.zeros(n + SR)
    patch_stab = _odin_patch(("Stabs", "House Stab"))
    for bar in range(0, n_bars, 2):
        tt = bar * BAR
        for p, d in frag[:3]:
            x = o2.render_notes(patch_stab, [62 + p], STEP * 2, tail_s=0.3)
            place_mono(stabs, x, tt)
            tt += 2 * STEP
    fmbass = gc.sidechain_duck(fmbass[:len(dg)], dg, amount=0.4,
                               release_s=0.1)
    stabs = gc.sidechain_duck(stabs[:len(dg)], dg, amount=0.35,
                              release_s=0.1)
    ct = np.zeros((n + 2 * SR, 2))
    place(ct, dg, 0, 0.9)
    place(ct, fmbass, 0, 0.75)
    place(ct, stabs, 0, 0.5)
    write(outdir / "contempt.wav", norm_lufs(loopify(ct, n), -15))

    # ---- STALWART: the wall -------------------------------------------------
    dh = drums_half()

    def wall_take(seed):
        r = np.random.default_rng(seed)
        out = np.zeros(n + SR)
        for bar in range(n_bars):
            root = roots[bar]
            for e8 in range(8):
                mute = 0.0 if e8 == 0 else 0.85
                vel = (1.0 if e8 == 0 else .55) * (1 + r.normal(0, .05))
                h = voices.chug_note(r, root, STEP * 1.9 * (1.6 - mute),
                                     mute, vel)
                place_mono(out, h, bar * BAR + e8 * 2 * STEP
                           + r.normal(0, .005))
        return out

    wl, wr = wall_take(11), wall_take(22)
    deep = np.zeros(n + SR)
    patch_deep = _odin_patch(BASS_DEEP)
    for bar, r in enumerate(roots):
        x = o2.render_notes(patch_deep, [26 + r], BAR * 0.95, tail_s=0.3)
        place_mono(deep, x, bar * BAR)
    wl = gc.sidechain_duck(wl[:len(dh)], dh, amount=0.35, release_s=0.1)
    wr = gc.sidechain_duck(wr[:len(dh)], dh, amount=0.35, release_s=0.1)
    deep = gc.sidechain_duck(deep[:len(dh)], dh, amount=0.45, release_s=0.12)
    monk_dry = hall(monk, 0.55).T
    st = np.zeros((n + 2 * SR, 2))
    place(st, dh, 0, 0.85)
    st[:, 0] += np.pad(wl, (0, len(st) - len(wl)))[:len(st)] * 0.75
    st[:, 1] += np.pad(wr, (0, len(st) - len(wr)))[:len(st)] * 0.75
    place(st, deep, 0, 0.8)
    place(st, monk_dry, 0, 0.7)
    stl = loopify(st, n)
    stl2 = np.tanh(stl * 1.1) / np.tanh(1.1)
    write(outdir / "stalwart.wav", norm_lufs(stl2, -14))

    # ---- riser + sting ------------------------------------------------------
    import synth as sy
    rn = int(2 * BAR * SR)
    noise = sy.pink_noise(2 * BAR, seed=3)[:rn]
    sweep = np.linspace(0.15, 1.0, rn) ** 2
    riser = noise * sweep
    write(outdir / "riser.wav", norm_lufs(
        loopify(np.stack([riser, riser], axis=1), rn), -18))
    stg = np.zeros((int(2 * BAR * SR), 2))
    place(stg, K.hit("crash", 1.0, rng), 0, 0.9)
    place(stg, bell_hit(1.0), 0, 0.8)
    place(stg, voices.chug_note(rng, 0, 1.2, 0.0, 1.0), 0, 0.9)
    write(outdir / "sting.wav", norm_lufs(stg, -13))

    # ---- stage beds ---------------------------------------------------------
    for tier, patch in BEDS.items():
        p = _odin_patch(patch)
        x = o2.render_notes(p, [38 - 2 * (tier - 1)], n_bars * BAR * 0.6,
                            tail_s=2.0)
        bed = np.zeros((n + 2 * SR, 2))
        place(bed, x, 0, 1.0)
        place(bed, x, n_bars * BAR * 0.55, 0.8)
        write(outdir / f"bed_t{tier}.wav", norm_lufs(loopify(bed, n), -19))

    # ---- weapon leads -------------------------------------------------------
    lead_ev = [(p, d) for p, d in events]
    for wname, (kind, sel, oct_shift) in WEAPON_LEADS.items():
        if kind == "odin":
            patch = _odin_patch(sel)
            x = phrase_on(lead_ev, lambda p, d: o2.render_notes(
                patch, [62 + p + oct_shift], d, tail_s=0.4))
        else:
            x = phrase_on(lead_ev, lambda p, d: dx.render_notes(
                sel, [62 + p + oct_shift], d, tail_s=0.4))
        x = gc.sidechain_duck(x[:n + SR], dh[:n + SR], amount=0.3,
                              release_s=0.1)
        ld = np.zeros((n + SR, 2))
        place(ld, x, 0, 1.0)
        write(outdir / f"lead_{wname}.wav", norm_lufs(loopify(ld, n), -16))

    # ---- enemy bass cells ---------------------------------------------------
    for ename, (cells, patch_sel) in ENEMY_CELLS.items():
        p = _odin_patch(patch_sel)
        eb = np.zeros(n + SR)
        for bar, r in enumerate(roots):
            for pos, semi, dsteps in cells:
                x = o2.render_notes(p, [38 + r + semi], dsteps * STEP * 0.9,
                                    tail_s=0.25)
                place_mono(eb, x, bar * BAR + pos * STEP)
        eb = gc.sidechain_duck(eb[:n + SR], dh[:n + SR], amount=0.35,
                               release_s=0.1)
        eo = np.zeros((n + SR, 2))
        place(eo, eb, 0, 1.0)
        write(outdir / f"bass_{ename}.wav", norm_lufs(loopify(eo, n), -17))

    meta = dict(melody=mel_name, bpm=BPM, bars=n_bars)
    import json
    (outdir / "bank.json").write_text(json.dumps(meta))
    return outdir


if __name__ == "__main__":
    mel = sys.argv[1] if len(sys.argv) > 1 else "dies_irae"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        Path("out/banks") / mel
    gen_bank(mel, out)
