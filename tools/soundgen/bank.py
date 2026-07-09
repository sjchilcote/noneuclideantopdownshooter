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


def hot_transient(dur_s: float = 0.008, seed=None, gain: float = 1.2,
                  lp_hz: float | None = None) -> np.ndarray:
    """0-8ms full-band white-noise click, very hot. Optionally darkened with
    a lowpass so it reads as physical impact rather than digital click."""
    n = sy.white_noise(dur_s, seed=seed)
    if lp_hz is not None:
        n = sy.lowpass(n, lp_hz)
    env = sy.env_exp_decay(dur_s, tau=dur_s / 3.0, start=1.0, end=0.001)
    return (sy.apply_env(n, env).astype(np.float64) * gain).astype(np.float32)


def body_knock(dur_s: float = 0.12, center_hz: float = 200.0, q: float = 1.1,
               seed=None, drive: float = 1.6) -> np.ndarray:
    """Low-mid 'knock' -- bandpassed noise burst in the 120-400Hz region.
    This is the part of an impact the ear reads as physical weight (fast pure
    sub-sine thumps are nearly inaudible perceptually)."""
    n = sy.white_noise(dur_s, seed=seed)
    n = sy.bandpass(n, center_hz, q=q)
    env = sy.env_exp_decay(dur_s, tau=dur_s / 3.5, end=0.001)
    return sy.soft_clip(sy.apply_env(n, env), drive)


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
            transient_gain: float = 0.85, thump_gain: float = 1.25,
            body_gain: float = 0.7, tail_gain: float = 0.25,
            knock_gain: float = 0.85, knock_hz: float = 200.0,
            transient_lp: float | None = 5000.0,
            drive: float = 2.5, double_thump_at: float | None = None,
            prepend: np.ndarray | None = None,
            sub_kw: dict | None = None, sub_gain: float = 0.0, sub_at: float = 0.006,
            fade_s: float = 0.015) -> np.ndarray:
    """Layered gunshot: darkened transient + pitched thump + low-mid knock +
    swept noise body + comb-delayed tail -> tanh -> enveloped to zero.

    `sub_gain` > 0 layers an extra deep, fast sub-bass punch (a second
    gun_thump tuned by `sub_kw`, defaults below) under everything -- the
    'felt' low-end weight distinct from the pitched thump's audible tone.
    It's placed at `sub_at` (a few ms after t=0, not exactly on top of the
    transient/thump/body/knock onset) on purpose: everything else piles
    onto the same sample at t=0, and the whole clip gets peak-normalized
    afterward, so stacking yet another hot layer there mostly just raises
    the peak and gets normalized right back down -- a measured no-op.
    Offsetting it lets it actually survive normalization as low-end weight.
    `fade_s` is forwarded to `finish()`; a longer fade blends the tail's own
    decay into true zero instead of a short window reading as a hard gate."""
    knock_dur = min(0.14, total_s * 0.5)
    events = [
        (0.0, hot_transient(seed=seed, lp_hz=transient_lp), transient_gain),
        (0.002, gun_thump(**thump_kw), thump_gain),
        (0.0, gun_body(seed=seed + 2, **body_kw), body_gain),
        (0.012, gun_tail(seed=seed + 3, **tail_kw), tail_gain),
    ]
    if knock_gain > 0:
        events.append((0.002, body_knock(knock_dur, knock_hz, seed=seed + 8), knock_gain))
    if sub_gain > 0:
        skw = dict(f0=90.0, f1=36.0, pitch_s=0.05, dur_s=0.14, drive=1.6)
        if sub_kw:
            skw.update(sub_kw)
        events.append((sub_at, gun_thump(**skw), sub_gain))
    if double_thump_at is not None:
        events.append((double_thump_at, gun_thump(**thump_kw), thump_gain * 0.8))
        if knock_gain > 0:
            events.append((double_thump_at, body_knock(knock_dur, knock_hz * 0.85,
                                                       seed=seed + 9), knock_gain * 0.7))
    x = place(total_s, *events)
    x = sy.soft_clip(x, drive)
    if prepend is not None:
        x = sy.concat(prepend, x)
    return finish(x, fade_s=fade_s)


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
               n_grains: int = 4, grain_lo: float = 350.0, grain_hi: float = 900.0,
               body_lp: float = 500.0, drive: float = 1.8, seed=None,
               gurgle: bool = True, grain_gain: float = 0.9,
               lp_hz: float = 3000.0, gurgle_depth: float = 0.45) -> np.ndarray:
    """Wet impact: lowpassed brown-noise body (AM 'gurgle' modulated) + sine
    thump + low-mid knock + low squelch grains, all darkened below ~3kHz so
    nothing reads as metallic. No reverb tail; envelope runs to true zero."""
    body = sy.brown_noise(dur_s, seed=seed)
    body = sy.lowpass(body, body_lp)
    if gurgle:
        lfo = sy.one_pole_lowpass(sy.white_noise(dur_s, seed=(seed or 0) + 13), 35).astype(np.float64)
        lfo = (1.0 - gurgle_depth) + gurgle_depth * lfo / (np.max(np.abs(lfo)) + 1e-9)
        body = (body.astype(np.float64) * lfo).astype(np.float32)
    body = sy.apply_env(body, sy.env_exp_decay(dur_s, tau=dur_s / 3.0, end=0.001))
    th = gun_thump(f0=thump_f0, f1=thump_f1, pitch_s=0.025, dur_s=dur_s * 0.95, drive=1.8)
    knock = body_knock(dur_s * 0.7, 240.0, q=1.0, seed=(seed or 0) + 5)
    grains = squelch_grains(dur_s, n_grains, grain_lo, grain_hi,
                            grain_s=0.008, seed=(seed or 0) + 7)
    x = place(dur_s,
              (0.0, hot_transient(0.005, seed=(seed or 0) + 3, gain=0.3, lp_hz=2500), 1.0),
              (0.0, body, 1.1),
              (0.001, th, 1.1),
              (0.002, knock, 0.8),
              (0.0, grains, grain_gain))
    x = sy.soft_clip(x, drive)
    x = sy.lowpass(x, lp_hz)
    return finish(x, fade_s=0.025, pad_s=0.04)


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
               ring_decay: float = 0.15, scrape: bool = True,
               ring_lp: float = 2600.0) -> np.ndarray:
    """One mechanical event: heavy low-mid thud + knock + dark inharmonic
    metal ring + noise scrape."""
    dur = ring_decay * 1.4 + 0.08
    thud = gun_thump(f0=thud_hz * 1.9, f1=thud_hz, pitch_s=0.015, dur_s=0.09, drive=2.2)
    knock = body_knock(0.08, max(160.0, thud_hz * 2.4), seed=(seed or 0) + 21)
    ring = metal_clank(base_hz, ring_decay, seed=seed, lp_hz=ring_lp)
    events = [(0.0, thud, 1.25), (0.0, knock, 0.85), (0.0, ring, 0.55)]
    if scrape:
        sc = sy.white_noise(0.04, seed=(seed or 0) + 11)
        sc = sy.bandpass(sc, 1400, q=1.0)
        sc = sy.apply_env(sc, sy.env_adsr(0.04, 0.008, 0.01, 0.5, 0.02))
        events.append((0.004, sc, 0.4))
    x = place(dur, *events)
    return sy.soft_clip(x, 1.8)


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


def grit(x: np.ndarray, drive: float = 1.7, floor_db: float = -40.0,
         seed=None) -> np.ndarray:
    """Lo-fi 'shipped' finish: tape-style saturation + a faint pink-noise
    floor under the whole clip, so nothing reads as sterile clean synthesis.
    Matches the saturated character of the bank's anchor sounds."""
    x = sy.soft_clip(x, drive)
    dur_s = len(x) / SR
    floor_ = sy.pink_noise(dur_s, seed=seed)
    env = np.abs(x.astype(np.float64))
    env = sy.one_pole_lowpass(env.astype(np.float32), 12.0).astype(np.float64)
    env = env / (np.max(env) + 1e-9)
    lvl = sy.db_to_lin(floor_db)
    out = x.astype(np.float64) + floor_.astype(np.float64) * lvl * (0.4 + 0.6 * env)
    return out.astype(np.float32)


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
    # Round-3 punch-up, take 3: take-2 STILL measured a big hi-band loss
    # (spectral A/B: -5.4dB @ 2-8kHz) despite "restoring" transient
    # brightness, because darkening body_kw's f_hi (the ring's actual
    # frequency content) compounded with several other small darkening
    # choices into a real net loss -- and the sub layer barely moved the
    # sub-band (+0.6dB) because it was placed at t=0 on top of everything
    # else, so it mostly just raised the single-sample peak that
    # normalize_peak() then scaled right back down (self-defeating).
    # Root-cause fix: "metallic ring too bright and DOMINANT" was a LEVEL
    # complaint, not a frequency one -- keep the body's brightness/frequency
    # content intact (real crack needs real high content) but pull its GAIN
    # down so it's not the dominant layer, and give the sub layer a
    # slightly offset onset (see gunshot()'s sub_at) so it actually survives
    # normalization as felt weight instead of vanishing into the peak.
    seed = _seed("pistol")
    return gunshot(
        0.28, seed,
        thump_kw=dict(f0=148, f1=48, pitch_s=0.045, dur_s=0.19, drive=2.5),
        body_kw=dict(dur_s=0.12, f_hi=1600, f_lo=230, brown_mix=0.55),
        tail_kw=dict(dur_s=0.25, lp_hz=550),
        knock_gain=1.0, knock_hz=170.0,
        transient_gain=0.85, transient_lp=5200,
        body_gain=0.48,
        sub_gain=1.1, sub_kw=dict(f0=78, f1=28, pitch_s=0.06, dur_s=0.22, drive=1.9),
        drive=2.6, fade_s=0.045,
    )


def gen_smg_fire() -> np.ndarray:
    # Round-3 punch-up, take 3: same fix as the pistol -- keep the snap's
    # body bright (level-tame it, don't dull it) and offset the sub so it
    # survives peak-normalization.
    seed = _seed("smg")
    x = gunshot(
        0.2, seed,
        thump_kw=dict(f0=158, f1=52, pitch_s=0.028, dur_s=0.12, drive=2.5),
        body_kw=dict(dur_s=0.08, f_hi=1600, f_lo=280, brown_mix=0.5),
        tail_kw=dict(dur_s=0.17, lp_hz=600),
        knock_gain=1.0, knock_hz=195.0,
        transient_gain=0.9, transient_lp=5200,
        body_gain=0.5,
        sub_gain=0.95, sub_kw=dict(f0=76, f1=30, pitch_s=0.025, dur_s=0.13, drive=1.8),
        tail_gain=0.26, drive=2.9, fade_s=0.03,
    )
    return sy.soft_clip(sy.bitcrush(x, bits=11), 1.1)


def gen_shotgun_fire() -> np.ndarray:
    # Round-3 punch-up, take 3 (was pinned to round-2 params at 0.77): the
    # ORIGINAL flaw was specifically the TRANSIENT ("harsh digital clipping
    # character") -- unlike the pistol, darkening the transient here is the
    # right lever. But take-1/2 also darkened+quieted the body (spread
    # rattle) chasing the same fix, which isn't what was flagged; keeping
    # its brightness (pellet-spread character) but at a tamed level, plus a
    # genuinely long/loud tail and an offset sub layer (see gunshot()'s
    # sub_at note) for the "heaviest gun in the game."
    seed = _seed("shotgun")
    return gunshot(
        0.62, seed,
        thump_kw=dict(f0=144, f1=36, pitch_s=0.04, dur_s=0.25, drive=2.1),
        body_kw=dict(dur_s=0.28, f_hi=1800, f_lo=210, brown_mix=0.7),
        tail_kw=dict(dur_s=0.5, lp_hz=650),
        transient_gain=0.95, thump_gain=1.15, transient_lp=4000, knock_gain=0.0,
        body_gain=0.7, tail_gain=0.42, drive=2.0,
        double_thump_at=0.034,
        sub_gain=1.0, sub_kw=dict(f0=95, f1=26, pitch_s=0.07, dur_s=0.32, drive=1.9),
        fade_s=0.1,
    )


def gen_rail_fire() -> np.ndarray:
    # NOTE: pinned to the round-2 parameters that judged 0.95 -- keep bit-exact
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
        transient_gain=1.2, thump_gain=0.95, transient_lp=None, knock_gain=0.0,
        drive=2.6, prepend=zap,
    )


def gen_lightning_fire() -> np.ndarray:
    # Round-3 punch-up: Gemini heard thin/purely-digital high frequencies
    # and an abrupt gated ending despite the existing 180ms fade -- the low
    # end (rumble/pulses) was dying out well before the fade window started,
    # so the last moments were pure crackle/sizzle with nothing to taper.
    # Fixed by extending the pulses further into the tail, deepening/
    # boosting rumble and pulses, trimming sizzle brightness, and lengthening
    # the fade further so the final low pulse actually decays into it.
    seed = _seed("lightning")
    rng = np.random.default_rng(seed)
    dur = 0.85
    # dense micro-crackles, density decaying over time, kept below 4kHz
    crackle_events = []
    for _ in range(30):
        t0 = dur * 0.62 * (rng.uniform(0, 1) ** 1.7)
        cdur = rng.uniform(0.005, 0.02)
        c = sy.white_noise(cdur, seed=int(rng.integers(0, 1 << 30)))
        c = sy.bandpass(c, rng.uniform(650, 3400), q=rng.uniform(1.2, 3.0))
        c = sy.apply_env(c, sy.env_exp_decay(cdur, tau=cdur / 3.0))
        c = sy.soft_clip(c, 2.2)
        crackle_events.append((t0, c, rng.uniform(0.35, 0.85)))
    crackles = place(dur, *crackle_events)
    # continuous chaotic arc: resonant noise gated by random telegraph signal
    # arc runs for only ~60% of the clip (not the full dur) and its own
    # envelope fully releases to zero within that shorter buffer -- so it
    # actually clears out of the way well before the end, instead of a
    # full-length envelope whose release phase still nominally ends exactly
    # at t=dur (masking the low pulses/closer for the whole clip via
    # simultaneous broadband noise even as its amplitude tapers).
    arc_dur = dur * 0.6
    arc = sy.white_noise(arc_dur, seed=seed + 1)
    walk = np.cumsum(rng.standard_normal(sy.samples(arc_dur))) * 2.0
    walk = 650.0 + 450.0 * np.sin(walk / 400.0) + sy.pitch_env(arc_dur, 230, 1600)
    arc = sy.bandpass(arc, np.clip(walk, 170, 3600), q=4.0)
    arc = (arc.astype(np.float64) * telegraph_gate(arc_dur, 250, 0.25, seed=seed + 2)).astype(np.float32)
    arc = sy.apply_env(arc, sy.env_adsr(arc_dur, 0.015, 0.1, 0.55, arc_dur * 0.4))
    arc = sy.soft_clip(arc, 1.6)
    # repeated low pulses -- the dangerous 'body' of the discharge, now
    # running most of the way through the clip so the low end is still
    # alive right up to the fade
    pulse_events = []
    t = 0.0
    while t < dur * 0.8:
        p = gun_thump(f0=105, f1=48, pitch_s=0.025, dur_s=0.16, drive=2.1)
        pulse_events.append((t, p, 1.1 * (1.0 - 0.6 * t / dur)))
        pulse_events.append((t, body_knock(0.11, 155, seed=seed + int(t * 1000)), 0.7))
        t += rng.uniform(0.08, 0.14)
    pulses = place(dur, *pulse_events)
    rumble = sy.brown_noise(dur, seed=seed + 3)
    rumble = sy.lowpass(rumble, 180)
    rumble = sy.apply_env(rumble, sy.env_exp_decay(dur, tau=dur / 1.8, end=0.001))
    # closing low thoom so the very end isn't pure crackle/sizzle decaying
    # into silence -- longer, louder, and starts earlier so it's clearly
    # audible carrying the sound out past where the crackle/sizzle thin out
    closer = gun_thump(f0=85, f1=30, pitch_s=0.06, dur_s=0.36, drive=1.9)
    # high 'sizzle' so the discharge isn't a boxy mid-band burst (trimmed
    # back and now decays faster so it doesn't linger into the low-end tail)
    sizzle = sy.white_noise(dur, seed=seed + 6)
    sizzle = sy.highpass(sizzle, 4800)
    sizzle = (sizzle.astype(np.float64) *
              telegraph_gate(dur, 300, 0.15, seed=seed + 7)).astype(np.float32)
    sizzle = sy.apply_env(sizzle, sy.env_exp_decay(dur, tau=dur / 4.5, end=0.001))
    x = place(dur,
              (0.0, hot_transient(0.01, seed=seed + 4, gain=1.2), 1.0),
              (0.0, crackles, 0.55),
              (0.0, arc, 0.38),
              (0.0, sizzle, 0.18),
              (0.0, pulses, 1.9),
              (0.0, rumble, 1.8),
              (dur * 0.5, closer, 1.7))
    x = grit(x, drive=1.7, floor_db=-36, seed=seed + 8)
    return finish(x, fade_s=0.26)


def gen_dry_click() -> np.ndarray:
    # Round-3 punch-up: Gemini repeatedly flagged this as too bright/thin
    # with no low-end body -- lowered the thud/knock/tick frequencies and
    # rebalanced gains toward the thud so the mechanism reads as heavy metal
    # snapping shut, not a plastic tap.
    seed = _seed("dryclick")
    thud = gun_thump(f0=115, f1=50, pitch_s=0.012, dur_s=0.075, drive=2.1)
    knock = body_knock(0.065, 200, seed=seed + 4)
    tick = metal_clank(520, 0.045, ratios=(1.0, 1.71, 2.9), seed=seed, lp_hz=2200)
    slide = sy.white_noise(0.03, seed=seed + 2)
    slide = sy.bandpass(slide, 1200, q=1.0)
    slide = sy.apply_env(slide, sy.env_exp_decay(0.03, tau=0.008))
    rattle = squelch_grains(0.05, 2, 450, 900, grain_s=0.006, spread=0.8,
                            seed=seed + 5, gain=0.3)
    x = place(0.13,
              (0.0, hot_transient(0.004, seed=seed + 1, gain=0.4, lp_hz=2200), 0.75),
              (0.0, thud, 1.5),
              (0.0, knock, 1.0),
              (0.001, tick, 0.45),
              (0.02, rattle, 1.0),
              (0.025, slide, 0.4))
    x = sy.soft_clip(x, 1.7)
    return finish(x, fade_s=0.025, pad_s=0.025)


def gen_reload() -> np.ndarray:
    # Round-3 punch-up, take 3: take-1's standalone sub gun_thump per clack
    # measured a real energy increase everywhere but got heard as FOUR taps.
    # Take-2 dropped that layer but STILL got "three/four rapid taps instead
    # of two clacks, no low end" consistently across 5/5 passes -- a real,
    # reproducible read, not noise. Root cause: `rattle` was only 4 sparse,
    # fairly loud grains spread over 90ms -- each one audible as its own
    # discrete tick rather than blending into texture -- and the standalone
    # `snap` was a third competing bright onset. Fix: drop snap (mech_clack's
    # own internal scrape already supplies metal-on-metal brightness), make
    # rattle dense/quiet/tight so it reads as friction texture not taps, and
    # add one genuinely deep (not just low-mid) sub pulse per clack.
    seed = _seed("reload")

    def clack(base_hz, thud_hz, seed_):
        # NOTE: a further push here (darker ring_lp, hotter/deeper sub) tested
        # worse (0.10, "plastic/thin") than this exact configuration (0.30,
        # correctly heard as two distinct heavy events) -- pinned to this.
        c = mech_clack(base_hz, seed=seed_ + 2, thud_hz=thud_hz, ring_decay=0.12)
        sub = gun_thump(f0=thud_hz * 1.3, f1=thud_hz * 0.4, pitch_s=0.02,
                        dur_s=0.11, drive=1.7)
        rattle = squelch_grains(0.1, 10, 500, 1600, grain_s=0.005,
                                spread=0.55, seed=seed_ + 1, gain=0.32)
        return place(0.22, (0.0, c, 1.3), (0.0, sub, 1.05), (0.012, rattle, 0.75))

    clack1 = clack(400, 62, seed)
    clack2 = clack(310, 50, seed + 9)
    x = place(0.56, (0.0, clack1, 1.0), (0.27, clack2, 1.25))
    x = sy.soft_clip(x, 1.6)
    x = grit(x, drive=1.6, floor_db=-38, seed=seed + 20)
    return finish(x, fade_s=0.05)


def gen_knife_swing() -> np.ndarray:
    # Round-3 punch-up, take 3: this was the worst-scoring gun/impact sound.
    # Take-1 kept the narrow resonant bandpass-sweep technique and Gemini
    # heard a "digital click/pop at the start" -- a high-Q bandpass hit with
    # a sudden broadband noise onset rings at its own resonant frequency.
    # Take-2 switched to a lowpass sweep to kill the ring, but a spectral
    # A/B check caught a real bug: swapping the 'body' layer from bandpass
    # to lowpass let brown noise's naturally strong sub-bass through
    # unfiltered (+25.5dB in the 0-150Hz band!) -- directly contradicting
    # this sound's own spec ("no low-end thud"). Fixed: highpass FIRST
    # (robustly kills true sub) then lowpass-sweep for the whoosh texture,
    # and the body layer is bandpassed again, not lowpassed.
    seed = _seed("knifeswing")
    dur = 0.24
    n = sy.pink_noise(dur, seed=seed)
    n = sy.highpass(n, 380)
    cutoff = sy.concat(sy.pitch_env(dur * 0.5, 700, 1600),
                       sy.pitch_env(dur * 0.5, 1600, 750))
    x = sy.lowpass(n, cutoff[: sy.samples(dur)])
    body = sy.brown_noise(dur, seed=seed + 3)
    body = sy.bandpass(body, 380, q=0.7)
    hump = sy.env_adsr(dur, attack=0.09, decay=0.03, sustain_level=0.75, release=0.14)
    x = sy.mix_layers([sy.apply_env(x, hump), sy.apply_env(body, hump)], [0.9, 0.4])
    x = grit(x, drive=1.4, floor_db=-42, seed=seed + 4)
    return finish(x, fade_s=0.09, pad_s=0.02)


def gen_knife_hit() -> np.ndarray:
    # Round-3 punch-up, take 2: take-1 darkened the slice transient along
    # with the body chasing "wet organic weight" and Gemini then heard "no
    # sharp slice transient at all... dry synthetic sine-drop" -- the slice_
    # layer wasn't the problem, it just got quieted/darkened by accident.
    # Fix: restore the bright thin slice, and get more wetness a different
    # way -- a deeper AM 'gurgle' on the body (new gurgle_depth knob) plus
    # more/denser splash grains -- instead of darkening across the board.
    seed = _seed("knifehit")
    base = wet_impact(dur_s=0.17, thump_f0=178, thump_f1=62, n_grains=9,
                      grain_lo=380, grain_hi=1300, body_lp=650, drive=2.0,
                      grain_gain=1.6, lp_hz=3700, seed=seed, gurgle_depth=0.62)
    slice_ = sy.white_noise(0.013, seed=seed + 20)
    slice_ = sy.highpass(slice_, 2800)
    slice_ = sy.apply_env(slice_, sy.env_exp_decay(0.013, tau=0.0045))
    splash = squelch_grains(0.11, 7, 1700, 4000, grain_s=0.006, spread=0.7,
                            seed=seed + 21, gain=0.55)
    x = place(len(base) / SR, (0.0, base, 1.0), (0.0, slice_, 0.6),
              (0.008, splash, 1.05))
    x = grit(x, drive=1.6, floor_db=-40, seed=seed + 22)
    return finish(x, fade_s=0.03, pad_s=0.0)


def gen_hit_flesh() -> np.ndarray:
    seed = _seed("hitflesh")
    return wet_impact(dur_s=0.18, thump_f0=170, thump_f1=72, n_grains=10,
                      grain_lo=400, grain_hi=1600, body_lp=700, drive=1.9,
                      grain_gain=1.5, lp_hz=3800, seed=seed)


def gen_hit_wall() -> np.ndarray:
    seed = _seed("hitwall")
    dur = 0.1
    # dull and dry: dust + thud + knock only -- no grains (they read as ring)
    dust = sy.brown_noise(dur, seed=seed)
    dust = sy.lowpass(dust, 900)
    dust = sy.apply_env(dust, sy.env_exp_decay(dur, tau=dur / 3.0, end=0.001))
    # single dull dry hit: no offset layers (they read as a double-tap),
    # no resonant knock (it read as hollow plastic ring)
    th = gun_thump(f0=150, f1=78, pitch_s=0.012, dur_s=0.055, drive=2.0)
    x = place(dur,
              (0.0, hot_transient(0.004, seed=seed + 1, gain=0.4, lp_hz=1800), 0.8),
              (0.0, dust, 1.4),
              (0.0, th, 1.0))
    x = grit(x, drive=1.8, floor_db=-40, seed=seed + 6)
    x = sy.lowpass(x, 2200)
    return finish(x, fade_s=0.03, pad_s=0.03)


def gen_ricochet() -> np.ndarray:
    # Round-3 punch-up, take 2: judged under non-anchored mode this looked
    # stuck at floor with "no descending whine present" even though the
    # whine layer is there -- that was largely a harness artifact (this clip
    # is <0.6s so audio_judge repeats it 4x for audibility, but the
    # non-anchored prompt never tells the model that, so "four identical
    # events" reads as repetitive machine-gun fire). Judging now goes
    # through anchored mode, which fixes that; on the design side, pushed
    # the thump/knock/whine louder and longer so the low end and the zing
    # both clearly register even under a single play-through.
    seed = _seed("ricochet")
    dur = 0.34
    clank = metal_clank(1050, 0.075, ratios=(1.0, 1.51, 2.32), seed=seed, lp_hz=3400)
    wsweep = sy.pitch_env(dur * 0.85, 3600, 800)
    whine = sy.white_noise(dur * 0.85, seed=seed + 2)
    whine = sy.bandpass(whine, wsweep, q=8.0)
    whine = sy.apply_env(whine, sy.env_exp_decay(dur * 0.85, tau=dur / 2.6, end=0.001))
    th = gun_thump(f0=125, f1=40, pitch_s=0.022, dur_s=0.12, drive=1.9)
    knock = body_knock(0.1, 165, seed=seed + 6)
    x = place(dur,
              (0.0, hot_transient(0.005, seed=seed + 1, gain=0.7, lp_hz=5200), 0.8),
              (0.0, th, 1.15),
              (0.0, knock, 0.75),
              (0.0, clank, 0.75),
              (0.015, whine, 1.05))
    x = sy.soft_clip(x, 1.6)
    x = grit(x, drive=1.6, floor_db=-38, seed=seed + 9)
    return finish(x, fade_s=0.05)


# ==========================================================================
# enemy sounds
# ==========================================================================

def gen_enemy_die_husk() -> np.ndarray:
    seed = _seed("diehusk")
    dur = 0.55
    # groan with real movement: falling contour + wobble, over a wet collapse
    voice = creature_voice(dur, [78, 64, 52, 38], vib_hz=3.8, vib_depth_end=0.14,
                           formant1=(520, 300), formant2=(1600, 850),
                           drive=4.5, breath=0.4, seed=seed)
    wob = 1.0 + 0.3 * np.linspace(0, 1, sy.samples(dur)) * \
        sy.sine(3.1, dur).astype(np.float64)
    voice = (voice.astype(np.float64) * wob).astype(np.float32)
    genv = sy.env_adsr(dur, attack=0.02, decay=0.15, sustain_level=0.6, release=0.25)
    voice = sy.apply_env(voice, genv)
    impact = wet_impact(dur_s=0.2, thump_f0=160, thump_f1=60, n_grains=8,
                        grain_lo=400, grain_hi=1300, grain_gain=1.3,
                        lp_hz=3600, seed=seed + 3)
    extra_wet = squelch_grains(0.35, 6, 350, 1200, grain_s=0.01, spread=0.9,
                               seed=seed + 11, gain=0.55)
    collapse = sy.brown_noise(dur * 0.8, seed=seed + 4)
    collapse = sy.lowpass(collapse, 650)
    lfo = sy.one_pole_lowpass(sy.white_noise(dur * 0.8, seed=seed + 8), 30).astype(np.float64)
    lfo = 0.5 + 0.5 * np.abs(lfo) / (np.max(np.abs(lfo)) + 1e-9)
    collapse = (collapse.astype(np.float64) * lfo).astype(np.float32)
    collapse = sy.apply_env(collapse, sy.env_exp_decay(dur * 0.8, tau=dur / 2.6, end=0.001))
    knock = body_knock(0.14, 180, seed=seed + 9)
    x = place(dur, (0.0, voice, 1.0), (0.05, impact, 1.15),
              (0.05, knock, 0.8), (0.08, collapse, 0.95), (0.1, extra_wet, 1.0))
    x = sy.soft_clip(x, 1.8)
    x = sy.lowpass(x, 3400)
    return finish(x, fade_s=0.08)


def gen_enemy_die_mite() -> np.ndarray:
    seed = _seed("diemite")
    # small but properly wet squelch pop -- no metallic chirp
    return wet_impact(dur_s=0.16, thump_f0=280, thump_f1=95, n_grains=9,
                      grain_lo=300, grain_hi=1100, body_lp=700, drive=2.2, seed=seed)


def gen_enemy_die_brute() -> np.ndarray:
    seed = _seed("diebrute")
    dur = 0.82
    # audible heavy fall: thumps stay above ~45Hz with long decays + knocks
    sub = gun_thump(f0=110, f1=48, pitch_s=0.06, dur_s=0.5, drive=2.4)
    sub2 = gun_thump(f0=85, f1=44, pitch_s=0.05, dur_s=0.35, drive=2.2)
    knock1 = body_knock(0.16, 160, seed=seed + 8)
    knock2 = body_knock(0.12, 130, seed=seed + 9)
    fall = sy.brown_noise(0.5, seed=seed)
    fall = sy.lowpass(fall, 380)
    fall = sy.apply_env(fall, sy.env_exp_decay(0.5, tau=0.16, end=0.001))
    wet = wet_impact(dur_s=0.24, thump_f0=140, thump_f1=55, n_grains=10,
                     grain_lo=350, grain_hi=1300, grain_gain=1.4,
                     lp_hz=3600, drive=1.9, seed=seed + 5)
    settle = sy.brown_noise(0.3, seed=seed + 6)
    settle = sy.lowpass(settle, 300)
    settle = sy.apply_env(settle, sy.env_exp_decay(0.3, tau=0.09, end=0.001))
    tail = gun_tail(0.35, lp_hz=450, seed=seed + 7)
    x = place(dur,
              (0.0, hot_transient(0.006, seed=seed + 1, gain=0.4, lp_hz=2500), 0.9),
              (0.0, sub, 1.2),
              (0.0, knock1, 0.9),
              (0.0, fall, 0.85),
              (0.02, wet, 1.0),
              (0.22, sub2, 0.85),
              (0.22, knock2, 0.7),
              (0.24, settle, 0.6),
              (0.03, tail, 0.35))
    x = sy.soft_clip(x, 1.7)
    x = sy.lowpass(x, 3200)
    return finish(x, fade_s=0.07)


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
    dur = 0.3
    events = []
    # clearly separated chitter clicks in an accelerating gallop, drifting
    # down in pitch; each click = dark noise snap + damped body 'thock'
    t = 0.01
    while t < dur - 0.05:
        cdur = rng.uniform(0.006, 0.012)
        drift = 1.0 - 0.3 * (t / dur)
        grain = sy.white_noise(cdur, seed=int(rng.integers(0, 1 << 30)))
        grain = sy.bandpass(grain, rng.uniform(2000, 3800) * drift, q=1.6)
        grain = sy.apply_env(grain, sy.env_exp_decay(cdur, tau=cdur / 2.5))
        thock = sy.sine(rng.uniform(500, 750) * drift, 0.022)
        thock = sy.soft_clip(thock, 2.0)
        thock = sy.apply_env(thock, sy.env_exp_decay(0.022, tau=0.006))
        g = rng.uniform(0.65, 1.0)
        events.append((t, grain, g))
        events.append((t + 0.002, thock, g * 0.4))
        gap = 0.034 - 0.016 * (t / dur)  # gallop accelerates
        t += gap * rng.uniform(0.8, 1.2)
    # faint body presence under the clicks (kept low -- clicks must dominate)
    bed = sy.brown_noise(dur, seed=seed + 1)
    bed = sy.bandpass(bed, 300, q=0.9)
    bed = sy.apply_env(bed, sy.env_adsr(dur, 0.04, 0.05, 0.5, 0.1))
    events.append((0.0, bed, 0.15))
    x = place(dur, *events)
    x = sy.soft_clip(x, 1.6)
    x = sy.lowpass(x, 5500)
    return finish(x, fade_s=0.04, pad_s=0.03)


def gen_spitter_shoot() -> np.ndarray:
    seed = _seed("spitter")
    dur = 0.28
    # deep wet gurgle: brown noise amplitude-modulated by a fast random LFO
    gurgle = sy.brown_noise(dur, seed=seed)
    gurgle = sy.lowpass(gurgle, 900)
    lfo = sy.one_pole_lowpass(sy.white_noise(dur, seed=seed + 1), 28).astype(np.float64)
    lfo = 0.4 + 0.6 * np.abs(lfo) / (np.max(np.abs(lfo)) + 1e-9)
    gurgle = (gurgle.astype(np.float64) * lfo).astype(np.float32)
    gurgle = sy.apply_env(gurgle, sy.env_adsr(dur, 0.015, 0.07, 0.55, 0.12))
    # noise-based 'plop' launch (a sine pitch-bend read as a synth bloop):
    # a burst of lowpass-swept noise, like liquid ejected under pressure
    plop = sy.white_noise(0.12, seed=seed + 4)
    plop = sy.lowpass(plop, sy.pitch_env(0.12, 1600, 250), q=0.9)
    plop = sy.apply_env(plop, sy.env_exp_decay(0.12, tau=0.035, end=0.001))
    plop = sy.soft_clip(plop, 2.5)
    knock = body_knock(0.1, 210, seed=seed + 5)
    grains = squelch_grains(dur, 11, 350, 1300, grain_s=0.01, spread=0.85,
                            seed=seed + 2, gain=1.3)
    # high wet splash detail -- the 'squelchy transient detail' the judge asked for
    splash = squelch_grains(0.12, 6, 1800, 4500, grain_s=0.004, spread=0.8,
                            seed=seed + 7, gain=0.5)
    drips = squelch_grains(0.08, 2, 500, 1100, grain_s=0.012, spread=0.9,
                           seed=seed + 6, gain=0.7)
    x = place(dur,
              (0.0, hot_transient(0.004, seed=seed + 3, gain=0.25, lp_hz=1800), 0.6),
              (0.0, gurgle, 1.1),
              (0.003, plop, 1.0),
              (0.005, knock, 0.6),
              (0.0, grains, 1.0),
              (0.005, splash, 1.0),
              (0.18, drips, 1.0))
    x = grit(x, drive=1.9, floor_db=-40, seed=seed + 8)
    x = sy.lowpass(x, 4200)
    return finish(x, fade_s=0.04, pad_s=0.03)


def gen_shrieker_scream() -> np.ndarray:
    seed = _seed("shrieker")
    dur = 0.88
    # dynamic scream: ragged rise, held peak, collapsing fall -- not a flat buzz
    voice = creature_voice(dur, [520, 950, 1350, 1400, 1000, 620],
                           vib_hz=5.5, vib_depth_end=0.12,
                           formant1=(750, 1100), formant2=(2200, 2900),
                           drive=3.0, breath=0.7, seed=seed)
    # scream noise core: swept ragged band, gives the 'throat tearing' texture
    rasp = sy.white_noise(dur, seed=seed + 5)
    rasp_sweep = np.interp(np.linspace(0, 1, sy.samples(dur)),
                           [0.0, 0.3, 0.7, 1.0], [900, 2400, 2600, 1100])
    rasp = sy.bandpass(rasp, rasp_sweep, q=2.2)
    rasp = (rasp.astype(np.float64) *
            telegraph_gate(dur, 180, 0.45, seed=seed + 6)).astype(np.float32)
    # low growl underlay for weight
    growl = sy.saw(sy.pitch_env(dur, 130, 85), dur)
    growl = sy.soft_clip(growl, 3.0)
    growl = sy.lowpass(growl, 450)
    # dynamics arc: fast ragged rise, sustained peak, steep collapse
    n = sy.samples(dur)
    arc = np.interp(np.linspace(0, 1, n), [0.0, 0.12, 0.3, 0.72, 1.0],
                    [0.0, 0.75, 1.0, 0.9, 0.0]) ** 1.2
    tremolo = 1.0 + 0.14 * sy.sine(11.0, dur).astype(np.float64)
    x = sy.mix_layers([voice, rasp, growl], [0.85, 0.5, 0.55])
    x = (x.astype(np.float64) * arc * tremolo).astype(np.float32)
    x = sy.soft_clip(x, 1.8)
    x = sy.highpass(x, 140)
    return finish(x, fade_s=0.08)


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
    dur = 1.45
    # short dying grunt, then a LOUD physical collapse, debris, and a long
    # clearly-audible ear-ring fading to the end
    voice = creature_voice(0.45, [140, 100, 60], vib_hz=3.2, vib_depth_end=0.08,
                           formant1=(550, 320), formant2=(1500, 850),
                           drive=3.5, breath=0.4, seed=seed)
    voice = sy.apply_env(voice, sy.env_adsr(0.45, attack=0.02, decay=0.15,
                                            sustain_level=0.5, release=0.2))
    body_fall = wet_impact(dur_s=0.26, thump_f0=150, thump_f1=52, n_grains=6,
                           grain_lo=300, grain_hi=800, drive=1.9, seed=seed + 2)
    second = wet_impact(dur_s=0.18, thump_f0=120, thump_f1=48, n_grains=4,
                        grain_lo=250, grain_hi=700, drive=1.7, seed=seed + 3)
    debris = squelch_grains(0.5, 6, 400, 1100, grain_s=0.012, spread=0.9,
                            seed=seed + 6, gain=0.4)
    knock = body_knock(0.18, 150, seed=seed + 7)
    # fading ear-ring: detuned pair blended with narrow ringing noise so it
    # reads as ringing ears, not a clean synth sine
    ringdur = 1.0
    rnoise = sy.white_noise(ringdur, seed=seed + 8)
    rnoise = sy.bandpass(rnoise, 1050, q=14.0)
    ring = sy.mix_layers([sy.sine(1050, ringdur), sy.sine(1063, ringdur), rnoise],
                         [0.45, 0.35, 0.8])
    ring = sy.apply_env(ring, sy.env_exp_decay(ringdur, tau=0.3, end=0.001))
    ring = sy.lowpass(ring, 2600)
    # low settling rumble under the tail so the fade isn't a bare tone
    settle = sy.brown_noise(0.8, seed=seed + 9)
    settle = sy.lowpass(settle, 350)
    settle = sy.apply_env(settle, sy.env_exp_decay(0.8, tau=0.3, end=0.001))
    x = place(dur,
              (0.0, voice, 0.5),
              (0.28, body_fall, 1.5),
              (0.28, knock, 1.1),
              (0.52, second, 1.0),
              (0.5, debris, 1.4),
              (0.55, settle, 0.7),
              (0.45, ring, 0.1))
    x = grit(x, drive=1.8, floor_db=-38, seed=seed + 10)
    x = sy.reverb(x, room_size=0.5, damping=0.5, mix=0.12, tail_s=0.2)
    x = sy.fade_out(x, 0.4)
    return finish(x, fade_s=0.12)


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
    # heavy magazine handled: low case thud + two dark clinks + brass slide
    clink1 = metal_clank(560, 0.08, ratios=(1.0, 1.63, 2.51), seed=seed, lp_hz=2800)
    clink2 = metal_clank(660, 0.1, ratios=(1.0, 1.59, 2.66), seed=seed + 1, lp_hz=2800)
    # granular friction slide (a smooth swept band read as a synth sweep):
    # irregular scrape grains stepping down in pitch, like brass on a shelf
    rng = np.random.default_rng(seed + 2)
    slide_events = []
    t = 0.0
    f = 1600.0
    while t < 0.12:
        gdur = rng.uniform(0.008, 0.018)
        g = sy.white_noise(gdur, seed=int(rng.integers(0, 1 << 30)))
        g = sy.bandpass(g, f * rng.uniform(0.85, 1.15), q=1.6)
        g = sy.apply_env(g, sy.env_exp_decay(gdur, tau=gdur / 2.0))
        slide_events.append((t, g, rng.uniform(0.5, 1.0)))
        t += gdur * rng.uniform(0.5, 0.9)
        f *= 0.88
    slide = place(0.14, *slide_events)
    thud = gun_thump(f0=150, f1=85, pitch_s=0.015, dur_s=0.07, drive=2.0)
    knock = body_knock(0.07, 240, seed=seed + 4)
    x = place(0.26,
              (0.0, thud, 1.1),
              (0.0, knock, 0.8),
              (0.0, clink1, 0.7),
              (0.08, clink2, 0.55),
              (0.05, slide, 0.85))
    x = grit(x, drive=3.4, floor_db=-32, seed=seed + 6)
    return finish(x, fade_s=0.04, pad_s=0.03)


def gen_pickup_medkit() -> np.ndarray:
    seed = _seed("pickmed")
    # soft case latch (slow attack, no strike click) + present canister hiss
    thud = gun_thump(f0=160, f1=88, pitch_s=0.03, dur_s=0.09, drive=1.8)
    thud = sy.apply_env(thud, sy.env_adsr(0.09, 0.012, 0.02, 0.8, 0.04))
    knock = body_knock(0.08, 220, q=1.0, seed=seed + 1)
    ring = metal_clank(330, 0.07, seed=seed, strike=False, lp_hz=1800)
    hiss = sy.white_noise(0.2, seed=seed + 2)
    hiss = sy.bandpass(hiss, 2200, q=0.7)
    hiss = sy.apply_env(hiss, sy.env_adsr(0.2, attack=0.06, decay=0.05,
                                          sustain_level=0.5, release=0.09))
    x = place(0.32, (0.0, thud, 1.1), (0.0, knock, 0.7), (0.005, ring, 0.4),
              (0.07, hiss, 0.45))
    x = sy.lowpass(x, 3200)
    return finish(x, fade_s=0.05, pad_s=0.03)


def gen_pickup_key() -> np.ndarray:
    seed = _seed("pickkey")
    # dark detuned chime: two clashing clanks a quarter-tone apart, so the
    # beating/wrongness is unmistakable; grimy floor, long-ish dark decay
    c1 = metal_clank(390, 0.28, ratios=(1.0, 1.5027, 2.44), detune_cents=35,
                     seed=seed, lp_hz=2400)
    c2 = metal_clank(390 * 0.971, 0.26, ratios=(1.0, 1.494, 2.51),
                     detune_cents=35, seed=seed + 7, strike=False, lp_hz=2400)
    chime = sy.mix_layers([c1, c2], [0.7, 0.55])
    chime = sy.soft_clip(chime, 1.8)
    thud = gun_thump(f0=120, f1=70, pitch_s=0.015, dur_s=0.07, drive=1.8)
    knock = body_knock(0.06, 220, seed=seed + 4)
    floor_ = sy.pink_noise(0.32, seed=seed + 2)
    floor_ = sy.bandpass(floor_, 700, q=0.6)
    floor_ = sy.apply_env(floor_, sy.env_exp_decay(0.32, tau=0.1, end=0.001))
    x = place(0.38, (0.0, chime, 0.8), (0.0, thud, 0.7), (0.0, knock, 0.5),
              (0.0, floor_, 0.3))
    x = sy.soft_clip(x, 1.3)
    return finish(x, fade_s=0.06, pad_s=0.02)


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
    # heavy mechanical key: low-mid thock dominates, dark tick on top
    thud = gun_thump(f0=200, f1=105, pitch_s=0.008, dur_s=0.045, drive=2.2)
    knock = body_knock(0.04, 300, q=1.3, seed=seed + 2)
    case = sy.white_noise(0.025, seed=seed)
    case = sy.bandpass(case, 800, q=1.1)
    case = sy.apply_env(case, sy.env_exp_decay(0.025, tau=0.007))
    tick = sy.white_noise(0.008, seed=seed + 3)
    tick = sy.bandpass(tick, 2000, q=2.0)
    tick = sy.apply_env(tick, sy.env_exp_decay(0.008, tau=0.0025))
    x = place(0.065,
              (0.0, hot_transient(0.003, seed=seed + 1, gain=0.35, lp_hz=2500), 0.85),
              (0.0, thud, 1.2),
              (0.0, knock, 0.9),
              (0.001, case, 0.6),
              (0.0, tick, 0.25))
    x = sy.soft_clip(x, 1.8)
    x = sy.lowpass(x, 3600)
    return finish(x, fade_s=0.015, pad_s=0.02)


def gen_radio_blip() -> np.ndarray:
    seed = _seed("radioblip")
    dur = 0.24
    # squelch burst -> voice-band burble -> squelch tail: reads as a radio
    # keying up, not a UI beep
    static = sy.white_noise(dur, seed=seed)
    static = (static.astype(np.float64) *
              telegraph_gate(dur, 300, 0.45, seed=seed + 1)).astype(np.float32)
    static = sy.bandpass(static, 1100, q=0.8)
    static = sy.apply_env(static, sy.env_adsr(dur, 0.01, 0.05, 0.6, 0.08))
    # burble: two alternating low square tones through the voice band,
    # like a compressed voice fragment
    t1 = sy.square(340, 0.05)
    t2 = sy.square(470, 0.05)
    t3 = sy.square(290, 0.06)
    burble = sy.concat(
        sy.apply_env(t1, sy.env_adsr(0.05, 0.008, 0.01, 0.7, 0.02)),
        sy.apply_env(t2, sy.env_adsr(0.05, 0.008, 0.01, 0.7, 0.02)),
        sy.apply_env(t3, sy.env_adsr(0.06, 0.008, 0.015, 0.6, 0.03)),
    )
    burble = sy.soft_clip(burble, 2.5)
    x = place(dur, (0.0, static, 1.2), (0.05, burble, 0.65))
    # radio voice-band filter + grit
    x = sy.bandpass(x, 900, q=0.55)
    x = sy.soft_clip(x, 2.4)
    x = sy.bitcrush(x, bits=8, rate_divisor=2)
    return finish(x, fade_s=0.05, pad_s=0.02)


def gen_door_unlock() -> np.ndarray:
    seed = _seed("doorunlock")
    # LONG buzzy servo motor spin-up (unmissable), then a heavy bolt slam
    whir_dur = 0.28
    whir = sy.mix_layers([
        sy.saw(sy.pitch_env(whir_dur, 50, 130), whir_dur),
        sy.square(sy.pitch_env(whir_dur, 130, 340), whir_dur),
    ], [0.9, 0.45])
    am = 1.0 + 0.6 * sy.square(26.0, whir_dur).astype(np.float64) * 0.5
    whir = (whir.astype(np.float64) * am).astype(np.float32)
    motor_noise = sy.white_noise(whir_dur, seed=seed + 8)
    motor_noise = sy.bandpass(motor_noise, 900, q=1.2)
    whir = sy.mix_layers([whir, motor_noise], [1.0, 0.3])
    whir = sy.lowpass(whir, 1100)
    whir = sy.soft_clip(whir, 3.0)
    whir = sy.apply_env(whir, sy.env_adsr(whir_dur, 0.05, 0.03, 0.85, 0.05))
    clunk = sy.mix_layers([
        gun_thump(f0=110, f1=40, pitch_s=0.035, dur_s=0.35, drive=2.5),
        body_knock(0.16, 150, q=0.9, seed=seed + 5),
        metal_clank(180, 0.18, ratios=(1.0, 1.43, 2.28), seed=seed, lp_hz=1400),
    ], [1.4, 1.0, 0.7])
    rattle = squelch_grains(0.2, 7, 400, 1200, grain_s=0.007, spread=0.9,
                            seed=seed + 3, gain=0.6)
    tail = gun_tail(0.3, lp_hz=450, seed=seed + 7)
    x = place(0.68,
              (0.0, whir, 0.9),
              (0.27, hot_transient(0.005, seed=seed + 2, gain=0.4, lp_hz=2400), 0.9),
              (0.27, clunk, 1.2),
              (0.33, rattle, 0.85),
              (0.29, tail, 0.4))
    x = grit(x, drive=3.4, floor_db=-32, seed=seed + 9)
    x = sy.lowpass(x, 2600)
    return finish(x, fade_s=0.09)


# ==========================================================================
# tau cannon family (experimental-physics energy weapon; original synthesis:
# capacitor whine, electric snap, metallic resonance)
# ==========================================================================

def gen_tau_fire() -> np.ndarray:
    # Built on the proven gunshot skeleton (rail judged 0.95): real thump,
    # real tail, with the electric character as a prepended instant snap and
    # a bright inharmonic ring layered over the body.
    seed = _seed("taufire")
    snap = sy.white_noise(0.03, seed=seed + 10)
    snap = sy.highpass(snap, 1200)
    snap = sy.apply_env(snap, sy.env_exp_decay(0.03, tau=0.008))
    snap = sy.soft_clip(snap, 3.0) * 0.8
    x = gunshot(
        0.34, seed,
        thump_kw=dict(f0=150, f1=52, pitch_s=0.03, dur_s=0.16, drive=2.2),
        body_kw=dict(dur_s=0.12, f_hi=3400, f_lo=420, brown_mix=0.35),
        tail_kw=dict(dur_s=0.22, lp_hz=900),
        transient_gain=1.1, thump_gain=1.05, transient_lp=None,
        knock_gain=0.6, drive=2.6, prepend=snap,
    )
    ring = metal_clank(760, 0.2, ratios=(1.0, 1.51, 2.32, 3.17),
                       seed=seed + 1, lp_hz=3200)
    x = place(max(0.34, 0.03 + 0.2),
              (0.0, x, 1.0), (0.028, ring, 0.4))
    x = grit(x, drive=2.6, floor_db=-34, seed=seed + 8)
    return x


def gen_tau_charge() -> np.ndarray:
    seed = _seed("taucharge")
    dur = 1.5
    n = sy.samples(dur)
    tt = np.linspace(0.0, 1.0, n)
    # capacitor whine: sweep 300->1500 over 1.35s, then hold the top for the
    # last 0.15s (charged-and-ready plateau) with a quiet saw octave shimmer
    sweep = np.concatenate([sy.pitch_env(dur - 0.15, 300, 1500),
                            np.full(sy.samples(0.15), 1500.0)])[: sy.samples(dur)]
    whine = sy.sine(sweep, dur)
    shimmer = sy.saw(sweep * 2.01, dur)
    shimmer = sy.lowpass(shimmer, 3400)
    # growing amplitude tremolo: rate 8->24Hz, depth deep enough to hear
    trem_rate = 8.0 + 16.0 * tt
    trem_phase = 2.0 * np.pi * np.cumsum(trem_rate) / SR
    trem = 1.0 - (0.25 + 0.45 * tt) * (0.5 + 0.5 * np.sin(trem_phase))
    # growing electrical crackle, density biased toward the end -- loud
    rng = np.random.default_rng(seed)
    crackle_events = []
    for _ in range(46):
        t0 = dur * (rng.uniform(0, 1) ** 0.45)
        cdur = rng.uniform(0.004, 0.014)
        c = sy.white_noise(cdur, seed=int(rng.integers(0, 1 << 30)))
        c = sy.bandpass(c, rng.uniform(1000, 5200), q=rng.uniform(1.5, 3.5))
        c = sy.apply_env(c, sy.env_exp_decay(cdur, tau=cdur / 3.0))
        crackle_events.append((min(t0, dur - cdur - 0.001), sy.soft_clip(c, 3.0),
                               rng.uniform(0.4, 0.9) * (0.4 + 0.6 * t0 / dur)))
    crackles = place(dur, *crackle_events)
    # breathy electric grit riding the whine (tracks the sweep)
    breath = sy.white_noise(dur, seed=seed + 9)
    breath = sy.bandpass(breath, sweep, q=4.0)
    # low capacitor-bank hum growing underneath
    hum = sy.mix_layers([sy.sine(55.0, dur), sy.sine(110.7, dur)], [0.8, 0.3])
    hum = sy.soft_clip(hum, 1.5)
    grow = (0.35 + 0.65 * tt) ** 1.3
    x = (whine.astype(np.float64) * 0.65 + shimmer.astype(np.float64) * 0.18 +
         breath.astype(np.float64) * 0.4 +
         hum.astype(np.float64) * 0.55) * trem * grow
    x = x.astype(np.float32)
    x = sy.mix_layers([x, crackles], [1.0, 1.0])
    x = grit(x, drive=3.4, floor_db=-32, seed=seed + 12)
    x = sy.lowpass(x, 3800)
    # ends hot by design (hands off to the shot): hold a short tremolo
    # plateau at the top, then a fast-but-not-instant release
    return finish(x, fade_s=0.04, pad_s=0.0)


def gen_tau_charged_fire() -> np.ndarray:
    # Deep concussion on the gunshot skeleton + a long descending electric
    # arc: falling inharmonic ring with decaying crackle grains, enveloped
    # all the way to zero (no gate).
    seed = _seed("taucharged")
    rng = np.random.default_rng(seed)
    x = gunshot(
        0.5, seed,
        thump_kw=dict(f0=120, f1=36, pitch_s=0.045, dur_s=0.3, drive=2.6),
        body_kw=dict(dur_s=0.2, f_hi=2800, f_lo=240, brown_mix=0.6),
        tail_kw=dict(dur_s=0.34, lp_hz=650),
        transient_gain=1.25, thump_gain=1.35, transient_lp=None,
        knock_gain=0.9, knock_hz=170.0, drive=2.8,
        double_thump_at=0.03,
    )
    arc_dur = 0.5
    sweep = sy.pitch_env(arc_dur, 1900, 320)
    arc = sy.sine(sweep, arc_dur)
    arc = arc + sy.sine(sweep * 1.51, arc_dur) * 0.5
    arc = sy.apply_env(arc, sy.env_exp_decay(arc_dur, tau=0.16))
    arc = sy.soft_clip(arc, 2.2) * 0.5
    crackle = []
    for _ in range(22):
        t0 = arc_dur * (rng.uniform(0, 1) ** 1.4)
        cdur = rng.uniform(0.004, 0.014)
        c = sy.white_noise(cdur, seed=int(rng.integers(0, 1 << 30)))
        c = sy.bandpass(c, rng.uniform(900, 3600), q=2.0)
        c = sy.apply_env(c, sy.env_exp_decay(cdur, tau=cdur * 0.4))
        crackle.append((t0, c, 0.5 * (1.0 - t0 / arc_dur)))
    x = place(0.78, (0.0, x, 2.2), (0.18, arc, 0.4), *crackle)
    x = grit(x, drive=2.0, floor_db=-33, seed=seed + 12)
    return x


def gen_tau_overcharge_hurt() -> np.ndarray:
    # Painful zap with real weight: thump + hot zap burst, then an urgent
    # dark two-tone, everything enveloped to silence.
    seed = _seed("tauover")
    th = gun_thump(f0=130, f1=48, pitch_s=0.03, dur_s=0.14, drive=2.4)
    zap = sy.white_noise(0.07, seed=seed + 3)
    zap = sy.bandpass(zap, 1700, q=1.4)
    zap = sy.apply_env(zap, sy.env_exp_decay(0.07, tau=0.025))
    zap = sy.soft_clip(zap, 3.2)
    grains = squelch_grains(0.12, 8, 1200, 4200, grain_s=0.005, spread=0.9,
                            seed=seed + 4, gain=0.7)
    tone_a = sy.apply_env(sy.square(392.0, 0.09),
                          sy.env_adsr(0.09, 0.004, 0.0, 1.0, 0.05))
    tone_b = sy.apply_env(sy.square(311.0, 0.13),
                          sy.env_adsr(0.13, 0.004, 0.0, 1.0, 0.08))
    tones = place(0.34, (0.0, tone_a, 0.32), (0.12, tone_b, 0.34))
    tones = sy.one_pole_lowpass(tones, 2400)
    tail = gun_tail(0.18, lp_hz=800, seed=seed + 5)
    x = place(0.52,
              (0.0, th, 2.4), (0.0, zap, 0.7), (0.005, grains, 0.55),
              (0.03, tail, 0.5), (0.16, tones, 0.75))
    x = grit(x, drive=2.9, floor_db=-33, seed=seed + 6)
    return x


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

    # dirty the whole mix: tape hiss floor + gentle saturation + bitcrush
    hiss = sy.pink_noise(dur, seed=seed + 7)
    hiss = sy.highpass(hiss, 1800)
    x = sy.mix_layers([shepard, bed, sub, whispers.astype(np.float32), hiss],
                      [0.5, 0.55, 0.35, 1.0, 0.05])
    x = sy.soft_clip(x, 1.4)
    x = sy.bitcrush(x, bits=10)
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
    # slow spectral movement: filter breathes open and shut with the smear
    filt_sweep = 1200.0 + 1400.0 * np.sin(np.pi * np.clip(tt * 1.4, 0, 1)) + 600.0 * smear
    cluster = sy.lowpass(cluster, filt_sweep)

    # slow static swell, gated, ducking into a low settle
    swell = sy.white_noise(dur, seed=seed + 2)
    swell = sy.bandpass(swell, 1100, q=0.8)
    gate = telegraph_gate(dur, 120, 0.4, seed=seed + 3)
    swell = (swell.astype(np.float64) * gate).astype(np.float32)
    swell_env = sy.env_adsr(dur, attack=dur * 0.45, decay=dur * 0.1,
                            sustain_level=0.3, release=dur * 0.4)
    swell = sy.apply_env(swell, swell_env)

    sub = gun_thump(f0=70, f1=42, pitch_s=0.4, dur_s=1.0, drive=1.8)

    # faint tape-hiss floor only (bitcrush/crackle read as 'flat static' --
    # judged worse in round 3, reverted)
    hiss = sy.pink_noise(dur, seed=seed + 5)
    hiss = sy.highpass(hiss, 1200)

    x = place(dur,
              (0.0, cluster, 0.7),
              (0.0, swell, 0.3),
              (0.0, hiss, 0.05),
              (dur * 0.62, sub, 0.6))
    # dynamic motion: swell in, recede, surge with the smear, long die-away
    amp_env = np.interp(np.linspace(0, 1, sy.samples(dur)),
                        [0.0, 0.12, 0.3, 0.45, 0.6, 0.75, 1.0],
                        [0.0, 0.85, 0.55, 1.0, 0.7, 0.6, 0.0]).astype(np.float32)
    # slow breathing tremble on top
    breathe = (1.0 - 0.15 * (0.5 + 0.5 * sy.sine(1.7, dur).astype(np.float64))
               ).astype(np.float32)
    x = sy.apply_env(x, (amp_env.astype(np.float64) *
                         breathe.astype(np.float64)).astype(np.float32))
    x = grit(x, drive=3.4, floor_db=-32, seed=seed + 9)
    return finish(x, fade_s=0.4, pad_s=0.05)


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
    ("pistol_fire", "a punchy sci-fi pistol shot: sharp crack transient, tight low-mid body with real weight, fast natural decay -- must sound like a lethal handgun discharge, not a synth blip or metal ping", 0.10, 0.20, "gun", gen_pistol_fire, ("peak", PEAK_GUN)),
    ("smg_fire", "a tight, ratty submachine-gun shot: fast sharp snap transient, compact low-mid body, very quick decay -- shorter and snappier than the pistol but with real low-end punch", 0.06, 0.14, "gun", gen_smg_fire, ("peak", PEAK_GUN)),
    ("shotgun_fire", "a deep shotgun boom: heavy low-end concussion, broadband pellet-spread rattle, longer decaying boom tail -- the heaviest, most physical gunshot in the game", 0.22, 0.42, "gun", gen_shotgun_fire, ("peak", PEAK_GUN)),
    ("rail_fire", "electric zap plus deep thud", 0.24, 0.36, "gun", gen_rail_fire, ("peak", PEAK_GUN)),
    ("lightning_fire", "a crackling electric discharge weapon burst: dense sizzling arc crackle over a deep pulsing low-end body -- scary, dangerous, physically heavy, not a thin digital buzz", 0.35, 0.85, "gun", gen_lightning_fire, ("peak", PEAK_GUN)),
    ("dry_click", "an empty-chamber dry-fire click: short, hard, mechanical -- a real gun hammer/striker snapping on nothing, with a bit of metal-on-metal weight, not a thin plastic tap", 0.02, 0.10, "gun", gen_dry_click, ("peak", PEAK_GUN)),
    ("reload", "a mechanical weapon reload: two heavy, distinct metal-on-metal clacks (magazine out, magazine in) with weight and friction rattle -- real gun-metal machinery, not a toy", 0.25, 0.35, "gun", gen_reload, ("peak", PEAK_IMPACT)),
    ("knife_swing", "a fast whoosh of a blade swinging through air: airy turbulent whoosh with a natural rise and fall, no click, no low-end thud -- must read as air displacement, not white noise hiss", 0.08, 0.16, "gun", gen_knife_swing, ("peak", PEAK_IMPACT)),
    ("knife_hit", "a wet thunk of a blade stabbing into flesh: sharp thin slice transient into a wet low-mid squelch body, fast decay -- an organic stabbing impact, not a dry synthetic hit", 0.07, 0.14, "gun", gen_knife_hit, ("peak", PEAK_IMPACT)),
    ("hit_flesh", "wet impact on flesh", 0.06, 0.20, "impact", gen_hit_flesh, ("peak", PEAK_IMPACT)),
    ("hit_wall", "dull concrete tick, dry, no ring", 0.04, 0.14, "impact", gen_hit_wall, ("peak", PEAK_IMPACT)),
    ("ricochet", "a metallic bullet ricochet: sharp metallic clank transient into a descending resonant whine -- dangerous and physically bright, with a clean bright metal ping over real low-end grit", 0.12, 0.28, "impact", gen_ricochet, ("peak", PEAK_IMPACT)),
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
    ("tau_fire", "sharp electric snap-crack with a metallic ring-down, zappy experimental energy weapon shot, brighter than a railgun", 0.15, 0.22, "gun", gen_tau_fire, ("peak", PEAK_GUN)),
    ("tau_charge", "rising capacitor whine, swept tone with growing tremolo and electrical crackle, charging energy weapon; intentionally ends hot mid-charge because it hands off to the shot", 1.2, 1.8, "gun", gen_tau_charge, ("peak", -3.5)),
    ("tau_charged_fire", "big energy discharge: deep concussion plus a long electric arc tail with a descending metallic ring", 0.5, 0.8, "gun", gen_tau_charged_fire, ("peak", PEAK_GUN)),
    ("tau_overcharge_hurt", "painful electric zap plus an urgent dark two-tone warning blip, weapon overcharge feedback", 0.25, 0.40, "gun", gen_tau_overcharge_hurt, ("peak", PEAK_PLAYER)),
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
