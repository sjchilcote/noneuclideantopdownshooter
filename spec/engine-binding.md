---
This specfile tells the work of the engine binding: the crate `necore-py` in `engine/necore-py`, which compiles to the Python module `necore`. The units are the Python classes and functions of the module, the platform layer for audio and the window, and the video recording path.

---

# Engine binding

This specfile tells the work of the crate `necore-py`. The crate is the Python module `necore`, a `cdylib` through `pyo3`. `PERIHELION` imports this module for physics, queries, the rasterizer, the window, audio, and video recording. The native engine is the crate `necore` in `engine/necore`, which this file does not include. This file tells the boundary between Python and Rust. The boundary includes the data that crosses it and the shape of that data.

These 3 requirements hold across the full module:

- All matrices go across the boundary as row-major 9-tuples of floats (`M9`).

- All angles are radians.

- Engine, platform, media, validation, and buffer failures become `ValueError` when the binding catches them. The message tells the cause. `FrameMismatch` is a subclass of `ValueError`. Python and `pyo3` can raise their standard errors before a Rust method starts. Examples are `TypeError` for an incorrect Python argument type and a buffer-protocol error for an incompatible typed buffer.

  A Rust panic or allocation failure can occur without a returned Rust error. A process started by this module can also fail with no returned Rust error. Those failures do not use this conversion.

## Crate configuration (`engine/necore-py/Cargo.toml`)

### Goal

The crate assembles one Python extension module that contains the engine binding and platform layer. One binary is applicable to Python 3.11 and subsequent versions.

### Invariants

- The library name is `necore`, and the crate type is `cdylib`.

- The `abi3-py311` flag of `pyo3` sets the stable Python ABI at version 3.11.

### Verification

`import necore` completes in Python 3.11 or a subsequent version. The module contains the classes and functions added by the module function in `lib.rs`.

### Implementation

The libraries and their tasks:

- `necore_core` — the native engine, the crate `necore` in `engine/necore`.

- `pyo3` 0.23 with `extension-module` and `abi3-py311` — the Python boundary.

- `winit` 0.30 — the window and the OS events.

- `softbuffer` 0.4 — copies the CPU frame to the window.

- `cpal` 0.15 — the audio output stream.

- `png` 0.17 — encodes PNG data for `write_png`.

- `minimp4` 0.1 with the `aac` flag — the AAC encoder for the recorder.

The module function `necore` in `lib.rs` adds 13 classes, the `FrameMismatch` error type, and 13 functions. The classes are `Sim`, `Raster`, `Space`, `Coordinate`, `Offset`, `Transform`, `EntityState`, `Track`, `RayResult`, `SignalField`, `AudioMixer`, `Window`, and `VideoRecorder`. The functions are the 9 matrix functions, `clip_polygon`, `clip_polyline`, `write_png`, and `read_sidecars`.

### Caveats

A comment in `Cargo.toml` names the platform layer as the part that replaces `pygame`. It includes window, frame output, event collection, audio output, and video encoding.

## Matrix functions (`src/lib.rs`, module level)

### Goal

Python holds `3x3` transforms as flat tuples. These functions multiply and apply matrices, assemble new matrices, calculate inverses, and read rotation angles. Two more functions clip shapes to convex regions.

### Invariants

- The tuple sequence is row-major, and angles are radians.

- `mat_inv` does not accept a matrix that is not invertible.

### Verification

To floating-point precision, `mat_mul` of a matrix and its `mat_inv` result gives the identity matrix. `mat_rotation_angle(mat_rotate(t))` gives the primary angle equivalent to `t`. `mat_inv` of a matrix with a zero row raises `ValueError`. Correct convex inputs have the specified vertex sequence. Each point from `clip_polygon` is in the clip region or on its edge.

### Implementation

The type `M9` is a 9-tuple of `f64`. The functions:

- `mat_mul(a, b)` — calculates matrix `a` times matrix `b`.

- `mat_inv(m)` — the inverse. It raises `ValueError` with the text `matrix is not invertible` when no inverse is available.

- `mat_apply(m, x, y)` — the full transform of a point, as a pair.

- `mat_apply_dir(m, x, y)` — only the linear part, for directions.

- `mat_translate(x, y)`, `mat_rotate(theta)`, `mat_scale(sx, sy)`, `mat_identity()` — assemble new matrices.

- `mat_rotation_angle(m)` — `atan2(m[3], m[0])`.

- `clip_polygon(subject, clip)` — clips a convex shape at a convex region through `geom::clip_polygon_convex`.

- `clip_polyline(pts, clip)` — cuts a polyline at a convex region and returns the pieces as a list of point lists.

### Caveats

The matrix maps `(x, y, 1)` column vectors. Its first row is `(m[0], m[1], m[2])`, and its second row is `(m[3], m[4], m[5])`. A positive angle turns from the positive x-axis to the positive y-axis. Screen coordinates can make that direction look clockwise when positive `y` points down.

`mat_rotation_angle` reads only 2 values of the matrix. For a matrix with scale or with a mirror transform, the result is the angle of the first column only.

The two clip functions do not check convexity, vertex sequence, duplicate points, self-intersection, or degenerate geometry. They give the sequences to the convex clipping procedures. Empty or incorrect geometry can return an empty or incorrect result. The binding does not raise a validation error.

## `FrameMismatch` (`src/frames.rs`)

### Goal

`FrameMismatch` is the error type for operations between coordinate spaces. The caller always receives it. Code that mixes two spaces with no route receives this error, not an incorrect number without an error.

### Invariants

- `FrameMismatch` is a subclass of `ValueError`. Code with `except ValueError` continues to catch it.

- Each between two spaces error in the module raises this type.

### Verification

When code subtracts two coordinates from two spaces with no route between them, `necore.FrameMismatch` occurs. An `except ValueError` block also catches this error.

### Implementation

The `create_exception!` call adds the type to module `necore` as a subclass of `PyValueError`. The `frame_err` helper changes a native-engine `FrameError` to this error with the native-engine message.

### Caveats

The message text comes from the native-engine error type, not from this crate.

## `Space` (`src/frames.rs`)

### Goal

Each object is one coordinate space. Two calls to `Space("Screenspace")` return different spaces.

### Invariants

- Two `Space` objects are equal only when their `id` values are equal.

- The hash of a `Space` is its `id`.

### Verification

`Space("a") == Space("a")` returns `False`. Two calls to `sim.polygon_space(r)` return equal objects. `space.place(x, y)` returns a `Coordinate` in `space`.

### Implementation

The class contains the native-engine `CoordinateSpace`. `Space(name)` assembles a new space. The `id` property (a `u64`) and `name` property identify it. `place(x, y)` returns the `Coordinate` at `(x, y)` in this space. Its representation is `Space({name:?}, id={id})`.

### Caveats

`Space.place` gives a known space to numbers that did not come from an engine query. The primary condition is pointer input. The OS supplies screen coordinates, and this call identifies their space. Code must name a location's space in the same line that supplies its numbers.

## `Coordinate` (`src/frames.rs`)

### Goal

A location contains a value pair, its active space, and the record of spaces through which it moved. Python cannot assemble a `Coordinate` from bare numbers. A location comes only from a source that names the space: an entity, portal, view record, `Sim.place`, or `Space.place`.

### Invariants

- The class has no Python constructor.

- Each operation that mixes two records raises `FrameMismatch` when the records have no same space.

- `__sub__` gives an `Offset` in the space of the left value.

### Verification

`Coordinate(...)` in Python raises. For two coordinates `a` and `b` in one space, `(a + (b - a)).local()` equals `b.local()`. `a.toward(b).local()` equals `(b - a).local()`. When two coordinate records have no same space, `-`, `distance_to`, and `toward` raise `FrameMismatch`. Offset addition also raises `FrameMismatch` when the records have no same space.

### Implementation

The properties and methods are:

- `space` — the space the location is in, at the end of its record.

- `chain` — each space the location was in, in time sequence, the first space first. An error message prints this record.

- `local()` — the raw pair in the space of the location.

- `offset(dx, dy)` — an `Offset` in the space of the location.

- `__sub__(other)` — the difference as an `Offset` in the left space.

- `__add__(offset)` — a moved location.

- `distance_to(other)` — the distance, measured in the left space.

- `toward(other)` — calls `other.sub(self)`. Thus, it points from `self` to `other` and is in the active space of `other`.

- `transformed(t)` — the location through a `Transform`.

- `__repr__` — the pair, the space name, and the record length.

For an operation on two coordinates, the left record selects a space contained in the two records. The operation examines the left chain from last to first. It selects the first space also found in the right chain. It uses the position of that space nearest the end of the right chain. It moves the right value rearward to the selected space and then forward through the remaining left record.

The result is in the terminal space of the left coordinate. Subtraction and addition start a new result record in that space and keep the two input records.

The correct representation is `Coordinate({x:.2}, {y:.2} in {space-name} via {n} hop)` when the record has one step. It uses `hops` for all other record lengths, with zero.

### Caveats

`local()` is for channels that name the space with the pair. Examples are a sound at a polygon, a decal, and an engine call. Code that calculates `a.local()[0] - b.local()[0]` runs with no space check. Through a portal with scale, `a.distance_to(b)` and `b.distance_to(a)` give different values, and each is correct in its space.

Defect: the source comment states that `toward` returns an offset in the space of `self`. The call is `other.sub(self)`, thus the returned offset is in the space of `other`. Across a portal with scale, this does not give the direction in the caller space that the comment states.

## `Offset` (`src/frames.rs`)

### Goal

A difference in one space. Python assembles an `Offset` freely. A location is different. A difference in the space of the caller is a decision. A location from bare numbers is a record about the world.

An offset moves through a portal by the linear part of the transform only.

### Invariants

- Operations on two offsets from spaces with no route between them raise `FrameMismatch`.

- `o / 0` raises `ValueError`.

- The truth value of an offset is `False` only when the two local components are zero.

### Verification

`Offset(space, 3, 4).length` equals 5. `o.normalized().length` equals 1 for an offset that is not empty. `o.dot(p)` for offsets from spaces with no route between them raises `FrameMismatch`. `o / 0` raises `ValueError`.

### Implementation

`Offset(space, dx, dy)` assembles an offset. Its properties are `space`, `length`, and `angle` (radians). Its operations are `local()`, `normalized()`, `rotated(theta)`, `dot`, `cross`, `+`, `-`, `* k`, `k *`, `/ k`, `__neg__`, `__bool__`, and `transformed(t)`.

An offset also contains its origin and transform record. Binary offset operations use the same operation as coordinate operations to select a space. They move the right offset through the linear parts of the recorded transforms into the left offset's space. Addition and subtraction return a new offset in the left space. `dot` and `cross` measure the two inputs in the left space and return a bare number.

`normalized()` returns the unit offset `(1, 0)` in the same space when the input length is less than `1e-12`. This includes the zero offset.

The correct representation is `Offset({dx:.2}, {dy:.2} in {space-name})`.

### Caveats

`length` and `angle` are bare numbers, and a bare number has no space. A limit in one space is not directly comparable with a length in a different space. This is important when a portal scales. `rotated` turns in the space of the offset. A mirror transform changes handedness. Rotation occurs before transport.

Normalization, scaling, rotation, and division do not reject nonfinite values. Division rejects positive and negative zero, but a nonzero infinite or NaN divisor follows floating-point arithmetic.

## `Transform` (`src/frames.rs`)

### Goal

A `Transform` contains a matrix and the two spaces it maps between. If a value is not in the source space, `apply` raises an error. It does not return a possible but incorrect number.

### Invariants

- A `Transform` maps only values with its `from_space` as their space.

- `inverse()` maps in the other direction: from `to_space` to `from_space`, with the inverse matrix.

### Verification

`t.inverse().from_space` equals `t.to_space`. `c.transformed(t)` for a location not in `t.from_space` raises `FrameMismatch`. A location through `t` and then through `t.inverse()` is at its start pair.

### Implementation

`Transform(from_space, to_space, m9, name="transform")` assembles a transform. Construction calculates the matrix inverse and raises `FrameMismatch` with `transform is not invertible` when no inverse is available. Its properties are `from_space`, `to_space`, and `m9`. `inverse()` returns the inverse transform. Its representation is `Transform({name:?}: {from-name} -> {to-name})`.

### Caveats

None.

## `EntityState` (`src/frames.rs`)

### Goal

`EntityState` is a state snapshot of one entity: polygon, location, velocity, direction, and radius. This record replaces a tuple of 7 floats. Each tuple float was a number with no space attached. 28 call points read the floats and mixed spaces freely.

### Invariants

- `pos`, `vel`, and `dir` hold the space of the entity polygon in the snapshot.

- The `pos`, `vel`, and `dir` properties assemble their objects only when read. The `polygon` property returns its integer without more work.

### Verification

For an entity in polygon `r`, `state.space` equals `sim.polygon_space(r)`. `state.pos - other_state.pos` for entities in polygons with no route between them raises `FrameMismatch`. `state.speed` equals `state.vel.length`.

### Implementation

`Sim.get` returns this record. Its properties are:

- `polygon` — the polygon index. A test of two such indices always identifies topology.

- `space` — the space of that polygon.

- `pos` — a `Coordinate`.

- `vel` — an `Offset`.

- `dir` — the unit `Offset` of the entity direction.

- `radius` — a length, and a length has no space.

- `speed` — the length of the velocity.

The correct representation is `EntityState(polygon={polygon}, pos=({x:.1}, {y:.1}) in {space-name})`.

### Caveats

The record is a snapshot at one tick. Subsequent simulation changes do not change it.

## `RayResult` (`src/frames.rs`)

### Goal

The ray result, with the two frames available. `pos` is in the space of the hit polygon, for a caller that marks the wall or the floor. `to_origin` moves values to the start space, for a caller that points an attack.

### Invariants

- `kind` is one of `"wall"`, `"ent"`, and `"none"`.

- `entity_id` is a value only for `"ent"`. `edge` is a value only for `"wall"`.

- The space of `pos` equals the space of `polygon`, and `to_origin` maps that space to the start space.

### Verification

A ray at a wall returns `kind == "wall"` with an `edge` and no `entity_id`. `result.pos.transformed(result.to_origin)` gives the hit location in the start space.

### Implementation

Its properties are `kind`, `entity_id`, `polygon` (where the ray ended), `edge`, `pos`, `to_origin`, `distance`, and `hops`. The distance adds the length of each route segment in sequence.

For `kind == "none"`, `entity_id` and `edge` are `None`. `polygon` is the last polygon found. `pos` is the location where the length or hop limit stopped the ray. `to_origin` maps that location to the start space. `distance` is the collected route length, and `hops` is the number of portal crossings.

The distance adds each segment after measurement in its polygon metric. Portal scale can thus make it different from a straight length in an end space.

The correct representation is `RayResult({kind} in polygon {polygon} at {distance:.0}u, {hops} hops)`.

### Caveats

None.

## `Track` (`src/frames.rs`)

### Goal

A `Track` records a view of the target, not the entity. The observer's route sets its values. Thus one entity can have many tracks when different routes show it. Distance and depth are here because they give facts about the observer-target pair.

### Invariants

- `pos`, `vel`, and `dir` moved along the same route into the observer space. Two different routes for one view can put two different transforms on the values. The difference between the routes then damages the values.

- `tick` records the time of the view. The binding does not compare it with the simulation tick. It does not reject a track from a tick before it. The caller must compare the ticks before it uses a track as new data.

### Verification

For a target in view through one portal, the space of `track.pos` equals the observer space, and `portal_depth` equals 1. Caller code that uses `track.vel` to point in front of the target stays correct across a portal with rotation.

### Implementation

Its properties are `entity_id`, `polygon` (where the target was when the view was recorded), `pos`, `vel`, `dir`, `path_distance`, `distance`, `portal_depth`, and `tick`. `path_distance` adds route segments in their polygon metrics. `distance` is the straight length in the observer space, which contains the observer range constants.

The correct representation is `Track(entity {entity_id}, {distance:.0}u away, depth {portal_depth}, tick {tick})`.

### Caveats

The `dir` field removed a caller-side defect. Code that pointed an attack with the raw body direction stopped at each portal. A direction moved along the route of the view works at each depth.

## `Sim` — world construction (`src/lib.rs`)

### Goal

Convex polygons form the world graph, and portals connect them. `PERIHELION` adds polygons, connects edges, and reads the geometry. It also cuts edges for portals that use only part of an edge.

### Invariants

- A polygon index out of range raises `ValueError` with the text `no polygon {r}`.

- An edge index out of range raises `ValueError` with the text `polygon {r} has no edge {e}`.

- Native-engine errors become `ValueError` with the native-engine message. These errors include an incorrect polygon or edge and an edge with a portal. They also include a polygon that is not convex, a degenerate edge, and a supplied transform that is not invertible.

### Verification

`add_polygon` returns index 0, 1, 2 in sequence. After `connect(a, ea, b, eb)`, `polygon_portals(a)[ea]` equals `(b, eb)`. After `disconnect`, the entry is `None`. `split_edge` returns the middle new edge index, and `polygon_verts` shows the two new vertices.

### Implementation

The methods:

- `Sim()` — an empty world and a new route cache.

- `add_polygon(verts)` — must have 3 or more vertices and changes the vertex sequence to the engine orientation convention. It rejects a polygon that is not convex or an edge shorter than `1e-9`. It moves the vertices to their centroid and returns the new index.

- `connect(a, ea, b, eb)` — connects two edges as a portal pair. The edges can have different lengths. The calculated transform turns and scales the neighbor edge equally in the two directions to fit.

- `connect_with_xform(a, ea, b, eb, m9)` — installs a caller-supplied invertible transform. It does not check that the two edges align after that transform.

- `disconnect(a, ea)` — removes a portal.

- `split_edge(polygon, edge, t0, t1)` — cuts a solid edge at the two parameters and returns the middle new edge index.

- `num_polygons()`, `polygon_verts(r)`, `polygon_portals(r)`, `portal_xform(r, e)`, `edge_endpoints(r, e)`, `polygon_radius(r)` — geometry reads.

- `edge_midpoint(r, e)` — the middle of an edge as a `Coordinate` in the space of that polygon. This is the steer target for a portal.

- `edge_normal(r, e)` — the unit normal vector of an edge, into the polygon, as an `Offset` in the space of that polygon.

### Caveats

`split_edge` moves the edge indices after the cut edge up by 2, and the native engine corrects its portals. A Python-side table can use `(polygon, edge)` keys. It must move its keys by the same 2, or entries point at incorrect edges.

`split_edge` accepts only a solid edge and parameters with `t0 > 1e-6`, `t1 < 1 - 1e-6`, and `t1 - t0 > 1e-6`. Each other condition raises `ValueError` from the native engine. The two parameters are fractions from the first endpoint to the second endpoint.

`portal_transform(r, e)` is different from the other indexed geometry reads. An edge index out of range returns `None`, the same result as a solid edge. `portal_xform(r, e)` raises `ValueError` for an edge index out of range.

## `Sim` — spaces and transport (`src/lib.rs`)

### Goal

Each polygon frame is a coordinate space. These methods return the space objects and change numbers from level files to locations. They also transport values between spaces along portal routes.

### Invariants

- `place(r, x, y)` names the polygon and the numbers in one call. The caller cannot give the position from one polygon with the index of a different polygon.

- `transform_between` and `develop` use the route with the smallest route-length cost.

- `develop` and `transform_between` return `None` when no route is available. They also return `None` when a space is not a polygon of this world.

### Verification

`polygon_of(polygon_space(r))` equals `r`. `polygon_of(Space("other"))` is `None`. For two connected polygons, `develop(place(a, x, y), polygon_space(b))` returns a location in the space of polygon `b`. `develop` into an independently assembled screen space returns `None`.

### Implementation

The methods:

- `polygon_space(r)` — the `Space` of the polygon.

- `place(r, x, y)` — the `Coordinate` at `(x, y)` in polygon `r`. This is the portal for level file data.

- `polygon_of(space)` — the polygon index of a space, or `None` when the space is not a polygon of this world. This is the path for interfaces that use polygon indices.

- `portal_transform(r, e)` — the `Transform` of the portal, or `None`. It maps the coordinates of the neighbor into the coordinates of polygon `r`.

- `transform_between(from, into)` — the composed `Transform` from `from` to `into` along the shortest route, or `None`. Its `from_space` is `from`, and its `to_space` is `into`. Its inverse supplies the other direction.

- `develop(c, into)` — a location moved into a different space along the shortest route, or `None`.

For `develop`, route cost starts at the given coordinate. For `transform_between`, it starts at `(0, 0)` in the source polygon. Each route segment is the distance from its entry edge midpoint or start point to its exit edge midpoint. The search uses the polygon count as its maximum hop count. For equal costs, the priority queue compares `(polygon, entry_edge, hops)`.

It removes the larger key first. A subsequent path replaces a previous path only when its cost is smaller by more than `1e-12`.

3 internal helpers do the space work for coordinate methods. `entity_space(id)` returns the space of an entity. `polygon_for(space)` returns the polygon of a space and raises `FrameMismatch` when the space has no polygon. `own_offset(id, o)` accepts an offset only in the entity space and raises `FrameMismatch` for each other space.

### Caveats

`transform_between` is for operations at a location that extend through a portal. An explosion measures each body in the explosion space and pushes each body in the body space. Those are the two directions of one transform. Two `develop` calls can select two different routes, and their results then do not agree.

## `Sim` — walk-mask terrain (`src/lib.rs`)

### Goal

A polygon can contain axis-aligned blocked rectangles from the terrain-mask image of its floor. Physics stops bodies at these rectangles, and AI steers around them.

### Invariants

- `set_polygon_terrain` replaces the full set. An empty list clears the polygon to fully open ground.

- Terrain stops each entity group, unless `set_terrain_block(group, False)` frees that group.

- `terrain_avoid_dir` must receive the location and wanted direction in the same space. It returns a unit vector in that space.

### Verification

After `set_polygon_terrain(r, rects)`, `polygon_terrain(r)` returns equivalent rectangles with lower x and y coordinates before higher coordinates. After a step, an entity that moves into a blocked rectangle stops or moves along it. When a blocked rectangle is directly in front, `terrain_avoid_dir` returns a direction to one side, not the wanted direction.

### Implementation

The methods:

- `set_polygon_terrain(r, rects)` — `rects` is a list of `(lo_x, lo_y, hi_x, hi_y)` in the local coordinates of the polygon.

- `polygon_terrain(r)` — the rectangles at the call time, for tests and tools.

- `set_terrain_block(group, blocked)` — selects if terrain stops entities in a group.

- `terrain_light_segments(r)` — the terrain edge segments in local coordinates, for a light operation that uses them as walls.

- `terrain_avoid_dir(from, radius, desired, lookahead=40.0)` — changes `desired` to unit length and tests its swept circle through `lookahead` units. A vector with length below `1e-12` becomes `(1, 0)`. This includes zero. It returns the unit input when no rectangle is hit.

  For the nearest hit, it adds `0.9` times a perpendicular direction opposite the rectangle center. It changes the sum to unit length. If the two sides are equal, it selects the negative right perpendicular direction.

The binding does not check rectangle coordinates, or the signs or finite state of `radius` and `lookahead`.

### Caveats

`terrain_light_segments` is an interface only. The active render code does not read it. The source comment points at `ENGINE_DESIGN.md`, section `Walk-mask terrain & light occlusion`.

## `Sim` — entities (`src/lib.rs`)

### Goal

Bodies spawn at locations, move through velocity and impulses, and contain physics properties. Each write checks that its value is in the body space.

### Invariants

- `spawn` receives the polygon from the space of the coordinate. A position from one polygon cannot pair with the index of a different polygon.

- `set_vel`, `apply_impulse`, `set_dir`, and `set_pos` do not accept a value from a different space, and raise `FrameMismatch`.

- `set_pos` moves a body only in its polygon. The polygon of a body changes only in `step`.

- `apply_impulse` changes velocity by the impulse divided by the mass.

- An unknown entity id raises `ValueError` with the text `no entity {id}`.

### Verification

`spawn(place(r, x, y), ...)` puts the body in polygon `r`. `set_vel` with an offset assembled in the space of a different polygon raises `FrameMismatch`. After `apply_impulse(id, j)`, velocity increases by `j` divided by mass. `exists(id)` becomes `False` after `remove(id)`.

### Implementation

The methods:

- `spawn(at, radius, mass, group)` — a new body at a location, returns its id.

- `remove(id)`, `exists(id)`.

- `set_vel(id, vel)` — velocity as an `Offset` in the space of the body.

- `apply_impulse(id, j)` — applies a physics impulse. It does not write velocity directly.

- `soften_polygon(polygon)` — changes a rigid polygon into a deformable polygon. It does no work for an index out of range or a polygon that is deformable. It records each edge length as its neutral spring length and sets each vertex velocity to zero. It records no neutral position for the polygon.

- `soft_wall_impulse(polygon, edge, t, magnitude)` — adds velocity to the two vertices of a deformable edge. It clamps `t` to `[0, 1]` and divides the push between the vertices with weights `1-t` and `t`. A positive value pushes against the inward edge normal. The call does no work when the polygon is rigid or the edge is out of range.

- `set_pos(id, at)` — a move in the polygon of the body.

- `set_dir(id, dir)` — sets the normalized direction. A vector with length below `1e-12`, with zero, becomes `(1, 0)`. The call does not reject nonfinite components.

- `set_props(id, ...)` — writes each supplied value for `rest_wall`, `rest_ent`, `max_substep`, `transfers`, `radius`, `mass`, `group`, and `physical`. Only supplied fields change.

- `get(id)` — an `EntityState`. `get_radius(id)`, `get_polygon(id)` — one field each.

- `polygon_entities(polygon)` — the ids in a polygon.

- `set_active_within(polygon, hops)`, `activate_also(polygon, hops)`, `set_all_active()`, `active_polygons()` — the polygons that the simulation steps.

`spawn` has no optional values. It accepts each `f64` radius and mass and each `u8` group without a range check. It clamps the initial location in the direction of the polygon internal area. New state has zero velocity, direction `(1, 0)`, wall restitution 0, and entity restitution 0.3. It also has `physical=True`, `max_substep=max(radius, 1)`, and `transfers=True`.

A nonpositive mass is kept, but a subsequent `apply_impulse` raises `ValueError`. `set_props` has the method parameters `set_props(id, rest_wall=None, rest_ent=None, max_substep=None, transfers=None, radius=None, mass=None, group=None, physical=None)`. It keeps each given value without a range check.

`set_active_within` clears the previous active set and turns off the mode that steps all polygons. It selects the start polygon plus polygons found through not more than `hops` portals. `activate_also` adds such a region to the active set. It does no work while the mode that steps all polygons is on. `set_all_active` turns on that mode. `active_polygons` returns polygon indexes from low to high.

During `step`, an entity in an inactive polygon does not move and emits no event. Deformable walls continue to move in all polygons.

At the start of each `step`, each deformable edge applies spring acceleration. The acceleration comes from the difference between its length and its neutral length. The step applies velocity damping, limits each vertex speed to 220, and then moves the vertices. It moves a reflex vertex into the chord between the two nearest vertices to keep the polygon convex.

At a portal, the step aligns the related endpoint positions and velocities through the portal transform. It calculates that transform again from the moved endpoints. Entity collision work then uses the moved geometry.

### Caveats

The requirement of one space on `set_vel` and the other write methods catches errors at the source. A direction for a body comes from work in the frame of that body. A correction with no record can mask the one condition where it did not.

## `Sim.step` and events (`src/lib.rs`)

### Goal

One physics step returns its events as tuples. Each position and direction is assembled at the event source in the event polygon space.

### Invariants

- Positions and normal vectors in `wall`, `terrain`, and `contact` events use `Coordinate` and `Offset` values. These values are in the event polygon space.

- The `contact` event names the polygon from the event data, not from the body data after the step. The remaining step can move the bodies.

### Verification

A body that hits a wall gives a `wall` event. The space of its `pos` equals the space of the named polygon. A move through a portal gives a `transfer` event with the two polygon indices and the portal matrix.

### Implementation

`step(dt)` runs the native-engine step and maps each event:

- `("transfer", ent, from, to, edge, m9)` — a body moved through a portal.

- `("wall", ent, polygon, edge, pos, normal, speed)` — a wall hit.

- `("terrain", ent, polygon, terrain, pos, normal, speed)` — a terrain hit, with the rectangle index.

- `("contact", a, b, polygon, pos, normal, rel_speed)` — two bodies touched. Contact is always in one polygon, because the physics tests a body only against the list of its polygon.

The binding sends `dt` to the engine. It does not check for zero, negative, nonfinite, or unusually large values. Event sequence follows entity iteration and engine collision work. Entity storage uses a hash table. A stable event sequence across runs is not specified.

### Caveats

The `transfer` event holds no space values: two polygon indices, an edge index, and a bare matrix. It is the one event shape without the space checks.

## `Sim.visible_set` (`src/lib.rs`)

### Goal

This render query returns polygon images on the screen. Each image comes through a portal sequence and contains its transform, clip region, and entities that show. A polygon can show many times when portals show it along many routes.

### Invariants

- The result obeys `max_depth` and `max_instances`.

- An entity fully out of the clip region of an image does not show in that image.

- A body with its circle across a portal also shows in the neighbor image, with the clip always on. Thus no body is cut at a portal line.

### Verification

For a camera in a closed polygon with one portal, the result contains that polygon at depth 0. It contains the neighbor at depth 1. An entity across the portal line shows in the two images. The far image marks it as not fully in.

### Implementation

`visible_set(camera_polygon, cam_m9, apex_x, apex_y, screen_w, screen_h, max_depth, max_instances)` calls the native-engine query and returns one tuple for each image:

`(polygon, xform_m9, depth, clip_screen, walls, entry_edge, ents)`

- `clip_screen` — the screen-space clip region as `(x, y)` pairs.

- `walls` — segments as `(x1, y1, x2, y2, portal_flag)`.

- `entry_edge` — the edge the camera sees the image through, or `-1` at depth 0.

- `ents` — one tuple for each body: `(id, x, y, dx, dy, radius, fully_inside)`. All fields use screen values, with radius scaled by the transform.

The signed clip depth is the minimum inward distance from the middle to an edge plane of the convex clip. A value of zero is on an edge. A positive value is in all edge planes. A negative value is out of one or more edge planes.

The entity work has two parts. First, the image polygon list drops a body when its signed clip depth is below `-radius`. The `fully_inside` flag is `True` when `depth >= radius`. Second, the procedure moves each neighbor body through the portal into this polygon. It keeps the body only when `depth >= -radius` and depth is below zero.

Thus, the circle touches this clip while its center stays on the neighbor side. This procedure always sets `fully_inside` to `False`.

`cam_m9` maps camera-polygon coordinates into screen coordinates. The apex is in the local coordinates of `camera_polygon`. Only the width and height are screen-space values. The binding does not attach a `Space` to the apex pair. The caller must keep that relation correct.

The binding rejects only a camera polygon index that is out of range. The unsigned integer depth and instance limits reject negative Python values during argument conversion. Zero limits can return no images.

The engine supplies the image, clip-vertex, wall, and entity sequences. The binding keeps them and does not sort or remove duplicate entity tuples.

### Caveats

The neighbor part looks one portal deep. A body that extends through two portals in sequence is not added to the far image. The clip regions mask the defect in play. A body two portals out is out of the near clip region.

The binding checks only `camera_polygon`. It does not reject nonfinite matrices, apex values, or screen dimensions. Zero depth or instance limits can return no image. Negative Python depth or instance limits raise during unsigned-integer conversion before the method starts.

## `Sim.raycast` (`src/lib.rs`)

### Goal

A ray through the world, through portals, until a wall, an entity, or the length limit stops it.

### Invariants

- The start location and the direction must be in one space, or the call raises `FrameMismatch`.

- The mask selects entity groups: bit `n` selects group `n`. A body out of the mask does not stop the ray.

- The result holds two frames. It holds the hit location in the hit polygon space and a transform to the start space.

### Verification

A ray at a solid wall returns `kind == "wall"` with the polygon and the edge. A ray through a portal at a body returns `kind == "ent"` with `hops == 1`. A ray with a mask that does not include the group of a body goes through that body.

### Implementation

`raycast(from, dir, max_hops, max_len, mask, ignore=-1)` finds the start polygon from the coordinate space. It changes `dir` to unit length. A zero direction stays zero. A negative Python `max_hops` or `mask` does not complete unsigned integer argument conversion. The 16 mask bits select `group & 15`.

Each negative `ignore` value shows no ignored entity. A nonnegative unknown id agrees with no entity.

The length test uses `max_len - distance`. A nonpositive length returns `"none"` at the start, with the input length in `distance`. A nonfinite length is not rejected. A portal at the hop limit returns `"none"` at the portal point before a portal crossing. When an entity and a wall have the same positive distance, the entity test returns the entity first.

The code names the result transform `ray composition`. That transform maps the last polygon to the start polygon.

### Caveats

None.

## `Sim` — view queries (`src/lib.rs`)

### Goal

These are the view queries. `track_of` finds one body from the observer. `tracks_to` lists each different image of one body. `find_closest_faction_member_with_los` finds the nearest body of a faction after a raycast checks the sightline. All 3 queries return `Track` records in the observer space.

### Invariants

- The route for a view has the smallest route-length cost, not the smallest hop count. A route with the smallest hop count can bend where a straight line does not go. The raycast check then rejects a good sightline.

- The raycast check receives the same `max_hops` as the route walk.

- `track_of` and `find_closest_faction_member_with_los` record only views that a raycast checks. Thus no view goes through walls at each depth.

- `tracks_to` records geometry without a raycast check, shortest first. Two routes that put the body at one location are one image.

- One function, `sighting`, assembles each `Track`. Thus all queries record the same values for one view.

### Verification

For an observer and a target in one polygon, `track_of` returns a track with `portal_depth` 0 and equal `distance` and `path_distance`. For a target behind a wall in a neighbor polygon, `track_of` returns `None`. `tracks_to` in a portal loop returns at most `max_images` tracks, nearest first. `find_closest_faction_member_with_los` with `prefer` set keeps the held target while that target stays in view and in range.

### Implementation

`track_core(sim, observer, target, group, max_hops)` is the same middle procedure for these queries:

1. When the two bodies are in one polygon, the function returns the view without a test. A convex polygon has no wall between them. Depth is 0, and the two distances are equal.

2. When the two bodies are in two polygons: the shortest route from the target polygon to the observer polygon. The location, velocity, and direction of the target move along the route steps.

3. A raycast checks the target location after transport along the route. It starts at the observer with length `distance + 40`, mask `1 << group`, and the observer ignored. The ray must hit the target, or the result is `None`.

4. The route ends at the last portal. The segment from the middle of that portal to the observer adds to the path distance.

`track_of(observer, target, group, max_hops, tick=0)` checks the two ids and puts the `track_core` result in a `Track`. `tracks_to(observer, target, max_hops, max_images, tick=0)` walks routes in the two limits and transports the state along each route. Without the image limit, a portal-loop search could continue without end.

`find_closest_faction_member_with_los(observer, faction, max_hops, max_range, tick=0, prefer=0)`:

1. When `prefer` names an active body, the function returns it if a raycast checks a view in range. This keeps a held target. An attack does not turn to a body that is nearer for only one tick.

2. One outward walk from the observer collects the found polygons and their transforms into observer space.

3. Candidates are active bodies of the faction in the found polygons and at `max_range` or less in observer space. The nearest candidate comes first.

4. A candidate in the observer polygon drops when the segment to it goes across a terrain rectangle. The helper `segment_crosses_rect` is a `Liang-Barsky` segment test against an axis-aligned rectangle, the same procedure as `_segment_crosses_rect` in `sim.py`.

5. The first candidate accepted by `sighting` is returned. A clear sightline costs one ray, not one ray for each body in the level.

Candidates with equal squared distance keep the polygon sequence from the graph walk. They also keep the entity-list sequence in each polygon. The sort is stable. The code does not use entity id to select between equal distances.

### Caveats

- Defect: the two raycast-backed queries do not agree about terrain in one polygon. `find_closest_faction_member_with_los` rejects an ordinary candidate behind terrain in the same polygon. `track_of` at depth 0 does no terrain test and reports the target. Polygon convexity does not remove this terrain occlusion.

- The `prefer` path also uses `track_core` before the terrain check in one polygon. A selected target in that polygon can thus stay selected behind terrain. The ordinary candidate path rejects it.

- The mask of the raycast check holds only the group of the target. Bodies of other groups do not stop a sightline.

- Defect: the cross-polygon path calculates that mask as `1u16 << group`. A group of 16 or more can panic. The function does not return a Python error.

- A comment records a removed defect. The raycast check had a 3-hop limit while the route walk had a 12-hop limit. A straight sightline down 5 small polygons composed, and the ray then rejected it.

## `Sim` — routes (`src/lib.rs`)

### Goal

Topology data for AI shows which edge goes to a polygon and how many hops it is. It also shows which polygons are in a hop limit.

### Invariants

- `next_edge` and `hop_distance` return `-1` when no route is available.

- The two check the two polygon indices and raise `ValueError` for an index out of range.

### Verification

For two polygons with one portal between them, `next_edge(a, b)` returns the portal edge of `a`, and `hop_distance(a, b)` returns 1. `polygons_within(r, 0)` returns `[r]`.

### Implementation

The 3 methods call the route cache (`Router`) or the native-engine walk:

- `next_edge(from_polygon, to_polygon)` — the edge of the first hop, or `-1`.

- `hop_distance(a, b)` — the hop count, or `-1`.

- `polygons_within(polygon, hops)` — the polygon indices in the limit.

`polygons_within` uses `BFS` portal sequence. It starts with the given polygon. It then adds each polygon that it finds by hop depth and by edge sequence in the active frontier. It returns each polygon at most once.

### Caveats

The route cache lives in the `Sim` object, and `next_edge` and `hop_distance` receive `&mut self`. The cache fills with caller requests.

## `Raster` (`src/lib.rs`)

### Goal

`Raster` is the Python interface to the CPU rasterizer, with pixel parity against the `pygame` render. `PERIHELION` sends one display list for each frame, and the engine fills pixels without the GIL.

### Invariants

- The side lengths stay in `1..=16384`, or construction raises `ValueError`.

- `draw` and `draw_blob` run with the GIL released.

- `finish` and `finish_into` return the same composed frame until the next `begin`.

- `finish_into` does not accept a read-only buffer, and does not accept a buffer with a dimension other than `width * height * 4`.

### Verification

`Raster(0, 5)` raises. After `begin`, `draw` of a stream, and `finish`, the result is `width * height * 4` bytes. A second `finish` without `begin` returns equal bytes. `finish_into` with a short buffer raises and writes no byte.

### Implementation

The frame cycle:

- `begin(bg_rgba=0x000000FF)` — clears the world layer to the color and empties the entity and coverage layers. It also clears the clip table, the transform table, and the overlay queue.

- `draw(cmds, coords)` — runs a command stream. `cmds` is a `u32` buffer of headers, 6 values each. `coords` is an `f32` buffer of payload points.

- `draw_blob(cmds, coords, xform_idx, clip_idx)` — runs the same byte blob more than once. It replaces the clip and transform of each command. This is the cached path for polygon data.

Each command header has 6 `u32` values: `(op, flags, clip, xform, rgba, n)`. Operation values 0 through 10 select polygon fill, polygon outline, polyline, filled circle, circle outline, and filled rectangle. The remaining operations are rectangle outline, glow, clip fill, texture fill, and decal replay. Values 0, 1, and 2 in the low 2 flag bits select the world, entity, and overlay layers. Value 3 raises `ValueError` for operations 0 through 9.

Decal replay uses a different path and does not read the flags.

Bits 2 and 3 select no clip, geometry clip, portal-gate clip, or rectangle clip. Bit 4 closes a polyline. Bit 5 scales a radius through the transform. Bits 8 through 15 hold the line width. The value `0xFFFFFFFF` shows that no clip or transform table entry applies.

For polygon operations, `n` is the point count and the payload has `2*n` floats. A circle or glow payload has `(cx, cy, radius)`. A rectangle payload has `(x, y, width, height)`. Clip fill and decal replay have no payload. Texture fill has the 2-float local texture origin.

The `rgba` value is the color, but texture fill uses it as the texture id. Decal replay uses it as the decal-list id. The raster rejects an unknown operation, a header or payload that is not complete, and an incorrect table index. It also rejects a command when its table or payload does not agree with the operation requirements.

`draw_blob` reads 4-byte values in native byte sequence. It rejects one of the two byte buffers when its length is not divisible by 4. After it replaces each clip and transform field, it uses the same command validation as `draw`.

- `finish()` — runs the composition sequence below and returns straight RGBA8 bytes.

- `finish_into(out)` — writes the same bytes into a caller buffer, for one `bytearray` that `PERIHELION` keeps. No new memory for each frame.

After a finish method composes a frame, `draw` and `draw_blob` raise `ValueError` until `begin` starts a new frame. More finish calls return the cached composition.

The normal composition sequence first multiplies only the world RGB by the lightmap when the lightmap is on. Each channel becomes `(color * light + 255) >> 8`. It then copies an entity RGB pixel on the world. This occurs only when entity alpha and the coverage byte are 255. It replays overlays in input sequence. A glow overlay adds RGB with saturation.

Each other overlay sets RGBA.

When one or more `mark_otherworld` regions are marked, the first lightmap multiply does not run. The entity copy and overlays run first. The last step selects a light field for each pixel. Pixels that are not in a marked region use the lightmap. A pixel in a region uses its `mix` byte to linearly mix the lightmap with the opposite cold field.

A subsequently marked region replaces the previous mix in their overlap. The selected field then multiplies the full composed RGB with `(color * field + 255) >> 8`. Thus, this mode can also zero entity and overlay RGB channels.

The scene tables:

- `add_clip(pts, coverage=True)` — adds a screen-space clip region from pairs or one flat list and returns its index. With `coverage`, the region also fills the entity coverage mask. The count in a flat list must be divisible by 2. The region must have 3 or more points, and each point must be finite. An error in each condition raises `ValueError`.

The call does not check convexity, vertex sequence, duplicate points, self-intersection, or zero area. It keeps such geometry, and the fill and clip procedures set the result.

- `add_xform(m9)` — adds a transform and returns its index.

- `set_texture(id, w, h, data)` — copies an RGB8 floor image that stays across frames.

- `set_decal_shape(id, pts)` — adds a decal shape.

- `set_decals(list_id, records)` — copies the kept decal records of one polygon. Each record has these 12 floats: `style`, `x`, `y`, `size`, `angle`, `squash`, `eff_mul`, `r`, `g`, `b`, `shape_id`, and `rot`.

Decal replay transforms `(x, y)` to the screen and drops a record when its middle is not in the clip polygon. It does not clip the remaining decal. The screen dimension is `size` times the transform scale, or one pixel if that result is lower. The integer RGB fields set an opaque color. When `rot` is not zero, the transformed direction supplies the screen angle.

When `rot` is zero, the screen angle is zero.

Style 0 fills the shape that `shape_id` selects. Style 2 renders that shape as a polyline with a width of 1 pixel. For these two styles, `eff_mul` multiplies the screen dimension. The `squash` value multiplies each local vertical coordinate. If `shape_id` does not identify a decal shape, that record renders no mark.

Style 1 renders a circle outline with a width of 1 pixel. Its radius is the truncated screen dimension, or 2 if that value is lower. It does not use `angle`, `squash`, `eff_mul`, `shape_id`, or `rot`. Each other style raises `ValueError`.

The `set_texture` byte count must equal `w*h*3`, and its dimensions must be positive. The `set_lightmap` byte count must equal `width*height*3`. The `lightmap_add_region` byte count must equal `rw*rh*3`, and the region must fit in the raster. `set_decal_shape` must have one or more coordinate pairs. The `set_decals` float count must be divisible by 12.

Each failure raises `ValueError`.

- `mark_otherworld(clip_idx, mix=1.0)` — marks an image as an `Otherworld` polygon. It clamps a finite mix to `[0, 1]` and changes it to one byte. A NaN mix is not rejected. Rust changes that float to integer byte 0. During the last composition step, that byte mixes the normal and cold light fields.

The light path:

- `set_darkness(on)` — turns the lightmap multiply on or off.

- `set_lightmap(data)` — copies the RGB8 lightmap of the frame at the raster dimension — the only light when the lightmap is on.

- `add_light(cx, cy, radius, tint_r, tint_g, tint_b, polys, poly_lens, shadows, shadow_lens)` — adds one world light. `polys` and `shadows` are flat coordinate lists. Their length lists give the point count of each polygon. The call fills the union of the light polygons and removes the shadow polygons. It applies radial falloff and RGB tint. It also checks that the length totals agree with the coordinate lists.

- `lightmap_add_region(x0, y0, rw, rh, data)` — adds an RGB8 region into the lightmap — the path for glows that move.

- `lightmap_bytes()` — reads the lightmap for parity tests.

- `apply_post(frame, passes)` — runs color operations in input sequence on a full RGBA `bytearray`. For an operation without a field, `ap=min(alpha,255)`. Each RGB channel becomes `(source*ap + destination*(255-ap) + 127)/255`. Alpha does not change.

For a field operation, the raster calculates and caches one edge table. For pixel `(x,y)`, it calculates normalized coordinates from the frame center, then `distance=sqrt(nx*nx+ny*ny)`. The table byte is `truncate(clamp((distance-0.20)/0.85,0,1)*190)`. Applied alpha is `table_byte*alpha/255` without a clamp to 255. A sufficiently large input alpha can make `255-applied_alpha` underflow in a debug build or wrap in a release build.

The frame byte count must equal `width*height*4`.

Two helpers check buffer input. `typed_buffer` requests `pyo3` for a buffer of the correct element type and copies it into a vector. Thus, `draw` must have `u32` elements for commands and `f32` elements for coordinates. The buffer protocol controls dimension, contiguity, format, and alignment errors before the raster runs. If an object has Python length zero, the helper returns an empty vector before it requests a typed buffer.

`blob_words` accepts a byte buffer that `PyBuffer<u8>` can copy. Its byte length must be divisible by 4. It reads each value in native byte sequence and copies it. Thus source alignment has no effect. `finish_into` must have a writable `u8` buffer with an item count equal to the frame byte count. The texture and lightmap methods also must have `u8` buffers and copy their bytes.

### Caveats

- `finish` and `finish_into` call native-engine composition twice. The first call composes the frame without the GIL. The second call copies the composed frame to Python. The native engine keeps the composed frame, thus the second call does no more composition.

- `apply_post` uses an `unsafe` slice of the `bytearray`. No Python code runs while the slice lives, thus the buffer cannot change dimension in that time.

- Defect: a field effect does not clamp its applied alpha. A sufficiently large input alpha can underflow in a debug build or wrap in a release build. The function does not return a specified blend.

- An empty command stream is a frame with no operation, not an error.

## `SignalField` (`src/lib.rs`)

### Goal

The Python face of the signal system of the engine, with 9 fields. Signals go into polygons, flow along the adjacency, decrease tick by tick, and drain. The typed layer is `game/perihelion/signals.py`, and the one implementation is in the native engine.

### Invariants

- Signal types go across the boundary as integers: the position of the type in the engine list.

- The field count is always 9. `sample_all` and `totals` return 9 values.

- Native-engine errors become `ValueError` with the native-engine message.

### Verification

Call `emit(kind, polygon, amount, tick)` with a correct type, polygon, positive quantity, and nondecreasing tick. Then `sample(kind, polygon, tick)` returns a value above zero. `sample`, `emit`, `emit_at_least`, `totals`, and `drain` can materialize a cell. They return `ValueError` when the tick is before that cell's kept tick. `step_to` is different: a tick before `last_spread` returns without error and does not change the field.

### Implementation

`SignalField(tick=0)` starts with empty storage and uses that tick as the last spread tick. `set_adjacency(adj)` replaces the neighbor lists. The outer list length is the active adjacency length. Storage becomes larger when the list is longer, but does not become smaller for a shorter list. Previous cell values stay after a shorter list.

The call keeps neighbor sequence, duplicate entries, and connections from a polygon to the same polygon index. It also keeps connections that go in only one direction. Python conversion rejects a negative neighbor index. A neighbor index above the available storage can panic during spread.

`emit(kind, polygon, amount, tick)` returns without work for a nonpositive quantity or an unknown polygon. This return also bypasses type and time checks. For a positive quantity and known polygon, it materializes the cell at `tick`. It adds the value and marks the polygon as used. Materialization raises when `tick` is before the kept cell tick. A type not in 0 through 8 can panic before the function returns an error.

`emit_many(kind, polygons, amount, tick)` returns without work for a nonpositive quantity. For a positive quantity, it calls `emit` in input sequence and stops at the first error or panic. Previous additions stay. `emit_at_least(kind, polygon, level, tick)` returns without work for an unknown polygon. For a known polygon, it samples at `tick`.

It keeps `level` only when the sampled value is lower. It does not change the cell tick. Thus the next materialization decays the new level from the previous tick. A nonfinite `level` follows floating-point comparison.

`sample(kind, polygon, tick)` calculates and returns the decayed value directly from the elapsed time. It raises for an unknown polygon or a tick before the kept cell tick. An incorrect type can panic. `sample_all` does this for types 0 through 8 and stops at the first error. `totals` examines types 0 through 8, then used polygons in index sequence from low to high. It raises at the first cell with a kept tick after the requested tick.

Types 0 through 8 have `(half-life in seconds, spread rate, hop gain)` values `(45, 0.12, 1)`, `(180, 0, 1)`, `(3, 1.20, 1)`, `(12, 0, 1)`, `(60, 0, 1)`, `(1, 1.8, 0.35)`, `(1.5, 0.9, 1)`, `(2, 0.7, 1)`, and `(8, 0.45, 1)`. Decay uses 60 ticks each second. A value kept at tick `a` becomes `value * 0.5 ** ((b-a) / (half_life * 60))` when the field calculates it at tick `b`. Values below `1e-5` become zero.

`step_to(tick)` runs spread in 15-tick parts until the last spread tick is less than 15 ticks behind the requested tick. A request before the last spread tick returns without work and without an error. At the start of a part, the field materializes each used polygon and its neighbors at the part tick. Polygon sequence goes from low to high. A type with a zero spread rate only decays.

For each type with a spread rate, the fraction for each neighbor is `min(rate * 15 / 60, 0.45)`. For each entry, a polygon with `degree` entries sends `value * min(fraction * degree, 0.9) / degree`. Duplicate entries and entries for the source polygon thus count more than once.

The calculation uses one copy of all source values. It then subtracts all sent values and adds each received value times the hop gain. A polygon with no neighbor sends no value. Types with a zero spread rate only decay.

Type 6 uses the same send calculation. When two or more different neighbors supply one polygon in a part, their full sum stays type 6. When one neighbor supplies it, the full sum becomes type 7. The received values change the field after removal of the sent type 6 values. Polygon sequence is from low to high.

Neighbor sequence is the sequence from `set_adjacency`.

`deposit_doorway_trail(polygon, edge, amount, tick)` does no work for a nonpositive value. For a positive value, it samples that key at `tick`, adds the value, limits the result to 8, and keeps `tick`. It does not check the polygon or edge. A tick before the kept tick increases the sampled value before the limit applies. `doorway_trail` returns zero for a missing key and applies a 660-tick half-life to a known key.

It also accepts a tick before the kept tick and can return more than the kept value.

`drain(polygon_weights, capacity, tick)` sorts input pairs by polygon index. It ignores unknown polygons and nonpositive weights. Duplicate polygon entries stay duplicate. For each pair, it samples signal types 0 through 8 in that sequence. It calculates `weighted = sum(value * weight)`.

For a positive weighted sum and capacity, its scale is `min(capacity / weighted, 1)`. It then subtracts `value * weight * scale` from each listed cell in pool sequence, with a zero lower limit. Duplicate entries use values sampled before removal but subtract in sequence. The return value is the sum of requested cuts. It can be more than the value left in a duplicate cell.

### Caveats

- Defect: `step_to` with a tick before the last spread tick returns without an error. The other signal operations that check time return an error.

- Defect: a signal type not in 0 through 8 can use an index above the internal array limit and panic. It does not return `ValueError`. An adjacency list with a polygon index above its storage limit can also panic during spread.

- Defect: after `set_adjacency` replaces a larger adjacency with a shorter one, previous nonzero cells stay in storage. A subsequent spread can index the shorter adjacency with one of those previous polygon indexes and panic.

- `doorway_trail` accepts a tick before its kept tick. The negative time interval increases the returned value above the kept value.

## `AudioMixer` (`src/platform.rs`)

### Goal

`AudioMixer` replaces `pygame.mixer` for audio output. It sends stereo samples to one `cpal` stream at 44100 Hz. The channel model does the `pygame` operations used by `PERIHELION`. Numbered channels let `PERIHELION` play, queue, set volume, stop, fade out, and read state. The SFX pool is different and has no channel numbers.

When no device works, the mixer plays no sound. This agrees with the `pygame.mixer.init` failure path.

### Invariants

- All sounds are raw stereo `f32` at 44100 Hz, with sample pairs in one sequence. Python copies the sounds and reads and decodes the files.

- The SFX pool holds at most 24 voices. When it is full, a new sound can have a higher gain sum. That sound replaces the voice with the lowest gain sum. The mixer drops a new sound with a lower gain sum.

- `ch_queue` starts the sound immediately when the channel is idle or unknown. This agrees with the `pygame` operations that `PERIHELION` uses.

- A finite master volume clamps to `[0, 1]`, and each finite mixed output sample clamps to `[-1, 1]`. Voice and channel volumes do not clamp.

- The mix runs on the audio thread with one state lock. Each control call also uses that lock.

### Verification

`ready` is `True` only when the default device accepts a stream with 2 channels at 44100 Hz and that stream starts. `load_sound` raises `ValueError` when the byte count is not divisible by 8. After 24 `sfx_play` calls, an additional call with a higher gain sum returns `True` and `sfx_active()` stays 24. A subsequent call with a lower gain sum returns `False`. `sfx_stats()` returns the `(played, stolen, dropped)` counts.

`ch_queue` on a stopped channel causes `ch_busy` to return `True`.

### Implementation

Construction opens the default output device with two channels at 44100 Hz. There can be no device, or stream construction or start can fail. Then the mixer keeps no stream and `ready` is `False`. The callback locks the state and mixes the samples.

For kept sounds, `load_sound(id, data)` parses `little-endian` `f32` pairs, and `free_sound(id)` removes one sound.

If an id is known, `load_sound` replaces its sample buffer. A voice that holds the previous buffer continues to use it. `free_sound` removes only the kept id, while active voices continue. A call with an unknown id has no effect.

`sfx_play` returns `False` for an unknown id and does not change a counter. `ch_play` and `ch_queue` do no work for an unknown id. Channel numbers have no set limit. A control call can add a new idle channel record.

`sfx_play(id, lvol, rvol)` reports if the SFX pool gave the sound a voice. The pool limit is 24. The priority value is the floating-point sum `lvol + rvol`. When the pool is full, a comparison selects the first voice with the smallest value. The call removes that voice unless the new sum is less than or equal to the selected sum.

Thus, a new NaN sum is not less than or equal to the selected value and removes the selected voice. The code does not check negative and nonfinite volume values.

The limit follows a measurement at the highest sound load, when `PERIHELION` sends about 27 audible sounds each second. With 12 voices, the pool played sounds for only 28 percent of enemy removals.

Voice selection is not the same as `pygame`, which dropped the new sound. This mixer keeps the event with the higher gain sum and does not always keep the first event. Tests can read the pool state through `sfx_active()` and `sfx_stats()`. The event callback in `PERIHELION` fires before the pool selects a voice. Thus only these counts identify the sounds that a player heard.

The channels: `ch_play(ch, id, loops=0)` starts a sound, and `loops` of `-1` plays it continuously. `ch_queue(ch, id)` sets the next chunk, or starts it immediately on an idle channel. `ch_has_queue`, `ch_set_volume(ch, l, r)`, `ch_stop`, `ch_fadeout(ch, ms)`, and `ch_busy` complete the model. `set_master(v)` and `stop_all()` apply to all channels and voices.

A positive `loops` value is the number of plays after the first play. Each negative value plays continuously, not only `-1`. SFX and channel volume values do not clamp. The last mixed sample value is clamped from -1 through 1 as a floating-point value. A NaN input stays NaN through output conversion.

`ch_fadeout` receives an unsigned integer ms value. Python rejects a negative value before the method starts. Zero ms uses a fade of one frame. `stop_all` does not set channel volumes, kept sounds, or SFX statistics to their initial values.

In the mix, SFX voices add at their voice volumes. Each channel plays its chunk at the channel volume, with a linear fade factor during fadeout. At a chunk end, the queued chunk can start with no silence. If no queued chunk starts, the chunk plays again as selected by `loops`, or the channel stops. When its fade factor is zero, fadeout clears the active and queued chunks. The fade factor is multiplied last, and then the clamp applies.

### Caveats

- Defect: a sound with no samples on a numbered channel with `loops != 0` causes the mix callback to loop without end. The audio thread does not return from the callback, and audio stops. `load_sound` accepts an empty buffer. This state can occur.

- The stream config is set at 44100 Hz. A device that does not accept that rate gives a mixer with no output, not a rate change.

- If the mixer replaces an active voice, it cuts the sample without a fade. This can cause a click.

- A queued chunk starts at full voice volume, and the channel volume applies on top of it.

- The SFX statistics start at zero during mixer construction and include its complete lifetime. No method sets them to zero again.

## `Window` (`src/platform.rs`)

### Goal

`Window` replaces the `pygame` display. Python collects events from its loop. The window centers the internal frame at an integer scale, with RGB `(0, 0, 0)` around it. Pointer coordinates map to internal pixels before Python receives the events.

### Invariants

- The first `pump` call calls the `winit` window constructor. The Python object constructor does not call it.

- `present` uses the largest integer scale that fits, with a lower limit of 1, and centers the image.

- Pointer events map through the scale and the corner offset of the last `present`.

- The key `name` field contains the `winit` debug text, for example `KeyW`. The same text after a library change or on a different platform is not specified.

### Verification

A `pump` after the user pushes a key returns a tuple with type 1, the key name, and the `repeat` flag. With a `640x360` internal frame in a `1920x1080` window, a click at the window middle maps to about `(320, 180)`. `present` with a byte count that is not `w * h * 4` raises `ValueError`.

### Implementation

`Window(width, height, title="PERIHELION", fullscreen=False)` assembles the `winit` event loop and keeps the initial values. `width` and `height` are the requested initial pixel dimensions of the inner window area. They do not set the dimensions of the internal render frame. The first `pump` calls the `winit` window constructor, in borderless fullscreen when requested.

`pump()` runs the event collection with a zero wait and returns the collected tuples `(kind, a, b, c, name, text)`:

- 0 — close request.

- 1 — key down. `a` is the `repeat` flag, `name` is the `winit` key, and `text` is the typed text.

- 2 — key up.

- 3 — pointer movement. `a` and `b` contain the mapped position.

- 4 and 5 — button down and button up. `a` is the button. `b` and `c` contain the mapped position.

- 6 — `MouseWheel`. `a` and `b` are its two steps.

- 7 — resize. `a` and `b` are the new dimension.

Each integer field with no event data is 0, and each text field with no event data is an empty string. Key down and key up put the `repeat` code in `a`. They put the `winit` key name in `name` and input text in `text`. Movement puts mapped `x` and `y` in `a` and `b`. The two button events put the button in `a` and mapped coordinates in `b` and `c`. A line delta from `MouseWheel` truncates each floating-point line value to zero.

A pixel delta from `MouseWheel` becomes only `-1`, 0, or 1 for each axis.

The button codes are 1 for left, 2 for middle, 3 for right, 6 for back, and 7 for forward. For `winit::MouseButton::Other(n)`, the code is `8 + n`. Thus, `Other(0)` gives 8 and `Other(1)` gives 9. The map subtracts the corner offset and uses Rust `div_euclid` integer division by the scale. It does not clamp the result.

A point above or to the left of the image can give a negative coordinate. A resize event does not change this map. The next correct `present` updates it.

`present(rgb, w, h, shake_x=0, shake_y=0)` checks the byte count. On its first call, it assembles the `softbuffer` surface. It changes the surface dimensions to the window dimensions and selects the scale. A zero `w` or `h` can go through the byte-count check for an empty buffer. It then causes integer division by zero.

Screen shake moves the corner offset in scaled window pixels. The clamp keeps the frame on the surface. The copy loop writes each source pixel `scale` times in each direction and ignores the alpha byte. `set_title` and `set_fullscreen` update the window.

Before the first `pump`, `set_title` and `set_fullscreen` have no effect. They do not change the values used for initial window construction. After construction, `set_fullscreen(True)` selects borderless fullscreen on the default monitor. `set_fullscreen(False)` returns to windowed mode. A close request only emits an event. The binding does not remove the window or stop subsequent `pump` calls.

### Caveats

- Defect: the window constructor uses Rust `expect`. If the `winit` constructor fails during `pump`, the binding panics instead of returning `ValueError`.

- Defect: `present` accepts zero `w` or `h` when the byte buffer is empty. It then divides by zero when it selects the scale. The method panics and does not return `ValueError`.

- Defect: a `MouseWheel` event with a line step below 1 becomes 0. `PERIHELION` does not receive small steps from a touch device. Pixel steps keep only their sign.

- `present` before the first `pump` returns without work, because no window is there. The frame drops with no record.

- Events from `pump` before the first `present` map pointer positions with scale 1 and offset 0 — raw window pixels.

- A window smaller than the internal frame uses scale 1, and the right and bottom of the frame are not shown.

- The binding does not change or freeze the `winit` key debug text.

## `write_png` (`src/platform.rs`)

### Goal

Write one RGB frame to one PNG file. The encode and file input and output release the GIL. Other Python threads can run, but the caller waits until the write is complete.

### Invariants

- The byte count must equal `w * h * 3`, or the call raises `ValueError`.

- The encode and the file write run with the GIL released.

### Verification

`write_png(path, w, h, rgb)` writes a file that an image program opens with the given dimensions. An incorrect byte count raises and writes no file.

### Implementation

The function checks the dimensions, releases the GIL, calls `File::create`, and encodes 8-bit RGB through the `png` crate. Each failure becomes `ValueError` with the cause.

### Caveats

The dimension check occurs before the `File::create` call. An available output file stays the same after a dimension error. After `File::create`, an encode or write failure can truncate an available output file. It can also replace only part of that file.

The GIL release starts no asynchronous task. A call from the primary loop adds its encode and file-write time to that loop iteration.

## `VideoRecorder` (`src/video.rs`)

### Goal

`VideoRecorder` encodes a complete video in the engine: frames in, one `.mp4` file that a video program can play out. Previously, a recording used more than 1000 PNG files and an `ffmpeg` operation after recording. Without that operation, the result was a directory of frames, not a file that a video program can play. The recorder has no clock. The caller sets the time for each frame, and the record path uses the simulation clock.

### Invariants

- `width` and `height` must be positive and divisible by 2, `fps` must be positive, and `profile` must be `"hq"` or `"telemetry"`.

- Frames go through `x264` to a temporary Annex B file. During `finish`, the binding reads that file and builds the MP4 bytes in memory. It then calls `File::create` for the destination and writes those bytes. If a recorder drops without `finish`, it writes no MP4. Exit from a `with` block calls `finish` when the body raised an exception too.

- `finish` does not write when the encoder packet count is not equal to the frame count. A clip that drops one frame moves each subsequent event back in time.

- A profile sets only quality and audio bitrate. The caller supplies the resolution and frame rate. The encode is lossy. The recorder does not change frame dimensions or the selected rate without a report.

- More than one `finish` call is safe, and `__exit__` calls `finish`.

### Verification

A recorder given 100 frames writes an `.mp4` with 100 samples in the video track at the given rate. A player opens the file. `VideoRecorder(path, 641, 480)` raises. `add_frame` after `finish` raises. When `set_audio` receives PCM with one or more samples, the file contains an AAC track for the full PCM duration.

### Implementation

`VideoRecorder(path, width, height, fps=60, profile="hq")` checks the values and opens an `H264Encoder`. The raw stream goes to the path with the extension `h264.tmp`. The profiles:

- `"hq"` — CRF 18, preset `veryfast`, audio at `128 kbit/s`. This profile is for clips that a person views.

- `"telemetry"` — CRF 30, preset `veryfast`, audio at `48 kbit/s`. At `854x480` and 20 frames each second, the measured rate is 14 times playback speed and `0.4 MB` in 60 seconds. The audio bitrate is important because sound at `128 kbit/s` uses more bytes than the image.

`add_frame(rgb)` checks for `width * height * 3` bytes and encodes with the GIL released. `set_audio(pcm, sample_rate=44100, channels=2)` supplies the full clip audio as 16-bit little-endian PCM, with channels in one sequence. It supplies a complete buffer, not a stream, because AAC encoding runs once at write time. `set_sidecar(name, data)` attaches a named blob, replaces a blob with the same name, and limits the name to 255 bytes.

`set_audio` accepts only 1 or 2 channels, a positive sample rate, and a byte count divisible by `2*channels`. A subsequent call replaces the complete previous PCM buffer, rate, and channel count. It can run after `finish`, but that data cannot be written because a subsequent `finish` returns immediately. The recorder does not cut or extend audio to the video duration. Thus, the audio track can be shorter or longer than the video track.

It writes the full PCM duration and fills only the last AAC unit with silence.

A sidecar name is a Python string encoded as UTF-8. Its UTF-8 byte length must be from 1 through 255. An empty or longer name raises `ValueError`. A new blob for a name removes the previous entry. It puts the new blob at the end of the write sequence.

`finish` closes the encoder, collects the packets, and checks the packet count against the frame count. With the GIL released, it then does these steps:

1. It assembles the video track, with `fps` as the clock rate and 1 tick for each sample.

2. When PCM is there, it encodes the AAC track and adds it.

3. It writes the MP4 bytes and attaches each sidecar as a `uuid` box at the top level.

4. It calls `create_dir_all` for the directory that holds the file and writes the file.

`__enter__` returns the same recorder. `__exit__` calls `finish` when the body of the `with` block raised an exception too. It returns `False`. The body error stays active. If `finish` also raises, its error replaces the active body error as specified for a Python `with` block.

The AAC path controls the `fdk-AAC` encoder from `minimp4`, not the `minimp4` muxer. That muxer only attaches audio to its H.264 stream. The transport is raw, without `ADTS` headers. MP4 keeps codec data in the sample entry. `ADTS` in MP4 plays as noise in some video programs. The stream encodes units of 1024 samples, and silence fills the last unit.

### Caveats

- Defect: the module comment tells that the codec is AV1 through `rav1e` and points at `av1.rs`. The code encodes H.264 through `x264`, and the crate holds no `av1.rs`. The correct measurements are in the `h264.rs` comment.

- Defect: after a `finish` failure, `open` stays `false`. A second `finish` call returns without an error and writes no file.

- Defect: a recorder with zero frames goes through the packet-count check. It writes a video track with no samples and an empty decoder configuration. Some video programs cannot open this file. Thus it does not produce the playable file promised by the goal.

- Defect: the constructor accepts dimensions divisible by 2 and above 65535, but `finish` changes each dimension to `u16` for the MP4 track. A larger value wraps. Thus the track metadata is not the same as the encoded frame.

- Defect: `create_dir_all` is called only during the MP4 write. `x264` opens the temporary `.h264.tmp` path before that directory is available. Thus the encode can fail for a destination in a new directory.

- Defect: the destination write is not atomic. `File::create` truncates an available file before `write_all` and `flush`. A `write_all` or `flush` failure can keep a file that is not fully written.

- Defect: `finish` removes the temporary raw stream only after a correct read. An encoder failure or raw-file read failure can keep the `.h264.tmp` file on disk.

- The wait for the `x264` process has no timeout. A process that does not exit can block `finish` or the drop of an encoder that did not finish.

- The silence fill extends the audio track by at most 1023 samples, about 23 ms at 44100 Hz.

- Two recorder objects with the same path use one `.h264.tmp` file and can damage each other's output.

- Memory use increases with the clip duration: all packets, the PCM, and the sidecars stay in memory until `finish`.

## `H264Encoder` (`src/h264.rs`)

### Goal

Encode H.264 by a pipe that sends frames to the `x264` program in a different process. The source uses the process, not a library connection, as its GPL boundary. This section records only the architecture. Distribution is out of scope.

### Invariants

- Chroma stays at full resolution (`4:4:4`) from input to output. Measurements showed that this was faster than `4:2:0`. It is also the only method that keeps a color line with one pixel of width. This occurs on areas with RGB channels near zero. This line is part of the `PERIHELION` visual result.

- The stream has no `B-frames`. `ctts` timing data is necessary for frames in a different sequence, and the raw stream cannot contain this data. A telemetry recorder that changes frame sequence breaks the property that it must keep the time of each event.

- `--keyint fps*2` limits the maximum keyframe interval to two seconds. `x264` can add keyframes before that interval ends.

- The frame geometry and rate travel in the `y4m` header with the data. They do not travel as flags that can be different from the data.

### Verification

`H264Encoder` with an unknown preset raises. On a system without `x264`, construction raises with a message that names the GPL boundary. For a clip with one or more frames from the selected `x264` path, `finish` returns one packet for each frame. The first packet is a keyframe.

### Implementation

Construction checks the preset against the 10 `x264` preset names and starts `x264 --demuxer y4m --output-csp i444 --preset P --crf N --keyint fps*2 --bframes 0 --log-level none -o RAW -`. The `--output-csp i444` flag is necessary. Without it, `x264` tries to change the data to `4:2:0`. `swscale` is necessary for this change. A build without `swscale` stops and breaks the pipe. The `y4m` header contains `C444`.

`encode(rgb)` checks the dimensions and changes RGB to YUV with `BT.601` weights across the complete channel range. All 3 planes keep the full dimensions. It writes `FRAME\n` and the 3 planes to the pipe. The plane buffers stay in memory across calls.

`finish` closes the pipe, which tells `x264` to write its last data and exit. It waits and rejects an exit code other than zero. It reads and removes the raw Annex B file, then returns `split_annex_b` of the bytes. The drop path closes the pipe, waits, and removes the raw file. Thus a dropped encoder keeps no `x264` process or raw file.

### Caveats

- The color conversion writes values across the complete channel range, and the stream contains no range field for the color channels. A video program that applies the limited range displays changed image levels.

- `encode` waits on the pipe when `x264` stops. The GIL is released during the call. Python threads continue while the caller's frame loop waits.

- The raw Annex B stream goes to disk before the MP4 write. Maximum disk use is approximately two clips.

## `split_annex_b` (`src/h264.rs`)

### Goal

Divide an Annex B stream into MP4 samples and assemble the decoder configuration record (`avcC`). MP4 contains no start codes. Each sample contains NAL units with length prefixes. The parameter sets move to the sample entry, not the sample stream.

### Invariants

- One output packet contains one frame. Thus the packet count equals the frame count.

- The SPS and PPS move from the stream into the `avcC` record.

- A packet with an IDR unit is marked as a keyframe.

### Verification

The frame-count check in `VideoRecorder` agrees with `x264` output, with the `SEI` unit before the first IDR included. A written clip has correct colors in a video program that decodes `4:4:4`.

### Implementation

The function finds the 3-byte and 4-byte start codes, collects the NAL units, and then groups them:

- Type 7 (SPS) and type 8 (PPS) go to the config record and are not in the sample stream.

- The function drops type 9 because MP4 does not contain it.

- Types 1 and 5 each start a frame. A frame-start NAL closes the open packet only when that packet contains a frame. Without this check, the `SEI` before the first IDR closes an empty packet. It adds an extra sample to the clip.

- Each kept NAL attaches to the packet as a 4-byte length plus the bytes.

The `avcC` record uses the SPS version, profile, `profile_compatibility`, and level bytes. It also contains 4-byte NAL lengths, one SPS, and one PPS. For the high profiles (100, 110, 122, 244), it adds chroma format 3, zero more bits of depth, and zero SPS extensions. Without these fields, some video programs read the chroma as `4:2:0` and display it incorrectly.

### Caveats

- Only the last SPS and PPS in the stream stay in the result. One `x264` run with one value set has only that pair.

- An empty input gives zero packets and an empty `avcC` record. A recorder with zero frames writes a file with an empty config record.

## MP4 writer (`src/mp4.rs`)

### Goal

A small ISO-BMFF writer contains the parts necessary for H.264 or AV1 video and AAC audio. `VideoRecorder` supplies only H.264. This writer is necessary because `minimp4` has no `av01` sample entry and this crate writes ISO-BMFF sidecar boxes too.

### Invariants

- The box sequence is `ftyp`, `mdat`, `moov`, with sample data before the tables that reference it. Each offset is known when the tables are assembled, and no value is patched after a write.

- The samples of each track use one chunk. This layout is not applicable to a network stream but is correct for a local clip.

- Chunk offsets use 64-bit values (`co64`). A long recording can push the tables above `4 GiB`, where a 32-bit table can overflow without an error.

- The sync table (`stss`) is included only when some samples are not sync points. No table means all samples are sync points. This is correct for audio and a video track in which all frames are keyframes.

### Verification

A written file opens in most video programs. The video track contains one sample for each packet, with the given clock rate and tick step. A file with audio contains an `mp4a` track. Its `esds` names AAC.

### Implementation

`write(tracks)` assembles the file. `ftyp` contains `isom` and the codec name from the first video track. `mdat` contains the samples of each track in sequence, and the writer records each track's start offset. `moov` contains `mvhd` at clock rate 1000 with the longest track duration, followed by one `trak` for each track.

The internal `TrackKind::Video` value can name H.264 or AV1 and hold one of the two codec configurations. The Python module has no AV1 encoder, and `VideoRecorder` always uses H.264. Thus AV1 has no Python input path in this crate.

Each `trak` holds these boxes:

- `tkhd` — the on flags, the audio volume, and the `16.16` width and height.

- `mdhd` — the track clock rate.

- `hdlr` — `vide` or `soun`.

- `minf` — the media header, a `dref` that points at this file, and the sample tables.

In the sample tables, `stsd` contains the codec sample entry. It uses `avc1` or `av01` with the config box, or `mp4a` with the `esds` chain. `stts` is one run at the constant tick step, and `stss` is included when necessary. `stsc` gives one chunk, `stsz` contains one byte count for each sample, and `co64` contains the chunk offset.

The `esds` chain identifies `MPEG-4` audio, an audio stream, zero given bitrates, and the AAC codec bytes. Each level uses a 4-byte length field. The audio sample entry writes the rate as a `16.16 fixed-point` value in a 16-bit field. The limit is 65535. Video programs read the `mdhd` clock rate for higher rates.

The `bx` helper wraps each body from the smallest inner box outward. Thus no box length is written twice or patched.

### Caveats

- Defect: each box length, with `mdat` included, uses 32 bits. Sample data above approximately `4 GiB` overflows the `mdat` length without an error and damages the file. Offsets use 64 bits for this file length. Thus the two limits do not agree.

- Defect: the module comment points at `av1.rs` for the AV1 measurements, and the crate holds no `av1.rs`.

- Track and media durations use 32-bit values. At clock rate 44100, the audio media duration overflows after approximately 97200 seconds.

## Sidecar read (`src/video.rs`)

### Goal

Read each named blob that `set_sidecar` wrote into a clip. Such a blob can hold replay data with the video.

### Invariants

- A sidecar is a `uuid` box at the file root. Its first 16 body bytes equal `PERIHELIONRPLY01`. The marker is text in the raw bytes.

- Video programs ignore unknown boxes at the file root. Thus the file stays an `.mp4` that most video programs open.

- `read_sidecars` returns the blobs in write sequence and runs with the GIL released.

### Verification

A clip written with two sidecars returns the two `(name, bytes)` pairs in sequence. The same file plays in a video player. A file without sidecars returns an empty list.

### Implementation

The `for_each_box` walk steps through boxes at the file root. A box length of 1 shows that a 64-bit length follows. A length of 0 shows that the box continues to the file end. The walk stops when a length does not fit the buffer.

`read_sidecars(path)` reads the file. For each `uuid` box with the marker, it parses the name length and the UTF-8 name. It then parses the 64-bit data length and the data.

A file-open or file-read failure raises `ValueError` with `VideoRecorder: read file:` and the OS cause. Duplicate names in a file from a different source stay as duplicate entries in read sequence. The reader returns each one as a different entry.

During `VideoRecorder.finish`, the writer attaches each blob in a set sequence. It writes box length, `uuid`, 16 marker bytes, name length, name, data length, and data. A blob too large for a 32-bit box length raises during the write.

### Caveats

A damaged sidecar box produces no entry or error. This includes an incorrect marker, a name that is not UTF-8, and a short name or data field. Bytes after the given data are ignored. Duplicate names stay as different entries. A malformed box length at the file root terminates the top-level box scan.

Thus, correct boxes after it are not read. A malformed sidecar body does not stop the walk through boxes at the file root. Subsequent boxes at the file root can still produce entries.
