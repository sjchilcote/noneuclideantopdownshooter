"""tools/soundgen/bank.py

Generates the full PERIHELION SFX bank into game/assets/sfx/*.wav using the
numpy DSP toolkit in synth.py. Every sound has a one-line SPEC string
(intent description) used later for AI verification (see verify_bank.py).

Run:
    uv run python tools/soundgen/bank.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth as sy  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SFX_DIR = REPO_ROOT / "game" / "assets" / "sfx"

SR = sy.SR
rng_master = np.random.default_rng(20260709)


def _seed(name: str) -> int:
    return int.from_bytes(name.encode()[:4].ljust(4, b"\0"), "little") & 0x7FFFFFFF


# ==========================================================================
# shared sound-design building blocks
# ==========================================================================

def crack(dur_s: float, hp: float = 1500.0, tau: float = 0.02, seed=None,
          drive: float = 1.0) -> np.ndarray:
    """A short filtered noise transient -- the 'snap' of a gunshot/click."""
    n = sy.white_noise(dur_s, seed=seed)
    n = sy.highpass(n, hp)
    env = sy.env_exp_decay(dur_s, tau=tau, start=1.0, end=0.01)
    x = sy.apply_env(n, env)
    if drive != 1.0:
        x = sy.soft_clip(x, drive)
    return x


def thump(dur_s: float, f0: float = 120.0, f1: float = 40.0, tau=None,
          drive: float = 1.0) -> np.ndarray:
    """A low pitched sine thud with downward pitch envelope."""
    pe = sy.pitch_env(dur_s, f0, f1)
    tone = sy.sine(pe, dur_s)
    env = sy.env_exp_decay(dur_s, tau=tau, start=1.0, end=0.01)
    x = sy.apply_env(tone, env)
    if drive != 1.0:
        x = sy.soft_clip(x, drive)
    return x


def metallic_ring(dur_s: float, base_freq: float = 1800.0,
                   partials=(1.0, 1.47, 2.03, 2.63), tau: float = 0.05,
                   seed=None) -> np.ndarray:
    """A handful of inharmonic sine partials with independent fast decay --
    reads as a metallic 'ring' rather than a clean musical tone."""
    rng = np.random.default_rng(seed)
    layers, gains = [], []
    for i, mult in enumerate(partials):
        detune = 1.0 + rng.uniform(-0.01, 0.01)
        tone = sy.sine(base_freq * mult * detune, dur_s, phase0=rng.uniform(0, 2 * np.pi))
        this_tau = tau / (1.0 + i * 0.35)
        env = sy.env_exp_decay(dur_s, tau=this_tau, start=1.0, end=0.005)
        layers.append(sy.apply_env(tone, env))
        gains.append(0.7 / (i + 1))
    return sy.mix_layers(layers, gains)


def noise_burst(dur_s: float, center: float, q: float = 2.0, tau=None,
                 seed=None) -> np.ndarray:
    n = sy.white_noise(dur_s, seed=seed)
    n = sy.bandpass(n, center, q=q)
    env = sy.env_exp_decay(dur_s, tau=tau, start=1.0, end=0.02)
    return sy.apply_env(n, env)


def swept_bandpass_noise(dur_s: float, f0: float, f1: float, q: float = 3.0,
                          seed=None) -> np.ndarray:
    n = sy.white_noise(dur_s, seed=seed)
    sweep = sy.pitch_env(dur_s, f0, f1)
    return sy.bandpass(n, sweep, q=q)


def swept_lowpass_noise(dur_s: float, f0: float, f1: float, seed=None) -> np.ndarray:
    n = sy.white_noise(dur_s, seed=seed)
    sweep = sy.pitch_env(dur_s, f0, f1)
    return sy.lowpass(n, sweep, q=0.8)


def click_train(n_clicks: int, dur_s: float, freq_lo: float, freq_hi: float,
                 tau: float = 0.02, jitter: float = 0.4, seed=None) -> np.ndarray:
    """A scattered series of short pitched blips within a window -- chitter,
    static ticks, etc."""
    rng = np.random.default_rng(seed)
    total_n = sy.samples(dur_s)
    out = np.zeros(total_n, dtype=np.float64)
    slot = dur_s / n_clicks
    for i in range(n_clicks):
        t_center = i * slot + rng.uniform(0, slot * jitter)
        blip_dur = min(0.02, dur_s - t_center - 1e-4)
        if blip_dur <= 0.001:
            continue
        f = rng.uniform(freq_lo, freq_hi)
        tone = sy.square(f, blip_dur)
        env = sy.env_exp_decay(blip_dur, tau=tau, start=1.0, end=0.02)
        blip = sy.apply_env(tone, env) * rng.uniform(0.6, 1.0)
        start = sy.samples(t_center)
        end = min(total_n, start + len(blip))
        out[start:end] += blip[: end - start]
    return out.astype(np.float32)


def groan(dur_s: float, f0: float, f1: float, vibrato_hz: float = 5.0,
          vibrato_depth: float = 0.03, drive: float = 2.0, seed=None) -> np.ndarray:
    """A low, organic, slightly distorted vocal-ish groan."""
    base = sy.pitch_env(dur_s, f0, f1)
    lfo = sy.sine(vibrato_hz, dur_s).astype(np.float64)
    freq = base * (1.0 + vibrato_depth * lfo)
    tone = sy.saw(freq, dur_s)
    tone = sy.soft_clip(tone, drive)
    tone = sy.lowpass(tone, max(f0, f1) * 3.5)
    return tone


# ==========================================================================
# weapon sounds
# ==========================================================================

def gen_pistol_fire() -> np.ndarray:
    seed = _seed("pistol")
    body = crack(0.06, hp=900, tau=0.012, seed=seed, drive=2.2)
    pop = thump(0.05, f0=320, f1=90, tau=0.014, drive=1.6)
    ring = metallic_ring(0.09, base_freq=2100, tau=0.03, seed=seed + 1)
    x = sy.mix_layers([body, pop, ring], [0.85, 0.55, 0.28])
    x = sy.soft_clip(x, 1.4)
    x = sy.pad_to(x, sy.samples(0.15))
    return x


def gen_smg_fire() -> np.ndarray:
    seed = _seed("smg")
    body = crack(0.045, hp=700, tau=0.008, seed=seed, drive=2.8)
    pop = thump(0.04, f0=260, f1=100, tau=0.009, drive=2.0)
    x = sy.mix_layers([body, pop], [0.9, 0.4])
    x = sy.bitcrush(x, bits=7, rate_divisor=2)
    x = sy.soft_clip(x, 1.8)
    x = sy.pad_to(x, sy.samples(0.09))
    return x


def gen_shotgun_fire() -> np.ndarray:
    seed = _seed("shotgun")
    boom = thump(0.32, f0=100, f1=32, tau=0.14, drive=1.8)
    spread = swept_lowpass_noise(0.3, 4200, 450, seed=seed)
    spread = sy.apply_env(spread, sy.env_exp_decay(0.3, tau=0.11))
    crack_ = crack(0.02, hp=600, tau=0.006, seed=seed + 3, drive=2.0)
    x = sy.mix_layers([crack_, boom, spread], [0.9, 0.95, 0.75])
    x = sy.soft_clip(x, 1.5)
    x = sy.pad_to(x, sy.samples(0.34))
    return x


def gen_rail_fire() -> np.ndarray:
    seed = _seed("rail")
    zap_pitch = sy.pitch_env(0.16, 2400, 180)
    zap = sy.square(zap_pitch, 0.16)
    zap = sy.bitcrush(zap, bits=6, rate_divisor=3)
    zap = sy.apply_env(zap, sy.env_exp_decay(0.16, tau=0.05))
    deep = thump(0.3, f0=150, f1=45, tau=0.11, drive=1.6)
    x = sy.mix_layers([zap, deep], [0.55, 0.9])
    x = sy.soft_clip(x, 1.3)
    x = sy.pad_to(x, sy.samples(0.3))
    return x


def gen_lightning_fire() -> np.ndarray:
    seed = _seed("lightning")
    rng = np.random.default_rng(seed)
    dur = 0.55
    n_total = sy.samples(dur)
    out = np.zeros(n_total, dtype=np.float64)
    # scattered crackle impulses
    n_crackles = 14
    for i in range(n_crackles):
        t0 = rng.uniform(0, dur * 0.85)
        cdur = rng.uniform(0.01, 0.035)
        center = rng.uniform(1800, 6500)
        c = noise_burst(cdur, center, q=rng.uniform(1.5, 4.0), tau=cdur * 0.4,
                         seed=int(rng.integers(0, 1 << 30)))
        c = sy.soft_clip(c, 2.5) * rng.uniform(0.4, 1.0)
        start = sy.samples(t0)
        end = min(n_total, start + len(c))
        out[start:end] += c[: end - start]
    # rising-falling resonant arc
    arc = swept_bandpass_noise(dur, 300, 5200, q=6.0, seed=seed + 1)
    arc_env = sy.env_adsr(dur, attack=0.05, decay=0.15, sustain_level=0.5, release=0.25)
    arc = sy.apply_env(arc, arc_env) * 0.7
    # low rumble bed
    rumble = sy.brown_noise(dur, seed=seed + 2)
    rumble = sy.lowpass(rumble, 180)
    rumble = sy.apply_env(rumble, sy.env_exp_decay(dur, tau=0.3)) * 0.5
    # metallic buzz via ring-mod
    buzz_lfo = sy.sine(90, dur).astype(np.float64)
    buzz = sy.white_noise(dur, seed=seed + 3) * buzz_lfo
    buzz = sy.bandpass(buzz, 2500, q=2.0)
    buzz = sy.apply_env(buzz, sy.env_exp_decay(dur, tau=0.2)) * 0.4
    x = sy.mix_layers([out.astype(np.float32), arc, rumble, buzz])
    x = sy.soft_clip(x, 1.6)
    return x


def gen_dry_click() -> np.ndarray:
    seed = _seed("dryclick")
    x = crack(0.02, hp=2000, tau=0.004, seed=seed, drive=1.0)
    x = sy.pad_to(x, sy.samples(0.05))
    return x


def gen_reload() -> np.ndarray:
    seed = _seed("reload")
    clack1 = sy.mix_layers([
        crack(0.03, hp=1200, tau=0.008, seed=seed, drive=1.5),
        metallic_ring(0.05, base_freq=1400, tau=0.02, seed=seed + 1),
    ], [0.9, 0.4])
    clack2 = sy.mix_layers([
        crack(0.035, hp=900, tau=0.01, seed=seed + 2, drive=1.8),
        metallic_ring(0.06, base_freq=1100, tau=0.025, seed=seed + 3),
    ], [1.0, 0.5])
    gap = sy.silence(0.15)
    x = sy.concat(clack1, gap, clack2)
    x = sy.pad_to(x, sy.samples(0.3))
    return x


def gen_knife_swing() -> np.ndarray:
    seed = _seed("knifeswing")
    dur = 0.12
    n = sy.pink_noise(dur, seed=seed)
    sweep = sy.concat(sy.pitch_env(dur * 0.5, 300, 2200), sy.pitch_env(dur * 0.5, 2200, 500))
    x = sy.bandpass(n, sweep[: len(n)], q=1.5)
    env = sy.env_adsr(dur, attack=0.03, decay=0.03, sustain_level=0.7, release=0.05)
    x = sy.apply_env(x, env)
    return x


def gen_knife_hit() -> np.ndarray:
    seed = _seed("knifehit")
    dur = 0.1
    low = thump(dur, f0=140, f1=55, tau=0.03, drive=1.4)
    splat = noise_burst(dur * 0.7, 650, q=1.2, tau=0.02, seed=seed)
    splat = sy.lowpass(splat, 2200)
    x = sy.mix_layers([low, sy.pad_to(splat, len(low))], [0.9, 0.6])
    return x


def gen_hit_flesh() -> np.ndarray:
    seed = _seed("hitflesh")
    dur = 0.12
    low = thump(dur, f0=130, f1=60, tau=0.035, drive=1.3)
    splat = noise_burst(dur, 550, q=1.0, tau=0.03, seed=seed)
    splat = sy.lowpass(splat, 1800)
    x = sy.mix_layers([low, splat], [0.75, 0.85])
    x = sy.soft_clip(x, 1.2)
    return x


def gen_hit_wall() -> np.ndarray:
    seed = _seed("hitwall")
    dur = 0.08
    x = noise_burst(dur, 1100, q=1.8, tau=0.015, seed=seed)
    x = sy.highpass(x, 250)
    x = sy.lowpass(x, 3000)
    return x


def gen_ricochet() -> np.ndarray:
    seed = _seed("ricochet")
    dur = 0.2
    sweep = sy.concat(sy.pitch_env(dur * 0.35, 700, 3200), sy.pitch_env(dur * 0.65, 3200, 1100))
    tone = sy.sine(sweep, dur)
    ring = metallic_ring(dur, base_freq=2600, tau=0.06, seed=seed)
    env = sy.env_exp_decay(dur, tau=0.06)
    x = sy.mix_layers([sy.apply_env(tone, env), ring], [0.7, 0.5])
    return x


# ==========================================================================
# enemy sounds
# ==========================================================================

def gen_enemy_die_husk() -> np.ndarray:
    seed = _seed("diehusk")
    dur = 0.4
    collapse = swept_lowpass_noise(dur * 0.9, 3000, 200, seed=seed)
    collapse = sy.apply_env(collapse, sy.env_exp_decay(dur * 0.9, tau=0.18))
    low = groan(dur, 130, 55, vibrato_hz=4.0, vibrato_depth=0.05, drive=2.2, seed=seed)
    low = sy.apply_env(low, sy.env_exp_decay(dur, tau=0.2))
    x = sy.mix_layers([sy.pad_to(collapse, sy.samples(dur)), low], [0.7, 0.75])
    return x


def gen_enemy_die_mite() -> np.ndarray:
    seed = _seed("diemite")
    dur = 0.15
    pop = crack(0.008, hp=1800, tau=0.003, seed=seed, drive=1.6)
    squelch = swept_bandpass_noise(dur * 0.85, 2200, 350, q=2.5, seed=seed + 1)
    squelch = sy.apply_env(squelch, sy.env_exp_decay(dur * 0.85, tau=0.045))
    x = sy.mix_layers([sy.pad_to(pop, sy.samples(dur)), sy.pad_to(squelch, sy.samples(dur))], [0.7, 0.9])
    return x


def gen_enemy_die_brute() -> np.ndarray:
    seed = _seed("diebrute")
    dur = 0.6
    sub = thump(dur, f0=85, f1=28, tau=0.28, drive=1.6)
    collapse = swept_lowpass_noise(dur * 0.85, 2600, 150, seed=seed)
    collapse = sy.apply_env(collapse, sy.env_exp_decay(dur * 0.85, tau=0.3))
    x = sy.mix_layers([sub, sy.pad_to(collapse, sy.samples(dur))], [0.95, 0.75])
    x = sy.soft_clip(x, 1.4)
    x = sy.reverb(x, room_size=0.3, damping=0.6, mix=0.15, tail_s=0.25)
    x = sy.pad_to(x, sy.samples(dur))
    return x


def gen_enemy_alert_husk() -> np.ndarray:
    seed = _seed("alerthusk")
    dur = 0.42
    breath = sy.pink_noise(dur, seed=seed)
    breath = sy.bandpass(breath, 900, q=0.8)
    breath_env = sy.env_adsr(dur, attack=0.12, decay=0.1, sustain_level=0.55, release=0.15)
    breath = sy.apply_env(breath, breath_env)
    low = groan(dur, 100, 75, vibrato_hz=3.2, vibrato_depth=0.06, drive=1.8, seed=seed + 1)
    low = sy.apply_env(low, sy.env_adsr(dur, attack=0.08, decay=0.1, sustain_level=0.6, release=0.18))
    x = sy.mix_layers([breath, low], [0.6, 0.55])
    return x


def gen_enemy_alert_mite() -> np.ndarray:
    seed = _seed("alertmite")
    x = click_train(9, 0.2, 1400, 3200, tau=0.018, jitter=0.6, seed=seed)
    return x


def gen_spitter_shoot() -> np.ndarray:
    seed = _seed("spitter")
    dur = 0.2
    lob = swept_bandpass_noise(dur * 0.75, 2600, 350, q=2.0, seed=seed)
    lob = sy.apply_env(lob, sy.env_exp_decay(dur * 0.75, tau=0.09))
    wet = noise_burst(dur * 0.3, 500, q=1.2, tau=0.05, seed=seed + 1)
    wet_start = sy.samples(dur * 0.6)
    n_total = sy.samples(dur)
    out = np.zeros(n_total, dtype=np.float64)
    lob_p = sy.pad_to(lob, n_total)
    out += lob_p
    end = min(n_total, wet_start + len(wet))
    out[wet_start:end] += wet[: end - wet_start]
    x = out.astype(np.float32)
    x = sy.soft_clip(x, 1.2)
    return x


def gen_shrieker_scream() -> np.ndarray:
    seed = _seed("shrieker")
    dur = 0.75
    pitch = sy.pitch_env(dur, 900, 2400)
    vibrato = sy.sine(9.0, dur).astype(np.float64)
    jitter_rng = np.random.default_rng(seed)
    jitter = np.cumsum(jitter_rng.standard_normal(sy.samples(dur))) * 0.6
    jitter = jitter / (np.max(np.abs(jitter)) + 1e-9) * 60.0
    freq1 = pitch * (1.0 + 0.025 * vibrato) + jitter
    voice1 = sy.saw(freq1, dur)
    freq2 = pitch * (1.0 + 0.025 * vibrato) * 1.015 + jitter * 0.7
    voice2 = sy.saw(freq2, dur)
    voice = sy.mix_layers([voice1, voice2], [0.7, 0.55])
    voice = sy.soft_clip(voice, 3.2)
    voice = sy.bitcrush(voice, bits=9, rate_divisor=1)
    breath = sy.white_noise(dur, seed=seed + 1)
    breath = sy.bandpass(breath, pitch, q=1.5)
    env = sy.env_adsr(dur, attack=0.03, decay=0.08, sustain_level=0.85, release=0.35)
    tremolo = 1.0 + 0.15 * sy.sine(14.0, dur).astype(np.float64)
    x = sy.mix_layers([voice, breath], [0.85, 0.35])
    x = sy.apply_env(x, env * tremolo.astype(np.float32))
    x = sy.highpass(x, 400)
    x = sy.soft_clip(x, 1.3)
    return x


# ==========================================================================
# player sounds
# ==========================================================================

def gen_player_hurt() -> np.ndarray:
    seed = _seed("playerhurt")
    dur = 0.15
    low = thump(dur, f0=130, f1=65, tau=0.045, drive=1.5)
    grunt = noise_burst(dur * 0.7, 550, q=1.0, tau=0.03, seed=seed)
    sting = sy.sine(3000, dur * 0.3)
    sting = sy.apply_env(sting, sy.env_exp_decay(dur * 0.3, tau=0.012))
    sting = sy.bitcrush(sting, bits=8, rate_divisor=2)
    n_total = sy.samples(dur)
    x = sy.mix_layers([low, sy.pad_to(grunt, n_total), sy.pad_to(sting, n_total)], [0.85, 0.5, 0.45])
    x = sy.soft_clip(x, 1.3)
    return x


def gen_player_die() -> np.ndarray:
    seed = _seed("playerdie")
    dur = 1.0
    low = groan(dur, 150, 40, vibrato_hz=2.5, vibrato_depth=0.04, drive=2.0, seed=seed)
    low = sy.apply_env(low, sy.env_exp_decay(dur, tau=0.45))
    collapse = sy.brown_noise(dur, seed=seed + 1)
    collapse = sy.lowpass(collapse, 400)
    collapse = sy.apply_env(collapse, sy.env_exp_decay(dur, tau=0.35)) * 0.4
    x = sy.mix_layers([low, collapse])
    x = sy.reverb(x, room_size=0.7, damping=0.35, mix=0.35, tail_s=0.5)
    x = sy.fade_out(x, 0.3)
    return x


def gen_heartbeat() -> np.ndarray:
    seed = _seed("heartbeat")
    lub = sy.mix_layers([
        thump(0.09, f0=70, f1=42, tau=0.03, drive=1.6),
        noise_burst(0.05, 90, q=1.5, tau=0.02, seed=seed),
    ], [0.9, 0.25])
    dub = sy.mix_layers([
        thump(0.08, f0=60, f1=38, tau=0.025, drive=1.5),
        noise_burst(0.04, 80, q=1.5, tau=0.018, seed=seed + 1),
    ], [0.75, 0.2])
    gap1 = sy.silence(0.14)
    tail_gap = sy.silence(0.42)
    x = sy.concat(lub, gap1, dub, tail_gap)
    x = sy.pad_to(x, sy.samples(0.8))
    return x


# ==========================================================================
# pickups / UI / narrative props
# ==========================================================================

def gen_pickup_ammo() -> np.ndarray:
    seed = _seed("pickammo")
    dur = 0.15
    clink = metallic_ring(dur * 0.6, base_freq=3200, partials=(1.0, 1.9, 2.6), tau=0.025, seed=seed)
    slide = crack(dur * 0.5, hp=2500, tau=0.03, seed=seed + 1, drive=1.0) * 0.35
    n_total = sy.samples(dur)
    x = sy.mix_layers([sy.pad_to(clink, n_total), sy.pad_to(slide, n_total)])
    return x


def gen_pickup_medkit() -> np.ndarray:
    seed = _seed("pickmed")
    dur = 0.25
    latch = crack(0.04, hp=600, tau=0.012, seed=seed, drive=1.0)
    latch = sy.lowpass(latch, 2500)
    hiss = sy.white_noise(dur * 0.9, seed=seed + 1)
    hiss = sy.highpass(hiss, 2500)
    hiss = sy.apply_env(hiss, sy.env_exp_decay(dur * 0.9, tau=0.1)) * 0.3
    n_total = sy.samples(dur)
    x = sy.mix_layers([sy.pad_to(latch, n_total), sy.pad_to(hiss, n_total)])
    return x


def gen_pickup_key() -> np.ndarray:
    seed = _seed("pickkey")
    dur = 0.2
    x = metallic_ring(dur, base_freq=920, partials=(1.0, 1.01, 1.53, 2.11), tau=0.13, seed=seed)
    return x


def gen_terminal_open() -> np.ndarray:
    seed = _seed("termopen")
    dur = 0.2
    hum = sy.square(58.0, dur)
    hum = sy.lowpass(hum, 400)
    hum_env = sy.env_adsr(dur, attack=0.015, decay=0.02, sustain_level=0.8, release=0.08)
    hum = sy.apply_env(hum, hum_env)
    click = crack(0.01, hp=2000, tau=0.004, seed=seed, drive=1.0) * 0.5
    n_total = sy.samples(dur)
    x = sy.mix_layers([hum, sy.pad_to(click, n_total)], [0.7, 0.5])
    return x


def gen_terminal_type() -> np.ndarray:
    seed = _seed("termtype")
    x = crack(0.02, hp=2500, tau=0.006, seed=seed, drive=1.0)
    x = sy.pad_to(x, sy.samples(0.03))
    return x


def gen_radio_blip() -> np.ndarray:
    seed = _seed("radioblip")
    dur = 0.15
    static = noise_burst(dur * 0.8, 1600, q=1.0, tau=0.06, seed=seed)
    tone = sy.square(820, dur * 0.5)
    tone = sy.apply_env(tone, sy.env_exp_decay(dur * 0.5, tau=0.05))
    n_total = sy.samples(dur)
    x = sy.mix_layers([sy.pad_to(static, n_total), sy.pad_to(tone, n_total)], [0.7, 0.5])
    x = sy.bandpass(x, 1400, q=0.9)
    x = sy.bitcrush(x, bits=7, rate_divisor=2)
    return x


def gen_door_unlock() -> np.ndarray:
    seed = _seed("doorunlock")
    dur = 0.3
    whir_pitch = sy.pitch_env(dur * 0.55, 180, 420)
    whir = sy.square(whir_pitch, dur * 0.55)
    whir = sy.lowpass(whir, 1200)
    whir = sy.apply_env(whir, sy.env_adsr(dur * 0.55, attack=0.02, decay=0.05, sustain_level=0.6, release=0.1))
    clunk = sy.mix_layers([
        thump(dur * 0.35, f0=160, f1=55, tau=0.05, drive=1.5),
        crack(dur * 0.15, hp=800, tau=0.02, seed=seed, drive=1.4),
    ], [0.9, 0.6])
    n_total = sy.samples(dur)
    clunk_start = sy.samples(dur * 0.5)
    out = np.zeros(n_total, dtype=np.float64)
    out[: len(whir)] += whir.astype(np.float64) * 0.6
    end = min(n_total, clunk_start + len(clunk))
    out[clunk_start:end] += clunk[: end - clunk_start].astype(np.float64)
    return out.astype(np.float32)


# ==========================================================================
# ambient drones (60s, loopable)
# ==========================================================================

def _vent_bed(dur_s: float, seed: int) -> np.ndarray:
    n = sy.brown_noise(dur_s, seed=seed)
    n = sy.bandpass(n, 220, q=0.7)
    lfo = 0.5 + 0.5 * sy.sine(0.045, dur_s).astype(np.float64)
    return (n.astype(np.float64) * lfo).astype(np.float32)


def _hum_bed(dur_s: float, base=55.0) -> np.ndarray:
    h1 = sy.sine(base, dur_s)
    h2 = sy.sine(base * 2.0, dur_s) * 0.4
    h3 = sy.sine(base * 3.01, dur_s) * 0.15
    hum = sy.mix_layers([h1, h2, h3])
    lfo = 1.0 + 0.06 * sy.sine(0.08, dur_s).astype(np.float64)
    hum = (hum.astype(np.float64) * lfo).astype(np.float32)
    return sy.lowpass(hum, 900)


def gen_amb_drone_early() -> np.ndarray:
    seed = _seed("ambearly")
    dur = 60.0
    hum = _hum_bed(dur, base=55.0)
    vents = _vent_bed(dur, seed)
    metal = np.zeros(sy.samples(dur), dtype=np.float64)
    rng = np.random.default_rng(seed + 5)
    for _ in range(4):
        t0 = rng.uniform(2, dur - 3)
        ring = metallic_ring(1.2, base_freq=rng.uniform(1200, 2200), tau=0.4, seed=int(rng.integers(0, 1 << 30)))
        ring = ring.astype(np.float64) * 0.12
        start = sy.samples(t0)
        end = min(len(metal), start + len(ring))
        metal[start:end] += ring[: end - start]
    x = sy.mix_layers([hum, vents, metal.astype(np.float32)], [0.6, 0.5, 0.4])
    x = sy.crossfade_loop(x, 2.5)
    return x


def gen_amb_drone_mid() -> np.ndarray:
    seed = _seed("ambmid")
    dur = 60.0
    base = gen_amb_drone_early()
    detune1 = sy.sine(110.0, dur)
    detune2 = sy.sine(111.6, dur)
    beat = sy.mix_layers([detune1, detune2], [0.35, 0.35])
    beat = sy.lowpass(beat, 500)
    n_total = sy.samples(dur)
    far_groan = np.zeros(n_total, dtype=np.float64)
    rng = np.random.default_rng(seed)
    for t0 in (rng.uniform(8, 18), rng.uniform(28, 40), rng.uniform(45, 55)):
        g = groan(2.0, 90, 65, vibrato_hz=2.0, vibrato_depth=0.08, drive=1.5, seed=int(rng.integers(0, 1 << 30)))
        g = sy.apply_env(g, sy.env_adsr(2.0, attack=0.4, decay=0.4, sustain_level=0.5, release=1.0))
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
    voices = []
    for i in range(n_voices):
        phase0 = i * n_octaves / n_voices
        pos = np.mod(phase0 - speed_oct_per_s * tt, n_octaves)
        freq = f_min * (2.0 ** pos)
        amp = np.sin(np.pi * pos / n_octaves) ** 2
        tone = np.sin(2.0 * np.pi * np.cumsum(freq) / SR)
        voices.append((tone * amp).astype(np.float32))
    shepard = sy.mix_layers(voices, [1.0 / n_voices] * n_voices)
    shepard = sy.lowpass(shepard, 2500)

    bed = sy.brown_noise(dur, seed=seed)
    bed = sy.bandpass(bed, 150, q=0.6)

    rng = np.random.default_rng(seed + 1)
    whispers = np.zeros(n, dtype=np.float64)
    for _ in range(8):
        t0 = rng.uniform(0, dur - 3)
        wdur = rng.uniform(1.2, 2.5)
        w = sy.white_noise(wdur, seed=int(rng.integers(0, 1 << 30)))
        w = sy.bandpass(w, rng.uniform(500, 2500), q=3.0)
        w = sy.apply_env(w, sy.env_adsr(wdur, attack=wdur * 0.3, decay=wdur * 0.2,
                                         sustain_level=0.4, release=wdur * 0.4))
        w = w.astype(np.float64) * 0.08
        start = sy.samples(t0)
        end = min(n, start + len(w))
        whispers[start:end] += w[: end - start]

    x = sy.mix_layers([shepard, bed, whispers.astype(np.float32)], [0.55, 0.5, 1.0])
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
        p = thump(1.6, f0=55, f1=28, tau=0.7, drive=1.1)
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
    dur = 2.5
    base = sy.sine(180.0, dur)
    h2 = sy.sine(180.0 * 2.0, dur) * 0.3
    h3 = sy.sine(180.0 * 3.0, dur) * 0.12
    pad = sy.mix_layers([base, h2, h3])

    smear_env = np.concatenate([
        np.zeros(sy.samples(dur * 0.25)),
        np.linspace(0.0, 1.0, sy.samples(dur * 0.3)),
        np.linspace(1.0, 0.0, sy.samples(dur * 0.45)),
    ])
    smear_env = sy.pad_to(smear_env.astype(np.float32), sy.samples(dur))
    detune_cents = 55.0
    detune_ratio = 2.0 ** (detune_cents / 1200.0)
    detuned = sy.sine(180.0 * detune_ratio, dur)
    smeared = sy.mix_layers([pad, detuned], [1.0, 0.6])
    x = pad.astype(np.float64) * (1.0 - smear_env.astype(np.float64)) + \
        smeared.astype(np.float64) * smear_env.astype(np.float64)
    x = x.astype(np.float32)

    noise_seed = seed
    swell = sy.white_noise(dur, seed=noise_seed)
    swell = sy.bandpass(swell, 700, q=0.6)
    swell_env = sy.env_adsr(dur, attack=dur * 0.35, decay=dur * 0.15, sustain_level=0.25, release=dur * 0.4)
    swell = sy.apply_env(swell, swell_env) * 0.25

    x = sy.mix_layers([x, swell])
    x = sy.fade_in(x, 0.25)
    x = sy.fade_out(x, 0.6)
    return x


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
    print(f"Building SFX bank -> {SFX_DIR}")
    res = build_bank()
    print(f"Wrote {len(res)} sounds.")
