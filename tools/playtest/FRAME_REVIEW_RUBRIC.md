# Gameplay frame review rubric

How to validate a recorded run (a `--record` capture directory) by actually
looking at it, every 10th sim tick, frame by frame. This exists because a
soak test once "passed" while the game sat on a press-any-key screen for an
hour: aggregate metrics lie, eyes don't.

## Protocol

1. Capture a run: `uv run python -m perihelion --seed N --mute --record DIR
   --record-seconds S` (add `--start-chunk K` for mid/late content).
2. Sample it: `uv run python tools/playtest/framecheck.py --rec DIR` writes
   `review/` with every 10th sim tick's frame and a `manifest.json` of
   `(frame, t_seconds)` pairs.
3. Reviewers (Sonnet agents) each take a **contiguous** time span and read
   every sampled frame in order — no skipping, no "spot checks". Consecutive
   frames are 1/6 s apart; motion between them is part of what's reviewed.
4. Every finding cites frame filenames and timestamps. A reviewer that
   reports "all clear" must also report what it checked per category below,
   or the pass doesn't count.

## What to look for (per frame)

**Readability.** Any text cut off by a screen edge, overlapping other text,
or too small/low-contrast to read at a glance: radio bar lines, location
titles, HUD numbers, terminal/conversation text, menu items. Quote the text
you can read; flag what you can't.

**Seamlessness (constitution invariant).** Brightness or palette must never
step at a room boundary — the world is one continuous space. Watch walls
and floors that span portal lines. Entities (enemies, pickups, bullets,
props) must never be clipped by a room boundary while straddling it.

**Lighting.** Darkness falls off from the player, warm near, dark far. Flag
any frame where a whole room pops bright/dark on entry, or glows (muzzle,
screens) fail to punch through the darkness field.

**Diegesis.** Props/terminals should read as belonging to the room's
function (dock, chapel, medbay...). Flag floating/misaligned props,
terminals not mounted to walls, furniture blocking doorways, or rooms that
read as empty geometry.

**HUD sanity.** HP/ammo/weapon consistent with the action (firing decreases
ammo, hits decrease HP); no NaN, no negative, no frozen values across an
active fight.

**Motion continuity (frame pairs).** Between consecutive sampled frames:
teleports without a portal crossing, entities popping in/out inside the
view, the player stuck (same position ≥ 12 consecutive samples ≈ 2 s while
not reading/talking), camera snaps.

**Scene flow.** Cards/menus/conversations should each be on screen long
enough to read but not stall: flag any non-gameplay scene occupying more
than ~10 consecutive samples, and any conversation frame whose speaker
label or choice list looks broken.

## Severity

- **P0** — invariant violation (seam, clipped entity), softlock, unreadable
  core text, crash frame (black/garbage).
- **P1** — wrong-but-playable: HUD glitch, prop misalignment, lighting pop,
  pacing stall.
- **P2** — polish: awkward composition, weak diegesis, minor overlap.

## Report format

JSON list of findings: `{"severity": "P0|P1|P2", "category": "...",
"frames": ["frame_000123.png"], "t": 41.1, "what": "...", "evidence":
"what is visible in the frame that supports this"}` — plus a `checked`
summary line per category. Findings without a frame citation are discarded.
