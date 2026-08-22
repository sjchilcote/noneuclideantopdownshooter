//! PyO3 binding layer for necore. Thin: converts between Python-friendly
//! tuples/lists and the core Rust types. All matrices cross the boundary as
//! row-major 9-tuples of floats; all angles are radians; errors become
//! ValueError with a useful message.

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

mod mp4;
mod h264;
mod frames;
mod platform;
mod video;

use frames::{
    frame_err, FrameMismatch, PyCoordinate, PyEntityState, PyOffset, PyRayResult, PySpace, PyTrack,
    PyTransform,
};
use necore_core::frames as core_frames;
use necore_core::{
    develop as core_develop, geom, transform_between as core_transform_between, polygons_within as core_polygons_within,
    raycast as core_raycast, reach as core_reach, route as core_route, routes as core_routes,
    terrain_avoid_dir as core_terrain_avoid_dir, terrain_light_segments as core_terrain_light_segments,
    visible_set as core_visible_set, v, Coordinate, Mat3, Polygon, RayHit, Raster as CoreRaster,
    Router, Sim as CoreSim, Vec2, World,
};

/// Row-major 3x3 homogeneous transform as it crosses the Python boundary.
type M9 = (f64, f64, f64, f64, f64, f64, f64, f64, f64);

fn mat_from_tuple(m: M9) -> Mat3 {
    Mat3 {
        m: [m.0, m.1, m.2, m.3, m.4, m.5, m.6, m.7, m.8],
    }
}

fn mat_to_tuple(m: Mat3) -> M9 {
    let a = m.m;
    (a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8])
}

fn no_polygon(r: usize) -> PyErr {
    PyValueError::new_err(format!("no polygon {r}"))
}

fn no_edge(r: usize, e: usize) -> PyErr {
    PyValueError::new_err(format!("polygon {r} has no edge {e}"))
}

fn no_ent(id: u64) -> PyErr {
    PyValueError::new_err(format!("no entity {id}"))
}

fn world_err(e: necore_core::WorldError) -> PyErr {
    PyValueError::new_err(e.to_string())
}

fn get_polygon(world: &World, r: usize) -> PyResult<&Polygon> {
    world.polygons.get(r).ok_or_else(|| no_polygon(r))
}

/// Engine events, with every position and direction space-tagged.
///
/// The polygon is included on the ones that have one so the game side never has
/// to recover it with a second call — and so the values can be minted in the
/// right space here, at the source, rather than assembled from floats later by
/// code that has to remember which frame they were in.
fn event_to_obj(sim: &CoreSim, py: Python<'_>, ev: necore_core::Event) -> PyObject {
    use necore_core::Event::*;
    let space = |r: usize| -> core_frames::SpaceId {
        sim.world.polygon_space(r).map(|s| s.id()).unwrap_or(0)
    };
    let place = |r: usize, p: Vec2| PyCoordinate::of(Coordinate::new(space(r), p));
    let dir = |r: usize, d: Vec2| PyOffset::of(core_frames::Offset::new(space(r), d));
    match ev {
        Transfer { ent, from, to, edge, xform } => {
            ("transfer", ent, from, to, edge, mat_to_tuple(xform)).into_py(py)
        }
        WallHit { ent, polygon, edge, pos, normal, speed } => (
            "wall", ent, polygon, edge, place(polygon, pos), dir(polygon, normal), speed,
        )
            .into_py(py),
        TerrainHit { ent, polygon, terrain, pos, normal, speed } => (
            "terrain", ent, polygon, terrain, place(polygon, pos), dir(polygon, normal), speed,
        )
            .into_py(py),
        // Entity contact is always WITHIN one polygon (the physics only tests a
        // body against its own polygon's list), so one space serves both bodies
        // and the normal — and the polygon comes from the EVENT, not from
        // either body's current membership, because the rest of the step can
        // move them.
        Contact { a, b, polygon, pos, normal, rel_speed } => (
            "contact", a, b, polygon, place(polygon, pos), dir(polygon, normal),
            rel_speed,
        )
            .into_py(py),
    }
}

#[pyclass]
struct Sim {
    sim: CoreSim,
    router: Router,
}

/// The geometric core shared by `Sim.track_of` and `Sim.sentry_acquire`:
/// pick the physically shortest route from the target's chamber to the
/// observer's, develop the target's position along it, then raycast-confirm
/// the line actually reaches the target (no wallhacks at any depth).
///
/// Returns the sighting in the OBSERVER's space. The route is chosen by TOTAL
/// PHYSICAL DISTANCE, not hop count (query::route): a hop-minimal route can
/// bend somewhere a straight line never goes, and then the composed position
/// lands somewhere the confirming ray refuses — sight that fails for a reason
/// that has nothing to do with the geometry between the two bodies.
///
/// The confirming ray is allowed the same `max_hops` as the compose walk. It
/// used to be hardcoded to 3 while the walk was allowed 12, so a straight
/// sightline down a colonnade of five small chambers composed correctly and
/// was then refused — silent inertness across a doorway, which is the thing
/// this game's own law forbids.
fn track_core(
    sim: &CoreSim,
    observer: u64,
    target: u64,
    group: u8,
    max_hops: usize,
) -> Option<(Coordinate, core_frames::Offset, core_frames::Offset, f64, f64, usize, usize)> {
    let obs = sim.entities.get(&observer)?;
    let tgt = sim.entities.get(&target)?;
    let obs_space = sim.world.polygon_space(obs.polygon)?.id();
    if obs.polygon == tgt.polygon {
        // Same chamber: unconditional. Chambers are convex, so nothing inside
        // one can hide a body.
        let d = (tgt.pos - obs.pos).len();
        return Some((
            Coordinate::new(obs_space, tgt.pos),
            core_frames::Offset::new(obs_space, tgt.vel),
            core_frames::Offset::new(obs_space, tgt.dir),
            d,
            d,
            0,
            tgt.polygon,
        ));
    }
    let tgt_space = sim.world.polygon_space(tgt.polygon)?.id();
    let r = core_route(&sim.world, tgt.polygon, tgt.pos, obs.polygon, max_hops)?;
    let here = Coordinate::new(tgt_space, tgt.pos).extended(&r.steps);
    let vel = core_frames::Offset::new(tgt_space, tgt.vel).extended(&r.steps);
    let facing = core_frames::Offset::new(tgt_space, tgt.dir).extended(&r.steps);
    let dd = here.local() - obs.pos;
    let dl = dd.len().max(1e-6);
    match core_raycast(
        sim,
        obs.polygon,
        obs.pos,
        v(dd.x / dl, dd.y / dl),
        max_hops,
        dl + 40.0,
        1u16 << group,
        Some(observer),
    ) {
        RayHit::Entity { id, .. } if id == target => {}
        _ => return None,
    }
    // The route stops at the last doorway; the leg from there to the observer
    // is the caller's to add, and this is the caller.
    let last_leg = r
        .entry_edge
        .and_then(|e| {
            let polygon = sim.world.polygons.get(obs.polygon)?;
            if e >= polygon.num_edges() {
                return None;
            }
            let (a, b) = polygon.edge(e);
            Some((obs.pos - a.lerp(b, 0.5)).len())
        })
        .unwrap_or(0.0);
    Some((here, vel, facing, dl, r.dist + last_leg, r.steps.len(), tgt.polygon))
}

/// One raycast-confirmed sighting, packaged for Python. The single place a
/// Track is built from the geometry, so every query that reports one — the
/// targeted `track_of` and the neighbourhood sweep
/// `find_closest_faction_member_with_los` — reports the same numbers.
fn sighting(
    sim: &CoreSim,
    observer: u64,
    target: u64,
    group: u8,
    max_hops: usize,
    tick: i64,
) -> Option<PyTrack> {
    track_core(sim, observer, target, group, max_hops).map(
        |(pos, vel, dir, dl, path, depth, polygon)| PyTrack {
            entity_id: target,
            polygon,
            pos,
            vel,
            dir,
            path_distance: path,
            distance: dl,
            portal_depth: depth,
            tick,
        },
    )
}

/// Liang-Barsky segment-vs-AABB — the exact port of sim.py's
/// `_segment_crosses_rect` (the sentry terrain-occlusion test).
fn segment_crosses_rect(
    x1: f64, y1: f64, x2: f64, y2: f64,
    lo_x: f64, lo_y: f64, hi_x: f64, hi_y: f64,
) -> bool {
    let (dx, dy) = (x2 - x1, y2 - y1);
    let (mut t0, mut t1) = (0.0f64, 1.0f64);
    for (p, q) in [
        (-dx, x1 - lo_x),
        (dx, hi_x - x1),
        (-dy, y1 - lo_y),
        (dy, hi_y - y1),
    ] {
        if p.abs() < 1e-12 {
            if q < 0.0 {
                return false;
            }
            continue;
        }
        let r = q / p;
        if p < 0.0 {
            if r > t1 {
                return false;
            }
            if r > t0 {
                t0 = r;
            }
        } else {
            if r < t0 {
                return false;
            }
            if r < t1 {
                t1 = r;
            }
        }
    }
    t0 < t1
}

/// Helpers that are NOT part of the Python surface: the space bookkeeping every
/// coordinate-taking method needs.
impl Sim {
    fn entity_space(&self, id: u64) -> PyResult<core_frames::SpaceId> {
        let e = self.sim.entities.get(&id).ok_or_else(|| no_ent(id))?;
        Ok(self
            .sim
            .world
            .polygon_space(e.polygon)
            .ok_or_else(|| no_polygon(e.polygon))?
            .id())
    }

    fn polygon_for(&self, space: core_frames::SpaceId) -> PyResult<usize> {
        self.sim.world.polygon_of_space(space).ok_or_else(|| {
            FrameMismatch::new_err(format!(
                "{} is not one of this world's polygons, so it names no place \
                 to put a body",
                core_frames::name_of(space)
            ))
        })
    }

    /// An offset that must already be in the body's OWN space. Strict on
    /// purpose: a heading meant for this body should have been computed from
    /// this body's own place, and reconciling silently here would hide the one
    /// case where it was not.
    fn own_offset(&self, id: u64, o: &PyOffset) -> PyResult<Vec2> {
        let space = self.entity_space(id)?;
        if o.inner.space() != space {
            return Err(FrameMismatch::new_err(format!(
                "entity {id} is in {}, but the offset given is in {}",
                core_frames::name_of(space),
                core_frames::name_of(o.inner.space())
            )));
        }
        Ok(o.inner.local())
    }
}

#[pymethods]
impl Sim {
    #[new]
    fn new() -> Self {
        Sim {
            sim: CoreSim::new(World::new()),
            router: Router::new(),
        }
    }

    // --- World construction --------------------------------------------

    fn add_polygon(&mut self, verts: Vec<(f64, f64)>) -> PyResult<usize> {
        let vs: Vec<Vec2> = verts.into_iter().map(|(x, y)| v(x, y)).collect();
        self.sim.world.add_polygon(&vs).map_err(world_err)
    }

    fn connect(&mut self, a: usize, ea: usize, b: usize, eb: usize) -> PyResult<()> {
        self.sim.world.connect(a, ea, b, eb).map_err(world_err)
    }

    fn connect_with_xform(&mut self, a: usize, ea: usize, b: usize, eb: usize, m9: M9) -> PyResult<()> {
        self.sim
            .world
            .connect_with_xform(a, ea, b, eb, mat_from_tuple(m9))
            .map_err(world_err)
    }

    fn disconnect(&mut self, a: usize, ea: usize) -> PyResult<()> {
        self.sim.world.disconnect(a, ea).map_err(world_err)
    }

    /// Split a solid wall edge at parametric (t0, t1); returns the middle
    /// sub-edge index. Portals referencing later edges of this polygon are
    /// remapped internally (+2) — callers keeping (polygon, edge) maps in
    /// Python must apply the same shift.
    fn split_edge(&mut self, polygon: usize, edge: usize, t0: f64, t1: f64) -> PyResult<usize> {
        self.sim.world.split_edge(polygon, edge, t0, t1).map_err(world_err)
    }

    fn num_polygons(&self) -> usize {
        self.sim.world.polygons.len()
    }

    fn polygon_verts(&self, r: usize) -> PyResult<Vec<(f64, f64)>> {
        let polygon = get_polygon(&self.sim.world, r)?;
        Ok(polygon.verts.iter().map(|p| (p.x, p.y)).collect())
    }

    fn polygon_portals(&self, r: usize) -> PyResult<Vec<Option<(usize, usize)>>> {
        let polygon = get_polygon(&self.sim.world, r)?;
        Ok(polygon
            .portals
            .iter()
            .map(|p| p.as_ref().map(|p| (p.target_polygon, p.target_edge)))
            .collect())
    }

    fn portal_xform(&self, r: usize, e: usize) -> PyResult<Option<M9>> {
        let polygon = get_polygon(&self.sim.world, r)?;
        let p = polygon.portals.get(e).ok_or_else(|| no_edge(r, e))?;
        Ok(p.as_ref().map(|p| mat_to_tuple(p.xform)))
    }

    fn edge_endpoints(&self, r: usize, e: usize) -> PyResult<(f64, f64, f64, f64)> {
        let polygon = get_polygon(&self.sim.world, r)?;
        if e >= polygon.num_edges() {
            return Err(no_edge(r, e));
        }
        let (a, b) = polygon.edge(e);
        Ok((a.x, a.y, b.x, b.y))
    }

    /// A doorway's midpoint as a PLACE in that polygon's space — the steering
    /// target when an agent heads for a door. Space-tagged because the whole
    /// point of steering is subtracting it from the agent's own position, and
    /// that subtraction is only meaningful in one space.
    fn edge_midpoint(&self, r: usize, e: usize) -> PyResult<PyCoordinate> {
        let space = self
            .sim
            .world
            .polygon_space(r)
            .ok_or_else(|| no_polygon(r))?
            .id();
        let polygon = get_polygon(&self.sim.world, r)?;
        if e >= polygon.num_edges() {
            return Err(no_edge(r, e));
        }
        let (a, b) = polygon.edge(e);
        Ok(PyCoordinate::of(Coordinate::new(space, a.lerp(b, 0.5))))
    }

    /// The unit INWARD normal of an edge, as a direction in that polygon's
    /// space.
    fn edge_normal(&self, r: usize, e: usize) -> PyResult<PyOffset> {
        let space = self
            .sim
            .world
            .polygon_space(r)
            .ok_or_else(|| no_polygon(r))?
            .id();
        let polygon = get_polygon(&self.sim.world, r)?;
        let n = *polygon.normals.get(e).ok_or_else(|| no_edge(r, e))?;
        Ok(PyOffset::of(core_frames::Offset::new(space, n)))
    }

    // --- Coordinate spaces --------------------------------------------

    /// A polygon's coordinate space. A polygon's frame IS its space; this is
    /// the handle a caller needs to build an Offset in it, or to ask for a
    /// sighting developed into it.
    fn polygon_space(&self, r: usize) -> PyResult<PySpace> {
        Ok(PySpace::of(
            self.sim
                .world
                .polygon_space(r)
                .ok_or_else(|| no_polygon(r))?
                .clone(),
        ))
    }

    /// The place in polygon `r` at local coordinates (x, y).
    ///
    /// THE DOOR FOR AUTHORED DATA. Level files say "polygon 7, at (40, -12)",
    /// and something has to turn that into a place. Note what makes this safe
    /// where a bare `Coordinate(x, y)` would not be: the polygon is named in
    /// the SAME call as the numbers, so the pairing cannot drift. The defect
    /// this whole system targets is numbers whose space was never stated at
    /// all — not numbers whose space is stated out loud.
    fn place(&self, r: usize, x: f64, y: f64) -> PyResult<PyCoordinate> {
        let space = self
            .sim
            .world
            .polygon_space(r)
            .ok_or_else(|| no_polygon(r))?
            .id();
        Ok(PyCoordinate::of(Coordinate::new(space, v(x, y))))
    }

    /// Which polygon a space belongs to, or None for a space this world did
    /// not mint. The inverse of `polygon_space`, and the bridge for channels
    /// that still speak in polygon indices (sound, decals, the fx queue).
    fn polygon_of(&self, space: &PySpace) -> Option<usize> {
        self.sim.world.polygon_of_space(space.inner.id())
    }

    /// A doorway's transform, tagged with the two spaces it maps between: it
    /// takes the NEIGHBOUR's coordinates into polygon `r`'s.
    fn portal_transform(&self, r: usize, e: usize) -> PyResult<Option<PyTransform>> {
        if r >= self.sim.world.polygons.len() {
            return Err(no_polygon(r));
        }
        Ok(self.sim.world.portal_transform(r, e).map(PyTransform::of))
    }

    /// The composed transform between two spaces, along the shortest physical
    /// route — INVERTIBLE, so one topology search answers both directions.
    ///
    /// This is what an operation centred on a place needs when it reaches
    /// through a doorway: a blast measures each body's distance in the blast's
    /// space and pushes each body in the BODY's space, and those are the two
    /// directions of one transform. Two `develop` calls would be two searches
    /// whose routes are not guaranteed to match. It is also how a direction
    /// minted somewhere else travels to where it is needed — a contact normal,
    /// or a shot loosed into a captor standing in the next chamber.
    ///
    /// None when no route exists, or when either space is not one of this
    /// world's polygons.
    fn transform_between(&self, from: &PySpace, into: &PySpace)
                         -> Option<PyTransform> {
        core_transform_between(&self.sim.world, from.inner.id(), into.inner.id())
            .map(PyTransform::of)
    }

    /// Develop a place into another space: the ONE operation here that consults
    /// live topology, which is why it belongs to the world and not to the
    /// coordinate. A deep search for the physically shortest route, then the
    /// transform. `None` when no route exists, or when the target space is not
    /// one of this world's polygons — the screen is a space, and no doorway
    /// reaches it.
    fn develop(&self, c: &PyCoordinate, into: &PySpace) -> Option<PyCoordinate> {
        core_develop(&self.sim.world, &c.inner, into.inner.id()).map(PyCoordinate::of)
    }

    fn polygon_radius(&self, r: usize) -> PyResult<f64> {
        Ok(get_polygon(&self.sim.world, r)?.radius)
    }

    // --- Walk-mask terrain --------------------------------------------

    /// Replace polygon `r`'s walk-mask terrain wholesale: `rects` is a list of
    /// `(lo_x, lo_y, hi_x, hi_y)` axis-aligned rects in the polygon's own local
    /// coordinates (the same frame `polygon_verts`/the floor texture live in).
    /// An empty list clears it back to fully walkable -- absence is the
    /// default (levels.py never calls this when a polygon has no
    /// `<texture>_walkmask.png`).
    fn set_polygon_terrain(&mut self, r: usize, rects: Vec<(f64, f64, f64, f64)>) -> PyResult<()> {
        if r >= self.sim.world.polygons.len() {
            return Err(no_polygon(r));
        }
        let rs: Vec<geom::Rect> = rects
            .into_iter()
            .map(|(lx, ly, hx, hy)| geom::Rect::new(v(lx, ly), v(hx, hy)))
            .collect();
        self.sim
            .world
            .set_polygon_terrain(r, rs)
            .map_err(world_err)
    }

    /// Read back polygon `r`'s current terrain rects (test/tooling use).
    fn polygon_terrain(&self, r: usize) -> PyResult<Vec<(f64, f64, f64, f64)>> {
        let polygon = get_polygon(&self.sim.world, r)?;
        Ok(polygon
            .terrain
            .iter()
            .map(|rect| (rect.lo.x, rect.lo.y, rect.hi.x, rect.hi.y))
            .collect())
    }

    /// Whether entities of `group` are blocked by walk-mask terrain
    /// (blocked by default for every group). Projectiles are terrain-solid
    /// equipment blocks light and shots alike -- pass `blocked=False` for a
    /// group that should be exempt (e.g. a decorative-only particle group).
    fn set_terrain_block(&mut self, group: u8, blocked: bool) {
        self.sim.set_terrain_block(group, blocked);
    }

    /// Light-occlusion INTERFACE ONLY (see ENGINE_DESIGN.md "Walk-mask
    /// terrain & light occlusion"): the terrain edge segments in polygon `r`'s
    /// local coordinates that a future lighting pass should treat as
    /// occluders, same as wall segments. NOT consumed by render.py yet.
    fn terrain_light_segments(&self, r: usize) -> PyResult<Vec<(f64, f64, f64, f64)>> {
        if r >= self.sim.world.polygons.len() {
            return Err(no_polygon(r));
        }
        Ok(core_terrain_light_segments(&self.sim.world, r)
            .into_iter()
            .map(|(a, b)| (a.x, a.y, b.x, b.y))
            .collect())
    }

    /// Steer `(dx, dy)` around walk-mask terrain in polygon `r` so bot AI that
    /// beelines a target doesn't grind forever against an obstacle it
    /// approaches head-on (physics-level wall sliding alone doesn't resolve
    /// that case -- see `query::terrain_avoid_dir`'s doc comment). Returns
    /// a unit vector; pass the result as the entity's desired heading
    /// before scaling by speed and calling `set_vel`.
    #[pyo3(signature = (from, radius, desired, lookahead = 40.0))]
    fn terrain_avoid_dir(
        &self,
        from: &PyCoordinate,
        radius: f64,
        desired: &PyOffset,
        lookahead: f64,
    ) -> PyResult<PyOffset> {
        let space = from.inner.space();
        if desired.inner.space() != space {
            return Err(FrameMismatch::new_err(format!(
                "terrain_avoid_dir: standing in {} but steering in {}",
                core_frames::name_of(space),
                core_frames::name_of(desired.inner.space())
            )));
        }
        let r = self.polygon_for(space)?;
        let out = core_terrain_avoid_dir(
            &self.sim.world,
            r,
            from.inner.local(),
            radius,
            desired.inner.local(),
            lookahead,
        );
        Ok(PyOffset::of(core_frames::Offset::new(space, out)))
    }

    // --- Entities ---------------------------------------------------------

    /// Spawn a body AT a place. The polygon comes from the coordinate's space,
    /// so there is no way to pass a position from one chamber with the index of
    /// another — a pairing nothing checked before.
    fn spawn(&mut self, at: &PyCoordinate, radius: f64, mass: f64, group: u8) -> PyResult<u64> {
        let polygon = self.polygon_for(at.inner.space())?;
        let p = at.inner.local();
        self.sim
            .spawn(polygon, p, radius, mass, group)
            .map_err(PyValueError::new_err)
    }

    fn remove(&mut self, id: u64) {
        self.sim.remove(id);
    }

    fn exists(&self, id: u64) -> bool {
        self.sim.entities.contains_key(&id)
    }

    /// Velocity as an Offset in the body's own space. A velocity is a
    /// difference per unit time, so it transforms by the linear part of a
    /// portal — which is why this cannot be two bare floats whose space
    /// nobody stated.
    fn set_vel(&mut self, id: u64, vel: &PyOffset) -> PyResult<()> {
        let d = self.own_offset(id, vel)?;
        let e = self.sim.entities.get_mut(&id).ok_or_else(|| no_ent(id))?;
        e.vel = d;
        Ok(())
    }

    /// Mass-scaled impulse: dv = J / m — knockback as force through the
    /// physics, never a velocity write.
    fn apply_impulse(&mut self, id: u64, j: &PyOffset) -> PyResult<()> {
        let d = self.own_offset(id, j)?;
        self.sim.apply_impulse(id, d).map_err(PyValueError::new_err)
    }

    /// Mark a polygon's walls soft (Otherworld).
    fn soften_polygon(&mut self, polygon: usize) {
        self.sim.soften_polygon(polygon);
    }

    /// Impulse a soft wall: t in [0,1] along the edge, positive = outward.
    fn soft_wall_impulse(&mut self, polygon: usize, edge: usize, t: f64, magnitude: f64) {
        self.sim.soft_wall_impulse(polygon, edge, t, magnitude);
    }

    /// Teleport within the body's CURRENT chamber. Polygon membership does not
    /// follow a position write (that is a `step` job), so the coordinate must
    /// already be in the body's own space and is refused otherwise.
    fn set_pos(&mut self, id: u64, at: &PyCoordinate) -> PyResult<()> {
        let space = self.entity_space(id)?;
        if at.inner.space() != space {
            return Err(FrameMismatch::new_err(format!(
                "set_pos: entity {id} is in {}, but the position given is in {}",
                core_frames::name_of(space),
                core_frames::name_of(at.inner.space())
            )));
        }
        let p = at.inner.local();
        let e = self.sim.entities.get_mut(&id).ok_or_else(|| no_ent(id))?;
        e.pos = p;
        Ok(())
    }

    fn set_dir(&mut self, id: u64, dir: &PyOffset) -> PyResult<()> {
        let d = self.own_offset(id, dir)?;
        let e = self.sim.entities.get_mut(&id).ok_or_else(|| no_ent(id))?;
        e.dir = d.normalized();
        Ok(())
    }

    #[pyo3(signature = (id, rest_wall=None, rest_ent=None, max_substep=None, transfers=None, radius=None, mass=None, group=None, physical=None))]
    #[allow(clippy::too_many_arguments)]
    fn set_props(
        &mut self,
        id: u64,
        rest_wall: Option<f64>,
        rest_ent: Option<f64>,
        max_substep: Option<f64>,
        transfers: Option<bool>,
        radius: Option<f64>,
        mass: Option<f64>,
        group: Option<u8>,
        physical: Option<bool>,
    ) -> PyResult<()> {
        let e = self.sim.entities.get_mut(&id).ok_or_else(|| no_ent(id))?;
        if let Some(x) = rest_wall {
            e.rest_wall = x;
        }
        if let Some(x) = rest_ent {
            e.rest_ent = x;
        }
        if let Some(x) = max_substep {
            e.max_substep = x;
        }
        if let Some(x) = transfers {
            e.transfers = x;
        }
        if let Some(x) = radius {
            e.radius = x;
        }
        if let Some(x) = mass {
            e.mass = x;
        }
        if let Some(x) = group {
            e.group = x;
        }
        if let Some(x) = physical {
            e.physical = x;
        }
        Ok(())
    }

    /// One body's state at this instant: polygon, place, velocity, facing.
    ///
    /// Replaces the seven-float tuple. Every float in that tuple was a number
    /// with no space attached, and the 28 sites that unpacked it as
    /// `_, ex, ey, *_ =` were free to subtract one body's from another's — how
    /// the Adversary's shove came to aim at nothing (gate 66, p=0.04).
    fn get(&self, id: u64) -> PyResult<PyEntityState> {
        let e = self.sim.entities.get(&id).ok_or_else(|| no_ent(id))?;
        let space = self
            .sim
            .world
            .polygon_space(e.polygon)
            .ok_or_else(|| no_polygon(e.polygon))?
            .id();
        Ok(PyEntityState {
            polygon: e.polygon,
            space,
            pos: e.pos,
            vel: e.vel,
            dir: e.dir,
            radius: e.radius,
        })
    }

    fn get_radius(&self, id: u64) -> PyResult<f64> {
        Ok(self.sim.entities.get(&id).ok_or_else(|| no_ent(id))?.radius)
    }

    fn get_polygon(&self, id: u64) -> PyResult<usize> {
        Ok(self.sim.entities.get(&id).ok_or_else(|| no_ent(id))?.polygon)
    }

    fn polygon_entities(&self, polygon: usize) -> PyResult<Vec<u64>> {
        Ok(get_polygon(&self.sim.world, polygon)?.entities.clone())
    }

    fn set_active_within(&mut self, polygon: usize, hops: usize) -> PyResult<()> {
        if polygon >= self.sim.world.polygons.len() {
            return Err(no_polygon(polygon));
        }
        self.sim.set_active_within(polygon, hops);
        Ok(())
    }
    fn activate_also(&mut self, polygon: usize, hops: usize) -> PyResult<()> {
        if polygon >= self.sim.world.polygons.len() {
            return Err(no_polygon(polygon));
        }
        self.sim.activate_also(polygon, hops);
        Ok(())
    }

    fn set_all_active(&mut self) {
        self.sim.all_active = true;
    }

    fn active_polygons(&self) -> Vec<usize> {
        self.sim.active_polygon_ids()
    }

    // --- Simulation ---------------------------------------------------

    fn step(&mut self, py: Python<'_>, dt: f64) -> Vec<PyObject> {
        let events = self.sim.step(dt);
        events
            .into_iter()
            .map(|e| event_to_obj(&self.sim, py, e))
            .collect()
    }

    // --- Rendering query -------------------------------------------------

    #[pyo3(signature = (camera_polygon, cam_m9, apex_x, apex_y, screen_w, screen_h, max_depth, max_instances))]
    #[allow(clippy::too_many_arguments)]
    fn visible_set(
        &self,
        py: Python<'_>,
        camera_polygon: usize,
        cam_m9: M9,
        apex_x: f64,
        apex_y: f64,
        screen_w: f64,
        screen_h: f64,
        max_depth: usize,
        max_instances: usize,
    ) -> PyResult<Vec<PyObject>> {
        if camera_polygon >= self.sim.world.polygons.len() {
            return Err(no_polygon(camera_polygon));
        }
        let cam = mat_from_tuple(cam_m9);
        let apex = v(apex_x, apex_y);
        let instances = core_visible_set(
            &self.sim.world,
            camera_polygon,
            cam,
            apex,
            screen_w,
            screen_h,
            max_depth,
            max_instances,
        );
        let mut out = Vec::with_capacity(instances.len());
        for inst in instances {
            let polygon = &self.sim.world.polygons[inst.polygon];
            let clip_screen: Vec<(f64, f64)> =
                inst.clip_screen.iter().map(|p| (p.x, p.y)).collect();
            let walls: Vec<(f64, f64, f64, f64, bool)> = inst
                .walls
                .iter()
                .map(|(a, b, portal)| (a.x, a.y, b.x, b.y, *portal))
                .collect();
            let entry_edge: i64 = inst.entry_edge.map(|e| e as i64).unwrap_or(-1);

            let mut ents = Vec::new();
            for &eid in &polygon.entities {
                if let Some(e) = self.sim.entities.get(&eid) {
                    let d = geom::depth_in_polygon(e.pos, &inst.clip_local);
                    if d < -e.radius {
                        continue; // fully outside the visible region
                    }
                    let fully_inside = d >= e.radius;
                    let sp = inst.xform.apply(e.pos);
                    let sd = inst.xform.apply_dir(e.dir).normalized();
                    let sr = e.radius * inst.xform.linear_scale();
                    ents.push((eid, sp.x, sp.y, sd.x, sd.y, sr, fully_inside));
                }
            }
            // Entities STRADDLING a portal from the neighbor's side: their
            // circle pokes into this instance's region, so this instance
            // must draw its share or the body is cut off at the boundary.
            for portal in polygon.portals.iter().flatten() {
                let neighbor = &self.sim.world.polygons[portal.target_polygon];
                for &eid in &neighbor.entities {
                    if let Some(e) = self.sim.entities.get(&eid) {
                        // neighbor-local -> this-polygon-local
                        let p_here = portal.xform.apply(e.pos);
                        let r_here = e.radius * portal.xform.linear_scale();
                        let d = geom::depth_in_polygon(p_here, &inst.clip_local);
                        if d < -r_here || d >= 0.0 {
                            // not reaching in, or its center is on OUR side
                            // (then it lives in our polygon list pass instead)
                            continue;
                        }
                        let sp = inst.xform.apply(p_here);
                        let sd = inst
                            .xform
                            .apply_dir(portal.xform.apply_dir(e.dir))
                            .normalized();
                        let sr = r_here * inst.xform.linear_scale();
                        // never fully_inside: force polygon clipping
                        ents.push((eid, sp.x, sp.y, sd.x, sd.y, sr, false));
                    }
                }
            }

            let tup = (
                inst.polygon,
                mat_to_tuple(inst.xform),
                inst.depth,
                clip_screen,
                walls,
                entry_edge,
                ents,
            )
                .into_py(py);
            out.push(tup);
        }
        Ok(out)
    }

    // --- Queries -----------------------------------------------------

    #[pyo3(signature = (from, dir, max_hops, max_len, mask, ignore=-1))]
    fn raycast(
        &self,
        from: &PyCoordinate,
        dir: &PyOffset,
        max_hops: usize,
        max_len: f64,
        mask: u16,
        ignore: i64,
    ) -> PyResult<PyRayResult> {
        let origin_space = from.inner.space();
        if dir.inner.space() != origin_space {
            return Err(FrameMismatch::new_err(format!(
                "raycast: the origin is in {} but the direction is in {}",
                core_frames::name_of(origin_space),
                core_frames::name_of(dir.inner.space())
            )));
        }
        let polygon = self.polygon_for(origin_space)?;
        let ignore_opt = if ignore < 0 { None } else { Some(ignore as u64) };
        let hit = core_raycast(
            &self.sim,
            polygon,
            from.inner.local(),
            dir.inner.local(),
            max_hops,
            max_len,
            mask,
            ignore_opt,
        );
        let (kind, entity_id, hit_polygon, edge, pos, xform, dist, hops) = match hit {
            RayHit::Wall { polygon, edge, pos, xform, dist, hops } => {
                ("wall", None, polygon, Some(edge), pos, xform, dist, hops)
            }
            RayHit::Entity { id, polygon, pos, xform, dist, hops } => {
                ("ent", Some(id), polygon, None, pos, xform, dist, hops)
            }
            RayHit::Nothing { polygon, pos, xform, dist, hops } => {
                ("none", None, polygon, None, pos, xform, dist, hops)
            }
        };
        let hit_space = self
            .sim
            .world
            .polygon_space(hit_polygon)
            .ok_or_else(|| no_polygon(hit_polygon))?
            .id();
        Ok(PyRayResult {
            kind: kind.to_string(),
            entity_id,
            polygon: hit_polygon,
            edge,
            pos: Coordinate::new(hit_space, pos),
            to_origin: core_frames::Transform::new(
                hit_space,
                origin_space,
                xform,
                "ray composition",
            )
            .map_err(frame_err)?,
            distance: dist,
            hops,
        })
    }

    /// TARGETED sight: a Track, or None.
    ///
    /// The one query that answers "where is that body, from here". The place it
    /// reports is developed into the OBSERVER's own space along the physically
    /// shortest route, and raycast-confirmed, so there are no wallhacks at any
    /// depth. `tick` is stamped on the Track: everything on it was computed at
    /// one instant, and an old sighting read as current is the same silent
    /// wrongness as a frame mismatch, in time instead of space.
    #[pyo3(signature = (observer, target, group, max_hops, tick = 0))]
    fn track_of(
        &self,
        observer: u64,
        target: u64,
        group: u8,
        max_hops: usize,
        tick: i64,
    ) -> PyResult<Option<PyTrack>> {
        if !self.sim.entities.contains_key(&observer) {
            return Err(no_ent(observer));
        }
        if !self.sim.entities.contains_key(&target) {
            return Err(no_ent(target));
        }
        Ok(sighting(&self.sim, observer, target, group, max_hops, tick))
    }

    /// EVERY distinct image of one body, shortest first.
    ///
    /// A portal graph with a loop admits unboundedly many routes, so this takes
    /// a budget and the caller raises it to see further; that is the honest
    /// shape of "the generator may never terminate". Distinct means distinct
    /// developed place: two routes that put the body in the same spot are one
    /// sighting however differently they got there.
    ///
    /// Unlike `track_of` these are NOT raycast-confirmed — an alternate image
    /// is a geometric fact about the world, and a caller asking for all of them
    /// is asking about the geometry, not about what it can shoot.
    #[pyo3(signature = (observer, target, max_hops, max_images, tick = 0))]
    fn tracks_to(
        &self,
        observer: u64,
        target: u64,
        max_hops: usize,
        max_images: usize,
        tick: i64,
    ) -> PyResult<Vec<PyTrack>> {
        let obs = self.sim.entities.get(&observer).ok_or_else(|| no_ent(observer))?;
        let tgt = self.sim.entities.get(&target).ok_or_else(|| no_ent(target))?;
        let obs_space = self
            .sim
            .world
            .polygon_space(obs.polygon)
            .ok_or_else(|| no_polygon(obs.polygon))?
            .id();
        let tgt_space = self
            .sim
            .world
            .polygon_space(tgt.polygon)
            .ok_or_else(|| no_polygon(tgt.polygon))?
            .id();
        let here = Coordinate::new(tgt_space, tgt.pos);
        let here_vel = core_frames::Offset::new(tgt_space, tgt.vel);
        let here_dir = core_frames::Offset::new(tgt_space, tgt.dir);
        let mut out = Vec::new();
        for r in core_routes(
            &self.sim.world,
            tgt.polygon,
            tgt.pos,
            obs.polygon,
            max_hops,
            max_images,
        ) {
            let developed = here.extended(&r.steps);
            let dl = (developed.local() - obs.pos).len();
            let last_leg = r
                .entry_edge
                .and_then(|e| {
                    let polygon = self.sim.world.polygons.get(obs.polygon)?;
                    if e >= polygon.num_edges() {
                        return None;
                    }
                    let (a, b) = polygon.edge(e);
                    Some((obs.pos - a.lerp(b, 0.5)).len())
                })
                .unwrap_or(0.0);
            debug_assert_eq!(developed.space(), obs_space);
            out.push(PyTrack {
                entity_id: target,
                polygon: tgt.polygon,
                pos: developed,
                vel: here_vel.extended(&r.steps),
                dir: here_dir.extended(&r.steps),
                path_distance: r.dist + last_leg,
                distance: dl,
                portal_depth: r.steps.len(),
                tick,
            });
        }
        Ok(out)
    }

    /// The nearest body of `faction` the observer actually has line of sight
    /// to, within `max_range` and `max_hops` doorways. Returns a Track, or
    /// None when the observer's neighbourhood holds no such body.
    ///
    /// This searches the POLYGON GRAPH: one outward walk from the observer
    /// (`query::reach`) develops each chamber it reaches into the observer's
    /// space, and candidates are read out of those chambers' entity indexes.
    /// Cost scales with the observer's neighbourhood, not with the world's
    /// population. The sightline confirmation is a real raycast, run
    /// nearest-first and stopped at the first body that answers, so a clear
    /// shot costs one ray rather than one per body in the level.
    ///
    /// `prefer` is target commitment: a gun already tracking a body keeps it
    /// while it still holds (sighted, in range, unblocked) instead of
    /// swinging to whatever is momentarily closest. Pass 0 for none.
    ///
    /// Same-chamber sightlines must additionally clear that chamber's
    /// walk-mask terrain rects — deeper ones are confirmed by the ray.
    #[pyo3(signature = (observer, faction, max_hops, max_range, tick = 0, prefer = 0))]
    #[allow(clippy::too_many_arguments)]
    fn find_closest_faction_member_with_los(
        &self,
        observer: u64,
        faction: u8,
        max_hops: usize,
        max_range: f64,
        tick: i64,
        prefer: u64,
    ) -> PyResult<Option<PyTrack>> {
        let obs = self.sim.entities.get(&observer).ok_or_else(|| no_ent(observer))?;
        let (r0, o) = (obs.polygon, obs.pos);
        let max_d2 = max_range * max_range;

        if prefer != 0 && prefer != observer && self.sim.entities.contains_key(&prefer) {
            if let Some(t) = sighting(&self.sim, observer, prefer, faction, max_hops, tick) {
                if t.distance * t.distance <= max_d2 {
                    return Ok(Some(t));
                }
            }
        }

        // one walk of the graph, then read the bodies out of what it reached
        let reached = core_reach(&self.sim.world, r0, o, max_hops, max_range);
        let mut candidates: Vec<(f64, u64, usize)> = Vec::new();
        for (i, rr) in reached.iter().enumerate() {
            let Some(polygon) = self.sim.world.polygons.get(rr.polygon) else {
                continue;
            };
            for &eid in &polygon.entities {
                if eid == observer {
                    continue;
                }
                let Some(ent) = self.sim.entities.get(&eid) else {
                    continue;
                };
                if ent.group != faction || !ent.alive {
                    continue;
                }
                let d2 = (rr.into_obs.apply(ent.pos) - o).len2();
                if d2 > max_d2 {
                    continue;
                }
                candidates.push((d2, eid, i));
            }
        }
        // nearest first; ties keep the body the walk reached first
        candidates.sort_by(|a, b| {
            a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal)
        });

        for (d2, eid, i) in candidates {
            let rr = &reached[i];
            let ent = &self.sim.entities[&eid];
            let w = rr.into_obs.apply(ent.pos);
            if rr.depth == 0 {
                let terrain = &get_polygon(&self.sim.world, r0)?.terrain;
                let blocked = terrain.iter().any(|rect| {
                    segment_crosses_rect(
                        o.x, o.y, w.x, w.y, rect.lo.x, rect.lo.y, rect.hi.x, rect.hi.y,
                    )
                });
                if blocked {
                    continue;
                }
            }
            // the walk says a line COULD reach this chamber; the ray says
            // whether it reaches this body
            let _ = d2;
            let Some(t) = sighting(&self.sim, observer, eid, faction, max_hops, tick) else {
                continue;
            };
            return Ok(Some(t));
        }
        Ok(None)
    }


    fn next_edge(&mut self, from_polygon: usize, to_polygon: usize) -> PyResult<i64> {
        if from_polygon >= self.sim.world.polygons.len() {
            return Err(no_polygon(from_polygon));
        }
        if to_polygon >= self.sim.world.polygons.len() {
            return Err(no_polygon(to_polygon));
        }
        Ok(self
            .router
            .next_edge(&self.sim.world, from_polygon, to_polygon)
            .map(|e| e as i64)
            .unwrap_or(-1))
    }

    fn hop_distance(&mut self, a: usize, b: usize) -> PyResult<i64> {
        if a >= self.sim.world.polygons.len() {
            return Err(no_polygon(a));
        }
        if b >= self.sim.world.polygons.len() {
            return Err(no_polygon(b));
        }
        Ok(self
            .router
            .hop_distance(&self.sim.world, a, b)
            .map(|d| d as i64)
            .unwrap_or(-1))
    }

    fn polygons_within(&self, polygon: usize, hops: usize) -> PyResult<Vec<usize>> {
        if polygon >= self.sim.world.polygons.len() {
            return Err(no_polygon(polygon));
        }
        Ok(core_polygons_within(&self.sim.world, polygon, hops))
    }
}

// --- Software rasterizer ---------------------------------------------------

fn raster_err(e: necore_core::RasterError) -> PyErr {
    PyValueError::new_err(e.to_string())
}

/// Copy a typed buffer (array('I')/array('f')/numpy) into a Vec.
/// Zero-length buffers short-circuit to an empty Vec BEFORE the typed
/// extraction: CPython's `array` exposes a dummy, unaligned base pointer for
/// empty arrays, which would otherwise fail pyo3's alignment check — and an
/// empty stream (nothing dynamic this frame) is a legitimate no-op.
fn typed_buffer<T: pyo3::buffer::Element + Copy>(
    py: Python<'_>,
    obj: &Bound<'_, PyAny>,
) -> PyResult<Vec<T>> {
    if obj.len().map(|l| l == 0).unwrap_or(false) {
        return Ok(Vec::new());
    }
    PyBuffer::<T>::get(obj)?.to_vec(py)
}

/// Reinterpret a native-endian byte blob (`array(..).tobytes()` /
/// `numpy .tobytes()`) as 4-byte words. Copies, so alignment never matters.
fn blob_words<T>(name: &str, bytes: &[u8], from: impl Fn([u8; 4]) -> T) -> PyResult<Vec<T>> {
    if bytes.len() % 4 != 0 {
        return Err(PyValueError::new_err(format!(
            "{name}: byte length {} is not a multiple of 4",
            bytes.len()
        )));
    }
    Ok(bytes
        .chunks_exact(4)
        .map(|c| from([c[0], c[1], c[2], c[3]]))
        .collect())
}

/// Display-list software rasterizer with pygame-ce pixel parity (world +
/// entity + coverage-fold + darkness + overlay glows). See
/// necore/src/raster.rs for the wire format and the compositing pipeline.
#[pyclass]
struct Raster {
    r: CoreRaster,
}

#[pymethods]
impl Raster {
    #[new]
    fn new(w: usize, h: usize) -> PyResult<Self> {
        if w == 0 || h == 0 || w > 16384 || h > 16384 {
            return Err(PyValueError::new_err(format!(
                "raster size {w}x{h} out of range (1..=16384 per side)"
            )));
        }
        Ok(Raster {
            r: CoreRaster::new(w, h),
        })
    }

    #[getter]
    fn width(&self) -> usize {
        self.r.width()
    }

    #[getter]
    fn height(&self) -> usize {
        self.r.height()
    }

    /// Start a frame: clear world to `bg_rgba`, entity/coverage to empty,
    /// and reset the clip/xform tables and overlay queue.
    #[pyo3(signature = (bg_rgba = 0x0000_00FF))]
    fn begin(&mut self, bg_rgba: u32) {
        self.r.begin(bg_rgba);
    }

    /// Darkness (lightmap) multiply on/off (off = debug full-bright).
    fn set_darkness(&mut self, on: bool) {
        self.r.set_darkness(on);
    }

    /// Upload this frame's lightmap: RGB8, row-major, `data` a `w*h*3`-byte
    /// buffer (bytes / bytearray / numpy uint8 array) sized to the raster's
    /// own (width, height) -- the world's SOLE illumination when darkness
    /// is on (zero ambient; see raster.rs module docs). Call once per
    /// frame, before `finish`/`finish_into`; skip the call for an all-black
    /// (unlit) world -- `begin()` already reset the map to zero.
    fn set_lightmap(&mut self, py: Python<'_>, data: PyBuffer<u8>) -> PyResult<()> {
        let bytes = data.to_vec(py)?;
        self.r.set_lightmap(&bytes).map_err(raster_err)
    }

    /// Accumulate one world light into the engine lightmap: rasterize the
    /// union of its (pre-filtered, pre-cone-clipped) gate wedges minus its
    /// shadow polys with the pygame-parity fill, multiply by the radial
    /// falloff gradient and the pre-multiplied tint, and saturating-add.
    /// `polys`/`shadows` are flat [x0, y0, ...] f64 sequences; the lens
    /// arrays give each polygon's vertex count.
    #[allow(clippy::too_many_arguments)]
    fn add_light(
        &mut self,
        cx: f64,
        cy: f64,
        radius: f64,
        tint_r: u32,
        tint_g: u32,
        tint_b: u32,
        polys: Vec<f64>,
        poly_lens: Vec<u32>,
        shadows: Vec<f64>,
        shadow_lens: Vec<u32>,
    ) -> PyResult<()> {
        self.r
            .add_light(
                cx, cy, radius, tint_r, tint_g, tint_b, &polys, &poly_lens, &shadows,
                &shadow_lens,
            )
            .map_err(raster_err)
    }

    /// Saturating-add an RGB8 region (row-major, `rh` rows of `rw*3`
    /// bytes) into the lightmap at (x0, y0) — the dynamic glow sprites.
    fn lightmap_add_region(
        &mut self,
        py: Python<'_>,
        x0: usize,
        y0: usize,
        rw: usize,
        rh: usize,
        data: PyBuffer<u8>,
    ) -> PyResult<()> {
        let bytes = data.to_vec(py)?;
        self.r
            .lightmap_add_region(x0, y0, rw, rh, &bytes)
            .map_err(raster_err)
    }

    /// The engine lightmap, row-major RGB8 — read-only accessor for
    /// parity tests and instrumentation.
    fn lightmap_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.r.lightmap_bytes())
    }

    /// Full-frame post passes (low-hp/hurt/death overlays) on a composited
    /// RGBA bytearray, in submission order; `field` passes scale alpha by
    /// the baked vignette falloff. Mutates `frame` in place.
    fn apply_post(
        &mut self,
        frame: &Bound<'_, pyo3::types::PyByteArray>,
        passes: Vec<(u8, u8, u8, u32, bool)>,
    ) -> PyResult<()> {
        // SAFETY: the slice lives only for this call; no Python code runs
        // while we hold it, so the bytearray cannot be resized under us.
        let buf = unsafe { frame.as_bytes_mut() };
        self.r.apply_post(buf, &passes).map_err(raster_err)
    }

    /// Register a local-space decal shape template (flat [x0, y0, ...]).
    fn set_decal_shape(&mut self, id: u32, pts: Vec<f64>) -> PyResult<()> {
        self.r.set_decal_shape(id, &pts).map_err(raster_err)
    }

    /// Upload (or replace) one polygon's RETAINED decal records (12 f64s
    /// each: [style, x, y, size, angle, squash, eff_mul, r, g, b,
    /// shape_id, rot]); OP_DECALS replays them each frame with that
    /// frame's xform/clip. Uploaded only when the list changes.
    fn set_decals(&mut self, list_id: u32, records: Vec<f64>) -> PyResult<()> {
        self.r.set_decals(list_id, &records).map_err(raster_err)
    }

    /// Mark a registered clip's instance as an OTHERWORLD chamber — its
    /// union selects the inverted cold field instead of the lightmap in
    /// the final compose (applied after the entity fold + overlays).
    #[pyo3(signature = (clip_idx, mix = 1.0))]
    fn mark_otherworld(&mut self, clip_idx: u32, mix: f32) -> PyResult<()> {
        self.r.mark_otherworld(clip_idx, mix).map_err(raster_err)
    }

    /// Register an instance's convex screen-space clip polygon — either a
    /// [(x, y), ...] pair list (what `visible()` hands the renderer; no
    /// Python-side flattening) or a flat [x0, y0, x1, y1, ...] sequence.
    /// Returns its clip-table index. With `coverage`, also union-fill it
    /// into the entity coverage mask (the no-seams invariant's mask).
    #[pyo3(signature = (pts, coverage = true))]
    fn add_clip(&mut self, pts: &Bound<'_, PyAny>, coverage: bool) -> PyResult<u32> {
        let flat: Vec<f64> = if let Ok(pairs) = pts.extract::<Vec<(f64, f64)>>() {
            let mut flat = Vec::with_capacity(pairs.len() * 2);
            for (x, y) in pairs {
                flat.push(x);
                flat.push(y);
            }
            flat
        } else {
            pts.extract::<Vec<f64>>().map_err(|_| {
                PyValueError::new_err(
                    "add_clip: pts must be [(x, y), ...] or a flat [x0, y0, ...] float list",
                )
            })?
        };
        self.r.add_clip(&flat, coverage).map_err(raster_err)
    }

    /// Register a row-major Mat3 (the instance xform from visible());
    /// returns its xform-table index.
    fn add_xform(&mut self, m9: M9) -> u32 {
        self.r.add_xform(mat_from_tuple(m9).m)
    }

    /// Upload (or replace) a polygon texture: RGB8, row-major, `data` a
    /// `w*h*3`-byte buffer (bytes / bytearray / numpy uint8 array). Persists
    /// across frames — call once per texture, not per frame. `id` is
    /// caller-chosen (render.py uses the engine polygon index).
    fn set_texture(
        &mut self,
        py: Python<'_>,
        id: u32,
        w: usize,
        h: usize,
        data: PyBuffer<u8>,
    ) -> PyResult<()> {
        let bytes = data.to_vec(py)?;
        self.r.set_texture(id, w, h, &bytes).map_err(raster_err)
    }

    /// Execute a command stream: `cmds` is a u32 buffer (array('I') or numpy
    /// uint32) of 6-word headers, `coords` an f32 buffer (array('f') or
    /// numpy float32) of payload points. Rasterization runs without the GIL.
    fn draw(
        &mut self,
        py: Python<'_>,
        cmds: &Bound<'_, PyAny>,
        coords: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let c: Vec<u32> = typed_buffer(py, cmds)?;
        let f: Vec<f32> = typed_buffer(py, coords)?;
        py.allow_threads(|| self.r.draw(&c, &f)).map_err(raster_err)
    }

    /// Replay a static blob (same wire format as `draw`, as bytes), with
    /// every command's CLIP and XFORM header fields overridden — the
    /// per-polygon detail cache path.
    fn draw_blob(
        &mut self,
        py: Python<'_>,
        cmds: PyBuffer<u8>,
        coords: PyBuffer<u8>,
        xform_idx: u32,
        clip_idx: u32,
    ) -> PyResult<()> {
        let c = blob_words("draw_blob cmds", &cmds.to_vec(py)?, u32::from_ne_bytes)?;
        let f = blob_words("draw_blob coords", &coords.to_vec(py)?, f32::from_ne_bytes)?;
        py.allow_threads(|| self.r.draw_with_overrides(&c, &f, xform_idx, clip_idx))
            .map_err(raster_err)
    }

    /// Composite (entity fold -> darkness -> overlay) and return the frame
    /// as straight RGBA8 bytes, len == w*h*4. Idempotent until `begin`.
    fn finish<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        py.allow_threads(|| {
            self.r.compose_frame();
        });
        PyBytes::new(py, self.r.compose_frame())
    }

    /// `finish`, but written into a caller-owned writable buffer (persistent
    /// bytearray wrapped once with pygame.image.frombuffer -> zero churn).
    fn finish_into(&mut self, py: Python<'_>, out: PyBuffer<u8>) -> PyResult<()> {
        if out.readonly() {
            return Err(PyValueError::new_err("finish_into: buffer is read-only"));
        }
        let want = self.r.width() * self.r.height() * 4;
        if out.item_count() != want {
            return Err(PyValueError::new_err(format!(
                "finish_into: buffer is {} bytes, need {want} (w*h*4)",
                out.item_count()
            )));
        }
        py.allow_threads(|| {
            self.r.compose_frame();
        });
        out.copy_from_slice(py, self.r.compose_frame())
    }
}

// --- Module-level math helpers --------------------------------------------

#[pyfunction]
fn mat_mul(a: M9, b: M9) -> M9 {
    mat_to_tuple(mat_from_tuple(a).mul(mat_from_tuple(b)))
}

#[pyfunction]
fn mat_inv(m: M9) -> PyResult<M9> {
    let mat = mat_from_tuple(m);
    if !mat.is_invertible() {
        return Err(PyValueError::new_err("matrix is not invertible"));
    }
    Ok(mat_to_tuple(mat.inverse()))
}

#[pyfunction]
fn mat_apply(m: M9, x: f64, y: f64) -> (f64, f64) {
    let p = mat_from_tuple(m).apply(v(x, y));
    (p.x, p.y)
}

#[pyfunction]
fn mat_apply_dir(m: M9, x: f64, y: f64) -> (f64, f64) {
    let p = mat_from_tuple(m).apply_dir(v(x, y));
    (p.x, p.y)
}

#[pyfunction]
fn mat_translate(x: f64, y: f64) -> M9 {
    mat_to_tuple(Mat3::translate(v(x, y)))
}

#[pyfunction]
fn mat_rotate(theta: f64) -> M9 {
    mat_to_tuple(Mat3::rotate(theta))
}

#[pyfunction]
fn mat_scale(sx: f64, sy: f64) -> M9 {
    mat_to_tuple(Mat3::scale(sx, sy))
}

#[pyfunction]
fn mat_rotation_angle(m: M9) -> f64 {
    m.3.atan2(m.0)
}

#[pyfunction]
fn mat_identity() -> M9 {
    mat_to_tuple(Mat3::IDENTITY)
}

#[pyfunction]
fn clip_polygon(subject: Vec<(f64, f64)>, clip: Vec<(f64, f64)>) -> Vec<(f64, f64)> {
    let s: Vec<Vec2> = subject.into_iter().map(|(x, y)| v(x, y)).collect();
    let c: Vec<Vec2> = clip.into_iter().map(|(x, y)| v(x, y)).collect();
    geom::clip_polygon_convex(&s, &c)
        .into_iter()
        .map(|p| (p.x, p.y))
        .collect()
}

#[pyfunction]
fn clip_polyline(pts: Vec<(f64, f64)>, clip: Vec<(f64, f64)>) -> Vec<Vec<(f64, f64)>> {
    let p: Vec<Vec2> = pts.into_iter().map(|(x, y)| v(x, y)).collect();
    let c: Vec<Vec2> = clip.into_iter().map(|(x, y)| v(x, y)).collect();
    geom::clip_polyline_convex(&p, &c)
        .into_iter()
        .map(|line| line.into_iter().map(|pt| (pt.x, pt.y)).collect())
        .collect()
}

/// Engine-side nine-field signal substrate (see necore/src/signals.rs —
/// the one implementation; game/perihelion/signals.py is the typed
/// facade). Kinds cross the boundary as their declaration-order index.
#[pyclass]
struct SignalField {
    f: necore_core::CoreSignalField,
}

fn sig_err(e: String) -> PyErr {
    PyValueError::new_err(e)
}

#[pymethods]
impl SignalField {
    #[new]
    #[pyo3(signature = (tick = 0))]
    fn new(tick: i64) -> Self {
        SignalField {
            f: necore_core::CoreSignalField::new(tick),
        }
    }

    fn set_adjacency(&mut self, adj: Vec<Vec<usize>>) {
        self.f.set_adjacency(adj);
    }

    fn emit(&mut self, kind: usize, polygon: i64, amount: f64, tick: i64) -> PyResult<()> {
        self.f.emit(kind, polygon, amount, tick).map_err(sig_err)
    }

    fn emit_many(&mut self, kind: usize, polygons: Vec<i64>, amount: f64, tick: i64) -> PyResult<()> {
        self.f.emit_many(kind, &polygons, amount, tick).map_err(sig_err)
    }

    fn emit_at_least(&mut self, kind: usize, polygon: i64, level: f64, tick: i64) -> PyResult<()> {
        self.f.emit_at_least(kind, polygon, level, tick).map_err(sig_err)
    }

    fn sample(&self, kind: usize, polygon: i64, tick: i64) -> PyResult<f64> {
        self.f.sample(kind, polygon, tick).map_err(sig_err)
    }

    fn sample_all(&self, polygon: i64, tick: i64) -> PyResult<[f64; 9]> {
        self.f.sample_all(polygon, tick).map_err(sig_err)
    }

    fn totals(&self, tick: i64) -> PyResult<[f64; 9]> {
        self.f.totals(tick).map_err(sig_err)
    }

    fn step_to(&mut self, tick: i64) -> PyResult<()> {
        self.f.step_to(tick).map_err(sig_err)
    }

    fn deposit_doorway_trail(&mut self, polygon: usize, edge: usize, amount: f64, tick: i64) {
        self.f.deposit_doorway_trail(polygon, edge, amount, tick);
    }

    fn doorway_trail(&self, polygon: usize, edge: usize, tick: i64) -> f64 {
        self.f.doorway_trail(polygon, edge, tick)
    }

    fn drain(&mut self, polygon_weights: Vec<(i64, f64)>, capacity: f64, tick: i64) -> PyResult<f64> {
        self.f.drain(&polygon_weights, capacity, tick).map_err(sig_err)
    }
}

#[pymodule]
fn necore(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Sim>()?;
    m.add_class::<Raster>()?;
    m.add_class::<PySpace>()?;
    m.add_class::<PyCoordinate>()?;
    m.add_class::<PyOffset>()?;
    m.add_class::<PyTransform>()?;
    m.add_class::<PyEntityState>()?;
    m.add_class::<PyTrack>()?;
    m.add_class::<PyRayResult>()?;
    m.add("FrameMismatch", py.get_type::<FrameMismatch>())?;
    m.add_class::<SignalField>()?;
    m.add_class::<platform::AudioMixer>()?;
    m.add_class::<platform::Window>()?;
    m.add_class::<video::VideoRecorder>()?;
    m.add_function(wrap_pyfunction!(video::read_sidecars, m)?)?;
    m.add_function(wrap_pyfunction!(platform::write_png, m)?)?;
    m.add_function(wrap_pyfunction!(mat_mul, m)?)?;
    m.add_function(wrap_pyfunction!(mat_inv, m)?)?;
    m.add_function(wrap_pyfunction!(mat_apply, m)?)?;
    m.add_function(wrap_pyfunction!(mat_apply_dir, m)?)?;
    m.add_function(wrap_pyfunction!(mat_translate, m)?)?;
    m.add_function(wrap_pyfunction!(mat_rotate, m)?)?;
    m.add_function(wrap_pyfunction!(mat_scale, m)?)?;
    m.add_function(wrap_pyfunction!(mat_rotation_angle, m)?)?;
    m.add_function(wrap_pyfunction!(mat_identity, m)?)?;
    m.add_function(wrap_pyfunction!(clip_polygon, m)?)?;
    m.add_function(wrap_pyfunction!(clip_polyline, m)?)?;
    Ok(())
}
