"""Shared part renderers for the album build — parameterized, no section
hardcoding. Ported from hymn01's proven voices; every part takes its
pattern/kit/patch as data so eight tracks can use eight asset sets.

Melody-first law lives in album_build.py: these just render parts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soundgen"))
import synth as sy                      # noqa: E402
import gordon_chain as gc               # noqa: E402
import voices                           # noqa: E402
import surge_bank                       # noqa: E402

SR = sy.SR


def place(out: np.ndarray, x: np.ndarray, t_s: float, gain: float = 1.0):
    i = int(t_s * SR)
    if i >= len(out) or i < 0:
        return
    seg = x[:len(out) - i]
    out[i:i + len(seg)] += seg * gain


def envelope(n: int, a_s: float, r_s: float, shape: float = 1.0) -> np.ndarray:
    a, r = max(1, int(a_s * SR)), max(1, int(r_s * SR))
    a, r = min(a, n // 2), min(r, n // 2)
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a) ** shape
    e[n - r:] = np.linspace(1, 0, r) ** shape
    return e


# --- rhythm section --------------------------------------------------------

def render_riff(rng, n_bars: int, bar_s: float, step_s: float, palette,
                vel_scale: float = 1.0) -> np.ndarray:
    """palette: tuple of bars, each a list of (pos16, semi, mute, vel)."""
    out = np.zeros(int(n_bars * bar_s * SR) + SR)
    for bar in range(n_bars):
        pat = palette[bar % len(palette)]
        for pos, semi, mute, vel in pat:
            t = bar * bar_s + pos * step_s + float(rng.normal(0, 0.006))
            v = vel * vel_scale * (1 + rng.normal(0, 0.05))
            h = voices.chug_note(rng, semi, step_s * 1.9 * (1.6 - mute),
                                 mute, v)
            place(out, h, max(0.0, t))
    return gc.tempo_punch(out, 60.0 / (bar_s / 4), gain_reduction_db=5.0,
                          attack_s=0.02)


def render_kick(rng, n_bars: int, bar_s: float, step_s: float, pattern,
                kick_sample: np.ndarray, jitter: float = 0.05) -> np.ndarray:
    out = np.zeros(int(n_bars * bar_s * SR) + SR)
    for bar in range(n_bars):
        for pos, vel in pattern:
            v = vel * (1 + rng.normal(0, jitter))
            place(out, kick_sample * v, bar * bar_s + pos * step_s)
    return sy.highpass(out, 34)


def render_hats(rng, n_bars: int, bar_s: float, step_s: float,
                vel: float, every: int = 2) -> np.ndarray:
    n_h = int(0.06 * SR)
    t = np.arange(n_h) / SR
    cl = np.zeros(n_h)
    for f in (5173.0, 6841.0, 8929.0, 11003.0):
        cl += np.sign(np.sin(2 * np.pi * f * t))
    cl *= np.sign(np.sin(2 * np.pi * 3271.0 * t))
    hat = sy.highpass(cl / 4.0, 5500) * envelope(n_h, 0.0008, 0.045, 0.7)
    out = np.zeros(int(n_bars * bar_s * SR) + SR)
    for bar in range(n_bars):
        for pos in range(0, 16, every):
            acc = 1.0 if pos % 8 == 4 else (0.55 if pos % 4 == 0 else 0.4)
            place(out, hat * vel * acc * (1 + rng.normal(0, 0.08)),
                  bar * bar_s + pos * step_s)
    return out


def render_bass(rng, n_bars: int, bar_s: float, step_s: float,
                roots_ab=( (0, 0), (-2, 0) ), patch: str = "fm_bass"
                ) -> np.ndarray:
    """Root 8ths following a two-bar harmonic rhythm."""
    out = np.zeros(int(n_bars * bar_s * SR) + SR)
    for bar in range(n_bars):
        roots = roots_ab[bar % len(roots_ab)]
        for half, root in enumerate(roots):
            for e8 in range(4):
                v = (0.95 if e8 == 0 else 0.75) * (1 + rng.normal(0, 0.05))
                note = surge_bank.render_notes(patch, [38 + int(root)],
                                               step_s * 1.7, tail_s=0.05)
                place(out, note * v,
                      bar * bar_s + (half * 8 + e8 * 2) * step_s)
    return out


def render_wall(rng, n_bars: int, bar_s: float, step_s: float,
                roots_ab=((0, 0), (-2, 0)), buzz: bool = True) -> np.ndarray:
    out = np.zeros(int(n_bars * bar_s * SR) + SR)
    for bar in range(n_bars):
        roots = roots_ab[bar % len(roots_ab)]
        for half, root in enumerate(roots):
            for iv, g in ((0, 1.0), (7, 0.8), (12, 0.55)):
                h = voices.chug_note(rng, root + iv, 8 * step_s * 1.05,
                                     mute=0.0, vel=g * (1 + rng.normal(0, 0.04)))
                place(out, h, bar * bar_s + half * 8 * step_s)
    out = gc.tempo_punch(out, 60.0 / (bar_s / 4), gain_reduction_db=5.0,
                         attack_s=0.02)
    out = sy.highpass(out, 120)
    if buzz:
        bz = surge_bank.render_notes("buzzsaw_wall", [38, 45],
                                     min(8.0, n_bars * bar_s), tail_s=0.1)
        reps = int(np.ceil(len(out) / len(bz)))
        bz = np.tile(bz, reps)[:len(out)]
        grind = sy.highpass(sy.lowpass(bz, 4500), 2000)
        out = out + 0.5 * (bz - 0.8 * grind)
    return out


# --- sacred voices -----------------------------------------------------------

def render_chant(rng, events, step_s: float, register_semi: float,
                 breath: float = 0.2, phrase_gain: bool = True) -> np.ndarray:
    total = sum(d for _, d in events)
    out = np.zeros(int(total * step_s * SR) + SR)
    semis = [s for s, _ in events if s is not None]
    if not semis:
        return out
    apex, lo = max(semis), min(semis)
    t = 0
    for s, d in events:
        if s is not None:
            g = 1.0
            if phrase_gain and apex > lo:
                g = 0.72 + 0.28 * ((s - lo) / (apex - lo))
            g *= 1.0 + rng.normal(0.0, 0.04)
            note = voices.machine_voice(register_semi + s, d * step_s * 1.04,
                                        breath=breath, vel=g,
                                        drift=float(rng.normal(0, 0.06)))
            place(out, note, t * step_s)
        t += d
    return out


def render_organum(rng, events, step_s: float, register_semi: float
                   ) -> np.ndarray:
    a = render_chant(rng, events, step_s, register_semi)
    b = render_chant(rng, events, step_s, register_semi - 7) * 0.58
    c = render_chant(rng, events, step_s, register_semi + 12) * 0.42
    n = max(len(a), len(b), len(c))
    out = np.zeros(n)
    for v in (a, b, c):
        out[:len(v)] += v
    return sy.highpass(out, 80)


def render_lead(rng, events, step_s: float, register_semi: float,
                patch: str = "lead_saw") -> np.ndarray:
    y = surge_bank.render_phrase(
        patch, events, step_s, base_midi=50 + int(register_semi),
        rng=np.random.default_rng(int(rng.integers(1 << 31))))
    return sy.highpass(y, 150)


def bell_hit(vel: float = 1.0) -> np.ndarray:
    raw = voices._mono(voices.SCRATCH / "freesound/bell.wav")[0]
    from scipy.signal import resample_poly
    from fractions import Fraction
    fr = Fraction(2.0 ** (1.7 / 12.0)).limit_denominator(200)
    return resample_poly(raw, fr.numerator, fr.denominator) * vel


def shepard_riser(dur_s: float, cycle_s: float) -> np.ndarray:
    n = int(dur_s * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    layers = 6
    for k in range(layers):
        pos = (t / cycle_s + k) % layers
        f = 55.0 * 2.0 ** pos
        phase = np.cumsum(2 * np.pi * f / SR)
        w = 0.5 - 0.5 * np.cos(2 * np.pi * pos / layers)
        out += np.sin(phase) * w
    return sy.lowpass(gc._tube(out / layers, drive=1.4), 5200)


def hum_bed(dur_s: float, vel: float = 1.0) -> np.ndarray:
    src = voices.machine_voice(0.0, min(dur_s, 12.0), breath=1.2, vel=0.4)
    reps = int(np.ceil(dur_s * SR / len(src)))
    x = np.tile(src, reps)[:int(dur_s * SR)]
    y = gc.feedback_loop(x * 0.5, delay_s=1.0 / 73.42, feedback_gain=1.05,
                         drive=1.0, input_gain=1.2, howl_hz=146.83,
                         howl_q=3.0)
    return y[:int(dur_s * SR)] * vel
