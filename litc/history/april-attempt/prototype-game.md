---
This warm-start specfile records the April 2025 prototype game as it is. It covers `main.py`, `util.py`, `perf_test.py`, `dip_test.py`, and the six level data files. It is the product definition that the NETDS port starts from. It does not describe the port.

Standards, per `spec/standards/manifest.md`:

- `litc-clear-technical-prose.md` applies. This file is agent-authored warm-start text.
- `ux-principles-interactable-software.md` applies to the released game that will be built from this definition, not to the prototype the file describes. Per the manifest, audit findings against the prototype are recorded here as caveats, not as failures. The harness units (`perf_test.py`, `dip_test.py`) are outside that standard's scope.
- `ste-simplified-technical-english.md` does not apply. The manifest pins it as a source for the writing system only.

The level editor (`leveledit.py`, `test_leveledit.py`) belongs to `spec/prototype-editor.md`.
---

# The prototype game

The prototype is a top-down shooter in a non-Euclidean world. The world is a graph of convex polygon rooms. Rooms connect edge to edge through portals, each with a 3x3 affine transform in homogeneous coordinates. There is no global world space: every position is room-local, and only portal transforms map between rooms. The player flies a triangle, aims with the mouse, fires bullets with the left button, and fires a lightning dart with the right button. Enemies are octagons that chase the player through the room graph.

Everything lives in `main.py` (2329 lines). `util.py` holds debugging helpers that no code imports. `perf_test.py` and `dip_test.py` are the performance harness. Dependencies are pinned in `requirements.txt`: `pygame` 2.5.2, `numpy` 1.24.3, `networkx` 3.1. `readme.txt` gives the run instructions: install the requirements, then `python ./main.py`.

## Rooms, edges, and the world graph (`Room`, `Edge`, `GameWorld`)

### Goal

Represent the world as convex polygon rooms joined edge to edge by portals. Each portal stores the transform that maps the far room's local coordinates into the near room's local coordinates. Geometry, physics, and rendering therefore never need a global coordinate system. `GameWorld` owns the room collection and the player reference.

### Invariants

- Each room is a convex polygon. Its vertices are room-local, in the order that puts the interior on the positive side of each edge normal (the edge direction rotated `(x, y)` to `(-y, x)`). On screen, where y grows downward, this order reads clockwise.

- A single call to `GameWorld.connect_rooms` leaves the two `Edge` objects mutually inverse. Each side stores the transform that maps the other room's coordinates into its own, and the two matrices are inverses.

- Room numbers are unique. A class counter assigns them in creation order, starting at 1.

### Verification

- Run `python main.py` and press F3: every visible room shows a distinct number.

- Walk through a portal: the room seam is invisible in both directions, and walking back returns to the same room. (The dense cluster in the large test world violates reciprocity. See the test-worlds unit.)

- `util.py`'s `check_room_connections` was written to audit transform reciprocity, but the module cannot run. See its unit.

### Implementation

- `Edge` holds `target_room`, `target_edge_idx`, and `transform` (default identity). An edge with `target_room = None` is a solid wall. The transform maps the target room's local coordinates into the owning room's local coordinates.

- `Room.__init__(num_sides)` builds a regular polygon with every edge 100 units long. The distance from center to each vertex is `50 / sin(pi / n)`, and the first vertex sits at angle -90 degrees (up on screen). It stores `vertices`, `vertices_h` (the same points in homogeneous coordinates), one fresh `Edge` per side, and an empty `entities` list. It also picks a random color with each channel in 20..235.

- The constructor also builds a floor texture: a square alpha surface with side `int(2.2 * radius)`. The texture is a checkerboard of 20-pixel cells in the room color, offset by `int(radius) % 20` on both axes. `scaled_texture` is a scale of that texture to its own size, so it equals the original.

- `Room.get_edge_vertices(i)` returns the endpoints of edge `i`, wrapping from the last vertex to the first.

- `GameWorld` holds a NetworkX graph whose nodes are `Room` objects, and `player`. `create_room` builds a room and adds the node. `root_room` is the player's current room, or `None` before the player exists.

- `GameWorld.connect_rooms(room1, e1, room2, e2)` computes the alignment transform. It rotates by the angle between the two edge vectors plus 180 degrees (the edges face each other), then translates so the edge midpoints coincide. It writes the transform to `room1.edges[e1]`, the inverse to `room2.edges[e2]`, and adds a graph edge with the two edge indices as attributes. It never scales, so it assumes the two edges have equal length. It does not check that, and it does not check convexity or vertex order anywhere.

- `GameWorld.collect_nearby_entities(max_distance=15)` walks the room graph breadth-first from the player's room, up to `max_distance` portal hops. In each visited room it deletes entities whose `is_gone` flag is set and gathers the rest. It returns the gathered list.

### Caveats

- Connecting two edges of unequal length leaves a visible seam mismatch, because the transform aligns midpoints without scaling. All built-in worlds use edges of length 100. One level file holds unequal pairs (see the level-files unit).

- A later `connect_rooms` call that reuses an already-connected edge overwrites that side only. The partner edge keeps its old target, and the pair is no longer reciprocal. The dense cluster in `create_large_test_level` triggers this (see the test-worlds unit).

- The NetworkX graph is a simple graph. Two portals between the same room pair collapse to one graph edge, and the second call overwrites the edge attributes. The game only uses the graph as a node registry, so nothing observable depends on this.

- Module-level draw-cache remnants `_draw_cache`, `get_transform_key`, and `clear_draw_cache` are dead code. `Room.draw` builds its own local cache.

- `main.py` lines 69-76 repeat `import math, random, numpy as np, pygame` three times between class definitions, remnants of pasted code.

- A comment block at the end of `main.py` ("IDEAS SCRATCHPAD") sketches edges that connect to several targets at once. No code implements it.

## Portal-recursive rendering (`Room.draw`)

### Goal

Draw the world as seen from the player's room, by walking the portal graph and drawing each visible room through the chain of portal transforms. A room seen through a portal is clipped to the sight cone through that portal, so geometry behind walls stays hidden. The same room may appear several times at different screen positions (loops, mirrors, overlapping structures), and each appearance is drawn independently. This is the non-Euclidean effect: the world on screen is whatever the portal chain implies, with no global consistency requirement.

### Invariants

- Traversal always terminates. Recursion depth is capped at 12. A per-frame cache rejects a room already visited at the same rounded screen transform. Off-viewport rooms are culled, and rooms projected smaller than 10 pixels stop the walk.

- A wall edge (no target room) is always drawn as a 4-pixel white line.

- Pixels outside every visible region stay black.

### Verification

- Run the game near the self-connected octagon of the large test world. The view through the mirror edge shows repeated copies of the room, and the recursion ends after finitely many reflections.

- Press F5 (visibility debug): rooms seen through portals go black, and the debug geometry appears in their place. Red marks the blocked part of an entry edge, green the visible part, blue the clipping cone. (Measured: at a hub-center view, the painted area drops from about 69000 pixels to about 13000.)

- Frame time stays interactive at every position of the performance harness (`perf_test.py` measures exactly this call).

### Implementation

`Room.draw` runs in two phases over six 800x600 layers passed in by the caller.

Phase 1, traversal. A stack seeds with the root room, the camera transform, and the viewpoint (the player's room-local position). Depth-first, for each popped room:

- Skip when depth exceeds `max_recursion_depth` (default 12).

- Skip when the cache holds the key `(room id, x, y, cos)` with the transform translation rounded to 0.1 pixels and the cosine component to 0.01. Otherwise add the key.

- The room is *fully visible* when it is the root, or when its view cone spans more than `wide_angle_threshold_degs` (default 170). A fully visible room's clip region is its own polygon. Otherwise the clip region is a frustum quad. The quad takes the visible span of the entry edge and extrudes it along the two cone rays. The extrusion length is 10 times the distance from the viewpoint to the room's farthest vertex.

- Project the vertices to screen. Skip the room when its bounding rectangle misses the viewport. When its projected radius is under 10 pixels and it is not the root, keep the room but do not push its children.

- For each other edge with a target room, the walk composes the child's screen transform (`l2s @ edge.transform`). It maps the viewpoint into the child's coordinates with the edge's inverse transform. That inverse is computed once and cached on the `Edge`, and a singular transform skips the edge.

- For a fully visible room, the child's cone is the entry edge's endpoints as seen from the viewpoint. Otherwise `_compute_edge_frustum_intersection` intersects the current frustum with the candidate edge and returns the visible sub-span. It returns `None` when the edge or the overlap is shorter than 0.5 units. It also returns `None` for a viewpoint within 0.5 units of the edge, no overlap, or a midpoint outside the cone. The child's visible-span interval flips (`1 - end, 1 - start`) because the matching edge in the target room runs the opposite direction. Push the child with depth + 1.

Phase 2, painting. For each collected room, in traversal order:

- Compute the clip rectangle: the projected bounding box padded by 10 pixels, clipped to the viewport. Clear the work layer inside it.

- Blit the room's floor texture centered on the projected room center. The blit applies no rotation and no scale, so the checkerboard is always screen-axis-aligned and unit-scaled, whatever the portal chain's rotation.

- Draw wall edges as 4-pixel white lines. With F2 on, portal edges appear as 1-pixel gray lines. With F3 on, the room number is drawn at the center.

- With F5 on, the frustum polygon goes to the entity layer as a translucent blue shape instead of into the frustum mask. Red and green lines on the entity layer mark the blocked and visible spans of the entry edge. The frustum mask then stays empty, so a room seen through a portal paints nothing while the flag is on. Only fully visible rooms stay on screen (verified by pixel count, see the Verification).

- Build the visibility mask: mask layer 1 gets the room polygon in white, mask layer 2 gets the frustum polygon (or a full fill when fully visible), and the two combine with `BLEND_RGBA_MIN`. The work layer is masked the same way, then blitted to the room layer. The mask accumulates into the entities mask with `BLEND_RGBA_MAX`.

- Every entity of the room draws itself onto the entity layer with this appearance's transform. A room collected twice draws its entities twice, once per appearance.

With F7 on (`VISUALIZE_CONSTRUCTION`), the room layer is flipped to the display after each room with a 0.1-second sleep, animating the construction. That branch reads the module-level global `screen`, which exists only after `main()` starts.

The caller composites afterwards: room layer to screen, entity layer multiplied by the entities mask (`BLEND_RGBA_MULT`), then entity layer to screen.

### Caveats

- Entity masking is global, not per-room. The entities mask is the union of all visible regions. An entity sprite that extends past its own room's visible region is clipped only by that union. Where appearances of different rooms touch on screen, an entity near a wall can bleed into the neighbor's region.

- Where two appearances legitimately overlap on screen (the self-overlapping structures), the later-drawn room wins inside the overlap. Each room's masked pixels are blitted over the room layer in traversal order, so the last blit shows.

- The floor texture ignores the portal chain's rotation. Two appearances of one room reached through differently-rotated portals show identically oriented checkerboards. Walls and entities do rotate correctly.

- The traversal cache key ignores the view cone. A room reached through two portals at nearly the same transform draws once, with whichever cone arrived first. The second cone's region can go under-drawn. A comment in the code accepts this trade for cache hits.

- The F5 overlays draw on the entity layer, and the caller multiplies that layer by the entities mask before it reaches the screen. With F5 on, the mask holds only the fully visible rooms, so the parts of the overlays outside those rooms are erased in the composite.

- `Room._ray_segment_intersect` is dead code. The frustum intersection inlines its own ray tests.

- The comment lines above `Room` ("Assume global constants are defined") are pasted-code remnants.

## The camera (`Camera`)

### Goal

Keep the view centered on the player across portal crossings. When the player crosses a portal, the camera transform composes with the portal transform. The frame of reference glides seamlessly into the new room, and any rotation the portal implies comes with it.

### Invariants

- `Camera.transform` always maps the player's current room's local coordinates to screen coordinates.

- Room transitions never jump the view: composing with the portal transform preserves the on-screen image of the crossing point.

### Verification

- Walk through a rotated portal (the large world's spiral): the world turns smoothly on screen, and the WASD directions keep meaning screen up, down, left, right.

- Stand still: the camera glides toward the player and settles centered on 400, 300.

### Implementation

`Camera` is all class attributes and class methods, one camera per process.

- `transform` starts as a pure translation to the screen center (400, 300). `target_room` starts as `None` and is set by `main()` and the level loader.

- `get_position` recovers the world-space look-at point: the rotation part transposed, applied to screen center minus translation. The screen center is hardcoded (400, 300).

- `get_rotation` returns `-atan2(m10, m00)`.

- `handle_room_transition(old, new, portal_transform)` requires `target_room == old`, composes `transform @ portal_transform`, and sets `target_room = new`. On mismatch it raises `ValueError`. Only `Player._transfer_to_room` calls it.

- `update(player_pos, dt, lerp_speed=5.0)` moves the camera toward the player by the fraction `min(1, 5 * dt)` of the remaining distance each frame, composed as a screen-space translation.

### Caveats

- The hardcoded 400, 300 center matches the fixed 800x600 window. A different window size would break `get_position` silently.

- The class-attribute design means the performance harnesses mutate the same camera the game would use. Nothing runs both in one process.

## Entity physics (`Entity`)

### Goal

Give every game object the same motion machinery. Velocity integration splits into substeps, so fast objects cannot tunnel through walls. The machinery covers polygon collision against other entities, wall bounces, and portal crossings. A crossing carries position, velocity, and facing into the next room's coordinates.

### Invariants

- An entity always belongs to exactly one room's entity list, the room in `parent_room`.

- An entity's position stays inside its parent room's polygon. Wall edges reflect it, portal edges transfer it.

- Movement per substep never exceeds `max_step_distance` (100 for the base class), so a collision check happens at least that often along the path.

### Verification

- Fire bullets (speed 64000) at walls from across a room: they bounce or die, and never appear outside a room or embedded in a wall.

- Push an enemy into a wall corner: it stays inside the polygon.

- The first invariant was observed broken: the code guards `update` with a diagnostic print for exactly that state. See the caveats.

### Implementation

- `__init__` sets room-local `pos`, unit `direction` (default +x), zero `velocity`, `sprite_size` 20, and `collision_radius` 18 (0.9 of sprite size). It also sets `mass` 1.0, `max_step_distance` 100, `is_gone` False, `previous_room` None, and a random bright color. The sprite is an isosceles triangle: nose 30 ahead, tail corners 16 behind and 16 to each side. The entity appends itself to the parent room's entity list.

- `update(dt)` returns early, printing a diagnostic that starts with "WHAT THE FUCK???", when the entity is not in its parent room's list. Otherwise it clears the debug `collision_points`, splits the frame's movement into `ceil(distance / max_step_distance)` equal substeps, and runs `_update_step` for each. It prints a timing line when the whole update exceeds 1 ms.

- `_update_step(dt)` loops while time remains, at most 10 iterations. Each iteration computes a tentative position, then:

  1. Entity collisions first (`_check_entity_collisions`). A hit backs the entity off along its movement by 1.5 times the penetration depth. Then `self.handle_collision(other)` runs. When `self` was not removed and the other entity is still in the room, `other.handle_collision(self)` runs with the reversed normal. The reported collision time is the constant 0.5, so half the remaining time is refunded and the loop continues.

  2. Wall and portal crossings second (`_handle_edge_collisions`). For each edge, a crossing is detected when the signed distance goes negative while the projection lies within the edge span plus one unit. A portal edge transfers the entity, unless the target room equals `previous_room` (blocking an immediate bounce-back). A wall edge computes the exact crossing fraction and moves the entity to the crossing point. `handle_collision` then reflects velocity about the edge normal, and the unused fraction of the step is refunded. It prints timing lines when a check exceeds 0.5 ms or 1 ms.

  3. A collision-free step ends the loop and, when no transfer happened (checked by object identity of the returned position), clears `previous_room`.

- `_check_polygon_collision` is the separating axis theorem over both entities' sprite polygons, preceded by a radius pre-check. The returned normal is the normalized center-to-center vector, not the separating axis.

- `handle_collision(other, normal)` reflects velocity for edges. For entities it applies an impulse with restitution 0.8 split by the two masses, skipping when the entities already separate. It returns False. Subclasses return True to mean "I was removed, stop processing me".

- `_transfer_to_room(new_room, transform)` sets `previous_room` and removes the entity from the old list (a missing entry returns the position unchanged). It maps the position through the inverse portal transform. It nudges the result toward the new room's center by `2 * EPSILON` (about 1e-15 units, effectively zero). It rotates velocity and direction by the rotation part, then appends the entity to the new room. `Player` overrides it to notify the camera first, `Bullet` and `LightningDart` to also transform trail geometry.

- `point_at(target)` turns `direction` toward a room-local point. `draw` paints the rotated sprite polygon in the entity's color.

- `get_all_entity_subclasses()` walks `Entity`'s subclass tree recursively and returns all classes except those named `Bullet` and `LightningDart`. The level loader uses it as its entity registry.

### Caveats

- The entity-collision time is the constant 0.5, not the actual time of impact, so the time refunded after an entity hit is an approximation. Wall hits use the exact fraction.

- The 1.5x penetration back-off moves the entity back along its movement, at most to the point where the substep started (the ratio clamps at 0).

- After crossing a self-connected portal, `previous_room` equals the room itself. Every portal leading back to that room is then blocked until one collision-free substep completes, not just the crossed edge.

- The `update` guard print means entity-list membership was observed to fail in practice. The print is the only handling: the entity silently stops updating that frame. The message contains profanity.

- `collision_points` is recorded for debug visualization each step, but no code draws it. See the frame-loop unit's F6 defect.

- The physics timing prints go to the console unconditionally, not gated by any debug flag.

## The player (`Player`)

### Goal

The player avatar. WASD applies thrust in screen directions, and the triangle always faces the mouse cursor. The left button fires bullets on a 0.25-second cooldown. The right button fires the lightning dart on a 30-second cooldown. While the dart recharges, a progress ring circles the player.

### Invariants

- Movement is camera-relative: W always thrusts toward the top of the screen, whatever rotation the portal chain accumulated.

- Shot cooldowns are enforced from the same clock the frame loop passes in (`pygame` ticks in seconds).

### Verification

- Hold W after walking through the rotated spiral: the player still moves up the screen.

- Hold the left button: 4 bullets per second. Thirty seconds after launch, hold the right button: one dart fires. The ring then takes 30 seconds to sweep full circle before the next dart fires.

- The dart-ready state shows no indicator. That is the defect below, not a broken test.

### Implementation

- `move_force` 300, `shot_cooldown` 0.25 s, `lightning_cooldown` 30 s. `last_shot_time` and `last_lightning_time` start at 0, and the clock counts seconds since pygame start. Bullets are available almost at once, but the dart's first shot waits until the clock itself reaches 30 (the caveat below).

- `update` reads WASD into a screen-space direction, rotates it into world space by the inverse camera rotation, normalizes, and applies `velocity += direction * 300 * dt`. Friction multiplies velocity by `(1 - 2 * dt)`, which settles top speed near 150 units per second. Then the base physics update runs, and the sprite turns toward the mouse (`_update_orientation` maps the cursor through the inverse camera transform and calls `point_at`).

- `try_shoot(now)` and `try_lightning(now)` fire when the cooldown period is over, and record the time. `_shoot` spawns a `Bullet` at the triangle's nose (30 units ahead) with velocity `direction * 64000 + player velocity`. `_fire_lightning` spawns a `LightningDart` the same way at speed 800.

- `_transfer_to_room` calls `Camera.handle_room_transition` before the base transfer.

- `draw` paints the triangle, then the dart cooldown: a dark ring of radius 36 and a filled pie wedge that grows with progress. When the dart is ready it computes a pulse value for a "READY" label, but every drawing statement for the label is commented out.

### Caveats

- Defect: the comments promise a pulsing "READY" indicator when the lightning dart is charged, and the code computes the pulse. All rendering of it is commented out. The only ready signal is the ring's absence.

- For the first 30 seconds of every run, the dart cannot fire and the recharge ring circles the player. The state is exactly as if a dart fired at startup. No comment states whether that lockout is intended.

- The pie wedge's color carries an alpha component, but the wedge is drawn straight onto the opaque display surface. The alpha is therefore ignored, and the wedge is opaque.

- The player draws twice per frame: once as a masked room entity, and once more directly onto the screen by the frame loop. The body and the ring therefore always sit on top of everything.

- The player has no health, takes no damage, and cannot die. Enemy contact only shoves. There is no win or lose state anywhere in the prototype. (UX finding, recorded per the manifest.)

## Bullets (`Bullet`)

### Goal

The primary projectile: a small, very fast diamond that leaves a streak. It bounces off walls with heavy speed loss, damages the first enemy it hits, and disappears.

### Invariants

- A bullet substep never exceeds 20 units of travel (`max_step_distance` 20), so even at speed 64000 the bullet collides with everything on its path.

- A bullet that was drawn at least once is removed when it hits an enemy, hits any non-enemy entity, or drops below speed 100.

### Verification

- Fire across a long corridor: the streak spans several rooms through the portals, and the bullet arrives without skipping walls.

- Fire at a wall: the bullet ricochets visibly slower (half speed per bounce) and evaporates after a few bounces.

- Fire 15 bullets into one enemy: the enemy dies (1 damage each against 15 HP).

### Implementation

- Diamond sprite of size 5, collision radius 3, yellow, mass 0.0008, minimum speed 100, trail capped at 15 points.

- `update` re-aims `direction` along velocity, removes the bullet when speed is below 100 and `has_drawn` is set, then runs base physics.

- `_update_step` duplicates the base substep loop, appending the position to the trail at every collision and step end instead of recording debug points.

- `handle_collision` applies base impulse physics first: the impulse shoves an enemy back roughly 90 units per second per hit. The same impulse would fling the near-massless bullet, but the bullet is removed before that shows. Then an `Enemy` hit calls `take_damage()` for 1 damage and removes the bullet. A wall bounce halves velocity, and removes the bullet when speed fell below 100. Any other entity hit removes the bullet. Every removal requires `has_drawn`.

- Whenever speed is at least 100, `draw` renders the trail as a 5-pixel polyline through the stored points plus the current position. It then appends the current position, trims the trail to 15, and sets `has_drawn`. The diamond draws on top.

- `_transfer_to_room` maps all trail points into the new room's coordinates.

### Caveats

- Bullet lifetime is coupled to rendering: every removal path requires `has_drawn`, which only `draw` sets, and only while speed is at least 100. Comments state the intent (guarantee the streak is visible for at least one frame). A bullet that leaves the rendered area before its first draw, or slows below 100 before it, can never be removed and persists invisibly. In practice bullets spawn in the player's room, which is always rendered next frame.

- The trail cap applies in `draw`. A bullet colliding in unrendered rooms grows its trail without bound until drawn. Bounded in practice by the bullet's short life.

- `initial_pos` and `last_drawn_pos` are stored and updated but never read for behavior. Dead state.

## The lightning dart (`LightningDart`)

### Goal

The special weapon: a slow blue dart that detonates on its first contact. The blast damages and shoves everything in a radius. A branching lightning flash then plays for a moment before the dart vanishes.

### Invariants

- One detonation per dart. After it, the dart stops moving and expires 0.8 seconds later.

- Blast effects fall off linearly with distance and reach nothing beyond 100 units.

### Verification

- Fire the dart into a pack of enemies. Enemies near the impact die instantly, enemies farther out are damaged, and everything in range is flung outward.

- The flash renders branched, flickering bolts and a fading circle, then the dart disappears.

### Implementation

- Dart-shaped sprite of size 8, collision radius 5, electric blue, mass 0.01, speed 800 at launch, minimum speed 50. The trail caps at 20 points. `detonation_radius` 100, `explosion_force` 2000, `damage` 20, `lightning_time` 0.8 s.

- `update` before detonation: re-aim along velocity, append to the trail, remove when slower than 50 (after first update), set `has_drawn`, then base physics. `has_drawn` is set in `update`, not in `draw`, despite the name, so the dart arms itself on its first simulation frame. After detonation: no movement, and the dart expires 0.8 s after the blast.

- `handle_collision` applies base physics, then calls `detonate()` once armed. It always returns False, so the dart is never removed by the collision itself.

- `detonate` records the explosion position and sweeps every other entity within 100 units. An `Enemy` takes `20 * (1 - distance/100)` damage. Every swept entity's velocity gains `2000 * (1 - distance/100)` directly away from the blast.

- The lightning pattern generates once, in room-local coordinates: 5 to 10 zigzag branches of length 80..180 with random sub-branches. `draw` renders each branch with random flicker: a branch skips 20% of frames. Thick segments get a white core. A translucent circle fades and shrinks from radius 100 to 50 over the effect's life. Before detonation `draw` renders the trail as a 3-pixel bright-blue polyline plus the dart shape.

- `_transfer_to_room` maps the branches and the explosion position into the new room, then runs the base transfer. The base transfer knows nothing about trails, so the trail points keep the old room's coordinates (the defect below). The branch mapping runs only after detonation, and a detonated dart no longer moves, so that path is dead.

### Caveats

- Defect: the code comments call the damage "enough to one-shot enemies". Against 15 HP with linear falloff, 20 damage one-shots only within 25 units of the impact, a quarter of the blast radius. Beyond that, enemies survive with reduced HP.

- Defect: the comment in `_transfer_to_room` says the parent call handles the trail points, but the base class does not touch trails (`Bullet` maps its own, this class does not). After the dart crosses a portal, `draw` applies the new room's transform to trail points that still hold old-room coordinates. The trail then renders as a displaced streak until those points age out of the 20-point window.

- The detonated dart stays collidable in the room for 0.8 s. An entity that runs into it gets a normal collision impulse against mass 0.01. The dart's own velocity changes show nothing, because its position no longer updates.

- The blast has no line-of-sight or wall check, but rooms are the collision universe. Only entities in the dart's current room are affected. A wall inside the blast radius therefore protects a *neighboring* room by room membership, not geometry.

## Enemies (`Enemy`)

### Goal

The only opponent: a red octagon with 15 HP that chases the player. In the player's room it homes directly. Elsewhere it navigates the room graph toward the player, room by room. It darkens as it takes damage and dies at zero HP.

### Invariants

- An enemy always moves toward the player: directly when they share a room, else toward the edge that leads one room closer.

- HP only decreases. At `hp <= 0` the enemy sets `is_gone` and is deleted by the next nearby-entity sweep.

### Verification

- Load a level with enemies (edit `main()` to call the loader, see the frame-loop unit). Enemies converge on the player from other rooms, arriving through portals.

- Shoot one 15 times: it visibly darkens with each of the first 14 hits, then vanishes on the 15th.

- Enemies shove the player on contact but deal no damage (there is no damage to deal, see the player unit).

### Implementation

- Octagon sprite of radius 20, base color (255, 50, 50), `chase_force` 200, `max_hp` and `hp` 15, `max_speed` 150 declared.

- `take_damage(amount=1.0)` subtracts. At zero or below it sets `is_gone` and returns True. Otherwise it recolors: the base color scaled by `0.5 + 0.5 * hp/max_hp`, a linear darkening toward half brightness (the comment calls it saturation).

- `update` searches its own room's entity list for a `Player`. Found: accelerate toward the player at force 200 and face it. Not found: ask the module-global `nav_manager` for the next edge from this room toward the module-global `world.player`'s room. The enemy then accelerates toward that edge's midpoint. Then friction multiplies velocity by `(1 - 0.2 * dt)`, and base physics runs.

### Caveats

- Defect: `max_speed = 150` is declared with the comment "Maximum speed" and never read. Nothing caps enemy speed. With force 200 against friction 0.2, the steady-state chase speed is about 1000 units per second, more than six times the player's top speed. In practice rooms span one to a few hundred units, so walls and the player interrupt the acceleration long before that.

- `update` depends on the module globals `world` and `nav_manager`, which exist only after `main()` starts. Any other caller that updates an enemy outside the player's room would crash with `NameError`. The harnesses never update entities.

- Enemies have no attack beyond the physics shove, no line-of-sight behavior, and no idle state. They chase from the moment they load, across the whole reachable graph.

## Room-to-room navigation (`NavigationManager`)

### Goal

Answer "which edge leads one room closer to the destination" cheaply, for enemies chasing the player across the graph. One full search per destination, cached forever.

### Invariants

- Returned edges lie on a shortest path in portal hops (every edge costs 1).

- The cache is only ever added to. The world's topology never changes after creation, so entries never go stale.

### Verification

- Enemies several rooms away take hop-minimal routes to the player (observable with F3 room numbers and a loaded enemy level).

### Implementation

- `explore_from_room(start)` is Dijkstra's algorithm with unit edge costs (equivalent to breadth-first search), run backward from the destination over the whole reachable graph. For each settled room it records which of that room's edges leads to the previous room on the path back to `start`. Ties resolve by insertion order via a counter. The destination maps to `None`.

- `get_next_edge(from_room, to_room)` runs and caches `explore_from_room(to_room)` on first use, then answers from the cache. Unreachable rooms answer `None`.

- `clear_cache` empties the cache. No code calls it.

### Caveats

- One full-graph search runs per distinct room the player is first chased into. Memory grows with visited rooms, bounded by the room count.

- When several edges of a room lead to the same neighbor, the recorded edge is the first by index, not the geometrically nearest.

## The frame loop and debug controls (`main`, `PerformanceMonitor`)

### Goal

Boot pygame, build the world, and run the fixed frame cycle: input, physics for everything near the player, camera, render, composite, flip. Function keys toggle the debug views. A small monitor tracks frame time.

### Invariants

- The frame rate is capped at 240 FPS, and `dt` is clamped to 0.2 s so physics stays stable under breakpoints and stalls.

- Only entities within 6 portal hops of the player update. With F9 off, only the player updates.

- Automatic garbage collection stays disabled. Each frame runs one manual generation-0 collection after the flip.

### Verification

- `python main.py` opens an 800x600 window in a procedurally generated world with the player in hub A.

- F2/F3/F4/F5/F7/F9 visibly change rendering, stats, or updates as listed below. F6 changes nothing (the defect below).

- F4 pressed once prints average frame time each second. Pressed twice, an FPS counter also renders top-left. A third press turns both off.

### Implementation

- Startup: disable GC, init pygame, 800x600 display, create the six render layers. Then build the world with `create_large_test_level()`, set the camera's target room, and create the `PerformanceMonitor` and the module-global `nav_manager`.

- The world line reads `world = create_large_test_level()#load_level_from_file("cool_level_1.json")`. The level-file loader is reachable only by editing this line.

- If `debug_persistence.json` exists, it restores player position, direction, room (matched by room number), and camera transform. A `KeyError` prints a notice and deletes the file.

- Per frame: clamp `dt`, update the monitor, drain events (window close ends the loop, function keys toggle flags). Poll held mouse buttons: left calls `try_shoot`, right `try_lightning`. Update every entity from `collect_nearby_entities(6)`, or the player alone with F9 off. Update the camera, clear the screen and all six layers, and call `world.root_room.draw(...)` with the camera transform and the player position. Composite: room layer, then entity layer masked by the entities mask, then the player drawn again on top. Draw the monitor, flip, collect generation 0.

- Debug keys: F2 `DRAW_CONNECTED_EDGES`, F3 `DRAW_ROOM_NUMBERS`, F4 `SHOW_PERFORMANCE` cycling 0/1/2 with an immediate print, F5 `DEBUG_VISIBILITY`, F6 `DEBUG_COLLISIONS`, F7 `VISUALIZE_CONSTRUCTION`, F9 `UPDATE_ENTITES` (spelled that way in the code).

- `PerformanceMonitor` keeps the last 10 frame times. Level 1 prints the average every second. Level 2 also renders the FPS top-left.

### Caveats

- Defect: F6 toggles `DEBUG_COLLISIONS`, whose comment promises "Show collision points and remaining movement". No code reads the flag or draws the recorded `collision_points`. The key is a dead control.

- The six level files are unreachable from the shipped entry point. Every launch generates a fresh random world instead (see the test-worlds unit). The loader works when the world line is edited.

- Nothing in the repository writes `debug_persistence.json`. The restore path runs only when the file is supplied by hand. Restoring into the random world matches by room number, which names a different room each launch.

- Entities beyond 6 hops are fully frozen: no updates, and their `is_gone` cleanup also waits until the player comes within 6 hops.

- The game window has no caption, no pause, no menu, and no quit control beyond the window close button. Physics timing warnings print to the console during normal play. (UX findings, recorded per the manifest.)

## Level loading and the level file format (`load_level_from_file`)

### Goal

Build a `GameWorld` from a JSON level file written by the level editor. A file holds rooms with explicit vertices, portal connections by room id and edge index, and entity placements. The file is the editor's contract with the game.

### Invariants

- Exactly one player exists after loading. The first `Player` entry wins, and later ones are dropped with a console warning. When no entry exists, a default player spawns in the file's first room.

- Every connection the loader creates is reciprocal (it calls `connect_rooms` once per pair).

### Verification

- Point the world line at `simple_corridors_w_enemies.json`, `squares.json`, `cool_level_1.json`, or `exactly3enemies.json`: each loads and plays, with enemies chasing.

- `level_with_enemies.json` does not load. See the level-files unit.

### Implementation

The file layout, as the loader consumes it:

```json
{
  "version": "1.0",
  "meta": {"grid_size": 50, "snap_to_grid": true, "edge_camera_movement": true},
  "rooms": [
    {
      "id": 2,
      "vertices": [[x, y], ...],
      "connections": {"0": {"target_room": 3, "target_edge": 1}},
      "entities": [{"type": "Enemy", "pos": [x, y]}]
    }
  ]
}
```

- Parsing is strict JSON via `json.load`.

- Of `meta`, only `grid_size` (default 20) is read, for the floor checkerboard cell size. `version`, `snap_to_grid`, and `edge_camera_movement` are editor concerns the game ignores.

- First pass, rooms: the room center is the arithmetic mean of the vertex list, and vertices are stored center-relative. The room radius is the largest vertex distance. The floor texture is rebuilt at `grid_size` with the constructor's random color (the constructor's regular-polygon texture is discarded). `absolute_center` is stored on the room.

- Entity `pos` values are absolute and convert to room-local the same way. Entity types resolve through `get_all_entity_subclasses`, so `Player` and `Enemy` are the loadable types. Unknown types warn and skip.

- Second pass, connections: each room's `connections` maps its edge index (a string key) to a target room id and edge index. A missing target room warns and skips. The loader calls `connect_rooms` only when the source id is less than or equal to the target id. Symmetric double-listed pairs therefore build once, from the lower-id side.

- Format constraints the loader assumes and never checks: vertices convex, in the interior-positive order the game generates (screen-clockwise), and connected edges of equal length. All six shipped files satisfy the first two. One violates the third (next unit).

### Caveats

- A connection listed only on the higher-id room's side is silently dropped by the id-ordering rule, with no warning. `level_with_enemies.json` contains three such entries.

- Room ids from the file are used for wiring only and then forgotten. The F3 room numbers come from the global creation counter in file order, so they almost never match the file's ids. `debug_persistence.json` room numbers therefore mean loader order, not file id.

- Room colors are random at every load. The format stores no appearance data beyond geometry and `grid_size`.

- A self-connection (`target_room` equal to the room's own id) is built once per listed side. Double-listing runs `connect_rooms` twice, and the second call overwrites the first with the same transforms (verified numerically). The only self-connection in the shipped files is a double-listed one in the unparseable draft (room 44 of `level_with_enemies.json`). No loadable file exercises this path.

## The level files

### Goal

Six JSON levels record hand-built worlds for the game: two combat sandboxes, two corridor test maps, one showcase map, and one abandoned draft. They double as the level format's real-world examples.

### Invariants

- Every file that parses satisfies the loader's geometric assumptions: convex rooms, interior-positive vertex order, and (except the draft) equal-length connected edges.

### Verification

- The counts below were measured from the files directly (with the draft's syntax error patched for measurement only).

### Implementation

All files declare `version` "1.0" and identical `meta` (`grid_size` 50, `snap_to_grid` true, `edge_camera_movement` true).

- `level.json` — one rectangular room, 400 by 350 units. No connections. 6 enemies and 2 `Player` entries at identical coordinates (the loader keeps the first). The minimal combat sandbox.

- `exactly3enemies.json` — one pentagon, 1 player, exactly 3 enemies. A minimal fixture whose name states its contract.

- `simple_corridors_w_enemies.json` — 11 rooms (10 quadrilaterals, 1 hexagon), 13 connections, 6 enemies, 2 stacked `Player` entries. A small corridor layout.

- `squares.json` — 31 quadrilateral rooms, 50 connections, 6 enemies, 2 stacked `Player` entries. A dense square-grid topology test.

- `cool_level_1.json` — the showcase: 33 rooms of 4 to 12 sides, 40 connections, 272 enemies, and 8 stacked `Player` entries in room 37. This is the file named in `main()`'s commented-out loader call.

- `level_with_enemies.json` — an abandoned draft: 38 rooms of 3 to 11 sides, 24 enemies, 1 player, 104 connection entries. It does not parse.

### Caveats

- Defect: `level_with_enemies.json` is not valid JSON. One trailing comma after room 29's last entity makes `json.load` raise, so the game cannot load the file at all. The file is a draft the editor last saved in a broken state.

- Beyond the syntax, the draft holds more breakage. Three connection entries reference room ids absent from the file (the loader would warn and skip). Three exist only on the higher-id side (silently dropped). Three connected edge pairs have unequal lengths, up to 1820 versus 828 units, which would render seam mismatches. Room 44 connects to itself (double-listed, edges 1 and 5), the only self-connection in any shipped file.

- Four of the six files contain duplicated `Player` entries stacked at identical coordinates (8 copies in `cool_level_1.json`). The loader tolerates this with warnings. The duplication pattern points at an editor save quirk, recorded for the editor specfile.

- No shipped file is reachable from the game without editing the world line in `main()`.

## The procedural test worlds (`create_test_level`, `create_large_test_level`)

### Goal

Generate worlds in code that exercise every topological trick the renderer and physics must survive. The structures: corridors, branches, cycles, a spiral, a self-overlapping zigzag, a dense cluster, a maze, and a room connected to itself (a mirror).

### Invariants

- Every generated room is a regular polygon with edges of length 100, so all portal pairs align exactly.

### Verification

- `python main.py` boots into the large world. Walking it encounters all the structures: 5 hubs, long corridors, a cycle, a hexagon spiral, the mirror octagon, the cluster, and the maze.

- Looking into the mirror edge shows the reflection recursion. The cluster shows the reciprocity defect below.

### Implementation

- `create_test_level()` builds a small structured world off a starting pentagon. It contains a corridor of quadrilaterals, and a branching structure: a square that splits to a triangle path and a pentagon path. A self-overlapping zigzag reconnects to the corridor. A hexagon-heptagon-hexagon cycle closes on itself. A final corridor leads to an octagon connected to itself on edge 3.

- The player of the small world spawns at the pentagon's center. No caller reaches the function: the game builds the large world, and the only other reference sits in unrunnable `util.py`.

- `create_large_test_level()` builds the world the game boots into. Hubs A through E have 6, 8, 5, 7, and 4 sides. Seven hub-to-hub corridors run 4 to 6 rooms each, and extra dead-end corridors hang off every hub. Hub B gets a 5-room cycle, and hub D gets a 7-room hexagon spiral. Off hub C, a corridor leads to a self-connected octagon. Hub E gets a 5-room cluster, and a 9-room maze path runs from hub A to hub D.

- Corridor rooms are random triangles, quadrilaterals, and pentagons. The player spawns at hub A's center.

- The generator draws from the global `random` module without a seed, so every launch produces a different layout. The harnesses re-run the same construction under `random.seed(42)` for reproducible measurements.

### Caveats

- Defect: the cluster's cross-connection loop connects edge 1 of every cluster-room pair in sequence, and each call overwrites edge 1 of both rooms. The final state leaves edge 1 of three peripheral rooms all targeting the last peripheral. The last peripheral reciprocates only one of them. The hub E link into the cluster center is also overwritten on the center's side: the center's edge 0 goes to a peripheral instead. The result is one-way portals: crossing one and walking back leads somewhere else. The surrounding `try/except Exception: pass` catches nothing, because `connect_rooms` does not raise on any of these calls.

- The corridor builders compute `safe_edge = 1 % prev.num_sides`, which is always 1.

- `create_test_level` is dead code in practice, kept as the small-world variant of the same test structures.

## World-perturbation and connection-audit helpers (`util.py`)

### Goal

Three debugging helpers for world geometry. `perturb_world` jostles all room vertices while it keeps rooms convex and connected edges equal in length. `debug_room` and `check_room_connections` print a connection audit, with a warning when a portal pair's transforms are not mutual inverses. `test_debug` runs the audit over the small test world.

### Invariants

- None hold, because the module cannot run. See the defect.

### Verification

- `python -c "import util"` raises `NameError: name 'GameWorld' is not defined`. That failure is this unit's one verifiable behavior.

### Implementation

- The module has no import statements. Its functions reference `np`, `random`, `GameWorld`, and `create_test_level` from `main.py`'s namespace, but nothing imports the module into any namespace, and no file imports `util`.

- `perturb_world(world, perturbation_magnitude=0.2)` records all connections, one per pair, ordered by object id (which drops self-connections). It disconnects everything, then perturbs each room's vertices by up to 20% of the room's mean radius. Ten attempts guard convexity, and after ten failures the room keeps its old shape. It then averages the lengths of formerly connected edge pairs. It moves the edge endpoints to match the averaged length while it preserves midpoints, averaging vertices that several edges adjust. Finally it reconnects everything with fresh transforms.

- `debug_room(room)` prints vertices, per-edge geometry, connection targets, and the transform. It prints a forward-transform check of the target edge's endpoints, and a warning when the two sides' transforms are not inverses of each other.

- `check_room_connections(world)` walks the graph depth-first to depth 10 from `world._root_room` and runs `debug_room` on each room.

- `test_debug()` builds `create_test_level()` and audits it.

### Caveats

- Defect: the module is unrunnable dead code. Importing it raises `NameError` at function-definition time, because the `GameWorld` annotation evaluates with no imports present. Even with imports added, `check_room_connections` reads `world._root_room`, an attribute no class defines (`GameWorld` has the `root_room` property).

- Latent defects, relevant if the module were revived. `perturb_world` never rebuilds `vertices_h` after moving vertices, so rendering would use the pre-perturbation geometry. It never clears the `inv_transform` values cached on edges, so traversal would use stale inverses. It also replaces the vertices array with a list of tuples, unlike everything else in the codebase.

## The rendering benchmark (`perf_test.py`)

### Goal

Measure rendering cost at 10 strategic camera positions in a reproducible copy of the large test world. Keep a named-experiment history, so optimization work has before/after receipts. The module docstring documents the workflow: baseline first, change, re-run, keep improvements.

### Invariants

- The world is identical on every run (`random.seed(42)` before the shared construction), so numbers are comparable across experiments.

- The timed region is exactly the production renderer: the real `Room.draw`, plus composite and flip.

- The history baseline is the best average among experiments marked as improvements.

### Verification

- `python perf_test.py` prints the report without saving. `python perf_test.py --name "x"` saves the experiment into `perf_history.json` and prints the history comparison with green improvement and red regression percentages.

### Implementation

- `create_large_test_level_with_refs()` duplicates `main.py`'s large-world construction under seed 42 and returns named references to the interesting rooms.

- The 10 positions start with hub A center, hub A near a corridor edge (0.7 toward vertex 0), and hub B center. Next come a corridor midpoint, the mirror room center, and the mirror room near its self-edge (0.6 toward vertex 3). The rest are a cycle room, the spiral's middle, the cluster center, and the maze's middle.

- `render_frame` points the camera at the position with a translation-only transform, clears all layers, and times `Room.draw` plus composite plus `pygame.display.flip`, returning milliseconds. No entity updates run. The only entity anywhere is the player standing in hub A.

- `run_benchmark` renders 1 warm-up plus 10 timed frames per position and aggregates overall average, 75th and 90th percentiles, and maximum.

- `save_experiment` writes the experiment into `perf_history.json` by name, replacing an entry with the same name. It marks the experiment an improvement when its average beats the stored baseline. It then recomputes the baseline as the minimum average among improvement-marked experiments. `perf_history.json` is this harness's measurement artifact, kept in the repository as the experiment log.

- `print_report` prints the current run, a per-position table, and the history with per-experiment percentage deltas against the best baseline.

### Caveats

- The level construction is a hand-copy of `main.py`'s generator. A change to one that misses the other silently benchmarks a different world than the game runs.

- The first saved experiment is always marked an improvement. An experiment that exactly ties the baseline is marked a regression (the comparison is strict).

- The timed region includes `pygame.display.flip`, so the display driver's behavior can dominate the numbers. Neither harness requests display synchronization: `dip_test.py` passes `vsync=0` explicitly, and this one relies on the pygame default, which requests the same. A driver can synchronize anyway.

## The frame-time variance harness (`dip_test.py`)

### Goal

Detect periodic stutter. The harness renders one fixed view (hub A center) continuously for a duration, default 60 seconds. It then reports the frame-time distribution, dip counts, a histogram, and a per-phase cost breakdown that localizes where slow frames spend their time. The reported per-frame totals are truncated by a timer defect (see the caveats).

### Invariants

- The measured world and view never change during the run, so all variance comes from the code and the platform, not the scene.

- Garbage collection is disabled and display synchronization is off during measurement.

### Verification

- `python dip_test.py --duration 10` runs 10 seconds and prints the report. The report holds min/max/average, percentiles, variance, and dip counts against 2x and 3x the median. It also holds the histogram, the phase breakdown, room-count analysis, and traversal detail.

### Implementation

- `create_test_level_hubA()` is a third copy of the seeded large-world construction, returning the world and hub A.

- `render_frame` is an instrumented re-implementation of `Room.draw`'s two phases, inlined into the harness. The traversal is the same: depth 12 cap, same cache key, same frustum math via the real `Room` static helpers. The painting sequence is also the same. It reuses preallocated transform arrays to avoid allocation churn.

- Around the phases sit timers for setup, clear, traversal, painting, composite, and flip. Counters track traversal iterations, matrix-multiply time, frustum time, and lazily computed edge inverses. The per-frame total that `render_frame` returns is corrupted by the timer defect below.

- `run_dip_test` opens the display with synchronization off, disables GC, warms up 10 frames, then renders until the duration elapses, printing progress every 5 seconds. Window close or Ctrl+C stops early. GC re-enables afterward.

- `print_report` prints summary statistics, percentiles (10/25/50/75/90), variance, and the coefficient of variation. It prints dip counts (frames above 2x median, severe above 3x, worst five listed) and a fixed-bucket histogram. It also prints per-phase averages and maxima with color-coded severity, room counts for slow versus fast frames, and traversal sub-phase statistics.

### Caveats

- Defect: `render_frame` reuses the variable that holds the frame's start time as the matrix-multiply timer inside the traversal loop. The returned per-frame total therefore spans only the last traversal iteration through the end of flip. The "setup" row of the phase breakdown is negative. Measured: reported totals near 4.9 ms while the draw phase alone averaged 5.5 ms, and setup near -2 ms. The summary statistics, percentiles, dip counts, and histogram all describe these truncated totals, missing the variance in setup, clear, and most of the traversal. The other phase rows use their own timers and are correct.

- The harness measures its own copy of the renderer, not `Room.draw` itself. The copy omits entity drawing, all debug overlays, and room-number rendering. A change to `Room.draw` does not reach these measurements until someone re-syncs the copy. `perf_test.py`, which calls the real `Room.draw`, is the ground truth for production cost.

- The percentile and colorize helpers are duplicated across both harness scripts, and `main.py` has a third frame-time tracker. None of the three share code.
