# The Gordon talk, read exactly — component-by-component spec + our translations

Source: GDC "DOOM: Behind the Music" (https://www.youtube.com/watch?v=U4FNBMZsqrY),
full transcript read directly on the main line (director's order — prior
distillations, including this doc's previous revision, genericized exact
toolchains). Where a component can't be replicated 1:1, the translation
targets the *same effect on the final product* (director's ruling).
Format per entry: WHAT HE SAID → WHAT IT DOES → OURS.

## 0. The brief pattern (identical to ours)

"Music no one has ever heard before, fits the game perfectly, instantly
loved." The piano player, the dubstep producer, and the Cubase-template
composer all FAIL the same way: same process → same output, merely *inspired
by* the brief, never an *execution* of it. That is precisely our round-1/2
failure ("organ clip + filter"). Change the process, change the outcome — and
the round-2 judge's 0.85 was the Cubase template of evaluation.

## 1. The DOOM instrument array (exact hardware list, translated)

Source: a computer sending a **pure sine wave** — nothing else. "Any
interesting thing happening within this array was being imparted onto that
sine wave in the purest form possible." Occasionally **two sines slightly
detuned** — the phase imbalance "would do all sorts of crazy stuff to the
pedals." The array IS the instrument; the performance is only amplitude,
pitch, and knob tweaks.

Four parallel chains from a split:

| # | His hardware | Function | Our DSP translation |
|---|---|---|---|
| 1 | Retro Mechanical Labs 432K → Metasonix KV100 (tube) → "Geiger counter" bitcrusher → Dwarfcraft pedal → **SPLITTER** | fuzz → asymmetric tube stages → rate/bit mangling → gated fuzz; the splitter taps this chain's envelope | hard fuzz → biased-tanh asym stages → decimate+quantize w/ jitter → gated fuzz; envelope follower = sidechain source |
| 2 | Geiger counter → Metasonix TX-3 → Mu-Tron Bi-Phase → DOD 70s phaser → **compressor (sidechained from 1)** | crush → tube filth → two vintage phasers in series → this chain ducks under chain 1 and swells when it decays | decimator → asym sat → cascaded swept allpass ×2 (6-stage + 4-stage, different LFO rates) → gain modulated inversely by chain-1 envelope |
| 3 | Watkins Copycat tape echo → Rocktronics valve box ("not really there for the distortion… more for the compression") → Akai reel-to-reel **fed ~40 dB more than it could handle** while recording back off it → spring reverb tank (wet/dry) → **compressor (sidechained)** | true tape echo → tube squash → screaming hot tape (saturation, wow, hiss) → dispersive boing → ducked like chain 2 | saturating wobbling tape-echo model → soft-knee squash → deep tanh + flutter + head-bump EQ + hiss floor → chirp-train spring IR → sidechain gain |
| 4 | Mini practice amp **fed ~40 dB over**, miked; a little of the mic split **back into the amp = feedback loop** tuned so small that "if a sound was actually coming through the amp it would choke out the feedback, and when that sound started to disappear the feedback would come back up in the mix" | the array BREATHES between notes — self-noise that answers the playing | built & benched: `y[n]=tanh(x+fb·y[n-D])`, loop gain barely past unity, in-loop bandpass at the howl note; measured −15.9 dBFS choke, +8.9 dB swell in the gaps |

Sum → **EQ**: cut ~4–5 dB @ 30–60 Hz, boost ~4–5 dB @ 8–10 kHz ("basically
creating a nice sort of smiley-face EQ — nothing really amazing there") →
**bus compressor absolutely PINNED**: "knocking off about 20 decibels…
so when the loud noises would start to go away the compressor would begin to
open up and bring up all the interesting noise that every single one of
these pedals and bits of equipment was creating." Attack ~30 ms ("really
cool punchy stuff"), **release adjusted to the tempo** of the material,
ratio "about twelve or twenty to one," then straight into the DAW.
**The array's noise floor is a feature.** His array even added its own note —
a ground-hum E creeping under four F notes ("that's not being generated from
me… that's coming from some ground hum within the array"). Ours: the
feedback bus IS our ground hum; let it sound honestly.

In-DAW after: **transient processing**. "Transients I believe are really the
key to getting a really punchy sounding game mix… what you want is those
dynamics going hey I'm a punch then I'm gone, and a punch then I'm gone, and
that tricks the player's ear into believing that there's more solid music
happening in the background" — a solidly-limited bed just disappears under
gunfire. Census agrees: album crest ~13 dB; our condemned demos 5.6–9.2.

Q&A detail: he never sent other waveforms through the array — but a pedal's
preamp clipping a sine "instantly creates a square wave there… naturally and
organically within that system." Squares are EARNED by drive, not synthesized.

## 2. Sub-bass audibility (exact recipe)

A ~36.7 Hz sub is inaudible on TVs. **Turn white noise on and off at the
frequency of the sub** ("what I'm essentially doing here is ring modulation…
at the audio frequency"), combine with the sub, then run the pair through
distortion: the noise sidebands + distortion harmonics make the sub READ on
small speakers while the sine keeps the weight. Trivial DSP:
`noise * (0.5+0.5*sign(sin(2π f_sub t)))` → array. Use on every drop.

## 3. The Sean Beavan / Manson chug (exact recipe)

Take the guitar part, **play it up an octave and twice as fast**, record to
tape at **30 inches per second**, then **play the tape back at 15 ips**
(pitch/tempo land back where written, but every transient, harmonic, and
tape artifact is stretched down an octave), then "run it through a preamp
which is kind of jacked pretty hard." Ours: render the chug pattern at 2×
speed +12 st → tape-saturation chain → high-quality 0.5× resample → driven
preamp stage. Apply to the REAL recorded chug samples, not synthesis.

## 4. The signature-tone move: MORPH (the Trojan horse)

The 9-string was abandoned — "sounding too much like a guitar… too sort of
metal thing." Zynaptiq **MORPH** interpolated the guitar tone **into a sample
of the chainsaw from the original DOOM** — the game's own iconic sound became
the guitar's timbre, "the little Trojan horse" that got guitars into the
game (introduced "5% here, 10% there" against a NO-GUITARS brief — see law
9.2). Ours (STFT cross-synthesis: |X|^α·|Y|^(1−α) with X's phase): morph the
chug toward PERIHELION's OWN sounds — the pitched-factory machine-choir bed,
station drones, a weapon report. The machines' guitar, literally built from
the machines. This is the "original sound never quite heard" lever, and it is
*meaningful*: the congregation's voice inside the instrument.

## 5. The horror drone (exact recipe)

"Everything you're hearing there is bowed guitar. I'm bowing this guitar
between C# and D, and I've spread that out across four octaves… recorded a
whole bunch of different takes and laid them on top of each other." The
dread is the unresolved ADJACENT-SEMITONE cluster in every register — not a
tritone cliché. Ours: sustained-excitation string model (or pitch-shifted
real sustained sources) at C#/D pairs ×4 octaves, slow independent
crossfades per take-layer. For PERIHELION: D is the album's center; C# is
the leading tone refusing to resolve — liturgically apt dread.

## 6. Spectrogram iconography + the mono-reveal (exact, and ours to weaponize)

- Image-Line **Harmor** resynthesizes an image "across the frequency
  spectrum… essentially you're able to insert an image into a wave file but
  you need a spectrograph to be able to see it." He hid a 6 and an inverted
  star under a three-note bass part. Ours, made MEANINGFUL (the goal spec
  demands symbolism with referents): hide the **Dies Irae neumes** — the
  actual chant notation — and/or the CUCULUS glyph in the spectrum of the
  machines' hymn: the score contains its own scripture. ISTFT: draw the
  image into a magnitude mask, resynthesize, tuck at ~−30 dB under the drone.
- **Mid-side phase trick**: "put something in the center, take a little bit
  of information from one side of the channel into the other side and flip
  the phase" — inaudible in stereo, and **a hidden signal appears on mono
  fold-down** (his: a reversed message). Ours: in stereo, machine noise; in
  mono, the plain chant emerges — belief hidden inside the machine. Verified
  by DSP fold-down only (Gemini is stereo-blind — johnny method §4).

## 7. Dynamic music (exact — and deliberately SIMPLE)

DOOM combat is linear ("the demons come out, your role is to kill all the
demons, then you move forward"), so they chose NOT to do clever mid-combat
rearrangement — "we just wanted it to be on… just going bang bang bang…
honestly that's as complicated as the dynamic music system in Doom was."
The entire system:
- Songs broken into **bars, delivered as Wwise segments, constantly
  re-arranged in order** ("we didn't have a single 30-minute loop… it's just
  going from there" — variation without data-driven cleverness).
- **Glory kills: the music drops out and a white riser plays**; duration
  unknown → **"endless risers": Shepard-tone loops** — "it just feels
  constantly like there's this tension rising… really handy in a game
  environment when you don't know how long something is going to go for."
  (Director-flagged gold: tension that releases on GAMEPLAY's schedule.)
- Combat entry: "the hi-hat and the basic kick riding along, and then BAM —
  when everything kicked in, that's when the music would start."
This vindicates pyweek-28 simplicity. Our system: N stems + bar-shuffled
arrangement + Shepard riser stem + entry-BAM. No cleverer than that.

## 8. The mix-integration law (exact)

Tonal game SFX share the music's key: the triple chaingun fires so fast "it
produces a tone… we made sure that tone was a D note, and that D note was
sitting with the same music playing in the background, which is also sitting
on a D." And: "if you're ducking stuff when something else happens… you're
fixing a problem that shouldn't be there in the first place." Design-time,
not mix-time. Ours: the album is D-centered; weapon tonal centers tune to
D/A; SFX beat-quantization (director's stretch goal) plus PITCH discipline.

## 9. Process laws (his closing, his order)

1. **Change the process → change the outcome. "Courage, not confidence"** —
   "confidence comes from doing the same thing over and over… it takes
   courage to change that."
2. **"Change the brief if it makes the project better"** — no-guitars →
   5% → 10% → the signature sound; the brief's deeper goals (instantly
   loved) outranked its letter (no guitars).
3. **Psychological safety** — Hite's reply to a failed first attempt: "I feel
   you've taken the first step on a journey toward the perfect destination.
   Keep going, you're almost there." Comfort with failure is what permits
   laws 1 and 2. He calls this the most important lesson.

Also from Q&A: the **soundtrack is an album** — "the absolute best
opportunity to put forth the best representation of that music… treated
almost like a separate project," structured with game monologues as
interludes (War of the Worlds concept-album model). For us later:
RATIO/terminal voices as interludes.

## 10. What this changes in our build, immediately

- The array gains the exact missing pieces: smiley EQ, pinned 20 dB
  tempo-release bus compressor, chain-2/3 sidechain from chain 1's splitter,
  detuned-sine-pair drive mode, noise-floor-as-feature discipline.
- Every drop gets the ring-mod-noise sub treatment (§2).
- The chug goes through the Beavan octave/speed tape round-trip (§3).
- The signature tone is a MORPH between the chug and the machine-choir /
  station drone (§4).
- One drone bed: D/C# bowed-cluster ×4 octaves (§5).
- The hymn hides its own neumes in the spectrum; mono fold-down reveals the
  plain chant (§6) — symbolism with referents, per the goal spec.
- The dynamic system stays DOOM-simple: stems + bar shuffle + Shepard riser
  + entry-BAM (§7); weapon tones in D (§8).
