use std::collections::HashMap;

use crate::frames::{CoordinateSpace, SpaceId, Transform};
use crate::geom;
use crate::math::{Mat3, Vec2};

pub type PolygonId = usize;

#[derive(Debug, Clone, Copy)]
pub struct Portal {
    pub target_polygon: PolygonId,
    pub target_edge: usize,
    /// Maps target-polygon coordinates into THIS polygon's coordinates.
    pub xform: Mat3,
    /// Cached inverse: this-polygon coordinates into target-polygon coordinates.
    pub inv: Mat3,
}

#[derive(Debug, Clone)]
pub struct Polygon {
    /// Canonical winding (y-down visual CCW), centroid at origin.
    pub verts: Vec<Vec2>,
    pub portals: Vec<Option<Portal>>,
    /// Unit inward normals per edge i (verts[i] -> verts[i+1]).
    pub normals: Vec<Vec2>,
    /// Edge lengths.
    pub edge_len: Vec<f64>,
    /// Entity ids currently in this polygon (the spatial index).
    pub entities: Vec<u64>,
    /// Max distance from origin to a vertex (bounding radius).
    pub radius: f64,
    /// Walk-mask terrain: polygon-local axis-aligned rects that block movement
    /// and (via `query::terrain_light_segments`) can occlude light. Empty by
    /// default -- absence means "fully walkable" (no fabricated terrain).
    pub terrain: Vec<geom::Rect>,
}

impl Polygon {
    pub fn edge(&self, i: usize) -> (Vec2, Vec2) {
        let n = self.verts.len();
        (self.verts[i], self.verts[(i + 1) % n])
    }

    /// Recompute normals, edge lengths and bounding radius from current
    /// vertices (soft polygons deform every step).
    pub fn refresh_geometry(&mut self) {
        let n = self.verts.len();
        self.normals.clear();
        self.edge_len.clear();
        for i in 0..n {
            let a = self.verts[i];
            let b = self.verts[(i + 1) % n];
            self.normals.push(geom::inward_normal(a, b));
            self.edge_len.push(a.dist(b));
        }
        self.radius = self.verts.iter().map(|p| p.len()).fold(0.0, f64::max);
    }

    pub fn num_edges(&self) -> usize {
        self.verts.len()
    }
}

#[derive(Debug)]
pub enum WorldError {
    NotConvex,
    TooFewVerts,
    BadPolygon(PolygonId),
    BadEdge(usize),
    EdgeOccupied(PolygonId, usize),
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
    pub polygons: Vec<Polygon>,
    /// Bumped on any topology change; invalidates route caches.
    pub topology_version: u64,
    /// One coordinate space per polygon, parallel to `polygons`. A polygon's
    /// frame IS its space; the ids are what a `Coordinate` carries around so
    /// that two numbers can say whether they are comparable.
    spaces: Vec<CoordinateSpace>,
    /// Reverse map, so a coordinate's space id finds its polygon in O(1).
    /// Spaces the world did not mint (the screen) are simply absent, which is
    /// why `develop` into them answers None rather than guessing.
    by_space: HashMap<SpaceId, PolygonId>,
}

impl World {
    pub fn new() -> World {
        World::default()
    }

    pub fn polygon_space(&self, r: PolygonId) -> Option<&CoordinateSpace> {
        self.spaces.get(r)
    }

    pub fn polygon_of_space(&self, s: SpaceId) -> Option<PolygonId> {
        self.by_space.get(&s).copied()
    }

    /// The transform on edge `ea` of polygon `a`, as a space-tagged Transform:
    /// it maps the NEIGHBOUR's coordinates into `a`'s, matching `Portal::xform`.
    pub fn portal_transform(&self, a: PolygonId, ea: usize) -> Option<Transform> {
        let p = (*self.polygons.get(a)?.portals.get(ea)?)?;
        Transform::new(
            self.spaces.get(p.target_polygon)?.id(),
            self.spaces.get(a)?.id(),
            p.xform,
            format!("portal {a}:{ea}"),
        )
        .ok()
    }

    /// Add a convex polygon. Vertices are re-centered on their centroid and
    /// rewound to canonical winding if needed. Returns the polygon id.
    pub fn add_polygon(&mut self, verts: &[Vec2]) -> Result<PolygonId, WorldError> {
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
        self.polygons.push(Polygon {
            verts: vs,
            portals: vec![None; n],
            normals,
            edge_len,
            entities: Vec::new(),
            radius,
            terrain: Vec::new(),
        });
        let id = self.polygons.len() - 1;
        let space = CoordinateSpace::new(format!("Polygon {id}"));
        self.by_space.insert(space.id(), id);
        self.spaces.push(space);
        self.topology_version += 1;
        Ok(id)
    }

    /// Replace polygon `r`'s walk-mask terrain wholesale (idempotent; an empty
    /// `rects` clears it back to fully-walkable). Polygon-local rects only --
    /// the engine has no world space, so this is automatically root-frame
    /// invariant: collision against it only ever consults the entity's
    /// current polygon and local position (see `physics::Sim::step_entity`),
    /// never anything about how the caller reached that polygon.
    pub fn set_polygon_terrain(&mut self, r: PolygonId, rects: Vec<geom::Rect>) -> Result<(), WorldError> {
        let polygon = self.polygons.get_mut(r).ok_or(WorldError::BadPolygon(r))?;
        polygon.terrain = rects;
        Ok(())
    }

    fn check_edge(&self, r: PolygonId, e: usize) -> Result<(), WorldError> {
        let polygon = self.polygons.get(r).ok_or(WorldError::BadPolygon(r))?;
        if e >= polygon.num_edges() {
            return Err(WorldError::BadEdge(e));
        }
        Ok(())
    }

    /// Connect edge `ea` of polygon `a` to edge `eb` of polygon `b` with the rigid
    /// motion that lays b's edge flush against a's edge, polygons on opposite
    /// sides. Stores mutually inverse transforms on both edges. Handles
    /// self-connection (a == b) and the mirror case (same edge to itself).
    pub fn connect(
        &mut self,
        a: PolygonId,
        ea: usize,
        b: PolygonId,
        eb: usize,
    ) -> Result<(), WorldError> {
        self.check_edge(a, ea)?;
        self.check_edge(b, eb)?;
        if self.polygons[a].portals[ea].is_some() {
            return Err(WorldError::EdgeOccupied(a, ea));
        }
        let mirror = a == b && ea == eb;
        if !mirror && self.polygons[b].portals[eb].is_some() {
            return Err(WorldError::EdgeOccupied(b, eb));
        }

        // Because both polygons wind the same way, glued edges must run in
        // OPPOSITE directions when overlaid (the t -> 1-t flip): a's edge
        // start pairs with b's edge end and vice versa.
        let (pa0, pa1) = self.polygons[a].edge(ea);
        let (pb0, pb1) = self.polygons[b].edge(eb);
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
        // xform maps b-polygon coords -> a-polygon coords: rotate/scale about b's
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

    /// Connect with an arbitrary invertible transform mapping b-polygon coords
    /// into a-polygon coords. The caller is responsible for geometric sanity
    /// (edges coinciding); the engine only requires invertibility.
    /// Rebuild the portal transform pair (a,ea)<->(b,eb) from the CURRENT
    /// edge endpoints, preserving the existing map's handedness. Soft polygons
    /// stretch their doorways; the map must stay exact.
    pub fn rebuild_portal_pair(
        &mut self,
        a: PolygonId,
        ea: usize,
        b: PolygonId,
        eb: usize,
    ) -> Result<(), WorldError> {
        self.check_edge(a, ea)?;
        self.check_edge(b, eb)?;
        let old = match self.polygons[a].portals[ea] {
            Some(p) => p,
            None => return Ok(()),
        };
        let det = old.xform.m[0] * old.xform.m[4] - old.xform.m[1] * old.xform.m[3];
        let (pa0, pa1) = self.polygons[a].edge(ea);
        let (pb0, pb1) = self.polygons[b].edge(eb);
        // complex-plane similarity mapping B1 -> A0 and B0 -> A1.
        let (ax0, ay0, ax1, ay1) = (pa0.x, pa0.y, pa1.x, pa1.y);
        let (bx0, by0, bx1, by1) = (pb0.x, pb0.y, pb1.x, pb1.y);
        let m = if det >= 0.0 {
            // z -> alpha*z + beta; alpha = (A1-A0)/(B0-B1)
            let (nx, ny) = (ax1 - ax0, ay1 - ay0);
            let (dx, dy) = (bx0 - bx1, by0 - by1);
            let dd = dx * dx + dy * dy;
            if dd < 1e-18 {
                return Ok(());
            }
            let ar = (nx * dx + ny * dy) / dd;
            let ai = (ny * dx - nx * dy) / dd;
            let btx = ax0 - (ar * bx1 - ai * by1);
            let bty = ay0 - (ai * bx1 + ar * by1);
            Mat3 {
                m: [ar, -ai, btx, ai, ar, bty, 0.0, 0.0, 1.0],
            }
        } else {
            // z -> alpha*conj(z) + beta; alpha = (A1-A0)/conj(B0-B1)
            let (nx, ny) = (ax1 - ax0, ay1 - ay0);
            let (dx, dy) = (bx0 - bx1, -(by0 - by1));
            let dd = dx * dx + dy * dy;
            if dd < 1e-18 {
                return Ok(());
            }
            let ar = (nx * dx + ny * dy) / dd;
            let ai = (ny * dx - nx * dy) / dd;
            // maps (x,y) -> alpha*(x,-y) + beta
            let btx = ax0 - (ar * bx1 + ai * by1);
            let bty = ay0 - (ai * bx1 - ar * by1);
            Mat3 {
                m: [ar, ai, btx, ai, -ar, bty, 0.0, 0.0, 1.0],
            }
        };
        let inv = m.inverse();
        if let Some(p) = self.polygons[a].portals[ea].as_mut() {
            p.xform = m;
            p.inv = inv;
        }
        if !(a == b && ea == eb) {
            if let Some(p) = self.polygons[b].portals[eb].as_mut() {
                p.xform = inv;
                p.inv = m;
            }
        }
        Ok(())
    }

    pub fn connect_with_xform(
        &mut self,
        a: PolygonId,
        ea: usize,
        b: PolygonId,
        eb: usize,
        m: Mat3,
    ) -> Result<(), WorldError> {
        self.check_edge(a, ea)?;
        self.check_edge(b, eb)?;
        if !m.is_invertible() {
            return Err(WorldError::NotInvertible);
        }
        let mirror = a == b && ea == eb;
        if self.polygons[a].portals[ea].is_some() {
            return Err(WorldError::EdgeOccupied(a, ea));
        }
        if !mirror && self.polygons[b].portals[eb].is_some() {
            return Err(WorldError::EdgeOccupied(b, eb));
        }
        self.install_portal(a, ea, b, eb, m, mirror)
    }

    fn install_portal(
        &mut self,
        a: PolygonId,
        ea: usize,
        b: PolygonId,
        eb: usize,
        m: Mat3,
        mirror: bool,
    ) -> Result<(), WorldError> {
        if !m.is_invertible() {
            return Err(WorldError::NotInvertible);
        }
        let inv = m.inverse();
        self.polygons[a].portals[ea] = Some(Portal {
            target_polygon: b,
            target_edge: eb,
            xform: m,
            inv,
        });
        if !mirror {
            self.polygons[b].portals[eb] = Some(Portal {
                target_polygon: a,
                target_edge: ea,
                xform: inv,
                inv: m,
            });
        }
        self.topology_version += 1;
        Ok(())
    }

    pub fn disconnect(&mut self, a: PolygonId, ea: usize) -> Result<(), WorldError> {
        self.check_edge(a, ea)?;
        if let Some(p) = self.polygons[a].portals[ea].take() {
            if !(p.target_polygon == a && p.target_edge == ea) {
                self.polygons[p.target_polygon].portals[p.target_edge] = None;
            }
            self.topology_version += 1;
        }
        Ok(())
    }

    /// Split a SOLID wall edge into three collinear sub-edges by inserting
    /// vertices at parametric t0 < t1 along it. Every portal in the world
    /// that references a later edge of this polygon is remapped (+2). Returns
    /// the edge index of the middle sub-segment (the doorway-to-be).
    /// Collinear vertices keep the polygon convex; this is the runtime
    /// counterpart of the level builder's doorway splitter, and what the
    /// portable hole is made of.
    pub fn split_edge(
        &mut self,
        r: PolygonId,
        e: usize,
        t0: f64,
        t1: f64,
    ) -> Result<usize, WorldError> {
        self.check_edge(r, e)?;
        if self.polygons[r].portals[e].is_some() {
            return Err(WorldError::EdgeOccupied(r, e));
        }
        if !(t0 > 1e-6 && t1 < 1.0 - 1e-6 && t1 - t0 > 1e-6) {
            return Err(WorldError::DegenerateEdge);
        }
        let (a, b) = self.polygons[r].edge(e);
        let p0 = a.lerp(b, t0);
        let p1 = a.lerp(b, t1);
        let n = geom::inward_normal(a, b);
        let len = self.polygons[r].edge_len[e];

        // insert vertices after position e
        let polygon = &mut self.polygons[r];
        polygon.verts.insert(e + 1, p1);
        polygon.verts.insert(e + 1, p0);
        // edge e keeps its wall status; two new edges inherit wall (None)
        polygon.portals.insert(e + 1, None);
        polygon.portals.insert(e + 1, None);
        polygon.normals.insert(e + 1, n);
        polygon.normals.insert(e + 1, n);
        polygon.edge_len[e] = len * t0;
        polygon.edge_len.insert(e + 1, len * (t1 - t0));
        polygon.edge_len.insert(e + 2, len * (1.0 - t1));

        // remap every portal (anywhere) that targets a shifted edge of r,
        // and this polygon's own outgoing portal records moved by the inserts.
        let npolygons = self.polygons.len();
        for ri in 0..npolygons {
            for ei in 0..self.polygons[ri].portals.len() {
                if let Some(p) = self.polygons[ri].portals[ei].as_mut() {
                    if p.target_polygon == r && p.target_edge > e {
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
        let a = w.add_polygon(&square_verts(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_polygon(&square_verts(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        let pa = w.polygons[a].portals[2].unwrap();
        let pb = w.polygons[b].portals[0].unwrap();
        let prod = pa.xform.mul(pb.xform);
        for (i, e) in Mat3::IDENTITY.m.iter().enumerate() {
            assert!((prod.m[i] - e).abs() < 1e-9);
        }
        // orientation flip: a's edge start == image of b's edge end
        let (a0, a1) = w.polygons[a].edge(2);
        let (b0, b1) = w.polygons[b].edge(0);
        assert!(pa.xform.apply(b1).dist(a0) < 1e-9);
        assert!(pa.xform.apply(b0).dist(a1) < 1e-9);
    }

    #[test]
    fn split_edge_inserts_doorway_and_remaps_portals() {
        let mut w = World::new();
        let a = w.add_polygon(&square_verts(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_polygon(&square_verts(0.0, 0.0, 50.0)).unwrap();
        // connect b to a's edge 3 (top); then split a's edge 1 (bottom):
        // edge 3 shifts to 5 and b's paired portal must follow.
        w.connect(a, 3, b, 1).unwrap();
        let mid = w.split_edge(a, 1, 0.4, 0.55).unwrap();
        assert_eq!(mid, 2);
        assert_eq!(w.polygons[a].verts.len(), 6);
        assert!((w.polygons[a].edge_len[1] - 40.0).abs() < 1e-9);
        assert!((w.polygons[a].edge_len[2] - 15.0).abs() < 1e-9);
        assert!((w.polygons[a].edge_len[3] - 45.0).abs() < 1e-9);
        let pb = w.polygons[b].portals[1].unwrap();
        assert_eq!(pb.target_polygon, a);
        assert_eq!(pb.target_edge, 5, "portal into a must be remapped");
        let pa = w.polygons[a].portals[5].unwrap();
        assert_eq!(pa.target_polygon, b);
        // geometry still convex-valid: connect a third polygon to the doorway
        let c = w.add_polygon(&square_verts(0.0, 0.0, 7.5)).unwrap();
        w.connect(a, mid, c, 0).unwrap();
        assert!(w.polygons[a].portals[mid].is_some());
        // splitting an occupied edge is refused
        assert!(w.split_edge(a, mid, 0.3, 0.6).is_err());
    }

    #[test]
    fn mirror_self_connection() {
        let mut w = World::new();
        let a = w.add_polygon(&square_verts(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 1, a, 1).unwrap();
        let p = w.polygons[a].portals[1].unwrap();
        // Crossing a mirror twice must be the identity.
        let twice = p.xform.mul(p.xform);
        for (i, e) in Mat3::IDENTITY.m.iter().enumerate() {
            assert!((twice.m[i] - e).abs() < 1e-9, "{:?}", twice);
        }
    }
}
