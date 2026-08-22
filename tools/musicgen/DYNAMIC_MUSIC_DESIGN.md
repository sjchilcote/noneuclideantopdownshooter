# Dynamic music system — design doc

Director's spec (his words, paraphrased into requirements):

1. Music gets more intense based on how intense the game is.
2. Different enemies produce different **basslines**.
3. The player's weapon determines the **lead**.
4. The chapter of the game sets the **rhythm** everything else builds on.
5. Keep the runtime mechanism as simple as his own pyweek-28 implementation.
6. Stretch goal (design only, not build): SFX quantized to the music.

This doc proposes a concrete design against each point, grounded in three
things built this session: the album playbook (`PLAYBOOK.md`), the
pyweek-28 prior-art mechanism, and what Phase C's judged instrument/demo
results actually revealed about what our synthesis can and can't do yet.

## 1. The runtime mechanism — honor pyweek-28's simplicity

pyweek-28's `DoubleLayerMusicPlayer` (`musicplayer/__init__.py` in the
cloned repo, scratchpad `pyweek-28/`) is the model to extend, not replace:

- Two (or more) full-length **looping stems**, all always playing.
- A background thread linearly ramps each stem's volume toward 0 or 1 at a
  fixed rate (his: 0.01 per 10ms) based on a **single boolean flag** read
  from game state every tick: `self.levelmusic.b_should_be_playing =
  (self.battle is not None)` (`gamestate/__init__.py:153`).
- No FSM, no curve tuning beyond the fixed linear rate, no per-encounter
  cue logic.

PERIHELION's version generalizes this to **N stems, each gated by one
scalar (0..1) instead of one boolean**, still with a single fixed-rate
linear fader per stem, still one thread (or one per-frame `lerp`) — no new
complexity class introduced:

```
class LayerPlayer:
    stems: dict[str, Sound]       # e.g. "rhythm", "bass", "lead"
    target: dict[str, float]      # what each stem's volume should ramp toward
    current: dict[str, float]     # ramps toward target at FADE_RATE/tick

    def tick(dt):
        for name in stems:
            current[name] = move_toward(current[name], target[name], FADE_RATE * dt)
            stems[name].set_volume(current[name])
```

Game code just writes `target["lead"] = 1.0 if player_in_combat else 0.0` —
exactly pyweek-28's pattern, generalized from a bool to a float and from 2
stems to however many the chapter needs. This is the entire runtime
mechanism. Everything below is about *what* sets `target[...]`, and *which*
audio plays in each stem slot — not about making the fader smarter.

## 2. Intensity → overall song energy

Candidate intensity metrics (to calibrate via a GPT Sol consult — see
`tools/musicgen/consult_machinery.py`, not yet run; this is a proposal list,
not a ruling):

- **Threat density**: count of active hostile entities within N tiles/LOS.
- **DPS in/out**: rolling window of damage dealt vs. taken (both matter —
  a player steamrolling a polygon reads differently than one barely surviving
  it, and the album's own `intensity_level` tags in the playbook distinguish
  "high" from "peak" partly on this kind of push/pull).
- **Health trend**: derivative of player HP over the last few seconds, not
  just current HP — a sharp drop should spike intensity even above a high
  static threat count.
- **Polygon lockdown state**: binary/tiered (unlocked / locked-in-combat /
  cleared) — maps cleanly onto the album's own structural_role tags
  (buildup / drop-climax / breakdown) found in the playbook.
- **Lurker proximity**: distance to nearest not-yet-aggroed threat — this
  is the one metric that should raise intensity *before* combat starts
  (dread, not just DPS), matching the album's dormant/low/building blocks
  which build tension with no drums yet.

Combine into a single 0..1 `intensity` scalar (simple weighted sum to
start, per pyweek-28's own preference for simple over clever), which then
maps to a **layer count**, not a continuous DSP parameter — e.g.
`intensity < 0.2` → rhythm bed only, `0.2-0.5` → + bass, `0.5-0.8` → + one
lead layer, `> 0.8` → + a second/harder lead or drone layer. This directly
reuses the playbook's own "what enters/exits between intensity levels"
findings (see PLAYBOOK.md's layering-grammar section) rather than inventing
a new intensity taxonomy from scratch.

**Calibration step**: once real telemetry exists (polygon clear times, damage
logs), consult GPT Sol via `consult_machinery.py` on the weighting — this
is exactly the kind of "outside model, no stake in our abstractions"
question `consult_planner_diagnostics.py` was written for in diet_app.
Not run yet (no real telemetry to calibrate against); a musicgen-specific
`build_prompt()` still needs writing (see that file's header for the
reusable-vs-diet_app-specific split).

## 3. Enemy → bassline

Each enemy *type* (not instance) owns a bass pattern + register, keyed the
same way `melodies.py`'s `BASS_PATTERN`/`render_bass` already parameterize
root note/octave. When an enemy type is present/aggroed, its bass motif
gets mixed into the `bass` stem (crossfaded per pyweek-28's linear-fader
rule when the enemy set changes — no special-case transition logic).
Concretely: a small `ENEMY_BASS_TABLE: dict[enemy_type, BassMotif]`, where
`BassMotif` is exactly the `(root_note, root_octave, pattern)` triple
`melodies.py` already takes. Multiple simultaneous enemy types = the
loudest/highest-priority one wins the bass slot (again: simple, not a
mixer) unless director wants true layering, which is a stretch.

## 4. Weapon → lead

Same pattern, mirrored onto `render_lead`: each *weapon* (not each shot)
owns a lead motif/register, active in the `lead` stem while that weapon is
equipped, gated by the intensity layer-count rule above (lead only sounds
during combat-tier intensity, matching what the playbook found: the lead
enters late, at/near the drop, never during dormant/low blocks). A
`WEAPON_LEAD_TABLE` mirrors `ENEMY_BASS_TABLE`'s shape.

## 5. Chapter → rhythm (the shared foundation)

The rhythm stem is the one thing that does NOT change per-encounter — it's
set once per chapter/area (a `CHAPTER_RHYTHM_TABLE: dict[chapter_id,
RhythmPattern]`), and the bass/lead motifs above are written to be
harmonically/rhythmically compatible with whichever chapter rhythm is
active (same BPM/meter — the playbook found the album overwhelmingly
converges on one tempo/grid, so chapters differing in *feel* should differ
in instrumentation/pattern-density, not tempo, to keep bass/lead drop-in
compatible without a re-tempo step).

## 6. Stretch: SFX quantized to the music (design only)

Not built this pass. Proposed mechanism, still honoring "simple":

- The music system already knows the current beat clock (a single running
  phase counter derived from `STEP_S`/`BAR_STEPS` in `melodies.py`'s grid).
  Expose it as a read-only `beats.current_phase_16th()` the SFX layer can
  poll.
- Weapon fire sounds get a **quantize-to-grid class**: heavy weapons
  (shotgun, rail) snap to the nearest downbeat/quarter; light/fast weapons
  (SMG) snap to 8th/16th subdivisions instead, so they can still feel
  responsive at high fire rates without becoming arrhythmic against the
  beat.
- Pitch variation: SFX take their pitch-shift *cents* offset from the
  currently active chord/mode (from the chapter rhythm's key), the same
  way `melodies.py`'s `BASS_PATTERN`/`LEAD_PATTERN_HIGH` already express
  motion as semitone offsets from a root.
- Success metric: Gemini judges a mixed clip (music + quantized SFX) with a
  prompt that must permit "reads as separate/off-beat" as a valid answer —
  same fail-first discipline used in `judge_instruments.py`/
  `compare_demo.py` this session (see PLAYBOOK.md/report for two real bugs
  that discipline caught).

## What Phase C's judged results imply for the artist handoff

Final per-instrument p_match vs real album excerpts (Gemini anchored
judge, fail-first-verified; history in `instruments.py`/`sample_bank.py`
docstrings):

| palette entry | best | how |
|---|---|---|
| fm_bass | 0.85 | synthesis (heavy saturation iteration) |
| industrial_drone | 0.85 | synthesis (tonal detuned saws, not noise) |
| snare | 0.85 | synthesis — modal head partials + wire rattle |
| rhythm chug | 0.85 | **sampled from album** (KS synthesis plateaued at 0.2) |
| hihat_closed | 0.8 | synthesis — square-cluster ring-mod |
| lead_saw | 0.75 | synthesis (driven detuned saws) |
| kick | 0.3 (plateau) | 9 attempts: 4 synthesis classes + 5 sample configs, all 0.1-0.4, oscillating "too clean" ↔ "hardstyle" |

- **Kick is the one open gap for the artist**: the album kick is a
  "heavily processed real drum" — acoustic body + industrial saturation —
  and neither layered-transient synthesis nor slicing it out of the
  wall-of-sound mix reproduced it. The chug gap closed only via sampling
  the album (scratchpad-only; the artist replaces those samples).
- **The demo piece passes the family test**: demo v8 (rhythm bed with
  sampled chug + modal snare + ring-mod hats, RMS-based mixing, root-pedal
  bass, sustained lead phrases, wall-of-sound glue saturation) judged
  same_family at p = 0.8/0.85/0.9 over three passes against a 3-track
  album montage. Sane score ordering: real album track 0.95 > demo 0.85 >
  gunshot SFX 0.1 > deliberately cheerful chiptune 0.0.
- **Measurement lesson (transfers to all future audio judging)**: the
  first family judge was broken — anchored on ONE guitar-forward excerpt,
  it rejected a *real track from the same album* at 0.2, and every demo
  scored 0.0-0.2 regardless of intervention; single runs also had huge
  variance (same file: 0.8 then 0.1, 0.1). The fix was a montage anchor
  spanning the album's range + "judge family/character, not production
  polish" + an is-it-even-music clause (a repeated gunshot false-accepted
  at 0.9 as an "industrial beat" until that clause). Validate any judge on
  positive AND negative known-answer controls before trusting it, and take
  the median of ≥3 passes.
- Composition tells matter as much as timbre: bouncy short-note melodies
  and melodic 5th/7th bass jumps read as "8-bit chiptune" to the judge
  even with matched timbres; the album's grammar is root-pedal 8th-note
  bass, 16th chug trains, sparse sustained lead — all now encoded in
  `melodies.py`.
