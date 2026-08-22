"""Surge XT voice bank — the album's synth palette, from the real synth.

The raw block analyses name the album's synth voices repeatedly:
"detuned sawtooth lead" / "soaring, detuned saw-wave lead" (30+ blocks),
"growling FM bass", "buzzsaw / tightly gated rhythm synth", dark drones.
Round 1-2 tried to fake these with naive numpy oscillators — the exact
Cubase-template failure. The audit proved Surge XT loads headlessly via
pedalboard (599 params, correct pitch, 224x realtime); these patches are
designed on it from Init via parameters.

Offline asset-authoring only (GPL tools never ship in the game).

    uv run python tools/musicgen/surge_bank.py   # render + probe the bank
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

SR = 44100
VST = Path("/tmp/claude-1000/-home-login-PycharmProjects-noneuclideantopdownshooter"
           "/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b/scratchpad/musicgen"
           "/vst3/Surge XT.vst3")


@lru_cache(maxsize=8)
def _plugin_for(patch: str):
    """One dedicated Surge instance per patch, params set ONCE. Switching
    patches on a shared instance corrupted the first phrase render after
    an FM2->Classic osc-type change (measured: conformance 0.0 with
    correct-looking params); per-patch instances remove switching
    entirely."""
    import pedalboard
    p = pedalboard.load_plugin(str(VST))
    _set(p, **PATCHES[patch])
    return p


def _plugin():
    import pedalboard
    return pedalboard.load_plugin(str(VST))


def _set(p, **params):
    for k, v in params.items():
        try:
            setattr(p, k, v)
        except Exception as e:  # noqa: BLE001 — a bad param name must be loud
            raise RuntimeError(f"param {k}={v}: {e}") from e


PATCHES = {
    # The album lead: wide detuned saw stack, open-but-dark filter, a
    # touch of waveshaper grit. "Buzzy, slightly unstable, soaring."
    "lead_saw": dict(
        a_osc_1_type="Classic", a_osc_1_shape=0.0,
        a_osc_1_unison_voices="7 voices", a_osc_1_unison_detune="32.00 cents",
        a_filter_1_type="LP 24 dB", a_filter_1_cutoff=52.0,
        a_filter_1_resonance=0.16,
        # the panel's unanimous fix: MOVEMENT — filter EG sweep + vibrato
        a_filter_1_feg_mod_amount="33.98 semitones",
        a_lfo_1_rate="5.436 Hz", a_lfo_1_amplitude=0.06,
        a_portamento="24.3 ms",
        a_waveshaper_type="Hard", a_waveshaper_drive=11.0,
        a_amp_eg_attack="12.0 ms", a_amp_eg_release="251.0 ms",
    ),
    # The growling FM bass: FM2 osc, short bite, dark filter.
    "fm_bass": dict(
        a_osc_1_type="FM2", a_osc_1_shape=0.35,
        a_filter_1_type="LP 24 dB", a_filter_1_cutoff=52.0,
        a_filter_1_resonance=0.18,
        a_waveshaper_type="Hard", a_waveshaper_drive=9.0,
        a_amp_eg_attack="4.0 ms", a_amp_eg_release="179.9 ms",
    ),
    # The buzzsaw wall: massive unison saw, meant to be pattern-gated.
    "buzzsaw_wall": dict(
        a_osc_1_type="Classic", a_osc_1_shape=0.0,
        a_osc_1_unison_voices="9 voices", a_osc_1_unison_detune="55.00 cents",
        a_filter_1_type="LP 24 dB", a_filter_1_cutoff=60.0,
        a_filter_1_resonance=0.08,
        a_waveshaper_type="Hard", a_waveshaper_drive=8.0,
        a_amp_eg_attack="6.0 ms", a_amp_eg_release="119.9 ms",
    ),
    # Dark drone: slow, low, breathing.
    "drone": dict(
        a_osc_1_type="Classic", a_osc_1_shape=0.15,
        a_osc_1_unison_voices="5 voices", a_osc_1_unison_detune="18.00 cents",
        a_filter_1_type="LP 24 dB", a_filter_1_cutoff=44.0,
        a_filter_1_resonance=0.22,
        a_amp_eg_attack="902.5 ms", a_amp_eg_release="1.40 s",
    ),
}


def render_notes(patch: str, notes, dur_s: float, sr: int = SR,
                 tail_s: float = 0.4, velocity: int = 110) -> np.ndarray:
    """Render simultaneous MIDI notes with a patch. notes = midi numbers."""
    from mido import Message
    p = _plugin_for(patch)
    p.reset()
    msgs = []
    for n in notes:
        msgs.append(Message("note_on", note=int(n),
                            velocity=int(max(1, min(127, velocity))),
                            time=0.0))
    for n in notes:
        msgs.append(Message("note_off", note=int(n), velocity=0,
                            time=dur_s))
    audio = p(msgs, duration=dur_s + tail_s, sample_rate=sr)
    return audio.mean(axis=0) if audio.ndim == 2 else audio


def render_phrase(patch: str, events, step_s: float, sr: int = SR,
                  base_midi: int = 50, humanize_s: float = 0.008,
                  vel_map=None, rng=None) -> np.ndarray:
    """Render a PHRASE as one continuous MIDI performance — legato inside
    the plugin (portamento works, envelopes connect), per-note VELOCITY
    from the phrase contour, humanized timing. events = (semi|None,
    steps). The panel's tells ('stiff, fully quantized, zero velocity
    variation') die here, at the performance layer."""
    import numpy as _np
    from mido import Message
    rng = rng or _np.random.default_rng(0)
    p = _plugin_for(patch)
    p.reset()
    msgs = []
    t = 0.0
    semis = [sv for sv, _ in events if sv is not None]
    apex, lo = (max(semis), min(semis)) if semis else (0, 0)
    total = sum(d for _, d in events) * step_s
    for sv, d in events:
        dur = d * step_s
        if sv is not None:
            j = float(rng.normal(0, humanize_s))
            v = 96
            if vel_map is not None:
                v = vel_map(sv)
            elif apex > lo:
                v = int(84 + 34 * (sv - lo) / (apex - lo)
                        + rng.normal(0, 4))
            on_t = max(0.0, t + j)
            off_t = max(on_t + 0.01, t + dur * 0.94 + j)
            msgs.append(Message("note_on", note=int(base_midi + sv),
                                velocity=int(max(1, min(127, v))),
                                time=on_t))
            msgs.append(Message("note_off", note=int(base_midi + sv),
                                velocity=0, time=off_t))
        t += dur
    msgs.sort(key=lambda m: m.time)
    audio = p(msgs, duration=total + 0.5, sample_rate=sr)
    return audio.mean(axis=0) if audio.ndim == 2 else audio


D2_MIDI, D3_MIDI, D4_MIDI = 38, 50, 62


def main():
    import soundfile as sf
    out = VST.parents[1] / "surge_bank"
    out.mkdir(exist_ok=True)
    tests = [
        ("lead_saw", [D4_MIDI], 2.0),
        ("fm_bass", [D2_MIDI], 1.2),
        ("buzzsaw_wall", [D2_MIDI, D2_MIDI + 7], 2.0),
        ("drone", [D2_MIDI, D2_MIDI + 12], 4.0),
    ]
    for name, notes, dur in tests:
        y = render_notes(name, notes, dur)
        peak = np.abs(y).max()
        y = y / (peak + 1e-9) * 0.85
        f = np.abs(np.fft.rfft(y * np.hanning(len(y))))
        fr = np.fft.rfftfreq(len(y), 1 / SR)
        sel = (fr > 30) & (fr < 2000)
        sf.write(str(out / f"{name}.wav"), y.astype(np.float32), SR)
        print(f"{name:14s} peak {peak:.3f}  f_peak {fr[sel][np.argmax(f[sel])]:7.1f} Hz")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
