"""game/tests/test_audio_bank.py

WAV integrity checks for the procedurally generated SFX bank
(tools/soundgen/bank.py -> game/assets/sfx/*.wav). Pure stdlib `wave` +
numpy -- no pygame/necore imports, runs under plain pytest.
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "soundgen"))
import bank  # noqa: E402

MANIFEST = bank.MANIFEST

# Any real synthesized SFX should clear this RMS floor (16-bit PCM full
# scale = 32767); a bug that produces near-silence/all-zero output would
# land far below this.
MIN_RMS = 20.0


def _load(path: Path):
    with wave.open(str(path), "rb") as f:
        nch = f.getnchannels()
        sw = f.getsampwidth()
        sr = f.getframerate()
        nframes = f.getnframes()
        raw = f.readframes(nframes)
    return nch, sw, sr, nframes, raw


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["name"])
def test_wav_file_exists(entry):
    path = REPO_ROOT / entry["path"]
    assert path.exists(), f"missing wav for {entry['name']}: {path}"


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["name"])
def test_wav_loads_and_is_44100_mono_16bit(entry):
    path = REPO_ROOT / entry["path"]
    if not path.exists():
        pytest.skip(f"{entry['name']}.wav not generated -- run tools/soundgen/bank.py")
    nch, sw, sr, nframes, _raw = _load(path)
    assert sr == 44100, f"{entry['name']}: expected 44100Hz, got {sr}"
    assert nch == 1, f"{entry['name']}: expected mono, got {nch} channels"
    assert sw == 2, f"{entry['name']}: expected 16-bit PCM, got sampwidth={sw} bytes"
    assert nframes > 0, f"{entry['name']}: zero-length wav"


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["name"])
def test_wav_non_silent(entry):
    path = REPO_ROOT / entry["path"]
    if not path.exists():
        pytest.skip(f"{entry['name']}.wav not generated -- run tools/soundgen/bank.py")
    _nch, _sw, _sr, _nframes, raw = _load(path)
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    rms = float(np.sqrt(np.mean(data ** 2))) if data.size else 0.0
    assert rms > MIN_RMS, f"{entry['name']}: too quiet/silent (rms={rms:.2f} <= {MIN_RMS})"


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["name"])
def test_wav_no_clipping(entry):
    path = REPO_ROOT / entry["path"]
    if not path.exists():
        pytest.skip(f"{entry['name']}.wav not generated -- run tools/soundgen/bank.py")
    _nch, _sw, _sr, _nframes, raw = _load(path)
    data = np.frombuffer(raw, dtype=np.int16)
    peak = int(np.max(np.abs(data.astype(np.int32)))) if data.size else 0
    assert peak < 32767, f"{entry['name']}: clipping detected (peak={peak})"


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["name"])
def test_wav_duration_within_2x_of_spec_range(entry):
    path = REPO_ROOT / entry["path"]
    if not path.exists():
        pytest.skip(f"{entry['name']}.wav not generated -- run tools/soundgen/bank.py")
    _nch, _sw, sr, nframes, _raw = _load(path)
    dur = nframes / sr
    lo = entry["dur_min"] / 2.0
    hi = entry["dur_max"] * 2.0
    assert lo <= dur <= hi, (
        f"{entry['name']}: duration {dur:.3f}s is outside 2x of the spec range "
        f"[{entry['dur_min']}, {entry['dur_max']}]s -> allowed [{lo:.3f}, {hi:.3f}]s"
    )


def test_manifest_covers_expected_sound_count():
    # Sanity check the manifest itself isn't accidentally empty/truncated.
    assert len(MANIFEST) >= 30, f"expected >=30 bank entries, got {len(MANIFEST)}"
    names = [e["name"] for e in MANIFEST]
    assert len(names) == len(set(names)), "duplicate sound names in MANIFEST"
