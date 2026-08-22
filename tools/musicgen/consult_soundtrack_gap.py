#!/usr/bin/env python3
"""tools/musicgen/consult_soundtrack_gap.py

Round 2, director's request: consult an external model (GPT Sol, via
consult_machinery.py's reusable streaming engine -- see that file's header
for what's reusable vs. diet_app-specific) with everything tried so far,
asking for concrete advice on bridging the gap from "MIDI + samples" to a
releasable game soundtrack. Director's verdict on the round-2 draft
(verbatim): "it does sound like music now, but the melodies are just
random child-playing-with-a-keyboard tunes that don't fit the situation,
and it just sounds like MIDI + some shitty samples, not an actual
finished game soundtrack."

This script only produces the consult; it does not implement anything.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import consult_machinery as cm  # noqa: E402

HERE = Path(__file__).resolve().parent

PRODUCT_CONTEXT = """
PERIHELION is a non-Euclidean Teleglitch-like survival shooter with a strict
Catholic register (Aquinas references, Latin, "Encarta Aeterna" branding).
We are building a dynamic in-game music system: industrial-metal-adjacent,
modeled on a specific reference album ("With the Machine, Against the
Machine" -- full 72-block Gemini close-listening analysis already done,
see PLAYBOOK.md), fused with a Gregorian-chant-derived cantus firmus
(strictly Catholic tradition, not Protestant -- see CATHOLIC_SOURCES.md).

We are a small team building this with Python/numpy DSP + fluidsynth +
free/CC-licensed real-world samples -- NO paid sample libraries, NO
professional composer, NO DAW/manual arrangement pass. Everything is
generated offline by scripts.
"""

ASK = """
## Where we are

Round 1 (a synthesis-only draft: fully synthesized instruments -- kick,
snare, hats, bass, lead, chug -- sequenced by a naive fixed-pattern-per-
intensity-level engine) was rejected by the human director in one sentence:
"sounds like S H I T - like a parody of what would happen if you asked an
AI to make music, AWFUL." The automated quality judge (Gemini via
OpenRouter, comparing clips against real album excerpts) had scored that
same draft 0.85 -- i.e. our own judge was worthless for this failure mode,
and remains suspect.

Round 2 (this round) changed three things based on directorial orders:
1. Distilled Mick Gordon's GDC "DOOM: Behind the Music" talk (read the FULL
   transcript directly, twice -- once via a summarizing subagent that
   produced a genericized, partly-wrong "audio production tips" listicle,
   corrected after the director caught it) into GORDON_METHOD.md, and built
   gordon_chain.py: parallel signal-processing paths (saturation, phaser-ish
   allpass+echo, tape-style pre-emphasis+drive) PLUS -- after a second
   directorial correction -- a genuine nonlinear self-reprocessing feedback
   loop (feedback_loop(): y[n] = tanh(x[n] + fb*y[n-D]), modeling his mic'd
   mini-amp feedback loop literally, not a linear comb filter) and a
   hard-compression-plus-makeup-gain stage (tempo_punch()) that's supposed
   to reveal each chain's own resonant/feedback tail once the input note
   decays (his stated mechanism, verified by direct quote from the
   transcript).
2. Replaced purely-synthesized "instruments" with REAL recorded source
   material: freesound CC-BY/CC0 guitar-chug and kick-drum one-shots
   processed through the chain above; CC0 GM-soundfont organ/choir/bells via
   fluidsynth (VST hosting was tried and ruled out: no dawdreamer wheel for
   our Python version, no passwordless sudo to pacman-install Surge
   XT/sfizz).
3. Rebuilt the melody generator (melodies.py) around researched
   music-theory rules (MELODY_CRAFT.md: antecedent/consequent phrases,
   motivic development -- sequence/inversion/fragmentation, contour
   classes, harmony-aware chord-tone/passing-tone snapping to the active
   church mode) SEEDED by a real Gregorian chant motif -- the Dies Irae
   incipit (F E F D | E C D D, mode I Dorian, captured from a real GABC
   transcription on GregoBase, see CATHOLIC_SOURCES.md) -- instead of an
   arbitrary hand-picked semitone array.

Director's verdict on THIS round's demo (verbatim): "it does sound like
music now, but the melodies are just random child-playing-with-a-keyboard
tunes that don't fit the situation, and it just sounds like MIDI + some
shitty samples, not an actual finished game soundtrack."

## What we want from you

We are NOT asking you to grade the audio (you can't hear it). We want
outside-model reasoning, with no stake in our existing abstractions, on:

1. **Diagnose the most likely root cause(s) of "sounds like MIDI + shitty
   samples, not a finished soundtrack"** given the pipeline described above.
   Consider (and rule in/out with reasoning, not just list) candidates like:
   arrangement/production (no sidechain glue between drum/bass/lead as a
   MIX, not just per-instrument processing; no reverb bus tying instruments
   into one polygon; no stereo width/imaging; raw sample-rate/bit-depth
   mismatches between fluidsynth renders (44.1kHz) and freesound sources
   (48kHz downsampled) introducing artifacts); harmonic/arrangement
   thinness (a lead + bass + drums with no mid-range pad/rhythm-guitar glue,
   no counter-melody, no harmonic rhythm/chord changes under the
   mode-locked melody, which could be exactly what reads as "child playing
   piano" -- a melody with no harmonic context moving under it); the
   "random child" complaint specifically -- is our motif-development
   algorithm (sequence/invert/fragment cycling deterministically through 4
   transforms) still audibly aimless because it lacks PHRASE-LEVEL INTENT
   (build toward a climax, resolve, contrast against the rhythm section)
   even though it satisfies the mechanical "don't repeat verbatim" rule; or
   something else entirely (arrangement density/orchestration over time,
   lack of dynamics/automation across the piece, missing a hook/theme
   statement the ear can latch onto, wrong register/voicing making the lead
   sound like a toy).

2. **Concrete, buildable-by-us recommendations** to close the gap to
   "releasable game soundtrack," ranked by expected impact given our actual
   constraints (numpy/fluidsynth/free samples, no paid libraries, no human
   composer/mix engineer, offline generation only). For each
   recommendation, state what observation would tell us it worked or
   failed (we are not able to easily A/B against your intuition, but you
   can name what a human ear would notice if the fix landed).

3. **Whether a rules-based/motif-development melody generator (as opposed
   to composing sections by hand, even a few reference bars) can plausibly
   ever clear "sounds like a finished soundtrack, not a demo"** -- your
   honest odds, and if you think it can't, what the smallest amount of
   HUMAN-authored material (e.g. a director-hummed or director-written 4-8
   bar reference phrase per section) would need to inject to fix it, versus
   what's fixable by better algorithms alone.

Be concrete and specific to OUR pipeline (reference file/function names
above where relevant), not a generic "hire a composer" essay. We will
implement testable pieces of your advice next, not defer to it uncritically
-- so name the strongest reasons your recommendations might be wrong too.
"""


def build_prompt() -> str:
    parts = [
        cm.section("PRODUCT CONTEXT", PRODUCT_CONTEXT.strip()),
        cm.section("BAYESCRAFT (how to reason about this)",
                    cm.extract_bayescraft(cm.GLOBAL_CLAUDE_MD)),
    ]
    for relname in ("GORDON_METHOD.md", "MELODY_CRAFT.md",
                     "CATHOLIC_SOURCES.md", "DYNAMIC_MUSIC_DESIGN.md"):
        p = HERE / relname
        if p.exists():
            parts.append(cm.section(f"FILE: tools/musicgen/{relname}",
                                     p.read_text()))
    for relname in ("gordon_chain.py", "melodies.py", "real_sources.py",
                     "assemble_demo.py"):
        p = HERE / relname
        if p.exists():
            parts.append(cm.section(f"FILE: tools/musicgen/{relname}",
                                     p.read_text()))
    parts.append(cm.section("THE ASK", ASK.strip()))
    return "\n\n".join(parts)


def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("no OPENROUTER_API_KEY set", file=sys.stderr)
        return 1
    prompt = build_prompt()
    print(f"prompt size: ~{cm.tokenish_size(prompt)} tokens", file=sys.stderr)
    out_dir = HERE / "analysis" / "soundtrack_gap_consult"
    out_dir.mkdir(parents=True, exist_ok=True)
    return cm.stream_consult(
        prompt=prompt,
        api_key=api_key,
        model=cm.DEFAULT_MODEL,
        effort="high",
        max_tokens=8000,
        connect_timeout_s=30.0,
        out_dir=out_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
