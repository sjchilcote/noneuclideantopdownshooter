use crate::geom;
use crate::math::{Mat3, Vec2};

pub type RoomId = usize;

#[derive(Debug, Clone, Copy)]
pub struct Portal {
    pub target_room: RoomId,
    pub target_edge: usize,
    /// Maps target-room coordinates into THIS room's coordinates.
    pub xform: Mat3,
    /// Cached inverse: this-room coordinates into target-room coordinates.
    pub inv: Mat3,
}

#[derive(Debug, Clone)]
pub struct Room {
    /// Canonical winding (y-down visual CCW), centroid at origin.
    pub verts: Vec<Vec2>,
    pub portals: Vec<Option<Portal>>,
    /// Unit inward normals per edge i (verts[i] -> verts[i+1]).
    pub normals: Vec<Vec2>,
    /// Edge lengths.
    pub edge_len: Vec<f64>,
    /// Entity ids currently in this room (the spatial index).
    pub entities: Vec<u64>,
    /// Max distance from origin to a vertex (bounding radius).
    pub radius: f64,
}

impl Room {
    pub fn edge(&self, i: usize) -> (Vec2, Vec2) {
        let n = self.verts.len();
        (self.verts[i], self.verts[(i + 1) % n])
    }

    pub fn num_edges(&self) -> usize {
        self.verts.len()
    }
}

#[derive(Debug)]
pub enum WorldError {
    NotConvex,
    TooFewVerts,
    BadRoom(RoomId),
    BadEdge(usize),
    EdgeOccupied(RoomId, usize),
    NotInvertible,
    DegenerateEdge,
}

impl std::fmt::Display for WorldError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}", self)
    }
}

#[derive(Default)]
pub struct World {
    pub rooms: Vec<Room>,
    /// Bumped on any topology change; invalidates route caches.
    pub topology_version: u64,
}

impl World {
    pub fn new() -> World {
        World::default()
    }

    /// Add a convex room. Vertices are re-centered on their centroid and
    /// rewound to canonical winding if needed. Returns the room id.
    pub fn add_room(&mut self, verts: &[Vec2]) -> Result<RoomId, WorldError> {
        if verts.len() < 3 {
            return Err(WorldError::TooFewVerts);
        }
        let mut vs = verts.to_vec();
        geom::canonicalize_winding(&mut vs);
        if !geom::is_convex(&vs) {
            return Err(WorldError::NotConvex);
        }
        let c = geom::centroid(&vs);
        for p in &mut vs {
            *p = *p - c;
        }
        let n = vs.len();
        let mut normals = Vec::with_capacity(n);
        let mut edge_len = Vec::with_capacity(n);
        for i in 0..n {
            let a = vs[i];
            let b = vs[(i + 1) % n];
            if a.dist(b) < 1e-9 {
                return Err(WorldError::DegenerateEdge);
            }
            normals.push(geom::inward_normal(a, b));
            edge_len.push(a.dist(b));
        }
        let radius = vs.iter().map(|p| p.len()).fold(0.0, f64::max);
        self.rooms.push(Room {
            verts: vs,
            portals: vec![None; n],
            normals,
            edge_len,
            entities: Vec::new(),
            radius,
        });
        self.topology_version += 1;
        Ok(self.rooms.len() - 1)
    }

    fn check_edge(&self, r: RoomId, e: usize) -> Result<(), WorldError> {
        let room = self.rooms.get(r).ok_or(WorldError::BadRoom(r))?;
        if e >= room.num_edges() {
            return Err(WorldError::BadEdge(e));
        }
        Ok(())
    }

    /// Connect edge `ea` of room `a` to edge `eb` of room `b` with the rigid
    /// motion that lays b's edge flush against a's edge, rooms on opposite
    /// sides. Stores mutually inverse transforms on both edges. Handles
    /// self-connection (a == b) and the mirror case (same edge to itself).
    pub fn connect(&mut self, a: RoomId, ea: usize, b: RoomId, eb: usize) -> Result<(), WorldError> {
        self.check_edge(a, ea)?;
        self.check_edge(b, eb)?;
        if self.rooms[a].portals[ea].is_some() {
            return Err(WorldError::EdgeOccupied(a, ea));
        }
        let mirror = a == b && ea == eb;
        if !mirror && self.rooms[b].portals[eb].is_some() {
            return Err(WorldError::EdgeOccupied(b, eb));
        }

        // Because both polygons wind the same way, glued edges must run in
        // OPPOSITE directions when overlaid (the t -> 1-t flip): a's edge
        // start pairs with b's edge end and vice versa.
        let (pa0, pa1) = self.rooms[a].edge(ea);
        let (pb0, pb1) = self.rooms[b].edge(eb);
        let da = pa1 - pa0;
        let db = pb1 - pb0;
        let la = da.len();
        let lb = db.len();

        // Rotation taking -db (b's edge reversed) onto da, plus uniform scale
        // la/lb when lengths differ.
        let ang_a = da.y.atan2(da.x);
        let ang_b = (-db.y).atan2(-db.x);
        let theta = ang_a - ang_b;
        let s = la / lb;
        // xform maps b-room coords -> a-room coords: rotate/scale about b's
        // edge start... build as: translate b's edge END to origin? We need
        // b_edge_end -> a_edge_start correspondence:
        //   M * pb1 == pa0 and M * pb0 == pa1.
        let rot = Mat3::rotate(theta).mul(Mat3::scale(s, s));
        let rb1 = rot.apply(pb1);
        let m = Mat3::translate(pa0 - rb1).mul(rot);
        debug_assert!(m.apply(pb1).dist(pa0) < 1e-6);
        debug_assert!(m.apply(pb0).dist(pa1) < 1e-6 * s.max(1.0));

        self.install_portal(a, ea, b, eb, m, mirror)
    }

    /// Connect with an arbitrary invertible transform mapping b-room coords
    /// into a-room coords. The caller is responsible for geometric sanity
    /// (edges coinciding); the engine only requires invertibility.
    pub fn connect_with_xform(
        &mut self,
        a: RoomId,
        ea: usize,
        b: RoomId,
        eb: usize,
        m: Mat3,
    ) -> Result<(), WorldError> {
        self.check_edge(a, ea)?;
        self.check_edge(b, eb)?;
        if !m.is_invertible() {
            return Err(WorldError::NotInvertible);
        }
        let mirror = a == b && ea == eb;
        if self.rooms[a].portals[ea].is_some() {
            return Err(WorldError::EdgeOccupied(a, ea));
        }
        if !mirror && self.rooms[b].portals[eb].is_some() {
            return Err(WorldError::EdgeOccupied(b, eb));
        }
        self.install_portal(a, ea, b, eb, m, mirror)
    }

    fn install_portal(
        &mut self,
        a: RoomId,
        ea: usize,
        b: RoomId,
        eb: usize,
        m: Mat3,
        mirror: bool,
    ) -> Result<(), WorldError> {
        if !m.is_invertible() {
            return Err(WorldError::NotInvertible);
        }
        let inv = m.inverse();
        self.rooms[a].portals[ea] = Some(Portal {
            target_room: b,
            target_edge: eb,
            xform: m,
            inv,
        });
        if !mirror {
            self.rooms[b].portals[eb] = Some(Portal {
                target_room: a,
                target_edge: ea,
                xform: inv,
                inv: m,
            });
        }
        self.topology_version += 1;
        Ok(())
    }

    pub fn disconnect(&mut self, a: RoomId, ea: usize) -> Result<(), WorldError> {
        self.check_edge(a, ea)?;
        if let Some(p) = self.rooms[a].portals[ea].take() {
            if !(p.target_room == a && p.target_edge == ea) {
                self.rooms[p.target_room].portals[p.target_edge] = None;
            }
            self.topology_version += 1;
        }
        Ok(())
    }

    /// Split a SOLID wall edge into three collinear sub-edges by inserting
    /// vertices at parametric t0 < t1 along it. Every portal in the world
    /// that references a later edge of this room is remapped (+2). Returns
    /// the edge index of the middle sub-segment (the doorway-to-be).
    /// Collinear vertices keep the polygon convex; this is the runtime
    /// counterpart of the level builder's doorway splitter, and what the
    /// portable hole is made of.
    pub fn split_edge(
        &mut self,
        r: RoomId,
        e: usize,
        t0: f64,
        t1: f64,
    ) -> Result<usize, WorldError> {
        self.check_edge(r, e)?;
        if self.rooms[r].portals[e].is_some() {
            return Err(WorldError::EdgeOccupied(r, e));
        }
        if !(t0 > 1e-6 && t1 < 1.0 - 1e-6 && t1 - t0 > 1e-6) {
            return Err(WorldError::DegenerateEdge);
        }
        let (a, b) = self.rooms[r].edge(e);
        let p0 = a.lerp(b, t0);
        let p1 = a.lerp(b, t1);
        let n = geom::inward_normal(a, b);
        let len = self.rooms[r].edge_len[e];

        // insert vertices after position e
        let room = &mut self.rooms[r];
        room.verts.insert(e + 1, p1);
        room.verts.insert(e + 1, p0);
        // edge e keeps its wall status; two new edges inherit wall (None)
        room.portals.insert(e + 1, None);
        room.portals.insert(e + 1, None);
        room.normals.insert(e + 1, n);
        room.normals.insert(e + 1, n);
        room.edge_len[e] = len * t0;
        room.edge_len.insert(e + 1, len * (t1 - t0));
        room.edge_len.insert(e + 2, len * (1.0 - t1));

        // remap every portal (anywhere) that targets a shifted edge of r,
        // and this room's own outgoing portal records moved by the inserts.
        let nrooms = self.rooms.len();
        for ri in 0..nrooms {
            for ei in 0..self.rooms[ri].portals.len() {
                if let Some(p) = self.rooms[ri].portals[ei].as_mut() {
                    if p.target_room == r && p.target_edge > e {
                        p.target_edge += 2;
                    }
                }
            }
        }
        self.topology_version += 1;
        Ok(e + 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::math::v;

    pub fn square_verts(cx: f64, cy: f64, half: f64) -> Vec<Vec2> {
        vec![
            v(cx - half, cy - half),
            v(cx - half, cy + half),
            v(cx + half, cy + half),
            v(cx + half, cy - half),
        ]
    }

    #[test]
    fn connect_produces_mutually_inverse_flush_transforms() {
        let mut w = World::new();
        let a = w.add_room(&square_verts(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_room(&square_verts(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        let pa = w.rooms[a].portals[2].unwrap();
        let pb = w.rooms[b].portals[0].unwrap();
        let prod = pa.xform.mul(pb.xform);
        for (i, e) in Mat3::IDENTITY.m.iter().enumerate() {
            assert!((prod.m[i] - e).abs() < 1e-9);
        }
        // orientation flip: a's edge start == image of b's edge end
        let (a0, a1) = w.rooms[a].edge(2);
        let (b0, b1) = w.rooms[b].edge(0);
        assert!(pa.xform.apply(b1).dist(a0) < 1e-9);
        assert!(pa.xform.apply(b0).dist(a1) < 1e-9);
    }

    #[test]
    fn split_edge_inserts_doorway_and_remaps_portals() {
        let mut w = World::new();
        let a = w.add_room(&square_verts(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_room(&square_verts(0.0, 0.0, 50.0)).unwrap();
        // connect b to a's edge 3 (top); then split a's edge 1 (bottom):
        // edge 3 shifts to 5 and b's paired portal must follow.
        w.connect(a, 3, b, 1).unwrap();
        let mid = w.split_edge(a, 1, 0.4, 0.55).unwrap();
        assert_eq!(mid, 2);
        assert_eq!(w.rooms[a].verts.len(), 6);
        assert!((w.rooms[a].edge_len[1] - 40.0).abs() < 1e-9);
        assert!((w.rooms[a].edge_len[2] - 15.0).abs() < 1e-9);
        assert!((w.rooms[a].edge_len[3] - 45.0).abs() < 1e-9);
        let pb = w.rooms[b].portals[1].unwrap();
        assert_eq!(pb.target_room, a);
        assert_eq!(pb.target_edge, 5, "portal into a must be remapped");
        let pa = w.rooms[a].portals[5].unwrap();
        assert_eq!(pa.target_room, b);
        // geometry still convex-valid: connect a third room to the doorway
        let c = w.add_room(&square_verts(0.0, 0.0, 7.5)).unwrap();
        w.connect(a, mid, c, 0).unwrap();
        assert!(w.rooms[a].portals[mid].is_some());
        // splitting an occupied edge is refused
        assert!(w.split_edge(a, mid, 0.3, 0.6).is_err());
    }

    #[test]
    fn mirror_self_connection() {
        let mut w = World::new();
        let a = w.add_room(&square_verts(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 1, a, 1).unwrap();
        let p = w.rooms[a].portals[1].unwrap();
        // Crossing a mirror twice must be the identity.
        let twice = p.xform.mul(p.xform);
        for (i, e) in Mat3::IDENTITY.m.iter().enumerate() {
            assert!((twice.m[i] - e).abs() < 1e-9, "{:?}", twice);
        }
    }
}
