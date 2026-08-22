use std::collections::HashSet;

use crate::geom::{self, HalfPlane};
use crate::math::{v, Mat3, Vec2};
use crate::world::{PolygonId, World};

/// A view frustum through a portal, expressed in the CURRENT polygon's local
/// coordinates. The visible region is the intersection of:
///   - the portal half-plane (this polygon's side of its entry edge — oriented by
///     the polygon's own inward edge normal, so it is exact even when the apex
///     sits on the portal line),
///   - the two half-planes bounded by rays apex->a and apex->b (dropped when
///     the apex is collinear with the segment: a genuine 180-degree view).
#[derive(Debug, Clone, Copy)]
pub struct Frustum {
    pub apex: Vec2,
    pub a: Vec2,
    pub b: Vec2,
    pub entry_edge: usize,
    /// Apex was within EDGE_BAND of the portal line: a ~180-degree view where
    /// the bounding rays are meaningless; only the portal plane clips.
    pub wide: bool,
}

/// Distance band around a portal line inside which the view is treated as a
/// full 180-degree fan. Sub-pixel at gameplay zoom; keeps mid-doorway frames
/// seamless instead of dropping the neighbor for one frame.
///
/// MUST STRICTLY EXCEED `sim.py`'s `GameSession._APEX_EPS` (0.75): the
/// camera/light apex the Python side hands to `visible_set` is never the
/// raw physical position, it is `_clamp_apex`'s output, pulled at least
/// `_APEX_EPS` inside the current polygon's polygon on every edge (that
/// margin exists to dodge a DIFFERENT bug -- the apex landing marginally
/// outside the polygon on transfer overshoot and hard-culling the portal
/// behind it, "THE FLICKER"). Concretely: walking straight at a doorway,
/// the apex handed to this traversal is pinned at exactly `_APEX_EPS`
/// from the portal line for every tick right up to the crossing -- it
/// never gets closer, no matter how close the real player gets. If
/// EDGE_BAND <= _APEX_EPS, `wide` (the smooth 180-degree convergence this
/// module promises "instead of dropping the neighbor for one frame") can
/// NEVER trigger on the approach: the non-root render stays a narrow
/// perspective wedge that clips away everything collinear with the
/// portal line (a doorway's own jamb walls, which run along that same
/// line) right up until the physics engine re-roots on the SAME tick the
/// player's collision volume crosses the threshold -- at which point the
/// new-root instance is unclipped and shows the jambs whole. One tick,
/// jamb walls (and the floor band they'd been occluding) pop from absent
/// to fully lit: the root-crossing "line color" flicker (see
/// game/tests/test_root_invariance.py's real-level jamb-reveal case).
/// Keeping EDGE_BAND comfortably above _APEX_EPS guarantees the clamped
/// apex is always already inside the wide band by the time the polygon
/// becomes reachable, so the pre-crossing render has already converged to
/// what root will show -- no pop left to have.
pub const EDGE_BAND: f64 = 1.0;

impl Frustum {
    pub fn half_planes(&self, world: &World, polygon: PolygonId) -> Vec<HalfPlane> {
        let r = &world.polygons[polygon];
        let (e0, _) = r.edge(self.entry_edge);
        let mut hps = Vec::with_capacity(3);
        hps.push(HalfPlane {
            point: e0,
            normal: r.normals[self.entry_edge],
        });
        if self.wide {
            return hps;
        }
        let ra = self.a - self.apex;
        let rb = self.b - self.apex;
        let cr = ra.cross(rb);
        // Collinear apex (standing in the doorway): the two rays no longer
        // bound anything; the portal half-plane alone is the exact answer.
        if cr.abs() > 1e-9 && ra.len2() > 1e-12 && rb.len2() > 1e-12 {
            // Keep the side of ray apex->a that contains b, and vice versa.
            let na = if cr > 0.0 {
                ra.perp_left()
            } else {
                ra.perp_right()
            };
            let nb = if cr > 0.0 {
                rb.perp_right()
            } else {
                rb.perp_left()
            };
            hps.push(HalfPlane {
                point: self.apex,
                normal: na.normalized(),
            });
            hps.push(HalfPlane {
                point: self.apex,
                normal: nb.normalized(),
            });
        }
        hps
    }
}

#[derive(Debug, Clone)]
pub struct PolygonInstance {
    pub polygon: PolygonId,
    /// polygon-local -> screen.
    pub xform: Mat3,
    pub depth: usize,
    /// Visible convex region, polygon-local coordinates.
    pub clip_local: Vec<Vec2>,
    /// Same region mapped to screen coordinates.
    pub clip_screen: Vec<Vec2>,
    /// Per polygon edge: visible span in screen coords + whether it is a portal.
    pub walls: Vec<(Vec2, Vec2, bool)>,
    pub entry_edge: Option<usize>,
    /// The frustum this instance's `clip_local` was clipped against (None
    /// for the camera polygon itself, which is unclipped). Exposed so callers
    /// (tests, tooling) can recompute `Frustum::half_planes` and verify
    /// containment independently of the traversal internals.
    pub frustum: Option<Frustum>,
}

struct Node {
    polygon: PolygonId,
    xform: Mat3,
    /// Portal-chain product WITHOUT the camera (identity at the root).
    /// Dedup keys on this: keying on the composed screen transform made
    /// instance identity camera-dependent, so two distinct portal paths to
    /// the same polygon aliased on some frames and not others as the camera
    /// moved — whole view wedges strobed in and out (the late-game
    /// flicker), and entities at the vanished wedge's boundary rendered
    /// sliced against black.
    rel: Mat3,
    frustum: Option<Frustum>,
    depth: usize,
}

fn quant(x: f64, s: f64) -> i64 {
    (x * s).round() as i64
}

/// Camera-independent instance identity: polygon, quantized portal-chain
/// transform (polygon-local units), entry edge, and the portal segment in the
/// child polygon's OWN frame. Stable across frames; a genuine traversal loop
/// (A->B->A composing to identity) still collides with the root and
/// terminates, exactly as before.
fn dedup_key(polygon: PolygonId, rel: &Mat3, fr: &Option<Frustum>) -> (usize, usize, [i64; 6], [i64; 4]) {
    let m = &rel.m;
    let mk = [
        quant(m[0], 1000.0),
        quant(m[1], 1000.0),
        quant(m[2], 4.0),
        quant(m[3], 1000.0),
        quant(m[4], 1000.0),
        quant(m[5], 4.0),
    ];
    let (edge, sk) = match fr {
        None => (usize::MAX, [i64::MIN, i64::MIN, i64::MIN, i64::MIN]),
        Some(f) => (
            f.entry_edge,
            [
                quant(f.a.x, 4.0),
                quant(f.a.y, 4.0),
                quant(f.b.x, 4.0),
                quant(f.b.y, 4.0),
            ],
        ),
    };
    (polygon, edge, mk, sk)
}

/// Recursive portal traversal. `cam` maps `camera_polygon` local coordinates to
/// screen coordinates; the camera/viewpoint is `apex_local` in that polygon.
/// Returns instances in painter's order (deepest first).
pub fn visible_set(
    world: &World,
    camera_polygon: PolygonId,
    cam: Mat3,
    apex_local: Vec2,
    screen_w: f64,
    screen_h: f64,
    max_depth: usize,
    max_instances: usize,
) -> Vec<PolygonInstance> {
    let mut out: Vec<PolygonInstance> = Vec::new();
    let mut seen: HashSet<(usize, usize, [i64; 6], [i64; 4])> = HashSet::new();
    let mut stack: Vec<Node> = vec![Node {
        polygon: camera_polygon,
        xform: cam,
        rel: Mat3::IDENTITY,
        frustum: None,
        depth: 0,
    }];
    let margin = 4.0;

    while let Some(node) = stack.pop() {
        if out.len() >= max_instances {
            break;
        }
        let polygon = match world.polygons.get(node.polygon) {
            Some(r) => r,
            None => continue,
        };

        // Continuity rule: a dedup collision must never COST COVERAGE.
        // Near-identical instances (two chains whose quantized keys
        // alternate between colliding and not as the apex moves) both
        // EMIT -- identical pixels overdraw harmlessly -- and only
        // recursion is cut, which is all that termination needs. Dropping
        // the emit made wedges pop in and out frame to frame.
        let novel = seen.insert(dedup_key(node.polygon, &node.rel, &node.frustum));

        let hps: Vec<HalfPlane> = match &node.frustum {
            None => Vec::new(),
            Some(f) => f.half_planes(world, node.polygon),
        };
        let mut clip_local = if hps.is_empty() {
            polygon.verts.clone()
        } else {
            geom::clip_polygon(&polygon.verts, &hps)
        };
        // Canonical output contract: no consecutive duplicate vertices
        // (including the first/last wrap pair). Wedge clipping can emit
        // them at frustum/edge intersections, and a zero-length edge in a
        // clip polygon poisons every consumer that builds edge normals
        // (see geom::DEGENERATE_EDGE — this was the decor flicker).
        clip_local.dedup_by(|a, b| a.dist(*b) < geom::DEGENERATE_EDGE);
        while clip_local.len() >= 2
            && clip_local[0].dist(clip_local[clip_local.len() - 1])
                < geom::DEGENERATE_EDGE
        {
            clip_local.pop();
        }
        if clip_local.len() < 3 {
            continue;
        }
        let clip_screen: Vec<Vec2> = clip_local.iter().map(|p| node.xform.apply(*p)).collect();

        // Off-screen cull (children of an off-screen region are also invisible
        // because they lie within this region's frustum projection).
        let (lo, hi) = geom::polygon_bbox(&clip_screen);
        if hi.x < -margin || hi.y < -margin || lo.x > screen_w + margin || lo.y > screen_h + margin
        {
            continue;
        }
        // Degenerate region only (numeric zero): threshold culls of
        // positive-measure regions pop the whole subtree as the region
        // oscillates across the cutoff -- continuity forbids them.
        if geom::signed_area(&clip_screen).abs() < 1e-6 {
            continue;
        }

        // Visible wall spans (edges clipped to the frustum).
        let n = polygon.num_edges();
        let entry_edge = node.frustum.as_ref().map(|f| f.entry_edge);
        let mut walls = Vec::with_capacity(n);
        for i in 0..n {
            let (a, b) = polygon.edge(i);
            let span = if hps.is_empty() {
                Some((a, b))
            } else {
                geom::clip_segment(a, b, &hps)
            };
            if let Some((p, q)) = span {
                if p.dist(q) > 1e-9 {
                    walls.push((
                        node.xform.apply(p),
                        node.xform.apply(q),
                        polygon.portals[i].is_some(),
                    ));
                }
            }
        }

        // Recurse through portals.
        if novel && node.depth < max_depth {
            let apex = match &node.frustum {
                None => apex_local,
                Some(f) => f.apex,
            };
            for i in 0..n {
                if Some(i) == entry_edge {
                    continue;
                }
                let portal = match polygon.portals[i] {
                    Some(p) => p,
                    None => continue,
                };
                let (ea, eb) = polygon.edge(i);
                // Nothing is visible through an edge whose line the apex sits
                // well behind (a straight sight line cannot re-cross a
                // half-plane boundary twice). This is a genuine half-space
                // test and is correct against the INFINITE line: any apex on
                // the far side cannot see through this portal, regardless of
                // how far off to the side it is.
                let apex_d = (apex - ea).dot(polygon.normals[i]);
                if apex_d < -EDGE_BAND {
                    continue;
                }
                // Within EDGE_BAND of the doorway the view through the
                // portal is a full 180-degree fan ("standing in the
                // doorway"). This must be proximity to the SEGMENT, not the
                // infinite line: `apex_d` alone only measures perpendicular
                // distance to the line through (ea, eb), so an apex far
                // outside the segment along its tangential direction --
                // e.g. a deep portal-chain apex that happens to align with
                // this edge's line from way off to the side -- was passing
                // the same test a genuine in-doorway apex passes, handing
                // out an unconstrained 180-degree fan through a portal the
                // apex is nowhere near facing (traced: seed 7 / aggro
                // capture, tick 71, polygon 6 depth-3 entry-0 chain: apex
                // (-52.62, 130.43) landed within EDGE_BAND of the line
                // x=-52.5 while the segment itself only spans y in
                // [-35, 35] -- 95 units off the actual doorway -- and polygon
                // 7 downstream inherited one tick of a polygon-filling wedge
                // where every neighboring tick had a sliver; see
                // visibility::tests::wide_fan_requires_apex_near_segment).
                let edge_vec = eb - ea;
                let elen2 = edge_vec.len2();
                let t = if elen2 > 1e-12 {
                    ((apex - ea).dot(edge_vec) / elen2).clamp(0.0, 1.0)
                } else {
                    0.0
                };
                let closest = ea.lerp(eb, t);
                let wide = apex_d <= EDGE_BAND && (apex - closest).len() <= EDGE_BAND;
                let span = if hps.is_empty() {
                    Some((ea, eb))
                } else {
                    geom::clip_segment(ea, eb, &hps)
                };
                let (sa, sb) = match span {
                    Some(s) => s,
                    None => continue,
                };
                if sa.dist(sb) < 1e-6 {
                    continue;
                }
                // Continuity rule: no threshold culls of positive-measure
                // views. A span is skipped only when exactly degenerate
                // (the world-space 1e-6 check above); a "half-pixel" span
                // must still recurse, or the polygon behind it pops as the
                // span oscillates across the old 0.75px cutoff.
                let ssa = node.xform.apply(sa);
                let ssb = node.xform.apply(sb);
                // Cull spans entirely off-screen: the child's region lies
                // within the wedge apex->span projected beyond the span; a
                // cheap conservative test is the span bbox vs screen, expanded
                // by projecting the wedge forward. Degenerate near the portal
                // line (wide view), where we skip the cull and let the child's
                // own bbox test decide.
                if !wide {
                    let sapex = node.xform.apply(apex);
                    let ext = 4.0 * (screen_w + screen_h);
                    let fa = ssa + (ssa - sapex).normalized() * ext;
                    let fb = ssb + (ssb - sapex).normalized() * ext;
                    let wedge = [ssa, ssb, fb, fa];
                    let (wlo, whi) = geom::polygon_bbox(&wedge);
                    if whi.x < -margin
                        || whi.y < -margin
                        || wlo.x > screen_w + margin
                        || wlo.y > screen_h + margin
                    {
                        continue;
                    }
                }

                let child_xform = node.xform.mul(portal.xform);
                let inv = portal.inv;
                stack.push(Node {
                    polygon: portal.target_polygon,
                    xform: child_xform,
                    rel: node.rel.mul(portal.xform),
                    frustum: Some(Frustum {
                        apex: inv.apply(apex),
                        a: inv.apply(sa),
                        b: inv.apply(sb),
                        entry_edge: portal.target_edge,
                        wide,
                    }),
                    depth: node.depth + 1,
                });
            }
        }

        out.push(PolygonInstance {
            polygon: node.polygon,
            xform: node.xform,
            depth: node.depth,
            clip_local,
            clip_screen,
            walls,
            entry_edge,
            frustum: node.frustum,
        });
    }

    // Painter's order: deepest first. Stable sort keeps traversal order
    // deterministic among equals.
    out.sort_by(|a, b| b.depth.cmp(&a.depth));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn square(cx: f64, cy: f64, half: f64) -> Vec<Vec2> {
        vec![
            v(cx - half, cy - half),
            v(cx - half, cy + half),
            v(cx + half, cy + half),
            v(cx + half, cy - half),
        ]
    }

    fn cam_center(w: f64, h: f64) -> Mat3 {
        Mat3::translate(v(w / 2.0, h / 2.0))
    }

    #[test]
    fn single_polygon_renders_fully() {
        let mut w = World::new();
        let a = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        let vis = visible_set(
            &w,
            a,
            cam_center(800.0, 600.0),
            Vec2::ZERO,
            800.0,
            600.0,
            8,
            64,
        );
        assert_eq!(vis.len(), 1);
        assert_eq!(vis[0].clip_local.len(), 4);
        assert!((geom::signed_area(&vis[0].clip_local).abs() - 10000.0).abs() < 1e-6);
    }

    #[test]
    fn corridor_of_polygons_renders_neighbors() {
        let mut w = World::new();
        let a = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        let c = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        // edge indices for canonical square (see geom tests): 0 left, 1 bottom,
        // 2 right, 3 top -- verts (-,-),(-,+),(+,+),(+,-).
        w.connect(a, 2, b, 0).unwrap();
        w.connect(b, 2, c, 0).unwrap();
        let vis = visible_set(
            &w,
            a,
            cam_center(800.0, 600.0),
            Vec2::ZERO,
            800.0,
            600.0,
            8,
            64,
        );
        let polygons: Vec<PolygonId> = vis.iter().map(|i| i.polygon).collect();
        assert!(
            polygons.contains(&a) && polygons.contains(&b) && polygons.contains(&c),
            "{polygons:?}"
        );
        // Painter's order: c (depth 2) must come before a (depth 0).
        let pos_a = vis.iter().position(|i| i.polygon == a).unwrap();
        let pos_c = vis.iter().position(|i| i.polygon == c).unwrap();
        assert!(pos_c < pos_a);
        // b is seen through a's right edge: its visible region must lie right
        // of the shared edge (x >= 50 in a's frame == screen x >= 450).
        let ib = vis.iter().find(|i| i.polygon == b).unwrap();
        for p in &ib.clip_screen {
            assert!(p.x >= 450.0 - 1e-6, "{:?}", p);
        }
    }

    #[test]
    fn mirror_polygon_terminates() {
        let mut w = World::new();
        let a = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 2, a, 2).unwrap();
        let vis = visible_set(
            &w,
            a,
            cam_center(800.0, 600.0),
            v(10.0, 0.0),
            800.0,
            600.0,
            32,
            512,
        );
        assert!(vis.len() >= 2, "mirror should show reflected copies");
        assert!(vis.len() <= 512);
    }

    #[test]
    fn infinite_corridor_self_loop_terminates_and_repeats() {
        let mut w = World::new();
        let a = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        // Loop right edge to own left edge: an endless corridor of copies.
        w.connect(a, 2, a, 0).unwrap();
        let vis = visible_set(
            &w,
            a,
            cam_center(800.0, 600.0),
            Vec2::ZERO,
            800.0,
            600.0,
            64,
            512,
        );
        // 800px wide screen / 100px polygons => roughly 9 copies, not 512.
        assert!(vis.len() >= 5, "expected several copies, got {}", vis.len());
        assert!(
            vis.len() <= 16,
            "should cull off-screen copies, got {}",
            vis.len()
        );
    }

    #[test]
    fn doorway_apex_sees_whole_neighbor() {
        let mut w = World::new();
        let a = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        // Apex exactly on the shared edge line (x = 50).
        let vis = visible_set(
            &w,
            a,
            cam_center(800.0, 600.0),
            v(50.0, 0.0),
            800.0,
            600.0,
            8,
            64,
        );
        let ib = vis.iter().find(|i| i.polygon == b).expect("b visible");
        // 180-degree view: whole neighbor visible.
        assert!((geom::signed_area(&ib.clip_local).abs() - 10000.0).abs() < 1.0);
    }

    #[test]
    fn wide_fan_requires_apex_near_segment() {
        // Regression for the tick-71 seed-7/aggro pop: an apex can sit
        // within EDGE_BAND of a portal edge's INFINITE line while being
        // far outside the finite SEGMENT along the tangent -- e.g. a
        // heavily-transformed apex several portal hops deep, whose
        // projected position happens to line up with an unrelated edge's
        // extension from way off to the side. The old `wide` test used
        // only the perpendicular line distance and granted a false
        // 180-degree fan (see `doorway_apex_sees_whole_neighbor` above for
        // the LEGITIMATE case this must be distinguished from -- same
        // EDGE_BAND proximity to the line, but apex.y is within the
        // segment there and 450 units outside it here).
        let mut w = World::new();
        let a = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_polygon(&square(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        // Apex is 0.2 units off edge 2's line (x = 50, comfortably inside
        // EDGE_BAND) but 450 units past the doorway segment's y in
        // [-50, 50].
        let vis = visible_set(
            &w,
            a,
            cam_center(800.0, 600.0),
            v(50.2, 500.0),
            800.0,
            600.0,
            8,
            64,
        );
        if let Some(ib) = vis.iter().find(|i| i.polygon == b) {
            // Must NOT be the false 180-degree fan (the full 10000-area
            // polygon, as legitimately granted in doorway_apex_sees_whole_
            // neighbor) -- a grazing view this far off-axis clips to a
            // sliver near the corner the apex is actually looking through.
            let area = geom::signed_area(&ib.clip_local).abs();
            assert!(area < 1000.0, "expected a thin sliver, got area {area}");
        }
    }
}
