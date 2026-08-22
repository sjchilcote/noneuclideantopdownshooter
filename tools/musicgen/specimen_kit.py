"""Specimen (Spektralisk) sample pack — catalog + keyed loader.

Free pack, EULA: use in music OK, NO redistribution of samples as
standalone files — samples live in the scratchpad only, renders are
committed (SOURCES_LICENSES.md).

Filename grammar:  SPEK_PACK_CATEGORY[_Loop_BPM][_KEY]_Name.wav
Keyed entries (e.g. C2, A#3) repitch like a sampler; loops carry BPM.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import numpy as np

SR = 44100
ROOT = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
            "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b"
            "/scratchpad/musicgen/specimen/Specimen by Spektralisk"
            "/Specimen Samples")

_NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
         "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
_RE = re.compile(
    r"SPEK_(?P<pack>\w+)_(?P<cat>[A-Z]+)"
    r"(?:_Loop)?(?:_(?P<bpm>\d+)BPM)?"
    r"(?:_(?P<key>[A-G]#?\-?\d))?_(?P<name>.+)\.wav$")


def catalog(category: str | None = None):
    """[(category, name, path, midi|None, bpm|None)]"""
    out = []
    for f in sorted(ROOT.rglob("*.wav")):
        m = _RE.match(f.name)
        if not m:
            continue
        cat = m.group("cat")
        if category and cat != category:
            continue
        midi = None
        if m.group("key"):
            k = m.group("key")
            pc = _NOTE[k[:-1]]
            midi = 12 * (int(k[-1]) + 1) + pc
        bpm = int(m.group("bpm")) if m.group("bpm") else None
        out.append((cat, m.group("name"), f, midi, bpm))
    return out


@lru_cache(maxsize=64)
def load(path: str) -> np.ndarray:
    import soundfile as sf
    x, sr = sf.read(path)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if sr != SR:
        n = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n),
                      np.arange(len(x)), x)
    return x.astype(np.float64)


def keyed(path: Path, src_midi: int, target_midi: int) -> np.ndarray:
    """Sampler repitch (resample; tape-style, matches the era)."""
    x = load(str(path))
    ratio = 2 ** ((target_midi - src_midi) / 12.0)
    n = int(len(x) / ratio)
    return np.interp(np.linspace(0, len(x) - 1, n),
                     np.arange(len(x)), x)


if __name__ == "__main__":
    cats = {}
    for cat, name, f, midi, bpm in catalog():
        cats.setdefault(cat, []).append((name, midi, bpm))
    for cat, items in sorted(cats.items()):
        keyed_n = sum(1 for _, m, _ in items if m)
        print(f"{cat:5s} {len(items):3d} items ({keyed_n} keyed)")
