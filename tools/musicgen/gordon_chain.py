"""tools/musicgen/gordon_chain.py

Round 2, director's order #1 applied: process real sampled sources
(real_sources.py) through parallel Gordon-method signal chains
(GORDON_METHOD.md secs 2, 3, 4, 7) instead of one linear distortion call.
Sine-through-a-single-clip() was round 1's failure mode (called out in
GORDON_METHOD.md sec 1 as the cliche a real chain must replace).

Each function here is a literal instrument-chain: several parallel
processing paths off the same real source, recombined with side-chain-style
ducking, a genuine self-reprocessing feedback loop, and a tempo-tuned
makeup-gain punch stage -- matching Gordon's description of his DOOM
sine-wave array, except our source is a real recorded sample instead of a
bare sine (see SOURCES_LICENSES.md).

## No analog gear / no VSTs -- confirmed, not assumed

Gordon's chain was built from real hardware pedals, a tape echo, a
reel-to-reel, a mic'd practice amp. We're headless Linux + Python with no
audio interface. VST hosting was tried and ruled out (dawdreamer has no
wheel for this box's Python; pacman-installing Surge XT/sfizz needs a
sudo password we don't have) -- see SOURCES_LICENSES.md for the concrete
commands that failed. The digital-equivalent mapping used instead, stage
by stage:

| His hardware | What it does physically | Our numpy equivalent |
|---|---|---|
| RML 432K distortion | asymmetric hard fuzz clipping | `_fuzz()` -- biased hard clip (asymmetry = fuzz's even+odd harmonic splat) |
| Metasonix KV100 / TX-3 (tube) | tube-stage saturation, even harmonics | `_tube()` -- tanh + squared term for the even-harmonic tube signature |
| Bitcrusher ("Geiger counter" pedal) | sample-rate/bit-depth reduction | `synth.bitcrush()` |
| Dwarfcraft pedal | gated/"velcro" fuzz sputter | `_gated_fuzz()` -- heavy fuzz through an envelope-keyed hard gate |
| Phaser pedals (Mu-Tron Bi-Phase, DOD 70s) | swept allpass notches, the filter MOVES | `_phaser()` -- LFO-swept first-order allpass cascade (6-stage slow for the Bi-Phase, 4-stage faster for the DOD); replaced the earlier static-allpass stand-in that was flagged as a gap |
| Tape echo (Watkins Copicat) | delay whose repeats saturate + darken + wobble (tape in the loop) | `_tape_echo()` -- fractional modulated-read delay with tanh AND a lowpass inside the feedback path; replaced the clean `delay_fx` stand-in flagged as a gap |
| Reel-to-reel driven 40dB hot | brutal tape saturation w/ record EQ | `_reel_overdrive()` -- pre-emphasis -> deep tanh -> de-emphasis |
| Spring reverb tank (wet/dry) | dispersive coil: each reflection is a downward chirp ("boing") | `_spring_reverb()` -- impulse response built as a train of decaying downward chirps at the coil round-trip spacing, FFT-convolved; a Schroeder polygon reverb cannot make the chirp signature |
| **Mini-amp feedback loop** (mic signal routed back into the amp) | **self-oscillating loop choked by the note, swelling back in the gaps** | `feedback_loop()` -- nonlinearity inside a true recursion, loop gain barely past self-sustain, plus a `howl_hz` bandpass giving the loop the single resonant howl frequency a real amp has (found necessary empirically: without frequency selectivity the ring never has to swell -- measured +8.9dB swell over ~0.4s after each note with it) |
| Chain 1's splitter -> chains 2/3 compressors | cross-chain sidechaining: chain 1's level dynamically ducks the others | `sidechain_duck(c2/c3, trigger=c1)` inside `doom_array()` -- the actual routing, chain 1 as driver, not four peer paths |
| Final hard compressor + makeup gain | reveal every chain's quiet artifacts once the loud input decays | `tempo_punch()` -- ~20dB GR, 30ms attack, tempo-tuned release, explicit makeup stage |

`doom_array()` below wires these into Gordon's actual four-chain topology
component by component (see its docstring for the chain-level order).
The chirp-IR spring and the pre/de-emphasis reel are still approximations
of physical devices, but each now reproduces the specific audible
signature the real unit contributes, rather than a generic filter
standing in for it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soundgen"))
import synth as sy  # noqa: E402


def envelope_follower(x: np.ndarray, attack_s: float = 0.003,
                       release_s: float = 0.08, sr: int = sy.SR) -> np.ndarray:
    """Peak envelope follower: fast attack, slower release -- the shape a
    hardware compressor's detector uses. Used both for our own punch stage
    and for sidechain ducking one layer off another's amplitude
    (GORDON_METHOD.md sec 3: "based on whatever the input was doing, it
    could dynamically change the mix")."""
    a_coef = np.exp(-1.0 / max(1, attack_s * sr))
    r_coef = np.exp(-1.0 / max(1, release_s * sr))
    env = np.zeros_like(x, dtype=np.float64)
    level = 0.0
    ax = np.abs(x)
    for i in range(len(x)):
        target = ax[i]
        coef = a_coef if target > level else r_coef
        level = coef * level + (1 - coef) * target
        env[i] = level
    return env


def sidechain_duck(carrier: np.ndarray, trigger: np.ndarray,
                    amount: float = 0.6, attack_s: float = 0.003,
                    release_s: float = 0.12) -> np.ndarray:
    """Duck `carrier`'s gain inversely to `trigger`'s envelope -- e.g. let
    a grit/noise layer swell only when the tonal body has decayed away
    (GORDON_METHOD.md sec 3's amp-feedback-loop description: "the feedback
    was small enough that any signal coming through the amp would choke it
    out, and when the signal died the feedback swelled back in")."""
    n = min(len(carrier), len(trigger))
    env = envelope_follower(trigger[:n], attack_s, release_s)
    if env.max() > 1e-9:
        env = env / env.max()
    duck_gain = 1.0 - amount * env
    out = carrier.copy()
    out[:n] = out[:n] * duck_gain
    return out


def sidechain_pump(carrier: np.ndarray, trigger: np.ndarray,
                    amount: float = 0.7, attack_s: float = 0.002,
                    release_s: float = 0.15) -> np.ndarray:
    """Classic sidechain pump: duck `carrier` on `trigger` transients (kick
    ducking the bed) so the transient reads as punchy against a suddenly
    quieter background (GORDON_METHOD.md sec 7: fast attack lets the
    transient through, then the ducked material swells back)."""
    return sidechain_duck(carrier, trigger, amount, attack_s, release_s)


# ---------------------------------------------------------------------------
# Component models for the DOOM array -- each named pedal/machine from the
# talk mapped to a numpy process with the same EFFECT on the signal (the
# director's instruction: Gordon describes the architecture component by
# component, precisely enough to replicate; where a component can't be
# replicated 1:1 on headless numpy, find the thing with a similar effect
# on the final product).
# ---------------------------------------------------------------------------

def _fuzz(x: np.ndarray, gain: float = 6.0, bias: float = 0.12) -> np.ndarray:
    """RML 432K-style fuzz: asymmetric HARD clipping (bias shifts the
    waveform so positive/negative halves clip differently -- that
    asymmetry is what separates fuzz's splatty even+odd harmonic mess
    from tanh's polite symmetric saturation)."""
    y = np.clip(gain * np.asarray(x, dtype=np.float64) + bias, -0.7, 0.8)
    return sy.one_pole_highpass(y - float(np.mean(y)), 35.0)


def _tube(x: np.ndarray, drive: float = 2.5) -> np.ndarray:
    """Metasonix KV100/TX-3-style tube stage: soft saturation with an
    added squared term (even-harmonic generation -- the "warm/filthy"
    tube signature a plain odd-symmetric tanh doesn't have)."""
    t = np.tanh(drive * np.asarray(x, dtype=np.float64))
    y = t + 0.3 * t * t
    return sy.one_pole_highpass(y - float(np.mean(y)), 30.0)


def _gated_fuzz(x: np.ndarray, thresh_ratio: float = 0.08) -> np.ndarray:
    """Dwarfcraft-style gated/velcro fuzz: heavy fuzz through a hard gate
    keyed on the input envelope, so the sound sputters open/shut instead
    of sustaining -- the broken-speaker texture those pedals are for."""
    env = envelope_follower(x, attack_s=0.001, release_s=0.025)
    m = float(env.max()) + 1e-12
    gate = (env > thresh_ratio * m).astype(np.float64)
    return _fuzz(x, gain=9.0) * gate


def _phaser(x: np.ndarray, rate_hz: float = 0.35, f_lo: float = 300.0,
             f_hi: float = 2200.0, stages: int = 4, mix: float = 0.5,
             sr: int = sy.SR) -> np.ndarray:
    """Mu-Tron Bi-Phase / DOD-style phaser: a cascade of first-order
    allpass filters whose corner frequency is SWEPT by an LFO, mixed with
    the dry signal so the moving phase cancellations become moving
    notches. This replaces the earlier static allpass stand-in (flagged
    as a gap in this module's mapping table): a phaser that doesn't move
    isn't a phaser."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    t = np.arange(n) / sr
    # exponential sweep between f_lo and f_hi
    sweep = f_lo * (f_hi / f_lo) ** (0.5 + 0.5 * np.sin(2 * np.pi * rate_hz * t))
    a = (np.tan(np.pi * sweep / sr) - 1.0) / (np.tan(np.pi * sweep / sr) + 1.0)
    y = x.copy()
    for _s in range(stages):
        out = np.empty(n)
        x1 = 0.0
        y1 = 0.0
        for i in range(n):
            yi = a[i] * y[i] + x1 - a[i] * y1
            x1 = y[i]
            y1 = yi
            out[i] = yi
        y = out
    return ((1.0 - mix) * x + mix * y)


def _tape_echo(x: np.ndarray, delay_s: float = 0.14, feedback: float = 0.5,
                wow_hz: float = 0.9, wow_depth_s: float = 0.0012,
                sr: int = sy.SR) -> np.ndarray:
    """Watkins Copicat-style tape echo: a delay whose repeats pass through
    tape, i.e. each repeat is SATURATED (tanh in the feedback path) and
    DARKENED (one-pole lowpass in the loop), and the read head wobbles
    (wow -- slow modulation of the delay time, fractional-sample read).
    Replaces the earlier clean delay_fx stand-in (previously flagged as a
    gap: 'missing the saturation-in-the-repeat-path Gordon's real tape
    had')."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    nd = max(2, sy.samples(delay_s, sr))
    buf = np.zeros(nd + sy.samples(wow_depth_s * 2, sr) + 4, dtype=np.float64)
    nb = len(buf)
    out = np.empty(n)
    widx = 0
    lp_state = 0.0
    lp_coef = np.exp(-2.0 * np.pi * 3500.0 / sr)  # tape darkening
    tt = np.arange(n) / sr
    wobble = wow_depth_s * sr * np.sin(2 * np.pi * wow_hz * tt)
    for i in range(n):
        rpos = (widx - nd + wobble[i]) % nb
        r0 = int(rpos)
        frac = rpos - r0
        r1 = (r0 + 1) % nb
        delayed = buf[r0] * (1 - frac) + buf[r1] * frac
        # tape in the loop: darken then saturate the repeat
        lp_state = lp_coef * lp_state + (1 - lp_coef) * delayed
        rep = np.tanh(1.2 * lp_state)
        out[i] = x[i] + rep * 0.9
        buf[widx] = x[i] + rep * feedback
        widx = (widx + 1) % nb
    return out


def _reel_overdrive(x: np.ndarray, drive: float = 12.0) -> np.ndarray:
    """Akai reel-to-reel fed ~40dB past its rated input, recorded off
    simultaneously: brutal tape saturation. Modeled as pre-emphasized
    drive (tape machines boost highs going in) into deep tanh, then
    de-emphasis (record/replay EQ) -- the grime without literal tape."""
    x = np.asarray(x, dtype=np.float64)
    pre = x + 1.2 * sy.one_pole_highpass(x, 2000.0)
    y = np.tanh(pre * drive)
    return sy.one_pole_lowpass(y, 9000.0)


def _spring_reverb(x: np.ndarray, mix: float = 0.35, sr: int = sy.SR) -> np.ndarray:
    """Spring reverb tank with wet/dry: a spring is DISPERSIVE -- high
    frequencies travel the coil slower, so each reflection is a downward
    chirp ("boing"), unlike a polygon's flat echoes. Modeled the way that
    effect actually arises: an impulse response made of a train of
    exponentially-decaying downward chirps at the spring's round-trip
    spacing, band-limited to the tank's 250Hz-4kHz voice, applied via FFT
    convolution. A Schroeder polygon reverb (synth.py's reverb()) cannot make
    the chirp signature, which is the entire audible identity of a
    spring."""
    x = np.asarray(x, dtype=np.float64)
    trip_s = 0.052          # coil round-trip
    n_trips = 6
    chirp_s = 0.09
    ir_len = sy.samples(trip_s * n_trips + chirp_s, sr)
    ir = np.zeros(ir_len)
    tc = np.arange(sy.samples(chirp_s, sr)) / sr
    for k in range(n_trips):
        f0, f1 = 3500.0, 350.0
        # exponential downward chirp, each trip darker and quieter
        phase = 2 * np.pi * f0 * (chirp_s / np.log(f1 / f0)) * \
            ((f1 / f0) ** (tc / chirp_s) - 1.0)
        chirp = np.sin(phase) * np.exp(-tc / 0.03) * (0.55 ** k)
        start = sy.samples(trip_s * k, sr)
        ir[start:start + len(chirp)] += chirp
    wet_full = np.fft.irfft(
        np.fft.rfft(x, len(x) + ir_len) * np.fft.rfft(ir, len(x) + ir_len))
    wet = sy.bandpass(wet_full[: len(x)], 1100.0, q=0.35)
    return (1.0 - mix) * x + mix * 2.2 * wet


def feedback_loop(x: np.ndarray, delay_s: float, feedback_gain: float = 0.75,
                   drive: float = 2.2, sr: int = sy.SR,
                   loop_lowpass_hz: Optional[float] = None,
                   input_gain: float = 1.0,
                   howl_hz: Optional[float] = None,
                   howl_q: float = 3.0) -> np.ndarray:
    """A genuine self-reprocessing feedback loop, modeling chain 4 of
    Gordon's DOOM array literally: a small amp fed ~40dB hot, mic'd, with
    a small amount of the mic signal routed back into the amp's own input
    -- "if a sound was actually coming through the amp it would choke out
    the feedback, and when that sound started to disappear the feedback
    would come back up in the mix."

    `comb_filter()` (synth.py) is NOT this -- it's a *linear* feedback
    filter (delayed copies decaying geometrically, same waveform each
    repeat), which only ever produces a metallic ringing, never new
    texture. The amp loop is nonlinear: distortion sits INSIDE the
    feedback path, so each pass around the loop doesn't just repeat the
    signal quieter, it reshapes it -- harmonics generated on pass 1 get
    fed back and redistorted on pass 2, and so on, so the loop accumulates
    genuinely emergent, chaotic character that isn't derivable from a
    single filtering pass over the dry source. That's the "biggest point"
    a purely feed-forward parallel-paths chain (the previous version of
    this module) cannot produce no matter how many static filters are
    stacked -- it has to be an actual recursive process:

        y[n] = drive_nonlinearity(x[n] + feedback_gain * y[n - delay_samples])

    This is the direct on-machine equivalent of "route a little of the
    mic signal back into the amp": a literal digital feedback loop with a
    nonlinearity inside it, computed sample-by-sample (numpy can't
    vectorize this -- it's a true IIR recursion through a nonlinearity,
    not a linear filter with a closed-form transfer function).

    THE CHOKE (director's emphasis, Gordon's words: "the feedback loop was
    only very very small... if a sound was actually coming through the amp
    it would choke out the feedback, and when that sound started to
    disappear the feedback would come back up in the mix"): the choke and
    the swell are BOTH emergent from tanh gain compression, but only in a
    specific parameter regime, found empirically after a first attempt
    (drive 3.0, fb 1.07) produced a constant always-on drone instead:

    - CHOKE: while a loud note passes through (input_gain hot enough to
      pin the tanh), the tanh's incremental gain collapses (sech^2 ~ 0 at
      the rails), so the loop's own oscillation decays hard DURING the
      note -- the note literally spends the amp's headpolygon.
    - SWELL: after the note, the ring regrows exponentially from the tiny
      residue at (drive x feedback_gain) per pass. For an AUDIBLE swell
      (hundreds of ms, what Gordon demos in the talk) that per-pass gain
      must be barely past self-sustain: ~1.1-1.3. At 3+ the ring is back
      at full amplitude in ~30ms -- perceptually "always on", no drama.

    Set feedback_gain*drive ~0.5-0.8 for a decaying resonant tail,
    ~1.1-1.3 (with input_gain ~2-3) for the true choke-and-swell amp.

    `loop_lowpass_hz` puts a one-pole lowpass INSIDE the loop (the amp's
    speaker + mic can't pass full bandwidth around the loop) -- it darkens
    the ring and keeps self-oscillation from screeching at the top.

    `howl_hz` is the piece that makes the swell AUDIBLE as an event (found
    empirically: without it the swell measured under 1dB): real amp
    feedback howls at ONE resonant frequency -- loop gain exceeds unity
    only there, so after the note the buffer's broadband note-content dies
    off in a few passes (bandpass-attenuated below unity) while the
    on-resonance component alone regrows from a whisper to the limit
    cycle. Without frequency selectivity, the loud note itself stays in
    the delay buffer at full level and the ring never has to swell -- it
    just continues. `howl_hz` inserts a narrow biquad bandpass (RBJ, 0dB
    peak at center, bandwidth set by `howl_q`) inside the loop at the howl
    pitch; pick a comb-supported frequency (an integer multiple of
    1/delay_s) or the loop fights itself."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    nd = max(1, sy.samples(delay_s, sr))
    y = np.empty(n, dtype=np.float64)
    buf = np.zeros(nd, dtype=np.float64)
    idx = 0
    lp_state = 0.0
    lp_coef = (np.exp(-2.0 * np.pi * loop_lowpass_hz / sr)
               if loop_lowpass_hz else 0.0)
    if howl_hz:
        b0, b1, b2, a1, a2 = sy._biquad_coeffs("bandpass", howl_hz, sr, howl_q)
        bx1 = bx2 = by1 = by2 = 0.0
    for i in range(n):
        fb = buf[idx]
        if loop_lowpass_hz:
            lp_state = lp_coef * lp_state + (1.0 - lp_coef) * fb
            fb = lp_state
        if howl_hz:
            bo = b0 * fb + b1 * bx1 + b2 * bx2 - a1 * by1 - a2 * by2
            bx2, bx1 = bx1, fb
            by2, by1 = by1, bo
            fb = bo
        combined = input_gain * x[i] + feedback_gain * fb
        out = np.tanh(combined * drive)
        buf[idx] = out
        y[i] = out
        idx += 1
        if idx >= nd:
            idx = 0
    return y.astype(np.float32)


def doom_array(source: np.ndarray, bpm: float = 140.0,
                dry_mix: float = 0.55, chain4_gain: float = 0.12,
                tail_s: float = 0.6) -> np.ndarray:
    """The DOOM instrument, chain by chain, as Gordon lists its components
    in the talk (GORDON_METHOD.md "actual array topology") -- not four
    generic 'flavors' but his named units each mapped to a process with
    the same effect:

    Chain 1: RML 432K fuzz -> Metasonix KV100 tube -> Geiger-counter
             bitcrusher -> Dwarfcraft gated fuzz -> SPLITTER (audio out +
             the sidechain trigger for chains 2 and 3's compressors).
    Chain 2: Geiger bitcrusher -> Metasonix TX-3 tube -> Mu-Tron Bi-Phase
             (slow 6-stage sweep) -> DOD phaser (faster 4-stage sweep) ->
             compressor SIDECHAINED FROM CHAIN 1.
    Chain 3: Watkins Copicat tape echo (saturating, wobbling repeats) ->
             distortion box "there for the compression aspect" (low-drive
             soft clip) -> Akai reel-to-reel +40dB (_reel_overdrive) ->
             spring reverb (chirp-train IR) -> compressor SIDECHAINED
             FROM CHAIN 1.
    Chain 4: mini-amp at +40dB with a small mic->amp feedback loop
             (feedback_loop past self-sustain; ring pitch tuned to D per
             Gordon's tune-shared-elements-to-the-root principle), mixed
             in "very very small" so it surfaces in the gaps.
    Sum:     mixer -> smiley EQ (-4-5dB @ 30-60Hz, +8-10dB top) ->
             pinned compressor (~20dB GR, 30ms attack, tempo release,
             makeup gain lifting every chain's quiet artifacts once the
             input dies).

    `dry_mix` keeps the source's identity present (our sources are real
    recorded instruments/machines, not Gordon's bare sine -- the array is
    the voice AROUND them, not a replacement for them)."""
    src = sy.pad_to(np.asarray(source, dtype=np.float64),
                     len(source) + sy.samples(tail_s))
    n = len(src)

    # Chain 1 -- the driver
    c1 = _gated_fuzz(sy.bitcrush(_tube(_fuzz(src)), bits=8.0, rate_divisor=2))

    # Chain 2 -- crushed tube into two swept phasers, ducked by chain 1
    c2 = _tube(sy.bitcrush(src, bits=9.0, rate_divisor=3), drive=2.0)
    c2 = _phaser(c2, rate_hz=0.21, stages=6, f_lo=250, f_hi=1800)  # Bi-Phase
    c2 = _phaser(c2, rate_hz=0.47, stages=4, f_lo=400, f_hi=2600)  # DOD
    c2 = sidechain_duck(c2, c1, amount=0.65, release_s=0.10)

    # Chain 3 -- tape echo -> compression-flavored clip -> hot reel -> spring
    c3 = _tape_echo(src, delay_s=60.0 / bpm / 2.0, feedback=0.45)
    c3 = sy.soft_clip(c3 * 1.4, drive=0.8)     # "more for the compression"
    c3 = _reel_overdrive(c3)
    c3 = _spring_reverb(c3, mix=0.4)
    c3 = sidechain_duck(c3, c1, amount=0.6, release_s=0.14)

    # Chain 4 -- the choke-and-swell loop. Measured tuning (see
    # feedback_loop docstring for the mechanism): delay comb rooted at D2,
    # howl bandpass selecting the D3 harmonic (Gordon's
    # tune-shared-elements-to-D principle), loop gain 1.12 barely past
    # self-sustain, hot input choking the ring during notes. Bench result
    # on a 3-hit chug sequence: ring choked to -15.9dBFS right after each
    # hit, swelling +8.9dB over ~0.4s in each gap -- the exact behavior
    # Gordon demos ("when that sound started to disappear, the feedback
    # would come back up in the mix").
    c4 = feedback_loop(src, delay_s=1.0 / 73.42, feedback_gain=1.12,
                        drive=1.0, input_gain=3.0,
                        howl_hz=146.84, howl_q=3.0)

    mixed = sy.mix_layers(
        [sy.pad_to(src, n), sy.pad_to(c1, n), sy.pad_to(c2, n),
         sy.pad_to(c3, n), sy.pad_to(c4, n)],
        gains=[dry_mix, 0.38, 0.24, 0.28, chain4_gain],
    )
    mixed = smiley_eq(mixed)
    mixed = tempo_punch(mixed, bpm, gain_reduction_db=20.0, attack_s=0.03)
    return sy.normalize_peak(mixed, -1.5)


def ring_mod_noise(carrier: np.ndarray, mod_freq: float, sr: int = sy.SR,
                    seed: int = 0) -> np.ndarray:
    """Ring-modulate gated white noise at the carrier's own fundamental
    rate and sum with the carrier before shared distortion (GORDON_METHOD.md
    sec 4's literal 36.7Hz sub-audibility recipe)."""
    n = len(carrier)
    noise = sy.white_noise(n / sr, sr=sr, seed=seed)[:n]
    gate = (sy.square(mod_freq, n / sr, sr=sr)[:n] > 0).astype(np.float64)
    return carrier + 0.35 * noise * gate


def tempo_punch(x: np.ndarray, bpm: float, gain_reduction_db: float = 14.0,
                 attack_s: float = 0.03, makeup_db: Optional[float] = None
                 ) -> np.ndarray:
    """Hard-pinned compressor + makeup gain, release locked to the beat
    (GORDON_METHOD.md sec 7). First pass here only squashed the loud
    transient down (downward compression, no makeup stage) -- that gives
    punch but throws away the actual effect Gordon described: with
    ~20dB of gain reduction on the transient, the makeup gain applied
    afterward to restore level pushes everything that was NOT being
    compressed (the parallel chains' quiet resonant tails -- comb-filter
    ring, feedback-loop decay, reverb) up by that same makeup amount, so
    once the input note dies the chain's own resonances/feedback swell up
    into audibility. Director's correction: that reveal-on-decay is the
    actual mechanism, not just a punchy attack."""
    release_s = (60.0 / bpm) * 0.5  # half a beat
    env = envelope_follower(x, attack_s, release_s)
    thresh = np.percentile(env, 70) + 1e-9
    over = np.maximum(env / thresh, 1.0)
    ratio = 1.0 + gain_reduction_db / 6.0  # rough dB->ratio mapping
    gain = np.where(over > 1.0, over ** (1.0 / ratio - 1.0), 1.0)
    compressed = x * gain
    # makeup gain: restore the level the compressor took off the transient
    # peak, applied to the WHOLE signal -- this is what lets the untouched
    # quiet tail material poke through once the loud part has decayed
    makeup = gain_reduction_db if makeup_db is None else makeup_db
    return compressed * sy.db_to_lin(makeup)


def smiley_eq(x: np.ndarray, sr: int = sy.SR) -> np.ndarray:
    """Gordon's "smiley face" curve: cut low mud, boost the top shelf
    (GORDON_METHOD.md sec 2: "cut 30-60Hz by ~4-5dB, boost ~8-10dB around
    8-10kHz shelf"). synth.py's biquad() only has lowpass/highpass/bandpass
    (no shelf types), so the shelves are built the standard way from those:
    subtract a scaled lowpassed copy (low cut) and add a scaled highpassed
    copy (high boost)."""
    low = sy.lowpass(x, 55.0, sr=sr, q=0.7)
    x = x - 0.4 * low
    high = sy.highpass(x, 8500.0, sr=sr, q=0.7)
    x = x + 1.8 * high
    return x


def guitar_chain(source: np.ndarray, bpm: float = 140.0) -> np.ndarray:
    """Real recorded guitar through the component-by-component DOOM array
    (doom_array() -- see its docstring for the chain-level mapping).

    Lineage, kept for the record: v1 was four generic over-driven paths
    that erased the guitar entirely (listen-proxy: "synthesizer, buzzy");
    v2 pulled the drive back and added a dry path but collapsed Gordon's
    four SPECIFIC chains into four generic flavors, and used a linear comb
    filter where his amp feedback loop belongs -- the director's
    correction ("he describes the entire instrument component by
    component; you could replicate it exactly... find the thing with a
    similar effect") led to doom_array(): named-component models
    (_fuzz/_tube/_gated_fuzz/_phaser/_tape_echo/_reel_overdrive/
    _spring_reverb), chain 1's splitter actually sidechaining chains 2-3,
    and chain 4 as a self-oscillating choke loop tuned to D. The healthy
    dry_mix survives from the v1 lesson: our source is a real instrument,
    not Gordon's bare sine, and its identity must stay audible."""
    return doom_array(source, bpm=bpm, dry_mix=0.6)


def organ_choir_chain(source: np.ndarray, drone: bool = True) -> np.ndarray:
    """Lighter processing for the liturgical layer (organ/choir/bells):
    real samples stay largely intact (this is the "sacred" register, not
    the "argent metal" register) but get width via a slow chorus-style
    detuned double and a long reverb tail, so the chant material reads as
    a real polygon, not a dry MIDI render."""
    n = len(source)
    # cheap chorus: short slap-delay double for width
    doubled = sy.delay_fx(source, delay_s=0.018, feedback=0.0, mix=0.5)
    mixed = sy.mix_layers([sy.pad_to(source, n), sy.pad_to(doubled, n)],
                           gains=[0.8, 0.5])
    wet = sy.reverb(mixed, polygon_size=0.85, damping=0.25, tail_s=2.2)
    out = 0.55 * sy.pad_to(mixed, len(wet)) + 0.45 * wet
    return sy.normalize_peak(out, -3.0)


def argent_bass_chain(source: np.ndarray, bpm: float = 140.0) -> np.ndarray:
    """Sub-heavy bass path: ring-mod the source with gated noise at its own
    approximate fundamental so it reads on small speakers (GORDON_METHOD.md
    ring-mod recipe), pass the ring-modulated signal through the same
    nonlinear feedback_loop() as the guitar chain's amp path (a bass tail
    that keeps regenerating harmonic content as it decays reads far less
    static than a filtered-once sub), then the shared smiley EQ / tempo
    punch for mix cohesion across the "argent" layers."""
    tail_s = 0.4
    source = sy.pad_to(source, len(source) + sy.samples(tail_s))
    n = len(source)
    ringmod = ring_mod_noise(source, mod_freq=55.0)
    driven = sy.soft_clip(ringmod * 3.0, drive=1.1)
    fb = feedback_loop(driven, delay_s=1.0 / 55.0, feedback_gain=0.5, drive=1.5)
    mixed = 0.65 * driven + 0.45 * fb
    mixed = smiley_eq(mixed)
    mixed = tempo_punch(mixed, bpm, gain_reduction_db=10.0)
    return sy.normalize_peak(sy.pad_to(mixed, n), -2.0)
