# Audio library audit — 2026-07-13

Prompted by the director: "I notice you're inventing everything from scratch
— send a Sonnet to go do a prior work audit for libs you can use for e.g.
autotuning sounds." This is that audit. Research + tooling only — no
composition code touched.

## The box

- Headless Linux, no sudo password, no audio interface, **but a real GPU**:
  RTX 4090 Laptop GPU present (`torch.cuda.is_available() == True`).
  "Headless" here means no display/audio device, not no compute.
- CPU: 13th Gen Intel Core i9-13950HX (Raptor Lake) — **no AVX-512**
  (fused off on all client 12th–14th gen chips, unlike server Xeons).
  This mattered (see pedalboard below).
- `uv run python --version` → **Python 3.14.2**. This is a brand-new
  CPython (Oct 2025), and it shows: several libraries had zero cp314
  wheels until versions that shipped in just the last few weeks, one
  (tensorflow) still has none.
- System binaries already present, no install needed: `rubberband` (CLI,
  v4.0.0), `fluidsynth` (v2.5.4), `ffmpeg`, `sox`. Full gcc/cmake
  toolchain available for source builds.
- 32 cores, 30GB RAM, plenty of disk. Network to PyPI/GitHub is open.

## Two ecosystem-level gotchas that cost the most time

These aren't per-library failures — they're the kind of thing that will
bite again if not written down.

1. **numpy 2.5.1 (released 2026-07-04, 9 days before this audit) has zero
   numba support**, and every numba release up to and including the
   latest (0.66.0) caps `numpy<2.5`. This project's `numpy>=1.26` floor
   was unbounded, so `uv add librosa` (or any numba-consuming package)
   silently backtracked through ~20 numba versions down to
   `llvmlite==0.36.0` — a 2020-era release with no cp314 wheel, whose
   `setup.py` throws `RuntimeError: Cannot install on Python version
   3.14.2; only versions >=3.6,<3.10 are supported.` The resulting error
   looks like "llvmlite doesn't support 3.14," which is **not** the real
   story; the real story is the numpy ceiling. **Fixed at the project
   level**: `pyproject.toml` main deps now read `numpy>=1.26,<2.5`
   (resolves to 2.4.6, released 2026-05-18). Verified this doesn't break
   the game: `pytest --collect-only` still collects all 561 tests, and
   `numpy`/`scipy`/`soundfile`/`pygame-ce` all import clean.
2. **pedalboard 0.9.23 and 0.9.24 crash with `SIGILL` on import** on this
   CPU — not a Python exception, a fatal illegal-instruction inside
   `pedalboard_native.*.so` during `dlopen`, before any Python code runs.
   Bisected across every cp314-supporting release (0.9.19 was the first
   to ship a cp314 wheel): 0.9.19 through 0.9.22 import cleanly, 0.9.23
   and 0.9.24 (latest) both SIGILL. Consistent with an AVX-512 codepath
   introduced in 0.9.23 without a runtime CPU-dispatch fallback, hitting
   a CPU that has AVX2 but not AVX-512 (this one). Did not chase the
   exact source diff — the version bisection is solid, that's enough to
   act on. **Pin `pedalboard==0.9.22` explicitly, do not let it float.**

## Results table

| Library | Installs on this box | License | What it's for | Measured smoke test | Verdict |
|---|---|---|---|---|---|
| **pedalboard** 0.9.22 | Yes (wheel). **0.9.23/0.9.24 SIGILL on import** on this CPU — pinned to last-good 0.9.22 | GPL-3.0 (Spotify) | Effects chain (Distortion/Convolution/Reverb/Compressor/Limiter/PitchShift) + headless VST3/CLAP host | Distortion→Convolution→Compressor→Reverb→Limiter chain on a 2.5s chug1.wav slice with 3 real cab IRs: all 3 processed in 26–42ms (~65–95x realtime), each numerically distinct from dry (peak 0.68–0.75 vs 0.48 dry). **Also loaded and rendered a real VST3 synth (Surge XT) headlessly** — see below. | **USE** (pin exact version) |
| **pedalboard VST3 hosting** | Same package, `load_plugin()` | — | Headless VST3 instrument/effect hosting | Downloaded Surge XT's official Linux "pluginsonly" tarball (no installer, no sudo, 97MB), `load_plugin()` loaded `Surge XT.vst3` in 1.3s, found 599 parameters, `is_instrument=True`. Sent a real MIDI note (A4/60 vel/2s) via `mido`, rendered 3s of audio in 0.013s (**224x realtime**), non-silent (peak 0.25), and the FFT peak of the sustained note landed at **exactly 440.0 Hz** — the plugin is really synthesizing, not passing through silence. | **USE** — this reopens the plugin route |
| **librosa** 0.11.0 | Yes, once numpy was capped (see gotcha #1) | ISC | pyin pitch tracking, onset detection, pitch_shift, HPSS | See pitch/onset/pitch-shift rows below | **USE** |
| **numba** 0.66.0 / **llvmlite** 0.48.0 | Yes, transitively via librosa, once numpy capped | BSD | JIT backend librosa needs | Imports and JITs correctly once numpy<2.5 | USE (transitive) |
| **praat-parselmouth** 0.4.7 | Yes (wheel) | GPLv3+ | Pitch tracking (Praat's autocorrelation) | Measured f0 on 6 chug1.wav hits: 4/6 voiced, median 61.96Hz, agrees with librosa.pyin within ~5%. Fastest of the four pitch trackers (~0.001–0.003s/hit). | **USE** |
| **torchcrepe** 0.0.24 | Yes (wheel; pulled full CUDA stack, see below) | MIT | Neural (CREPE) pitch tracking, most accurate for weak/noisy fundamentals | On GPU: 0.01–0.02s/hit after 2.6s one-time model load. **Gotcha**: raw `.predict()` always emits *some* f0, even for noise — it hallucinated ~165Hz (2x octave error) on 2 slices that pyin/parselmouth correctly called unvoiced. Fix: `return_periodicity=True`, threshold at 0.21 (CREPE-paper standard) — confirmed this exactly zeroes out the 2 bad slices (periodicity 0.10–0.12, below threshold) and agrees with the others. | **USE** (must periodicity-gate) |
| **crepe** (TensorFlow) | **Not attempted** — tensorflow has zero cp314 wheels at its latest release (2.21.0), checked directly via PyPI JSON, any platform | — | Same as torchcrepe, TF backend | N/A — hard blocked upstream | **DEAD-ON-THIS-BOX** (torchcrepe fully substitutes) |
| **essentia** 2.1b6.dev1438 | Yes (wheel — surprising; director expected this to fail) | **AGPL-3.0** (commercial license available from MTG/UPF) | PitchYinFFT, OnsetDetection, general MIR toolkit | `PitchYinFFT`: only 3/6 hits produced a confident (conf>0.5) frame on these short percussive slices — least robust of the 4 pitch trackers here, though still correct when it fires (median 64.51Hz). `OnsetDetection(hfc)+Onsets`: 65 onsets on chug1.wav vs librosa's 119 (65 matched within 30ms) — essentia's HFC method is markedly more conservative on dense material. | **USABLE-BUT** (AGPL — fine as an offline authoring tool never linked into the shipped game; flag for legal if that ever changes) |
| **aubio** | **FAILS to build** — no wheel for any recent Python, source build errors: `ufuncs.c` uses a numpy ufunc C-API function-pointer signature (`void(*)(char**, npy_intp*, ...)`) that the current numpy C-API rejects (`incompatible pointer type`) | GPLv3+ | Pitch/onset/tempo (older alternative) | Build failure, see above | **DEAD-ON-THIS-BOX** (unmaintained since ~2018; librosa/parselmouth/essentia fully cover its use case) |
| **pyrubberband** 0.4.0 | Yes (wheel; needs the `rubberband` CLI, already present at `/usr/bin/rubberband` v4.0.0) | ISC (wrapper); CLI itself is **GPL-2.0** (Breakfast Quay; commercial license available) | Pitch-shift / time-stretch without touching the other | Controlled 220Hz sine, −3.9 semitones (expect 175.63Hz): measured **176.67Hz** via FFT peak. Duration preserved exactly (0.3000s→0.3000s). 0.021s. | **USE** |
| **librosa.effects.pitch_shift** | (part of librosa) | ISC | Same, in-process, no external binary | Same sine test: **176.67Hz** measured, duration preserved exactly, 2.03s (much slower — STFT/phase-vocoder path, not JIT'd) | **USE** (slower; fine for offline batch) |
| **pedalboard.PitchShift** | (part of pedalboard) | GPL-3.0 | Same, in-process | Same sine test: **180.0Hz** measured (2 FFT bins off — least precise of the three, still correct direction/ballpark), duration preserved exactly, 0.037s | **USE** (fastest in-process option) |
| **pyworld** 0.3.5 | Builds from source (Cython ext, ~16s). **Requires `setuptools<81`** — its `__init__.py` unconditionally imports the now-removed `pkg_resources` | Wrapper: MIT. Upstream WORLD C++ (M. Morise): permissive BSD-style (own license text, not SPDX-tagged) | WORLD vocoder: f0/spectral-envelope/aperiodicity analysis+resynthesis — the machine-choir voice | See dedicated section below — real, measured, and it needed a second attempt to get right | **USE** (setuptools pin required) |
| **librosa onset_detect** | (part of librosa) | ISC | Slice chug1.wav into hits | 119 onsets on the 20.7s file (5.8/s), 0.093s warm (13.8s cold on first call — numba JIT compiling; worth a warm-up call at pipeline startup) | **USE** |
| **essentia OnsetDetection** | (part of essentia) | AGPL-3.0 | Same | 65 onsets, 0.055s, no JIT warm-up cost; 65/119 librosa onsets matched within 30ms — catches the strong hits, misses ~half the softer ones in this dense chug | USABLE-BUT (see essentia license note) |
| **madmom** | **FAILS to build** — sdist only (no wheel for *any* Python), and the build itself is broken independent of Python 3.14: `ModuleNotFoundError: No module named 'Cython'` (doesn't declare Cython as a build dependency) | Code: BSD. **Pretrained beat/onset/downbeat models: CC BY-NC-SA — non-commercial** | Beat tracking / downbeat / onset (ISMIR-grade) | Build failure, didn't chase further | **DEAD-ON-THIS-BOX**, and license-blocked for this project even if it built |
| **pysfizz** 0.1.3 | Yes (wheel — brand new, uploaded 2026-07-08, 5 days before this audit) | BSD-2-Clause (binding); sfizz itself BSD-2-Clause | SFZ soundfont playback | Wrote a minimal `.sfz` pointing at a real project sample, `Synth().load_sfz_file()` → `True`, `get_note_info(60)` returned correct region metadata, `render_note(60, 100, 0.5, 1.0)` produced real non-silent stereo audio (peak 0.082) | **USE** |
| **fluidsynth** (CLI, already installed) | Pre-existing, v2.5.4 | LGPL | SF2 soundfont rendering | `fluidsynth -ni -F out.wav -r 44100 font.sf2 in.mid` rendered a real 3.66s file from the project's existing cached SF2 banks, headless (ALSA probe warnings are cosmetic — file output still works). Note: in `-ni` mode, output flags **must precede** the soundfont/MIDI positional args or fluidsynth silently misparses them. | **USE** (already in use) |
| **pyloudnorm** 0.2.0 | Yes (pure Python, wheel) | MIT | Real ITU-R BS.1770-4 integrated LUFS | Measured on all 3 project samples, <0.07s each: chug1.wav **−17.67 LUFS** (vs −15.15 plain RMS dBFS, Δ−2.52dB); organ_cathedral.wav **−21.54 LUFS** (vs −19.96, Δ−1.58dB); machine_factory.wav **−36.26 LUFS** (vs −36.57, Δ+0.31dB). K-weighting measurably diverges from RMS — confirms the hand-rolled RMS census has been reading the wrong number. | **USE** |
| **torch** 2.13.0+cu130 | Yes, but **default PyPI install pulls the full CUDA stack** (nvidia-cublas/cudnn/cufft/cusolver/cusparse/nccl/cusparselt + triton) — ~2.4GB download, ~5.5 min wall time here | BSD-3 | torchcrepe's backend | `torch.cuda.is_available() == True` — this box's RTX 4090 is real and usable. If a future box is truly GPU-less, use `--index-url https://download.pytorch.org/whl/cpu` to skip ~2GB of unused CUDA wheels. | USE (as a transitive dep; be deliberate about the index on GPU-less boxes) |
| **mido** 1.3.3 | Yes (pure Python) | MIT | MIDI message construction, needed to drive `pedalboard` VST instruments | Used to build the note-on/note-off pair for the Surge XT render test | USE (small utility, add if VST3 route is adopted) |

## Pitch detection accuracy — the numbers, honestly

Sliced 6 well-separated hits out of `chug1.wav` by onset detection and ran
all four trackers on each. **Measured median f0 clustered around 62–70Hz**,
not the ~92Hz ballpark expected going in. This is not a library
disagreement — three independent algorithm families (YIN-based pyin,
autocorrelation-based Praat, neural CREPE) converge tightly on each other
(61.96–65.41Hz on the hits they agree are voiced). It's a riff, not a
drone: different hits are different notes/strings, and the six sampled
here happened to land lower than the ~92Hz region the director had in
mind. Worth re-checking against a specific hit index if 92Hz matters for
a specific cue, but the pitch trackers are not the source of the
discrepancy — treat this as "verify which hit," not "distrust the tool."

Two of the six slices are genuinely unvoiced/percussive noise (pyin and
parselmouth agree — 0 voiced frames). Only ungated torchcrepe disagreed,
and only until periodicity-gated (see table). Essentia's YinFFT is real
but the weakest of the four on short slices at a 0.5 confidence gate —
loosen the threshold or feed longer windows if adopting it.

## The pyworld machine-choir test, in full

This one needed a second pass to do right, which is itself the useful
finding. `machine_factory.wav`, 4s chunk: `dio`+`stonemask` find it
correctly mostly-unpitched (40/801 frames = 5% voiced, 88.5–173.1Hz where
voiced at all — consistent with real industrial noise, not tonal
material).

First attempt: force `f0` flat to 146.8Hz, leave `aperiodicity` alone,
resynthesize. **Weak result** — FFT peak-to-trough harmonic-comb contrast
(energy at n×f0 vs the antinode at (n+0.5)×f0, the correct way to quantify
"is this actually a comb") was **2.8dB**, barely above the **4.8dB**
measured on the *untouched original* at those same frequencies (i.e.,
close to the noise floor — not a convincingly pitched sound).

Root cause: WORLD's aperiodicity parameter controls the periodic/noise
excitation mix *independently* of f0. The analyzed aperiodicity for real
machine noise is close to 1.0 (fully aperiodic) almost everywhere, so
forcing f0 alone tells the synthesizer "if there's a tone, put it here,"
but the tone's amplitude stays low because the analysis said there mostly
isn't one.

Second attempt: force `f0` flat **and** scale `aperiodicity` down to 5%
of analyzed (`ap * 0.05`) — the standard WORLD "robotization" move.
**Peak-to-trough contrast: 25.6dB.** Clear, strong, real harmonic comb.
Rendered to
`renders/pyworld_machine_choir_146.8hz_ap_forced.wav` in the scratchpad.
**This is the recipe to hand to the composition line**: force f0 *and*
crush aperiodicity, not f0 alone.

## Recommended toolchain

**(a) Auto-tuning sliced hits**: `librosa.pyin` for primary f0 estimation
(converges with parselmouth, already in the dependency tree for onset
work) → `pedalboard.PitchShift` for the actual correction (in-process, no
external binary, fastest of the three verified shifters, all three
preserve duration exactly). Cross-check with `pyrubberband` (marginally
more precise in the one controlled measurement here) if quality complaints
come up — it needs the `rubberband` CLI, already present on this box.
Reach for `torchcrepe` (periodicity-gated, threshold 0.21) when a hit's
fundamental is weak enough that YIN-family trackers disagree; GPU makes it
cheap here.

**(b) Real cab/amp tone via convolution**: `pedalboard` (pinned
`==0.9.22`) — `Pedalboard([Distortion(...), Convolution(ir_path), 
Compressor(...), Reverb(...), Limiter(...)])`, confirmed working
end-to-end at ~65–95x realtime. Three CC0 cab IRs fetched to
`scratchpad/musicgen/ir/` and load-verified (all via Freesound, matching
this project's existing sourcing convention — see SOURCES_LICENSES.md
append):
  - `jesterdyne_4x12_vintage_129399.wav` — 5.5ms (very short, likely a bare
    speaker-cone IR from a Korg AX1500g cab-sim unit, no polygon tail)
  - `jesterdyne_bg412s_godmode_618897.wav` — 1.28s (modified Behringer
    BG412S w/ Celestion V30 + Eminence DV77, includes polygon tail)
  - `tosha73_brown_cab_507167.wav` — 0.5s (mic'd cab, Audix i5, normal
    cab-IR length — probably the best default starting point of the three)

  **Bonus, changes the picture**: `pedalboard.load_plugin()` really does
  headlessly host VST3 plugins on this box. Surge XT (free, GPL-3.0, no
  sudo/installer needed — official Linux "pluginsonly" tarball) loaded and
  rendered a correctly-pitched note in testing. **This reopens the plugin
  route the director said was previously ruled out** — worth a real
  evaluation for cab/amp-sim plugins (many free ones ship the same
  installerless-tarball or portable-zip pattern), not just Surge itself.

**(c) Machine-choir vocoder**: `pyworld` (pin `setuptools<81` alongside
it) — analyze with `dio`→`stonemask`→`cheaptrick`→`d4c`, resynthesize with
`f0` forced flat to the target pitch **and** `aperiodicity` scaled down
(~0.05x) to make the voice actually buzz instead of staying a quiet
undertone. Confirmed via FFT peak-to-trough measurement, not vibes: 25.6dB
of comb contrast, real render in the scratchpad.

**(d) LUFS**: `pyloudnorm`, drop-in, MIT, sub-100ms per file, ITU-R
BS.1770-4 compliant. Replace the hand-rolled RMS census metric with this.

## License note (read before shipping anything through these tools)

Several of the most useful tools here are copyleft: pedalboard (GPL-3.0),
Surge XT (GPL-3.0), rubberband CLI (GPL-2.0), essentia (AGPL-3.0). None of
this blocks using them as **offline asset-authoring tools** — render the
final one-shot/stem, commit *that*, and none of these libraries ship
inside the game binary or its runtime. It would become a real question if
any of them were ever embedded at runtime (e.g., live convolution reverb
computed in-game) — that's a different distribution question and worth
actual legal review if it comes up, not a snap judgment here.

## What's in the scratchpad

`scratchpad/musicgen/tests/` — the 5 smoke-test scripts run for this audit
(pitch detection, pitch-shift, pedalboard chain, pyworld vocoder, VST3
hosting, onset detection). Throwaway/audit code, not composition code.

`scratchpad/musicgen/ir/` — the 3 CC0 cab IRs (mp3 preview + decoded wav).

`scratchpad/musicgen/vst3/` — Surge XT Linux "pluginsonly" build (~500MB
extracted; not committed, re-fetchable from the GitHub release URL logged
in SOURCES_LICENSES.md).

`scratchpad/musicgen/renders/` — every test's audio output, including both
pyworld machine-choir variants (naive and correct) and the Surge XT MIDI
render, for anyone who wants to listen rather than trust the FFT numbers.

## Time spent

Roughly 2 hours wall-clock against a 40-minute soft budget — the numpy/
numba ceiling chase, the pedalboard SIGILL bisection, and the ~5.5-minute
CUDA-stack download for torch each cost real time and each turned into a
genuine finding rather than a dead end, so the overrun bought real
information rather than just running long.
