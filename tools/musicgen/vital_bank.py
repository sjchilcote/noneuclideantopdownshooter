"""Vital goldmine — slot assignments + Vitalium render helpers.

Director's ruling 2026-07-15: ALL synth voices come from the Vital
banks ("if we use Vital patches that add their own detailed character,
the rudimentary nature of our sources becomes an asset rather than a
problem"). Delay Lama (the album's voice), the TR-909 kit, and the chug
wall stay — they're samples/the vocal, not synths.

SLOTS maps slot -> (bank, preset stem). Filled from preset_scout
results + name-flavor fit; every choice's runners-up live in the scout
scores JSON (the decision log's alternates).
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

S = Path("/tmp/claude-1000/-home-login-PycharmProjects-"
         "noneuclideantopdownshooter/6f0b5b45-ac47-4526-b96e-c9dc90e4fe0b"
         "/scratchpad/musicgen")
BANKS = {
    "tngkaos": S / "tngkaos/TngKaos/Presets",
    "5years": S / "fiveyears/5 Years of Vital/Presets",
}
SO = S / "vital/VitalInstaller/lib/vst/Vital.so"   # REAL Vital
#     (Vitalium = 1.0.x engine, mangles 1.5.x presets to a
#      fallback tone — director caught it by ear 2026-07-15)

# slot -> (bank, preset). ALL drawn from director_picks.json
# (picks-first law); name-flavor fit by me, his lab bake-off is the
# gate. Runners-up = the rest of the picks file.
SLOTS: dict[str, tuple[str, str]] = {
    # the WALL: synth (director 2026-07-15: the chug sample is scuffed,
    # internal hard cuts — "find a suitable synthesizer"); rendered
    # through the guitar amp+cab chain, double-tracked with per-take
    # micro-offsets. Alternates: Reso Poly, Nicotine, Knowledge.
    "wall": ("5years", "Supersync"),
    # core basses
    "bass_deep": ("5years", "Heavy"),
    "bass_fm": ("5years", "FM Bass 1"),
    # enemy bass cells — each kind finally tellable by TIMBRE
    "cell_mite": ("5years", "Short Pulse Bass"),
    "cell_husk": ("5years", "Rubber Bass"),
    "cell_spitter": ("5years", "Acid Bass 3"),
    "cell_shrieker": ("5years", "Rave Alarm"),
    "cell_brute": ("tngkaos", "Fat Bass"),
    "cell_warden": ("5years", "Sub Fall"),
    "cell_flicker": ("5years", "Malfunction"),
    # weapon leads
    "lead_knife": ("5years", "Elastic"),
    "lead_pistol": ("5years", "Hypercube PLUCK"),
    "lead_smg": ("5years", "Techtonics"),
    "lead_shotgun": ("5years", "Splatter"),
    "lead_rail": ("5years", "Magnetic Separation"),
    "lead_lightning": ("5years", "Tesla Coil"),
    "lead_tau": ("5years", "Exabyte"),
    "lead_hole": ("5years", "Fifth Revival"),
    "lead_scrap": ("tngkaos", "Dirty  Fonk"),
    "lead_gland": ("5years", "Tuvan"),
    # holy / defiant voices
    "choir": ("5years", "Choir Pad"),
    "organ_holy": ("5years", "Heaven's Gate"),
    "organ_defiant": ("5years", "Hoover"),   # Medieval Punk = arpy pad, director 2026-07-15
    # stage beds by descent
    "bed_t1": ("5years", "Machine Drone"),  # measured sustain 0.84; the
    #   "does not loop" report was the demo clip's dying release tail
    "bed_t2": ("tngkaos", "Dark mood 1"),
    "bed_t3": ("5years", "Distress Signal"),
    "bed_t4": ("5years", "Evil"),
}


def preset_path(bank: str, stem: str) -> Path:
    p = BANKS[bank] / f"{stem}.vital"
    if not p.exists():
        raise FileNotFoundError(p)
    return p


@lru_cache(maxsize=1)
def _synth():
    from vst2_host import Vst2Synth
    return Vst2Synth(SO)


_loaded: list[str] = [""]


def render_seq(bank: str, stem: str, seq, total_s: float,
               tail_s: float = 1.0) -> np.ndarray:
    """One continuous pass of a note sequence through the preset.
    seq: [(midi, t_on_s, dur_s, vel)]."""
    syn = _synth()
    key = f"{bank}/{stem}"
    if _loaded[0] != key:
        syn.set_chunk(preset_path(bank, stem).read_bytes() + b"\0")
        _loaded[0] = key
    return syn.render(seq, total_s, tail_s)


def render_notes(bank: str, stem: str, notes, dur_s: float,
                 velocity: int = 100, tail_s: float = 0.8) -> np.ndarray:
    seq = [(int(n), 0.0, dur_s, velocity) for n in notes]
    return render_seq(bank, stem, seq, dur_s, tail_s)
