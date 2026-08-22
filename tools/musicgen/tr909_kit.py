"""TR-909 kit — real machine samples as the drum instrument (M2).

Presets-first law: the samples ARE the preset. AudioRealism's 853-sample
pack (real TR-909, individual outs, 11 accent levels per instrument, 5x5x5
knob grid on kick/snare, open-hat choke combos, snare+clap master-out
phasing pairs). Per-hit accent selects a REAL sampled accent layer — the
hardware's own velocity response, not gain scaling.

License: free download from audiorealism.se; no redistribution — samples
stay in the scratchpad, only renders are committed (SOURCES_LICENSES.md).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import numpy as np

SR = 44100
PACK = Path("/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter"
            "/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/musicgen"
            "/tr909/TR-909-44.1kHz-16bit")

# instrument dir -> filename accent pattern
INSTS = {
    "kick": ("BassDrum", "BassDrum909"),
    "snare": ("SnareDrum", "SnareDrum909"),
    "chh": ("ClosedHat", "ClosedHat"),
    "ohh": ("OpenHat", "OpenHat"),
    "clap": ("HandClap", "HandClap"),
    "ride": ("Ride", "Ride"),
    "crash": ("Crash", "Crash"),
    "rim": ("RimShot", "RimShot"),
}


@lru_cache(maxsize=None)
def _load(path: str) -> np.ndarray:
    import soundfile as sf
    x, sr = sf.read(path)
    if x.ndim == 2:
        x = x.mean(axis=1)
    assert sr == SR, (path, sr)
    return x.astype(np.float64)


@lru_cache(maxsize=None)
def _accent_files(inst: str) -> tuple:
    """Sorted (accent_level, path) for an instrument's accent-sampled set."""
    d = PACK / INSTS[inst][0]
    out = []
    for f in d.glob("*accent*.wav"):
        m = re.search(r"accent(\d+)", f.name)
        if m and "tune050" in f.name or (m and "tune" not in f.name):
            out.append((int(m.group(1)), str(f)))
    if not out:                      # fall back to any accent files
        for f in d.glob("*accent*.wav"):
            m = re.search(r"accent(\d+)", f.name)
            if m:
                out.append((int(m.group(1)), str(f)))
    if not out:                      # no accent set: single default sample
        cands = sorted(d.glob("*.wav"))
        if cands:
            out = [(100, str(cands[len(cands) // 2]))]
    return tuple(sorted(out))


def hit(inst: str, vel: float, rng=None) -> np.ndarray:
    """A real sampled hit at the nearest sampled accent to `vel` (0..1);
    tiny neighbor-accent randomization = the machine's own layer spread."""
    files = _accent_files(inst)
    if not files:
        raise FileNotFoundError(f"no samples for {inst} in {PACK}")
    target = vel * 100
    idx = int(np.argmin([abs(a - target) for a, _ in files]))
    if rng is not None and len(files) > 1 and rng.random() < 0.3:
        idx = int(np.clip(idx + rng.integers(-1, 2), 0, len(files) - 1))
    return _load(files[idx][1])


def kick_knob(tune: int = 25, attack: int = 25, decay: int = 50) -> np.ndarray:
    """A specific kick from the 5x5x5 knob grid (values 0/25/50/75/100)."""
    f = PACK / "BassDrum" / \
        f"BassDrum909-tune{tune:03d}-attack{attack:03d}-decay{decay:03d}.wav"
    if not f.exists():
        raise FileNotFoundError(f)
    return _load(str(f))


def place(out: np.ndarray, x: np.ndarray, t_s: float, gain: float = 1.0):
    i = int(t_s * SR)
    if 0 <= i < len(out):
        seg = x[:len(out) - i]
        out[i:i + len(seg)] += seg * gain
