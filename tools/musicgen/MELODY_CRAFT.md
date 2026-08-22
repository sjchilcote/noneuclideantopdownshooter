# Melody craft notes — round 2

Round 1 verdict (director, verbatim): "sounds like a parody of what an AI
thinks music sounds like... AWFUL" — specifically "a synth playing one
annoying note over and over forever." The automated judge that scored round
1 highly (`judge_instruments.py` / `compare_demo.py` pipeline) is known
broken; its scores are not evidence either way for round 2. This doc is
sourced music-theory research distilled into rules for rebuilding
`melodies.py` around motifs and phrases instead of a naive note loop.

## What round 1 actually did wrong (read `melodies.py` before building)

Current `render_lead()`: a single 9-event `LEAD_PATTERN_HIGH` list of
`(semitone, length)` tuples spanning one 4-bar phrase, looped verbatim,
unchanged, for the entire duration of "high"/"peak" intensity. No
antecedent/consequent, no variation on repeat, no register change, no
harmonic context beyond a fixed root — every note is `root*2 *
2**(semi/12)`, i.e. picked by ear against no chord track at all. This is
structurally *identical* to the "one annoying note over and over forever"
failure the director named, just with 9 notes instead of 1: a fixed loop
with zero development is monotony regardless of loop length. `BASS_PATTERN`
is even flatter — a single repeated root pulse, defensible *only* because
bass is supposed to be a static pedal under a moving lead, which the current
lead doesn't provide.

## Core rules (actionable, for melodies.py's rebuild)

### 1. Build in phrases, not loops

A melody is not "a pattern that repeats" — it is **antecedent + consequent**
forming a period: a "question" phrase ending on a half cadence / open
harmony, answered by a "consequent" phrase that ends more conclusively (full
cadence, or a resolution back to the tonic/root). Typical phrase length is
4 or 8 bars; a period is two phrases, so 8 or 16 bars total.
[Open Music Theory: Period](https://elliotthauser.com/openmusictheory/period.html)

- In a **parallel period**, the consequent starts with the same (or
  near-same) opening idea as the antecedent, then diverges to resolve
  differently — this is the cheapest way to sound composed rather than
  looped, because the ear recognizes the restart as intentional.
- Concretely for the generator: define a short **basic idea** (1-2 bars),
  restate it to open the consequent phrase, but vary the tail so phrase 1
  and phrase 2 are not byte-identical.

### 2. Motifs, not full melodies, are the reusable unit — and they must be developed, not repeated

A motif is a short (2-5 note, sub-bar to 1-bar) rhythmic/melodic cell — the
smallest recognizable idea, e.g. Beethoven's 5th short-short-short-long.
Development techniques, all well documented and all mechanical enough to
implement as pitch/duration-array transforms:

- **Repetition** (exact restatement — fine once or twice, never as the
  entire piece)
- **Sequence** — repeat the motif starting from a different pitch, same
  shape (e.g. transpose the whole motif up or down a step each repeat)
- **Inversion** — flip each interval's direction (up-3rd becomes down-3rd)
- **Augmentation / diminution** — same pitch sequence, note durations
  doubled (augmentation) or halved (diminution)
- **Fragmentation** — take only the head or tail of the motif and repeat
  *that* alone, often at higher rhythmic density, typically used to build
  tension toward a phrase's climax

[Vaia: Motive Development](https://www.vaia.com/en-us/explanations/music/music-theory/motive-development/),
[Fiveable: Motivic Development Techniques](https://fiveable.me/music-theory-and-composition/unit-7/motivic-development-techniques/study-guide/JWOcNBgrI0AhrBYJ)

**Rule for the generator**: a motif may repeat verbatim at most 2 times
consecutively; every repeat after that must apply at least one
transformation (sequence/inversion/augment/diminish/fragment). This is a
direct, encodable fix for "one note/pattern over and over forever."

### 3. Contour must have a shape, and the shape must move

Melodic contour is the up/down shape traced by pitch over time. Named
shapes: ascending (rising = building tension), descending (falling =
releasing tension), static (hovering — reads as stuck/boring if sustained),
arch (rise to a peak, then fall — the default "phrase" shape, since it both
builds and resolves tension within one breath).
[Ableton: Creating Melodies 1: Contour](https://makingmusic.ableton.com/creating-melodies-1-contour),
[about-music-theory: melody shape](https://www.aboutmusictheory.com/melody-shape.html)

Motion within contour is either **conjunct** (stepwise, adjacent scale
degrees — smooth, singable) or **disjunct** (leaps of a 4th or larger —
dramatic, attention-grabbing). Good melodies mix both and, per general
melody-writing guidance, answer a leap with the opposite motion (a leap up
answered by a step down, or vice versa) rather than continuing to leap in
the same direction, which is what makes a "hook" leap read as intentional
rather than random.
[dummies: How to Use Music Theory to Shape the Melody](https://www.dummies.com/article/academics-the-arts/music/music-theory/how-to-use-music-theory-to-shape-the-melody-144456/)

**Rule for the generator**: every phrase must have a distinguishable
contour class (rising / falling / arch — never flat/static for a whole
phrase), and a phrase should not stay confined to a single pitch or repeat
the identical pitch on every single event of the phrase (that is the "one
note" failure mode literally, not metaphorically).

### 4. Tension and resolution against the harmony — not notes picked by ear

Every melody note should be understood against the chord/mode sounding
underneath it at that instant:

- **Chord tones** (root/3rd/5th/7th of the current chord) are stable —
  land on them at strong beats and especially at phrase ends/cadences.
- **Passing tones** connect two chord tones stepwise through the gap
  between them, usually on weak beats.
- **Neighbor tones** step away from a chord tone and back (upper or lower
  neighbor), decorating without changing the harmonic implication.
- **Suspensions** hold a note *over* a chord change so it becomes
  momentarily dissonant against the new chord, then resolve down by step —
  this is a primary source of felt "tension then release" in a melodic
  line.
[Milne: Nonharmonic Tones](https://milnepublishing.geneseo.edu/fundamentals-function-form/chapter/15-nonharmonic-tones/),
[Wikipedia: Nonchord tone](https://en.wikipedia.org/wiki/Nonchord_tone)

A **cadence** is a melodic+harmonic resolution point: half cadence
(lands on a non-tonic, unresolved — question) vs. full/authentic cadence
(lands on the tonic — answer). Phrase endings should be built as cadences,
not just "wherever the loop wraps."

**Rule for the generator**: even in a mode/riff-based (not full-tonal)
context, tag every scale degree the melody can land on as
stable/chord-tone vs. passing/tension, and bias strong beats (esp. phrase
starts and phrase-end cadence notes) toward stable tones, weak beats toward
passing/neighbor tones. This is what makes a lead sound harmonically aware
of the bass/rhythm bed instead of picked independently — the current
`render_lead` computing frequencies purely from `root * 2 * 2**(semi/12)`
with no reference to what the bass is doing at that step is exactly the
gap to close.

### 5. Voice leading: treat the single line as if it had to connect smoothly

Voice leading is normally about multiple parts, but the same discipline
applies to a monophonic lead moving across a chord progression: prefer
common tones or stepwise motion into the next chord's chord-tone over
random leaps, and when you do leap, land on a chord tone of the new
harmony so the ear can parse the jump as harmonically motivated rather than
arbitrary.
[Wikipedia: Voice leading](https://en.wikipedia.org/wiki/Voice_leading),
[Berklee: Voice Leading Paradigms](https://online.berklee.edu/takenote/voice-leading-paradigms-for-harmony-in-music-composition/)

**Rule for the generator**: when a chord/root changes under the lead, the
next lead note should either be the nearest chord tone by smallest
interval, or an intentional leap that still lands on that new chord's
chord tone — never an arbitrary semitone offset carried over from the
previous harmonic context.

### 6. Ostinato/riff-driven writing (the genre this game actually is) still needs all of the above

Ostinato = a short motif repeated persistently (classical term; "riff" in
metal/rock is the same device). It is legitimate and idiomatic for
industrial/metal/combat-music — repetition itself is not the bug. The bug
is repetition with *zero* variation layered around it. Concrete,
genre-appropriate techniques to keep an ostinato/riff alive over many bars:
[Beyond Music Theory: Avoiding Ostinato Boredom](https://www.beyondmusictheory.org/avoiding-ostinato-boredom/),
[Metal Mastermind: Writing Metal Riffs](https://metalmastermind.com/writing-metal-riffs/),
[pillowmath: Video Game Music: Ostinato and Repetition](https://pillowmath.github.io/musings/ostinato-repetition.html)

- **Harmonic reharmonization**: keep the riff's notes fixed but change the
  chord/root sounding under it every N bars, so the same notes take on
  different harmonic color.
- **Register/instrumentation shift**: move the riff up an octave, or hand
  it to a different layer (rhythm guitar chug vs. lead), rather than
  always the same voice at the same pitch.
- **Rhythmic variation**: keep the pitch content but alter note density —
  straight 8ths this repeat, syncopated or double-time next repeat.
- **Add/drop notes**: insert a passing note or drop a note from the cell on
  alternating repeats so it's never bit-identical twice in a row.
- **Call and response between layers**: have the lead state a phrase and
  the rhythm/bass answer it (or vice versa) rather than all layers
  running the identical rhythmic grid in lockstep for the whole track —
  this is also how `render_rhythm_bed`/`render_bass`/`render_lead` being
  three independent unrelated grids (current architecture) should instead
  interlock.
- **Fragmentation for tension**: shrink the riff to its head-motif only
  and repeat that fragment faster leading into a section change (e.g. into
  the drop where "high"/"peak" intensity kicks in) — turns a structural
  transition into a felt one instead of an abrupt gain-stage switch.

## Banned pattern

**The round-1 failure, generalized**: any layer whose pitch/rhythm content
for a given intensity level is one fixed array (`LEAD_PATTERN_HIGH`,
`BASS_PATTERN`) played back identically, unbroken, for the entire duration
that intensity is active, with no phrase boundary, no cadence, no motivic
transformation, and no harmonic relationship to the other layers. Whether
that fixed array has 1 note or 9 makes no perceptual difference past ~2
repeats — the director's ear caught a 9-event loop exactly as fast as it
would catch a 1-note loop, because the failure is "no development," not
"too few notes."

**The concrete rule that prevents it**:

1. No motif (a cell of 1-2 bars) may repeat verbatim more than 2 times
   consecutively without a transformation (sequence, inversion,
   augmentation/diminution, fragmentation, rhythmic variation, register
   shift, or added/dropped note).
2. Every intensity level's lead must be structured as at least one
   antecedent/consequent period (a question phrase + an answer phrase,
   4-8 bars each, i.e. 8-16 bars minimum before any large-scale loop
   point), not a single phrase looped raw.
3. Every phrase has an assigned contour class (ascending / descending /
   arch) and must not sit on a single pitch for the whole phrase.
4. Every note is chosen with reference to the harmony sounding under it
   at that step (chord tone on strong beats/cadences, passing/neighbor
   tone permitted on weak beats) — not derived purely from a fixed root
   with an arbitrary semitone table.
5. Phrase endings land on a cadence (resolve to a stable/chord tone,
   ideally the root, at the point another layer or intensity level would
   transition) rather than wrapping mid-idea.

If a generated layer violates any of (1)-(5), it is architecturally the
same bug the director already rejected once, regardless of how it scores
on the (broken) automated judge.

## Sources

- [Open Music Theory: The Period](https://elliotthauser.com/openmusictheory/period.html)
- [Milne Publishing: Sentences and Periods](https://milnepublishing.geneseo.edu/fundamentals-function-form/chapter/35-sentences-and-periods/)
- [Wikipedia: Period (music)](https://en.wikipedia.org/wiki/Period_(music))
- [Vaia: Motive Development — Techniques & Examples](https://www.vaia.com/en-us/explanations/music/music-theory/motive-development/)
- [Fiveable: Motivic Development Techniques](https://fiveable.me/music-theory-and-composition/unit-7/motivic-development-techniques/study-guide/JWOcNBgrI0AhrBYJ)
- [Toby Rush: Motivic Development (PDF)](https://tobyrush.com/theorypages/pdf/en-us/motivic-development.pdf)
- [Study.com: Melodic Contour — Definition, Shape & Types](https://study.com/academy/lesson/melodic-contour-definition-examples.html)
- [Ableton Making Music: Creating Melodies 1 — Contour](https://makingmusic.ableton.com/creating-melodies-1-contour)
- [about-music-theory.com: Melody shape and melodic contour](https://www.aboutmusictheory.com/melody-shape.html)
- [dummies.com: How to Use Music Theory to Shape the Melody](https://www.dummies.com/article/academics-the-arts/music/music-theory/how-to-use-music-theory-to-shape-the-melody-144456/)
- [Milne Publishing: Nonharmonic Tones](https://milnepublishing.geneseo.edu/fundamentals-function-form/chapter/15-nonharmonic-tones/)
- [Wikipedia: Nonchord tone](https://en.wikipedia.org/wiki/Nonchord_tone)
- [Wikipedia: Voice leading](https://en.wikipedia.org/wiki/Voice_leading)
- [Berklee Online Take Note: Voice Leading Paradigms for Harmony in Music Composition](https://online.berklee.edu/takenote/voice-leading-paradigms-for-harmony-in-music-composition/)
- [Beyond Music Theory: Avoiding Ostinato Boredom](https://www.beyondmusictheory.org/avoiding-ostinato-boredom/)
- [Metal Mastermind: 10 Methods for Writing Metal Riffs](https://metalmastermind.com/writing-metal-riffs/)
- [pillowmath: Video Game Music — Ostinato and Repetition](https://pillowmath.github.io/musings/ostinato-repetition.html)
