# Stem Composition Design — authored sums, tagged compatibility, fluent transitions

Ratified in planning session 2026-07-14 (director + Claude). Governs how
stems are authored and combined so every reachable mix is a composed
piece, not a coincidence. Supersedes the "render lanes independently and
sum at gains" approach, which the director correctly identified as the
core defect ("stems need to sum to an authored composition, not
independently authored pieces slapped on top of each other").

Mechanism baseline: the Tower-of-Torment chunk-queue sequencer (pyweek-28
musicplayer) already adopted in game/perihelion/music.py — bar chunks on
channel.queue(), pending-chunk replacement, the audio is the clock.

## 1. The authoring law: compose the tutti, subtract the stems

For each melody x section, the FULL arrangement (tutti) is composed and
verified first — gauntlet, then the director's ear. Stems are derived by
muting part groups of the verified tutti. A subset of a composed whole is
a composed mix; the reverse is never guaranteed. Slot variants (weapon
leads, enemy basslines) are verified linearly: re-render the tutti once
per variant, never audition the combinatorial space.

## 2. Shared-spec construction (compatibility by construction)

Every stem in a bank is generated from one shared spec:

- **Mode + home note** (the chant's own mode, from GABC; transposed as a
  bank to the instruments' best registers). Mode is moral register:
  faith = dorian/phrygian family; locrian belongs to the Adversary and
  never sums with faith material except scripted moments.
- **Progression**: an explicit per-bar chord list per section. All
  pitched stems are generated from it. Default harmonic language: PEDAL
  POINT on home (the device chant and industrial metal share); real
  chord motion is spent at section boundaries and peaks.
- **Register map**: fixed octave/band per part slot; exactly one owner
  of the bass floor; wall in low-mids, chant mids, lead above, bells air.
- **Rhythmic roles**: timekeeper / backbone / harmonic-rhythm / sustain /
  free-floating (the monk only — chant is ametrical by tradition). One
  occupant per role.
- **Melody discipline**: <=1 foreground voice. Counter-melody only in
  the chant's rest windows (known from the note data) and in a different
  register. The weapon lead answers the monk call-and-response or plays
  long-note reductions — never unison doubling.

## 3. Tag schema + the solver

Stems carry: bank+section id; progression id; mode; register bands;
rhythmic role; onset density (measured, census units); melodic role;
dissonance level; intensity tier; exclusivity group.

At each bar boundary a small constraint solve (greedy+backtracking is
sufficient; ~15-25 candidates) picks the stem set:

- HARD: same section+progression; register exclusivity (one sub owner);
  <=1 foreground; one occupant per role; mode compatibility matrix.
- SOFT (score): summed density inside the census band for the current
  tier; no hollow registers; tier matches the value triple; continuity
  preferred except when a wall is called for.

Dissonance is a budgeted resource that scales with CONTEMPT/STALWART
(aimed minor-2nd / tritone material at peaks, Adversary textures),
never an accident of collision.

## 4. Transition controller — derivative-driven fluency (director's rule)

Entries/exits are AUTHORED chunks, not volume ramps: every stem group
ships fill (entry) and exit (ring-out) chunks besides its loop chunks.
The controller maps the smoothed derivative of (prayer, contempt,
stalwart) to a build program, scheduled as pending-chunk selections and
re-planned every bar:

- steep spike (monster closet): ONE-BAR lead-in — fill now, sting on the
  downbeat, wall at bar+1. One bar is the floor; nothing starts mid-air.
- moderate slope: 2-4 bar staged build — hats tell -> kick -> bass ->
  wall, riser across the last bar.
- shallow sustained climb (stalking a boss): 4-8 bar long program — bed
  darkens, tells, riser swell, one layer admitted per bar or two.
- falls mirror: sudden threat-gone = vacuum exit with ring-out bar; slow
  disengage = staged exits in reverse.
- interruption: a spike mid-build replaces the remaining program with
  the one-bar path (the pounce collapses the stalk).
- scheduled builds land on PHRASE boundaries (4-bar), the emergency path
  on bar boundaries. The riser's length IS the program length — the
  music's anticipation stays honest to the actual rate of deterioration.

## 5. Form

Each melody bank is a FORM the chunk index walks: statement /
statement+counter / development (fragmentation + sequence transforms) /
peak tutti / outro — target 4-6 sections per the album's block structure
(director notified; revisit if the demo argues otherwise). The solver
picks palettes per section; development is what separates a song from a
loop.

## 6. Harmonization governance (director's ruling, 2026-07-14)

Progressions and arrangement choices are taste-critical; the director
cannot audition prose. Protocol: I make the calls, render the demo, and
LOG every alternative passed up in the Decision Log below. If a demo
displeases, the logged alternatives are the first candidates rendered
for comparison. Nothing is relitigated from memory.

## 6.5 The Delay Lama law (director's ear, 2026-07-15)

"It has to be a spice, not the main ingredient." The monk is ALWAYS
distant, background, heavily processed (deep in the hall, harsh band
tamed, modest gain). The loud dry monk clashes; the quiet distant one
works. Foreground melody duty belongs to the leads/choir; the monk is
the haunting behind them. (Converges with the grounded judge's
"vocal detached on top of the backing" complaint.)

## 7. Decision log (alternatives we passed up)

Format: date | decision | chosen | passed up | revisit trigger.

- 2026-07-14 | harmonic language default | pedal point on home, chord
  motion at boundaries/peaks | (a) full functional progressions
  throughout, (b) parallel modal planing under the chant | demo sounds
  static or "one-note" -> render (a); demo sounds too clean/tonal ->
  render (b).
- 2026-07-14 | entry policy | derivative-driven program (1/2-4/4-8 bar) |
  fixed asymmetric rule (instant walls, 1-bar entries always) | builds
  feel sluggish or walls feel cheap in play.
- 2026-07-14 | lead behavior | call-and-response with the monk +
  long-note reductions | lead doubles chant in unison (rejected:
  foreground collision) | peaks feel thin without unison doubling ->
  try octave-doubling at peak tutti only.
- 2026-07-15 | synth sourcing | ALL synth voices from the Vital banks
  (TngKaos + 5 Years of Vital via Vitalium; director: "if we use Vital
  patches that add their own detailed character, the rudimentary nature
  of our sources becomes an asset rather than a problem") | Odin2
  factory + Dexed DX7 as primary voices (they remain available as
  fallbacks; assignments + runners-up in preset_scout_scores.json) |
  a slot sounds better on the old preset in the lab A/B.
- 2026-07-14 | anti-MIDI language | the ALBUM'S OWN (measured + pro-tier
  piano-roll reconstruction): strict grid, flat velocity + downbeat
  accents, zero legato in rhythm section, binary gates (ring or chopped
  silence), two independent takes hard L/R, bass in perfect unison with
  guitar | generic forum humanization (timing jitter, per-note velocity
  randomness) | if the director still hears "MIDI" after the album
  language lands, revisit jitter ONLY for drums fills / lead phrasing.
  Note: audio_judge probes downmix mono (-ac 1) and cannot hear
  double-tracking; stereo stems are judged by ear only.
