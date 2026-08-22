# Sources & licenses log (tools/musicgen)

Running log of downloaded/consulted assets and their source + license status for
the music-generation pipeline.

## 2026-07-13 — Catholic chant/mode research (text/note-data only, no audio)

Round-2 music direction requires melodic material drawn strictly from Catholic
liturgical tradition (Gregorian chant modes + specific chant melodies), separated
from Protestant hymnody. Research and captured note data written to
`tools/musicgen/CATHOLIC_SOURCES.md`. **No audio files were downloaded** for this
work — only mode definitions and short GABC-notation incipits (note-letter
sequences) transcribed by hand from public chant databases into that markdown file.

- Public-domain status: the eight church modes are medieval music-theory
  definitions (not copyrightable); the four captured chant melodies (Dies Irae,
  Victimae Paschali Laudes, Salve Regina, Veni Creator Spiritus) are medieval/early
  compositions whose melodic content is public domain. Only the *note sequence* was
  extracted as documented musicological fact from a modern (1961 Solesmes)
  engraving — the engraving/page image itself was not reproduced or stored.
- URLs consulted (see CATHOLIC_SOURCES.md for full citation list per item):
  - https://gregobase.selapa.net/chant.php?id=1198 (Dies irae, GABC incipit)
  - https://gregobase.selapa.net/chant.php?id=1086 (Victimae paschali laudes, GABC incipit)
  - https://gregobase.selapa.net/chant.php?id=2715 (Salve Regina, GABC incipit)
  - https://gregobase.selapa.net/chant.php?id=2923 (Veni Creator Spiritus, GABC incipit)
  - https://en.wikipedia.org/wiki/Church_modes
  - https://en.wikipedia.org/wiki/Dies_irae
  - https://en.wikipedia.org/wiki/Tom%C3%A1s_Luis_de_Victoria
  - https://en.wikipedia.org/wiki/Giovanni_Pierluigi_da_Palestrina
  - https://en.wikipedia.org/wiki/Genevan_Psalter
  - https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_instr_19670305_musicam-sacram_en.html (Musicam Sacram, 1967 — "Gregorian chant... pride of place")
  - https://grokipedia.com/page/Lutheran_chorale
  - https://grokipedia.com/page/Victimae_paschali_laudes

## 2026-07-13 — Marathon 1 (1994) MIDI soundtrack analysis (reference only, NOT PD)

Director approved borrowing licks from the Marathon 1 General MIDI soundtrack
(Alexander Seropian, Bungie, 1994; Marathon 2/Infinity had no music). The 16
original QuickTime-export MIDI files were downloaded to a scratch directory
(Dropbox folder linked from https://aaronfreed.github.io/soundtracks.html,
"Marathon 1 MIDI files" section), channel-split, and lead-line note sequences
extracted into `tools/musicgen/MARATHON_SOURCES.md`.

- **License status: copyrighted, not public domain.** The Marathon Trilogy is
  freeware (https://trilogyrelease.bungie.org/) and the Marathon 2 engine is GPL
  (Aleph One), but the music compositions remain Bungie/Seropian copyright.
- **No Bungie-derived files are committed to this repo** — the MIDIs stayed in
  scratch; only short analyzed note fragments (lick-length, for transformed
  homage use) are recorded in MARATHON_SOURCES.md.
- URLs consulted:
  - https://aaronfreed.github.io/soundtracks.html (MIDI exports + track history)
  - https://marathon.bungie.org/story/music.html (composer, format, track names)
  - https://marathongame.fandom.com/wiki/Marathon_Soundtrack
  - https://trilogyrelease.bungie.org/ (freeware status)
  - https://github.com/Aleph-One-Marathon/alephone (GPL covers engine, not music)

## 2026-07-13 — CC0 GM soundfonts for real organ/choir/bell/guitar samples

Round-2 order #2 ("real instruments... a guitar/chug that sounds like a GUITAR,
organ/choir/bells that sound REAL"). VST hosting (dawdreamer) was tried and ruled
out: no dawdreamer wheel matches this box's Python (3.13, dawdreamer's newest wheel
tops out at cp311), and `sudo` requires a password we don't have, so pacman-installed
Surge XT/sfizz was also a dead end. Fell back to the director's own explicitly
endorsed alternative: fluidsynth (already installed) + soundfonts, using ONLY CC0
1.0 licensed banks so provenance is unambiguous.

- **Source repo (aggregator only, not the rights holder)**:
  https://github.com/bratpeki/soundfonts — its README licence table marks
  `ChaosBank.sf2`, `Jnsgm2.sf2`, `Masterpiece.sf2`, `Unison.SF2` as **CC0 1.0**,
  originating from rKhive.com's soundfont collection
  (https://rkhive.com/banks.html, license page https://rkhive.com/legal.html).
  `Jnsgm2.sf2` additionally lists Jordi Navarro Subirana ("JNS-GM v2.0",
  https://www.polyphone-soundfonts.com/documents/27-instrument-sets/55-jns-gm-2)
  as an alternate source, same CC0 status per that repo's table.
- **Not committed to git** (would blow the <5MB audio-asset commit budget — each
  bank is 12-33MB). `tools/musicgen/fetch_soundfonts.sh` re-downloads all four CC0
  banks into `~/.cache/perihelion_musicgen/sf2` (override with `SF2_DIR`); that
  script IS committed (it's text, not audio).
  `tools/musicgen/real_sources.py` reads from that cache dir at render time.
- **Used for**: Church Organ, Choir Aahs, Tubular Bells, Distortion/Overdrive
  Guitar GM patches (all real sampled instruments baked into the soundfont, not
  synthesized) — real source material for `gordon_chain.py`'s processing.
- **Fallback soundfont** `GeneralUser GS` (S. Christian Collins,
  https://schristiancollins.com/generaluser.php, license text at
  https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/documentation/LICENSE.txt)
  was also downloaded during evaluation but is **NOT used** in the committed
  pipeline: its license explicitly states some contained samples have
  "questionable origin" / uncertain provenance, which fails the director's
  "CC0/PD sources only, provenance logged" bar for the Catholic-tradition organ/
  choir/bell voices specifically. Kept only as a local scratch comparison, not
  wired into `real_sources.py`'s `BANK_ORDER`.

## 2026-07-13 — freesound real guitar-chug + kick samples

A listen-proxy sanity check (`gemini_listen.py`) on the CC0 GM soundfonts'
"Distortion Guitar"/"Overdrive Guitar" patches came back negative even on
the RAW unprocessed sample ("Brass... synthesized... buzzy", not "guitar") --
i.e. the free GM soundfont's guitar patches are themselves low-fidelity, a
source-quality problem, not a processing problem (isolated by testing the
raw sample before any Gordon-chain processing). Pivoted to the director's
other endorsed route (freesound CC0/CC-licensed real recordings) for guitar
and kick specifically; kept the CC0 soundfonts for organ/choir/bells, which
DID pass the same listen-proxy check.

- **Guitar chug**: "100 BPM Rhythm Guitar B0 8th Note Chug 1" by Vrezerino,
  https://freesound.org/people/Vrezerino/sounds/846771/, **CC Attribution
  4.0** (not CC0 -- attribution required, logged here: "100 BPM Rhythm
  Guitar B0 8th Note Chug 1" by Vrezerino, freesound.org, CC BY 4.0).
  Downloaded via the public HQ preview URL (no login needed for the
  preview stream): `https://cdn.freesound.org/previews/846/846771_17361-hq.mp3`.
  One hit sliced out and run through `gordon_chain.guitar_chain()` to
  produce `chug_sampled.wav` for the demo's rhythm-bed sample slot.
  Listen-proxy check on the raw slice: "string... acoustic guitar riff...
  real instrument: true".
- **Kick**: "Metal Bass Drum" by deadpoetsocietyband,
  https://freesound.org/people/deadpoetsocietyband/sounds/128970/, **CC0**
  (page states "Creative Commons 0"). Same public-preview download route:
  `https://cdn.freesound.org/previews/128/128970_2354572-hq.mp3`.
- **Not committed to git** (source recordings only exist in scratchpad,
  same <5MB commit-budget reasoning as the soundfonts) -- the committed
  pipeline (`gordon_chain.py`, `melodies.py`) consumes pre-rendered
  `demo_samples/{chug,kick}_sampled.wav` at render time, not raw
  freesound audio; those processed one-shots are small enough to commit
  if the director wants them locked in (currently left as a build step,
  not committed, pending his ear-check on round 2).

## 2026-07-13 — machine-choir source + liturgical real-sample candidates

Director's aesthetic thesis for the project's sound: "Gregorian chants and
Catholic hymns as played and sung by industrial machines who genuinely
believe in what they represent" — real industrial sounds pushed through the
Gordon-array pipeline to become instruments. Downloads (all via freesound's
public HQ preview URLs, scratchpad only, never committed):

- **Machine-choir voice**: "Industrial factory working 02.wav" by
  dersinnsspace, https://freesound.org/people/dersinnsspace/sounds/439402/,
  **CC0** (found via freesound's license:"Creative Commons 0" search
  filter; page states "Creative Commons 0"). A steady 1.2s slice is
  pitched note-by-note through the full Dies Irae first strophe
  (scratchpad `round2/machine_choir.py`) — the factory sings the chant.
  Used in the round-2 showcase video's "MACHINE CHOIR" chapter.
- **Real pipe organ candidate**: "Cathedral Organ" by Beetlemuse,
  https://freesound.org/people/Beetlemuse/sounds/527206/, **CC0** (page
  states "Creative Commons 0"). Downloaded + verified by listen-proxy;
  intended replacement for the GM-soundfont organ after the director's
  "no GM sounds" pushback; not yet wired into the committed pipeline.
- **Real chamber choir candidate**: "chamber_choir_chord_o.wav" (and
  single-note files) by uair01,
  https://freesound.org/people/uair01/packs/4311/, **CC BY 3.0**
  (attribution: uair01, freesound.org). Real recordings of a chamber
  choir; listen-proxy confirms "sustained chord sung by a choir, real".
  Candidate for the choir voice; not yet wired in.
- **Church bell**: "Church bell.wav" by Audeption
  (https://freesound.org/people/Audeption/sounds/425172/) — downloaded for
  evaluation but its license marker was NOT successfully scraped from the
  page; **treated as unusable until the license is confirmed** (logged
  here so the gap is explicit, per no-silent-failures discipline). The
  listen-proxy liked it ("large resonant bell, real"), but provenance
  gates usage, not quality.

## 2026-07-13 — Library audit: cab IRs + headless VST3 host

Director asked for a prior-work audit of the Python audio ecosystem
(auto-tuning, cab/amp convolution, vocoder, loudness) instead of hand-rolled
DSP for everything. Full results in `tools/musicgen/LIB_AUDIT.md`. Two
categories of asset downloaded to the scratchpad as part of proving the
tools actually work (nothing here committed to git, same commit-budget
reasoning as the soundfonts above):

- **Cab IRs (3x, all CC0)**, found via Freesound's own
  `license:"Creative Commons 0"` search filter, same public HQ-preview
  download route as the rest of this log:
  - "4x12 Vintage.wav" by jesterdyne,
    https://freesound.org/people/jesterdyne/sounds/129399/, **CC0**.
    `https://cdn.freesound.org/previews/129/129399_867203-hq.mp3`. 5.5ms —
    a bare cabinet-sim IR (Korg AX1500g unit), no polygon tail.
  - "Cabinet IR BG412S Godmode DV77+V30 Mix.wav" by jesterdyne,
    https://freesound.org/people/jesterdyne/sounds/618897/, **CC0**.
    `https://cdn.freesound.org/previews/618/618897_867203-hq.mp3`. 1.28s,
    modified Behringer BG412S w/ Celestion V30 + Eminence DV77, includes
    polygon tail.
  - "IR Brown Cab_Audix i5 Center.wav" by tosha73,
    https://freesound.org/people/tosha73/sounds/507167/, **CC0**.
    `https://cdn.freesound.org/previews/507/507167_10725617-hq.mp3`. 0.5s,
    mic'd cab (Audix i5) — normal cab-IR length, probably the best default
    of the three.
  - All 3 downloaded as HQ MP3 preview, decoded to wav via ffmpeg, and
    load-verified through `pedalboard.Convolution` in a real
    distortion→convolution→compressor→reverb→limiter chain on a chug1.wav
    slice (see LIB_AUDIT.md). Stored at `scratchpad/musicgen/ir/`.

- **Surge XT VST3 (GPL-3.0)**, official Linux "pluginsonly" release
  tarball, no installer/sudo required:
  https://github.com/surge-synthesizer/releases-xt/releases/download/1.3.4/surge-xt-linux-1.3.4-pluginsonly.tar.gz
  (via https://github.com/surge-synthesizer/surge, license confirmed
  GPL-3.0 via the GitHub API). Downloaded + extracted to
  `scratchpad/musicgen/vst3/`, load-verified via
  `pedalboard.load_plugin()` and rendered a real, correctly-pitched MIDI
  note (FFT-confirmed). Used here purely as an audit smoke test of
  pedalboard's headless VST3 hosting capability, not wired into any
  pipeline. GPL-3.0 is fine for offline asset-authoring tooling (never
  linked into the shipped game binary); see LIB_AUDIT.md's license note
  before using any GPL/AGPL tool from this audit at runtime.

## Album Mode v2 / M0 (2026-07-13)
- **Delay Lama VST** (AudioNerdz, 2002) — freeware VST2 (i386 DLL); the
  source album's actual vocal instrument (director-identified). Fetched
  from https://archive.org/details/delay-lama (3,719,168 bytes). Kept in
  scratchpad only; never committed, never shipped in the game.
- **MrsWatson 0.9.8** (Teragon Audio, BSD-style license) — CLI VST2 host,
  Windows build run under wine 11.9 for headless offline rendering.
  https://github.com/teragonaudio/MrsWatson — scratchpad only.
- **Dragonfly Reverb 3.2.10** (Michael Willis, GPL-3) — Linux x86_64 VST3
  (Hall/Polygon/Plate/Early), loaded headless via pedalboard; factory preset
  values applied verbatim from the source preset table
  (DistrhoPluginInfo.h). Offline authoring only; scratchpad only.
- **AudioRealism TR-909 Sample Pack** (audiorealism.se) — 853 samples from
  a real TR-909 (11 accent layers/instrument, 5x5x5 kick/snare knob grid,
  choke + phasing combos). Free download, free for personal & commercial
  use per their site; NO redistribution — samples scratchpad-only, only
  our renders are committed.

## Vitalium (Vital engine, open-source fork)
- Source: DISTRHO-Ports via Arch `extra/distrho-ports-vst` package
  (vitalium.so, VST2), extracted to scratchpad — not installed.
- License: GPLv3. OFFLINE AUTHORING ONLY, never shipped in the game
  (same policy as Dragonfly). Renders are ours.
- Hosted by tools/musicgen/vst2_host.py (ctypes VST2 host, offline).
- State chunk == the .vital preset JSON format (+NUL): community
  .vital presets load verbatim via effSetChunk. CHECK EACH PACK'S
  LICENSE before use; log here.

## Tyrell N6 (u-he, freeware)
- Linux VST2 .so in scratchpad. Loads + initializes under vst2_host;
  PARKED: stalls at first processReplacing (next lever: effStartProcess
  opcode 71 before rendering). u-he freeware EULA: free use, no
  redistribution — binary stays in scratchpad.

## Specimen by Spektralisk (free sample pack)
- Provided by the director (Downloads). EULA: non-exclusive license,
  use in music OK; NO redistribution of samples/loops as standalone
  files. Samples stay in the scratchpad; renders are committed.
- 82 samples, 19 keyed. Wired via tools/musicgen/specimen_kit.py;
  lab alternates: ATMO->beds, IMP->stings, RISE->risers, keyed
  BASS->riff sampler voice.

## Vital (Matt Tytel, free tier)
- Downloaded by the director with his vital.audio account
  (VitalInstaller.zip). Free-tier EULA: free to use; binaries stay in
  the scratchpad, never redistributed/committed.
- Replaces Vitalium as the render engine for .vital banks: Vitalium's
  1.0.x engine mangles 1.5.x presets into a fallback tone (measured:
  cross-preset correlation 0.86 -> ~0.00 on real Vital 1.5.5).

## Ylanne Vinyl Church Bells (Joonas Ylanne / AV-Ylanne, v1.1)
- Provided by the director (Downloads zip; Decent Sampler freeware).
  License (Readme.txt): freeware; "free to use the sounds in your
  music and projects, including commercial work"; may NOT resell,
  redistribute, or repackage the instrument or its contents. Samples
  stay in the scratchpad ($S/bells/); only rendered stings (sting.wav
  per bank) are committed.
- ChurchBell1.wav (Puolimatkan chapel bell, vinyl-recorded) is the
  source of the sting bell: measured perceived strike ~C5 (+22 cents),
  resampled down 34.2 semitones to strike MIDI 38 (D2, 73.4 Hz; hum
  partial ~37 Hz) via tools/musicgen/bell_sting.py.
