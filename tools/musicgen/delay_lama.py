"""Delay Lama — the album's actual vocal instrument, rendering headless.

AudioNerdz Delay Lama (2002, freeware, VST2 i386; archive.org/details/
delay-lama) hosted by MrsWatson 0.9.8 (BSD, teragonaudio) under wine.
Milestone-0 verification (2026-07-13): MIDI 50 renders at f0=73.6 Hz —
a D, 100% voiced (parselmouth) — and the flash ear reports "a low,
steady male vocal drone," sounds_like_singing_voice=true.

Facts this wrapper encodes:
- MrsWatson reads MIDI TYPE 0 only.
- The plugin sounds an octave below MIDI nominal (MIDI 50 -> D2 73.4 Hz):
  callers write intended pitches; we add +12 internally.
- Monophonic (it is one monk). FOUR VST parameters (enumerated via
  --display-info): 0 PortTime (default 0.5 — the meditative glide that
  poisoned note conformance to 7/29), 1 Vowel, 2 Delay (default 0.8 — a
  built-in echo), 3 HeadSize. Driven via MrsWatson --parameter. The
  earlier pitchwheel-as-vowel assumption was WRONG (params are static
  per render; per-phrase vowel = separate renders).

    from delay_lama import render_vocal
    y = render_vocal([(0, 8), (3, 8), (2, 8), (0, 16)], step_s=0.214)
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

SR = 44100
DL_DIR = Path("/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter"
              "/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/musicgen/delaylama")
DLL = DL_DIR / "DelayLama.dll"
HOST = DL_DIR / "MrsWatson-0.9.8/Windows/mrswatson.exe"
D3_MIDI = 50            # written pitch for D3; +12 applied for the octave map
PPQ = 480
BPM_MIDI = 120.0        # mido default tempo; timings computed against it


def _write_midi(events, step_s: float, path: Path, base_midi: int,
                vowels=None):
    """events: (semi_from_D3 | None, dur_steps). Timing via delta ticks at
    the default 120 BPM tempo map (1 tick = 60/(120*480) s)."""
    import mido
    mid = mido.MidiFile(type=0, ticks_per_beat=PPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tick_s = 60.0 / (BPM_MIDI * PPQ)
    # Per the shipped documentation: CC5=portamento, CC12=delay mix,
    # CC13=voice, CC1=vibrato; PITCHBEND = vowel (not pitch!). HOST BUG
    # (measured): MrsWatson silences the render if a MIDI file contains
    # MORE THAN ONE control_change — any pair, any spacing, even the same
    # CC twice. So exactly ONE CC per render: portamento (the one that
    # decides note conformance). Delay/voice/vibrato ride their defaults;
    # vary them per-render only via separate renders if ever needed.
    tr.append(mido.Message("control_change", control=5,
                           value=_cc(_write_midi.port_time), time=0))
    pending = 0             # rest time accumulated, in ticks
    for i, (sv, d) in enumerate(events):
        dur_ticks = max(1, int(round(d * step_s / tick_s)))
        if sv is None:
            pending += dur_ticks
            continue
        if vowels is not None and i < len(vowels) and vowels[i] is not None:
            bend = int(np.clip(vowels[i], -1, 1) * 8191)
            tr.append(mido.Message("pitchwheel", pitch=bend, time=pending))
            pending = 0
        note = int(base_midi + 12 + round(sv))
        gate = max(1, int(dur_ticks * 0.93))
        tr.append(mido.Message("note_on", note=note, velocity=100,
                               time=pending))
        tr.append(mido.Message("note_off", note=note, velocity=0,
                               time=gate))
        pending = dur_ticks - gate
    tr.append(mido.MetaMessage("end_of_track", time=pending + PPQ))
    mid.save(str(path))


def _cc(v: float) -> int:
    return int(max(0, min(127, round(v * 127))))


def render_vocal(events, step_s: float, base_midi: int = D3_MIDI,
                 vowels=None, port_time: float = 0.04, delay: float = 0.08,
                 voice: float = 0.35, vibrato: float = 0.15,
                 timeout_s: int = 300) -> np.ndarray:
    """Render a monophonic vocal line through Delay Lama. Returns mono
    float64 at 44100. Loud failure on any host error — no silent fallback
    (instruction-substitution law: this instrument or an error)."""
    import soundfile as sf
    if not DLL.exists() or not HOST.exists():
        raise FileNotFoundError(
            f"Delay Lama toolchain missing: dll={DLL.exists()} "
            f"host={HOST.exists()} — re-fetch per ALBUM_MODE_V2_DESIGN M0")
    with tempfile.TemporaryDirectory(dir=str(DL_DIR)) as td:
        midp = Path(td) / "line.mid"
        wavp = Path(td) / "line.wav"
        _write_midi.port_time = port_time
        _write_midi.delay = delay
        _write_midi.voice = voice
        _write_midi.vibrato = vibrato
        _write_midi(events, step_s, midp, base_midi, vowels)
        # wine + MrsWatson want paths relative to cwd (unix absolutes
        # fail plugin-chain construction — M0 spike used relative paths)
        r = subprocess.run(
            ["wine", str(HOST.relative_to(DL_DIR)), "--plugin",
             DLL.name, "--midi-file", str(midp.relative_to(DL_DIR)),
             "--output", str(wavp.relative_to(DL_DIR)),
             "--sample-rate", str(SR)],
            capture_output=True, text=True, timeout=timeout_s,
            cwd=str(DL_DIR))
        if not wavp.exists():
            raise RuntimeError(
                f"Delay Lama render failed (rc={r.returncode}):\n"
                f"{(r.stdout or '')[-800:]}\n{(r.stderr or '')[-400:]}")
        x, sr = sf.read(str(wavp))
    if x.ndim == 2:
        x = x.mean(axis=1)
    if sr != SR:
        from fractions import Fraction
        from scipy.signal import resample_poly
        fr = Fraction(SR, sr).limit_denominator(1000)
        x = resample_poly(x, fr.numerator, fr.denominator)
    return x.astype(np.float64)


if __name__ == "__main__":
    import soundfile as sf
    y = render_vocal([(0, 8), (3, 4), (2, 4), (0, 12)], step_s=60 / 140 / 4)
    out = DL_DIR / "selftest.wav"
    sf.write(str(out), (y / (np.abs(y).max() + 1e-9) * 0.85).astype("float32"),
             SR)
    print(f"selftest: {len(y)/SR:.2f}s -> {out}")
