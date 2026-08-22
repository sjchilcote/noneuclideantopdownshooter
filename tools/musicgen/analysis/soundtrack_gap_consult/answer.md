## Bottom line

The director is probably identifying **two separate failures**:

1. **“Random child-playing-with-a-keyboard tunes” is primarily a composition-system failure.**  
   `melodies.py` satisfies local rules—modal snapping, transformations, no third identical repeat—but does not encode phrase-level musical intent. It has no real harmonic progression, climax plan, rhythmic breathing, or interaction with the rhythm section.

2. **“MIDI + shitty samples” is primarily a performance/orchestration/mix failure.**  
   The actual `assemble_demo.py` path is still mostly a mono step sequencer using `inst.fm_bass()` and `inst.lead_saw()`, repeated one-shots, fixed grids, static levels, section-by-section normalization, and one final distortion/lowpass pass. The organ/choir/bells and most Gordon-chain machinery are not actually part of that mix.

Sample-rate mismatch is worth checking because `_load_sample()` ignores the returned sample rate, but it is unlikely to explain the “random child melody” complaint.

---

# 1. Bayesian diagnosis

These hypotheses overlap; they are possible simultaneous causes.

## H1: The melody engine lacks phrase-level intent

**Prior:** 2:1. Mechanical motif generators commonly produce valid-but-aimless lines.

**Evidence E1:** The director specifically hears “random child-playing-with-a-keyboard tunes.”

- `P(E1 | H1) ≈ 0.80`
- `P(E1 | ¬H1) ≈ 0.15`
- LR ≈ 5.3
- Posterior after E1: about **11:1**

**Evidence E2:** The code does not actually implement several properties claimed in the documentation:

- no phrase contour model;
- no chord/harmonic timeline;
- no climax or unique high point;
- no rhythmic interaction with drums;
- antecedent and consequent both resolve to root;
- the demo only exposes four high-intensity bars, so the eight-bar period is truncated after the antecedent;
- strong-beat snapping mutates the source chant rather than harmonizing around it.

- `P(E2 | H1) ≈ 0.90`
- `P(E2 | ¬H1) ≈ 0.15`
- LR ≈ 6

Combined posterior is roughly **60:1 or greater**. I would assign about **95–98% probability that this is a major contributor**.

### Concrete code evidence

#### The chant is damaged immediately

`DIES_IRAE_MOTIF` begins:

```python
[3, 2, 3, 0, 2, -2, 0, 0]
```

But every even-indexed eighth note lands on a strong beat and is passed through:

```python
_snap_to_mode(..., prefer_stable=True)
```

With `STABLE_DEGREES = {0, 3, 4, 7}`, the opening F–E–F–D can become approximately G–E–G–D. The generator is not preserving a Dies Irae statement and developing it afterward; it is correcting individual notes according to a local nearest-note rule. That is exactly the kind of procedure that produces a line whose notes are individually legal but whose intervals feel arbitrary.

#### “Harmony-aware” currently means “in the same scale”

There is no chord or harmonic-root timeline. The lead knows only a fixed Dorian root. The bass independently changes to the fifth for one bar in four:

```python
use_fifth = (bar % 4 == 3)
```

The lead is not told that this happened. Modal membership is not harmonic awareness.

#### The antecedent/consequent distinction is mostly documentary

`build_phrase()` always forces:

```python
snapped = 0  # resolve to the root -- authentic cadence
```

Therefore both phrases have a root cadence. The antecedent does not end open on the reciting tone/fifth as claimed.

#### The demo does not play the complete period

`assemble_demo.py` defaults to four bars per section. The lead is silent in low and building, then gets four bars in high. `build_period()` creates eight bars, but `render_lead()` stops after the first four. The director never hears the promised question-and-answer period.

#### The phrase has no breathing

The lead emits continuous eighth notes with essentially one articulation and one dynamic. There are no rests, held tensions, pickups, syncopations, or call-and-response gaps. Even a good pitch sequence can sound like keyboard noodling under those conditions.

---

## H2: The demo is still architecturally a MIDI mockup

**Prior:** 3:2.

**Evidence E1:** “Sounds like MIDI + some shitty samples.”

- `P(E1 | H2) ≈ 0.75`
- `P(E1 | ¬H2) ≈ 0.25`
- LR ≈ 3
- Posterior: about **4.5:1**

**Evidence E2:** Trace the actual render path:

```text
assemble_demo
  -> melodies.render_layer
      rhythm -> samples or synthesized one-shots
      bass   -> inst.fm_bass()
      lead   -> inst.lead_saw()
  -> static RMS targets
  -> section peak normalization
  -> concatenate sections
  -> hard soft_clip
  -> mono lowpass
```

The following round-two work is not present in the assembled demo mix:

- `organ_choir_chain()`;
- rendered organ/choir/bell arrangement;
- `argent_bass_chain()`;
- mix-level sidechaining;
- shared polygon/reverb bus;
- stereo placement;
- performance-level MIDI articulation;
- transitions or automation.

- `P(E2 | H2) ≈ 0.95`
- `P(E2 | ¬H2) ≈ 0.10`
- LR ≈ 9.5

Posterior is roughly **40:1**, or about **97% that this is a major contributor**.

The implementation has changed more than the audible assembly path has. “Real recorded source material exists in the repository” is not the same proposition as “the final piece is performed and orchestrated with real-sounding sources.”

---

## H3: Source quality and articulation are exposing the sampler

**Prior:** 1:1.

**Evidence:**

- GM guitar and choir patches often remain unconvincing even though they are technically sample-based.
- One-shots are repeatedly retriggered on a hard grid.
- There are no visible round robins, velocity layers, alternate picking, release noises, cymbal chokes, ghost notes, or phrase-wide instrument rendering.
- Bass and lead are still synthesized.
- `real_sources.render_note()` renders isolated notes rather than a whole musical performance.

Approximate update:

- `P(evidence | H3) ≈ 0.85`
- `P(evidence | ¬H3) ≈ 0.30`
- LR ≈ 2.8
- Posterior ≈ **3:1**, strengthened further by the director’s wording.

I would put this at **80–90% as a contributor**, although probably secondary to composition and arrangement.

A sampled instrument still sounds “MIDI” when the performance has:

- identical attacks;
- identical velocities;
- identical release behavior;
- exact grid timing;
- no articulation changes;
- isolated notes instead of connected gestures.

The provenance of the waveform does not solve the performance problem.

---

## H4: Missing mix cohesion is the main cause

**Prior:** 1:1.

The final mix has:

- no shared polygon;
- no stereo plan;
- no kick-triggered bass ducking;
- no instrument buses;
- no send automation;
- no common section-wide dynamic curve;
- independent section normalization;
- a final hard clip used as glue.

That strongly predicts “unfinished mockup.”

However, mix glue cannot make an aimless melody intentional. My posterior is:

- **90% that mix incompleteness contributes to “unfinished”;**
- only **20–30% that it is the dominant cause of the complete verdict.**

Adding reverb and sidechain to the existing melody would likely produce a more expensive-sounding random melody.

---

## H5: Sample-rate or bit-depth mismatch

**Prior:** about 1:9.

There is one real code risk:

```python
x, _sr = sy.read_wav(p)
return np.asarray(x, dtype=np.float32)
```

`_load_sample()`