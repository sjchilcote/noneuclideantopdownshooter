"""Dexed headless host — real DX7 factory voices, selected for real.

Dexed 1.0.1 (GPL) Linux VST3. The `program` parameter lists the 32
factory-cartridge voices but the engine ignores parameter-set changes
headless; the documented state XML (`<dexedState currentProgram=... >`
with the cartridge as a sysex blob) is authoritative. State nesting is
the same JUCE sandwich mapped on Odin2: outer VC2!+XML IComponent →
JUCE-base64 → inner VC2!+len+dexedState XML. We decode, edit
currentProgram (and later: swap the sysex blob for other DX7 cartridges
— the entire classic ROM library), re-encode, assign raw_state.
"""
from __future__ import annotations

import re
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np

SR = 44100
S = Path("/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter"
         "/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/musicgen/dexed")
VST = S / "Dexed.vst3"
_TABLE = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def _jenc(data: bytes) -> bytes:
    nbits = len(data) * 8
    out = []
    for i in range((nbits + 5) // 6):
        v = 0
        for b in range(6):
            k = i * 6 + b
            if k < nbits and (data[k >> 3] >> (k & 7)) & 1:
                v |= 1 << b
        out.append(_TABLE[v])
    return (str(len(data)) + "." + "".join(out)).encode()


def _jdec(enc: str) -> bytes:
    size_s, data = enc.split(".", 1)
    size = int(size_s)
    out = bytearray(size)
    for i, ch in enumerate(data):
        v = _TABLE.index(ch)
        for b in range(6):
            k = i * 6 + b
            if k < size * 8 and (v >> b) & 1:
                out[k >> 3] |= 1 << (k & 7)
    return bytes(out)


@lru_cache(maxsize=1)
def _plugin():
    import pedalboard
    return pedalboard.load_plugin(str(VST))


def _cartridge():
    """(outer_state, xml_span, sysex_span_in_xml, sysex_bytes)."""
    p = _plugin()
    outer = bytes(p.raw_state)
    m = re.search(rb"<IComponent>(.*?)</IComponent>", outer, re.S)
    inner = _jdec(m.group(1).decode())
    assert inner[:4] == b"VC2!", inner[:8]
    xml = inner[8:]
    ms = re.search(rb'sysex="([^"]*)"', xml)
    syx = _jdec(ms.group(1).decode())
    assert syx[:6] == b"\xf0\x43\x00\x09\x20\x00" and len(syx) == 4104, \
        (len(syx), syx[:6].hex())
    return outer, m, xml, ms, syx


def program_names():
    _, _, _, _, syx = _cartridge()
    return [syx[6 + i * 128 + 118:6 + i * 128 + 128]
            .decode("ascii", "replace").strip() for i in range(32)]


def unpack_voice(pv: bytes) -> bytes:
    """DX7 packed voice (128 B) -> unpacked VCED (155 B).

    Validated byte-for-byte against Dexed's own base64:program blob for
    factory voice 0.
    """
    out = bytearray()
    for op in range(6):
        b = pv[op * 17:(op + 1) * 17]
        out += b[:11]
        out += bytes([b[11] & 3, (b[11] >> 2) & 3,        # curves L R
                      b[12] & 7,                          # rate scaling
                      b[13] & 3, (b[13] >> 2) & 7,        # AMS, KVS
                      b[14],                              # output level
                      b[15] & 1, (b[15] >> 1) & 31,       # mode, coarse
                      b[16], (b[12] >> 3) & 15])          # fine, detune
    g = pv[102:]
    out += g[:8]                                          # pitch EG
    out += bytes([g[8] & 31, g[9] & 7, (g[9] >> 3) & 1])  # alg, fb, oks
    out += g[10:14]                                       # LFO s/d/pmd/amd
    out += bytes([g[14] & 1, (g[14] >> 1) & 7,            # lfo sync, wave
                  (g[14] >> 4) & 7, g[15]])               # pms, transpose
    out += g[16:26]                                       # name
    return bytes(out)


def set_program(n: int):
    """Make factory voice n the SOUNDING voice.

    The engine renders from dexedBlob's base64:program (unpacked current
    voice), not from the cartridge or the `program` parameter — so graft
    BOTH: voice n reordered into cartridge slot 0 (checksum fixed) and
    voice n unpacked into the program blob (its 6-byte tail — op switches
    etc. — kept verbatim).
    """
    p = _plugin()
    outer, m, xml, ms, syx = _cartridge()
    data = bytearray(syx[6:6 + 4096])
    n = int(n)
    v = bytes(data[n * 128:(n + 1) * 128])
    del data[n * 128:(n + 1) * 128]
    data[0:0] = v
    chk = (-sum(data)) & 0x7F
    new_syx = syx[:6] + bytes(data) + bytes([chk, 0xF7])
    new_xml = xml[:ms.start(1)] + _jenc(new_syx) + xml[ms.end(1):]
    mp = re.search(rb'base64:program="([^"]*)"', new_xml)
    old_prog = _jdec(mp.group(1).decode())
    new_prog = unpack_voice(v) + old_prog[155:]
    new_xml = (new_xml[:mp.start(1)] + _jenc(new_prog)
               + new_xml[mp.end(1):])
    new_inner = b"VC2!" + struct.pack("<I", len(new_xml)) + new_xml
    enc = _jenc(new_inner)
    new_outer = outer[:m.start(1)] + enc + outer[m.end(1):]
    no = bytearray(new_outer)
    no[4:8] = struct.pack("<I", struct.unpack("<I", outer[4:8])[0]
                          + (len(new_outer) - len(outer)))
    p.raw_state = bytes(no)
    return p


def render_notes(program: int, notes, dur_s: float, velocity: int = 100,
                 tail_s: float = 0.8) -> np.ndarray:
    from mido import Message
    p = set_program(program)
    msgs = []
    for nn in notes:
        msgs.append(Message("note_on", note=int(nn), velocity=velocity,
                            time=0.0))
    for nn in notes:
        msgs.append(Message("note_off", note=int(nn), velocity=0,
                            time=dur_s))
    y = p(msgs, duration=dur_s + tail_s, sample_rate=SR)
    return y.mean(axis=0) if y.ndim == 2 else y


def render_sequence(program: int, seq, total_s: float,
                    tail_s: float = 1.0) -> np.ndarray:
    """One continuous pass for a whole phrase (see odin2_host)."""
    from mido import Message
    p = set_program(program)
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
    names = program_names()
    print("factory voices:", names[:8], "...")
    a = render_notes(0, [50], 1.0)
    b = render_notes(4, [50], 1.0)
    n = min(len(a), len(b))
    d = float(np.abs(a[:n] - b[:n]).max())
    print(f"program 0 vs 4 diff: {d:.4f} "
          f"({'PRESETS SWITCH HEADLESS' if d > 1e-3 else 'STILL STUCK'})")
    if d > 1e-3:
        yn = b / (np.abs(b).max() + 1e-9)
        sf.write("out/dexed_factory_test.wav", (yn * 0.85).astype("float32"),
                 SR)
        print(f"wrote out/dexed_factory_test.wav (voice: {names[4]!r})")
