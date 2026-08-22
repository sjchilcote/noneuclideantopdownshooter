"""voices v2 — the real instruments, built on the audited toolchain.

Replaces hymn01's hand-rolled voice layer after the director's verdict on
stems v1 ("random General MIDI clips... nothing like the original album")
triangulated with the probes ("synth imitating guitar", "no melody
present") and the census (mid-dead, mono, thin). Every voice here uses
the prior-work tools the audit proved on this box (LIB_AUDIT.md):

- GUITAR: real sliced hits, parselmouth-tuned, through a pedalboard chain
  ending in a REAL 4x12 cab IR convolution (CC0, provenance in
  SOURCES_LICENSES.md), double-tracked as two takes for the album's
  hard-panned WALL (ALBUM_TECHNIQUES §1).
- MACHINE CHOIR: the pyworld WORLD-vocoder recipe from the audit — force
  f0 AND crush aperiodicity to ~5% (measured 25.6 dB comb contrast vs
  2.8 dB for f0-alone): the factory recording literally given a voice.
- Space: dark plate IR (synthesized exponential-decay noise, lowpassed)
  for SANCTUARY voicings only; DEFIANCE voicings stay dry (director:
  the organ is sometimes distant-and-holy, sometimes a machine screaming
  in defiance, close and raw).
- Loudness: pyloudnorm LUFS, not hand-rolled RMS.

GPL note: pedalboard/rubberband are offline asset-authoring tools only —
they render wavs committed as assets; nothing GPL ships in the game.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soundgen"))
import synth as sy                                  # noqa: E402

SR = sy.SR
SCRATCH = Path("/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter"
               "/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/musicgen")
IR_DIR = SCRATCH / "ir"
CAB_IR = IR_DIR / "jesterdyne_4x12_vintage_129399.wav"   # CC0, audited

D2, D3 = 73.42, 146.83


def _mono(path: Path) -> tuple[np.ndarray, int]:
    x, sr = sf.read(str(path), always_2d=True, dtype="float64")
    return x.mean(axis=1), sr


# --------------------------------------------------------------------------
# GUITAR — the wall and the riff voice
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _chug_kit() -> tuple:
    """Slice + tune real hits from the 20.7 s riff recording. librosa
    onsets + parselmouth f0 per slice (the audit's cross-validated
    detectors), every slice tuned to D2 exactly."""
    import librosa
    import parselmouth
    raw, sr = _mono(SCRATCH / "freesound/chug1.wav")
    on = librosa.onset.onset_detect(y=raw, sr=sr, units="samples",
                                    backtrack=True, delta=0.12)
    picks = []
    for i in on:
        if raw[i:i + int(0.25 * sr)].std() < 0.02:
            continue
        if picks and i - picks[-1] < int(0.3 * sr):
            continue
        picks.append(int(i))
    kit = []
    for i in picks[:12]:
        seg = raw[i:i + int(0.85 * sr)].copy()       # natural decay window
        if len(seg) < int(0.3 * sr):
            continue
        f = int(0.08 * sr)                            # tail-only fade
        seg[-f:] *= np.linspace(1, 0, f)
        snd = parselmouth.Sound(seg[:int(0.3 * sr)], sampling_frequency=sr)
        pitch = snd.to_pitch(pitch_floor=55, pitch_ceiling=220)
        f0s = pitch.selected_array["frequency"]
        f0s = f0s[f0s > 0]
        if not len(f0s):
            continue
        f0 = float(np.median(f0s))
        off = 12 * np.log2(D2 / f0)
        off -= 12 * round(off / 12)                  # nearest octave of D
        if abs(off) > 3.5:                           # not a D-family hit
            continue
        # SAMPLER-STYLE resample repitch (speed+pitch together): keeps the
        # pick transient character a phase vocoder smears into "square-wave
        # synth" (probe-measured). Length change is fine for one-shots.
        from fractions import Fraction
        from scipy.signal import resample_poly
        ratio = 2.0 ** (-off / 12.0)
        fr = Fraction(ratio).limit_denominator(300)
        tuned = resample_poly(seg, fr.denominator, fr.numerator)
        kit.append(tuned / (np.abs(tuned).max() + 1e-9))
    if len(kit) < 3:
        raise RuntimeError(f"chug kit too small: {len(kit)} tuned slices")
    return tuple(kit)


@lru_cache(maxsize=2)
def _amp_chain(drive_db: float = 18.0):
    from pedalboard import (Pedalboard, Distortion, Convolution,
                            Compressor, HighpassFilter, LowShelfFilter)
    return Pedalboard([
        HighpassFilter(cutoff_frequency_hz=70),
        Compressor(threshold_db=-24, ratio=3, attack_ms=5, release_ms=80),
        Distortion(drive_db=drive_db),
        LowShelfFilter(cutoff_frequency_hz=110, gain_db=-3),
        Convolution(str(CAB_IR), mix=1.0),
    ])


def amp(x: np.ndarray, drive_db: float = 18.0) -> np.ndarray:
    y = _amp_chain(drive_db)(x.astype(np.float32), SR)
    return y.astype(np.float64)


def chug_note(rng: np.random.Generator, semi: float, dur_s: float,
              mute: float, vel: float) -> np.ndarray:
    """One picked hit from the tuned kit; palm depth shortens/darkens."""
    import librosa.effects
    kit = _chug_kit()
    seg = kit[int(rng.integers(len(kit)))]
    if abs(semi) > 0.01:
        seg = librosa.effects.pitch_shift(seg, sr=SR, n_steps=float(semi))
    n = int(dur_s * SR)
    if len(seg) < n:
        seg = np.pad(seg, (0, n - len(seg)))
    seg = seg[:n].copy()
    fade = max(1, int(min(0.02, dur_s * 0.1) * SR))
    seg[-fade:] *= np.linspace(1, 0, fade)
    if mute > 0:
        # a real palm mute is SHORT but keeps its midrange grind — the
        # earlier 1250 Hz lowpass turned mutes into "bass synth pulses"
        # (probe-measured). Gentle tilt only, aggressive shortening.
        seg = sy.lowpass(seg, 5200 - 1700 * mute)
        body = int(n * (0.30 + 0.35 * (1 - mute)))
        env = np.ones(n)
        env[body:] *= np.exp(-np.linspace(0, 6 * mute + 1, n - body))
        seg *= env
    return seg * vel


# --------------------------------------------------------------------------
# MACHINE CHOIR — the WORLD-vocoded congregation (audit recipe)
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _factory_world():
    import pyworld
    x, sr = _mono(SCRATCH / "freesound/machine_factory.wav")
    x = x[:int(20 * sr)]
    if sr != SR:
        import librosa
        x = librosa.resample(x, orig_sr=sr, target_sr=SR)
    f0, t = pyworld.harvest(x, SR)
    sp = pyworld.cheaptrick(x, f0, t, SR)
    ap = pyworld.d4c(x, f0, t, SR)
    return sp, ap


def machine_voice(semi_from_d3: float, dur_s: float, breath: float = 0.18,
                  vel: float = 1.0, drift: float = 0.0) -> np.ndarray:
    """The congregation sings: WORLD resynthesis of the factory with f0
    FORCED to the note and aperiodicity crushed to 5% (LIB_AUDIT: 25.6 dB
    comb contrast — a real pitched voice, not a hope)."""
    import pyworld
    sp, ap = _factory_world()
    hop_s = 0.005
    n_frames = int(dur_s / hop_s) + 2
    total = sp.shape[0]
    start = int(abs(hash((round(semi_from_d3 * 7), round(dur_s * 13))))
                % max(1, total - n_frames)) if total > n_frames else 0
    sp_n = sp[start:start + n_frames].copy()
    ap_n = np.clip(ap[start:start + n_frames] * 0.05, 0.0, 1.0)
    f0_n = np.full(sp_n.shape[0],
                   D3 * 2.0 ** ((semi_from_d3 + drift) / 12.0))
    y = pyworld.synthesize(f0_n, sp_n, ap_n, SR, frame_period=hop_s * 1000)
    n = int(dur_s * SR)
    if len(y) < n:
        y = np.pad(y, (0, n - len(y)))
    y = y[:n]
    a = max(1, int(breath * SR))
    r = max(1, int(min(0.3, dur_s * 0.3) * SR))
    env = np.ones(n)
    env[:min(a, n // 2)] = np.linspace(0, 1, min(a, n // 2)) ** 1.3
    env[n - min(r, n // 2):] = np.linspace(1, 0, min(r, n // 2)) ** 1.3
    m = np.abs(y).max() + 1e-9
    return y / m * 0.5 * env * vel


# --------------------------------------------------------------------------
# Space + loudness
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _plate_ir(decay_s: float = 3.5) -> np.ndarray:
    """Dark plate: exponentially decaying noise, progressively lowpassed —
    the SANCTUARY space (holy = far). Deterministic."""
    rng = np.random.default_rng(0x1A7E)
    n = int(decay_s * SR)
    ir = rng.normal(0, 1, n) * np.exp(-np.linspace(0, 7.5, n))
    ir = sy.lowpass(ir, 5200)
    dark = sy.lowpass(ir, 2200)
    w = np.linspace(0, 1, n)
    ir = ir * (1 - w) + dark * w                    # darkens as it decays
    ir[:int(0.03 * SR)] *= np.linspace(0, 1, int(0.03 * SR))  # pre-delay-ish
    return ir / (np.abs(ir).sum() / 400.0)


def sanctuary(x: np.ndarray, mix: float = 0.4) -> np.ndarray:
    from scipy.signal import fftconvolve
    wet = fftconvolve(x, _plate_ir())[:len(x)]
    return x * (1 - mix) + wet * mix


def lufs(x: np.ndarray) -> float:
    import pyloudnorm
    meter = pyloudnorm.Meter(SR)
    return float(meter.integrated_loudness(x))


def to_lufs(x: np.ndarray, target: float = -15.0) -> np.ndarray:
    cur = lufs(x)
    if not np.isfinite(cur):
        return x
    return x * (10 ** ((target - cur) / 20.0))
