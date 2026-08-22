"""Chant transcriptions + pure motif transforms — DATA ONLY.

Extracted from the deleted generation-era melodies.py: these are the
researched, GABC-verified transcriptions (CATHOLIC_SOURCES.md) and the
development transforms. No synthesis imports — this module must never
grow rendering code.
"""
from __future__ import annotations

BAR_STEPS = 16  # 16th-steps per bar
# ---------------------------------------------------------------------------
# Chant-derived motifs (CATHOLIC_SOURCES.md sec 2) -- semitone offsets from
# the chant's own final, captured from real GABC incipits on GregoBase.
# ---------------------------------------------------------------------------
# Dies Irae, "Dies irae, dies illa": F E F D | E C D D, mode I Dorian, final D.
# Semitones from D: F=+3 E=+2 D=0 | E=+2 C=-2(nat. 7th below D) D=0 D=0.
DIES_IRAE_MOTIF = [3, 2, 3, 0, 2, -2, 0, 0]
# Victimae Paschali Laudes: D C D F G F E D, same Dorian family, final D.
VICTIMAE_MOTIF = [0, -2, 0, 3, 5, 3, 2, 0]

# Each motif entry paired with a 16th-step duration (syllabic default: one
# step per note, giving a compact ~half-bar cell -- the "1-2 bar cell" size
# MELODY_CRAFT.md sec 2 specifies for a developable motif).
MOTIF_DUR_STEPS = 2  # each chant syllable -> an 8th note (2 x 16th steps)

# ---------------------------------------------------------------------------
# The COMPLETE Dies Irae first strophe -- the authored phrase seed.
#
# Director's framing (and the entire point of the CATHOLIC_SOURCES.md
# research): the chant IS the human-authored seed phrase the Sol consult
# said a rules-based generator needs (its odds of clearing "finished
# soundtrack" jump from ~15-25% to ~65-80% WITH an authored seed). An
# 800-year-old composed phrase already has contour, cadences, apex, and
# breathing built in -- the earlier approach of shredding the 8-note
# incipit into transform fodder used 5% of the seed and generated the
# other 95%, which was backwards.
#
# Captured from the full GABC (GregoBase chant 1198, "Dies irae",
# Sequentia, mode 1; book: Graduale Romanum 1961 p.96 / Liber Usualis
# 1961 p.1810; transcriber credited in the GABC header: Andrew Hinkley;
# https://gregobase.selapa.net/download.php?id=1198&format=gabc&elem=1):
#
#   (c4) DI(f)es(e) i(f)rae,(d) di(e)es(c) il(d)la,(d.) (;)
#   Sol(f)vet(fg) sae(fe)clum(dc) in(e) fa(f)vil(e)la:(d.) (;)
#   Te(a)ste(cd) Da(d)vid(dc) cum(e) Si(f)byl(e)la.(d.) (::)
#
# Pitch-letter mapping verified against TWO independently known phrases
# (the famous F-E-F-D incipit AND the later "Tu(h)ba(j)" = A4-C5 register
# jump), so in this transcription letters = literal note names:
# a=A3 ... c=C4 d=D4 e=E4 f=F4 g=G4 h=A4 j=C5.
#
# Encoding: (semitones_from_D_final, duration_in_16th_steps); None = rest
# (the chant's own breath marks (;)). Syllable = quarter note (4 steps),
# two-note neumes (fg, fe, dc, cd) split their syllable into two 8ths,
# mora-dotted line finals (d.) hold longer. Three 8-syllable lines at
# 140bpm = an exactly 8-bar authored period, breathing included.
DIES_IRAE_STROPHE = [
    # Line 1: Di-es i-rae, di-es il-la, (antecedent -- the famous statement)
    (3, 4), (2, 4), (3, 4), (0, 4),
    (2, 4), (-2, 4), (0, 4), (0, 8),
    (None, 4),                                  # breath (;)
    # Line 2: Sol-vet sae-clum in fa-vil-la: (answering line, adds the G apex)
    (3, 4), (3, 2), (5, 2), (3, 2), (2, 2), (0, 2), (-2, 2),
    (2, 4), (3, 4), (2, 4), (0, 8),
    (None, 4),                                  # breath (;)
    # Line 3: Te-ste Da-vid cum Si-byl-la. (consequent -- dips to low A, closes)
    (-5, 4), (-2, 2), (0, 2), (0, 4), (0, 2), (-2, 2),
    (2, 4), (3, 4), (2, 4), (0, 12),
    (None, 8),                                  # full stop (::), phrase tail
]
assert sum(d for _, d in DIES_IRAE_STROPHE) == 8 * BAR_STEPS, \
    "Dies Irae strophe must be exactly 8 bars on the 140bpm 16th grid"


# ---------------------------------------------------------------------------
# Motivic development transforms (MELODY_CRAFT.md sec 2)
# ---------------------------------------------------------------------------

def sequence(motif, shift_semitones):
    """Repeat the motif transposed -- same shape, different pitch level."""
    return [s + shift_semitones for s in motif]


def invert(motif):
    """Flip each interval's direction around the motif's first note."""
    root = motif[0]
    return [root - (s - root) for s in motif]


def fragment(motif, n, from_end=False):
    """Take only the head (or tail) of a motif -- used to build tension via
    rhythmic density near a phrase's climax/cadence."""
    return motif[-n:] if from_end else motif[:n]


def retrograde(motif):
    """Reverse the motif -- a fourth mechanical transform, used sparingly
    for the consequent phrase's divergence point."""
    return list(reversed(motif))


# ---------------------------------------------------------------------------
# Harmony-aware snapping (MELODY_CRAFT.md sec 4/5): bias strong-beat/cadence
# notes onto stable scale degrees of the active mode instead of leaving an
# arbitrary chant interval unresolved against the underlying root.
# ---------------------------------------------------------------------------

def sequence(motif, shift_semitones):
    """Repeat the motif transposed -- same shape, different pitch level."""
    return [s + shift_semitones for s in motif]


def invert(motif):
    """Flip each interval's direction around the motif's first note."""
    root = motif[0]
    return [root - (s - root) for s in motif]


def fragment(motif, n, from_end=False):
    """Take only the head (or tail) of a motif -- used to build tension via
    rhythmic density near a phrase's climax/cadence."""
    return motif[-n:] if from_end else motif[:n]


def retrograde(motif):
    """Reverse the motif -- a fourth mechanical transform, used sparingly
    for the consequent phrase's divergence point."""
    return list(reversed(motif))
