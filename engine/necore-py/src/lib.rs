//! PyO3 binding layer for necore. Thin: converts between Python-friendly
//! tuples/lists and the core Rust types. All matrices cross the boundary as
//! row-major 9-tuples of floats; all angles are radians; errors become
//! ValueError with a useful message.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use necore_core::{
    geom, raycast as core_raycast, rooms_within as core_rooms_within,
    visible_set as core_visible_set, v, Mat3, RayHit, Room, Router, Sim as CoreSim, Vec2, World,
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

fn no_room(r: usize) -> PyErr {
    PyValueError::new_err(format!("no room {r}"))
}

fn no_edge(r: usize, e: usize) -> PyErr {
    PyValueError::new_err(format!("room {r} has no edge {e}"))
}

fn no_ent(id: u64) -> PyErr {
    PyValueError::new_err(format!("no entity {id}"))
}

fn world_err(e: necore_core::WorldError) -> PyErr {
    PyValueError::new_err(e.to_string())
}

fn get_room(world: &World, r: usize) -> PyResult<&Room> {
    world.rooms.get(r).ok_or_else(|| no_room(r))
}

fn event_to_obj(py: Python<'_>, ev: necore_core::Event) -> PyObject {
    use necore_core::Event::*;
    match ev {
        Transfer { ent, from, to, edge, xform } => {
            ("transfer", ent, from, to, edge, mat_to_tuple(xform)).into_py(py)
        }
        WallHit { ent, room, edge, pos, normal, speed } => (
            "wall", ent, room, edge, pos.x, pos.y, normal.x, normal.y, speed,
        )
            .into_py(py),
        Contact { a, b, pos, normal, rel_speed } => {
            ("contact", a, b, pos.x, pos.y, normal.x, normal.y, rel_speed).into_py(py)
        }
    }
}

fn rayhit_to_obj(py: Python<'_>, hit: RayHit) -> PyObject {
    match hit {
        RayHit::Wall { room, edge, pos, xform, dist, hops } => {
            ("wall", room, edge, pos.x, pos.y, dist, hops, mat_to_tuple(xform)).into_py(py)
        }
        RayHit::Entity { id, room, pos, xform, dist, hops } => {
            ("ent", id, room, pos.x, pos.y, dist, hops, mat_to_tuple(xform)).into_py(py)
        }
        RayHit::Nothing { room, pos, xform, dist, hops } => {
            ("none", room, pos.x, pos.y, dist, hops, mat_to_tuple(xform)).into_py(py)
        }
    }
}

#[pyclass]
struct Sim {
    sim: CoreSim,
    router: Router,
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

    fn add_room(&mut self, verts: Vec<(f64, f64)>) -> PyResult<usize> {
        let vs: Vec<Vec2> = verts.into_iter().map(|(x, y)| v(x, y)).collect();
        self.sim.world.add_room(&vs).map_err(world_err)
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
    /// sub-edge index. Portals referencing later edges of this room are
    /// remapped internally (+2) — callers keeping (room, edge) maps in
    /// Python must apply the same shift.
    fn split_edge(&mut self, room: usize, edge: usize, t0: f64, t1: f64) -> PyResult<usize> {
        self.sim.world.split_edge(room, edge, t0, t1).map_err(world_err)
    }

    fn num_rooms(&self) -> usize {
        self.sim.world.rooms.len()
    }

    fn room_verts(&self, r: usize) -> PyResult<Vec<(f64, f64)>> {
        let room = get_room(&self.sim.world, r)?;
        Ok(room.verts.iter().map(|p| (p.x, p.y)).collect())
    }

    fn room_portals(&self, r: usize) -> PyResult<Vec<Option<(usize, usize)>>> {
        let room = get_room(&self.sim.world, r)?;
        Ok(room
            .portals
            .iter()
            .map(|p| p.as_ref().map(|p| (p.target_room, p.target_edge)))
            .collect())
    }

    fn portal_xform(&self, r: usize, e: usize) -> PyResult<Option<M9>> {
        let room = get_room(&self.sim.world, r)?;
        let p = room.portals.get(e).ok_or_else(|| no_edge(r, e))?;
        Ok(p.as_ref().map(|p| mat_to_tuple(p.xform)))
    }

    fn edge_endpoints(&self, r: usize, e: usize) -> PyResult<(f64, f64, f64, f64)> {
        let room = get_room(&self.sim.world, r)?;
        if e >= room.num_edges() {
            return Err(no_edge(r, e));
        }
        let (a, b) = room.edge(e);
        Ok((a.x, a.y, b.x, b.y))
    }

    fn edge_midpoint(&self, r: usize, e: usize) -> PyResult<(f64, f64)> {
        let room = get_room(&self.sim.world, r)?;
        if e >= room.num_edges() {
            return Err(no_edge(r, e));
        }
        let (a, b) = room.edge(e);
        let m = a.lerp(b, 0.5);
        Ok((m.x, m.y))
    }

    fn edge_normal(&self, r: usize, e: usize) -> PyResult<(f64, f64)> {
        let room = get_room(&self.sim.world, r)?;
        let n = room.normals.get(e).ok_or_else(|| no_edge(r, e))?;
        Ok((n.x, n.y))
    }

    fn room_radius(&self, r: usize) -> PyResult<f64> {
        Ok(get_room(&self.sim.world, r)?.radius)
    }

    // --- Entities ---------------------------------------------------------

    fn spawn(&mut self, room: usize, x: f64, y: f64, radius: f64, mass: f64, group: u8) -> PyResult<u64> {
        self.sim
            .spawn(room, v(x, y), radius, mass, group)
            .map_err(PyValueError::new_err)
    }

    fn remove(&mut self, id: u64) {
        self.sim.remove(id);
    }

    fn exists(&self, id: u64) -> bool {
        self.sim.entities.contains_key(&id)
    }

    fn set_vel(&mut self, id: u64, vx: f64, vy: f64) -> PyResult<()> {
        let e = self.sim.entities.get_mut(&id).ok_or_else(|| no_ent(id))?;
        e.vel = v(vx, vy);
        Ok(())
    }

    fn set_pos(&mut self, id: u64, x: f64, y: f64) -> PyResult<()> {
        let e = self.sim.entities.get_mut(&id).ok_or_else(|| no_ent(id))?;
        e.pos = v(x, y);
        Ok(())
    }

    fn set_dir(&mut self, id: u64, dx: f64, dy: f64) -> PyResult<()> {
        let e = self.sim.entities.get_mut(&id).ok_or_else(|| no_ent(id))?;
        e.dir = v(dx, dy).normalized();
        Ok(())
    }

    #[pyo3(signature = (id, rest_wall=None, rest_ent=None, max_substep=None, transfers=None, radius=None, mass=None, group=None))]
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
        Ok(())
    }

    fn get(&self, id: u64) -> PyResult<(usize, f64, f64, f64, f64, f64, f64)> {
        let e = self.sim.entities.get(&id).ok_or_else(|| no_ent(id))?;
        Ok((e.room, e.pos.x, e.pos.y, e.vel.x, e.vel.y, e.dir.x, e.dir.y))
    }

    fn get_radius(&self, id: u64) -> PyResult<f64> {
        Ok(self.sim.entities.get(&id).ok_or_else(|| no_ent(id))?.radius)
    }

    fn get_room(&self, id: u64) -> PyResult<usize> {
        Ok(self.sim.entities.get(&id).ok_or_else(|| no_ent(id))?.room)
    }

    fn room_entities(&self, room: usize) -> PyResult<Vec<u64>> {
        Ok(get_room(&self.sim.world, room)?.entities.clone())
    }

    fn set_collision_pair(&mut self, g: u8, h: u8, on: bool) {
        self.sim.set_collision_pair(g, h, on);
    }

    fn set_active_within(&mut self, room: usize, hops: usize) -> PyResult<()> {
        if room >= self.sim.world.rooms.len() {
            return Err(no_room(room));
        }
        self.sim.set_active_within(room, hops);
        Ok(())
    }

    fn set_all_active(&mut self) {
        self.sim.all_active = true;
    }

    // --- Simulation ---------------------------------------------------

    fn step(&mut self, py: Python<'_>, dt: f64) -> Vec<PyObject> {
        self.sim
            .step(dt)
            .into_iter()
            .map(|e| event_to_obj(py, e))
            .collect()
    }

    // --- Rendering query -------------------------------------------------

    #[pyo3(signature = (camera_room, cam_m9, apex_x, apex_y, screen_w, screen_h, max_depth, max_instances))]
    #[allow(clippy::too_many_arguments)]
    fn visible_set(
        &self,
        py: Python<'_>,
        camera_room: usize,
        cam_m9: M9,
        apex_x: f64,
        apex_y: f64,
        screen_w: f64,
        screen_h: f64,
        max_depth: usize,
        max_instances: usize,
    ) -> PyResult<Vec<PyObject>> {
        if camera_room >= self.sim.world.rooms.len() {
            return Err(no_room(camera_room));
        }
        let cam = mat_from_tuple(cam_m9);
        let apex = v(apex_x, apex_y);
        let instances = core_visible_set(
            &self.sim.world,
            camera_room,
            cam,
            apex,
            screen_w,
            screen_h,
            max_depth,
            max_instances,
        );
        let mut out = Vec::with_capacity(instances.len());
        for inst in instances {
            let room = &self.sim.world.rooms[inst.room];
            let clip_screen: Vec<(f64, f64)> =
                inst.clip_screen.iter().map(|p| (p.x, p.y)).collect();
            let walls: Vec<(f64, f64, f64, f64, bool)> = inst
                .walls
                .iter()
                .map(|(a, b, portal)| (a.x, a.y, b.x, b.y, *portal))
                .collect();
            let entry_edge: i64 = inst.entry_edge.map(|e| e as i64).unwrap_or(-1);

            let mut ents = Vec::new();
            for &eid in &room.entities {
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

            let tup = (
                inst.room,
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

    #[pyo3(signature = (room, ox, oy, dx, dy, max_hops, max_len, mask, ignore=-1))]
    #[allow(clippy::too_many_arguments)]
    fn raycast(
        &self,
        py: Python<'_>,
        room: usize,
        ox: f64,
        oy: f64,
        dx: f64,
        dy: f64,
        max_hops: usize,
        max_len: f64,
        mask: u16,
        ignore: i64,
    ) -> PyResult<PyObject> {
        if room >= self.sim.world.rooms.len() {
            return Err(no_room(room));
        }
        let ignore_opt = if ignore < 0 { None } else { Some(ignore as u64) };
        let hit = core_raycast(
            &self.sim,
            room,
            v(ox, oy),
            v(dx, dy),
            max_hops,
            max_len,
            mask,
            ignore_opt,
        );
        Ok(rayhit_to_obj(py, hit))
    }

    fn next_edge(&mut self, from_room: usize, to_room: usize) -> PyResult<i64> {
        if from_room >= self.sim.world.rooms.len() {
            return Err(no_room(from_room));
        }
        if to_room >= self.sim.world.rooms.len() {
            return Err(no_room(to_room));
        }
        Ok(self
            .router
            .next_edge(&self.sim.world, from_room, to_room)
            .map(|e| e as i64)
            .unwrap_or(-1))
    }

    fn hop_distance(&mut self, a: usize, b: usize) -> PyResult<i64> {
        if a >= self.sim.world.rooms.len() {
            return Err(no_room(a));
        }
        if b >= self.sim.world.rooms.len() {
            return Err(no_room(b));
        }
        Ok(self
            .router
            .hop_distance(&self.sim.world, a, b)
            .map(|d| d as i64)
            .unwrap_or(-1))
    }

    fn rooms_within(&self, room: usize, hops: usize) -> PyResult<Vec<usize>> {
        if room >= self.sim.world.rooms.len() {
            return Err(no_room(room));
        }
        Ok(core_rooms_within(&self.sim.world, room, hops))
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

#[pymodule]
fn necore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Sim>()?;
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
