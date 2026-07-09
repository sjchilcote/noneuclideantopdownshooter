"""tools/soundgen/synth.py

Small numpy-only DSP toolkit for procedurally synthesizing SFX/ambience.
No external audio dependencies -- pure numpy + the stdlib `wave` module.

All signals are 1-D numpy arrays (mono), nominal full-scale = +/-1.0,
sample rate SR unless otherwise specified. Everything here is meant for
*offline* (non-realtime) rendering, so filters etc. favour simplicity and
numerical robustness over CPU efficiency.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Iterable, Sequence, Union

import numpy as np

SR = 44100

ArrayOrScalar = Union[float, int, np.ndarray]


# --------------------------------------------------------------------------
# time / length helpers
# --------------------------------------------------------------------------

def samples(dur_s: float, sr: int = SR) -> int:
    """Number of samples for a duration in seconds (>=1)."""
    return max(1, int(round(dur_s * sr)))


def time_array(dur_s: float, sr: int = SR) -> np.ndarray:
    n = samples(dur_s, sr)
    return np.arange(n, dtype=np.float64) / sr


def _match_len(arr: np.ndarray, n: int) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float64)
    if len(arr) == n:
        return arr
    if len(arr) > n:
        return arr[:n]
    if len(arr) == 0:
        return np.zeros(n)
    return np.pad(arr, (0, n - len(arr)), mode="edge")


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def lin_to_db(lin: float) -> float:
    return float(20.0 * np.log10(max(abs(lin), 1e-12)))


# --------------------------------------------------------------------------
# oscillators
# --------------------------------------------------------------------------

def _freq_phase(freq: ArrayOrScalar, n: int, sr: int) -> np.ndarray:
    """Return an instantaneous-phase (radians, unwrapped) array of length n
    for a possibly time-varying frequency (Hz)."""
    if np.isscalar(freq):
        tt = np.arange(n, dtype=np.float64) / sr
        return 2.0 * np.pi * float(freq) * tt
    freq_arr = _match_len(np.asarray(freq, dtype=np.float64), n)
    return 2.0 * np.pi * np.cumsum(freq_arr) / sr


def sine(freq: ArrayOrScalar, dur_s: float, sr: int = SR, phase0: float = 0.0) -> np.ndarray:
    n = samples(dur_s, sr)
    ph = _freq_phase(freq, n, sr) + phase0
    return np.sin(ph).astype(np.float32)


def saw(freq: ArrayOrScalar, dur_s: float, sr: int = SR) -> np.ndarray:
    """Band-unlimited (naive) sawtooth, -1..1. Fine at these SFX durations/pitches."""
    n = samples(dur_s, sr)
    if np.isscalar(freq):
        freq_arr = np.full(n, float(freq))
    else:
        freq_arr = _match_len(np.asarray(freq, dtype=np.float64), n)
    phase = np.cumsum(freq_arr) / sr
    x = 2.0 * (phase - np.floor(phase + 0.5))
    return x.astype(np.float32)


def square(freq: ArrayOrScalar, dur_s: float, sr: int = SR, duty: float = 0.5) -> np.ndarray:
    n = samples(dur_s, sr)
    if np.isscalar(freq):
        freq_arr = np.full(n, float(freq))
    else:
        freq_arr = _match_len(np.asarray(freq, dtype=np.float64), n)
    phase = np.cumsum(freq_arr) / sr
    frac = phase - np.floor(phase)
    x = np.where(frac < duty, 1.0, -1.0)
    return x.astype(np.float32)


def triangle(freq: ArrayOrScalar, dur_s: float, sr: int = SR) -> np.ndarray:
    n = samples(dur_s, sr)
    if np.isscalar(freq):
        freq_arr = np.full(n, float(freq))
    else:
        freq_arr = _match_len(np.asarray(freq, dtype=np.float64), n)
    phase = np.cumsum(freq_arr) / sr
    frac = phase - np.floor(phase)
    tri = 4.0 * np.abs(frac - 0.5) - 1.0
    return tri.astype(np.float32)


def _colored_noise(n: int, sr: int, alpha: float, seed: Union[int, None] = None) -> np.ndarray:
    """Generate noise with power spectral density ~ 1/f^alpha via FFT spectral
    shaping of white gaussian noise. alpha=0 -> white, 1 -> pink, 2 -> brown/red."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    if alpha == 0.0:
        y = white
    else:
        spec = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
        freqs = freqs.copy()
        freqs[0] = freqs[1] if len(freqs) > 1 else 1.0
        scale = 1.0 / np.power(freqs, alpha / 2.0)
        scale[0] = 0.0
        spec *= scale
        y = np.fft.irfft(spec, n)
    peak = np.max(np.abs(y)) + 1e-12
    return (y / peak).astype(np.float32)


def white_noise(dur_s: float, sr: int = SR, seed: Union[int, None] = None) -> np.ndarray:
    return _colored_noise(samples(dur_s, sr), sr, alpha=0.0, seed=seed)


def pink_noise(dur_s: float, sr: int = SR, seed: Union[int, None] = None) -> np.ndarray:
    return _colored_noise(samples(dur_s, sr), sr, alpha=1.0, seed=seed)


def brown_noise(dur_s: float, sr: int = SR, seed: Union[int, None] = None) -> np.ndarray:
    return _colored_noise(samples(dur_s, sr), sr, alpha=2.0, seed=seed)


# --------------------------------------------------------------------------
# envelopes
# --------------------------------------------------------------------------

def env_exp_decay(dur_s: float, sr: int = SR, tau: Union[float, None] = None,
                   start: float = 1.0, end: float = 0.001) -> np.ndarray:
    """Exponential decay from `start` towards ~`end` over dur_s seconds."""
    n = samples(dur_s, sr)
    tt = np.arange(n, dtype=np.float64) / sr
    if tau is None:
        end = max(end, 1e-6)
        tau = -dur_s / np.log(end / max(start, 1e-9))
        tau = max(tau, 1e-4)
    return (start * np.exp(-tt / tau)).astype(np.float32)


def env_adsr(dur_s: float, attack: float, decay: float, sustain_level: float,
             release: float, sr: int = SR) -> np.ndarray:
    n_total = samples(dur_s, sr)
    n_a = min(samples(attack, sr) if attack > 0 else 0, n_total)
    n_d = min(samples(decay, sr) if decay > 0 else 0, max(0, n_total - n_a))
    n_r = min(samples(release, sr) if release > 0 else 0, max(0, n_total - n_a - n_d))
    n_s = max(0, n_total - n_a - n_d - n_r)

    segs = []
    if n_a > 0:
        segs.append(np.linspace(0.0, 1.0, n_a, endpoint=False))
    if n_d > 0:
        segs.append(np.linspace(1.0, sustain_level, n_d, endpoint=False))
    if n_s > 0:
        segs.append(np.full(n_s, sustain_level))
    if n_r > 0:
        segs.append(np.linspace(sustain_level, 0.0, n_r, endpoint=True))
    if not segs:
        return np.zeros(n_total, dtype=np.float32)
    env = np.concatenate(segs)
    if len(env) < n_total:
        env = np.pad(env, (0, n_total - len(env)))
    else:
        env = env[:n_total]
    return env.astype(np.float32)


def linear_ramp(dur_s: float, start: float, end: float, sr: int = SR) -> np.ndarray:
    n = samples(dur_s, sr)
    return np.linspace(start, end, n).astype(np.float64)


def pitch_env(dur_s: float, start_hz: float, end_hz: float, sr: int = SR,
              curve: str = "exp") -> np.ndarray:
    """A frequency-over-time array suitable for feeding to sine/saw/square as `freq`."""
    n = samples(dur_s, sr)
    tt = np.linspace(0.0, 1.0, n)
    if curve == "exp" and start_hz > 0 and end_hz > 0:
        freqs = start_hz * (end_hz / start_hz) ** tt
    else:
        freqs = start_hz + (end_hz - start_hz) * tt
    return freqs


def apply_env(x: np.ndarray, env: np.ndarray) -> np.ndarray:
    n = min(len(x), len(env))
    return (x[:n].astype(np.float64) * env[:n].astype(np.float64)).astype(np.float32)


def fade_in(x: np.ndarray, dur_s: float, sr: int = SR) -> np.ndarray:
    n = min(samples(dur_s, sr), len(x))
    x = x.copy()
    if n > 0:
        x[:n] = (x[:n].astype(np.float64) * np.linspace(0.0, 1.0, n)).astype(np.float32)
    return x


def fade_out(x: np.ndarray, dur_s: float, sr: int = SR) -> np.ndarray:
    n = min(samples(dur_s, sr), len(x))
    x = x.copy()
    if n > 0:
        x[-n:] = (x[-n:].astype(np.float64) * np.linspace(1.0, 0.0, n)).astype(np.float32)
    return x


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------

def one_pole_lowpass(x: np.ndarray, cutoff_hz: float, sr: int = SR) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if cutoff_hz <= 0:
        return np.zeros_like(x, dtype=np.float32)
    if cutoff_hz >= sr / 2.0:
        return x.astype(np.float32)
    a = float(np.exp(-2.0 * np.pi * cutoff_hz / sr))
    b0 = 1.0 - a
    y = np.empty_like(x)
    acc = 0.0
    for i in range(x.shape[0]):
        acc = a * acc + b0 * x[i]
        y[i] = acc
    return y.astype(np.float32)


def one_pole_highpass(x: np.ndarray, cutoff_hz: float, sr: int = SR) -> np.ndarray:
    lp = one_pole_lowpass(x, cutoff_hz, sr).astype(np.float64)
    return (np.asarray(x, dtype=np.float64) - lp).astype(np.float32)


def _biquad_coeffs(kind: str, freq: float, sr: int, q: float):
    w0 = 2.0 * np.pi * max(min(freq, sr / 2.0 - 1.0), 1.0) / sr
    alpha = np.sin(w0) / (2.0 * q)
    cosw0 = np.cos(w0)
    if kind == "lowpass":
        b0 = (1 - cosw0) / 2
        b1 = 1 - cosw0
        b2 = (1 - cosw0) / 2
        a0 = 1 + alpha
        a1 = -2 * cosw0
        a2 = 1 - alpha
    elif kind == "highpass":
        b0 = (1 + cosw0) / 2
        b1 = -(1 + cosw0)
        b2 = (1 + cosw0) / 2
        a0 = 1 + alpha
        a1 = -2 * cosw0
        a2 = 1 - alpha
    elif kind == "bandpass":
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1 + alpha
        a1 = -2 * cosw0
        a2 = 1 - alpha
    else:
        raise ValueError(f"unknown biquad kind {kind!r}")
    return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def biquad(x: np.ndarray, kind: str, freq: ArrayOrScalar, sr: int = SR,
           q: float = 0.707) -> np.ndarray:
    """RBJ cookbook biquad. `freq` may be a scalar or a per-sample array
    (time-varying filter, e.g. a swept bandpass)."""
    x = np.asarray(x, dtype=np.float64)
    n = x.shape[0]
    y = np.empty(n, dtype=np.float64)
    x1 = x2 = y1 = y2 = 0.0

    if np.isscalar(freq):
        b0, b1, b2, a1, a2 = _biquad_coeffs(kind, float(freq), sr, q)
        for i in range(n):
            xi = x[i]
            yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            y[i] = yi
            x2, x1 = x1, xi
            y2, y1 = y1, yi
    else:
        freq_arr = _match_len(np.asarray(freq, dtype=np.float64), n)
        for i in range(n):
            b0, b1, b2, a1, a2 = _biquad_coeffs(kind, float(freq_arr[i]), sr, q)
            xi = x[i]
            yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            y[i] = yi
            x2, x1 = x1, xi
            y2, y1 = y1, yi
    return y.astype(np.float32)


def lowpass(x, freq, sr=SR, q=0.707):
    return biquad(x, "lowpass", freq, sr, q)


def highpass(x, freq, sr=SR, q=0.707):
    return biquad(x, "highpass", freq, sr, q)


def bandpass(x, freq, sr=SR, q=1.2):
    return biquad(x, "bandpass", freq, sr, q)


# --------------------------------------------------------------------------
# distortion / lo-fi
# --------------------------------------------------------------------------

def soft_clip(x: np.ndarray, drive: float = 1.0) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return np.tanh(x * drive).astype(np.float32)


def hard_clip(x: np.ndarray, ceiling: float = 1.0) -> np.ndarray:
    return np.clip(x, -ceiling, ceiling).astype(np.float32)


def bitcrush(x: np.ndarray, bits: float = 8.0, rate_divisor: int = 1) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    levels = 2 ** bits
    half = levels / 2.0 - 1.0
    y = np.round(x * half) / max(half, 1e-9)
    if rate_divisor and rate_divisor > 1:
        n = len(y)
        idx = (np.arange(n) // rate_divisor) * rate_divisor
        idx = np.clip(idx, 0, n - 1)
        y = y[idx]
    return y.astype(np.float32)


# --------------------------------------------------------------------------
# delay / reverb
# --------------------------------------------------------------------------

def delay_fx(x: np.ndarray, delay_s: float, feedback: float = 0.35,
             mix: float = 0.3, sr: int = SR) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    nd = max(1, samples(delay_s, sr))
    n = len(x)
    out = np.empty(n, dtype=np.float64)
    line = np.zeros(nd, dtype=np.float64)
    widx = 0
    for i in range(n):
        delayed = line[widx]
        out[i] = x[i] + delayed * mix
        line[widx] = x[i] + delayed * feedback
        widx += 1
        if widx >= nd:
            widx = 0
    return out.astype(np.float32)


def comb_filter(x: np.ndarray, delay_s: float, feedback: float = 0.7,
                 sr: int = SR) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    nd = max(1, samples(delay_s, sr))
    n = len(x)
    y = np.empty(n, dtype=np.float64)
    buf = np.zeros(nd, dtype=np.float64)
    idx = 0
    for i in range(n):
        bv = buf[idx]
        yi = x[i] + feedback * bv
        buf[idx] = yi
        y[i] = yi
        idx += 1
        if idx >= nd:
            idx = 0
    return y.astype(np.float32)


def allpass_filter(x: np.ndarray, delay_s: float, g: float = 0.5,
                    sr: int = SR) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    nd = max(1, samples(delay_s, sr))
    n = len(x)
    y = np.empty(n, dtype=np.float64)
    buf = np.zeros(nd, dtype=np.float64)
    idx = 0
    for i in range(n):
        bv = buf[idx]
        xi = x[i]
        yi = -g * xi + bv
        buf[idx] = xi + g * yi
        y[i] = yi
        idx += 1
        if idx >= nd:
            idx = 0
    return y.astype(np.float32)


def reverb(x: np.ndarray, room_size: float = 0.5, damping: float = 0.3,
           mix: float = 0.25, sr: int = SR, tail_s: float = 0.6) -> np.ndarray:
    """Simple Schroeder-style reverb: parallel combs -> series allpasses."""
    xpad = np.pad(np.asarray(x, dtype=np.float64), (0, samples(tail_s, sr)))
    comb_delays = (0.0297, 0.0371, 0.0411, 0.0437)
    fb = min(0.6 + 0.35 * room_size, 0.97)
    lp_cutoff = 8000.0 * (1.0 - damping) + 800.0
    acc = np.zeros_like(xpad)
    for d in comb_delays:
        c = comb_filter(xpad, d, feedback=fb, sr=sr)
        c = one_pole_lowpass(c, lp_cutoff, sr=sr)
        acc += c
    acc /= len(comb_delays)
    acc = allpass_filter(acc, 0.005, g=0.5, sr=sr)
    acc = allpass_filter(acc, 0.0017, g=0.5, sr=sr)
    out = xpad * (1.0 - mix) + acc * mix
    return out.astype(np.float32)


# --------------------------------------------------------------------------
# layering / mixing / assembly
# --------------------------------------------------------------------------

def pad_to(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if len(x) >= n:
        return x[:n]
    return np.pad(x, (0, n - len(x)))


def gain_db(x: np.ndarray, db: float) -> np.ndarray:
    return (np.asarray(x, dtype=np.float64) * db_to_lin(db)).astype(np.float32)


def mix_layers(layers: Sequence[np.ndarray], gains: Union[Sequence[float], None] = None) -> np.ndarray:
    """Sum layers (linear gain per layer, default 1.0), auto-padding to the
    longest layer's length."""
    if not layers:
        return np.zeros(1, dtype=np.float32)
    if gains is None:
        gains = [1.0] * len(layers)
    n = max(len(l) for l in layers)
    out = np.zeros(n, dtype=np.float64)
    for layer, g in zip(layers, gains):
        arr = np.asarray(layer, dtype=np.float64)
        out[: len(arr)] += arr * g
    return out.astype(np.float32)


def concat(*layers: np.ndarray) -> np.ndarray:
    return np.concatenate([np.asarray(l, dtype=np.float32) for l in layers])


def silence(dur_s: float, sr: int = SR) -> np.ndarray:
    return np.zeros(samples(dur_s, sr), dtype=np.float32)


def crossfade_loop(x: np.ndarray, xfade_s: float, sr: int = SR) -> np.ndarray:
    """Make a buffer seamlessly loopable by crossfading its tail into its head
    in-place (equal-power-ish linear crossfade), keeping total length the same."""
    x = np.asarray(x, dtype=np.float64).copy()
    n = len(x)
    nx = min(samples(xfade_s, sr), n // 4)
    if nx <= 0:
        return x.astype(np.float32)
    fade_in_ = np.linspace(0.0, 1.0, nx)
    fade_out_ = 1.0 - fade_in_
    head = x[:nx].copy()
    tail = x[-nx:].copy()
    blended = tail * fade_out_ + head * fade_in_
    x[:nx] = blended
    x[-nx:] = blended
    return x.astype(np.float32)


def normalize_peak(x: np.ndarray, peak_dbfs: float = -1.5) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    target = db_to_lin(peak_dbfs)
    peak = np.max(np.abs(x)) + 1e-12
    return (x * (target / peak)).astype(np.float32)


def normalize_rms(x: np.ndarray, rms_dbfs: float = -12.0, safety_peak: float = 0.999) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    target = db_to_lin(rms_dbfs)
    rms = float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    y = x * (target / rms)
    peak = np.max(np.abs(y)) + 1e-12
    if peak > safety_peak:
        y *= safety_peak / peak
    return y.astype(np.float32)


# --------------------------------------------------------------------------
# WAV I/O
# --------------------------------------------------------------------------

def write_wav(path: Union[str, Path], x: np.ndarray, sr: int = SR) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.clip(np.asarray(x, dtype=np.float64), -1.0, 1.0)
    ints = np.round(x * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(ints.tobytes())


def read_wav(path: Union[str, Path]):
    with wave.open(str(path), "rb") as f:
        nch = f.getnchannels()
        sw = f.getsampwidth()
        sr = f.getframerate()
        nframes = f.getnframes()
        raw = f.readframes(nframes)
    if sw != 2:
        raise ValueError(f"expected 16-bit PCM, got sampwidth={sw}")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        data = data.reshape(-1, nch)
    return data, sr
