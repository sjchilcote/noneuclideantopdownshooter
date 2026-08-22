1. **Replace note-by-note generation with an explicit 8-bar phrase plan**
   - **Change:** Make the generator consume a phrase specification containing:
     - chord/modal center per bar;
     - target contour and register;
     - rhythmic cell per bar;
     - planned rests and held notes;
     - open cadence in bar 4 and final cadence in bar 8;
     - one unique apex, preferably in bars 6–7;
     - exact motif statement locations and permitted transformations.
     
     Preserve the source motif literally on its first appearance; do not strong-beat-snap its individual notes. Generate accompaniment from the motif’s notes, not vice versa. Ensure `assemble_demo.py` renders the complete eight-bar period.
   - **Expected impact:** **High**
   - **What the ear should notice:** A recognizable musical statement, a question-and-answer shape, a deliberate high point, breathing space, and an actual ending instead of continuous legal-but-arbitrary notes.

2. **Generate multiple candidates and select by musical scoring**
   - **Change:** Generate perhaps 64–256 deterministic candidates per phrase and score/reject them. Penalize:
     - excessive direction changes;
     - repeated short-note “typing” rhythms;
     - unprepared large leaps;
     - immediate reversal after leaps;
     - weak-beat chord tones followed by strong-beat non-chord tones;
     - repeated apex notes;
     - excessive pitch-class or rhythmic entropy;
     - unresolved phrase endings.
     
     Reward motif recurrence, mostly stepwise motion, recoveries after leaps, contour coherence, rhythmic repetition with controlled variation, bar-4 openness, and bar-8 resolution. Save the score and rejection reasons for debugging.
   - **Expected impact:** **High**
   - **What the ear should notice:** Far fewer nonsensical lines and more phrases that sound selected rather than merely emitted.

3. **Create a small authored vocabulary of rhythms, cadences, and phrase archetypes**
   - **Change:** Stop generating every dimension freely. Build reusable data tables for:
     - 8–16 rhythm cells with rests, pickups, holds, syncopations, and endings;
     - antecedent/consequent templates;
     - call-and-response templates;
     - modal bass progressions;
     - cadence formulas;
     - tension curves such as `low → medium → high → release`.
     
     Let procedural logic choose, transpose, ornament, and recombine these templates. Coordinate lead attacks with drum and bass events so every layer is not competing on the same grid.
   - **Expected impact:** **High**
   - **What the ear should notice:** Memorable rhythms, intentional pauses, clearer section identity, and parts that appear to listen to one another.

4. **Make the assembled demo use the production instrument path**
   - **Change:** Refactor assembly around rendered stems—drums, bass, lead, organ, choir, bells, ambience—and route the actual Gordon-chain/real-source implementations into those stems. Remove `fm_bass()` and `lead_saw()` from the default showcase path unless they are deliberate layers. Add an automated render report listing the source and processing chain used by every audible stem.
   - **Expected impact:** **High**
   - **What the ear should notice:** The demo will finally sound like the developed production system rather than a step-sequencer mockup with newer code sitting unused elsewhere.

5. **Render performances, not isolated notes**
   - **Change:** Give every instrument a deterministic performance model:
     - phrase-level velocity and expression curves;
     - instrument-specific timing offsets, not uniform random jitter;
     - variable note lengths and overlaps;
     - legato versus detached articulation;
     - accent and ghost-note layers;
     - two or more round robins where free samples permit;
     - cymbal choke and release handling;
     - bass slides or overlaps only at selected transitions;
     - alternating attacks for guitar-like sources.
     
     Prefer whole-phrase FluidSynth MIDI rendering with CC expression, sustain, pitch bend, and articulation switching over independently rendered note files.
   - **Expected impact:** **High**
   - **What the ear should notice:** Less machine-gun repetition, connected gestures instead of separate key presses, and dynamics that follow the phrase.

6. **Use exposed instruments only where the available sources are convincing**
   - **Change:** Audit each free SoundFont/sample set by rendering a fixed audition phrase at several registers and velocities. Do not expose weak GM guitar or choir patches as solo foreground instruments. Use them as filtered or layered textures. Favor roles that tolerate limited samples:
     - organ and choir for sustained beds;
     - bells for sparse punctuation;
     - percussion for transient detail;
     - synth bass as an intentionally synthetic element;
     - layered lead combining a restrained synth core with low-level sampled texture.
     
     Keep each instrument inside its credible register.
   - **Expected impact:** **Medium–high**
   - **What the ear should notice:** Fewer obviously fake solo instruments, less “cheap General MIDI” character, and a more coherent game-score palette.

7. **Build macro-form, transitions, and section automation**
   - **Change:** Generate a complete cue rather than concatenating normalized loops. Define a form such as:
     - intro;
     - eight-bar statement;
     - reduced variation;
     - intensified return;
     - climax;
     - release or loop-safe outro.
     
     Automate density, register, octave doubling, drum activity, filter brightness, polygon sends, and stem levels across the form. Add pickups, fills, cymbal transitions, tails, and one-bar handoffs between sections.
   - **Expected impact:** **Medium–high**
   - **What the ear should notice:** A soundtrack cue that develops and arrives somewhere, rather than several loops placed end to end.

8. **Replace section normalization and final clipping with stem/bus mixing**
   - **Change:** Establish fixed gain staging across the entire cue. Do not peak-normalize every section independently. Add:
     - per-stem high-pass/low-pass and broad corrective EQ;
     - modest bus compression where needed;
     - kick-triggered bass ducking;
     - one shared stereo polygon using a free impulse response and NumPy FFT convolution;
     - shorter ambience for drums and longer sends for pads/choir;
     - deliberate stereo positions and width limits;
     - volume/send automation;
     - a conservative final limiter or soft clipper used only for peak control.
     
     Leave headpolygon before the master stage and loudness-match comparison renders.
   - **Expected impact:** **Medium–high**
   - **What the ear should notice:** Instruments occupying one acoustic world, clearer kick/bass separation, smoother section changes, greater width and depth, and less “samples pasted onto MIDI.”

9. **Add objective render validation and mandatory listening exports**
   - **Change:** For every build, export the full mix plus stems and diagnostic versions: melody+bass, dry mix, wet mix, and percussion-only. Automatically flag clipping, DC offset, abnormal crest factor, long-term level jumps, excessive sub-bass, and suspiciously repetitive onset/velocity patterns. Produce stable A/B renders with identical loudness and random seeds.
   - **Expected impact:** **Medium**
   - **What the ear should notice:** Fewer regressions and faster identification of whether a failure comes from composition, performance, orchestration, or mixing.

10. **Normalize every asset at load time**
    - **Change:** Honor the sample rate returned by the loader. Resample every source offline to the project rate with a tested sinc/polyphase implementation, convert channels explicitly, remove DC, trim or preserve tails intentionally, and cache processed assets. Record source rate, target rate, pitch root, license, and gain in metadata.
    - **Expected impact:** **Low unless assets are currently mismatched**
    - **What the ear should notice:** Correct pitch and duration, fewer inexplicable tonal artifacts, and consistent transient behavior; this will not by itself cure the musical or MIDI-like result.

A rules-based motif generator can produce convincing material, but only when its rules and templates already embody substantial human musical judgment; a generic scale-snapping/transformation system working from nothing has perhaps a **15–25%** chance of producing director-approved material reliably, even after the rendering pipeline is fixed. With one director-approved 4–8 bar phrase—or even a hummed/MIDI reference supplying rhythm, contour, cadence, and emotional direction—the odds are closer to **65–80%**, rising with one feedback pass. A motif generator **alone** can never establish “finished soundtrack” quality because performance, orchestration, form, and mix remain separate requirements; the practical recommendation is to require a minimal approved seed and let the procedural system handle variation, adaptation, intensity, and arrangement.