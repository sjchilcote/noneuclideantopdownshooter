"""Tutti — complete tracks, each telling a DIFFERENT story.

    uv run python tools/musicgen/tutti.py [melody|all]

Director's variety laws (2026-07-15):
- no track shares more than TWO elements with any other (checked by
  check_uniqueness(), run before every batch);
- every element axis is cast per track: wall voice, basses, choir,
  flourish, bell variant, drum kit (style/kick-knob/snare/hats), drone
  spine, lead, progressions, accent templates, seeds;
- STRUCTURE varies: each recipe declares its own form from typed
  sections — vigil / ritual (drum-less, the album's Chant-of-Trust
  move) / entry / develop / rebuild (one element, layers added) /
  peak / outro;
- titles on-theme (PROVISIONAL — the director edits them);
- Delay Lama = spice: distant, processed, always EMERGES (6s ramp);
- transitions: producer's pull + riser/reverse tells; never a
  master-bus chop; drone spine survives everything.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soundgen"))

import generate_bank as G          # noqa: E402
import gordon_chain as gc          # noqa: E402
import harmony                     # noqa: E402
import riffs                       # noqa: E402
import specimen_kit as SP          # noqa: E402
import tr909_kit as K              # noqa: E402
import vital_bank as VB            # noqa: E402
import voices                      # noqa: E402
from parts import bell_hit         # noqa: E402

SR = 44100
BPM = 110.0
BAR = 240.0 / BPM
STEP = BAR / 16

_ACC = {"A": riffs.ACCENTS_A, "B": riffs.ACCENTS_B, "C": riffs.ACCENTS_C}
_SPINE_BANK = {"Daphne Oram 2": "tngkaos", "Ether": "tngkaos",
               "Boass": "tngkaos", "Machine Drone": "5years",
               "Faulty Connection": "5years", "Taiga": "5years",
               "St. George": "5years", "Lysergic": "5years",
               "MissingNo": "5years", "Faux": "5years",
               "Digivice": "5years"}

# ---------------------------------------------------------------------------
# Recipes — one per track; forms differ in SHAPE, not just content.
# form: list of (section_type, bars, progression)
# ---------------------------------------------------------------------------
RECIPES = {
    "dies_irae": dict(
        title="tutti_dies_irae",
        form=[("vigil", 8, "vigil"), ("entry", 8, "pressure"),
              ("develop", 8, "swagger"), ("peak", 8, "ratchet"),
              ("outro", 4, "vigil")],
        accents=("A", "B", "C"), lead="lead_rail",
        wall=("5years", "Supersync"), bass=("5years", "Heavy"),
        fm=("5years", "FM Bass 1"), choir=("5years", "Choir Pad"),
        flour=("5years", "Hoover"), bell=("authored", 0),
        kit=dict(style="half", kick=(25, 25, 50), snare="snare",
                 hats="eighth"),
        spine=("Daphne Oram 2", "Faulty Connection", "Taiga",
               "St. George", "Ether"), seeds=(11, 22, 33, 44, 7)),
    "media_vita": dict(
        title="tutti_media_vita",
        form=[("vigil", 8, "vigil"), ("ritual", 8, "pressure"),
              ("entry", 8, "grind"), ("peak", 8, "pressure"),
              ("vigil", 4, "vigil")],
        accents=("B", "A", "C"), lead="lead_hole",
        wall=("5years", "Reso Poly"), bass=("5years", "Sub Fall"),
        fm=("5years", "Nicotine"), choir=("5years", "Laika"),
        flour=("5years", "Injustice"), bell=("authored", -5),
        kit=dict(style="doom", kick=(50, 0, 75), snare="rim",
                 hats="quarter"),
        spine=("Ether", "Machine Drone", "Lysergic", "St. George",
               "Daphne Oram 2"), seeds=(13, 24, 35, 46, 9)),
    "vexilla_regis": dict(
        title="tutti_vexilla_regis",
        form=[("entry", 8, "ratchet"), ("develop", 8, "swagger"),
              ("ritual", 6, "vigil"), ("peak", 8, "ratchet"),
              ("outro", 4, "vigil")],
        accents=("A", "C", "A"), lead="lead_smg",
        wall=("5years", "Knowledge"), bass=("5years", "Galatheae"),
        fm=("5years", "Core Robot"), choir=("5years", "Monument"),
        flour=("5years", "Splatter"), bell=("tubular", 0),
        kit=dict(style="march", kick=(0, 50, 50), snare="snare",
                 hats="sixteenth"),
        spine=("Taiga", "Faulty Connection", "MissingNo", "Lysergic",
               "Ether"), seeds=(15, 26, 37, 48, 11)),
    "idumea": dict(
        title="tutti_idumea",
        form=[("develop", 8, "swagger"), ("ritual", 6, "vigil"),
              ("peak", 8, "grind"), ("develop", 6, "swagger"),
              ("outro", 4, "vigil")],
        accents=("C", "B", "C"), lead="lead_pistol",
        wall=("5years", "Tesla Coil"), bass=("5years", "Aqualung"),
        fm=("5years", "Donk"), choir=("5years", "Cretacic"),
        flour=("5years", "Headache"), bell=("none", 0),
        kit=dict(style="groove", kick=(25, 25, 25), snare="clap",
                 hats="offbeat"),
        spine=("Faux", "Boass", "Digivice", "Machine Drone", "Taiga"),
        seeds=(17, 28, 39, 50, 13)),
    "pange_lingua": dict(
        title="tutti_pange_lingua",
        form=[("vigil", 6, "vigil"), ("rebuild", 8, "grind"),
              ("entry", 8, "pressure"), ("peak", 8, "lunge"),
              ("ritual", 4, "vigil")],
        accents=("B", "A", "C"), lead="lead_tau",
        wall=("5years", "Malfunction"), bass=("tngkaos", "Fat Bass"),
        fm=("5years", "Acid Bass 3"), choir=("5years", "Melloflute"),
        flour=("5years", "Cryogen"), bell=("spec_imp", 0),
        kit=dict(style="half", kick=(75, 50, 25), snare="snare+clap",
                 hats="sparse"),
        spine=("Lysergic", "St. George", "Ether", "Faulty Connection",
               "Machine Drone"), seeds=(19, 30, 41, 52, 15)),
    "lhomme_arme": dict(
        title="tutti_lhomme_arme",
        form=[("entry", 8, "ratchet"), ("peak", 8, "swagger"),
              ("ritual", 6, "pressure"), ("peak", 8, "ratchet"),
              ("outro", 4, "vigil")],
        accents=("A", "B", "A"), lead="lead_shotgun",
        wall=("5years", "Movie Intro"), bass=("5years", "Follin"),
        fm=("5years", "Supersync"), choir=("5years", "Museum"),
        flour=("5years", "Western"), bell=("authored", 7),
        kit=dict(style="dbeat", kick=(25, 75, 50), snare="snare+clap",
                 hats="offbeat"),
        spine=("Machine Drone", "Taiga", "Boass", "Daphne Oram 2",
               "St. George"), seeds=(21, 32, 43, 54, 17)),
    "old_100th_dark": dict(
        title="tutti_old_100th_dark",
        form=[("ritual", 8, "vigil"), ("develop", 8, "grind"),
              ("entry", 6, "pressure"), ("peak", 8, "ratchet"),
              ("outro", 4, "vigil")],
        accents=("B", "C", "B"), lead="lead_gland",
        wall=("5years", "Home Run"), bass=("5years", "Bamboo"),
        fm=("5years", "Sonar"), choir=("5years", "Hypercube PAD"),
        flour=("5years", "Gecko"), bell=("ride", 0),
        kit=dict(style="groove", kick=(50, 25, 75), snare="rim",
                 hats="quarter"),
        spine=("St. George", "Lysergic", "Faulty Connection", "Ether",
               "Taiga"), seeds=(23, 34, 45, 56, 19)),
}


def check_uniqueness(max_shared: int = 2):
    """No pair of tracks shares more than max_shared elements."""
    def axes(r):
        return {
            "lead": r["lead"], "wall": r["wall"], "bass": r["bass"],
            "fm": r["fm"], "choir": r["choir"], "flour": r["flour"],
            "bell": r["bell"][0], "kit_style": r["kit"]["style"],
            "kick": r["kit"]["kick"], "snare": r["kit"]["snare"],
            "hats": r["kit"]["hats"], "accents": r["accents"],
            "spine": frozenset(r["spine"]),
            "shape": tuple(s for s, _, _ in r["form"]),
        }
    names = list(RECIPES)
    worst = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            aa, bb = axes(RECIPES[a]), axes(RECIPES[b])
            shared = [k for k in aa if aa[k] == bb[k]]
            worst = max(worst, len(shared))
            if len(shared) > max_shared:
                raise AssertionError(f"{a} vs {b} share {shared}")
    return worst


# ---------------------------------------------------------------------------
# element renderers
# ---------------------------------------------------------------------------

def place(buf, x, t_s, g=1.0):
    i = int(t_s * SR)
    if 0 <= i < len(buf):
        seg = x[:len(buf) - i]
        buf[i:i + len(seg)] += seg * g


def lp(ctx, lane, buf, x, t_s, g=1.0):
    """place() that ALSO captures into the named lane buffer when the
    compose pass is collecting stems (bank mode)."""
    place(buf, x, t_s, g)
    lanes = ctx.get("lanes")
    if lanes is not None:
        place(lanes[lane], x, t_s, g)


def monksig(ctx, x, t_s, g=1.0):
    """Ground-truth marker: mirrors a CLOSE monk placement into the
    detection-only 'monksig' lane. Adds NOTHING to the audible mix --
    the gap-fill law reads this lane to know where the chant is
    actually CARRYING; every audio-derived detector failed (spine
    underlay, choir pads and hall tails all keep bar-RMS healthy
    through his composed rests). monk_far placements deliberately do
    NOT count: a sidechain-ducked distant wash under full drums reads
    as texture, not the chant (media_vita's develop "coverage" was
    exactly that, and the full-mix probe heard 10s of absence)."""
    lanes = ctx.get("lanes")
    if lanes is not None:
        place(lanes["monksig"], x, t_s, g)


def drum_bus(d):
    import synth as sy
    par = np.tanh(d * 4.0)
    crush = sy.bitcrush(d, bits=10, rate_divisor=3) * 0.5
    polygon = gc._spring_reverb(d, mix=1.0) * 0.22
    y = d * 0.9 + par * 0.8 + crush + polygon
    return y / (np.abs(y).max() + 1e-9) * np.abs(d).max() * 1.15


def _knock():
    m = int(0.28 * SR)
    ph = 2 * np.pi * (52 - 14 * np.arange(m) / m) * np.arange(m) / SR
    return np.sin(np.cumsum(np.diff(ph, prepend=0))) \
        * np.exp(-np.arange(m) / (0.09 * SR))


def _snare_hit(kind, vel, rng):
    if kind == "snare":
        return K.hit("snare", vel, rng)
    if kind == "clap":
        return K.hit("clap", vel, rng)
    if kind == "rim":
        return K.hit("rim", min(1.0, vel * 1.2), rng)
    x1, x2 = K.hit("snare", vel, rng), K.hit("clap", vel * .8, rng)
    n = max(len(x1), len(x2))
    y = np.zeros(n)
    y[:len(x1)] += x1
    y[:len(x2)] += x2
    return y


def _hat_positions(hats):
    return {"eighth": list(range(0, 16, 2)),
            "quarter": [0, 4, 8, 12],
            "sixteenth": list(range(16)),
            "offbeat": [2, 6, 10, 14],
            "sparse": [0, 6, 8, 14]}[hats]


_KICKPAT = {"half": [(0, 1.0), (4, .85), (12, .5)],
            "groove": [(0, 1.0), (4, .9), (8, 1.0), (12, .9)],
            "doom": [(0, 1.0), (7, .8)],
            "march": [(0, 1.0), (4, .9), (8, .95), (12, .9)],
            "dbeat": [(0, 1.0), (3, .7), (8, 1.0), (11, .7)]}
_SNPAT = {"half": [8], "groove": [4, 12], "doom": [8],
          "march": [4, 12], "dbeat": [4, 12]}


def drums(rec, n_bars, rng, fills_at=()):
    kit = rec["kit"]
    d = np.zeros(int(n_bars * BAR * SR) + SR)
    kick = K.kick_knob(*kit["kick"])
    kick = kick + np.pad(_knock() * 0.9,
                         (0, max(0, len(kick) - int(0.28 * SR))))[:len(kick)]
    hatpos = _hat_positions(kit["hats"])
    for bar in range(n_bars):
        if bar in fills_at:
            for pos in range(8, 16):
                v = 0.4 + 0.6 * (pos - 8) / 7
                K.place(d, _snare_hit(kit["snare"], v, rng),
                        bar * BAR + pos * STEP)
            K.place(d, kick, bar * BAR)
            continue
        for pos, vel in _KICKPAT[kit["style"]]:
            K.place(d, kick * (0.6 + 0.4 * vel), bar * BAR + pos * STEP)
        for pos in _SNPAT[kit["style"]]:
            K.place(d, _snare_hit(kit["snare"], .95, rng),
                    bar * BAR + pos * STEP)
        for pos in hatpos:
            acc = (.75 if pos % 8 == 4 else .45) * (1 + rng.normal(0, .12))
            K.place(d, K.hit("chh", max(.15, acc), rng),
                    bar * BAR + pos * STEP)
        if kit["style"] == "march" and bar % 2 == 1:   # military ruff
            for pos in (14, 15):
                K.place(d, _snare_hit(kit["snare"], .4, rng),
                        bar * BAR + pos * STEP)
        if bar >= n_bars // 2:                          # back-half metal
            import synth as sy
            for pos in (2, 10):
                K.place(d, sy.bitcrush(K.hit("ride", .5, rng), bits=9) * .5,
                        bar * BAR + pos * STEP)
    return d


def bell_render(rec, vel=0.6):
    variant, shift = rec["bell"]
    if variant == "none":
        return np.zeros(64)
    if variant == "authored":
        x = bell_hit(vel)
        if shift:
            n = int(len(x) / 2 ** (shift / 12.0))
            x = np.interp(np.linspace(0, len(x) - 1, n),
                          np.arange(len(x)), x)
        return x
    if variant == "tubular":
        y = VB.render_seq("5years", "Tubular Bells",
                          [(62 + shift, 0.0, 2.5, 100)], 2.5, 2.0)
        return y / (np.abs(y).max() + 1e-9) * vel
    if variant == "spec_imp":
        for cat, nm, f, midi, bpm in SP.catalog("IMP"):
            if nm == "Crackle Impactor":
                return SP.load(str(f)) * vel
    if variant == "ride":
        return K.hit("ride", vel, np.random.default_rng(1)) * 1.4
    raise ValueError(variant)


def wall_take(rec, riff, seed, drive):
    import synth as sy
    rng = np.random.default_rng(seed)
    first_take = seed in (rec["seeds"][0], rec["seeds"][2])
    seq = []
    t = 0
    for p, steps, art in riff:
        off = 0.0 if first_take else float(rng.normal(0, 0.004))
        if art == "open":
            for iv, vv in ((12, 118), (19, 104), (24, 88)):
                seq.append((38 + p + iv, max(0.0, t * STEP + off),
                            STEP * steps * 1.6, vv))
        else:
            seq.append((38 + p, max(0.0, t * STEP + off),
                        STEP * 0.9, 96 if t % 16 else 118))
        t += steps
    out = VB.render_seq(*rec["wall"], seq, t * STEP, 0.4)
    out = voices.amp(out * 0.6 / (np.abs(out).max() + 1e-9), drive)
    return sy.highpass(out, 120)


def _sub_layer(seq, total_s):
    n = int((total_s + 0.5) * SR)
    out = np.zeros(n)
    for note, t0, d, v in seq:
        f = 440.0 * 2 ** ((note - 12 - 69) / 12.0)
        m = int(d * SR)
        ph = 2 * np.pi * f * np.arange(m) / SR
        env = np.minimum(1, np.arange(m) / (0.005 * SR)) * \
            np.minimum(1, (m - np.arange(m)) / (0.02 * SR))
        place(out, np.tanh(np.sin(ph) * 2.0) * env * (v / 127), t0)
    return out


def vb_seq_raw(bank_stem, seq, total, tail=1.0):
    x = VB.render_seq(*bank_stem, seq, total, tail)
    return x / (np.abs(x).max() + 1e-9)


def _pull(x, end_s, fade_ms=35):
    """The producer's pre-drop PULL: this lane stops, its space rings."""
    y = x.copy()
    e = int(end_s * SR)
    f = int(fade_ms * SR / 1000)
    if 0 < e < len(y):
        y[e - f:e] *= np.linspace(1, 0, f)
        y[e:] = 0.0
    return y


def _boundary_tell(ctx, t_s, rng):
    import synth as sy
    C = ctx["C"]
    rn = int(1.0 * BAR * SR)
    riser = sy.pink_noise(1.0 * BAR, seed=int(t_s))[:rn] \
        * np.linspace(0.05, 0.9, rn) ** 2
    lp(ctx, "tells", C, sy.highpass(riser, 800) * 0.7, t_s - BAR)
    rev = G.hall(K.hit("crash", 0.8, rng), 1.5).T.mean(axis=1)[::-1]
    lp(ctx, "tells", C, rev[-int(BAR * SR):] * 0.6, t_s - BAR)
    lp(ctx, "tells", C, K.hit("crash", 0.85, rng), t_s, 0.9)
    boom = np.sin(2 * np.pi * 55 * np.arange(int(0.5 * SR)) / SR) \
        * np.exp(-np.arange(int(0.5 * SR)) / (0.12 * SR))
    lp(ctx, "tells", C, boom * 0.9, t_s)


# ---------------------------------------------------------------------------
# section renderers — each writes into ctx buffers at ctx["t"]
# ---------------------------------------------------------------------------

def _bass_seq_from_riff(riff, base=26):
    seq, t = [], 0
    for pp, steps, art in riff:
        seq.append((base + pp, t * STEP,
                    STEP * steps * (0.92 if art == "mute" else 1.6),
                    118 if art == "open" else 96))
        t += steps
    return seq, t * STEP


def _monk_enter(ctx, t0, gain=0.5, ramp_s=6.0):
    monk = ctx["monk"]
    ramp = np.minimum(1, np.arange(len(monk)) / (ramp_s * SR)) ** 1.5
    lp(ctx, "holy", ctx["C"], monk * ramp * gain, t0 + BAR)
    monksig(ctx, monk * ramp * gain, t0 + BAR)
    ctx["monk_used"] = True


def sec_vigil(ctx, bars, prog):
    rec, C, t0 = ctx["rec"], ctx["C"], ctx["t"]
    if not ctx["monk_used"]:
        head = [(pp, d) for pp, d in ctx["events"] if pp is not None][:8]
        cs, tt = [], BAR
        for pp, d in head:
            cs.append((62 + pp, tt, d * ctx["chant_step"] * 1.1, 96))
            tt += d * ctx["chant_step"]
        ch = vb_seq_raw(rec["choir"], cs, bars * BAR, 1.5)
        lp(ctx, "holy", C, G.hall(ch, 1.6).T.mean(axis=1) * 0.45, t0)
        # call-and-response, never simultaneous (director: "two vocals
        # fight for the same aural space"): the choir STATES the line,
        # the monk answers after it
        _monk_enter(ctx, t0 + tt + BAR)
    lp(ctx, "holy", C, G.hall(bell_render(rec), 1.4).T.mean(axis=1) * 0.5,
       t0 + 2 * BAR)
    lp(ctx, "holy", C, G.hall(bell_render(rec, 0.4), 1.4).T.mean(axis=1) * 0.4,
       t0 + (bars - 2) * BAR)


def sec_ritual(ctx, bars, prog):
    """Drum-less: choir chords + monk + sparse flourish stabs."""
    rec, C, t0 = ctx["rec"], ctx["C"], ctx["t"]
    roots = harmony.roots_16(prog, bars)
    cs = []
    for bar in range(bars):
        r = roots[bar * 16]
        for nn in (50 + r, 57 + r, 62 + r):
            cs.append((nn, bar * BAR, BAR * 0.97, 96))
    ch = vb_seq_raw(rec["choir"], cs, bars * BAR, 1.5)
    lp(ctx, "holy", C, G.hall(ch, 1.7).T.mean(axis=1) * 0.5, t0)
    if not ctx["monk_used"]:
        _monk_enter(ctx, t0 + 2 * BAR)
    else:
        lp(ctx, "holy", C, ctx["monk_far"] * 0.4, t0 + 2 * BAR)
    fl = []
    for bar in range(1, bars, 2):
        r = roots[bar * 16]
        fl.append((62 + r, bar * BAR + 8 * STEP, 3 * STEP, 100))
    if fl:
        x = vb_seq_raw(rec["flour"], fl, bars * BAR, 0.5)
        lp(ctx, "flour", C, x * 0.3, t0)


def sec_entry(ctx, bars, prog):
    rec, C, L, R, t0 = ctx["rec"], ctx["C"], ctx["L"], ctx["R"], ctx["t"]
    rng = ctx["rng"]
    import synth as sy
    acc = _ACC[rec["accents"][0]]
    if t0 > 0:
        fill = drums(rec, 1, rng, fills_at=(0,))
        lp(ctx, "drums", C, drum_bus(fill) * 0.7, t0 - BAR)
    dh = drums(rec, bars, rng)
    lp(ctx, "drums", C, drum_bus(dh) * 0.7, t0)
    roots = harmony.roots_16(prog, bars)
    riff = riffs.riff_16(ctx["events"], n_bars=bars, accents=acc,
                         chord_roots=roots)
    s = rec["seeds"]
    wl = wall_take(rec, riff, s[0], 18.0)
    wr = wall_take(rec, riff, s[1], 19.0)
    wl = gc.sidechain_duck(wl, dh[:len(wl)], amount=0.35, release_s=0.1)
    wr = gc.sidechain_duck(wr, dh[:len(wr)], amount=0.35, release_s=0.1)
    lp(ctx, "wall_L", L, wl * 0.7, t0)
    lp(ctx, "wall_R", R, wr * 0.7, t0)
    bseq, btot = _bass_seq_from_riff(riff)
    bass = sy.highpass(vb_seq_raw(rec["bass"], bseq, btot, 0.4), 90)
    sub = sy.lowpass(_sub_layer(bseq, btot), 90)
    m = min(len(bass), len(sub))
    bass = bass[:m] + sub[:m] * 0.55
    bass = gc.sidechain_duck(bass, dh[:len(bass)], amount=0.45,
                             release_s=0.12)
    lp(ctx, "bass", C, bass * 0.85, t0)
    if ctx["monk_used"]:
        lp(ctx, "holy", C, ctx["monk_far"] * 0.3, t0 + 2 * BAR)
    else:
        _monk_enter(ctx, t0 + 2 * BAR, gain=0.35)
    ans = riffs.lead_phrase(
        [(p, d) for p, d in ctx["events"] if p is not None][:6], factor=2)
    fl, tt = [], (bars - 2) * BAR
    for p, d in ans:
        fl.append((50 + p, tt, d * STEP * 1.2, 110))
        tt += d * STEP
    x = vb_seq_raw(rec["flour"], fl, bars * BAR, 0.5)
    x = gc.sidechain_duck(x, dh[:len(x)], amount=0.3, release_s=0.1)
    lp(ctx, "flour", C, x * 0.4, t0)


def sec_develop(ctx, bars, prog):
    rec, C, t0 = ctx["rec"], ctx["C"], ctx["t"]
    rng = ctx["rng"]
    acc = _ACC[rec["accents"][1]]
    dg = drums(rec, bars, rng, fills_at=(bars - 1,))
    dgp = _pull(dg, bars * BAR - 0.5 * BAR) if ctx["next_is_peak"] else dg
    lp(ctx, "drums", C, drum_bus(dgp) * 0.7, t0)
    roots = harmony.roots_16(prog, bars)
    r3 = riffs.riff_16(ctx["events"], n_bars=bars, accents=acc,
                       chord_roots=roots)
    fseq, ftot = _bass_seq_from_riff(r3, base=38)
    fm = vb_seq_raw(rec["fm"], fseq, ftot, 0.3)
    fm = gc.sidechain_duck(fm, dg[:len(fm)], amount=0.4, release_s=0.1)
    if ctx["next_is_peak"]:
        fm = _pull(fm, bars * BAR - 0.5 * BAR)
    lp(ctx, "fm", C, fm * 0.6, t0)
    frag = riffs.lead_phrase(
        [(p, d) for p, d in ctx["events"] if p is not None][:8], factor=2)
    lseq = []
    for k in range(max(1, bars // 4)):
        tt = k * 4 * BAR
        for p, d in frag:
            lseq.append((62 + p, tt, (d + 0.5) * STEP, 108))
            tt += d * STEP
    lead = vb_seq_raw(VB.SLOTS[rec["lead"]], lseq, bars * BAR, 0.5)
    lead = gc.sidechain_duck(lead, dg[:len(lead)], amount=0.3,
                             release_s=0.1)
    if ctx["next_is_peak"]:
        lead = _pull(lead, bars * BAR - 0.5 * BAR)
    lp(ctx, "lead", C, lead * 0.5, t0)
    cs = [(50, 0.0, bars * BAR, 90), (57, 0.0, bars * BAR, 84)]
    c3 = vb_seq_raw(rec["choir"], cs, bars * BAR, 1.0)
    c3 = G.hall(c3, 1.8).T.mean(axis=1)
    c3 = gc.sidechain_duck(c3, dg[:len(c3)], amount=0.5, release_s=0.1)
    lp(ctx, "holy", C, c3 * 0.3, t0)


def sec_rebuild(ctx, bars, prog):
    """One element alone, layers admitted every 2 bars (album 07 blk03)."""
    rec, C, t0 = ctx["rec"], ctx["C"], ctx["t"]
    rng = ctx["rng"]
    roots = harmony.roots_16(prog, bars)
    r = riffs.riff_16(ctx["events"], n_bars=bars,
                      accents=_ACC[rec["accents"][1]], chord_roots=roots)
    fseq, ftot = _bass_seq_from_riff(r, base=38)
    fm = vb_seq_raw(rec["fm"], fseq, ftot, 0.3)
    lp(ctx, "fm", C, fm * 0.55, t0)
    dh = drums(rec, bars, rng)
    n_in = int(2 * BAR * SR)
    dh2 = dh.copy()
    dh2[:n_in] *= np.linspace(0, 1, n_in) ** 2
    lp(ctx, "drums", C, drum_bus(dh2) * 0.6, t0)
    wl = wall_take(rec, r, rec["seeds"][2], 17.0)
    keep = (bars - 2) * BAR
    wl2 = np.zeros_like(wl)
    wl2[int(keep * SR):] = wl[int(keep * SR):]
    lp(ctx, "wall_L", ctx["L"], wl2 * 0.6, t0)
    lp(ctx, "wall_R", ctx["R"], wl2 * 0.6, t0)


def sec_peak(ctx, bars, prog):
    rec, C, L, R, t0 = ctx["rec"], ctx["C"], ctx["L"], ctx["R"], ctx["t"]
    rng = ctx["rng"]
    import synth as sy
    rn = int(2 * BAR * SR)
    riser = sy.pink_noise(2 * BAR, seed=3)[:rn] * np.linspace(0.1, 1, rn) ** 2
    lp(ctx, "tells", C, riser * 0.5, t0 - 2 * BAR)
    lp(ctx, "tells", C, K.hit("crash", 1.0, rng), t0, 0.8)
    lp(ctx, "holy", C, G.hall(bell_render(rec, 1.0), 1.2).T.mean(axis=1) * 0.6, t0)
    dh4 = drums(rec, bars, rng, fills_at=(bars - 1,))
    lp(ctx, "drums", C, drum_bus(dh4) * 0.75, t0)
    acc = _ACC[rec["accents"][2]]
    roots = harmony.roots_16(prog, bars)
    if prog != "lunge" and bars >= 8:
        roots[6 * 16:8 * 16] = harmony.roots_16("lunge", 2)
    r4 = riffs.riff_16(ctx["events"], n_bars=bars, accents=acc,
                       chord_roots=roots)
    s = rec["seeds"]
    wl4 = wall_take(rec, r4, s[2], 20.0)
    wr4 = wall_take(rec, r4, s[3], 21.0)
    wl4 = gc.sidechain_duck(wl4, dh4[:len(wl4)], amount=0.35, release_s=0.1)
    wr4 = gc.sidechain_duck(wr4, dh4[:len(wr4)], amount=0.35, release_s=0.1)
    lp(ctx, "wall_L", L, wl4 * 0.8, t0)
    lp(ctx, "wall_R", R, wr4 * 0.8, t0)
    b4, btot = _bass_seq_from_riff(r4)
    bass4 = sy.highpass(vb_seq_raw(rec["bass"], b4, btot, 0.4), 90)
    sub4 = sy.lowpass(_sub_layer(b4, btot), 90)
    m4 = min(len(bass4), len(sub4))
    bass4 = bass4[:m4] + sub4[:m4] * 0.6
    bass4 = gc.sidechain_duck(bass4, dh4[:len(bass4)], amount=0.45,
                              release_s=0.12)
    lp(ctx, "bass", C, bass4 * 0.95, t0)
    cs = []
    for bar in range(bars):
        root = roots[bar * 16]
        for nn in (62 + root, 69 + root):
            cs.append((nn, bar * BAR, BAR * 0.97, 100))
    choir = vb_seq_raw(rec["choir"], cs, bars * BAR, 1.0)
    cw = sy.highpass(G.hall(choir, 1.3).T.mean(axis=1), 300)
    cw = gc.sidechain_duck(cw, dh4[:len(cw)], amount=0.5, release_s=0.12)
    lp(ctx, "holy", C, cw * 0.5, t0)
    monk2 = ctx["monk_far"]
    ramp2 = np.minimum(1, np.arange(len(monk2)) / (4.0 * SR)) ** 1.5
    m2 = gc.sidechain_duck(monk2 * ramp2, dh4[:len(monk2)],
                           amount=0.5, release_s=0.12)
    lp(ctx, "holy", C, m2 * 0.4, t0 + (bars // 2) * BAR)


def sec_outro(ctx, bars, prog):
    rec, C, t0 = ctx["rec"], ctx["C"], ctx["t"]
    rng = ctx["rng"]
    lp(ctx, "tells", C, K.hit("crash", 0.9, rng), t0)
    lp(ctx, "holy", C, G.hall(bell_render(rec, 0.7), 1.5).T.mean(axis=1) * 0.5,
       t0 + 0.5 * BAR)


SECS = {"vigil": sec_vigil, "ritual": sec_ritual, "entry": sec_entry,
        "develop": sec_develop, "rebuild": sec_rebuild, "peak": sec_peak,
        "outro": sec_outro}
_BAND = {"entry", "develop", "peak", "rebuild"}


# ---------------------------------------------------------------------------

LANE_NAMES = ("holy", "drums", "wall_L", "wall_R", "bass",
              "fm", "lead", "flour", "tells", "spine", "monksig")


def compose(mel_name: str, collect_lanes: bool = False):
    events = G.MELODIES[mel_name]
    rec = RECIPES[mel_name]
    form = rec["form"]
    rng = np.random.default_rng(rec["seeds"][4])
    total_s = sum(b for _, b, _ in form) * BAR + 6.0
    n = int(total_s * SR)
    L, R, C = np.zeros(n), np.zeros(n), np.zeros(n)

    chant_step = 60.0 / 72.0 / 4
    import synth as sy
    vows = [None if p is None else (-0.5 if d >= 8 else 0.2)
            for p, d in events]
    monk_raw = G.render_vocal(events, chant_step, base_midi=50, vowels=vows)
    monk_raw /= np.abs(monk_raw).max() + 1e-9
    monk_raw = sy.lowpass(monk_raw, 5000)
    harsh = sy.highpass(sy.lowpass(monk_raw, 4500), 1800)
    monk_raw = monk_raw - 0.8 * harsh
    lanes = ({nm: np.zeros(n) for nm in LANE_NAMES}
             if collect_lanes else None)
    ctx = dict(rec=rec, events=events, L=L, R=R, C=C, rng=rng, t=0.0,
               lanes=lanes,
               monk=G.hall(monk_raw, 2.4).T.mean(axis=1),
               monk_far=G.hall(monk_raw, 2.0).T.mean(axis=1),
               chant_step=chant_step, monk_used=False,
               next_is_peak=False)

    t = 0.0
    for i, (stype, bars, prog) in enumerate(form):
        ctx["t"] = t
        ctx["next_is_peak"] = (i + 1 < len(form)
                               and form[i + 1][0] == "peak")
        prev_band = i > 0 and form[i - 1][0] in _BAND
        if i > 0 and stype in _BAND and not prev_band:
            _boundary_tell(ctx, t, rng)
        SECS[stype](ctx, bars, prog)
        t += bars * BAR

    # drone spine: one texture per section, survives everything
    D = np.zeros(n)
    gains = (0.20, 0.16, 0.14, 0.18, 0.20)
    notes = (36, 24, 36, 24, 36)
    tt = 0.0
    for i, (stype, bars, prog) in enumerate(form):
        nm = rec["spine"][i % len(rec["spine"])]
        dur = bars * BAR
        y = VB.render_seq(_SPINE_BANK[nm], nm,
                          [(notes[i % 5], 0.0, dur, 96)], dur, tail_s=1.0)
        y = sy.lowpass(y / (np.abs(y).max() + 1e-9), 1800)
        e = int(0.4 * SR)
        y[:e] *= np.linspace(0, 1, e)
        place(D, y * gains[i % 5], tt)
        if lanes is not None:
            place(lanes["spine"], y * gains[i % 5], tt)
        tt += dur
    C = C + D

    mono = (L + R) * 0.5 + C
    glue = G.hall(mono, 0.5).T.mean(axis=1)
    C = C + 0.38 * glue[:len(C)]
    st = np.stack([L + C, R + C], axis=1)
    st[:, 0] = sy.highpass(st[:, 0], 28)
    st[:, 1] = sy.highpass(st[:, 1], 28)
    st = np.tanh(st * 0.6) / np.tanh(0.6)
    g = 10 ** ((-15.0 - voices.lufs(st.mean(axis=1))) / 20.0)
    st *= g
    pk = np.abs(st).max()
    if pk > 10 ** (-1.0 / 20):
        st *= 10 ** (-1.0 / 20) / pk
    if collect_lanes:
        return st, lanes, ctx
    return st


def slug(title):
    import re
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def main():
    import soundfile as sf
    arg = sys.argv[1] if len(sys.argv) > 1 else "dies_irae"
    names = list(RECIPES) if arg == "all" else [arg]
    worst = check_uniqueness()
    print(f"uniqueness ok (worst pair shares {worst} elements)", flush=True)
    for mel in names:
        st = compose(mel)
        out = Path("out") / f"track_{slug(RECIPES[mel]['title'])}.wav"
        out.parent.mkdir(exist_ok=True)
        sf.write(str(out), st.astype(np.float32), SR)
        print(f"{RECIPES[mel]['title']!r} ({mel}): {out} "
              f"{len(st)/SR:.1f}s", flush=True)


if __name__ == "__main__":
    main()
