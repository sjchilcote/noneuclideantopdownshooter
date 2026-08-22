//! Soft polygons: the Otherworld's walls are a damped mass-spring system on
//! the polygon-graph's vertex set.
//!
//! Each soft polygon's edges remember their REST LENGTH (captured when the
//! polygon is softened) but vertices have no rest POSITION — the spring
//! energy is translation- and rotation-invariant, so the equilibrium
//! manifold is degenerate: a hard enough impact can settle a set of polygons
//! into a genuinely new stable configuration, and the walls only ever try
//! to restore their original *lengths*, never their original place.
//!
//! Invariants preserved every step:
//!   - convexity: vertex updates are projected so no polygon goes reflex
//!     (visibility and physics both assume convex polygons);
//!   - portal identification: a portal edge's endpoints are the SAME
//!     quotient vertex seen from two polygon frames. Positions and velocities
//!     are reconciled through the portal transform each step (waves cross
//!     doorways), and the transform itself is recomputed from the fresh
//!     endpoint pair (stretched doorways stay exact maps).

use std::collections::HashMap;

use crate::math::{Mat3, Vec2};
use crate::world::{PolygonId, World};

const SPRING_K: f64 = 26.0; // per-unit-strain acceleration on endpoints
const DAMPING: f64 = 1.9; // s^-1 velocity decay
const MAX_VERT_SPEED: f64 = 220.0;
const MIN_EDGE_LEN: f64 = 10.0;
const CONVEX_EPS: f64 = 0.25; // projection depth inside the (prev,next) chord

#[derive(Debug, Clone, Default)]
pub struct SoftPolygon {
    pub rest_len: Vec<f64>,
    pub vel: Vec<Vec2>,
}

#[derive(Debug, Default)]
pub struct SoftSystem {
    pub polygons: HashMap<PolygonId, SoftPolygon>,
}

impl SoftSystem {
    pub fn is_soft(&self, polygon: PolygonId) -> bool {
        self.polygons.contains_key(&polygon)
    }

    /// Mark a polygon soft, capturing current edge lengths as rest lengths.
    pub fn soften(&mut self, world: &World, polygon: PolygonId) {
        let r = &world.polygons[polygon];
        self.polygons.insert(
            polygon,
            SoftPolygon {
                rest_len: r.edge_len.clone(),
                vel: vec![Vec2 { x: 0.0, y: 0.0 }; r.verts.len()],
            },
        );
    }

    /// A vertex was inserted into `polygon` at edge `edge` (post-split index
    /// layout: edge, edge+1 are the halves). Mirror the split in the soft
    /// state so array shapes stay aligned with the world.
    pub fn on_split(&mut self, world: &World, polygon: PolygonId, edge: usize) {
        if let Some(sr) = self.polygons.get_mut(&polygon) {
            let r = &world.polygons[polygon];
            let prev_vel = sr.vel[edge];
            let next_vel = sr.vel[(edge + 1) % sr.vel.len().max(1)];
            let mid_vel = Vec2 {
                x: (prev_vel.x + next_vel.x) * 0.5,
                y: (prev_vel.y + next_vel.y) * 0.5,
            };
            sr.vel.insert(edge + 1, mid_vel);
            // rest lengths: the split edge's rest splits proportionally to
            // the actual split, so the new vertex is born unstressed along
            // the wall and only the impact impulse moves it.
            let old_rest = sr.rest_len[edge];
            let l0 = r.edge_len[edge];
            let l1 = r.edge_len[edge + 1];
            let total = (l0 + l1).max(1e-9);
            sr.rest_len[edge] = old_rest * (l0 / total);
            sr.rest_len.insert(edge + 1, old_rest * (l1 / total));
        }
    }

    /// Impart an impulse to the wall of a soft polygon. `t` in [0,1] along the
    /// edge; positive `magnitude` pushes the wall OUTWARD (away from the
    /// polygon interior, i.e. against the inward normal).
    pub fn wall_impulse(
        &mut self,
        world: &World,
        polygon: PolygonId,
        edge: usize,
        t: f64,
        magnitude: f64,
    ) {
        let Some(sr) = self.polygons.get_mut(&polygon) else {
            return;
        };
        let r = &world.polygons[polygon];
        if edge >= r.normals.len() {
            return;
        }
        let n = r.normals[edge];
        let push = Vec2 {
            x: -n.x * magnitude,
            y: -n.y * magnitude,
        };
        let i0 = edge;
        let i1 = (edge + 1) % r.verts.len();
        let w1 = t.clamp(0.0, 1.0);
        let w0 = 1.0 - w1;
        sr.vel[i0] = sr.vel[i0] + push * w0;
        sr.vel[i1] = sr.vel[i1] + push * w1;
    }

    /// One integration step over all soft polygons.
    pub fn step(&mut self, world: &mut World, dt: f64) {
        if self.polygons.is_empty() {
            return;
        }
        let ids: Vec<PolygonId> = self.polygons.keys().copied().collect();

        // 1) spring forces + integration, per polygon.
        for &id in &ids {
            let sr = self.polygons.get_mut(&id).unwrap();
            let polygon = &mut world.polygons[id];
            let n = polygon.verts.len();
            if sr.vel.len() != n || sr.rest_len.len() != n {
                // topology changed without on_split (defensive): re-soften.
                sr.rest_len = polygon.edge_len.clone();
                sr.vel = vec![Vec2 { x: 0.0, y: 0.0 }; n];
            }
            let mut acc = vec![Vec2 { x: 0.0, y: 0.0 }; n];
            for i in 0..n {
                let j = (i + 1) % n;
                let d = polygon.verts[j] - polygon.verts[i];
                let len = d.len().max(1e-9);
                let dir = d * (1.0 / len);
                let rest = sr.rest_len[i].max(MIN_EDGE_LEN);
                let stretch = len - rest;
                let f = dir * (SPRING_K * stretch);
                acc[i] = acc[i] + f;
                acc[j] = acc[j] - f;
            }
            let decay = (1.0 - DAMPING * dt).max(0.0);
            for i in 0..n {
                let mut v = (sr.vel[i] + acc[i] * dt) * decay;
                let sp = v.len();
                if sp > MAX_VERT_SPEED {
                    v = v * (MAX_VERT_SPEED / sp);
                }
                sr.vel[i] = v;
                polygon.verts[i] = polygon.verts[i] + v * dt;
            }
        }

        // 2) portal quotient reconciliation: shared endpoints agree in the
        // quotient space, velocities mix through the portal's linear part,
        // and the transform is rebuilt from the fresh endpoint pair.
        for &id in &ids {
            let n_edges = world.polygons[id].verts.len();
            for e in 0..n_edges {
                let Some(p) = world.polygons[id].portals[e] else {
                    continue;
                };
                let (b, eb) = (p.target_polygon, p.target_edge);
                // reconcile each pair once (owner = smaller (polygon,edge))
                if (b, eb) < (id, e) {
                    continue;
                }
                if !self.polygons.contains_key(&id) && !self.polygons.contains_key(&b) {
                    continue;
                }
                self.reconcile_portal(world, id, e, b, eb);
            }
        }

        // 3) convexity projection + refresh derived data.
        for &id in &ids {
            let polygon = &mut world.polygons[id];
            let n = polygon.verts.len();
            for _pass in 0..2 {
                for i in 0..n {
                    let prev = polygon.verts[(i + n - 1) % n];
                    let next = polygon.verts[(i + 1) % n];
                    let v = polygon.verts[i];
                    let cr = (v - prev).cross(next - v);
                    // canonical winding: negative shoelace => convex turns
                    // keep cross <= 0. A positive cross is a reflex vertex.
                    if cr > 0.0 {
                        // project onto the chord, nudged inside.
                        let chord = next - prev;
                        let cl = chord.len().max(1e-9);
                        let dirc = chord * (1.0 / cl);
                        let along = (v - prev).dot(dirc);
                        let base = prev + dirc * along.clamp(0.0, cl);
                        // inward = left of chord for our winding
                        let inward = Vec2 {
                            x: dirc.y,
                            y: -dirc.x,
                        };
                        polygon.verts[i] = base + inward * CONVEX_EPS;
                        if let Some(sr) = self.polygons.get_mut(&id) {
                            sr.vel[i] = sr.vel[i] * 0.5;
                        }
                    }
                }
            }
            polygon.refresh_geometry();
        }
    }

    fn reconcile_portal(&mut self, world: &mut World, a: PolygonId, ea: usize, b: PolygonId, eb: usize) {
        let (pa0, pa1) = world.polygons[a].edge(ea);
        let (pb0, pb1) = world.polygons[b].edge(eb);
        let m = match world.polygons[a].portals[ea] {
            Some(p) => p.xform,
            None => return,
        };
        // correspondence: M*pb1 == pa0, M*pb0 == pa1 (the t -> 1-t flip).
        let qb1 = m.apply(pb1);
        let qb0 = m.apply(pb0);
        let avg0 = (pa0 + qb1) * 0.5;
        let avg1 = (pa1 + qb0) * 0.5;
        {
            let ra = &mut world.polygons[a];
            let na = ra.verts.len();
            ra.verts[ea] = avg0;
            ra.verts[(ea + 1) % na] = avg1;
        }
        let minv = match world.polygons[a].portals[ea] {
            Some(p) => p.inv,
            None => return,
        };
        {
            let rb = &mut world.polygons[b];
            let nb = rb.verts.len();
            rb.verts[eb] = minv.apply(avg1);
            rb.verts[(eb + 1) % nb] = minv.apply(avg0);
        }
        // velocity mixing through the linear parts, so waves cross.
        let a0 = ea;
        let a1 = (ea + 1) % world.polygons[a].verts.len();
        let b0 = eb;
        let b1 = (eb + 1) % world.polygons[b].verts.len();
        let (va0, va1) = {
            let sa = self.polygons.get(&a);
            (
                sa.map_or(Vec2 { x: 0.0, y: 0.0 }, |s| s.vel[a0]),
                sa.map_or(Vec2 { x: 0.0, y: 0.0 }, |s| s.vel[a1]),
            )
        };
        let (vb0, vb1) = {
            let sb = self.polygons.get(&b);
            (
                sb.map_or(Vec2 { x: 0.0, y: 0.0 }, |s| s.vel[b0]),
                sb.map_or(Vec2 { x: 0.0, y: 0.0 }, |s| s.vel[b1]),
            )
        };
        let mixed0 = (va0 + m.apply_dir(vb1)) * 0.5; // a0 <-> b1
        let mixed1 = (va1 + m.apply_dir(vb0)) * 0.5; // a1 <-> b0
        if let Some(sa) = self.polygons.get_mut(&a) {
            sa.vel[a0] = mixed0;
            sa.vel[a1] = mixed1;
        }
        if let Some(sb) = self.polygons.get_mut(&b) {
            sb.vel[b1] = minv.apply_dir(mixed0);
            sb.vel[b0] = minv.apply_dir(mixed1);
        }
        // rebuild the transform from the fresh endpoint pair so the map
        // stays exact as the doorway stretches.
        let _ = world.rebuild_portal_pair(a, ea, b, eb);
    }
}
