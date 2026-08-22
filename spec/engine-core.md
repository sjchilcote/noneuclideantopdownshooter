# The engine (`necore`)

This specfile tells the operation of the Rust crate `necore` in `engine/necore/`. The warm-start procedure wrote it from the code. All sections tell the facts of the code as it is.

## The crate

### Goal

`necore` is the engine of `PERIHELION`. A world is a graph of convex polygons. Portals connect the polygons edge to edge, with invertible affine transforms. There is no world space: each coordinate is polygon-local, and only portal transforms map between polygons. The crate holds the procedures that do not change — geometry, `visible_set`, the simulation, and the queries — and emits events. The Python layer above gives the `PERIHELION` response to those events.

### Invariants

- No unit of the crate holds a global world position. All positions are polygon-local.

- The crate uses no other library at runtime. The only test library is `proptest`.

### Verification

- `cargo test` in `engine/necore/` runs the tests in each module and the tests in `tests/`.

### Implementation

- `Cargo.toml`: name `necore`, version `0.1.0`, `edition = "2021"`, no runtime libraries, `proptest = "1"` for tests.

- `src/lib.rs` lists the modules `frames`, `geom`, `math`, `signals`, `physics`, `query`, `raster`, `soft`, `visibility`, `world`. It also contains `pub use` declarations for names from those modules at the crate root. One declaration is `SignalField as CoreSignalField`.

### Caveats

- None.

## Vectors and matrix operations (`math.rs`)

### Goal

`Vec2` and `Mat3` give the crate its `2D` vector operations and its `3x3` transforms that include translation. The engine convention: the `y` axis points down, as on a screen. Polygons have a canonical vertex orientation, which gives a negative area from the sum of cross products. For an edge `a->b` of such a polygon, `(b - a).perp_right()` points into the polygon.

### Invariants

- For a finite input with a finite calculated length, `Vec2::normalized` gives `(1, 0)` below length `1e-12`. It gives a unit vector for all other lengths.

- Each tested, well-conditioned invertible matrix multiplied by its inverse gives the identity in `1e-9` for each element.

### Verification

- The test `inverse_roundtrip` composes translation, rotation, and scale, and checks that the result with the inverse is the identity.

- The test `perp_right_is_inward_for_visual_ccw` checks that `perp_right` of a canonical edge points into the polygon.

- The property test `normalized_fallback_is_unit_and_never_nan` samples zero vectors, almost zero vectors, and normal vectors. It checks that the output is finite. It also checks that inputs below the threshold use the `(1, 0)` fallback. A comment records a failure with the threshold changed to `l <= 0.0`: the test found a value that was not finite.

### Implementation

`Vec2` holds the `f64` fields `x` and `y`, with the constructor `v(x, y)`. It has the operations add, subtract, multiply by a scalar, and minus. Its functions:

- `dot`, `cross` (the `2D` scalar cross product), `len`, `len2` (the square of the length), `dist`.

- `perp_left` gives `(-y, x)`. `perp_right` gives `(y, -x)`.

- `normalized`: when the length is less than `1e-12`, the result is `(1, 0)`. Otherwise, the result is the vector divided by its length.

- `lerp(o, t)` blends from `self` to `o` along a straight line.

`Mat3` holds an `[f64; 9]` in row sequence and contains an affine map. The code keeps the full `3x3` shape, thus connections that divide by `w` stay possible. Its functions:

- `IDENTITY`, `translate`, `rotate(theta)`, `scale(sx, sy)`, `mul` (matrix `a` times matrix `b`).

- `apply(p)` maps a point through the full matrix and divides by `w`.

- `apply_dir(d)` maps a direction through the `2x2` part only. Velocities and directions use this map.

- `det` gives the `3x3` determinant. `is_invertible` is `det().abs() > 1e-12`.

- `inverse` calculates the standard `3x3` inverse, divided by the determinant.

- `linear_scale` gives `sqrt(|det of the 2x2 part|)`. Callers use it to change local lengths into screen lengths.

### Caveats

- `inverse` does not examine the determinant. On a matrix that is not invertible, it divides by zero and gives values that are not finite. Callers with external matrices check `is_invertible` first (`world.rs`, `frames.rs`, and `raster.rs` do this).

- `normalized` does not reject NaN or infinite values. Such inputs can give components that are not finite. `is_invertible` is only a determinant threshold. It does not give a general error limit for ill-conditioned matrices.

- The `(1, 0)` fallback of `normalized` was the cause of a repaired defect. An edge with zero length used this fallback as its "normal", which added an incorrect half-plane. The checks are in `geom.rs` (`DEGENERATE_EDGE`), before each caller that calculates edge normals.

## Geometry (`geom.rs`)

### Goal

`geom.rs` gives the polygon procedures: area, centroid, vertex orientation, convexity, and half-plane clips of polygons, segments, and polylines. It also gives the tests that tell if a point is in a polygon, and the terrain collision primitives (`Rect`, the swept circle against a rect).

### Invariants

- An edge shorter than `DEGENERATE_EDGE = 1e-9` does not become a half-plane. A clip polygon with duplicate vertices (at all positions, the wrap pair included) clips the same as the clean polygon. `point_in_polygon` and `depth_in_polygon` also ignore degenerate edges.

- The vertex orientation of a clip result agrees with the vertex orientation of the input. A clip result with less than 3 vertices is the empty list.

- `swept_circle_vs_rect` detects a collision when a fast diagonal movement crosses the rectangle. A circle with its center in the padded rectangle at the start returns `None`: that is not a crossing.

### Verification

- Tests in the module check a canonical square, the half-plane clip of a square, and the segment clip. Another test clips one convex polygon against another. The flicker regression test `duplicate_clip_vertex_is_inert` adds a duplicate vertex at each position, including the wraparound pair. It also examines the point tests, the depth test, and the polyline clip.

- Tests of the swept circle show that it stops at the padded face from all 4 sides. A fast diagonal movement does not pass through. A parallel movement with sufficient clearance reports no collision. An embedded start is not a crossing.

- The property test `degenerate_edge_injection_is_inert_under_arbitrary_polygons` (`tests/properties.rs`, item 9) adds 1 to 3 duplicate vertices to convex polygons from the test generator. It compares the clip, point, and depth results with the clean polygon. A comment records a failure with `DEGENERATE_EDGE` set to `0.0`: the property found the defect.

### Implementation

- `signed_area`: the sum of vertex cross products times `0.5`. Canonical polygons give a negative value.

- `centroid`: the standard centroid procedure, weighted by area. When `|area|` is less than `1e-12`, it gives the mean of the vertices.

- `canonicalize_winding`: when the signed area is positive, it changes the vertex sequence to the opposite sequence. It returns a flag that tells if it did.

- `is_convex`: it gives `false` for less than 3 vertices. For each pair of adjacent edges, the cross product must not be more than `1e-9` (almost collinear pairs go through).

- `inward_normal(a, b)`: `(b - a).perp_right().normalized()`.

- `HalfPlane { point, normal }` keeps the points for which `normal.dot(p - point) >= 0`. `signed_dist` gives that `dot` result.

- `clip_polygon_halfplane`: the `Sutherland-Hodgman` step against one half-plane.

- `clip_polygon`: applies a half-plane list in sequence. It stops with the empty list when less than 3 vertices stay.

- `clip_polygon_convex(subject, clip)`: builds the inward half-planes of the clip polygon in edge sequence, ignores degenerate edges, and applies them.

- `polygon_halfplanes`: the same half-plane construction, as a crate function. The rasterizer calculates the half-planes for each clip polygon and then uses them again.

- `clip_segment(a, b, hps)`: the part of the segment that all half-planes keep, as 2 points, or `None`. A segment almost parallel to a plane (`|dd| < 1e-12`) stays only when its start point is in the half-plane.

- `clip_polyline_convex` and `clip_polyline_halfplanes`: they clip each segment of the polyline and connect the results into pieces. A distance larger than `1e-9` between results starts a new piece.

- `point_in_polygon(p, pts, eps)`: `true` when the point is at `-eps` or more on each inward side. Degenerate edges do not count.

- `depth_in_polygon`: the minimum inward signed distance across the edges that are not degenerate. A positive value means the point is in the polygon. It gives `f64::INFINITY` when there are no such edges.

- `Rect { lo, hi }`: `new` sorts the 2 corners, thus `lo <= hi` on each axis. `inflate(r)` moves all sides out by `r`. `contains` is a bounds test that includes the boundary. `edges` gives the 4 sides as segments.

- `swept_circle_vs_rect(pos, target, radius, rect)`: an axis-interval test of the segment against the rectangle padded by the radius. It returns the first entry time `t` in `(0, 1]` and the outward face normal at contact, or `None`. The padded shape is a square rather than a rounded rectangle, so it conservatively includes the true swept-circle collision region. A diagonal movement toward a corner can therefore stop slightly before true contact, but cannot pass through the rectangle. A start with `t0 <= 1e-12` returns `None`. Callers handle initially embedded centers separately.

- `polygon_bbox`: the minimum corner and the maximum corner of a point list. For an empty list, the minimum corner is `f64::INFINITY` in the `x` and `y` directions. The maximum corner is `f64::NEG_INFINITY` in the `x` and `y` directions.

### Caveats

- `DEGENERATE_EDGE` records a repaired defect (the flicker). A duplicate clip vertex caused an edge with zero length. The `normalized` fallback added an incorrect vertical half-plane from it. That half-plane removed the full clip result on some ticks. Decals and marks on polygons blinked at a rate as high as `30 Hz`. The checks in this module are the repair.

- `clip_polygon`, the function that receives a half-plane list, has no degenerate-edge check in it. The checks are in the functions that calculate half-planes. A caller that supplies the half-plane list accepts that risk.

- The comment on `Rect::edges` tells that the vertex orientation agrees with the polygon convention only for occluder use.

## Coordinate spaces (`frames.rs`)

### Goal

This module reports a space mismatch as an error. A pair of numbers is meaningful in only one coordinate space. Code once subtracted positions from different polygons and silently calculated an incorrect value. In that failure, the target direction, range test, and push direction all crossed a polygon boundary.

The module prevents 3 silent failure modes. The first is subtraction of coordinates from different spaces. The second is a valid route to the wrong destination space. The third is avoidance of necessary transforms because an operation stays in one polygon. Operations that can detect a frame mismatch therefore return `Result`. Constructors and infallible property reads return values directly.

### Invariants

- Space identifiers remain unique for the lifetime of the process. The code never reuses one. The name registry keeps all identifiers and their names. If the registry lock is poisoned, lookup returns `space {id}` rather than a stale or incorrect name.

- An operation on 2 values returns `NoSharedSpace` when no space occurs in the two records. A transform returns `WrongSource` for a value that is not in its source space.

- An `Offset` moves through the `2x2` part of a transform only. A `Coordinate` moves through the full affine map.

- A `Coordinate` does not read the world. It replays only the matrices in its record. Thus topology changes have no effect on it.

- When 2 routes between the same spaces have a holonomy, `sub` reports the difference. The module does not remove it.

### Verification

Tests in the module, one for each fact:

- Different identifiers, with names that have no effect.

- Add, subtract, and distance in one space.

- An error for 2 new coordinates in different spaces.

- A moved coordinate compared with a local one.

- An error for an incorrect source.

- Reconciliation through the same space from a point nearer the start of the chains.

- An offset moves through the `2x2` part only.

- A portal with scale scales a difference.

- A holonomy is reported, not removed.

- The same space nearest the chain ends is the reconciliation point, with no matrix work when the last spaces agree.

- A record stays correct through topology changes.

- Travel through a mirror portal and back.

- An error for offsets across spaces with no connection.

- The `Coordinate::offset` short procedure.

### Implementation

- `SpaceId` is `u64`. A global counter starts at 1 and only increases. A global map keeps `id -> name` for messages only. `name_of(id)` returns the name, or `space {id}`. `space_handle(id)` wraps a known identifier in a `CoordinateSpace` value. It does not call `CoordinateSpace::new`.

- `CoordinateSpace` holds `id` and `name`. The `==` compare uses only `id`. `new(name)` increments the global counter, uses the result as the identifier, and records the name.

- `Step { into, xform }` is one record entry: the space this step moved into, and the matrix that moved it.

- `FrameError` has the variants `WrongSource { expected, found, transform }`, `NoSharedSpace { left, right, left_chain, right_chain }`, and `NotInvertible`. The error text prints the space names and the two chains.

- A chain is the space list that a value was in, with the first space first. It contains the start space, then the `into` of each step.

- `shared(left, right)` finds a common space nearest the end of the left chain. If more than one candidate is equally near that end, it chooses the candidate nearest the end of the right chain. If both values already end in the same space, it chooses that space and performs no matrix operations. The selection matters because routes can have a holonomy. A different reconciliation point gives a different result that is also correct.

- `transport` moves a value rearward along the right record (with inverse matrices) to the same space, then forward along the left record. A point uses the full map. A difference uses the `2x2` part.

- `Coordinate { pos, origin, record }`. Only the engine constructs a `Coordinate`. Its origin space identifies the coordinate system in which its raw position was expressed. Its functions are `space`, `origin_space`, `chain`, `record`, `local` (the raw pair, for a channel that names the adjacent space), `offset(d)` (a difference in the space of this coordinate), `sub` (gives an `Offset` in the space of `self` after transporting the right operand into that space), `add(Offset)`, `distance` (measured in the space of `self`), `extended(steps)` (attaches a full route, engine only, with no source test, because route steps start in the space of this coordinate), and `transformed(t)` (returns an error for an incorrect source, then attaches one step).

- With portals that scale, the selected measurement space affects `distance`. The same pair of bodies has a larger distance from one side than from the other. The constants of a body apply on its side.

- `Offset { d, origin, record }`. Callers can use the constructor `new(space, d)`. Constructing an `Offset` directly chooses the space in which the displacement is expressed. Unlike a position, it need not identify a world location. Its scalar functions are `space`, `chain`, `record`, `local`, `len`, `is_empty`, and `angle`. An angle has no space.

  Other functions are `scaled`, `normalized`, `rotated`, `add`, `sub`, `dot`, `cross`, `extended`, and `transformed`. `rotated` operates in its active space before movement because a mirror portal changes handedness. `add`, `sub`, `dot`, and `cross` reconcile through the same space.

- `Transform { from, to, m, name }`. `new` returns an error for a matrix that is not invertible. `inverse` interchanges the spaces and calculates the inverse matrix.

### Caveats

- The results of `sub`, `add`, and the other reconciled operations hold an empty record. A result keeps no memory of its chain, and attaches only to its space.

- The name map becomes larger for the life of the process. No code removes entries. Names are for messages only, and no operation reads them.

- The module comments point to 2 notes (`docs/FRAME_SYSTEM_DESIGN_20260729.md`, `docs/FRAME_ALGEBRA_NOTES_20260729.md`). The cause: identity must be a runtime integer, because no special value can tell the destination space from moved numbers.

## The world and its portals (`world.rs`)

### Goal

`World` holds the polygon graph: the convex polygons, their portals, their terrain rects, and one space for each polygon. It gives the operations that change topology. A caller can add a polygon, connect 2 edges, connect with a selected transform, and disconnect. A caller can also calculate a portal transform again from moved endpoints. Last, `split_edge` divides a wall edge to form a doorway at runtime.

### Invariants

- The vertex list of a polygon has canonical orientation. The polygon centroid is the origin of its space.

- The 2 transforms of a portal pair are the inverse of each other. `connect` aligns the edge of `b` flush against the edge of `a`, with the 2 edge directions opposite (`t -> 1-t`). The transform maps the edge end of `b` to the edge start of `a`. It maps the edge start of `b` to the edge end of `a`.

- A mirror connection (an edge to the same edge) installs one portal, and that transform is an involution.

- `split_edge` keeps the polygon convex (the new vertices are collinear with the edge). It also corrects each portal in the world that points to a moved edge.

- `add_polygon`, `connect`, `connect_with_xform`, the removal of an installed portal pair, and `split_edge` each increase `topology_version` by 1. A disconnect call on an edge with no portal does not increase it. Changes to terrain and changes to the matrices of an installed portal pair do not increase it. Router hop tables attach to this number and contain edge selections, not matrices.

### Verification

- Tests in the module: flush transforms that are the inverse of each other, with opposite edge directions. The doorway from `split_edge` has correct edge lengths, and portal correction follows the division. An additional polygon connects to the new doorway. Division of an edge with a portal returns an error. A mirror connection applied twice is the identity.

- Property tests are in `tests/properties.rs`, items 1, 2, and 10. They test the `connect` invariants for polygon pairs from the test generator. They also test the mirror involution and the `connect_with_xform` error conditions.

  The test tolerance scales with the ratio of edge lengths, because `connect` scales when the lengths are different. `connect_with_xform` rejects singular matrices and installs a correct inverse pair otherwise. A comment on item 10 records a failure after removal of the `is_invertible` check. An almost singular condition gave values that were not finite.

### Implementation

- `PolygonId` is `usize`, the index into `World::polygons`.

- `Portal { target_polygon, target_edge, xform, inv }`. `xform` maps neighbor coordinates into the coordinates of this polygon. `inv` is the cached inverse.

- `Polygon` holds `verts`, `portals` (one `Option<Portal>` for each edge), `normals` (unit inward normals, one for each edge), `edge_len`, `entities` (the entity identifiers in this polygon — the position index), `radius` (the largest vertex distance from the origin), and `terrain` (terrain rects, empty as the default — no rects means fully walkable). `edge(i)` gives the endpoints. `refresh_geometry` calculates the normals, edge lengths, and radius again from the vertices. Deformable polygons change their vertices each step. `num_edges` equals the vertex count.

- `WorldError`: `NotConvex`, `TooFewVerts`, `BadPolygon`, `BadEdge`, `EdgeOccupied`, `NotInvertible`, `DegenerateEdge`.

- `World` holds `polygons`, `topology_version`, and a `spaces` list parallel to `polygons`. It also holds `by_space`, the map from a space identifier back to its polygon. Spaces that the world did not give (the screen) are not in the map. Thus `develop` into them gives `None`.

- `polygon_space(r)` and `polygon_of_space(s)` read those maps. `portal_transform(a, ea)` wraps the portal matrix and its 2 spaces in a `Transform` named `portal {a}:{ea}`.

- `add_polygon`: rejects less than 3 vertices. It sets the vertex orientation to canonical and rejects a polygon that is not convex. It moves the vertices, thus the centroid is the origin. It rejects an edge shorter than `1e-9`. Then it calculates normals, lengths, and the radius, gives the polygon a `Polygon {id}` space, and increases the version.

- `set_polygon_terrain(r, rects)`: replaces the full terrain list of the polygon. An empty list marks it as fully walkable again. Terrain is polygon-local only. Thus collision against it does not read the route that the caller used to move to the polygon.

- `connect(a, ea, b, eb)`: rejects bad edges and edges that have portals. It calculates the rotation that turns the opposite of the edge of `b` onto the edge of `a`. The scale `la/lb` applies when the lengths are different. Then it calculates the translation that sets `M * pb1 == pa0` and `M * pb0 == pa1`. Debug assertions examine the 2 maps. `install_portal` writes the pair (one portal only in the mirror condition).

- `connect_with_xform(a, ea, b, eb, m)`: it runs the same edge tests, but the caller supplies the matrix. It also checks that the edges do not have portals. The engine checks only that the matrix is invertible. It accepts a matrix that does not align the connected edges. It installs `m` and its inverse and increases `topology_version`.

- `rebuild_portal_pair(a, ea, b, eb)`: calculates the transform pair again from the current edge endpoints. It reads the determinant sign of the installed map and keeps its handedness. For a determinant of zero or more, it calculates `z -> alpha*z + beta` with `B1 -> A0` and `B0 -> A1`. For a negative determinant, it calculates the form that uses the conjugate of the input. Deformable polygons can change doorway lengths, and the map must stay correct. This operation does not increase `topology_version`.

- `disconnect(a, ea)`: removes the portal and the portal on the other side (not applicable to a mirror), and increases the version.

- `split_edge(r, e, t0, t1)`: rejects a portal edge. It checks that `t0 > 1e-6`, `t1 < 1 - 1e-6`, and `t1 - t0 > 1e-6`. It adds the points at `t0` and `t1` to the vertex list. It adds 2 wall edges with the same normal to the edge lists and divides the edge length with no error. Then it corrects each portal in the world that points to an edge of `r` after `e` (it adds 2 to the edge index). It returns the middle edge index `e + 1` — the middle edge is for the doorway — and increases the version.

### Caveats

- `rebuild_portal_pair` returns `Ok` and changes no data when the edge has no portal. It does the same when the edge of `b` is degenerate (`dd < 1e-18`). In the degenerate condition, the stale transform remains installed and no error is reported.

- The flush property of `connect` is a debug assertion only. A release build does not examine it.

- `set_polygon_terrain` does not increase `topology_version`. Terrain is not routed topology. Physics and the terrain queries read it live.

- `split_edge` does not tell the deformation system. Refer to the caveats of `soft.rs`.

## Queries and routing (`query.rs`)

### Goal

`query.rs` gives query results about the connected world. It gives raycasts through portals, hop routing for tests of near polygons, and routing by length for accurate directions. The `develop` operation transports coordinates into other spaces. The module also gives the outward perception walk (`reach`) and terrain queries.

### Invariants

- Walls always stop a ray. Entity hits obey the group mask and the ignored identifier.

- `Router` tables attach to `topology_version`. A topology change does not let an expired result stay in use.

- `route` gives its search the key (polygon, entry edge, hop count). Thus a deep node does not replace a node with larger cost and a lower hop count. The deep node can have a smaller cost. The node with the lower hop count is necessary because of the hop cap.

- `routes` gives different images only, smallest cost first, in the hop cap, the image cap, and the work budget.

- `Reached::near` is a lower limit on the length of each possible sightline into the polygon. A range cut on it does not remove a body in range.

- `reach` and `route` agree on the position of a transported point.

### Verification

- Tests in the module: one raycast crosses portals and hits a wall at the correct distance. A different raycast hits an entity through a portal. Router results go through chains. The router calculates its table again after a topology change. A comment on that last test records a failure with the version compare set off. The two checks found expired results.

- More tests: routing by length against hop routing, in a world where the two do not agree (90 units in 3 hops against 990 units in 1 hop). Also: the hop cap, with the empty route in one polygon. Also: `develop` into a different space, with the record equal to the route. Also: `develop` returns `None` for the screen space and for a polygon with no route. Also: `routes` gives different images, smallest cost first, and a larger budget sees more images.

- Tests of `reach`: the `develop` step into the space of the observer, and the hop cap. Also: the range cut keeps each polygon that a sightline can go into. Also: the lower limit property of `near`. Also: `reach` and `route` agree on transported positions.

- Terrain query tests: no occluder segments without a mask, and 4 segments on the rect boundary for 1 rect. An unknown polygon gives the empty list. `terrain_avoid_dir` gives a clear direction back with no change. It turns a movement pointed straight at a rect, with the same result each time, at unit length.

### Implementation

- `RayHit` is `Wall`, `Entity`, or `Nothing`. Each variant holds the polygon, position, distance, and hop count. It also holds the collected matrix from the hit polygon back to the start polygon.

- `raycast(sim, polygon, origin, dir, max_hops, max_len, mask, ignore)`: the direction is normalized. Each loop turn finds the exit: the smallest positive crossing in the edges that the ray goes out through (`d.dot(n) < -1e-12`, `t > 1e-9`). Entity tests run in the segment that ends at the exit or at the range end. An entity must be active and must not be the ignored identifier. Its group bit (`1 << (group & 15)`) must be in the mask. The circle intersection gives the smallest `t` in `(1e-9, seg_end]`, and an entity hit in the segment is selected.

- The end conditions of `raycast`: when the range ends first, the result is `Nothing` at the range end. When no exit is found, the result is `Nothing` at the active segment origin. It contains the distance collected before that segment. At the exit edge, the portal counts only when the crossing point is in the open span, with no extension. Otherwise, the result is `Wall`. At the hop cap, the result is `Nothing` at the edge.

- A crossing maps the position through `inv`, and the direction through the `2x2` part. It changes the direction to unit length again. Then it nudges the position forward `1e-6`, and adds `1e-6` to the distance.

- Distances collect in the local metric of each polygon: correct for rigid portals, a decision for portals that scale. Gameplay ranges change with the scale of the space.

- `Router` keeps one table for each destination: a `BFS` from the destination through portals. The table has `next[polygon]` as the edge to cross, and `dist[polygon]` as the hop count, attached to the topology version. `next_edge` replaces an expired table with a table calculated for the active version. `hop_distance` returns the hop count or `None`.

- `terrain_light_segments(world, polygon)`: the edges of each terrain rect, polygon-local. This is an interface only: no render code reads it, and terrain has no effect on `visible_set`.

- `terrain_avoid_dir(world, polygon, pos, radius, desired, lookahead)`: it sweeps the normalized direction `lookahead` units, with the swept-circle test against each terrain rect. With no hit, the result is the normalized input direction. With a hit, the result is `normalize(d + perp * 0.9 * side)`. The sign `side` turns to the opposite side from the center of the hit rect. This selection has the same result each time: the same side each tick for a static scene.

- The cause of `terrain_avoid_dir`: wall slip moves a body along a wall at an angle. A movement pointed straight at a face has zero tangential velocity. A bot that points at the same blocked target each tick stops without end.

- Routing by length: `Router` gives results in hops, which is the incorrect measure for `which direction is the player`. Legs measure between doorway midpoints in the local metric of each polygon. This is a maximum for the shortest path, and correct when the path goes through doorway centers. Lengths through a portal that scales are in the metric of each leg, by decision.

- `Route { polygons, steps, dist, entry_edge }`: the polygons the route goes into, in sequence, and one `Step` for each hop. An empty list means the start polygon is the destination. `dist` is the length from the source point to the last doorway. The route does not know the destination point. The caller adds the last leg. `entry_edge` names the entry edge, `None` for the empty route.

- `route(world, from, from_pos, to, max_hops)`: a `Dijkstra` search through the keys (polygon, entry edge, hops), smallest cost first, with `usize::MAX` as the source entry mark. The search does not go back out through the entry edge. It returns `None` when an identifier is out of range or no route obeys the cap.

- `routes(world, from, from_pos, to, max_hops, max_images)`: lists different routes, smallest cost first. Two routes are the same when their transported images of the source point agree, quantized at `1e-3` units. This compare does not examine the complete transforms. Two transforms can map the source point to the same grid position but map other points differently. They count as one image. That grid is much smaller than gameplay differences and much larger than float noise.

  A graph with a loop has routes without limit.

  A work budget of `max_images * 256 + 4096` limits the search, also when the search ends before the full image count.

- `transform_between(world, from, into)`: the composed transform along the shortest route by length, measured from the centroid of the source polygon, or `None`. It is here, adjacent to `develop`, because an explosion through a doorway must have the two directions from one search. It must have each body position in the explosion space. It also must have the opposite, and the two must agree. Two `develop` calls are 2 searches, and their routes can be different.

- `develop(world, c, into)`: the one operation here that reads live topology. It finds a route between the coordinate polygon and the target-space polygon. It extends the coordinate by the route steps. It returns `None` when one of the 2 spaces is not a polygon of this world. The screen is such a space. It also returns `None` when no route is found.

  This world function searches world state. It is not a `Coordinate` function because the search can return `None`.

- `Reached { polygon, into_obs, depth, path, near }`: one polygon in the observer walk. `into_obs` transports it into the space of the observer. `depth` is the doorway count, `path` the midpoint path length, and `near` the sightline lower limit.

- `reach(world, from, from_pos, max_hops, max_range)`: one outward walk from the observer, smallest cost first, with the key (polygon, entry edge). A polygon that the walk goes into through a different doorway is a different image. For each crossing, the walk composes `into_obs` with the portal matrix, and calculates the doorway as the observer sees it. It sets `near` to the maximum, across the chain, of the distance from the observer to the doorway. It cuts when `near` is more than the range.

- One outward traversal is used to control routing cost. Perception examines the local area of the observer. The traversal gives results for all bodies together. The removed procedure did one route search for each body. This was 3200 searches each tick for 36 observers and used the full frame budget.

- `polygons_within(world, center, hops)`: a `BFS` list of polygon identifiers.

### Caveats

- Defect: the comment on `reach` tells that the results are `nearest first`. The code adds each polygon when the walk first finds it, in the edge sequence of the source node. Two entries can be out of length sequence. No test examines the sequence.

- The result list of `routes` is not complete when the budget ends first. Larger budgets see more. In a graph with a loop, no complete result is possible.

- `polygons_within` indexes its `center` in the traversal state without a check. A center external to the world panics. The Python binding checks the center before it calls this engine function.

- A comment in `tests/properties.rs` (item 6) calculates its distance tolerance from a raycast nudge that does not add to the distance. The code adds the nudge (`travelled += 1e-6`). Thus the small distance error in that comment is not in the code. The comment is an expired note, not a code defect.

## The visible set (`visibility.rs`)

### Goal

`visible_set` is the portal traversal with recursion. From a camera polygon and a viewpoint, it gives each polygon instance in view. Each instance holds its screen transform, its convex region in view, and its wall spans in view. The output is sorted deepest first for the painter algorithm.

### Invariants

- The `clip_local` region of each instance is convex, is in its polygon, and is in the half-planes of its frustum.

- Output regions have no adjacent duplicate vertices, the wrap pair included. A duplicate can cause geometry to show on one frame but not on a different frame. This occurs when a consumer calculates edge normals.

- Between topology changes and traversal-cap boundaries, the region in view changes continuously with the apex. Geometry with almost zero measure is different. Regions below area `1e-6` and spans below the related geometric limits are removed. The traversal depth and instance caps can also change the returned set at their boundaries. No more threshold removes a region with positive measure. Such a cut causes full subtrees to blink as the apex crosses the threshold.

- A duplicate-instance collision cuts recursion only, not the output. The same pixels render on top of the same pixels, and this is safe. A cut output caused wedges to blink between frames.

- The traversal ends. Recursion stops on instances that were seen, at the depth cap, at the instance cap, and out of the screen.

### Verification

- Tests in the module: one polygon renders fully. A corridor shows all 3 polygons deepest first, with the neighbor region on the correct side of the portal edge. A mirror connection ends and shows mirror copies. A corridor that loops onto the same polygon gives approximately as many copies as the screen width holds (between 5 and 16, not 512). An apex on the doorway line sees the full neighbor.

- The wide fan test uses an apex `0.2` units from the edge line but 450 units out of the segment. It must give a thin region. The full polygon is the defect shape (the recorded seed-7 tick-71 blink).

- `tests/invariants.rs`: an apex movement across a `3x3` grid, in steps of `0.35` units. It checks the contract against duplicate vertices and continuity. A large region does not fall more than 60 percent in one step.

- `tests/properties.rs` item 8: for random apex positions on a translation grid. Each `clip_local` is convex, is in its polygon, and is in the half-planes of its frustum.

### Implementation

- `Frustum { apex, a, b, entry_edge, wide }`, in the local coordinates of the polygon at this step. `half_planes` gives the portal half-plane with the polygon inward edge normal. This is correct when the apex is on the portal line too. If not `wide` and the apex is not collinear with the segment, it adds 2 half-planes. They are at the rays `apex->a` and `apex->b`. Each has the normal that keeps the other endpoint.

- `EDGE_BAND = 1.0`: at this distance or less from a portal, the view through it is a full 180-degree fan (`in the doorway`). This keeps frames smooth in the middle of a doorway. Without it, the neighbor polygon is removed for one frame.

- `PolygonInstance { polygon, xform, depth, clip_local, clip_screen, walls, entry_edge, frustum }`. `xform` maps polygon-local to screen. `walls` holds the edge spans in view, in screen coordinates, each with a portal flag. Tests can read `frustum`, thus they calculate the half-planes again without the traversal.

- The key against duplicates does not include the camera. The key contains the polygon, entry edge, and quantized portal-chain matrix `rel`. It also contains the quantized portal segment in the next polygon space. The `rel` matrix is the chain result without the camera. A key on the composed screen transform caused instance identity to be a function of the camera.

  Two chains then used the same key on some frames only, and full wedges blinked (the recorded wedge flicker). A traversal loop continues to use the key of the start polygon, and ends.

- `visible_set(world, camera_polygon, cam, apex_local, screen_w, screen_h, max_depth, max_instances)` walks a stack of nodes. The start node is the camera polygon, with the identity `rel` and no frustum.

- The steps for each node: stop when the output list contains `max_instances` accepted instances. Rejected nodes do not count against this cap. Add the key to the seen set (`novel` tells if it was new). Clip the polygon vertices against the frustum half-planes (none for the start node). Remove adjacent duplicate vertices, the wrap pair included. Remove regions with less than 3 vertices, and map to screen.

- More node steps: remove the node when its bounds are more than 4 pixels out of the screen. Regions of the next node are in the projection of its source node, thus the subtree goes with it. Remove only regions with almost zero measure (screen area below `1e-6`). Clip each polygon edge against the frustum for the wall spans.

- Recursion runs only when `novel` and below the depth cap, for each portal edge but the entry edge. An apex more than `EDGE_BAND` behind the infinite edge line cannot see through the edge (a straight sightline cannot cross a half-plane boundary 2 times). `wide` is `true` only near the segment, not near the line. The distance to the line, and the distance to the closest segment point, must each be at most `EDGE_BAND`.

- The span of the portal edge is clipped against the frustum. A span with almost zero length (`< 1e-6`) is removed, and no wider threshold is applied. For a span that is not `wide`, a careful screen test removes the wedge (the span pushed `4 * (screen_w + screen_h)` out, in the direction from the apex). The next node holds the composed screen transform, the composed `rel`, and the frustum mapped through the portal inverse.

- The output sorts by depth, deepest first, with a stable sort. Thus equal depths keep the traversal sequence.

### Caveats

- `EDGE_BAND` must stay more than the apex clamp margin of the Python layer (`_APEX_EPS = 0.75` in `sim.py`). `PERIHELION` gives this module a clamped apex that does not come nearer to a portal line than that margin. With `EDGE_BAND` not more than the margin, the wide fan cannot start before a doorway crossing. The side walls of the doorway then blink from not rendered to lit on the crossing tick (the recorded crossing flicker). Only a comment holds this connection. No code connects the 2 constants.

- A comment in `tests/properties.rs` (item 8) names `EDGE_BAND` as `0.5`. The constant is `1.0`. The test stays correct — its apex keeps 5 units or more from each edge line — but the comment is expired.

- The walls list also holds the span of the entry edge, with its portal flag `true`.

## Physics (`physics.rs`)

### Goal

`Sim` steps each entity through substeps against walls, portals, terrain, and other entities. It emits events. Walls bounce the body. A portal moves the entity into the neighbor polygon, with its velocity and direction mapped through. Terrain rects block the same as walls.

Contacts interchange impulses. Movement is swept against walls, portals, and terrain. Thus fast bodies do not go through them with no collision.

### Invariants

- Containment goal: the last physics correction tries to keep each entity center in its recorded polygon. It runs at the end of each tick. The simulation also has a correction sweep. A group of bodies can push at a doorway corner can move the center out of its polygon. See `spec/simulation.md`.

- Energy does not increase while all restitutions are 1 or less.

- `apply_impulse` is accurate: the velocity change is the impulse divided by the mass. It returns an error for a mass of zero or less, and for an unknown identifier. It is the only permitted push from gameplay.

- Terrain collision reads only the polygon of the entity and its local state. The result is the same for all portal chains that moved the entity there.

- An entity with `transfers` off uses wall collision at portals. An entity goes through an opening only when the opening is wide against its body: `2 * radius <= edge_len * 1.05`.

### Verification

- Tests in the module: a wall slip stays in the polygon, and the wall absorbs the normal velocity part. A transfer from a position on the far side of the portal plane moves the entity into the target polygon. This records a campaign failure in which a pushed entity moved out and blocked a run. A transfer keeps speed and goes back.

  A bullet at `4000 units/s` bounces and does not go through the wall. A collision transfers speed to the other body in the energy limit. An entity with `transfers` off stays in its polygon.

- Terrain tests in the module: a movement straight at a rect stops at the padded face. A fast bullet bounces off a thin rect. A bot that points at a blocked target stops in the test. This records the defect that `terrain_avoid_dir` repairs. The direction from `terrain_avoid_dir` ends on the far side.

- More terrain tests: terrain blocks projectiles as the default. A group with the block bit off goes through. No mask means fully walkable. An embedded entity is pushed out in one step.

- `tests/invariants.rs`: 12 entities on a fully connected `3x3` grid, pushed at high speeds by a deterministic generator for 4000 steps. Each center stays in its recorded polygon at each step. `impulse_is_mass_scaled_exactly` locks `dv = J/m`, the sum of impulses, and the error conditions.

- `tests/properties.rs`, item 3 checks containment with random impulses in polygons from the test generator. Item 4 checks that energy does not increase. Item 5: a transfer through a portal and back keeps correct speed and a position in one transfer nudge. Its transfer matrices compose to the identity. Item 7: the world position follows a flat bounce oracle in `1e-2` (the comment tells the cause: bounce systems increase the small nudges that are part of engine operation). Item 11: in a thin wedge, position and velocity stay finite, and containment holds.

  The terrain test compares an entity that crossed a portal with one spawned in the target polygon. The absolute coordinate difference between their trajectories is at most `1e-6`.

### Implementation

Constants: `TRANSFER_NUDGE = 1e-3` (the push into the new polygon after a transfer), `EDGE_SPAN_EXT = 1.0` (wall spans extend on the far side of their endpoints, thus wall seams have no opening — safe because the polygon is convex), `MAX_ITERS = 512` and `MAX_STALLS = 8` (the limits that stop a substep loop in a corner).

`Entity`: `id`, `polygon`, `pos`, `vel`, `dir`, `radius`, `mass`, `rest_wall`, `rest_ent`, `group`, `physical`, `max_substep`, `transfers`, `alive`. `physical` replaced a `16x16` group collision table that encoded one fact — a pickup is not a physics object. All fire hits all sides, thus the table held no other fact. The values at `spawn`: `rest_wall 0`, `rest_ent 0.3`, `physical` on, `transfers` on, `dir (1, 0)`, `max_substep = radius.max(1.0)`.

`Event` variants:

- `Transfer { ent, from, to, edge, xform }`: `xform` maps coordinates from the source polygon into the destination polygon. A consumer applies it to all data kept in the source polygon space. `edge` is the edge index in the source polygon.

- `WallHit { ent, polygon, edge, pos, normal, speed }` and `TerrainHit { ent, polygon, terrain, pos, normal, speed }`. The physics response is the same. The 2 variants only let `PERIHELION` hear `hit painted equipment` against `hit the polygon boundary`.

- `Contact { a, b, polygon, pos, normal, rel_speed }`. `polygon` is where the contact occurred, recorded at contact time, because the fact is not available after that. Without it, a subsequent transfer in the same step causes a consumer to read the normal in the incorrect space.

`Sim` holds the world and the entity map. The map is a `BTreeMap`, thus iteration sequence is deterministic. It also holds the identifier counter (from 1), `terrain_blocks`, the active polygon set, and the deformation system. `terrain_blocks` has one bit for each group, with all bits set by default. Its functions:

- `soften_polygon` (idempotent), `soft_wall_impulse` (no effect on polygons that are not deformable), `set_terrain_block(group, blocked)`.

- `set_active_within(center, hops)` replaces the active set with a `BFS` region. `activate_also(center, hops)` adds another region: units sent far from the player must simulate, or they do not move. `active_polygon_ids` returns the authoritative active set. `PERIHELION` systems must read it, and must not calculate a different region.

- `spawn(polygon, pos, radius, mass, group)`: rejects an unknown polygon. It sets the requested clearance to `radius.min(polygon.radius * 0.5)`. For a maximum of 8 turns, it finds the minimum signed depth across all edges. If the minimum signed depth is not less than the requested clearance, it stops. Otherwise, it pushes along the inward normal of the edge that has the minimum depth. The push is the missing clearance plus `1e-6`.

  The function does not report when 8 turns end before all edges have the requested clearance. It records the last position and adds the entity to the polygon list.

- `remove`, and `apply_impulse` (refer to the invariants).

- `step(dt)`: deformable walls integrate first, thus collision this step sees the new geometry. Then each active entity in an active polygon runs `step_entity`. Events collect and return.

`step_entity` runs a substep loop while more than `1e-9` seconds stay:

1. Loop progress monitor: an iteration that uses less than `1e-7 * dt` seconds counts as small progress. After `MAX_ITERS` iterations, or `MAX_STALLS` iterations with small progress in sequence, the code sets the velocity to zero and stops. A body that cannot move freely between surfaces stops. It does not go through a surface or loop without end.

2. The substep is `remaining.min(max_substep / speed)`. The target is `pos + vel * step_dt`.

3. Entity to entity: test each other active entity in the same polygon. Only test entities with physics enabled. Test overlap at the target position. Select the overlap with the smallest distance. The normal points from the other body to this one (`(1, 0)` when the centers are closer than `1e-9`).

4. Walls and portals, for each edge. The edge is a portal only when a portal is there and the entity transfers. The opening must also be wide against the body. A portal tests the center against the plane (`rad = 0`), and a wall tests the circle (`rad = radius`). The code ignores edges unless movement crosses them from in to out. The crossing time clamps to `[0, 1]`.

   A portal crossing must be in the open span, with no extension. If the crossing is not in the span, the same edge stops the entity as a wall. Wall spans extend `EDGE_SPAN_EXT` on the far side of the 2 endpoints.

5. Terrain, when the group bit is set: the swept circle against each rect. The code compares the first hit with the wall candidate and selects the first of the two. It selects the wall at an equal time.

6. Selection: a portal is selected when its time is not after the wall or terrain time. The code processes that transfer before it examines an entity overlap. Thus, a selected portal always has priority above an entity contact. When no portal is selected, an entity overlap applies if no wall or terrain occurs before the substep end. Wall and terrain times are measured, and the overlap test is at the substep end. Last, the wall or terrain hit applies.

7. Portal transfer: the crossing point maps through `inv`, and velocity and direction map through the `2x2` part. The direction is normalized again. The position receives a nudge of `TRANSFER_NUDGE` along the inward normal of the target entry edge. Then 2 iterations clamp it into the target polygon through its half-planes. The floor is zero at portal edges and `min(radius * 0.5, edge_len * 0.25)` at walls. The cause: a group of bodies can push an entity through the plane before the crossing is found.

   The time `t` clamps to 0, and the raw mapped point is out of the target polygon. The entity moves between the polygon lists, a `Transfer` event emits, and the used time has a floor of `step_dt * tp.max(1e-3)`.

8. Contact: an impulse along the normal, applied only when the bodies come closer. `rest` is the minimum of the 2 `rest_ent` values, and the weights are the inverse masses. Position separation divides the overlap plus `1e-6` by inverse mass. This entity also moves its full substep. The 2 entities clamp into their polygons again. One `Contact` event for each pair in each tick (a seen set removes duplicates).

9. Wall or terrain hit: the position stops at the crossing point plus `1e-6` along the normal. The velocity bounces: the normal part times `(1 + rest_wall)` is removed. A `WallHit` or `TerrainHit` event emits, with the contact point on the circle (`cross_pt - n * radius`) and the speed into the surface. The used time has the same `1e-3` floor.

10. Free movement goes to the target.

After the loop, 2 corrections run always. `contain_in_polygon`: 2 iterations through all half-planes, portal planes included, with a push in at each point where `d < -1e-9`. The plane is in the polygon, and this is a decision with 2 causes. A positive floor at a portal is a wall that no slow movement can cross. A radius floor at walls uses the infinite line.

Walls from `split_edge` and their portal are on this same line. Entities then stop a radius short of each new doorway.

The replaced version ignored portal edges. A corner slip could go through a portal plane but not be in its open span. The entity then stayed external to its polygon for all subsequent steps. The visibility apex became external to its polygon, and all polygons behind the entry portal had RGB channels of zero.

`push_out_of_terrain`: the center can be in a padded terrain rect without a swept test. A transfer, a mask load below a static entity, or a radius change can cause this. Two iterations push it out along the axis with the smallest depth, plus `1e-6`.

### Caveats

- The entity test against other entities is an overlap test at the substep end, not a sweep. Two fast small bodies can go through each other in one substep. `max_substep` limits movement in each substep to the body radius. This limits the window but does not remove it. Walls, portals, and terrain are swept.

- No test causes the iteration limit or limit for small progress to operate for a corner. The failure note on `tests/properties.rs` item 11 records that with the limits removed, thin wedge conditions did not hang. The limits stay as protection for conditions with contacts and walls together.

- The floors on used time (`tp.max(1e-3)`, `tw.max(1e-3)`) cause an approximate time count in collision substeps. The flat oracle test records the difference and limits it.

- Only a transfer writes the `dir` field (mapped through the portal). No other engine code writes or reads it.

## The rasterizer (`raster.rs`)

### Goal

`Raster` is the CPU rasterizer, with `pygame-ce 2.5.7` pixel parity. It replaced the pygame renderer. Thus each primitive uses the applicable pygame `draw.c` algorithm, not a general version — a difference shows in the frame tests.

It renders a command list into 3 layers with a set composite sequence. It multiplies the world by the lightmap (RGB channels are zero by default). It shows entity pixels only where the coverage mask contains rendered world pixels. Thus entities do not show across seams. It then replays overlays. It also has textures, kept decals, engine-side lights, the `otherworld` composite, and operations on the full frame.

### Invariants

- Pixel parity: each primitive renders the same pixel set as `pygame-ce 2.5.7` for the same integer inputs.

- The floor equals the coverage. `OP_CLIP_FILL`, `OP_TEX_FILL`, and the coverage mask of `add_clip` paint the same `f64` polygon with the same fill. The floor and the coverage mask agree pixel for pixel.

- Zero light as the default: the lightmap is set to all zero at `begin`. A world pixel that no light touches renders with RGB channels of zero.

- The lightmap does not decrease entity RGB channels (in frames with no `otherworld` region): the multiply runs before the entity fold. Entity alpha is binary, thus the fold is a pixel selection, cut only where the rendered world ends.

- Each malformed command stream returns `RasterError`. No primitive is dropped for a structural cause without reporting an error.

- The composite runs once in each frame. Subsequent `finish` calls return the same frame. Subsequent draws and `add_clip` calls return an error until the next `begin`.

### Verification

- Fixture tests compare each primitive against recorded pygame pixels (`raster_pygame_fixtures.rs`). The shapes: triangles (basic, flat top, thin, degenerate), and polygons (square, `diamond`, not convex, with a notch, clockwise). Also: thin and wide lines at all slopes, and open polylines and outlines. Also: circle fills and thin circle outlines, for radius values 1 to 10, with clipped conditions. Also: rect fill, and rect outlines with the 2 thin shapes where pygame fills, not draws borders.

- Span tests lock the fill algorithm with pygame rows. They include the full spans of a square and the `even-odd` algorithm on crossed edges.

- Rounding tests lock round-half-to-even (`py_round`) and `C` truncation (`c_int`).

- Clip-mode tests: `GEOM` equals a clip calculated with `geom` directly, and a fully clipped primitive is removed. `GATE` keeps by the gate point and draws with no clip. The gate works on clockwise polygons (a ray test, not vertex orientation). The transform applies, and the radius scale flag applies.

- Composite tests: the coverage union masks the entity layer, and the mask equals the floor fill. Pixels with no light have RGB channels of zero. The multiply is `(c*m + 255) >> 8` (255 stays 255). Entities stay lit on a world with no light. A glow adds with saturation in its bounds. The gate drops a glow with its center out of the polygon.

  Overlays draw after the lightmap at full brightness.

- Structure tests: stream errors have a report for each malformed shape, and the two override indexes replace the command fields. `begin` clears all frame state. `finish` is idempotent, and subsequent draws return an error. `finish_into` examines the length. `OP_CLIP_FILL` equals `OP_POLY_FILL`, which equals the coverage. `OP_TEX_FILL` samples the closest texel and agrees with the coverage, and tests include the error shapes of the two.

### Implementation

The command format has 6 `u32` values for each command: `OP, FLAGS, CLIP, XFORM, RGBA, N`. Payload floats use `f32`, and the opcode sets their count. `pack_flags` writes the layer and clip mode to 2 bits each. It writes the closed flag to bit 4 and the radius-scale flag to bit 5. The width uses 8 bits from bit 8. `IDX_NONE = 0xFFFF_FFFF` means no table entry.

```
op 0  POLY_FILL      2n floats   op 6  RECT_OUTLINE   4 floats
op 1  POLY_OUTLINE   2n floats   op 7  GLOW           3 floats (overlay only)
op 2  POLYLINE       2n floats   op 8  CLIP_FILL      0 floats (fills the clip entry)
op 3  CIRCLE_FILL    3 floats    op 9  TEX_FILL       2 floats (RGBA word = texture id)
op 4  CIRCLE_OUTLINE 3 floats    op 10 DECALS         0 floats (RGBA word = list id)
op 5  RECT_FILL      4 floats
layers: 0 world, 1 entity, 2 overlay
clip modes: 0 none, 1 geom, 2 gate, 3 bbox
TEX_DENSITY = 3.0 texture pixels for each world unit
```

Rounding parity: `py_round` is round-half-to-even (`int(round(x))` in Python). `c_int` truncates (`pg_IntFromObj`, `pygame.Rect`). Coordinates cross the API as floats, transform in `f64`, and use pixel rounding at raster time. `point_in_poly` uses the ray test from `render.py` and does not read vertex orientation. Its `x < x_at` compare lets clip polygons be clockwise behind mirror portals.

The pygame implementations, each line for line from `draw.c`:

- `pg_line_thin`: `Bresenham`, with a clip test for each pixel (pygame does not clip thin lines before the walk). The error calculation uses `C` truncation division.

- `pg_line_width`: a wide line has a perpendicular span of `width` pixels at each point of the `Bresenham` walk. It has flat ends, no corner connections, and one extra pixel on one side for even widths. It is not a rectangle with caps. `pg_clip_line_reject` runs first and stops a line that is fully out of the clip.

- `pg_filltri`: pygame fills 3-point polygons with an `f32` slope scanline, not with the general fill. The two render different pixels. Thus the selection by point count (`pg_poly_fill`) is necessary for parity.

- `pg_fillpoly`: the `even-odd` scanline fill. Intersections calculate in `f32`. Then the count at that point selects `floor` or `ceil`, in edge sequence, not sorted sequence. This pygame difference moves span ends by one pixel on some slopes. Horizontal edges internal to the row range run a second iteration. A polygon 1 pixel high is 1 span.

- `filltri_spans`, `fillpoly_spans`, `poly_fill_spans`: the same procedures in span shape, kept as full copies, not the same code. Thus the fixtures for fills of one color stay applicable with no change. The texture fill reads these.

- `pg_poly_outline` and `pg_polyline`: the code draws each edge as one wide line, with no corner connections.

- `pg_circle_filled`: the midpoint circle with span output, the `f >= 0` gate, and a footprint that is different on its sides. `pg_circle_thin`: the 8-part circle walk with the `-1` moves that give pygame circles different sides. The 2 use the same fast test, which stops a circle fully out of the clip.

- `pg_rect`: width 0 fills the clipped rect. A positive width draws borders — but when the clipped rect is thin (`width * 2` not less than a side), pygame fills and does not draw borders. It reports no error.

Frame tables: `add_clip(pts, coverage)` records a clip entry. It contains the `f64` polygon before rounding and its half-planes. It also contains a `pygame.Rect` parity integer bounds rect with a truncated minimum and `int(max - min) + 1` widths. With `coverage` on, it fills the polygon into the coverage mask with the same fill and rounding as `POLY_FILL`. `add_xform(m9)` records a matrix with its scale.

`Canvas` replaces the pygame surface. It has a byte buffer and bytes for each pixel. It also has a clip rect and a write mode. The modes are `Set` (RGBA write), `Add` (RGB add with saturation), and `Mask` (one byte). `hline_raw` writes spans in blocks for the fill hot path, byte-equal to writes of one pixel each.

Command runs (`draw`, or `draw_with_overrides`, which replaces the clip and transform indexes of each command — the static replay path): the stream length must divide into headers. Each opcode has a set float count. Floats that stay at the end are an error. For each command, geometry becomes tasks:

- Clip mode `GEOM` clips the transformed geometry. A result below 3 vertices is removed without reporting an error (the `render.py` check). Mode `GATE` uses one point to keep or drop the full primitive. This point is the first vertex, circle center, or rect center. Mode `BBOX` is for glows only.

- Alpha must be `0xFF`, but not for `GLOW` and `TEX_FILL` (their RGBA value is not a color). A circle outline width must be 1. Rect operations are screen-space and return an error for a transform. `CLIP_FILL` fills the polygon of the clip entry (no payload, no transform, no clip mode). `TEX_FILL` must have a clip and a transform.

- More on `TEX_FILL` and `GLOW`: `TEX_FILL` calculates the inverse of the instance transform in `f64`. It samples the recorded texture at each pixel center: `texel = floor((local - bbox_min) * TEX_DENSITY)`, clamped. `GLOW` must be on the overlay layer and must have a clip entry. `BBOX` draws in the clip bounds without a gate. `GATE` also drops the glow when its center is out of the polygon.

- World tasks draw immediately into the world plane (the texture fill through its span path). Entity tasks draw into the entity plane. Overlay tasks wait until the composite.

`OP_DECALS` replays a kept decal list, with the transform and clip of this frame. `set_decal_shape(id, pts)` records a shape template in local coordinates. `set_decals(list_id, records)` loads records of 12 `f64` values each:

```
[style, x, y, size, angle, squash, eff_mul, r, g, b, shape_id, rot]
style 0 = polygon fill, 1 = thin circle outline, 2 = polyline of width 1
```

Each record gates on its transformed center point against the clip polygon, and draws with no clip. The screen dimension is `size * scale`, with a floor of 1. With `rot` set, the screen angle comes from the transformed direction of `angle`.

Styles 0 and 2 transform the template with squash and rotation, and apply pixel rounding to the vertices before the task. Thus the task rounding changes no value. Style 1 draws a thin circle with the radius `trunc(s)`, floor 2. An unknown style is an error. A missing list or template draws no pixels and reports no error.

Lights: `add_light` uses the `render.py` light loop in the engine. The replaced loop used more than `4 ms` in each frame at 15 lights. It fills a work mask with the union of one light's wedge polygons minus its shadow polygons. The work mask has 1 byte for each pixel. It fills only in the work rect (the union bounds, light disc, and screen), with the same polygon fill. Vertices go through an `f32` quantization step first.

The Python code sent them through the `f32` command format before rounding.

Without this step, full pixel columns moved by one (a recorded frame parity search). Then it adds `(tint * gradient + 255) >> 8` into the lightmap below the mask, through a table for each channel, with saturation. Additions with saturation give the same total in each sequence. Thus sequence has no effect.

The gradient table for a radius key holds `trunc(clamp(1 - hypot(dx+0.5, dy+0.5)/key)^2 * 255)` in `f32`. It uses `sqrt(x*x + y*y)`, not the careful library `hypot`. The last bit is different and moved one boundary pixel for each light.

The cache empties when it holds more than 32 tables. The add loop runs on one thread by decision. A measured parallel version increases the time at the slow end more than one CPU decreases it. `lightmap_add_region` adds a raw RGB region with saturation (the glow images that stay in Python). `set_lightmap` replaces the full lightmap (the length must agree).

`Otherworld`: `mark_otherworld(clip_idx, mix)` marks the instance of a recorded clip as an `otherworld` region, with a blend weight (`0` normal, `1` full `otherworld`). On its first call, `bake_inv_field` calculates the inverse cold field. It uses an `f32` `smoothstep` of center distance, channel scales `(0.62, 0.38, 0.50)`, and truncated quantization. The result has low RGB channel values near the screen center, with dim light at distance.

Each result bit is the same as in the reference NumPy calculation. The code calculates the division constant in `f64` before one rounding operation. This keeps the NumPy calculation sequence.

The composite (`compose`, idempotent in each frame — `compose_frame`, `finish`, and `finish_into` call it):

1. World commands went to the world plane at draw time, in send sequence.

2. Entity commands went to the entity plane at draw time.

3. When the lightmap is on and no `otherworld` marks are set, it multiplies only the world plane. Each channel uses `(c * m + 255) >> 8`.

4. The coverage fold: where `min(entity_alpha, coverage) == 255`, the entity pixel replaces the world pixel. The 2 alpha values are binary, thus this is a selection. Entities draw full and are cut only where the rendered world ends. The frame sees them by sensor, not by light.

5. Overlay tasks replay in send sequence: glows add with saturation and the radial falloff (`peak * (1 - dist/r)^2`, no pixels at a radius of 1 or less, cut to the bounds rect of the clip entry). All other overlay tasks are raw color writes, with no light decrease.

6. When the lightmap is on and `otherworld` marks are set, the light multiply runs here, on the full composited frame. Each marked clip fills its blend weight into a mask (a subsequent clip writes on top). Then each pixel multiplies by the blend of the lightmap and the inverse field, `(lm * (255 - m) + iv * m + 127) / 255`, then `(c * field + 255) >> 8`. Entities and overlays in `otherworld` regions become dim with the field — the approved look.

`apply_post(frame, passes)` applies operations to a composited frame. One operation is `source-over` for a color at an alpha, with `SDL` rounding `(s*a + d*(255-a) + 127) / 255`. A `field` operation also scales the alpha for each pixel by the cached vignette (`clamp((dist - 0.20)/0.85) * 190`, truncated). These are the overlays for low health that used `3` to `6 ms` in Python on the heavy frames.

### Caveats

- `Raster::new` stops the program with an assertion on a zero dimension. It does not return an error value.

- `add_xform`, `mark_otherworld`, `set_lightmap`, and `set_texture` have no check after the composite. `draw` and `add_clip` return an error after `finish`. These 4 have no effect on the finished frame, and report no error. `set_texture`, `set_decal_shape`, and `set_decals` continue across frames by decision, thus for them this is safe.

- A missing decal list or shape template draws no pixels and reports no error. The docstrings record this, but this procedure is different from stream errors, which report an error.

- Defect: a field operation in `apply_post` does not clamp the calculated alpha after it multiplies by the vignette. A sufficiently large input alpha can underflow in a debug build or wrap in a release build.

- Textures, decal templates, decal lists, the gradient cache, the vignette, and the inverse field continue across `begin`. Clips, transforms, overlays, `otherworld` marks, the lightmap, and the planes become empty at each `begin`.

## Raster fixtures (`raster_pygame_fixtures.rs`, `gen_fixtures.py`)

### Goal

The fixtures file holds recorded pygame pixels: for each primitive shape, the surface dimensions and the set of lit pixels. The parity tests in `raster.rs` compare against these sets. `gen_fixtures.py` runs an installed pygame and writes a complete fixture file from that run.

### Invariants

- The fixtures come from a pygame run, not from the Rust code that the tests examine.

- A program writes the file, not a person.

### Verification

- The raster fixture tests read each constant in the file.

### Implementation

`gen_fixtures.py` runs with `uv run python engine/necore/gen_fixtures.py`, with `SDL_VIDEODRIVER=dummy`. It draws each shape with RGB channels of 255 on a surface with RGB channels of zero through `pygame.draw` calls. It reads back the lit pixel set, and writes `src/raster_pygame_fixtures.rs`, one constant for each shape: `(width, height, &[(x, y)])`. The shape list includes triangle and general fills, thin and wide lines, polylines, outlines, circles, and rects. General fills include shapes that are not convex, shapes with a notch, and clockwise shapes. Circles include fill, thin, and clipped shapes.

Rects include fill, outlines, and the 2 thin shapes where pygame fills and does not draw borders. The pygame version goes into the file top.

### Caveats

- The recorded pixels lock `pygame-ce 2.5.7`. A run with a different pygame version records the pixels of that version. The file top names the version for that cause.

## The signal field (`signals.rs`)

### Goal

`SignalField` contains the 9 signal types as the engine implementation of `game/perihelion/signals.py`. That Python module stays as the typed facade. This is the one implementation.

Bots read signals as values for each polygon. Each cell keeps the tick of its last change, and exponential decay is calculated directly from elapsed time. Thus a polygon with no updates becomes dim at the same rate as one with updates each tick. Spread runs at a fixed interval independent of the sampling rate.

### Invariants

- This implementation is deterministic: there is no random source or wall clock. Iteration is sorted where sequence changes results. The Rust code follows the Python floating-point operation sequence. No test in this crate compares all output bits with the Python implementation.

- For signal cells, a sample or update is an error when its tick is before the cell's last change. The global spread clock and doorway trails use time differently, as the Caveats tell.

- Values below `1e-5` become zero.

- Spread runs in pieces of 15 ticks (`SPREAD_DT`), in a loop until the field is at the new tick.

### Verification

- No test in this crate reads this module. The code follows the operation sequence of the Python facade, but no code here examines parity.

### Implementation

Constants: `TICK_RATE = 60`, `SPREAD_DT = 15` ticks, `EPS = 1e-5`, `NKINDS = 9`. The type table, in the declaration sequence of the facade:

```
type                 half-life s  spread/s  hop gain
DISTRESS                  45.0      0.12      1.0
DANGER                   180.0      0.0       1.0
NOISE                      3.0      1.20      1.0
TRAIL                     12.0      0.0       1.0
PATROL                    60.0      0.0       1.0
MUSTER                     1.0      1.8       0.35
GARRISON_INTERIOR          1.5      0.9       1.0
GARRISON_REACH             2.0      0.7       1.0
KIN                        8.0      0.45      1.0
```

The decay for one tick of a type is `0.5 ^ (1 / (half_life * 60))`.

- For each type, state has a value list and a list of ticks that record the last changes. Each list has one entry for each polygon. The field also keeps the polygons with signal values, adjacency, polygon count, last spread tick, decay table, and trail map.

- `set_adjacency(adj)` replaces the adjacency. When the adjacency becomes longer, it keeps the cells. New cells receive the last spread tick as the tick of their last change. The facade gives the portal targets of each polygon in edge sequence — the float sequence of spread comes from it. The function does not check neighbor identifiers.

- `materialize(kind, polygon, tick)` applies the decay formula for the time since the last change. It then moves the tick of the last change. `emit` materializes, then adds. A quantity of zero or less, and a polygon out of range, have no effect and report no error. `emit_many` loops `emit`.

- `emit_at_least(kind, polygon, level, tick)` lifts the cell to `level` or more but does not move the tick of its last change. Thus the next materialize step decays the new level from the tick of the last change in that cell.

- `sample`, `sample_all`, and `totals` apply the elapsed-time decay formula and the `EPS` floor. `totals` sums only across polygons that have signal values.

- `deposit_doorway_trail(polygon, edge, amount, tick)` and `doorway_trail` keep a value for each doorway, with a cap of 8 and a half-life of 660 ticks.

- `step_to(tick)` runs `spread_chunk` once for each full `SPREAD_DT` interval.

- `spread_chunk`: the active set is the polygons with nonzero signal values plus their neighbors, sorted. For a type with a zero spread rate, the function only applies elapsed decay to the cells. Otherwise, the flow fraction is `(rate * chunk_seconds).min(0.45)`. The outflow through each doorway is `value * (frac * degree).min(0.9) / degree`. It is calculated from a snapshot and then applied in polygon sequence and edge sequence. Thus all cells update at the same time.

  A receiver gains `per * hop_gain`.

- The `GARRISON_INTERIOR` type uses a different calculation. A polygon that receives flow from 2 or more different neighbors gains `GARRISON_INTERIOR`. A polygon that receives flow from 1 neighbor receives the gain as `GARRISON_REACH`. After the flows, values below `EPS` become zero. The code clears the set of polygons with nonzero signal values and adds the active polygons again.

- `drain(polygon_weights, capacity, tick)`: removes a maximum of `capacity` weighted units across all types, in proportion. The pool reads the weights in sorted polygon sequence and the types in declaration sequence. The scale is `min(capacity / weighted_total, 1)`. Each cut is `value * weight * scale`, and a cell clamps at zero. It returns the sum of the cuts.

### Caveats

- Defect (latent): `set_adjacency` can receive a shorter list. A polygon can keep a signal value after it is no longer in the new list. That condition causes `spread_chunk` to index above the adjacency list limit, and the program stops. The value lists do not become shorter, but the adjacency does. Only the loop that collects neighbors has a bounds check. No caller supplies a shorter adjacency.

- Defect (latent): an adjacency entry can have a neighbor identifier external to the cell arrays. It adds that identifier to the live set. The next call of `materialize` indexes the arrays with it, and the program stops. No caller supplies such an identifier.

- Defect: `step_to` with a tick before `last_spread` returns with no error and does not change the field. `doorway_trail` also accepts a tick before its kept trail tick. It applies a negative decay interval, which increases the reported value above the kept value.

- In `drain`, a weight of more than 1 can cause a cut larger than the cell value. The cell clamps at zero, but the returned sum counts the full cut. Thus the return can be more than the value that left the field.

- `emit_at_least` does not move the tick of the last change. Thus the lifted level starts with some decay applied at the next read. The engine keeps this procedure for parity.

## Deformable walls (`soft.rs`)

### Goal

Deformable polygons are the walls of the `otherworld`: a spring system with damping on the polygon vertices. Edges keep their reference length, read when the polygon becomes deformable. Vertices have no reference position. The spring energy does not change with translation or rotation. Thus a hard hit can move polygons into a new stable shape. The walls only pull to their lengths, not to their initial positions.

### Invariants

- Convexity holds after each step: vertex updates move vertices inward, thus no polygon has a reflex vertex. `visible_set` and physics operate only on convex polygons.

- Portal identification: a portal edge endpoint and its paired endpoint show the same vertex. They show it in 2 polygon coordinate systems. Positions and velocities reconcile through the portal transform each step, and waves cross doorways. The transform is calculated again from the new endpoints. Thus a doorway with changed length stays a correct map.

### Verification

`tests/soft_walls.rs`:

- `impulse_deforms_then_lengths_restore`: an impulse moves the wall more than 1 unit. After 30 seconds, each edge length is in 1.5 units of its reference length.

- `wave_crosses_the_portal`: an impulse far from the doorway moves the vertices of the neighbor polygon.

- `convexity_holds_under_bombardment`: 240 steps of random impulses, and no step shows a reflex vertex.

- `portal_transform_stays_exact_under_deformation`: through 300 steps, the portal maps the endpoints of `b` onto the endpoints of `a` in `1e-6`.

- `hard_hit_reaches_a_new_stable_shape`: the springs become stable. The lengths are near their reference values, but the shape moved — the equilibrium set is degenerate.

- `on_split_array_length_tracks_world_split_edge` records the `on_split` mismatch (refer to the caveats), with a test on the incorrect count that the code calculates.

### Implementation

Constants: `SPRING_K = 26` (endpoint acceleration for each unit of length difference), `DAMPING = 1.9` each second, `MAX_VERT_SPEED = 220`, `MIN_EDGE_LEN = 10` (reference lengths have this floor), `CONVEX_EPS = 0.25` (the movement depth in from the chord).

- `SoftPolygon { rest_len, vel }`. `SoftSystem` maps polygon identifiers to them. `is_soft`, and `soften` (reads the active edge lengths as reference lengths).

- `on_split(world, polygon, edge)`: adds 1 velocity to the list (the mean of the 2 edge endpoints) and divides the reference length of the edge in proportion to the division. Thus the new vertex starts with no length difference.

- `wall_impulse(world, polygon, edge, t, magnitude)`: adds a push opposite to the inward normal to the 2 endpoint velocities of the edge, with the weights `(1 - t, t)`.

- `step(world, dt)` runs 3 phases for all deformable polygons. Phase 1, springs: for each edge, the spring push is `SPRING_K * (length - reference_length)` along the edge, applied in opposite directions to its endpoints. Velocities decay by `(1 - DAMPING * dt)` with a floor of zero, clamp to `MAX_VERT_SPEED`, and integrate. When the kept lists do not agree with the vertex count, the code calls `soften` again as a defense. Velocities then start at zero, and reference lengths come from the active edge lengths.

- Phase 2, portal reconciliation: the side with the smaller identifier processes each portal pair. It does this once if one of the two polygons is deformable. Each pair of related endpoint positions is transformed into one polygon space and averaged. The endpoint sequence changes by `t -> 1-t`. The averaged position is transformed back for the other polygon. Velocities use the same procedure through the `2x2` matrix parts, and `rebuild_portal_pair` fits the transform to the new endpoints.

- Phase 3, convexity: 2 iterations move each reflex vertex onto the chord between its neighbors. They nudge it in by `CONVEX_EPS` and multiply its velocity by `0.5`. Then `refresh_geometry` calculates normals, lengths, and the radius again.

### Caveats

- Defect (latent): `on_split` adds 1 vertex to the deformation lists, but `World::split_edge` adds 2 vertices to the polygon. After a runtime division of a deformable wall, the deformation lists do not agree with the polygon. The defense in `step` (a call to `soften`) then drops the active deformation state without reporting an error. The test records the mismatch as an open defect. No code divides a deformable polygon.

- Defect (latent): a deformable polygon can have a portal to a polygon that is not deformable. Reconciliation moves the vertices of that polygon too. But phase 3 calculates the geometry data again only for deformable polygons. The normals, edge lengths, and radius of the rigid neighbor become expired against its moved vertices. The tests call `soften` on the 2 sides and do not touch this.

- No code connects `on_split` to `World::split_edge`. The caller must call the 2 functions, in that sequence.
