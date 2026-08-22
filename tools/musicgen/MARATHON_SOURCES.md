# Marathon 1 (1994) soundtrack — lick/motif source data

Director's addendum to the round-2 music direction: we may also borrow some licks
from the **Marathon 1 General MIDI soundtrack** (Marathon 2 and Infinity had no
music, ambient only). This file records real note data extracted from the original
MIDI files, plus the licensing status — which is **different from the chant
material** (see below).

## Provenance

- Composer: **Alexander Seropian** (Bungie founder), 1994. The in-game soundtrack
  was 16 MIDI compositions stored as QuickTime music tracks in the `Music.fil`
  data file; 7 tracks also shipped as CD audio on some pressings.
  Sources: [Marathon Music — marathon.bungie.org/story](https://marathon.bungie.org/story/music.html),
  [Marathon Soundtrack — Marathon Wiki](https://marathongame.fandom.com/wiki/Marathon_Soundtrack),
  [Aaron Freed's Marathon soundtrack page](https://aaronfreed.github.io/soundtracks.html).
- Note data below was extracted (by channel-splitting the merged MIDI and reading
  note-on events per channel) from the **direct QuickTime MIDI exports** of the
  original 16 tracks hosted on Aaron Freed's page (Dropbox folder linked from the
  "Marathon 1 MIDI files" section, files dated 2022). All 16 files parse cleanly:
  AliensAgain, Chomber, Fat Man, Flippant, Flowers in Heaven, Freedom, Guardians,
  Landing, Leela, New Pacific, New Pacific (reprise), Rapture, Rushing,
  Splash (Marathon), Swirls, What About Bob.
- The MIDI files were analyzed in a scratch directory and are **deliberately not
  committed to this repo** (see licensing).

## Licensing — NOT public domain, handle differently from chant

- The Marathon Trilogy is **freeware** (free to download and play, per Bungie's
  [Trilogy Release](https://trilogyrelease.bungie.org/)), and the Marathon 2
  *engine source code* is GPL (Aleph One). **Neither of these places the music in
  the public domain** — the compositions remain Bungie/Seropian copyright.
  Freeware ≠ PD ≠ GPL-covered.
- Consequence for us: unlike the chant (where we may quote whole melodies
  verbatim), Marathon material should be used as **short licks/stylistic
  homage** — brief fragments, transformed (re-harmonized, re-rhythmized, mode-shifted
  onto our chant modes), not verbatim extended melody lifts, and we ship **no
  Bungie-derived audio or MIDI data files**. The note fragments below are retained
  as analysis/reference data.

## The big musicological finding

Seropian's Marathon 1 melodic language is overwhelmingly **C minor pentatonic
(C–Eb–F–G–Bb), C Dorian, and C blues** — almost every track sits on a C or Eb
tonal center with a flat 3rd and flat 7th. This is the *same mode family the
director ordered for the chant material* (Dies Irae is Dorian). Marathon licks and
chant cantus firmi can therefore share a tonal center with zero friction: put the
Dies Irae in C Dorian (C D Eb F G A Bb C) and every lick below fits over it.

## Captured licks (note names, octave = MIDI convention, C4 = middle C)

### Leela (track 08) — THE signature Marathon melody
- Lead (ch1/ch3, GM prog 96/97 FX pads): **C5 D#5 F5 C5 | A#4 A4 G4 | D#4 F4 | G4**
  ("Eb" written D#, "Bb" written A#). Read in C: 1–b3–4–1 | b7–6–5 | b3–4 | 5.
  The **A natural (6th degree) against a C-minor field = C Dorian**, exactly the
  Dies Irae mode. Highest-value lick of the set.
- Bass ostinato (ch0, prog 44 tremolo strings): **C2 G2 C3** loop (1–5–8 pump) —
  trivially reusable as an industrial-metal chug pattern.

### Landing (track 07)
- Lead (ch3, prog 96): **C5 D#5 G5 C5 D#5 | A#4 G4 A#4 C5** — arpeggiated
  Cm + b7 neighbor motion; secondary line (ch1, prog 94) **C5 A#4 G4 G4 D#4 C4**
  is a clean descending C-minor-pentatonic answer phrase.
- Bass: **C2 G2 D#2** loop (1–5–b3).

### Flowers in Heaven (track 04)
- Lead (ch0, prog 96): **C4 D#4 G4 C5 | A#4 G4 A#4 C5** then cadence
  **G4 F4 D#4 F4 G4 C4** — hymn-like arch in C minor; the most "sacred"-feeling
  track of the set, natural bridge between Marathon homage and chant register.
- Bass (ch1, prog 48): octave pedals C2/C3 → G1/G2.

### Rushing (track 12) — combat energy
- Lead (ch3, prog 85 lead): **C5 D#5 F5 A#4 G4 A#4 C5 | C4 D#4 F4 G4 A#4 D#5** —
  pure C minor pentatonic, riff-shaped, drops straight onto a metal guitar.
- Piccolo ostinato (ch2, prog 112): **C6 D#6 F6 D#6** 4-note loop — usable as a
  high synth/bell tension figure.

### New Pacific (track 09)
- Lead (ch0, prog 96): **C5 D#5 G5 D#5 G5 A#5** loop — rising Cm7 arpeggio
  (1–b3–5–b3–5–b7); counter-line (ch2, prog 85): **C5 D5 D#5 D5 C5 A#4** —
  stepwise 1–2–b3 turn figure.

### Guardians (track 06)
- Lead (ch0, prog 48): **D#4 F4 G4 D#4 F4 A#4 | D#4 F4 G4 D#4 C4 A#3** — Eb-major
  /C-minor relative color, gentler contour.

### Chomber (track 01)
- Lead (ch4, prog 85): **C4 F4 G4 C5 G4 D#4 A#4 F4 D#4** — wide-interval C minor
  pentatonic hook, very riffable.

### Freedom (track 05)
- Bass line (ch0, prog 85): **C2 D#2 F2 F#2 G2 A#2 C3** — the **C blues scale**
  ascending, verbatim. The F# (b5) is the one chromatic note in the whole set
  worth stealing; over Dorian material it reads as a diabolus-in-musica accent,
  thematically on-brand for PERIHELION.

## Usage guidance

- Best fusion targets: **Leela** lick (Dorian, signature) and **Freedom** blues-b5
  bass as accents inside chant-derived Dorian material; **Rushing**/**Chomber**
  pentatonic shapes as riff vocabulary; **Flowers in Heaven** as the
  Marathon-to-chant crossover register.
- Keep each borrowing to lick length (one phrase), transform it, and never ship
  the source MIDI/audio. The Catholic chant material (CATHOLIC_SOURCES.md) remains
  the primary melodic source; Marathon licks are seasoning and homage.
