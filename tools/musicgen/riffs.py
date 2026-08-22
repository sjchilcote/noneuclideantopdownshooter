"""Riff-ification — historical melody -> genre-native delivery. DATA ONLY.

The chant transcriptions are the SOURCE, not the performance. Direct
playback reads as "MIDI samples of historical melodies" (director,
2026-07-14). This module holds the delivery transforms:

- diminish: double/quad-time the line (chant quarters -> 8ths/16ths).
- riff_16: the Gordon/album idiom — a continuous 16th motor of
  palm-muted PEDAL notes with the melody's pitches landing as OPEN
  accents on a syncopated slot template. The tune's pitch order is
  preserved; the rhythm becomes the genre's.
- lead_phrase: diminished melody with anticipation pushes and held
  phrase-peaks — a lead performance, not a recitation.

Events: (semitone_from_final | None, dur_16th_steps) as everywhere.
riff_16 output adds articulation: (semi, steps, art) with art in
{"open", "mute"} for the renderer to map (open chug vs palm-mute,
full vs ghost velocity).
"""
from __future__ import annotations

# syncopated accent templates (16th slots per bar) — the album's push
# patterns; pick per section for variety
ACCENTS_A = (0, 3, 6, 10, 12)          # push-heavy (drop-feel)
ACCENTS_B = (0, 4, 7, 10, 14)          # driving with backbeat lean
ACCENTS_C = (0, 2, 6, 8, 11, 14)       # busier, peak sections


def pitches(events):
    return [p for p, _ in events if p is not None]


def diminish(events, factor: int = 2):
    """Compress durations by factor (min one 16th); rests shrink too."""
    return [(p, max(1, d // factor)) for p, d in events]


def riff_16(events, n_bars: int = 4, accents=ACCENTS_A, pedal: int = 0,
            bar_steps: int = 16, chord_roots=None):
    """Pedal-motor riff: every 16th slot sounds.

    With chord_roots (per-16th root list from harmony.roots_16), the
    wall is the HARMONIC-RHYTHM instrument: accent slots punch the
    CURRENT CHORD (open), the motor chugs the current root (muted) —
    the melody belongs to the foreground voices, not the wall
    (<=1-foreground law). Without chord_roots, accents walk the melody
    (legacy demo mode)."""
    mel = pitches(events)
    out = []
    mi = 0
    for bar in range(n_bars):
        slot = 0
        while slot < bar_steps:
            k = bar * bar_steps + slot
            root = chord_roots[k % len(chord_roots)] if chord_roots \
                else pedal
            if slot in accents:
                p = root if chord_roots else mel[mi % len(mel)]
                mi += 1
                nxt = min([a for a in accents if a > slot],
                          default=bar_steps)
                steps = 2 if nxt - slot >= 2 else 1
                out.append((p, steps, "open"))
                slot += steps
            else:
                out.append((root if chord_roots else pedal, 1, "mute"))
                slot += 1
    return out


def lead_phrase(events, factor: int = 2, push_every: int = 3,
                hold_top: bool = True):
    """Lead delivery: diminished line, every push_every-th note
    anticipated a 16th early (borrowing from the previous note), the
    line's highest note held double (the phrase peak breathes)."""
    dim = diminish(events, factor)
    mel = [(p, d) for p, d in dim if p is not None]
    if not mel:
        return dim
    top = max(p for p, _ in mel)
    out = []
    for i, (p, d) in enumerate(mel):
        d2 = d
        if hold_top and p == top:
            d2 = d * 2
        if i % push_every == push_every - 1 and out and out[-1][1] > 1:
            out[-1] = (out[-1][0], out[-1][1] - 1)   # steal a 16th
            d2 += 1                                   # land early, ring
        out.append((p, d2))
    return out
