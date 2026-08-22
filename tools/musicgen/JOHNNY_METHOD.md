# The johnny audio workflow, applied to PERIHELION (round 3 spec)

Distilled directly from ../johnny (`docs/boot_audio_process.md`,
`docs/tracker_playbook.md`, `AUDIO_HANDOFF.md`, `tools/boot_critic.py`,
`tools/make_boot_audio.py`, `tools/mod_census.py`) per the director's order:
"Learn from the music and audio workflow we did in ../johnny - look directly,
no more subagents on this particular task." Main-line work only.

## What johnny actually did (the ten moves)

1. **Code is the DAW.** One composer file, numpy DSP, primitives grown as
   needed (`kick808`, `riser`, `tape_stop`, …), a `Mix` bus with soft-tanh
   saturation. Variants are one-line flags in a dict; renders deterministic.
2. **Score to a locked map.** Structure first: every event sits on a named
   timestamp constant; the grid is derived from the structure. Radio-imaging
   grammar there (hook → riser → impact → bed → cold mixout → stinger);
   song-form here.
3. **Anchored grading or nothing.** The pivotal move of that project:
   unanchored "P(professional would ship)" rated *actually-shipped* pieces
   0.10–0.17 — and our round-1 judge rated garbage 0.85. Same instrument
   failure, both signs. Fix: Clip A = a shipped piece ("this defines
   shippable"), judge ours as Clip B against it, rotate references, median of
   n≥3. Validate the judge on known-answer fixtures before trusting a number.
4. **Know the ears' blind spots.** Gemini: deaf below ~60 Hz (verify low end
   by FFT), stereo-blind, unreliable timestamps, hallucinates video unless
   told AUDIO-ONLY, last-position bias — an A/B verdict counts only if it
   survives position swap.
5. **Two channels: metric vs lead generator.** The anchored score is the
   metric. Harsh per-beat critique is a LEAD GENERATOR only: its absolute
   numbers are noise, but complaints that (a) recur and (b) survive
   verification against waveform/FFT/code were all real bugs. Dismiss failed
   claims with data. Stop signals: a complaint unchanged after its fix, or
   contradicting complaint pairs — that's convergence.
6. **Pointed probes beat open critique.** "Transcribe every word." "Describe
   the sounds in order." Ask for observables, not opinions.
7. **Objective gates under the subjective loop.** Per-beat RMS lanes,
   duration, true peak (≤ −1 dBTP), LUFS target, FFT checks — the invariants
   past bugs violated, as a regression net.
8. **Mix-bus physics.** The tanh saturator equalizes peaks — perceived
   dynamics must come from ARRANGEMENT (dead gaps, contrast), not fader moves.
   Headpolygon discipline: beds ~1.2 pre-peak, only the one transient that must
   win goes 2.5+. Impact needs driven harmonics 60–250 Hz to read on small
   speakers. The 150–250 ms dead gap before the drop did more than any layer.
9. **Census → playbook → verify against the census.** Count what recurs in
   the corpus, derive authoring rules from counts, then RUN THE CENSUS ON OUR
   OUTPUT: johnny's covers had to land near 1.29 fx/note, not 0.1. The
   doorbell diagnosis: "a cover without an effect column isn't plain, it's
   unfinished."
10. **Craft moves that repeatedly landed:** contrast sells impact; cadence on
    the tonic; hold one canonical leitmotif phrase byte-identical (ear-brand);
    Easter eggs at partial intelligibility; cold mixouts chop mid-scream.

## Round-3 application (the plan of record)

- **Census the album for real** (`album_census.py`): DSP-measured ground truth
  per 30s block — tempo confirm, RMS arc, spectral centroid/flatness per
  intensity tier, onset density per layer band, kick-pattern grid, section
  lengths. The round-1 corpus JSON has Gemini's *descriptions*; the census
  adds *numbers*. Authoring rules come from counts; our renders must pass the
  same census (PERIHELION's "1.29 fx/note" equivalents TBD by measurement —
  e.g. onsets/bar in the 60–250 Hz band, crest factor per section, per-hit
  velocity variance ≠ 0).
- **Anchored critic** (`anchored_critic.py`, adapted line-for-line from
  johnny's `boot_critic.py`): Clip A = a real album block (defines the bar),
  B = ours; rotate ≥3 reference blocks; median; position-swap discipline;
  AUDIO-ONLY framing; pointed probes ("describe the sounds in order", "what
  instrument plays the melody", "does the guitar read as a guitar or a
  synth?"). Fixture validation before first use: B = another real album block
  must read "comparable craft"; B = the condemned round-2 demo must read
  "clearly worse." **Advisory only — the director's ear is the gate.**
- **Score to a locked form map**: a 60–90 s piece with named-constant
  sections (LOW bed with chant statement → riser → DROP → driving verse on
  the chug grid → machine-choir cantus firmus over the riff → feedback-choke
  breakdown → climax → cold end). Grid from the census (album: 4/4, ~135 BPM
  median, D tonal center).
- **Per-note articulation is law** (the volume-column lesson): every chug hit
  gets its own velocity/mute-depth, kick accents follow a pattern, choir
  notes breathe. Flat sequenced hits = the doorbell = round 1's disease.
- **Instruments**: the real recorded chug/kick through the component-modeled
  Gordon array (choke benched at −15.9 dBFS / +8.9 dB swell); the pitched-
  factory machine-choir (round 2's one thesis-true artifact, D3 register);
  real CC0 organ/choir samples (downloaded, license-verified) — no GM, no
  bare synthesis where a real source exists.
- **Melody**: Dies Irae strophe as cantus firmus (already transcribed from
  GABC); the counter-motif is COMPOSED BY HAND on the main line — antecedent/
  consequent, single apex, Dorian, developed by register and rhythm, never
  note-scrambled. Original composition inspired by the sources; never a
  fetched asset with a filter on it (DIRECTOR_FEEDBACK.md, law 2).
- **Objective gates** (`music_check.py`): per-section RMS lanes, LUFS/dBTP,
  FFT sub-bass presence at the drop, census conformance — regression net
  under the ear loop.
- **Ship small, early.** First deliverable is one piece + a labeled video to
  the director's ear, not a component zoo.
