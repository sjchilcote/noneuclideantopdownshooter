# Album Mode v2 — design before build

Director's restart directive (2026-07-13): recover the research and
actually use it; install Delay Lama (the actual vocal VST used in the
source album); stronger Gemini models for assembled work (flash for solo
instruments only); album-mode system working FIRST; design then build.

Standing laws in force: instruction-substitution law (a blocker on a
specific instruction is investigated and reported, never replaced with my
own invention); melody law (the copied chant melodies ARE the tunes, in
full); gauntlet law (nothing reaches the director unchecked); his ear is
the only final gate.

## 1. Research inventory (recovered — all of this gets USED, not decorated)

| Artifact | Where | Use in v2 |
|---|---|---|
| Per-block analyses, unreduced (72 blocks, timbres/rhythms/production/transitions) | `analysis/RAW_BLOCK_NOTES.md`, `album_block_corpus.json` | per-track reference sheets: each v2 track is built against ITS original's block descriptions |
| DSP census (RMS/crest/bands/onsets lanes per tier) | `analysis/album_census.json`, `album_census.py` | objective lanes each render must sit in |
| Production language (wall/spine stage, wet-holy/dry-violence space grammar, pump, drum-bus decay, binary transitions, mode-as-moral-register) | `ALBUM_TECHNIQUES.md` | the mix architecture spec |
| Gordon component spec + translations | `GORDON_METHOD.md` | processing chains + dynamics grammar |
| Chant transcriptions (Dies Irae full strophe GABC-verified; Victimae) | `melodies.py`, `CATHOLIC_SOURCES.md` | THE melodies — sung in full by Delay Lama |
| Track→state canon + intensity arcs | `DIRECTOR_FEEDBACK.md`, corpus | the eight factor curves (kept from v1 — confirmed working) |
| Tool audit (pedalboard/Surge proven; wine/carla present) | `LIB_AUDIT.md` | hosting routes |

## 2. Architecture (three layers, strictly ordered)

**PRESETS-FIRST LAW (director, after hearing M1):** "You need to lean as
heavily as you can on premade samples and presets on your tools - you
_can't hear_." Every instrument AND every processing step (reverb, EQ,
compression) uses a real tool's factory presets/samples wherever one
exists; hand-rolled DSP only where no tool exists, and it dies the moment
a tool is found. First proof: my noise-IR "sanctuary" (his verdict:
"sounds really bad") replaced by Dragonfly Hall's factory "Large Vocal
Hall" preset — flash gauntlet flipped to reverb_quality=natural.
Acquisition queue: preset-driven synth VSTs for leads/bass (Vital/Odin2/
Dexed class), a drumkit VST or 909-style kit, processing VSTs throughout.

**Layer 1 — INSTRUMENTS (each gated solo, flash-tier ears + FFT):**
- **Voice: Delay Lama** (Windows VST2) — the album's actual vocal
  instrument. Hosting route: MrsWatson (CLI VST2 host) under wine 11.9;
  fallback routes if that fails: Carla's wine bridge, then LinVst. If ALL
  fail, STOP and report evidence — no substitution.
- **Synths: Surge XT** (proven headless): lead/bass/wall/drone patches,
  per-patch instances (the switching bug is documented).
- **Drums: REWORKED per the standing order** — real sampled kit route:
  the audited freesound/album-sliced one-shots through pedalboard chains
  (drive + cab/polygon IR + compressor), plus pattern-level humanization.
  GM-adjacent output is an automatic gate failure.
- **Guitar: the tuned chug kit** (raw, zero re-amping — probe-proven).

**Layer 2 — SONGS (album mode): eight tracks, factor-curve authored**
- Form: the v1 curve system (waypoints from the original arcs) — kept.
- Melody: the FULL chant melodies stated by Delay Lama as the principal
  voice, with the melody-continuity law (phrase chains, breaths); lead
  synth doubles/answers antiphonally. Conformance metered (melodia).
- Mix: ALBUM_TECHNIQUES stage — wall hard-panned, mono spine, pump,
  drum-bus decay, wet-holy/dry-violence spaces, binary transitions.
- Census lanes per section against the matching original track's blocks.

**Layer 3 — EVALUATION (assembled work = pro-tier ears ONLY):**
- Solo instruments: flash tier (cheap screen) + FFT checks.
- Assembled sections/tracks: **strongest available Gemini via OpenRouter**
  (resolve exact id at build time from the models endpoint; candidates:
  gemini-3.1-pro / 2.5-pro family) with the fixture discipline: judge must
  fail known-bad (v3-condemned render, preserved in git) and pass real
  album blocks BEFORE its scores count.
- Milestone ear-checks: the director hears SHORT artifacts at every
  milestone (single sung line → one verse → one track → eight) — never
  hours of iteration between his listens.

## 3. Milestones (each ends with a director-audible artifact)

- **M0 — Delay Lama spike (GATE)**: DLL acquired from a reputable archive,
  hosted headless, renders a D3 vowel + a 4-note phrase to wav; FFT pitch
  check; committed spike script. STOP-AND-REPORT if infeasible.
- **M1 — the voice sings the chant**: full Dies Irae strophe, Delay Lama,
  phrase grammar (breaths, mora holds), dry; + a sanctuary-space version.
  → director listens (~40 s).
- **M2 — drums reworked**: kit built from real one-shots + IRs; a 8-bar
  groove at three intensities; census + pro-tier check.
  → director listens (~30 s).
- **M3 — one verse assembled** (t01 grammar: chant + bed, band entry):
  full mix stage; pro-tier fixture-validated panel; census lanes.
  → director listens (~60 s).
- **M4 — track 01 complete**, then **M5 — the eight tracks** batch with
  the full battery + report table.
- **M6 — album-mode listening kit**: out/album_v2/ + per-track reference
  sheet (what the original's blocks say vs what ours does).

Game integration: NOT in this program (album mode first, per directive).
The kept input engine consumes the artist's or v2 stems later, unchanged.

## 3.5 SOLVED — headless preset selection (was the director's blocker)

Both synths now select factory presets headless, render-diff + probe
verified (2026-07-14):
- **Odin2**: juce_valuetree.py converts the binary-ValueTree .odin files
  to the XML `<Odin>` form the plugin state carries (format transcribed
  from fetched JUCE 7.0.12 sources, full-parse validated); graft via the
  verified JUCE-b64 codec. All 260 factory patches load — readback shows
  251/253 params applied (only live modwheel/pitchbend differ).
- **Dexed**: the engine renders from dexedBlob's `base64:program`
  attribute (the UNPACKED current voice), not the cartridge and not the
  `program` param. dexed_host.set_program() reorders the chosen packed
  voice into cartridge slot 0 (checksum fixed) AND grafts its unpacked
  155-byte VCED into base64:program (unpack validated byte-for-byte
  against Dexed's own blob for voice 0). Voices audibly switch.
- Instrument tables live in generate_bank.py (presets-first): Odin2
  Church Organ / 666-001-Organ / Choir Aahs / Drones tiers / Bass +
  Dexed DX7 voices for two weapon leads.

## 4. Risks & their planned handling

- Delay Lama under wine fails → three routes in order (MrsWatson/wine,
  Carla bridge, LinVst), then STOP-REPORT with the concrete errors.
- Delay Lama is characterful but narrow (one vowel-morphing monk voice) —
  that's the point: it's the album's actual voice; EQ/space per
  ALBUM_TECHNIQUES, no replacement synthesis.
- Pro-tier audio support via OpenRouter uncertain → verify with a
  known-answer fixture before trusting; if the strong model can't hear
  audio, report options rather than silently downgrading to flash.
- Judge noise (seen in v1: 4/4↔1/4 rerolls) → n≥5 medians on assembled
  work + always paired with objective meters (census, melodia).
