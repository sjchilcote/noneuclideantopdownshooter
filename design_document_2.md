# Design Document: Non-Euclidean Top-Down Shooter
*A Teleglitch-like set in a graph-based impossible space*

---

## 1. Vision

The game is a 2D top-down survival shooter that borrows its moment-to-moment mechanics directly from Teleglitch — tense, scarce, line-of-sight-driven combat in oppressive corridors — with one foundational twist: the world is not Euclidean. The game world is a graph of convex polygonal rooms whose connections are completely arbitrary. A corridor may loop back onto the far side of itself. Four left turns may deposit you somewhere new. A room may connect to another side of itself, or to the *same* side, producing a mirror.

Crucially, none of this is announced. From the player's perspective, the world is presented as one continuous, seamless 2D space, drawn and traversed exactly as a normal space would be. The non-Euclidean nature of the world is something the player *discovers* — first as a vague unease ("this building is too big on the inside"), later as an undeniable, reality-breaking fact, and finally as the tactical and thematic core of the game. The illusion of continuity is therefore sacred: rendering, movement, camera behavior, and physics must all conspire so that crossing a room boundary is completely imperceptible. Any visible seam, bump, pop, or flicker at a transition directly damages the game's central conceit.

The intended emotional arc mirrors the spatial one: mundane dread → creeping wrongness → cosmic horror, with the geometry itself as the antagonist's fingerprint.

## 2. The Foundational World Model

### 2.1 Rooms

The atomic unit of space is the **room**: always a convex polygon, defined by a counter-clockwise-wound list of vertices in its own private, local coordinate system (rooms are constructed centered on their own origin). Convexity is a hard, load-bearing invariant, not a stylistic preference:

Convexity guarantees that a room can never self-occlude — from any point inside a room, every point of that room is visible. This single fact collapses the entire visibility problem into portal logic: occlusion can only ever happen *between* rooms, at their connecting edges. It likewise simplifies collision (the interior is exactly the intersection of the half-planes of the edges), containment tests, and editor validation. Anywhere a geometric algorithm can be simplified by assuming convexity, it should be, and the editor must make it impossible to author a concave room (concave shapes get split into convex pieces).

Every entity in the game world belongs to exactly one room at any moment, and its position, velocity, and facing direction are expressed in that room's local coordinates and *only* make sense there.

### 2.2 Edges and Connections

Each edge of a room is either a solid wall or a **connection** (portal) to an edge of some room — possibly a different room, possibly another edge of the same room, possibly even the *same* edge (the mirror case). The rooms form a graph: rooms are vertices, connections are edges. There is no requirement whatsoever that this graph be embeddable in the plane; connections are arbitrary and the level designer is free to build spaces that could never exist.

A connection stores, alongside its target room and target edge index, a 3×3 homogeneous affine **transform matrix**. By convention, the transform on an edge maps points *from the target room's coordinate space into the source room's coordinate space*. The reverse direction is obtained by inversion. When two rooms are connected, the transform is computed so that the two edges coincide exactly, with the target room rotated and translated so its edge lies flush against the source's edge (the alignment includes a 180° flip, since the rooms face each other across the shared edge). Both edges get their respective transforms — each the inverse of the other.

An important, easy-to-forget consequence of consistent CCW winding: when two edges are glued together, the *first* vertex of the parent's edge coincides with the *last* vertex of the child's coincident edge, and vice versa. Every algorithm that carries parametric positions along an edge across a connection (visibility segments, spawn points, anything) must flip the parameter (`t → 1 − t`) and must keep the orientation bookkeeping straight. Getting this wrong has historically been the single richest source of bugs in the project; the design assumption is that any edge-crossing code is guilty of an orientation error until proven innocent.

### 2.3 There Is No World Space

This is the cardinal rule of the entire codebase and deserves its own section despite being one sentence long:

**A position vector has absolutely no meaning outside the room it belongs to.** There is no global coordinate system. The only way to relate coordinates in one room to coordinates in another is through the transform attached to the connection between them (or a composition of transforms along a path of connections — and note that different paths between the same two rooms may yield *different* compositions; that is the whole point of the game). Rooms are usually rotated relative to one another; their axes generally do not align, and no code may assume they do. "Screen space" exists only as the composition of the camera transform with the chain of connection transforms taken while rendering.

Every system in the game — rendering, physics, AI, aiming, audio someday — is designed around propagating information along the room graph, transforming it at every edge crossing, rather than ever computing in a shared frame.

### 2.4 Transforms Beyond Rigid Motion (Future Direction)

The 3×3 homogeneous matrices are deliberately more general than the rotation+translation currently required. The design intends to eventually exploit this generality: uniform and non-uniform **scaling** connections (rooms that are bigger on the inside; corridors that shrink you), **mirroring** connections (chirality-flipping passages), **shear**, and even perspective-like effects via the projective row. Every system must therefore be written against arbitrary invertible 3×3 transforms, not against an assumed rigid motion — e.g., caches must key on the full matrix rather than a decomposed (x, y, θ), and velocity/direction transforms must use the actual linear part rather than a reconstructed rotation. The only hard requirement on connection transforms is that they remain invertible.

## 3. Player Experience & Core Gameplay

### 3.1 Teleglitch DNA

The combat and survival loop is lifted from Teleglitch on purpose: top-down real-time shooting; the player character always aims at the mouse cursor; movement is WASD; visibility is strictly line-of-sight so that danger lives in the darkness beyond every doorway; ammunition and resources are scarce and every shot matters; enemies are fast, physical, and lethal in numbers; death is punishing. The claustrophobic tension of only seeing what the character could actually see is not just aesthetic — in this game it is doubly essential, because the visibility system is also what sells the non-Euclidean space (you see *through* portals along genuine sight lines, so impossible spaces look perfectly natural until you map them).

### 3.2 Controls

Controls are defined relative to the **camera/screen**, never relative to any room's axes. W is always "up on the screen." Since rooms are arbitrarily rotated relative to one another, room-space controls would visibly wrench sideways at every transition and destroy the seamlessness; instead, screen-space input is converted into the current room's space via the inverse of the camera's rotation each frame. Aiming works the same way: the mouse cursor's screen position is mapped through the inverse camera transform into the player's current room's coordinates, and the player character points at that local point. Movement is force/acceleration-based with friction, giving weighty, slightly slippery Teleglitch-style handling rather than instant velocity changes.

### 3.3 The Discovery Arc

Non-Euclideanness is a revelation, not a bullet point on the box. Level design (§8) and narrative (§9) are structured so that early play is deliberately mundane, the first anomalies are deniable, and the escalation to overt impossibility is paced across the whole game.

## 4. Rendering

### 4.1 Recursive Portal Rendering

Rendering is a recursive traversal of the room graph rooted at the camera's room (the camera is pinned to the player under normal gameplay). The room containing the camera is drawn in full — convexity guarantees the player can see all of it, walls permitting. For each connected edge of that room, a **view frustum** is projected from the viewpoint through the edge into the neighboring room: two rays from the viewpoint through the edge's endpoints bound the visible wedge. The neighbor is drawn clipped to that frustum, composed into place by multiplying the running local-to-screen matrix with the edge's transform. Wherever the frustum crosses another connected edge of the neighbor, the visible sub-segment of that edge spawns a narrower frustum into *its* neighbor, and so on, until recursion terminates.

Termination conditions: the frustum leaves the screen bounds; no connected edge is visibly intersected; the visible segment shrinks below numerical significance; a maximum recursion depth is hit (kept high, e.g. 10–12 — visibility, not depth, should be the practical limiter); or the exact (room, cumulative transform, entry edge, visible segment, view-cone) combination has already been drawn this frame. The cache key deliberately includes the *path-dependent* view information, not just room and transform: the same room can legitimately be visible in the same on-screen location through multiple different portal chains simultaneously, and each such view cone must be rendered. Cycles in the graph (including self-connections) are handled naturally by this cache — an infinite corridor renders as many copies of itself as fit on screen and no more.

All visibility math is performed in each room's own local coordinates. Sight-line rays and visible-segment parameters are transformed at every edge crossing (positions through the full inverse transform; directions through its linear part only), with the winding-order flip of §2.2 applied to segment parameters and ray correspondence. Rays crossing into a child room must additionally be reoriented to point *into* the child (a sight line "from player to edge" in the parent becomes a frustum boundary pointing inward in the child) — the semantics of a ray are not preserved by naive vector transformation across a portal.

### 4.2 Visibility Masking

Each room instance is rendered to a working layer and clipped by the intersection of two regions: the room's own polygon, and the view frustum it is seen through. The intended, correct construction of that intersection is **analytic**: rather than rasterizing an enormous frustum polygon and intersecting mask surfaces graphically, the visible region is constructed as an exact polygon by walking the room's perimeter — collecting vertices that lie inside the frustum, the intersection points of the (mathematically infinite) frustum rays with the room's edges, and the visible entry-segment endpoints, ordered by edge index and then by parameter along each edge. Because the room is convex, this walk always yields a single convex visible polygon. This approach has no maximum ray length, no giant-polygon rasterization cost, and behaves correctly at arbitrarily wide frustum angles.

Entities are drawn on a separate entity layer, clipped by the union of all visible-region masks, so entities are only ever visible where the floor beneath them is. The design also calls for depth-based dimming — rooms further down the portal chain render slightly darker — as a subtle readability and atmosphere cue.

### 4.3 The Near-Edge ("Promotion") Case

As the viewpoint approaches a connected edge, the frustum angle through it approaches 180° and the bounding rays approach parallelism with the edge. The original workaround — fully "promoting" the neighbor and drawing it whole once the angle exceeded ~150° — was a stopgap that is *not* the design intent: it wrongly reveals parts of neighbors that lie outside the true sight cone in complex levels. The intent is that the analytic mask construction of §4.2 handle extreme angles gracefully, so promotion is needed only as a degenerate-case escape hatch at essentially-on-the-line angles (≈179.5°+), where "you can genuinely see the whole room" is actually true. The player should be able to skate along and across an edge with the rendered scene evolving perfectly smoothly.

### 4.4 Performance Principles

Rendering must comfortably sustain 60 FPS at the most graph-central points of a level, where dozens of room instances may be visible. Guiding rules: no per-frame surface allocation (pre-allocated, reused full-screen layers and a surface pool); cull edge recursions whose visible segment falls entirely off-screen *before* doing transform math; keep the per-frame draw cache cheap to key and query; prefer analytic geometry over rasterized mask arithmetic. Micro-optimization is explicitly deprioritized in favor of eliminating structural waste.

## 5. Camera

The camera is itself a 3×3 transform from the current room's space to screen space (its translation component incorporates the screen-center offset — a fact that downstream code such as mouse unprojection must respect rather than re-apply). It smoothly follows the player with lerp-style tracking, focused on the player — not on a blend of player and room center.

When the player crosses a connection, the camera's transform is re-based by composing it with the connection transform, with a compensating correction applied so that the composition produces **zero visible change on screen**. Room transitions are camera non-events by design; the camera's orientation drifts through the world as the accumulated product of every transform the player has passed through, which is exactly what makes a loop of "identical" rooms feel continuous even when the loop is geometrically impossible. Camera rotation (extracted from the transform) is the reference frame for the control scheme (§3.2).

## 6. Movement, Collision & Physics

### 6.1 Philosophy

The game deliberately does **not** use a full physics engine — neither a hand-rolled one nor Box2D, which is a poor fit for a world with no global space. The target is the minimal simulation that *looks* right for a Teleglitch-like: convincing shoves, bounces, and pile-ups, without rotational dynamics, constraint solvers, or continuous-time sophistication beyond what stability demands.

### 6.2 Wall Collision & Room Transfer

Movement integrates velocity over the frame, sub-stepped for stability. Each step's tentative position is tested against the current room's edges (signed distance against the CCW edge normals — again exploiting convexity). Crossing a solid wall produces an elastic reflection of velocity about the edge normal and a positional correction back inside. Crossing a connected edge triggers a room transfer:

The entity's position is mapped through the *inverse* of the edge transform (the stored transform maps target→source; transfer needs source→target); velocity and facing direction are mapped through the linear part only. The entity is nudged a small epsilon toward the new room's interior so its side-of-edge status is unambiguous, and its room membership is updated. Facing is stored as a normalized direction *vector*, not an angle, precisely so transfers are a single matrix-vector multiply with no trigonometry or angle-wrapping.

Robustness rules learned the hard way and now part of the design: transfers only occur when the velocity actually points out through the edge (dot-product test against the edge normal with a small epsilon), killing boundary ping-ponging; edge collision spans are extended slightly past one endpoint so the vertex where two edges meet has no gap to slip through (safe only because, by convexity, the extended region lies outside the room); and after any collision resolution within a step, the remainder of the step must be re-run through the *full* pipeline — wall checks, transfer checks, everything — because a corrected position can itself cross an edge. Time refunds after a collision use the actual computed collision time, not a fixed heuristic fraction.

### 6.3 Entity–Entity Collision

Two-phase detection: a cheap circle pre-check on collision radii (hitboxes intentionally a bit smaller than sprites, especially the player's), followed by an exact convex-polygon test (separating axis theorem) for pairs that pass. Response is impulse-based conservation of momentum with per-entity mass and restitution — elastic, point-of-impact-agnostic, no torque. Entity collisions resolve before edge collisions within a step, and their positional outcomes are fed back through the edge/transfer pipeline like any other movement. Entities interacting *across* an open connection is a known hard problem this model defers; the mitigation is that rooms are large relative to entities and the epsilon-nudge keeps entities decisively inside one room.

## 7. Entities & AI

### 7.1 Entity Model

All game objects (player, enemies, projectiles, pickups) derive from a common Entity: parent room reference, room-local position, velocity, normalized direction vector, polygonal sprite, mass/restitution/collision radius. The parent room also lists its entities — the room list is the spatial index; the entity's back-reference is the authority on membership, and transfers keep the two in sync atomically.

Per-frame updates run over entities gathered by a breadth-first walk of the room graph out to a fixed hop count from the player's room. Graph distance, not metric distance (which doesn't exist), is the activity horizon: the far reaches of the world are frozen until the player nears them, which is both a performance measure and thematically fitting. The longer-term architectural ambition is a more data-oriented system — flat entity storage with simple rules applied in passes — but the current class-based model is kept deliberately simple until that's earned.

### 7.2 Pathfinding

Enemies chase the player directly (steering force toward the player's local position) when they share the player's room — convexity guarantees an unobstructed straight line. Across rooms, a NavigationManager runs shortest-path searches over the room graph and caches results, refreshed periodically rather than per-frame-per-entity; enemies query only "which edge do I leave my current room through?" and steer for that edge's span, letting the ordinary transfer mechanics carry them across. All path state is expressed as room/edge sequences — never positions — because positions don't travel.

## 8. Level Design

### 8.1 The Escalation Curve

Levels introduce spatial impossibility on a deliberate gradient:

**Early game — deniable wrongness.** Spaces that are subtly too big on the inside; loops that return you to a hallway just slightly unlike the one you left; a figure-eight that a careful mapper would find impossible but a fighting player never notices. The player should be able to finish these levels without consciously registering that anything is wrong — and feel the hair on their neck anyway.

**Mid game — confirmable paradox.** Parallel corridors whose crossing-passage counts don't match from either side; two wings that provably occupy the same space; a Möbius sequence that returns the player rotated 180°; side paths that emerge near the start but at an angle that cannot be reconciled. The player is now testing the space deliberately, and the space is failing the tests.

**Late game — overt impossibility.** Mirror rooms (edges connected to themselves), visibly self-overlapping chambers, infinite corridors rendered as endless repetition, recursion tricks. Geometry is now openly hostile and tactically central: escaping a chase by understanding a loop, shooting an enemy "through" a mirror, using a self-connection to attack from an impossible angle.

**Endgame — pure graph.** All pretense of architecture is dropped; levels are structures straight from graph theory with no buildable analogue: hypercube graphs, Cayley graphs of groups (identical rooms where operation order determines destination), De Bruijn graphs with decipherable room-codes, Königsberg-style traversal traps, expander graphs (the goal visible but necessarily far), strongly regular graphs, and finally Erdős–Rényi random connectivity — controlled chaos, tuned by average degree to stay playable.

Additional spice available at any tier: one-way connections (directed edges), and dynamic graph modification — events or enemies that add or remove connections mid-level.

### 8.2 The Level Editor

Levels are authored in a dedicated editor and serialized to JSON: per-room vertex lists, per-edge connection records (target room, target edge), and per-room entity placements (type + local position); connection transforms are recomputed from edge geometry at load. The editor provides polygon creation (with automatic connection when a new room is drawn sharing an edge of an existing one), vertex editing, an explicit connection tool, and room movement; it enforces convexity (splitting concave polygons), validates connections when geometry changes, and supports self-connections and edge-length reconciliation between connected edges of different lengths. Editor placement of a player entity overrides the default spawn. The editor is a first-class tool — the escalation curve of §8.1 lives or dies on authoring throughput.

## 9. Narrative

The story exists to do four jobs: explain who the player character is and why he shoots, give the player a mystery worth pushing through rough patches for, make them want the protagonist to succeed — and deliver the non-Euclidean revelation as a *discovery*, never a premise. The tone is cosmic horror grown from techno-mundane roots.

The working direction: the protagonist is a Commando aboard/around an isolated station (ultimately bound for the sun), entangled with a connection to somewhere *else* — a far side from which invaders probe. His companion and foil is **Ratio**, a rationalist counterpart whose trust the player builds or burns through choices; their philosophical conflict (faith vs. reason vs. the void's own alien logic) is expressed mechanically through a mind-map progression system in which nodes are simultaneously understanding and capability, along faith / rationalist / human / void paths.

The endings are fixed points of the design: **Faith** (conviction carries him through), **Guard** (he and Ratio spend eternity — millennia — defending the station and its secret from both sides of the connection, until the invaders lose interest, the station decays, and they let it fall into the sun without attempting escape), **Together** (horror accepted but defied through the friendship), and **Apostasy + Betrayal** (he loses faith, kills Ratio, exterminates all life beyond the connection, then returns to snuff out the Sol system, finishing with himself). Key beats along the way: first contact and the initial philosophical clash, a mid-game crisis over sharing tactical data as the invaders probe, and the discovery of the Container, whose honest analysis depends on the trust built with Ratio.

## 10. Development Tooling & Persistence

Debugging non-Euclidean geometry by eyeball is hopeless, so instrumentation is a standing requirement, bound to function keys and cheap to toggle live: performance readout (rolling frame-time average and on-screen FPS), visibility-overlay mode (frustums drawn as translucent overlays instead of clip masks, with the visible/occluded parts of entry edges marked in green/red), room numbers and Y-axis orientation arrows, connected-edge highlighting, collision point visualization, and step-by-step slow-motion rendering of the portal-recursion order. A debug save (F6) captures exact player position, orientation, room, and camera transform to JSON and restores it on launch, so any geometric bug can be reproduced from the precise spot where it occurs.

## 11. Design Invariants (Summary)

If any change to the game violates one of these, the change is wrong:

1. Rooms are convex polygons, always, with consistent CCW winding.
2. There is no world space. Coordinates are room-local; crossing an edge means transforming through that edge's matrix (or its inverse, in the appropriate direction), and directions transform through the linear part only.
3. Edge transforms map target-room space → source-room space; paired edges hold mutually inverse transforms; transforms may be any invertible affine (eventually projective) map, not just rigid motions.
4. Glued edges have opposed orientation: parametric quantities flip (t → 1 − t) at every crossing.
5. Room transitions are imperceptible: no camera jump, no velocity change, no rendering discontinuity.
6. Visibility is strict line of sight, computed analytically per room in local space, propagated through portals; the same room may be visible multiple ways at once and each must render.
7. The player discovers the non-Euclidean nature; the game never announces it.
