"""Odin2 headless host — factory presets loaded for real (presets-first law).

Odin2 (TheWaveWarden, GPL) Linux VST3 + the 260-patch factory soundbank
from the repo. Preset loading path discovered here: the VST3 state chunk
is `VC2!` + length + XML(VST3PluginState) whose <IComponent> payload is a
JUCE MemoryBlock::toBase64Encoding of the SAME JUCE ValueTree bytes that
.odin patch files contain ("Odin" magic). So: JUCE-base64-encode the
.odin file, splice into the state XML, assign raw_state. The JUCE
encoding (juce_MemoryBlock.cpp): "<decimal size>.<data>" over table
".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+",
6-bit groups read LSB-first from the byte stream.
"""
from __future__ import annotations

import re
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np

SR = 44100
S = Path("/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter"
         "/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/musicgen/odin2")
VST = S / "Odin2.vst3"

_TABLE = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def juce_b64encode(data: bytes) -> bytes:
    nbits = len(data) * 8
    nchars = (nbits + 5) // 6
    out = []
    for i in range(nchars):
        v = 0
        for b in range(6):
            k = i * 6 + b
            if k < nbits and (data[k >> 3] >> (k & 7)) & 1:
                v |= 1 << b
        out.append(_TABLE[v])
    return (str(len(data)) + "." + "".join(out)).encode()


@lru_cache(maxsize=1)
def _plugin():
    import pedalboard
    return pedalboard.load_plugin(str(VST))


@lru_cache(maxsize=1)
def _state_template():
    p = _plugin()
    st = bytes(p.raw_state)
    m = re.search(rb"<IComponent>(.*?)</IComponent>", st, re.S)
    return st, m.start(1), m.end(1)


def load_patch(patch_path: Path):
    """Convert the binary-ValueTree .odin patch to the XML form the
    plugin's state actually carries (VC2! + u32 len + XML <Odin>),
    then graft into <IComponent>."""
    from juce_valuetree import binary_to_xml
    p = _plugin()
    st, a, b = _state_template()
    xml = binary_to_xml(patch_path.read_bytes()).encode()
    inner = b"VC2!" + struct.pack("<I", len(xml)) + xml
    enc = juce_b64encode(inner)
    new = st[:a] + enc + st[b:]
    ns = bytearray(new)
    ns[4:8] = struct.pack("<I", struct.unpack("<I", st[4:8])[0]
                          + (len(new) - len(st)))
    p.raw_state = bytes(ns)
    return p


def factory_patches(category: str | None = None):
    root = next(S.rglob("Factory Presets"))
    if category:
        return sorted((root / category).glob("*.odin"))
    return sorted(root.rglob("*.odin"))


def render_notes(patch_path: Path, notes, dur_s: float,
                 velocity: int = 100, tail_s: float = 0.6) -> np.ndarray:
    from mido import Message
    p = load_patch(patch_path)
    msgs = []
    for n in notes:
        msgs.append(Message("note_on", note=int(n), velocity=velocity,
                            time=0.0))
    for n in notes:
        msgs.append(Message("note_off", note=int(n), velocity=0, time=dur_s))
    y = p(msgs, duration=dur_s + tail_s, sample_rate=SR)
    return y.mean(axis=0) if y.ndim == 2 else y


def render_sequence(patch_path: Path, seq, total_s: float,
                    tail_s: float = 1.0) -> np.ndarray:
    """ONE continuous plugin pass for a whole phrase — the anti-MIDI
    fix: overlapping notes get real legato/glide, envelopes and LFOs
    run across the line instead of retriggering identically per note.

    seq: [(midi_note, t_on_s, dur_s, velocity 1..127)]
    """
    from mido import Message
    p = load_patch(patch_path)
    msgs = []
    for n, t0, d, v in seq:
        msgs.append(Message("note_on", note=int(n),
                            velocity=int(max(1, min(127, v))),
                            time=float(t0)))
        msgs.append(Message("note_off", note=int(n), velocity=0,
                            time=float(t0 + d)))
    msgs.sort(key=lambda m: m.time)
    y = p(msgs, duration=total_s + tail_s, sample_rate=SR)
    return y.mean(axis=0) if y.ndim == 2 else y


if __name__ == "__main__":
    import soundfile as sf
    base = render_notes.__wrapped__ if hasattr(render_notes, "__wrapped__") \
        else None
    p = _plugin()
    from mido import Message
    msgs = [Message("note_on", note=38, velocity=100, time=0.0),
            Message("note_off", note=38, velocity=0, time=1.2)]
    y0 = p(msgs, duration=1.8, sample_rate=SR)
    y0 = y0.mean(axis=0) if y0.ndim == 2 else y0
    patch = factory_patches("Bass")[0]
    y1 = render_notes(patch, [38], 1.2)
    n = min(len(y0), len(y1))
    d = float(np.abs(y0[:n] - y1[:n]).max())
    print(f"patch '{patch.stem}': render diff vs init {d:.4f} "
          f"({'LOADED' if d > 1e-3 else 'NOT LOADED'})")
    yn = y1 / (np.abs(y1).max() + 1e-9)
    sf.write("out/odin2_factory_bass_test.wav",
             (yn * 0.85).astype("float32"), SR)
    print("wrote out/odin2_factory_bass_test.wav")
