# Non-Euclidean Top-Down Shooter - Design Document

This document describes the current implementation of the non-euclidean top-down shooter prototype. It captures exactly what the code does, including apparent bugs and oddities.

---

## Core Concept

A 2D top-down shooter where the player navigates interconnected rooms (convex polygons). The twist: rooms can connect in geometrically impossible ways. Looking through a doorway, you see the connected room rendered at a different position/rotation than the room actually "is" — the connection defines an arbitrary affine transformation. This creates non-euclidean spaces where corridors can loop back on themselves, rooms can appear multiple times at different locations, and spatial relationships don't follow normal rules.

---

## Coordinate Systems and Rendering

### Room-Local Coordinates

Each room exists in its own local coordinate system:
- Origin (0,0) is at the center of the polygon
- Vertices are stored as offsets from this center
- All entity positions within a room are relative to the room's center
- The room itself has no "world position" — only transformation relationships to connected rooms

### Transform Chains

When rendering or doing physics across room boundaries:
- Each edge connection stores a 3x3 homogeneous transformation matrix
- This transform maps points FROM the connected room's coordinate system INTO the current room's coordinate system
- Traversing an edge to another room requires applying the inverse of that transform
- Transform chains can be composed by matrix multiplication

### Camera System

The camera exists in the coordinate system of the room the player is currently in:
- `Camera.transform` is a 3x3 matrix that maps room-local coordinates to screen coordinates
- Screen center is hardcoded to (400, 300) based on 800x600 window
- When the player transitions between rooms, the camera transform is composed with the edge's transform to maintain visual continuity
- Camera smoothly interpolates position toward player using `lerp_speed * dt` factor (default lerp_speed = 5.0)
- Camera rotation is preserved across transitions; `get_rotation()` extracts angle from transform matrix via `arctan2(transform[1,0], transform[0,0])`

---

## Room Structure

### Room Class

Each room is a convex polygon with:
- `num_sides`: Number of edges/vertices
- `vertices`: numpy array of (x, y) vertex positions, counter-clockwise from top
- `vertices_h`: Same vertices with homogeneous coordinate (x, y, 1) for matrix multiplication
- `edges`: List of `Edge` objects, one per side
- `entities`: List of entities currently in this room
- `room_number`: Auto-incrementing unique ID (starts at 1)
- `color`: Random RGB tuple (each component 20-235)
- `room_radius`: Distance from center to vertex, calculated as `50 / sin(pi / num_sides)`

### Default Room Geometry

Regular polygons are generated with:
- First vertex at top (angle = -π/2)
- Vertices placed at equal angular intervals
- Radius calculated so that edge length is approximately 100 units (derived from `50 / sin(π/num_sides)`)

### Room Texture

Each room has a procedurally generated checkerboard texture:
- Grid size is 20 pixels (default) or loaded from level file
- Alternating squares use the room's random color vs transparent
- Texture size is `room_radius * 2.2`
- Texture is centered on room center during rendering

### Edge Class

Each edge stores:
- `target_room`: Reference to the connected room (None if solid wall)
- `target_edge_idx`: Which edge index in the target room this connects to
- `transform`: 3x3 matrix mapping target room coords → this room coords
- `inv_transform`: Cached inverse (computed lazily on first use during rendering)

---

## Non-Euclidean Rendering Algorithm

The `Room.draw()` method implements visibility-aware recursive rendering:

### Overview

1. Uses a stack-based iterative approach (not true recursion) to traverse room connections
2. Draws rooms back-to-front by collecting them first, then rendering in order
3. Tracks view frustums to cull invisible geometry
4. Uses a cache to avoid drawing the same room+transform combination twice

### Cache Key

The draw cache prevents redundant rendering:
```python
cache_key = (id(room), tx, ty, cos_theta)
```
Where tx, ty are rounded to 0.1 precision and cos_theta to 0.01 precision. This means the same room at very similar transforms is only drawn once.

### Frustum Tracking

When entering a room through an edge:
- `entry_edge_index`: Which edge we entered through (can't look back out that edge)
- `visible_entry_segment`: (t1, t2) parametric range of the entry edge that's visible
- `view_cone_rays`: Two unit vectors defining the left/right bounds of visibility

When `entry_edge_index` is None (first room) or view angle exceeds 170°, the entire room is considered visible (full = True).

### Edge-Frustum Intersection

`_compute_edge_frustum_intersection()` calculates what portion of an edge is visible from the viewpoint through the current frustum:
- Uses ray-segment intersection tests
- Returns parametric (t1, t2) range of the edge that's visible
- Returns None if edge is not visible or visible portion is too small (< 0.5 units)

### Rendering Layers

Six surfaces are used for compositing:
1. `room_layer`: Accumulated room geometry (opaque)
2. `entity_layer`: Entity sprites (with alpha)
3. `mask_layer1`: Room polygon mask
4. `mask_layer2`: Frustum mask
5. `entities_mask`: Union of all visible areas (for entity visibility)
6. `work_layer`: Temporary compositing surface

For each room drawn:
1. Draw room texture to work_layer
2. Draw walls (white lines for solid edges, gray if connected and debug on)
3. Create polygon mask in mask_layer1
4. Create frustum mask in mask_layer2 (or fill white if full visibility)
5. Combine masks: `mask_layer1 = min(mask_layer1, mask_layer2)` per pixel
6. Apply mask to work_layer: `work_layer *= mask_layer1`
7. Copy work_layer to room_layer
8. Accumulate mask to entities_mask for later entity visibility masking
9. Draw entities in this room to entity_layer

### Recursion Limits

- `max_recursion_depth`: Default 12; stops traversing after this many room transitions
- Rooms with projected radius < 10 pixels are not traversed further (but are still drawn)
- Each traversal pushes connected rooms onto the stack with updated frustums

### Recursion Termination

For each edge (except the entry edge):
1. If no target room, skip
2. Calculate the visible portion of this edge through current frustum
3. If nothing visible, skip
4. Transform viewpoint to target room's coordinate system
5. Calculate new frustum rays from viewpoint through visible edge portion
6. Push target room onto stack with new frustum parameters

---

## Entity System

### Entity Base Class

All game objects inherit from Entity:

#### Properties
- `parent_room`: The room this entity is in
- `pos`: numpy array, position relative to room center
- `direction`: Unit vector indicating facing direction
- `velocity`: Current velocity vector
- `sprite_size`: Visual size (default 20)
- `collision_radius`: For circle-based broad-phase collision (default = sprite_size * 0.9)
- `mass`: For physics calculations (default 1.0)
- `max_step_distance`: Maximum movement per physics sub-step (default 100.0)
- `is_gone`: Flag marking entity for removal
- `previous_room`: The room we just came from (to prevent immediate bounceback)
- `color`: Random RGB for rendering

#### Sprite Shape

Default entity sprite is an isosceles triangle:
- Front point at (sprite_size * 1.5, 0)
- Back corners at (-sprite_size * 0.8, ±sprite_size * 0.8)
- Rotated to face `direction` during rendering

### Physics Update

`Entity.update(dt)`:
1. Calculate total intended movement from velocity * dt
2. Subdivide into steps if movement exceeds `max_step_distance`
3. For each sub-step, call `_update_step(dt_per_step)`

`Entity._update_step(dt)`:
1. Loop up to 10 iterations while remaining_time > 0
2. Calculate step_movement = velocity * remaining_time
3. Check entity collisions at new position
4. If entity collision: move to collision point, call `handle_collision()`, reduce remaining_time
5. Check edge collisions (walls/transitions)
6. If wall collision: bounce, reduce remaining_time
7. If room transition: transfer to new room
8. If no collision: done with this step

### Collision Detection

#### Entity-Entity (Broad Phase)
- Circle-circle check: `dist < collision_radius_1 + collision_radius_2`

#### Entity-Entity (Narrow Phase)
- Separating Axis Theorem (SAT) on polygon vertices
- Projects both polygons onto edge normals
- If any axis has a gap, no collision
- Collision normal is vector from other.pos to self.pos

#### Entity-Edge
- For each edge, calculates signed distance to edge line
- If entity crosses edge line (distance goes negative) and is within edge bounds:
  - If edge has target_room: trigger room transition
  - If edge is solid: bounce (reflect velocity about edge normal)

### Collision Response

`Entity.handle_collision(other, normal)`:
- Edge collision: Reflect velocity about normal
- Entity collision: Conservation of momentum with restitution 0.8

### Room Transition

`Entity._transfer_to_room(new_room, transform)`:
1. Set `previous_room` to old room (prevents immediate re-transition)
2. Remove self from old room's entity list
3. Transform position using inverse of edge transform
4. Nudge position slightly toward room center (EPSILON * 2 units)
5. Transform velocity and direction vectors (rotation only)
6. Add self to new room's entity list
7. Return new position

---

## Player Entity

Extends Entity with:
- `move_force`: 300 (acceleration per second when moving)
- `shot_cooldown`: 0.25 seconds (4 shots per second)
- `lightning_cooldown`: 30.0 seconds

### Movement

1. Read WASD input to get screen-space direction
2. Transform to world-space using inverse camera rotation
3. Apply acceleration: `velocity += direction * move_force * dt`
4. Apply friction: `velocity *= (1.0 - 2 * dt)`
5. Call base Entity.update()
6. Face mouse cursor (transform screen coords to world coords)

### Shooting

On left mouse held:
- If cooldown elapsed, spawn Bullet at triangle tip position
- Bullet velocity = `direction * 64000 + player.velocity`

### Lightning Cannon

On right mouse held:
- If 30-second cooldown elapsed, spawn LightningDart
- Dart velocity = `direction * 800 + player.velocity`

### Room Transition Override

When player transitions rooms, also updates camera transform to maintain visual continuity.

---

## Bullet Entity

High-speed projectile with:
- `sprite_size`: 5
- `collision_radius`: 3
- `mass`: 0.0008
- `max_step_distance`: 20 (smaller steps for accuracy)
- `min_speed`: 100 (removed if slower)

### Visual Trail

- Stores last 15 positions in `trail_points`
- Draws line through all points when moving above min_speed
- `has_drawn` flag ensures bullet isn't removed before being visible at least once

### Collision Behavior

- On hitting Enemy: deal damage, mark self for removal
- On hitting wall: `velocity *= 0.5`, remove if below min_speed
- On hitting other: mark self for removal

### Room Transition

Transforms all trail points to new room's coordinate system.

---

## LightningDart Entity

Special projectile with area-of-effect detonation:
- `sprite_size`: 8
- `min_speed`: 50
- `detonation_radius`: 100
- `explosion_force`: 2000
- `damage`: 20

### Detonation

When hitting something:
1. Set `lightning_active = True`
2. Record explosion position
3. Find all entities within detonation_radius in same room
4. Apply damage with distance falloff: `damage * (1 - distance/radius)`
5. Apply knockback: `entity.velocity += direction * force * falloff`

### Lightning Visual

- Generates 5-10 random branching lightning bolts from explosion center
- Each branch has 4-10 zigzag segments
- Sub-branches spawn with 40% probability
- Pattern stored in world coordinates, transformed during room transitions
- Rendered with flicker effect (20% chance to skip each frame)
- Fades over `lightning_time` seconds (0.8)

### Lifecycle

- Before detonation: moves like a bullet with trail
- After detonation: stays in place, renders lightning effect
- Removed when lightning_time expires

---

## Enemy Entity

Octagon-shaped enemy with:
- `chase_force`: 200
- `max_speed`: 150 (not currently enforced)
- `max_hp`: 15
- `hp`: Current health

### Behavior

Each update:
1. If player in same room: accelerate toward player
2. Else: use NavigationManager to find path, accelerate toward next edge
3. Apply friction: `velocity *= (1.0 - 0.2 * dt)`

### Damage

`take_damage(amount)`:
- Subtract from hp
- If hp <= 0: mark for removal, return True
- Update color saturation based on remaining HP percentage

---

## Navigation System

### NavigationManager

Caches pathfinding results from any room to a destination.

`explore_from_room(start)`:
- Dijkstra's algorithm from start room
- For each room discovered, records which edge leads back toward start
- Returns dict mapping Room → edge_index

`get_next_edge(from_room, to_room)`:
- If to_room not in cache, run explore_from_room(to_room)
- Return cached edge index for from_room

This means pathfinding is done once per destination room, then cached.

---

## GameWorld

Top-level container:
- `graph`: NetworkX graph of room connections
- `player`: Reference to Player entity

### Room Creation

`create_room(num_sides)`: Creates regular polygon room, adds to graph.

### Room Connection

`connect_rooms(room1, edge1_idx, room2, edge2_idx)`:
1. Get vertex pairs for both edges
2. Calculate rotation angle to align edges (with π added to flip)
3. Calculate translation to align edge midpoints
4. Compose into transform matrix
5. Set room1.edges[edge1_idx] to point to room2 with transform
6. Set room2.edges[edge2_idx] to point to room1 with inverse transform
7. Add edge to NetworkX graph

### Entity Collection

`collect_nearby_entities(max_distance)`:
- BFS from player's room
- Collects all entities within max_distance room-hops
- Removes entities marked `is_gone`

---

## Main Loop

```
while running:
    dt = clock.tick(240) / 1000.0  # Target 240 FPS
    dt = min(dt, 0.2)  # Clamp to prevent physics explosion
    
    handle_input_events()
    
    if left_mouse_held:
        player.try_shoot(current_time)
    if right_mouse_held:
        player.try_lightning(current_time)
    
    if UPDATE_ENTITIES:
        for entity in world.collect_nearby_entities(6):
            entity.update(dt)
    else:
        player.update(dt)  # Debug mode: only update player
    
    Camera.update(player.pos, dt)
    
    clear_all_surfaces()
    
    world.root_room.draw(...)  # Render from player's room
    
    composite_layers_to_screen()
    
    gc.collect(0)  # Incremental garbage collection
```

---

## Level File Format

JSON structure:
```json
{
  "version": "1.0",
  "meta": {
    "grid_size": 50,
    "snap_to_grid": true,
    "edge_camera_movement": true
  },
  "rooms": [
    {
      "id": 1,
      "vertices": [[x1,y1], [x2,y2], ...],
      "connections": {
        "0": {"target_room": 2, "target_edge": 3}
      },
      "entities": [
        {"type": "Player", "pos": [x, y]},
        {"type": "Enemy", "pos": [x, y]}
      ]
    }
  ]
}
```

### Loading

1. Create rooms with vertices (converted to room-local coords by subtracting center)
2. Store absolute center for later connection calculations
3. Create entities at positions relative to room center
4. Create connections using `connect_rooms()` (which recomputes transforms)

---

## Debug Features

Toggle keys:
- F2: `DRAW_CONNECTED_EDGES` - Draw gray lines for connected edges
- F3: `DRAW_ROOM_NUMBERS` - Draw room ID at center
- F4: `SHOW_PERFORMANCE` - Cycle through off/print/display FPS
- F5: `DEBUG_VISIBILITY` - Draw frustum polygons in blue, entry edge portions in red/green
- F6: `DEBUG_COLLISIONS` - Draw collision points and remaining movement
- F7: `VISUALIZE_CONSTRUCTION` - Step through rendering one room per frame
- F9: `UPDATE_ENTITIES` - Toggle entity updates (debug player-only mode)

### Performance Monitor

Tracks last 10 frame times, calculates average FPS.

---

## Known Issues / Design Quirks

1. **Bullet initial velocity is extremely high** (64000 units/sec), possibly a typo for 640.

2. **Enemy max_speed is never enforced** — only chase_force is used, velocity can exceed limit.

3. **Room transition epsilon nudge** uses `EPSILON * 2` which is essentially zero (float epsilon is ~2e-16). This nudge is too small to be meaningful.

4. **LightningDart damage only applies to entities in same room** — blast doesn't cross room boundaries.

5. **Level file can have duplicate entities** — example level.json has duplicate Player and Enemy entries.

6. **Camera screen center is hardcoded** to (400, 300) but window is resizable in editor.

7. **NavigationManager cache is never cleared** — if level topology changes, stale paths remain.

8. **Friction application varies** — Player uses `1 - 2*dt`, Enemy uses `1 - 0.2*dt` (10x difference).

9. **Trail points accumulate during physics sub-steps** — bullet trails can have many closely-spaced points.

10. **Garbage collection is disabled globally** with only gen0 collection per frame — may cause memory issues in long sessions.

---

## Level Editor (leveledit.py)

Separate application for creating levels:

### Tools
1. **Polygon Tool**: Click vertices to create convex rooms
2. **Vertex Tool**: Drag vertices to reshape rooms
3. **Connection Tool**: Click edges to connect rooms
4. **Entities Tool**: Place Player, Enemy entities
5. **Move Tool**: Drag rooms

### Features
- Grid snapping (configurable size)
- Edge-of-screen camera panning
- Undo/redo system
- Concave polygon detection (prevents saving)
- Automatic polygon "fixing" via chord splitting or circular adjustment

### Connections

Connections are stored as `(target_room_id, target_edge_index)` tuples. The editor doesn't compute transforms — those are computed at runtime by `load_level_from_file()` calling `connect_rooms()`.

---

## Ideas Scratchpad (from source)

> Let edges connect to multiple other edges — whenever we need to use the edge connection for something other than rendering, pick one at random. When the player looks through such an edge everything on the other side will appear to be chaotically shifting every frame. Maybe instead have it shift once every 5 frames or something? Either that, or certain angles lead to one connection or the other, sort of like a lenticular image. Beside looking cool this has a gameplay effect — if you are standing in a room shooting through such an edge at a target on the other side, half your bullets go to the wrong place, but if the multiplicity effect is one way, the same does not apply to the other guy!

---

## Procedural Level Generation

`create_large_test_level()` generates a test level:

### Structure
- 5 hub rooms (hexagon, octagon, pentagon, heptagon, square)
- Hubs connected by 4-6 room corridors
- Additional branching corridors from each hub
- Cycle loops (rooms that connect back to earlier rooms)
- Spiral patterns (series of hexagons connecting in a helix)
- Mirror corridor (room that connects to itself)
- Dense clusters (room with multiple connections to neighbors)
- Maze-like branches

### Room Types in Corridors
- Randomly chosen from triangles, squares, and pentagons

---

## Utility Functions (util.py)

### perturb_world(world, magnitude=0.2)

Randomly jostles room vertices while:
- Maintaining convexity
- Preserving connections
- Normalizing connected edge lengths to match

### debug_room(room)

Prints detailed information about a room's vertices, edges, connections, and transforms.

### check_room_connections(world)

Traverses room graph printing debug info for each room encountered.
