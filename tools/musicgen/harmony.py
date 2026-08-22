"""Harmonic identity — progressions as combat forces. DATA ONLY.

Ratified direction (director, 2026-07-14): progressions MEAN something;
harmony fights. Chords are forces acting on home; harmonic rhythm is
the fight's tempo; cadences are kills. Mode is moral register (faith =
dorian/phrygian family; locrian belongs to the Adversary).

A progression = per-bar chord roots (semitones from the bank's home),
each bar optionally subdivided for faster harmonic rhythm. Power-chord
voicing throughout (root + 5th + octave): no thirds, no sentiment,
just force.

Factor identities:
  PRAYER   -> "vigil" (pure pedal; motion = nothing can move you)
  CONTEMPT -> "swagger" (short easy cycles; nothing here threatens)
  STALWART -> "pressure"/"ratchet"/"grind" (forces visit, home wins
              every bar; escalation = harmonic rhythm, not new chords)
"""
from __future__ import annotations

# each entry: bars -> list of (root_semi, beats) cells; meanings logged
PROGRESSIONS = {
    # stillness — PRAYER. One force: home.
    "vigil": dict(
        bars=[[(0, 4)]],
        meaning="the pedal; eternity, vigil, nothing moves you",
        factor="prayer"),
    # swagger — CONTEMPT. Easy cycle, resolves often, walks away.
    "swagger": dict(
        bars=[[(0, 2), (-2, 2)], [(0, 4)]],
        meaning="i-bVII vamp; dismissive strut, everything resolves",
        factor="contempt"),
    # the Phrygian slap — STALWART verse. bII leans on the door.
    "pressure": dict(
        bars=[[(0, 4)], [(1, 2), (0, 2)], [(0, 4)], [(1, 1), (1, 1), (0, 2)]],
        meaning="bII pressing on home; pressure fought off each bar",
        factor="stalwart"),
    # the grim-resolve loop — STALWART chorus. Weight re-earned.
    "ratchet": dict(
        bars=[[(0, 4)], [(-4, 4)], [(-2, 4)], [(0, 4)]],
        meaning="i-bVI-bVII-i; resolve under fire, home re-earned",
        factor="stalwart"),
    # grinding advance — descent.
    "grind": dict(
        bars=[[(0, 4)], [(3, 4)], [(1, 4)], [(0, 4)]],
        meaning="i-bIII-bII-i descent; walls closing / inexorable advance",
        factor="stalwart"),
    # the enemy's shape — tritone stabs, forced back. Adversary color.
    "lunge": dict(
        bars=[[(0, 3), (6, 1)], [(0, 4)]],
        meaning="tritone visits and is beaten back; the Adversary's "
                "interval, always losing",
        factor="stalwart_peak"),
}

POWER = (0, 7, 12)      # power-chord intervals over any root


_MAJOR = (0, 2, 4, 5, 7, 9, 11)
_TARGETS = {
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
}


def recast(events, target: str = "aeolian"):
    """Parallel-mode recast: keep contour, rhythm, and scale DEGREES;
    translate the degree intervals into the target mode. The classical
    fix for a bright-mode tune in a dark score (the menu's major-family
    chants/chorales clash with the album's minor/phrygian register —
    director's ear, 2026-07-14). Non-diatonic pitches map to the
    nearest degree."""
    tgt = _TARGETS[target]
    out = []
    for p, d in events:
        if p is None:
            out.append((None, d))
            continue
        octave, pc = divmod(p, 12)
        deg = min(range(7), key=lambda i: min((pc - _MAJOR[i]) % 12,
                                              (_MAJOR[i] - pc) % 12))
        out.append((octave * 12 + tgt[deg], d))
    return out


def bar_cells(name: str, n_bars: int):
    """Per-bar chord cells for n_bars, cycling the progression's shape.
    -> [[(root_semi, beats), ...] per bar]"""
    shape = PROGRESSIONS[name]["bars"]
    return [shape[b % len(shape)] for b in range(n_bars)]


def roots_16(name: str, n_bars: int):
    """Chord root for every 16th slot — what the riff engine consumes.
    -> list[n_bars*16] of root semitones."""
    out = []
    for bar in bar_cells(name, n_bars):
        for root, beats in bar:
            out.extend([root] * int(beats * 4))
    return out
