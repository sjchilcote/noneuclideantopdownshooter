"""Minimal ctypes VST2 host — offline rendering of native Linux .so
synths (Vitalium, Tyrell N6...) that pedalboard (VST3-only) can't load.

VST2 ABI essentials (aeffect.h, public knowledge for decades):
  entry:  AEffect* VSTPluginMain(audioMasterCallback)
  AEffect fields used: magic 'VstP', dispatcher, processReplacing,
  numInputs/numOutputs/numPrograms/numParams, flags.
  dispatcher opcodes: effOpen=0, effClose=1, effSetProgram=2,
  effGetProgramName=5, effGetProgramNameIndexed=29, effSetSampleRate=10,
  effSetBlockSize=11, effMainsChanged=12, effProcessEvents=25,
  effSetChunk=24, effGetChunk=23, effCanDo=51.
  audioMaster opcodes answered: audioMasterVersion=1 -> 2400,
  audioMasterGetSampleRate=16, audioMasterGetBlockSize=17,
  audioMasterCurrentId=2, audioMasterGetTime=7 -> NULL.

Offline only, one instance per process is safest; never used in-game.
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path

import numpy as np

SR = 44100
BLOCK = 512

audioMasterCallback = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_int32,
                                  C.c_int32, C.c_ssize_t, C.c_void_p,
                                  C.c_float)
DispatcherProc = C.CFUNCTYPE(C.c_ssize_t, C.c_void_p, C.c_int32,
                             C.c_int32, C.c_ssize_t, C.c_void_p,
                             C.c_float)
ProcessProc = C.CFUNCTYPE(None, C.c_void_p,
                          C.POINTER(C.POINTER(C.c_float)),
                          C.POINTER(C.POINTER(C.c_float)), C.c_int32)


class AEffect(C.Structure):
    _fields_ = [
        ("magic", C.c_int32),
        ("dispatcher", DispatcherProc),
        ("process", C.c_void_p),
        ("setParameter", C.c_void_p),
        ("getParameter", C.c_void_p),
        ("numPrograms", C.c_int32),
        ("numParams", C.c_int32),
        ("numInputs", C.c_int32),
        ("numOutputs", C.c_int32),
        ("flags", C.c_int32),
        ("resvd1", C.c_ssize_t),
        ("resvd2", C.c_ssize_t),
        ("initialDelay", C.c_int32),
        ("realQualities", C.c_int32),
        ("offQualities", C.c_int32),
        ("ioRatio", C.c_float),
        ("object", C.c_void_p),
        ("user", C.c_void_p),
        ("uniqueID", C.c_int32),
        ("version", C.c_int32),
        ("processReplacing", ProcessProc),
    ]


class VstMidiEvent(C.Structure):
    _fields_ = [("type", C.c_int32), ("byteSize", C.c_int32),
                ("deltaFrames", C.c_int32), ("flags", C.c_int32),
                ("noteLength", C.c_int32), ("noteOffset", C.c_int32),
                ("midiData", C.c_char * 4), ("detune", C.c_char),
                ("noteOffVelocity", C.c_char), ("reserved1", C.c_char),
                ("reserved2", C.c_char)]


def _master(effect, opcode, index, value, ptr, opt):
    if opcode == 1:          # audioMasterVersion
        return 2400
    if opcode == 16:         # sample rate
        return int(SR)
    if opcode == 17:         # block size
        return BLOCK
    return 0


_MASTER = audioMasterCallback(_master)


class Vst2Synth:
    def __init__(self, so_path: str | Path):
        self.lib = C.CDLL(str(so_path))
        entry = None
        for name in ("VSTPluginMain", "main"):
            try:
                entry = getattr(self.lib, name)
                break
            except AttributeError:
                continue
        entry.restype = C.POINTER(AEffect)
        entry.argtypes = [audioMasterCallback]
        self.ae = entry(_MASTER)
        assert self.ae and self.ae.contents.magic == 0x56737450, \
            "not a VST2 plugin (magic mismatch)"
        e = self.ae.contents
        self.n_out = e.numOutputs
        self.n_in = e.numInputs
        d = e.dispatcher
        d(self.ae, 0, 0, 0, None, 0.0)                 # effOpen
        d(self.ae, 10, 0, 0, None, float(SR))          # setSampleRate
        d(self.ae, 11, 0, BLOCK, None, 0.0)            # setBlockSize
        d(self.ae, 12, 0, 1, None, 0.0)                # mainsChanged on

    def set_program(self, n: int):
        self.ae.contents.dispatcher(self.ae, 2, 0, int(n), None, 0.0)

    def program_names(self):
        e = self.ae.contents
        out = []
        buf = C.create_string_buffer(256)
        for i in range(e.numPrograms):
            e.dispatcher(self.ae, 29, i, 0, buf, 0.0)  # nameIndexed
            out.append(buf.value.decode("latin1"))
        return out

    def set_chunk(self, data: bytes):
        buf = C.create_string_buffer(data, len(data))
        self.ae.contents.dispatcher(self.ae, 24, 0, len(data), buf, 0.0)

    def _send_midi(self, events):
        """events: [(delta_frames, bytes3)] within the CURRENT block."""
        n = len(events)
        if not n:
            return
        class VstEvents(C.Structure):
            _fields_ = [("numEvents", C.c_int32),
                        ("reserved", C.c_ssize_t),
                        ("events", C.c_void_p * n)]
        evs = [VstMidiEvent(type=1, byteSize=C.sizeof(VstMidiEvent),
                            deltaFrames=df, flags=1,
                            midiData=bytes(md) + b"\0")
               for df, md in events]
        holder = VstEvents(numEvents=n)
        for i, ev in enumerate(evs):
            holder.events[i] = C.cast(C.pointer(ev), C.c_void_p)
        self.ae.contents.dispatcher(self.ae, 25, 0, 0,
                                    C.byref(holder), 0.0)

    def render(self, seq, total_s: float, tail_s: float = 1.0):
        """seq: [(midi_note, t_on_s, dur_s, vel)] -> float64 mono."""
        msgs = []
        for note, t0, dur, vel in seq:
            msgs.append((t0, bytes([0x90, int(note), int(vel)])))
            msgs.append((t0 + dur, bytes([0x80, int(note), 0])))
        msgs.sort(key=lambda m: m[0])
        n_total = int((total_s + tail_s) * SR)
        out = np.zeros(n_total)
        n_ch = max(1, self.n_out)
        bufs = [(C.c_float * BLOCK)() for _ in range(n_ch)]
        out_ptrs = (C.POINTER(C.c_float) * n_ch)(
            *[C.cast(b, C.POINTER(C.c_float)) for b in bufs])
        in_ch = max(1, self.n_in)
        zeros = [(C.c_float * BLOCK)() for _ in range(in_ch)]
        in_ptrs = (C.POINTER(C.c_float) * in_ch)(
            *[C.cast(z, C.POINTER(C.c_float)) for z in zeros])
        mi = 0
        pos = 0
        while pos < n_total:
            block_events = []
            while mi < len(msgs) and msgs[mi][0] * SR < pos + BLOCK:
                df = max(0, int(msgs[mi][0] * SR) - pos)
                block_events.append((df, msgs[mi][1]))
                mi += 1
            self._send_midi(block_events)
            self.ae.contents.processReplacing(self.ae, in_ptrs,
                                              out_ptrs, BLOCK)
            n = min(BLOCK, n_total - pos)
            acc = np.zeros(n)
            for b in bufs:
                acc += np.frombuffer(b, dtype=np.float32,
                                     count=n).astype(np.float64)
            out[pos:pos + n] = acc / n_ch
            pos += BLOCK
        return out

    def close(self):
        try:
            self.ae.contents.dispatcher(self.ae, 12, 0, 0, None, 0.0)
            self.ae.contents.dispatcher(self.ae, 1, 0, 0, None, 0.0)
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    import soundfile as sf
    so = sys.argv[1]
    s = Vst2Synth(so)
    e = s.ae.contents
    print(f"loaded: id={e.uniqueID:#x} programs={e.numPrograms} "
          f"params={e.numParams} outs={e.numOutputs}")
    names = s.program_names()
    print("programs:", names[:8])
    x = s.render([(50, 0.0, 1.5, 100), (57, 0.0, 1.5, 100)], 2.0)
    peak = float(np.abs(x).max())
    print(f"render peak {peak:.4f} ({'SOUND' if peak > 1e-4 else 'SILENT'})")
    if peak > 1e-4:
        x = x / peak * 0.85
        sf.write("out/vst2_host_test.wav", x.astype("float32"), SR)
        print("wrote out/vst2_host_test.wav")
