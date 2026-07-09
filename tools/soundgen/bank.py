"""tools/soundgen/bank.py

Generates the full PERIHELION SFX bank into game/assets/sfx/*.wav using the
numpy DSP toolkit in synth.py. Every sound has a one-line SPEC string
(intent description) used later for AI verification (see verify_bank.py).

Synthesis approach (round-2 rebuild after Gemini judging): every percussive
sound is layered -- hot broadband transient, pitched sine thump for low-end
weight, swept-bandpass noise body, comb-delayed room tail -- summed, tanh
soft-clipped for grit, and ALWAYS enveloped to true zero (never truncated
mid-energy).

Run:
    uv run python tools/soundgen/bank.py [comma,separated,names]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth as sy  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SFX_DIR = REPO_ROOT / "game" / "assets" / "sfx"

SR = sy.SR


def _seed(name: str) -> int:
    return int.from_bytes(name.encode()[:4].ljust(4, b"\0"), "little") & 0x7FFFFFFF


# ==========================================================================
# shared sound-design building blocks
# ==========================================================================

def finish(x: np.ndarray, fade_s: float = 0.015, pad_s: float = 0.05) -> np.ndarray:
    """Guarantee a sound ends at true zero: raised-cosine fade over the last
    fade_s, then pad_s of silence. Kills the 'abrupt clicky cutoff' tell."""
    x = np.asarray(x, dtype=np.float64).copy()
    nf = min(sy.samples(fade_s), len(x))
    if nf > 1:
        w = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, nf)))
        x[-nf:] *= w
    if pad_s > 0:
        x = np.pad(x, (0, sy.samples(pad_s)))
    return x.astype(np.float32)


def place(total_s: float, *events) -> np.ndarray:
    """Mix (t0_seconds, array, gain) events onto a silent timeline."""
    n_total = sy.samples(total_s)
    out = np.zeros(n_total, dtype=np.float64)
    for t0, arr, gain in events:
        a = np.asarray(arr, dtype=np.float64) * gain
        start = sy.samples(t0) if t0 > 0 else 0
        if start >= n_total:
            continue
        end = min(n_total, start + len(a))
        out[start:end] += a[: end - start]
    return out.astype(np.float32)


def hot_transient(dur_s: float = 0.008, seed=None, gain: float = 1.2) -> np.ndarray:
    """0-8ms full-band white-noise click, very hot."""
    n = sy.white_noise(dur_s, seed=seed)
    env = sy.env_exp_decay(dur_s, tau=dur_s / 3.0, start=1.0, end=0.001)
    return (sy.apply_env(n, env).astype(np.float64) * gain).astype(np.float32)


def gun_thump(f0: float = 160.0, f1: float = 55.0, pitch_s: float = 0.03,
              dur_s: float = 0.15, drive: float = 2.0) -> np.ndarray:
    """Sine with exponential pitch drop f0->f1 over pitch_s, then hold f1;
    exponential amplitude decay over dur_s. This is the low-end 'weight'."""
    n = sy.samples(dur_s)
    npitch = min(sy.samples(pitch_s), n)
    freqs = np.empty(n, dtype=np.float64)
    tt = np.linspace(0.0, 1.0, npitch)
    freqs[:npitch] = f0 * (f1 / f0) ** tt
    freqs[npitch:] = f1
    tone = sy.sine(freqs, dur_s)
    env = sy.env_exp_decay(dur_s, tau=dur_s / 4.5, start=1.0, end=0.001)
    x = sy.apply_env(tone, env)
    return sy.soft_clip(x, drive)


def gun_body(dur_s: float, f_hi: float = 2000.0, f_lo: float = 300.0,
             brown_mix: float = 0.5, seed=None) -> np.ndarray:
    """Brown+white noise through a bandpass whose center sweeps f_hi->f_lo,
    exponential decay."""
    w = sy.white_noise(dur_s, seed=seed).astype(np.float64)
    b = sy.brown_noise(dur_s, seed=(seed or 0) + 1).astype(np.float64)
    noise = (brown_mix * b + (1.0 - brown_mix) * w).astype(np.float32)
    sweep = sy.pitch_env(dur_s, f_hi, f_lo)
    x = sy.bandpass(noise, sweep, q=0.9)
    env = sy.env_exp_decay(dur_s, tau=dur_s / 3.5, start=1.0, end=0.002)
    return sy.apply_env(x, env)


def gun_tail(dur_s: float = 0.25, lp_hz: float = 800.0, seed=None) -> np.ndarray:
    """Lowpassed noise room tail with parallel comb delays (13/17/23 ms)."""
    n = sy.white_noise(dur_s, seed=seed)
    n = sy.lowpass(n, lp_hz)
    combs = [sy.comb_filter(n, d, feedback=0.35) for d in (0.013, 0.017, 0.023)]
    x = sy.mix_layers(combs, [1.0 / len(combs)] * len(combs))
    env = sy.env_exp_decay(dur_s, tau=dur_s / 3.0, start=1.0, end=0.001)
    return sy.apply_env(x, env)


def gunshot(total_s: float, seed: int,
            thump_kw: dict, body_kw: dict, tail_kw: dict,
            transient_gain: float = 1.2, thump_gain: float = 0.95,
            body_gain: float = 0.7, tail_gain: float = 0.25,
            drive: float = 2.5, double_thump_at: float | None = None,
            prepend: np.ndarray | None = None) -> np.ndarray:
    """Layered gunshot: transient + pitched thump + swept noise body +
    comb-delayed tail -> tanh -> enveloped to zero."""
    events = [
        (0.0, hot_transient(seed=seed), transient_gain),
        (0.002, gun_thump(**thump_kw), thump_gain),
        (0.0, gun_body(seed=seed + 2, **body_kw), body_gain),
        (0.012, gun_tail(seed=seed + 3, **tail_kw), tail_gain),
    ]
    if double_thump_at is not None:
        events.append((double_thump_at, gun_thump(**thump_kw), thump_gain * 0.8))
    x = place(total_s, *events)
    x = sy.soft_clip(x, drive)
    if prepend is not None:
        x = sy.concat(prepend, x)
    return finish(x)


def squelch_grains(total_s: float, n_grains: int, f_lo: float, f_hi: float,
                   grain_s: float = 0.005, spread: float = 0.6, seed=None,
                   gain: float = 0.6) -> np.ndarray:
    """Random short grains of bandpassed noise -- the 'wet' texture."""
    rng = np.random.default_rng(seed)
    events = []
    for _ in range(n_grains):
        t0 = rng.uniform(0.0, total_s * spread)
        g = sy.white_noise(grain_s, seed=int(rng.integers(0, 1 << 30)))
        g = sy.bandpass(g, rng.uniform(f_lo, f_hi), q=2.0)
        g = sy.apply_env(g, sy.env_exp_decay(grain_s, tau=grain_s / 3.0))
        events.append((t0, g, gain * rng.uniform(0.6, 1.0)))
    return place(total_s, *events)


def wet_impact(dur_s: float = 0.14, thump_f0: float = 180.0, thump_f1: float = 70.0,
               n_grains: int = 4, grain_lo: float = 900.0, grain_hi: float = 1600.0,
               body_lp: float = 600.0, drive: float = 1.8, seed=None) -> np.ndarray:
    """Wet impact: lowpassed brown-noise body + sine thump + squelch grains.
    No reverb tail; envelope runs to true zero."""
    body = sy.brown_noise(dur_s * 0.85, seed=seed)
    body = sy.lowpass(body, body_lp)
    body = sy.apply_env(body, sy.env_exp_decay(dur_s * 0.85, tau=dur_s / 4.0, end=0.001))
    th = gun_thump(f0=thump_f0, f1=thump_f1, pitch_s=0.02, dur_s=dur_s * 0.9, drive=1.5)
    grains = squelch_grains(dur_s, n_grains, grain_lo, grain_hi, seed=(seed or 0) + 7)
    x = place(dur_s,
              (0.0, hot_transient(0.005, seed=(seed or 0) + 3, gain=0.7), 1.0),
              (0.0, body, 0.9),
              (0.001, th, 0.9),
              (0.0, grains, 0.8))
    x = sy.soft_clip(x, drive)
    return finish(x, fade_s=0.02, pad_s=0.04)


def metal_clank(base_hz: float = 700.0, decay_s: float = 0.3,
                ratios=(1.0, 1.59, 2.66), detune_cents: float = 9.0,
                strike: bool = True, lp_hz: float = 4500.0, seed=None) -> np.ndarray:
    """Metal ring: detuned exponentially-decaying sines at inharmonic ratios
    plus a strike-noise transient, soft-clipped and darkened. Reads as struck
    metal, not a UI beep."""
    rng = np.random.default_rng(seed)
    dur = decay_s * 1.3
    layers, gains = [], []
    for i, r in enumerate(ratios):
        det = 2.0 ** (rng.uniform(-detune_cents, detune_cents) / 1200.0)
        f = base_hz * r * det
        tone = sy.sine(f, dur, phase0=rng.uniform(0, 2 * np.pi))
        # pair each partial with a slightly detuned twin for beating
        twin = sy.sine(f * 2.0 ** (rng.uniform(4, 12) / 1200.0), dur,
                       phase0=rng.uniform(0, 2 * np.pi))
        env = sy.env_exp_decay(dur, tau=decay_s / (1.6 + i * 0.9), end=0.001)
        layers.append(sy.apply_env(sy.mix_layers([tone, twin], [0.6, 0.4]), env))
        gains.append(0.8 / (1.0 + i * 0.6))
    x = sy.mix_layers(layers, gains)
    if strike:
        st = sy.white_noise(0.008, seed=(seed or 0) + 5)
        st = sy.highpass(st, 900)
        st = sy.apply_env(st, sy.env_exp_decay(0.008, tau=0.002))
        x = place(dur, (0.0, x, 1.0), (0.0, st, 0.8))
    x = sy.soft_clip(x, 1.5)
    x = sy.lowpass(x, lp_hz)
    return x


def mech_clack(base_hz: float = 700.0, seed=None, thud_hz: float = 75.0,
               ring_decay: float = 0.15, scrape: bool = True) -> np.ndarray:
    """One mechanical event: low sine thud + inharmonic metal ring + noise scrape."""
    dur = ring_decay * 1.4 + 0.05
    thud = gun_thump(f0=thud_hz * 1.8, f1=thud_hz, pitch_s=0.012, dur_s=0.06, drive=1.8)
    ring = metal_clank(base_hz, ring_decay, seed=seed)
    events = [(0.0, thud, 0.9), (0.0, ring, 0.6)]
    if scrape:
        sc = sy.white_noise(0.04, seed=(seed or 0) + 11)
        sc = sy.bandpass(sc, 2000, q=1.0)
        sc = sy.apply_env(sc, sy.env_adsr(0.04, 0.008, 0.01, 0.5, 0.02))
        events.append((0.004, sc, 0.35))
    x = place(dur, *events)
    return sy.soft_clip(x, 1.6)


def creature_voice(dur_s: float, pitch_pts, vib_hz: float = 5.0,
                   vib_depth_end: float = 0.08, formant1=(800.0, 1000.0),
                   formant2=(2400.0, 2800.0), drive: float = 4.0,
                   breath: float = 0.3, seed=None) -> np.ndarray:
    """Organic voice: saw carrier w/ pitch contour + deepening vibrato ->
    heavy tanh -> two sweeping formant bandpasses + breath-noise layer."""
    n = sy.samples(dur_s)
    tt = np.linspace(0.0, 1.0, n)
    times = np.linspace(0.0, 1.0, len(pitch_pts))
    freq = np.interp(tt, times, np.asarray(pitch_pts, dtype=np.float64))
    depth = vib_depth_end * tt  # vibrato deepens over time
    vib = sy.sine(vib_hz, dur_s).astype(np.float64)
    freq_mod = freq * (1.0 + depth * vib)
    carrier = sy.saw(freq_mod, dur_s)
    voiced = sy.soft_clip(carrier, drive)
    f1_arr = sy.pitch_env(dur_s, formant1[0], formant1[1])
    f2_arr = sy.pitch_env(dur_s, formant2[0], formant2[1])
    v1 = sy.bandpass(voiced, f1_arr, q=1.8)
    v2 = sy.bandpass(voiced, f2_arr, q=2.2)
    br = sy.white_noise(dur_s, seed=seed)
    br = sy.bandpass(br, f2_arr, q=1.2)
    return sy.mix_layers([v1, v2, br], [0.85, 0.5, breath])


def telegraph_gate(dur_s: float, rate_hz: float = 300.0, floor: float = 0.35,
                   seed=None) -> np.ndarray:
    """Random on/off gating signal -- radio squelch / chaotic arc dynamics."""
    g = sy.white_noise(dur_s, seed=seed).astype(np.float64)
    g = sy.one_pole_lowpass(g.astype(np.float32), rate_hz).astype(np.float64)
    return (floor + (1.0 - floor) * (g > 0.0)).astype(np.float64)


# ==========================================================================
# weapon sounds
# ==========================================================================

def gen_pistol_fire() -> np.ndarray:
    seed = _seed("pistol")
    return gunshot(
        0.26, seed,
        thump_kw=dict(f0=160, f1=55, pitch_s=0.03, dur_s=0.11, drive=2.0),
        body_kw=dict(dur_s=0.1, f_hi=2000, f_lo=300, brown_mix=0.45),
        tail_kw=dict(dur_s=0.2, lp_hz=800),
        drive=2.6,
    )


def gen_smg_fire() -> np.ndarray:
    seed = _seed("smg")
    x = gunshot(
        0.17, seed,
        thump_kw=dict(f0=170, f1=62, pitch_s=0.02, dur_s=0.07, drive=2.2),
        body_kw=dict(dur_s=0.06, f_hi=2300, f_lo=350, brown_mix=0.35),
        tail_kw=dict(dur_s=0.12, lp_hz=900),
        tail_gain=0.2, drive=3.0,
    )
    return sy.soft_clip(sy.bitcrush(x, bits=10), 1.1)


def gen_shotgun_fire() -> np.ndarray:
    seed = _seed("shotgun")
    return gunshot(
        0.52, seed,
        thump_kw=dict(f0=150, f1=48, pitch_s=0.035, dur_s=0.18, drive=2.2),
        body_kw=dict(dur_s=0.25, f_hi=1800, f_lo=250, brown_mix=0.7),
        tail_kw=dict(dur_s=0.38, lp_hz=700),
        body_gain=0.9, tail_gain=0.3, drive=2.8,
        double_thump_at=0.03,
    )


def gen_rail_fire() -> np.ndarray:
    seed = _seed("rail")
    # 80ms rising zap: saw 200->3k through a resonant bandpass
    zap_dur = 0.08
    zsweep = sy.pitch_env(zap_dur, 200, 3000)
    zap = sy.saw(zsweep, zap_dur)
    zap = sy.bandpass(zap, zsweep, q=6.0)
    zap = sy.apply_env(zap, sy.env_adsr(zap_dur, 0.01, 0.0, 1.0, 0.015))
    zap = sy.soft_clip(zap, 2.0) * 0.7
    return gunshot(
        0.42, seed,
        thump_kw=dict(f0=140, f1=42, pitch_s=0.035, dur_s=0.2, drive=2.2),
        body_kw=dict(dur_s=0.16, f_hi=2600, f_lo=280, brown_mix=0.5),
        tail_kw=dict(dur_s=0.28, lp_hz=750),
        drive=2.6, prepend=zap,
    )


def gen_lightning_fire() -> np.ndarray:
    seed = _seed("lightning")
    rng = np.random.default_rng(seed)
    dur = 0.62
    # dense micro-crackles, density decaying over time
    crackle_events = []
    for _ in range(36):
        t0 = dur * 0.85 * (rng.uniform(0, 1) ** 1.7)
        cdur = rng.uniform(0.004, 0.018)
        c = sy.white_noise(cdur, seed=int(rng.integers(0, 1 << 30)))
        c = sy.bandpass(c, rng.uniform(1500, 7000), q=rng.uniform(1.5, 4.0))
        c = sy.apply_env(c, sy.env_exp_decay(cdur, tau=cdur / 3.0))
        c = sy.soft_clip(c, 3.5)
        crackle_events.append((t0, c, rng.uniform(0.4, 1.0)))
    crackles = place(dur, *crackle_events)
    # continuous chaotic arc: resonant noise gated by random telegraph signal
    arc = sy.white_noise(dur, seed=seed + 1)
    walk = np.cumsum(rng.standard_normal(sy.samples(dur))) * 2.0
    walk = 900.0 + 700.0 * np.sin(walk / 400.0) + sy.pitch_env(dur, 300, 2500)
    arc = sy.bandpass(arc, np.clip(walk, 200, 6000), q=5.0)
    arc = (arc.astype(np.float64) * telegraph_gate(dur, 250, 0.25, seed=seed + 2)).astype(np.float32)
    arc = sy.apply_env(arc, sy.env_adsr(dur, 0.01, 0.1, 0.7, dur * 0.35))
    arc = sy.soft_clip(arc, 2.5)
    # sub-bass dread: pitched sub drop + brown rumble
    sub = gun_thump(f0=90, f1=48, pitch_s=0.05, dur_s=dur * 0.9, drive=1.8)
    rumble = sy.brown_noise(dur, seed=seed + 3)
    rumble = sy.lowpass(rumble, 140)
    rumble = sy.apply_env(rumble, sy.env_exp_decay(dur, tau=dur / 3.0, end=0.002))
    x = place(dur,
              (0.0, hot_transient(seed=seed + 4), 1.0),
              (0.0, crackles, 0.85),
              (0.0, arc, 0.6),
              (0.002, sub, 0.85),
              (0.0, rumble, 0.6))
    x = sy.soft_clip(x, 2.2)
    return finish(x, fade_s=0.03)


def gen_dry_click() -> np.ndarray:
    seed = _seed("dryclick")
    # hammer fall on empty chamber: thud + damped metal tick + slide
    thud = gun_thump(f0=130, f1=70, pitch_s=0.008, dur_s=0.035, drive=1.8)
    tick = metal_clank(1400, 0.035, ratios=(1.0, 1.71, 2.9), seed=seed, lp_hz=5000)
    slide = sy.white_noise(0.02, seed=seed + 2)
    slide = sy.bandpass(slide, 2400, q=1.0)
    slide = sy.apply_env(slide, sy.env_exp_decay(0.02, tau=0.006))
    x = place(0.09,
              (0.0, hot_transient(0.004, seed=seed + 1, gain=0.8), 0.9),
              (0.0, thud, 0.85),
              (0.001, tick, 0.5),
              (0.02, slide, 0.3))
    x = sy.soft_clip(x, 1.8)
    return finish(x, fade_s=0.012, pad_s=0.03)


def gen_reload() -> np.ndarray:
    seed = _seed("reload")
    clack1 = mech_clack(680, seed=seed, thud_hz=78, ring_decay=0.12)
    clack2 = mech_clack(590, seed=seed + 9, thud_hz=70, ring_decay=0.15)
    x = place(0.42, (0.0, clack1, 0.9), (0.18, clack2, 1.0))
    return finish(x, fade_s=0.03)


def gen_knife_swing() -> np.ndarray:
    seed = _seed("knifeswing")
    dur = 0.16
    n = sy.pink_noise(dur, seed=seed)
    sweep = sy.concat(sy.pitch_env(dur * 0.45, 380, 1900),
                      sy.pitch_env(dur * 0.55, 1900, 600))
    x = sy.bandpass(n, sweep[: sy.samples(dur)], q=1.1)
    body = sy.brown_noise(dur, seed=seed + 1)
    body = sy.lowpass(body, 500)
    hump = sy.env_adsr(dur, attack=0.05, decay=0.04, sustain_level=0.6, release=0.06)
    x = sy.mix_layers([sy.apply_env(x, hump), sy.apply_env(body, hump)], [0.9, 0.45])
    x = sy.soft_clip(x, 1.5)
    return finish(x, fade_s=0.03, pad_s=0.03)


def gen_knife_hit() -> np.ndarray:
    seed = _seed("knifehit")
    return wet_impact(dur_s=0.13, thump_f0=180, thump_f1=68, n_grains=4,
                      grain_lo=900, grain_hi=1600, body_lp=650, drive=2.0, seed=seed)


def gen_hit_flesh() -> np.ndarray:
    seed = _seed("hitflesh")
    return wet_impact(dur_s=0.12, thump_f0=170, thump_f1=72, n_grains=5,
                      grain_lo=800, grain_hi=1500, body_lp=600, drive=1.9, seed=seed)


def gen_hit_wall() -> np.ndarray:
    seed = _seed("hitwall")
    dur = 0.09
    dust = sy.brown_noise(dur, seed=seed)
    dust = sy.lowpass(dust, 900)
    dust = sy.apply_env(dust, sy.env_exp_decay(dur, tau=dur / 4.0, end=0.001))
    th = gun_thump(f0=140, f1=65, pitch_s=0.01, dur_s=0.045, drive=1.6)
    grit = squelch_grains(dur, 3, 1800, 3500, grain_s=0.003, spread=0.4,
                          seed=seed + 3, gain=0.3)
    x = place(dur,
              (0.0, hot_transient(0.004, seed=seed + 1, gain=0.7), 0.8),
              (0.0, dust, 1.0),
              (0.0, th, 0.75),
              (0.005, grit, 1.0))
    x = sy.soft_clip(x, 1.9)
    return finish(x, fade_s=0.015, pad_s=0.03)


def gen_ricochet() -> np.ndarray:
    seed = _seed("ricochet")
    dur = 0.3
    # impact clank then descending resonant whine
    clank = metal_clank(1100, 0.06, ratios=(1.0, 1.51, 2.32), seed=seed)
    wsweep = sy.pitch_env(dur * 0.85, 3400, 850)
    whine = sy.white_noise(dur * 0.85, seed=seed + 2)
    whine = sy.bandpass(whine, wsweep, q=9.0)
    whine = sy.apply_env(whine, sy.env_exp_decay(dur * 0.85, tau=dur / 3.2, end=0.001))
    th = gun_thump(f0=150, f1=80, pitch_s=0.01, dur_s=0.04, drive=1.5)
    x = place(dur,
              (0.0, hot_transient(0.004, seed=seed + 1, gain=0.8), 0.8),
              (0.0, th, 0.5),
              (0.0, clank, 0.7),
              (0.015, whine, 0.8))
    x = sy.soft_clip(x, 1.7)
    return finish(x, fade_s=0.03)


# ==========================================================================
# enemy sounds
# ==========================================================================

def gen_enemy_die_husk() -> np.ndarray:
    seed = _seed("diehusk")
    dur = 0.5
    # groan pitched down ~30% vs the alert voice
    voice = creature_voice(dur, [66, 58, 42], vib_hz=3.8, vib_depth_end=0.1,
                           formant1=(500, 320), formant2=(1500, 900),
                           drive=4.5, breath=0.35, seed=seed)
    genv = sy.env_adsr(dur, attack=0.02, decay=0.15, sustain_level=0.6, release=0.22)
    voice = sy.apply_env(voice, genv)
    impact = wet_impact(dur_s=0.16, thump_f0=160, thump_f1=60, n_grains=5,
                        grain_lo=700, grain_hi=1400, seed=seed + 3)
    collapse = sy.brown_noise(dur * 0.7, seed=seed + 4)
    collapse = sy.lowpass(collapse, 450)
    collapse = sy.apply_env(collapse, sy.env_exp_decay(dur * 0.7, tau=dur / 3.5, end=0.001))
    x = place(dur, (0.0, voice, 0.8), (0.05, impact, 0.9), (0.08, collapse, 0.5))
    x = sy.soft_clip(x, 1.8)
    return finish(x, fade_s=0.04)


def gen_enemy_die_mite() -> np.ndarray:
    seed = _seed("diemite")
    x = wet_impact(dur_s=0.13, thump_f0=320, thump_f1=110, n_grains=7,
                   grain_lo=700, grain_hi=2100, body_lp=900, drive=2.2, seed=seed)
    # tiny pitch-down chirp remnant, distorted (dying chitter)
    chirp = sy.saw(sy.pitch_env(0.05, 2600, 700), 0.05)
    chirp = sy.soft_clip(chirp, 3.0)
    chirp = sy.bandpass(chirp, 1800, q=1.5)
    chirp = sy.apply_env(chirp, sy.env_exp_decay(0.05, tau=0.015))
    x = place(len(x) / SR, (0.0, x, 1.0), (0.01, chirp, 0.25))
    return finish(x, fade_s=0.02, pad_s=0.02)


def gen_enemy_die_brute() -> np.ndarray:
    seed = _seed("diebrute")
    dur = 0.75
    sub = gun_thump(f0=95, f1=30, pitch_s=0.05, dur_s=0.4, drive=2.0)
    sub2 = gun_thump(f0=70, f1=26, pitch_s=0.04, dur_s=0.3, drive=1.8)
    fall = sy.brown_noise(0.45, seed=seed)
    fall = sy.lowpass(fall, 380)
    fall = sy.apply_env(fall, sy.env_exp_decay(0.45, tau=0.14, end=0.001))
    wet = wet_impact(dur_s=0.2, thump_f0=140, thump_f1=50, n_grains=6,
                     grain_lo=600, grain_hi=1300, drive=1.8, seed=seed + 5)
    settle = sy.brown_noise(0.25, seed=seed + 6)
    settle = sy.lowpass(settle, 300)
    settle = sy.apply_env(settle, sy.env_exp_decay(0.25, tau=0.07, end=0.001))
    tail = gun_tail(0.3, lp_hz=500, seed=seed + 7)
    x = place(dur,
              (0.0, hot_transient(0.006, seed=seed + 1), 0.9),
              (0.0, sub, 1.0),
              (0.0, fall, 0.7),
              (0.02, wet, 0.9),
              (0.18, sub2, 0.7),
              (0.2, settle, 0.5),
              (0.03, tail, 0.3))
    x = sy.soft_clip(x, 2.0)
    return finish(x, fade_s=0.05)


def gen_enemy_alert_husk() -> np.ndarray:
    seed = _seed("alerthusk")
    dur = 0.48
    # raspy inhale: rising breath noise through rising formants
    inhale_dur = 0.22
    br = sy.white_noise(inhale_dur, seed=seed)
    fsweep = sy.pitch_env(inhale_dur, 500, 1600)
    br = sy.bandpass(br, fsweep, q=2.5)
    br = sy.apply_env(br, sy.env_adsr(inhale_dur, attack=inhale_dur * 0.7,
                                      decay=inhale_dur * 0.1, sustain_level=0.8,
                                      release=inhale_dur * 0.2))
    br = sy.soft_clip(br, 2.0)
    voice = creature_voice(dur - 0.18, [95, 88, 62], vib_hz=3.4, vib_depth_end=0.09,
                           formant1=(600, 380), formant2=(1700, 1100),
                           drive=4.0, breath=0.4, seed=seed + 1)
    voice = sy.apply_env(voice, sy.env_adsr(dur - 0.18, attack=0.05, decay=0.08,
                                            sustain_level=0.65, release=0.12))
    x = place(dur, (0.0, br, 0.6), (0.16, voice, 0.85))
    x = sy.soft_clip(x, 1.6)
    return finish(x, fade_s=0.04)


def gen_enemy_alert_mite() -> np.ndarray:
    seed = _seed("alertmite")
    rng = np.random.default_rng(seed)
    dur = 0.24
    events = []
    # irregular gallop of organic clicks: noise grain + tiny damped resonance
    t = 0.005
    while t < dur - 0.02:
        cdur = rng.uniform(0.004, 0.009)
        grain = sy.white_noise(cdur, seed=int(rng.integers(0, 1 << 30)))
        grain = sy.bandpass(grain, rng.uniform(2200, 4800), q=2.0)
        grain = sy.apply_env(grain, sy.env_exp_decay(cdur, tau=cdur / 3.0))
        res = sy.sine(rng.uniform(1000, 1400), 0.012)
        res = sy.apply_env(res, sy.env_exp_decay(0.012, tau=0.003))
        events.append((t, grain, rng.uniform(0.5, 1.0)))
        events.append((t + 0.001, res, rng.uniform(0.1, 0.25)))
        t += rng.uniform(0.014, 0.035)
    # faint breathy body under the clicks
    bed = sy.white_noise(dur, seed=seed + 1)
    bed = sy.bandpass(bed, 3000, q=0.8)
    bed = sy.apply_env(bed, sy.env_adsr(dur, 0.03, 0.05, 0.4, 0.08))
    events.append((0.0, bed, 0.15))
    x = place(dur, *events)
    x = sy.soft_clip(x, 1.8)
    return finish(x, fade_s=0.02, pad_s=0.03)


def gen_spitter_shoot() -> np.ndarray:
    seed = _seed("spitter")
    dur = 0.22
    # wet gurgle: brown noise amplitude-modulated by a slow random LFO
    gurgle = sy.brown_noise(dur, seed=seed)
    gurgle = sy.lowpass(gurgle, 800)
    lfo = sy.one_pole_lowpass(sy.white_noise(dur, seed=seed + 1), 45).astype(np.float64)
    lfo = 0.5 + 0.5 * lfo / (np.max(np.abs(lfo)) + 1e-9)
    gurgle = (gurgle.astype(np.float64) * lfo).astype(np.float32)
    gurgle = sy.apply_env(gurgle, sy.env_adsr(dur, 0.01, 0.06, 0.5, 0.1))
    # bloop: pitched-down sine, wet
    bloop = gun_thump(f0=420, f1=110, pitch_s=0.07, dur_s=0.13, drive=1.8)
    grains = squelch_grains(dur, 6, 600, 1600, grain_s=0.006, spread=0.7,
                            seed=seed + 2, gain=0.7)
    x = place(dur,
              (0.0, hot_transient(0.004, seed=seed + 3, gain=0.5), 0.6),
              (0.0, gurgle, 0.9),
              (0.005, bloop, 0.75),
              (0.0, grains, 0.9))
    x = sy.soft_clip(x, 2.0)
    return finish(x, fade_s=0.025, pad_s=0.03)


def gen_shrieker_scream() -> np.ndarray:
    seed = _seed("shrieker")
    dur = 0.78
    voice = creature_voice(dur, [600, 1100, 1400, 1150, 900],
                           vib_hz=5.2, vib_depth_end=0.09,
                           formant1=(800, 1150), formant2=(2400, 3100),
                           drive=5.0, breath=0.45, seed=seed)
    # sub-growl underlay for weight
    growl = sy.saw(sy.pitch_env(dur, 140, 90), dur)
    growl = sy.soft_clip(growl, 4.0)
    growl = sy.lowpass(growl, 500)
    env = sy.env_adsr(dur, attack=0.04, decay=0.1, sustain_level=0.85, release=0.28)
    tremolo = (1.0 + 0.18 * sy.sine(13.0, dur).astype(np.float64)).astype(np.float32)
    x = sy.mix_layers([voice, growl], [0.9, 0.5])
    x = sy.apply_env(x, (env.astype(np.float64) * tremolo.astype(np.float64)).astype(np.float32))
    x = sy.soft_clip(x, 2.0)
    x = sy.bitcrush(x, bits=10)
    x = sy.highpass(x, 180)
    return finish(x, fade_s=0.06)


# ==========================================================================
# player sounds
# ==========================================================================

def gen_player_hurt() -> np.ndarray:
    seed = _seed("playerhurt")
    dur = 0.17
    imp = wet_impact(dur_s=0.12, thump_f0=175, thump_f1=62, n_grains=3,
                     grain_lo=700, grain_hi=1200, body_lp=700, drive=1.8, seed=seed)
    # dark high sting: detuned sine pair, distorted, fast decay
    sting = sy.mix_layers([sy.sine(2100, 0.08), sy.sine(2180, 0.08)], [0.6, 0.5])
    sting = sy.soft_clip(sting, 2.5)
    sting = sy.apply_env(sting, sy.env_exp_decay(0.08, tau=0.02, end=0.001))
    sting = sy.bandpass(sting, 2200, q=1.2)
    x = place(dur, (0.0, imp, 1.0), (0.005, sting, 0.35))
    x = sy.soft_clip(x, 1.4)
    return finish(x, fade_s=0.02, pad_s=0.03)


def gen_player_die() -> np.ndarray:
    seed = _seed("playerdie")
    dur = 1.35
    voice = creature_voice(0.9, [130, 95, 55, 42], vib_hz=3.0, vib_depth_end=0.07,
                           formant1=(550, 300), formant2=(1500, 800),
                           drive=3.5, breath=0.3, seed=seed)
    voice = sy.apply_env(voice, sy.env_adsr(0.9, attack=0.03, decay=0.3,
                                            sustain_level=0.55, release=0.4))
    body_fall = wet_impact(dur_s=0.2, thump_f0=150, thump_f1=48, n_grains=4,
                           grain_lo=500, grain_hi=1100, drive=1.7, seed=seed + 2)
    second = wet_impact(dur_s=0.14, thump_f0=120, thump_f1=45, n_grains=3,
                        grain_lo=400, grain_hi=900, drive=1.6, seed=seed + 3)
    # fading dark ring -- ears ringing as the screen dies
    ring = metal_clank(480, 0.7, ratios=(1.0, 1.5, 2.76), seed=seed + 4, strike=False)
    x = place(dur,
              (0.0, voice, 0.85),
              (0.3, body_fall, 0.8),
              (0.55, second, 0.55),
              (0.45, ring, 0.22))
    x = sy.soft_clip(x, 1.7)
    x = sy.reverb(x, room_size=0.6, damping=0.4, mix=0.22, tail_s=0.25)
    x = sy.fade_out(x, 0.35)
    return finish(x, fade_s=0.05)


def gen_heartbeat() -> np.ndarray:
    seed = _seed("heartbeat")

    def beat(f0, f1, dur, seed_):
        th = gun_thump(f0=f0, f1=f1, pitch_s=0.03, dur_s=dur, drive=2.5)
        skin = sy.brown_noise(dur * 0.7, seed=seed_)
        skin = sy.lowpass(skin, 260)
        skin = sy.apply_env(skin, sy.env_exp_decay(dur * 0.7, tau=dur / 4.0, end=0.001))
        b = place(dur, (0.0, th, 1.0), (0.0, skin, 0.5))
        return sy.soft_clip(b, 1.8)

    lub = beat(95, 48, 0.14, seed)
    dub = beat(80, 42, 0.12, seed + 1)
    x = place(0.8, (0.0, lub, 1.0), (0.19, dub, 0.7))
    return finish(x, fade_s=0.04, pad_s=0.0)


# ==========================================================================
# pickups / UI / narrative props
# ==========================================================================

def gen_pickup_ammo() -> np.ndarray:
    seed = _seed("pickammo")
    clink1 = metal_clank(950, 0.07, ratios=(1.0, 1.63, 2.51), seed=seed)
    clink2 = metal_clank(1150, 0.09, ratios=(1.0, 1.59, 2.66), seed=seed + 1)
    slide = sy.white_noise(0.08, seed=seed + 2)
    slide = sy.bandpass(slide, sy.pitch_env(0.08, 2600, 1200), q=1.3)
    slide = sy.apply_env(slide, sy.env_adsr(0.08, 0.01, 0.02, 0.6, 0.04))
    thud = gun_thump(f0=140, f1=80, pitch_s=0.01, dur_s=0.04, drive=1.5)
    x = place(0.22,
              (0.0, thud, 0.5),
              (0.0, clink1, 0.8),
              (0.06, clink2, 0.6),
              (0.05, slide, 0.4))
    x = sy.soft_clip(x, 1.4)
    return finish(x, fade_s=0.03, pad_s=0.03)


def gen_pickup_medkit() -> np.ndarray:
    seed = _seed("pickmed")
    latch = mech_clack(520, seed=seed, thud_hz=85, ring_decay=0.06, scrape=False)
    hiss = sy.white_noise(0.16, seed=seed + 2)
    hiss = sy.highpass(hiss, 2800)
    hiss = sy.apply_env(hiss, sy.env_adsr(0.16, attack=0.02, decay=0.05,
                                          sustain_level=0.5, release=0.07))
    x = place(0.28, (0.0, latch, 0.85), (0.05, hiss, 0.3))
    return finish(x, fade_s=0.03, pad_s=0.03)


def gen_pickup_key() -> np.ndarray:
    seed = _seed("pickkey")
    # dark detuned chime: heavy beating partial pairs, darkened, dirty floor
    x = metal_clank(520, 0.22, ratios=(1.0, 1.5027, 2.44), detune_cents=14,
                    seed=seed, lp_hz=3200)
    thud = gun_thump(f0=110, f1=65, pitch_s=0.012, dur_s=0.05, drive=1.5)
    floor_ = sy.pink_noise(0.25, seed=seed + 2)
    floor_ = sy.bandpass(floor_, 900, q=0.6)
    floor_ = sy.apply_env(floor_, sy.env_exp_decay(0.25, tau=0.08, end=0.001))
    x = place(0.3, (0.0, x, 0.85), (0.0, thud, 0.4), (0.0, floor_, 0.12))
    x = sy.soft_clip(x, 1.3)
    return finish(x, fade_s=0.04, pad_s=0.02)


def gen_terminal_open() -> np.ndarray:
    seed = _seed("termopen")
    dur = 0.24
    # degauss thunk + mains hum + static crackle + faint high whine
    thunk = gun_thump(f0=130, f1=55, pitch_s=0.015, dur_s=0.06, drive=2.0)
    hum = sy.square(50.0, dur)
    hum = sy.lowpass(hum, 260)
    hum = sy.apply_env(hum, sy.env_adsr(dur, attack=0.02, decay=0.03,
                                        sustain_level=0.7, release=0.09))
    static = squelch_grains(dur, 6, 1500, 5000, grain_s=0.004, spread=0.5,
                            seed=seed + 1, gain=0.35)
    whine = sy.sine(sy.pitch_env(dur, 9000, 11500), dur)
    whine = sy.apply_env(whine, sy.env_adsr(dur, 0.04, 0.03, 0.5, 0.1))
    x = place(dur,
              (0.0, hot_transient(0.005, seed=seed + 2, gain=0.6), 0.7),
              (0.0, thunk, 0.8),
              (0.005, hum, 0.55),
              (0.0, static, 1.0),
              (0.01, whine, 0.08))
    x = sy.soft_clip(x, 1.8)
    return finish(x, fade_s=0.04, pad_s=0.02)


def gen_terminal_type() -> np.ndarray:
    seed = _seed("termtype")
    thud = gun_thump(f0=210, f1=95, pitch_s=0.006, dur_s=0.02, drive=1.8)
    case = sy.white_noise(0.018, seed=seed)
    case = sy.bandpass(case, 750, q=1.4)
    case = sy.apply_env(case, sy.env_exp_decay(0.018, tau=0.005))
    x = place(0.045,
              (0.0, hot_transient(0.003, seed=seed + 1, gain=0.8), 0.85),
              (0.0, thud, 0.7),
              (0.001, case, 0.5))
    x = sy.soft_clip(x, 1.7)
    return finish(x, fade_s=0.01, pad_s=0.02)


def gen_radio_blip() -> np.ndarray:
    seed = _seed("radioblip")
    dur = 0.17
    static = sy.white_noise(dur, seed=seed)
    static = (static.astype(np.float64) *
              telegraph_gate(dur, 500, 0.3, seed=seed + 1)).astype(np.float32)
    static = sy.bandpass(static, 1700, q=0.9)
    static = sy.apply_env(static, sy.env_adsr(dur, 0.008, 0.04, 0.55, 0.06))
    tone = sy.square(880, 0.07)
    tone = sy.soft_clip(tone, 2.0)
    tone = sy.apply_env(tone, sy.env_adsr(0.07, 0.005, 0.01, 0.7, 0.03))
    x = place(dur, (0.0, static, 0.85), (0.04, tone, 0.4))
    # radio voice-band filter + grit
    x = sy.bandpass(x, 1400, q=0.7)
    x = sy.soft_clip(x, 2.2)
    x = sy.bitcrush(x, bits=8, rate_divisor=2)
    return finish(x, fade_s=0.025, pad_s=0.02)


def gen_door_unlock() -> np.ndarray:
    seed = _seed("doorunlock")
    # servo whir: low saw sweep with buzz, then heavy clunk + settle rattle
    whir_dur = 0.16
    whir = sy.mix_layers([
        sy.saw(sy.pitch_env(whir_dur, 45, 95), whir_dur),
        sy.square(sy.pitch_env(whir_dur, 118, 240), whir_dur),
    ], [0.8, 0.3])
    whir = sy.lowpass(whir, 520)
    whir = sy.soft_clip(whir, 2.2)
    whir = sy.apply_env(whir, sy.env_adsr(whir_dur, 0.03, 0.02, 0.8, 0.03))
    clunk = sy.mix_layers([
        gun_thump(f0=95, f1=34, pitch_s=0.02, dur_s=0.16, drive=2.2),
        metal_clank(310, 0.12, ratios=(1.0, 1.43, 2.28), seed=seed),
    ], [1.0, 0.55])
    rattle = squelch_grains(0.1, 4, 800, 2000, grain_s=0.005, spread=0.8,
                            seed=seed + 3, gain=0.35)
    x = place(0.42,
              (0.0, whir, 0.6),
              (0.15, hot_transient(0.005, seed=seed + 2, gain=0.9), 0.9),
              (0.15, clunk, 1.0),
              (0.2, rattle, 0.8))
    x = sy.soft_clip(x, 1.9)
    return finish(x, fade_s=0.04)


# ==========================================================================
# ambient drones (60s, loopable)
# ==========================================================================

def _vent_bed(dur_s: float, seed: int) -> np.ndarray:
    n = sy.brown_noise(dur_s, seed=seed)
    n = sy.bandpass(n, 220, q=0.7)
    lfo = 0.5 + 0.5 * sy.sine(0.045, dur_s).astype(np.float64)
    return (n.astype(np.float64) * lfo).astype(np.float32)


def _hum_bed(dur_s: float, base=55.0) -> np.ndarray:
    # detuned pair at the fundamental for slow beating + saturated harmonics
    h1 = sy.sine(base, dur_s)
    h1b = sy.sine(base * 1.006, dur_s)
    h2 = sy.sine(base * 2.0, dur_s) * 0.4
    h3 = sy.sine(base * 3.01, dur_s) * 0.15
    hum = sy.mix_layers([h1, h1b, h2, h3], [0.7, 0.5, 1.0, 1.0])
    hum = sy.soft_clip(hum, 1.6)
    lfo = 1.0 + 0.06 * sy.sine(0.08, dur_s).astype(np.float64)
    hum = (hum.astype(np.float64) * lfo).astype(np.float32)
    return sy.lowpass(hum, 700)


def _dull_knock(seed: int) -> np.ndarray:
    """Distant dull metal knock -- lowpassed thud + heavily damped dark ring.
    Replaces the old clean 'ring' events that read as beeps."""
    th = gun_thump(f0=120, f1=60, pitch_s=0.02, dur_s=0.25, drive=1.5)
    ring = metal_clank(240, 0.35, ratios=(1.0, 1.48, 2.21), seed=seed,
                       strike=False, lp_hz=900)
    x = place(0.6, (0.0, th, 0.7), (0.0, ring, 0.5))
    x = sy.lowpass(x, 700)
    return finish(x, fade_s=0.1, pad_s=0.0)


def gen_amb_drone_early() -> np.ndarray:
    seed = _seed("ambearly")
    dur = 60.0
    hum = _hum_bed(dur, base=55.0)
    vents = _vent_bed(dur, seed)
    hiss = sy.pink_noise(dur, seed=seed + 9)
    hiss = sy.highpass(hiss, 1500)
    n_total = sy.samples(dur)
    knocks = np.zeros(n_total, dtype=np.float64)
    rng = np.random.default_rng(seed + 5)
    for _ in range(5):
        t0 = rng.uniform(3, dur - 4)
        k = _dull_knock(int(rng.integers(0, 1 << 30))).astype(np.float64)
        start = sy.samples(t0)
        end = min(n_total, start + len(k))
        knocks[start:end] += k[: end - start] * rng.uniform(0.15, 0.3)
    x = sy.mix_layers([hum, vents, hiss, knocks.astype(np.float32)],
                      [0.6, 0.55, 0.06, 1.0])
    x = sy.crossfade_loop(x, 2.5)
    return x


def groan_layer(dur_s: float, f0: float, f1: float, seed=None) -> np.ndarray:
    """Distant groan used by the mid drone: distorted saw glide, lowpassed."""
    freq = sy.pitch_env(dur_s, f0, f1)
    vib = sy.sine(2.0, dur_s).astype(np.float64)
    tone = sy.saw(freq * (1.0 + 0.08 * vib), dur_s)
    tone = sy.soft_clip(tone, 1.5)
    tone = sy.lowpass(tone, max(f0, f1) * 3.5)
    env = sy.env_adsr(dur_s, attack=dur_s * 0.2, decay=dur_s * 0.2,
                      sustain_level=0.5, release=dur_s * 0.5)
    return sy.apply_env(tone, env)


def gen_amb_drone_mid() -> np.ndarray:
    seed = _seed("ambmid")
    dur = 60.0
    base = gen_amb_drone_early()
    detune1 = sy.sine(110.0, dur)
    detune2 = sy.sine(111.6, dur)
    beat = sy.mix_layers([detune1, detune2], [0.35, 0.35])
    beat = sy.soft_clip(beat, 1.4)
    beat = sy.lowpass(beat, 500)
    n_total = sy.samples(dur)
    far_groan = np.zeros(n_total, dtype=np.float64)
    rng = np.random.default_rng(seed)
    for t0 in (rng.uniform(8, 18), rng.uniform(28, 40), rng.uniform(45, 55)):
        g = groan_layer(2.0, 90, 65, seed=int(rng.integers(0, 1 << 30)))
        g = g.astype(np.float64) * 0.15
        start = sy.samples(t0)
        end = min(n_total, start + len(g))
        far_groan[start:end] += g[: end - start]
    x = sy.mix_layers([base, beat, far_groan.astype(np.float32)], [0.8, 0.35, 1.0])
    x = sy.crossfade_loop(x, 2.5)
    return x


def gen_amb_drone_late() -> np.ndarray:
    seed = _seed("amblate")
    dur = 60.0
    n = sy.samples(dur)
    f_min, f_max = 55.0, 880.0
    n_octaves = float(np.log2(f_max / f_min))
    n_voices = 5
    wrap_period_s = 20.0
    speed_oct_per_s = n_octaves / wrap_period_s
    tt = np.arange(n, dtype=np.float64) / SR
    rng = np.random.default_rng(seed + 3)
    voices = []
    for i in range(n_voices):
        phase0 = i * n_octaves / n_voices
        pos = np.mod(phase0 - speed_oct_per_s * tt, n_octaves)
        freq = f_min * (2.0 ** pos)
        amp = np.sin(np.pi * pos / n_octaves) ** 2
        # dirty voice: slightly detuned pair, saturated
        tone = np.sin(2.0 * np.pi * np.cumsum(freq) / SR)
        tone2 = np.sin(2.0 * np.pi * np.cumsum(freq * 1.007) / SR + rng.uniform(0, 6.28))
        v = np.tanh((tone + 0.7 * tone2) * 1.4)
        voices.append((v * amp).astype(np.float32))
    shepard = sy.mix_layers(voices, [1.0 / n_voices] * n_voices)
    shepard = sy.bitcrush(shepard, bits=11)
    shepard = sy.lowpass(shepard, 2200)

    bed = sy.brown_noise(dur, seed=seed)
    bed = sy.bandpass(bed, 150, q=0.6)

    # oppressive slow sub swell
    sub = sy.sine(42.0, dur)
    sub_lfo = 0.5 + 0.5 * sy.sine(0.05, dur).astype(np.float64)
    sub = (sub.astype(np.float64) * sub_lfo).astype(np.float32)

    rng2 = np.random.default_rng(seed + 1)
    whispers = np.zeros(n, dtype=np.float64)
    for _ in range(10):
        t0 = rng2.uniform(0, dur - 3)
        wdur = rng2.uniform(1.2, 2.5)
        w = sy.white_noise(wdur, seed=int(rng2.integers(0, 1 << 30)))
        w = sy.bandpass(w, rng2.uniform(500, 2500), q=3.0)
        gate = telegraph_gate(wdur, 30, 0.2, seed=int(rng2.integers(0, 1 << 30)))
        w = (w.astype(np.float64) * gate).astype(np.float32)
        w = sy.apply_env(w, sy.env_adsr(wdur, attack=wdur * 0.3, decay=wdur * 0.2,
                                        sustain_level=0.4, release=wdur * 0.4))
        w = w.astype(np.float64) * 0.12
        start = sy.samples(t0)
        end = min(n, start + len(w))
        whispers[start:end] += w[: end - start]

    x = sy.mix_layers([shepard, bed, sub, whispers.astype(np.float32)],
                      [0.5, 0.55, 0.35, 1.0])
    x = sy.crossfade_loop(x, 2.5)
    return x


def gen_amb_drone_finale() -> np.ndarray:
    seed = _seed("ambfinale")
    dur = 60.0
    n_total = sy.samples(dur)
    sub = sy.sine(38.0, dur)
    sub_lfo = 0.7 + 0.3 * sy.sine(0.06, dur).astype(np.float64)
    sub = (sub.astype(np.float64) * sub_lfo).astype(np.float32)

    hollow = sy.brown_noise(dur, seed=seed)
    hollow = sy.bandpass(hollow, 90, q=0.5)

    pulses = np.zeros(n_total, dtype=np.float64)
    rng = np.random.default_rng(seed + 1)
    t = 2.0
    while t < dur - 2.0:
        p = gun_thump(f0=55, f1=28, pitch_s=0.3, dur_s=1.6, drive=1.1)
        p = p.astype(np.float64) * 0.5
        start = sy.samples(t)
        end = min(n_total, start + len(p))
        pulses[start:end] += p[: end - start]
        t += rng.uniform(6.0, 8.5)

    x = sy.mix_layers([sub, hollow, pulses.astype(np.float32)], [0.7, 0.4, 1.0])
    x = sy.reverb(x, room_size=0.85, damping=0.2, mix=0.2, tail_s=0.4)
    x = sy.pad_to(x, n_total)
    x = sy.crossfade_loop(x, 3.0)
    return x


# ==========================================================================
# stinger
# ==========================================================================

def gen_stinger_wrongness() -> np.ndarray:
    seed = _seed("stinger")
    dur = 2.6
    n = sy.samples(dur)
    tt = np.linspace(0.0, 1.0, n)

    # detuned cluster that smears further apart mid-way (tape-warble glide)
    smear = np.clip((tt - 0.25) / 0.35, 0.0, 1.0)  # 0 until 25%, 1 by 60%
    wobble = sy.one_pole_lowpass(sy.white_noise(dur, seed=seed + 1), 3.0).astype(np.float64)
    wobble = wobble / (np.max(np.abs(wobble)) + 1e-9)
    base_hz = 175.0
    voices = []
    for det_cents, g in ((0.0, 0.8), (18.0, 0.55), (-27.0, 0.5)):
        cents = det_cents * smear + 9.0 * wobble * (0.3 + smear)
        freq = base_hz * 2.0 ** (cents / 1200.0) * (1.0 - 0.04 * smear)
        v = sy.saw(freq, dur)
        voices.append((v.astype(np.float64) * g).astype(np.float32))
    cluster = sy.mix_layers(voices)
    # distortion swells in with the smear
    drive_env = 1.0 + 2.5 * smear
    cluster = np.tanh(cluster.astype(np.float64) * drive_env).astype(np.float32)
    cluster = sy.lowpass(cluster, 1600)

    # slow static swell, gated, ducking into a low settle
    swell = sy.white_noise(dur, seed=seed + 2)
    swell = sy.bandpass(swell, 1100, q=0.8)
    gate = telegraph_gate(dur, 120, 0.4, seed=seed + 3)
    swell = (swell.astype(np.float64) * gate).astype(np.float32)
    swell_env = sy.env_adsr(dur, attack=dur * 0.45, decay=dur * 0.1,
                            sustain_level=0.3, release=dur * 0.4)
    swell = sy.apply_env(swell, swell_env)

    sub = gun_thump(f0=60, f1=34, pitch_s=0.4, dur_s=1.0, drive=1.5)

    x = place(dur,
              (0.0, cluster, 0.7),
              (0.0, swell, 0.22),
              (dur * 0.62, sub, 0.5))
    amp_env = sy.env_adsr(dur, attack=0.18, decay=0.2, sustain_level=0.85,
                          release=dur * 0.3)
    x = sy.apply_env(x, amp_env)
    x = sy.soft_clip(x, 1.3)
    return finish(x, fade_s=0.15, pad_s=0.05)


# ==========================================================================
# manifest / normalization / build
# ==========================================================================

PEAK_GUN = -1.5
PEAK_IMPACT = -2.5
PEAK_ENEMY = -2.0
PEAK_PLAYER = -3.0
PEAK_UI = -4.0
RMS_DRONE = -12.0
PEAK_STINGER = -6.0

# (name, spec, dur_min, dur_max, category, generator, normalize)
_ENTRIES = [
    ("pistol_fire", "sharp crack, punchy transient, slight metallic ring", 0.10, 0.20, "gun", gen_pistol_fire, ("peak", PEAK_GUN)),
    ("smg_fire", "shorter, rattier crack than the pistol", 0.06, 0.14, "gun", gen_smg_fire, ("peak", PEAK_GUN)),
    ("shotgun_fire", "deep boom plus spread noise", 0.22, 0.42, "gun", gen_shotgun_fire, ("peak", PEAK_GUN)),
    ("rail_fire", "electric zap plus deep thud", 0.24, 0.36, "gun", gen_rail_fire, ("peak", PEAK_GUN)),
    ("lightning_fire", "crackling electric discharge burst, scary", 0.35, 0.75, "gun", gen_lightning_fire, ("peak", PEAK_GUN)),
    ("dry_click", "empty mag click, very short and dry", 0.02, 0.08, "gun", gen_dry_click, ("peak", PEAK_GUN)),
    ("reload", "mechanical clack-clack reload", 0.25, 0.35, "gun", gen_reload, ("peak", PEAK_IMPACT)),
    ("knife_swing", "whoosh of a knife swing through air", 0.08, 0.16, "gun", gen_knife_swing, ("peak", PEAK_IMPACT)),
    ("knife_hit", "wet thunk of a knife impact", 0.07, 0.14, "gun", gen_knife_hit, ("peak", PEAK_IMPACT)),
    ("hit_flesh", "wet impact on flesh", 0.06, 0.20, "impact", gen_hit_flesh, ("peak", PEAK_IMPACT)),
    ("hit_wall", "dull concrete tick, dry, no ring", 0.04, 0.14, "impact", gen_hit_wall, ("peak", PEAK_IMPACT)),
    ("ricochet", "occasional metallic zing ricochet", 0.12, 0.28, "impact", gen_ricochet, ("peak", PEAK_IMPACT)),
    ("enemy_die_husk", "wet collapse plus a low groan", 0.30, 0.55, "enemy", gen_enemy_die_husk, ("peak", PEAK_ENEMY)),
    ("enemy_die_mite", "small squelch pop death", 0.10, 0.22, "enemy", gen_enemy_die_mite, ("peak", PEAK_ENEMY)),
    ("enemy_die_brute", "heavy wet fall plus sub thud", 0.45, 0.85, "enemy", gen_enemy_die_brute, ("peak", PEAK_ENEMY)),
    ("enemy_alert_husk", "raspy inhale and groan, unsettling", 0.25, 0.60, "enemy", gen_enemy_alert_husk, ("peak", PEAK_ENEMY)),
    ("enemy_alert_mite", "rapid insect-like chittering", 0.15, 0.30, "enemy", gen_enemy_alert_mite, ("peak", PEAK_ENEMY)),
    ("spitter_shoot", "organic wet spit lob projectile launch", 0.15, 0.30, "enemy", gen_spitter_shoot, ("peak", PEAK_ENEMY)),
    ("shrieker_scream", "piercing distorted shriek, the scariest sound in the game", 0.55, 1.0, "enemy", gen_shrieker_scream, ("peak", PEAK_ENEMY + 0.5)),
    ("player_hurt", "sharp grunt-like thump plus a high sting", 0.10, 0.20, "player", gen_player_hurt, ("peak", PEAK_PLAYER)),
    ("player_die", "long collapse with a fading ring", 1.0, 1.5, "player", gen_player_die, ("peak", PEAK_PLAYER)),
    ("heartbeat", "single low double-thump, loopable, ~800ms", 0.6, 1.0, "player", gen_heartbeat, ("peak", PEAK_PLAYER - 2.0)),
    ("pickup_ammo", "metallic clink-slide of picking up ammo", 0.10, 0.20, "pickup", gen_pickup_ammo, ("peak", PEAK_UI)),
    ("pickup_medkit", "soft latch click plus a hiss", 0.18, 0.32, "pickup", gen_pickup_medkit, ("peak", PEAK_UI)),
    ("pickup_key", "small chime, but dark and detuned", 0.15, 0.28, "pickup", gen_pickup_key, ("peak", PEAK_UI)),
    ("terminal_open", "CRT power hum blip", 0.15, 0.28, "ui", gen_terminal_open, ("peak", PEAK_UI)),
    ("terminal_type", "single keyboard key tick", 0.015, 0.05, "ui", gen_terminal_type, ("peak", PEAK_UI)),
    ("radio_blip", "short filtered static burst plus tone, radio voice cue", 0.10, 0.20, "ui", gen_radio_blip, ("peak", PEAK_UI)),
    ("door_unlock", "heavy mechanical servo clunk unlocking a door", 0.25, 0.40, "door", gen_door_unlock, ("peak", PEAK_IMPACT)),
    ("amb_drone_early", "60s loopable low industrial hum, distant vents, faint metal -- mundane", 60.0, 60.0, "drone", gen_amb_drone_early, ("rms", RMS_DRONE)),
    ("amb_drone_mid", "60s loopable industrial hum plus subtle wrongness: slow detuned beating, occasional far groan", 60.0, 60.0, "drone", gen_amb_drone_mid, ("rms", RMS_DRONE)),
    ("amb_drone_late", "60s loopable oppressive tonal shepard-tone descent illusion with whispers of static", 60.0, 60.0, "drone", gen_amb_drone_late, ("rms", RMS_DRONE)),
    ("amb_drone_finale", "60s loopable vast hollow sun-falling dread with deep slow pulses", 60.0, 60.0, "drone", gen_amb_drone_finale, ("rms", RMS_DRONE)),
    ("stinger_wrongness", "2-3s reality-hiccup sting for scripted moments, subtle detune smear, not a horror-movie jumpscare orchestra hit", 2.0, 3.2, "stinger", gen_stinger_wrongness, ("peak", PEAK_STINGER)),
]


def _normalize(x: np.ndarray, spec) -> np.ndarray:
    kind, target = spec
    if kind == "peak":
        return sy.normalize_peak(x, target)
    if kind == "rms":
        return sy.normalize_rms(x, target)
    raise ValueError(kind)


def build_manifest() -> list[dict]:
    manifest = []
    for name, spec, dmin, dmax, category, _gen, norm in _ENTRIES:
        manifest.append({
            "name": name,
            "spec": spec,
            "dur_min": dmin,
            "dur_max": dmax,
            "category": category,
            "path": str((SFX_DIR / f"{name}.wav").relative_to(REPO_ROOT)),
        })
    return manifest


MANIFEST = build_manifest()


def build_bank(out_dir: Path = SFX_DIR, only: set[str] | None = None) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name, spec, dmin, dmax, category, gen, norm in _ENTRIES:
        if only is not None and name not in only:
            continue
        x = gen()
        x = _normalize(x, norm)
        path = out_dir / f"{name}.wav"
        sy.write_wav(path, x)
        dur = len(x) / SR
        results.append({
            "name": name, "spec": spec, "dur_min": dmin, "dur_max": dmax,
            "category": category, "path": str(path.relative_to(REPO_ROOT)),
            "actual_dur": dur,
        })
        print(f"  {name:22s} {dur:7.3f}s -> {path.relative_to(REPO_ROOT)}")
    return results


if __name__ == "__main__":
    only = None
    if len(sys.argv) > 1:
        only = set(sys.argv[1].split(","))
    print(f"Building SFX bank -> {SFX_DIR}")
    res = build_bank(only=only)
    print(f"Wrote {len(res)} sounds.")
