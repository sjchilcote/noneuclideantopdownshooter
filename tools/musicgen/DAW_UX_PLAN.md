# DAW UX pass — plan, graded by ux-principles-interactable-software.md

Inputs: the 13-agent UX scan (out/daw_ux_inventory.json, 91 items), the
main-thread workflow brainstorm, and the playbook. This document is the
playbook applied: what got promoted, what got cut, and what "done" means.

## Step 0 — paradigm gate

Real-time / media app (continuous loop, transport, playhead) → binding
sections: §4 control-loop feedback + glanceable HUD, §5 status truth +
liveness, §7 state machine, §3 discoverability, §15 gate with the
**screen-recording ledger** form. The file watcher is additionally a
machine-operated surface (the artist's DAW "calls" it by writing files)
→ §10's structured-contract discipline applies to file drops.

## §9 gate — patch, not overhaul

Run over the whole artifact: the frame (DAW-session metaphor over a
recorded run, with hot-swap) matches the target user's mental model by
construction, was just validated by the director, and no structural
trigger fires (first pass; no diminishing returns; IA coherent).
Verdict: **patch level**. The §9 from-scratch question — "would I build
it this way today?" — yes: same frame, same surfaces.

## P0 — Status must be true (§5, §12): the lie list

Every item here is a status that can currently lie. Fix = derive from
the work, not intent; acceptance = the §5 falsifiability test named
with each item ("force X; the indicator must say so").

1. **48k/24-bit/format guard.** A DAW-default bounce plays as static or
   detuned under green `ready`. Load-time check of samplerate/width;
   resample 48k or refuse with a §10-grade message ("prayer.wav is
   24-bit 48 kHz — export 16-bit 44.1 kHz WAV"). *Force: drop a 24-bit
   48k wav → red message, old mix keeps playing.*
2. **Render-thread exception guard.** Any decode failure freezes amber
   `rebuilding…` forever. try/except → red `RENDER FAILED: <cause> — R
   retries`, previous buffer stays playable. *Force: drop a truncated
   wav mid-write.*
3. **Watcher = watchdog (§8 resilience).** The always-on intent is
   "replace-and-hear never silently stops," so the fix is not just an
   error surface: guard the loop, auto-restart it, and show liveness
   ("watching 5 folders · scanned 0.4s ago") so silence is
   distinguishable from death. *Force: kill/starve the watcher thread →
   liveness chip goes stale, watchdog restarts it.*
4. **Write-settle by quiescence.** Replace the fixed 0.3s sleep with
   mtime/size stability across scans + rebuild only after a quiet poll
   (also fixes the multi-file-bounce hybrid mix). *Force: slow-copy a
   stem in 3 chunks over 3s → exactly one rebuild, of the final file.*
5. **Wrong-length stem detection.** A loop-length export silently
   silences later bars. Compare against the form length on load; warn
   "prayer.wav is 8 bars, bank needs 36 — bars 8+ silent." *Force: drop
   an 8-bar wav.*
6. **Non-audio-contract drops.** `prayer.aiff` = non-event; `prayer
   (1).wav` = confident no-op reload. Glob common extensions to warn
   "ignored — export WAV/OGG"; diff changed basenames against the stem
   keys this session actually plays → "not a stem this session plays."
   *Force: both.*
7. **Reload-into-muted-lane note** ("lane muted — unmute to hear") and
   **companion-stem note** (new prayer.wav still plays old
   prayer_tail.wav at seams). *Force: solo drums, drop lead.wav.*
8. **Unresolvable bank / missing stem / stale bank.json.** Silence
   under green ready + `None` path; ruler stays stale after bank.json
   edits even on R. Red per-bank status; re-parse Project on bank.json
   change and on R. *Force: rename a bank dir; edit sections.*
9. **Mute+solo contradiction** (muted+soloed lane plays at full volume
   with red M lit) and **unknown lane names** leaking through solo.
   Make the effective-mute computation the single source for both audio
   and display. *Force: mute+solo same lane; add a bogus lane to taps.*
10. **Status surface redesign (§4 mode visibility).** One 13px string
    carries five states; errors wear busy-amber; the Royal-Majesty
    trap. Color-coded chip (green ready / amber busy / red error),
    flash on transition, mix generation counter ("mix #4 · from
    prayer.wav · 21:14:03") so old-vs-new is answerable at a glance.
11. **ffmpeg/video honesty.** Failures swallowed + retried forever;
    missing video indistinguishable from no feature. One red "video
    unavailable (<cause>)" chip; stop the spawn storm; stale-frame dim.
    *Force: remove ffmpeg from PATH; point --video at nothing.*
12. **Thread hygiene backing all of the above:** render-generation cap
    (drop superseded renders early), stem-cache lock, single writer for
    status. CLIP gets an amount + location + reset (jump-to-loudest
    doubles as the §1.5 headpolygon check).
13. **Startup failures** are raw tracebacks post window-flash → §10
    message + nonzero exit ("recording not found: <path>").
14. **Truth-adjacent visuals** (display asserting things the mix
    contradicts): death halts silence everything but draw as a 20px
    tick → full-height red bars; stab markers parsed but never drawn →
    draw; riser landing invisible → draw the 2-bar envelope to its
    strike; `music_stab`/soft-jump filtering documented in the legend.

## P1 — Undo and state design (§7)

15. **A/B last-two renders = the undo of the swap action.** Keep the
    previous buffer; one key toggles old/new at the same playhead.
    Promoted by §7 from convenience to default-for-destructive-action
    (the swap currently destroys the only copy of "before").
16. **Session recall instead of quit-confirm.** ESC-quits-instantly is
    a slip risk, but a confirm taxes every quit to catch a rare slip
    (§7 anti-pattern). Make the slip cheap instead: persist playhead +
    mutes + window state to the rec dir; restore on reopen. ESC stays
    instant. (Scan's "ESC confirm" suggestion **rejected** per
    playbook.)
17. **Designed non-happy states:** initial-render state (transport that
    explains itself instead of dead SPACE; >1s ⇒ progress per Nielsen
    thresholds — show render progress fraction), end-of-session state
    (SPACE at end restarts from 0 instead of dying), NO-MUSIC-TAPS
    state explains the dead transport, loudness anchor latch guarded
    against M/S-during-first-render.

## P2 — Gulf of execution (§3): each item carries its observed need

Per §8, every addition below names a concrete observed instance, not a
symmetry. Additions without one were cut (see Cut list).

18. **`?` help overlay + marker legend.** The manual is a docstring the
    user can never see = the taped-sign anti-pattern inverted; five
    glyph codes with zero legend = recall-over-recognition. (Observed:
    every beta persona asked how they'd learn the controls.)
19. **Numeric go-to + copy-timestamp.** Director feedback is
    timestamp-shaped (observed: "listened at 3:42"-class notes all
    week). `G` → type mm:ss; `C` → copy "05:23 / bar 30 / tutti_x".
20. **Marker/section jump keys.** (Observed: this week's verification
    work was "audition every riser/sting/halt" — done by eyeballing
    8px glyphs.) `,`/`.` prev/next marker; up/down section starts.
21. **Horizontal zoom.** (Observed: riser-landing verification was done
    numerically because one bar = 3.8px is unverifiable by eye.)
    Stepped zoom about the playhead; overview strip stays full-length
    as the navigator — follow-playhead on.
22. **Loop region.** (Observed: the overnight defect passes re-listened
    fixed 16s windows dozens of times; the artist's seam work is the
    same shape.) Drag on ruler sets cycle; L toggles.
23. **Bounce/export.** (Observed: the whole judge pipeline exports
    windows; artist↔director exchange will be clips.) `B` bounces the
    loop region (or full mix) to a wav next to the rec.
24. **Export-spec + stem-key display (P0.7's twin).** Per-bank line
    "110 bpm · 36 bars · stem 78.5s · 44.1k/16-bit" + current stem key
    per track at the playhead — closes hear-it → name-it →
    overwrite-it.

## P3 — feedback fit and comfort

25. Audio chunk feed off the render loop (real dropout conditions);
    0.2s→shorter chunks for seek feel where cheap.
26. Key repeat for arrows; bar nudge from actual bar events, not the
    session median; scrub hit-region excludes the help line; END goes
    to the end.
27. Redraw caching (static layers to surfaces; blit per frame).
28. Legibility batch: distinguishable section colors + labels,
    palette de-collision (CONTEMPT vs groove hue), bank-boundary
    labels, overview both channels, truncation guards.
29. Resizable window/SCALED — deferred unless the artist's display
    forces it (the one structural rework; §8 restraint).

## Cut list (§8: no observed need, or actively harmful)

- **Per-track gain trim** — would make the monitor lie about the game's
  actual mix; the tool's core promise is truth. Unreachable-bad-state
  argument: don't add it.
- **Quit confirmation** — replaced by session recall (§7).
- **Half-speed audition, exclusive-solo modes, play-from-last-start,
  master fader, bigger video, in-app bank/recording pickers, hover
  inspection layer** — hypothesized needs only; revisit on an observed
  instance from the actual artist (Mom-Test bar: a past occurrence,
  not "they might").
- **Watcher on/off switch** — §8's literal example; resilience instead
  (P0.3).

## Unit-audit addendum — six Sonnets fanned by code unit (2026-07-18)

Eighteen findings survived dedup against the inventory and this plan;
every one carries a verified mechanism, several carry measurements.

### P0 additions (status truth / crash class)

30. **Main-thread audio calls unguarded** (Player `_start`/`poll`/
    `_chunk`): the only failure mode that kills the whole process, not
    a thread — an audio-backend hiccup (PipeWire restart, device
    unplug) mid-playback crashes the app with total session loss.
    Extend the P0.2 guard pattern; `AUDIO FAILED — R retries` status;
    keep last-good playhead. *Force: restart the audio server while
    playing.*
31. **CLIP escapes the generation guard** (cross-confirmed by two
    independent audits): `self.clip` is written between the two
    supersession checks, so a discarded render's verdict displays
    against the newer, playing mix. Move the write inside the locked,
    gen-checked block. *Force: two quick M/S toggles with mixes that
    disagree on clipping.*
32. **VideoMonitor cache race = app crash**: unlocked dict, worker
    FIFO-evicts between the main thread's `in` check and `[q]` read →
    KeyError propagates out of `draw()` and kills the process. Same
    class as the stem-cache race, separate dict, worse blast radius.
    Lock it (or `.get`). *Force: heavy back-scrubbing with the cache
    at its 400 cap.*
33. **Video frame truth, four ways**: (a) `cur` only advances on an
    exact cache hit → under sustained extraction-slower-than-playback
    the monitor freezes on an arbitrary stale frame, unbounded, never
    self-correcting — track `(surf, q_of_surf)` set by the worker and
    diff against live q every draw; (b) the worker blocks up to 10s in
    one `subprocess.run` with nothing marking the video pane as the
    stuck element — "video lagging Ns" badge + supersede-aware
    extraction; (c) cache keyed by time only — a regenerated mp4
    serves stale frames forever and R doesn't clear it — key by
    (q, path, mtime); (d) `-ss` before `-i` is keyframe seek: frames
    can be a full GOP earlier than requested, silently — move `-ss`
    after `-i` (accurate seek; fine at one frame per request) and
    probe the shipped mp4's GOP to size the error we've been living
    with. *Forces: slow storage; huge mp4; overwrite mp4 mid-session;
    ffprobe the GOP.*
34. **No rec↔video correspondence guard**: a wrong-session mp4 of
    similar length plays with full confidence — worst case for a
    ground-truth monitor. Cheapest: ffprobe duration vs proj.dur,
    warn on mismatch; stronger: stamp renders with the recording id.
35. **Watcher input-contract gaps beyond P0.6**: case-sensitive globs
    (`PRAYER.WAV` from a mac/win-habituated artist is a non-event —
    match case-insensitively); stem-cache key needs `st_size` (a
    timestamp-preserving restore can collide with a cached mtime and
    replay stale audio under fresh `ready`).
36. **The settle window is a silent seam**: nothing acknowledges
    "saw your save" until the rebuild starts, and P0.4's quiescence
    fix lengthens that gap — emit `detected <files> — settling…`
    the moment a change is seen.
37. **Input-side seek race**: `handle()`'s `seek()` calls
    (arrows/HOME/END/drag) take no lock against `_render`'s buffer
    swap — torn reads exactly during the headline gesture (scrubbing
    during a hot-swap), distinct from the poll-side race. Take
    `self._lock` around input-driven seeks.
38. **Event dispatch continues after quit**: no `break` after
    `running = False`, so a queued R/M/S in the same frame batch can
    spawn a render thread in the same tick as `pygame.quit()`.
    One-line fix.

### Display-contradicts-sound (Project vs the mixer's ground truth;
empirically verified by re-running the real mixer)

39. **Bar-0 doubling is a MIXER bug, not just display**: the synthetic
    pre-roll entry sums a second, different bar-slice into the same
    samples when the first tap is at t=0 (RMS 0.040 measured vs 0.033
    single-bar) — a doubled-voice artifact at the start of every
    rendered session, including shipped videos. Fix in mkvideo (skip
    the synthetic bar0 when it collides with the first real tap),
    then A/B-verify per the release-grammar protocol before adopting;
    give Project a matching model either way.
40. **Rotation crossfade has no visual counterpart**: for ~2 bars
    after each bank switch, roughly half the audible mix is the OLD
    bank's fading continuation (measured RMS 0.118, peak 0.67 in the
    diff) while the transport instantly names only the new bank.
    Shade the crossfade window; transitional label
    ("dies_irae → idumea").
41. **`~f` farewell suffix unstripped in Project**: fading bars draw
    as flat sustained blocks, and the stored key `bass_warden~f`
    would poison the planned stem-key display (P2.24) with a filename
    that doesn't exist. Strip suffixes at parse, keep a fade flag,
    taper the block's right edge.
42. **Waveform x-axis mismatch**: overview binned over `dur+1s` of
    buffer but drawn on the ruler's `dur` span — ~2px on the 649s
    session, ~8% skew on a 10s debug recording. Bin over
    `dur × RATE` samples.

Audits also *cleared* (measured, not assumed): all 42 jump markers
land at delta 0.000 from their bar taps; `key@idx` free-running holy
keys never occur in any real recording; the video worker's CV protocol
has no lost-wakeup bug; the message audit found nothing beyond the
inventory; argparse contract is adequately covered by planned items.

## Affordance-expectation audit (per-element, screenshot-based, 2026-07-18)

Method (director's protocol): every UI element highlighted with a red
bounding box in a real screenshot; an isolated no-context Sonnet asked
what left/right/middle-click and vertical/horizontal scroll do; judged
against the handler's ground truth; mismatches got a generated tooltip
injected into a fresh reader's prompt and iterated for clarity and
concision (a shortened tooltip only kept if it re-passed). 22 elements,
92 agents, full transcripts in out/daw_affordance_audit.json.

**Result: 14/22 self-evident** (naive expectations correct — all
timeline surfaces, M/S boxes, status chip, info panel), **8/22
mismatched, all corrected by one tooltip round, 0 unresolved.** Every
right/middle/scroll expectation across all 22 elements was correctly
"nothing" — the mismatches are all left-click.

Disposition per §3 (a tooltip whose only job is to explain a confusing
control is the taped sign — where the expected behavior is already
planned, implement it instead of shipping the tooltip):

| Element | Naive expectation | Disposition |
|---|---|---|
| play glyph | click toggles play/pause | **Implement it** (trivial; better than the tooltip). |
| time readout | click = numeric time entry | **Implement** — this is P2.19's numeric go-to, now with expectation evidence; put it on the readout. |
| clip chip | click resets the latch | **Implement** — folds into P0.12's CLIP reset. |
| help line | expects nothing; reality seeks | **Fix the hit-region** (P2.26) — the audit empirically confirms the overreach surprises users; do not tooltip a defect. |
| video monitor | click enlarges | Tooltip for now ("Video preview only — no clicks or controls."); enlarge stays deferred — expectation is §3 evidence of surprise, not §8 evidence of need. |
| bank title | click opens a bank picker | Tooltip ("Bank name — display only, not clickable"); in-app switching stays deferred. |
| value labels | legend-click toggles curves | Tooltip ("Read-only labels; clicking won't toggle or hide curves.") — or implement curve-toggling if the hover layer lands anyway; it's cheap and expectation-aligned. |
| track name | click selects the track | Tooltip ("Track name (label only)"); there is no selection model to attach. |

The four kept tooltips + the audit's refined texts for the implemented
ones are the seed content for the §3 hover/help layer (P2.18); the
audit's judged texts are in the results JSON verbatim.

## Definition of done (§15, media-paradigm ledger)

The earlier headless smoke test is a **grant-everything harness** —
happy-path only, structurally blind to every P0 item. It no longer
counts as verification. Done means:

1. **Fault-injection suite** (§14): scripted forces for every P0 lie —
   48k wav, 24-bit wav, aiff, misnamed, truncated-mid-write, slow
   multi-file copy, short stem, killed watcher, missing ffmpeg, missing
   video, renamed bank dir, edited bank.json, mute+solo, M/S spam —
   each asserting the *indicator*, not just the audio. Addendum forces:
   audio-server restart mid-play, disagreeing-CLIP M/S race, video
   cache at cap + back-scrub, mp4 overwrite mid-session, wrong-session
   --video, GOP probe of the shipped mp4, `PRAYER.WAV`, mtime-preserving
   restore, ESC+R same-frame batch, scrub-during-hot-swap, short-rec
   waveform alignment, bar-0 doubling A/B, crossfade-window display,
   `~f` bar rendering.
2. **Screen-recording ledger**: one timestamped cold-session capture —
   launch → first listen → scrub → zoom/loop → mute/solo → a real
   hot-swap → a forced failure and its red status → A/B toggle →
   quit/reopen recall — with every state legible on screen. Frames
   personally reviewed (in-situ law).
3. **Cognitive walkthrough** (§14) by a context-free agent driving the
   real keybindings against the running tool, plus the director as the
   first non-builder human. The real §2 test — watching the actual
   artist cold — runs the day they onboard, and its findings outrank
   this whole document.

## Execution record — 2026-07-18

Everything above is BUILT, VALIDATED, TESTED. Commits: 9640bca
(mkvideo bar-0), 36cb5f7 (daw v3, all tiers), fb0d2ae (fault suite +
its 2 catches), plus the ledger/walkthrough commit.

- **P0 1–14, addendum 30–38, display truth 40–42**: implemented in
  daw.py (v3). Addendum 33d resolved by measurement: `-ss` before
  `-i` is byte-identical to output-seek on this ffmpeg at 3 probe
  points across the 16.7s GOP — the hypothesized keyframe error is
  zero; fast form kept.
- **Item 39 (bar-0 mixer bug)**: fixed in mkvideo (pre-roll = trimmed
  tail of the previous slice, dropped at t=0 collision). A/B verified:
  winning session first-bar RMS 0.0401→0.0332, zero diff beyond bar
  0; no-collision geometry byte-identical. Clips for audition:
  out/ab_bar0_{old,new}.wav. Shipped videos NOT re-rendered — next
  render adopts the fix (release decision stays with the director).
- **P1 15–17, P2 18–24, P3 25–28**: implemented. 29 (resizable)
  stays deferred per this plan's own ruling.
- **DoD §1 fault-injection**: tools/musicgen/daw_fault_suite.py — 36
  forces, all green, asserting indicators. The suite itself caught
  two defects (watch_dirs dropped missing dirs so a renamed bank
  never recovered; rendered buffer overran the ruler span by ~0.2s) —
  both fixed.
- **DoD §2 ledger**: out/daw_ledger/ — 12 timestamped cold-session
  frames (launch → listen → scrub → zoom/loop → mute → REAL hot-swap
  via prayer.wav-beside-ogg, 330Hz spectrally confirmed in the mix →
  24-bit forced failure → recovery → A/B → help → reopen recall),
  personally reviewed. Review caught two defects (error chip
  truncated its remedy; duplicate notes) — both fixed, failure frame
  re-captured with the full remedy line.
- **DoD §3 walkthrough**: out/daw_ledger/walkthrough.md — context-free
  agent, 7/7 tasks, zero stuck moments; its one finding (the video
  lag counter reads as an error during normal playback) fixed:
  badge now reserved for >2.5s stalls.
- Outstanding: the director as first non-builder human, and the real
  artist cold test on onboarding day.
