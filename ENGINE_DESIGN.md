# PERIHELION — Engine & Game Architecture

Working title: **PERIHELION** — a Teleglitch-like survival shooter aboard a station
falling into the sun, set in a non-Euclidean graph of rooms. This document defines
the from-scratch rewrite: a Rust engine core (`necore`) that owns everything that
never changes — the geometry, the simulation, the invariants — and a Python game
layer that owns everything artistic: mechanics, scripting, rendering style, juice,
content. `design_document_2.md` §11 is the constitution; this document is the law.

## 0. Prime directives

1. Every §11 invariant of `design_document_2.md` holds. No world space. Convex CCW
   rooms. Transforms are arbitrary invertible affine maps. `t → 1−t` at every edge
   crossing. Transitions are imperceptible.
2. **AI-testability is a first-class requirement.** The sim is deterministic and
   headless-runnable; every feature must answer "how do I test this with no human?"
   before it is built. That includes *fun*: the harness exposes metrics and captures
   screenshots/GIFs/audio for LLM judging.
3. The Rust core is verified by property tests, including an *oracle test*: a
   planar-embeddable level simulated both as a room graph and as flat Euclidean
   geometry must agree exactly.

## 1. Repository layout

```
engine/                 Rust workspace
  necore/               pure Rust: math + sim + visibility (no PyO3, proptest suite)
  necore-py/            PyO3 cdylib (maturin), thin binding layer
game/                   uv project, package `perihelion`
  perihelion/
    app.py              window, fixed-timestep loop, scene stack
    render.py           immediate-mode renderer from necore draw lists
    sim.py              GameSession: engine world + Python entity scripting
    entities/           player, enemy archetypes, projectiles, pickups, props
    weapons.py          weapon definitions (data-driven)
    juice.py            screenshake, hitstop, particles, decals, flashes
    audio.py            mixer, sound bank, graph-propagated positional audio
    narrative.py        Ratio radio lines, terminals, level intro cards
    hud.py, menus.py
    levels.py           level loading (JSON v2), campaign manifest
    editor/             level editor (same renderer, same engine)
    testkit/            headless session, replay, bot policies, metrics, capture
tools/
  soundgen/             numpy SFX/music synthesis → game/assets/sfx/*.wav
  playtest/             LLM/Gemini judge harnesses
levels/                 campaign JSON + lore text
```

## 2. The engine core (`necore`, Rust)

f64 everywhere. No RNG in the engine. No I/O. Pure state machine:
`World` + inputs → `step()` → state + events. Everything queryable.

### 2.1 Types

- `Vec2`, `Mat3` (row-major homogeneous 3×3; full inverse; `apply_point`,
  `apply_dir` = linear part only). Transform composition is the only way
  coordinates ever relate across rooms.
- `Room { verts: Vec<Vec2> /* CCW, centroid at origin */, edges: Vec<Option<Portal>> }`
- `Portal { target_room, target_edge, xform: Mat3 /* target-room coords → this-room coords */ }`
- `Entity { room, pos, vel, dir, radius, mass, restitution_entity, restitution_wall,
  group: u8, max_substep, alive }` — circle collider for entity-entity; the polygon
  *sprite* is a Python-side artistic concern. Group×group collision mask is a
  16×16 bit matrix set from Python (player, enemy, pbullet, ebullet, pickup, prop…).
- `restitution_wall = 0` → slide (kill normal component; Teleglitch handling),
  `1` → elastic bounce; anything between works.

### 2.2 World construction

- `add_room(verts) -> RoomId` — verts are re-centered on centroid, validated convex
  CCW (auto-rewound if CW; rejected if concave).
- `connect(a, edge_a, b, edge_b)` — computes the rigid transform aligning edge_b of
  room b flush against edge_a of room a (rotate 180° across the shared edge,
  translate midpoints together), stores mutually inverse transforms on both edges.
  Handles self-connections (a==b, even edge_a==edge_b: the mirror).
- `connect_with_xform(a, edge_a, b, edge_b, m)` — arbitrary invertible affine
  (scaling corridors, chirality flips) for the late game. Nothing in the engine may
  assume rigid motion.
- Edge lengths need not match: the transform maps edge_b's span onto edge_a's span
  (scale along the edge is allowed on `connect` only when lengths differ ≤ tolerance;
  otherwise use `connect_with_xform` deliberately).

### 2.3 Visibility (the renderer's brain)

`visible_set(camera_room, cam: Mat3 /*room→screen*/, screen_w, h, max_depth, max_instances) -> Vec<DrawInstance>`

Iterative portal traversal from the camera room. A frustum through a portal is
represented as **three half-planes**: the portal line itself plus the two rays from
the apex through the visible segment's endpoints. This stays exact and
well-conditioned at any view angle — there is no "promotion" hack; skating along an
edge evolves smoothly by construction. The visible region of a room instance is the
convex polygon `room ∩ frustum` via Sutherland–Hodgman. Recursion: for every other
portal edge of the room, intersect it with the current frustum (parametric segment,
**flip t → 1−t crossing over**), transform apex + segment into the child's space,
recurse. Terminate on: depth, instance cap, visible-segment length < ε, clipped
polygon screen-bbox off-screen or area < ~2px². Dedup key: (room,
quantized-6-float-xform, quantized-segment) — the same room seen via *different*
paths at different places must all render; identical repeats must not.

`DrawInstance { room, xform /*room→screen*/, clip_local: Vec<Vec2>,
clip_screen: Vec<Vec2>, depth, entities: Vec<(EntityId, screen_pos, screen_dir, fully_inside)> }`

Returned deepest-first (painter's order). The engine also exposes
`clip_polygon(subject, clip)` and `clip_polyline(pts, clip)` so the Python renderer
can clip room detail geometry and boundary-straddling sprites exactly, with zero
mask surfaces.

### 2.4 Simulation

`step(dt) -> Vec<Event>` — fixed dt (1/60). Substepped per entity
(`max_substep` distance, e.g. bullets use their radius). Hard-won robustness rules
from the prototype, now law:

- Wall test = signed distance vs CCW edge normals (convexity ⇒ interior is the
  half-plane intersection). Edge spans extended slightly past endpoints so vertex
  seams can't leak (safe by convexity).
- Portal transfer only when velocity points out through the edge
  (dot(vel, normal) > ε) — kills boundary ping-pong. Position maps through the
  portal's inverse, vel/dir through its linear part; epsilon nudge (1e-3 units,
  a *real* epsilon) into the new interior.
- After any collision resolution the remainder of the substep re-runs the **full**
  pipeline; time refunds use computed collision time. Iteration cap with
  velocity-zeroing fallback (never tunnel, never hang).
- Entity-entity: circle-circle, group-mask filtered, impulse response with mass +
  restitution. Room-local only (rooms are large relative to entities; the nudge
  keeps membership decisive). Broad phase: per-room lists (the room *is* the
  spatial index).
- Events: `Transfer{ent, from, to, edge, xform}`, `WallHit{ent, room, edge, point,
  normal, speed}`, `Contact{a, b, point, normal, rel_speed}` — Python turns these
  into damage, sound, particles, camera rebasing. The engine never decides what a
  collision *means*.

### 2.5 Queries

- `raycast(room, origin, dir, max_hops, max_len)` — walks portals (transforming ray
  at each crossing), returns wall hit or entity hit with the accumulated transform.
  Line-of-sight for AI, hitscan weapons, audio occlusion.
- `route_next_edge(from_room, to_room)` — Dijkstra over the room graph, cached per
  destination, invalidated on topology change. Path state is room/edge sequences,
  never positions.
- `hop_distance(a, b)`, `rooms_within(room, hops)` — activity horizon + audio
  attenuation.
- `rebase(cam, portal_xform)` — the camera composition for seamless transfer.

### 2.6 Property tests (proptest, in `necore`)

1. `connect` invariants: paired transforms mutually inverse (‖M·M⁻¹−I‖ < 1e-9);
   mapped edge endpoints coincide with orientation flip.
2. Transfer roundtrip: cross an edge and come back ⇒ pos/vel restored (< 1e-6).
3. Visibility: every clip polygon is convex, ⊆ room, ⊆ frustum half-planes;
   deeper instance's portal segment ⊆ parent's clip.
4. Containment: after arbitrary force sequences, every entity is inside its room
   polygon (+ε). *The* anti-tunneling invariant.
5. Energy: collisions with restitution ≤ 1 never increase total kinetic energy.
6. **Euclidean oracle**: generate a random planar level (grid rooms glued
   Euclideanly), simulate/raycast/render both as room-graph and as flat geometry;
   positions, hits, and visible polygons must agree to 1e-6. This single test
   validates traversal, transforms, transfer, and visibility together.
7. t-flip: parametric quantities crossing any edge obey t → 1−t (checked via
   marked points on glued edges).

## 3. The game layer (Python, pygame-ce)

### 3.1 Loop & determinism

Fixed 60 Hz sim tick, render decoupled (interpolation unnecessary at lo-fi).
`GameSession(level, seed)` is pure: `tick(InputFrame)` → state; pygame only in
`app.py`/`render.py`. `InputFrame {keys bitfield, mouse_pos, buttons}` — recorded
per tick into replays; `seed` drives one `random.Random`. Same level+seed+inputs ⇒
bit-identical run. This is the AI-testability keystone.

### 3.2 Rendering (immediate-mode, lo-fi)

Internal resolution **480×270**, integer-scaled ×3 to 1440×810 window with nearest
neighbor — chunky Teleglitch grit and a hard perf ceiling. Per DrawInstance,
back-to-front: floor = flat dark polygon (`clip_screen`) + room detail primitives
(static per-room grime: lines, plates, stains in local coords) clipped via engine
and drawn as vector strokes; walls = thick bright segments on the visible span;
depth dimming per instance; entities as rotated polygon sprites (engine-clipped
when straddling a portal). The same entity legitimately renders in several
instances at once — that's the game. Post: vignette, scanline flicker on damage,
screenshake applied to the final blit offset. No per-frame surface allocation
anywhere.

### 3.3 Combat (Teleglitch DNA)

WASD screen-relative (via inverse camera rotation), mouse aim, force+friction
movement. Weapons data-driven: knife (infinite, desperate), pistol, SMG, shotgun,
rivet rail, **lightning cannon** (signature AOE, long cooldown, graph-propagating
flash). Ammo scarce; every corpse and crate matters. Enemies: husk (rusher), mite
(fast swarm), spitter (ranged arc), brute (tank, door-breaker feel), shrieker
(summons through portals — the non-Euclidean enemy), warden (endgame). HP low,
death fast, checkpoints at level start.

### 3.4 Juice (from Vlambeer/Nuclear Throne canon, tuned darker)

Screenshake (magnitude-clamped, decaying), 40–60 ms hitstop on kills, muzzle flash
that briefly lights the floor polygon, tracers, casings, blood decals that
**persist in room-local space** (so you recognize a room you've "never" visited),
corpse persistence for the same reason, damage flash + heartbeat vignette at low
HP, kill-confirm sound layering. Horror pacing: silence is the default; sound is
information (enemies audible through portals with hop attenuation before visible).

### 3.5 Audio

Procedurally synthesized bank (tools/soundgen, numpy → wav): layered gunshots,
impacts, deaths, pickups, Ratio radio blips, drone beds per level tier. Positional:
pan/volume from portal-chain transform when audible instance is visible, hop-count
attenuation otherwise. Every generated sound is judged by Gemini (johnny/
autoclipping recipe) against a description of intent before acceptance.

### 3.6 Narrative delivery

Ratio radio lines (typewriter text, bottom bar) triggered by level events;
terminal props with lore pages; level intro cards. Arc: mundane maintenance sweep →
creeping wrongness → the Connection revealed → Guard-ending stinger. The game never
says "non-Euclidean"; Ratio's growing unease says it for us.

### 3.7 Levels (format v2)

JSON: `{name, tier, rooms: [{id, verts, edges: {idx: {room, edge} | {room, edge,
xform}}, entities: [{type, pos, props}], detail_seed}], player_spawn, lore,
music}`. Campaign manifest orders levels along the §8.1 escalation curve. Authored
via `perihelion.editor` + generator helpers (corridor, loop, Möbius pair, mirror
room, hypercube, Cayley graph, de Bruijn).

## 4. Testing & the playtest loop

- **Rust**: cargo test + proptest (§2.6) on every engine change.
- **Python unit/integration**: pytest, headless (`SDL_VIDEODRIVER=dummy`);
  screenshot goldens for named scenarios (dip_test heritage); perf scenarios with
  p50/p90/max budgets (perf_test heritage), CI-style script `./check.sh`.
- **Bot playtests**: policies (rusher, camper, explorer, pacifist) drive
  `GameSession` via InputFrames; metrics per run: survival time, damage taken/dealt,
  ammo pressure (fraction of time < 1 mag), near-misses, backtracks, portal
  crossings, fps. Every level must be *completable by the aggressive bot* and
  *lethal to the pacifist*.
- **LLM judge**: capture GIFs/screenshot strips of bot runs → judge for
  readability, juice, horror mood, "would a Teleglitch fan grin"; Gemini judges the
  audio bank. Findings feed tuning until convergence.

## 5. Performance budget

60 fps floor on this machine: `visible_set` < 2 ms at 40 instances; python draw
< 8 ms at 480×270; step < 2 ms at 100 live entities. Measured, not vibed —
`tools/playtest/perf.py` runs the worst-case scenes (hub center, mirror room,
infinite corridor) every session.
