use std::collections::HashSet;

use crate::geom::{self, HalfPlane};
use crate::math::{v, Mat3, Vec2};
use crate::world::{RoomId, World};

/// A view frustum through a portal, expressed in the CURRENT room's local
/// coordinates. The visible region is the intersection of:
///   - the portal half-plane (this room's side of its entry edge — oriented by
///     the room's own inward edge normal, so it is exact even when the apex
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
pub const EDGE_BAND: f64 = 0.5;

impl Frustum {
    pub fn half_planes(&self, world: &World, room: RoomId) -> Vec<HalfPlane> {
        let r = &world.rooms[room];
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
            let na = if cr > 0.0 { ra.perp_left() } else { ra.perp_right() };
            let nb = if cr > 0.0 { rb.perp_right() } else { rb.perp_left() };
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
pub struct RoomInstance {
    pub room: RoomId,
    /// room-local -> screen.
    pub xform: Mat3,
    pub depth: usize,
    /// Visible convex region, room-local coordinates.
    pub clip_local: Vec<Vec2>,
    /// Same region mapped to screen coordinates.
    pub clip_screen: Vec<Vec2>,
    /// Per room edge: visible span in screen coords + whether it is a portal.
    pub walls: Vec<(Vec2, Vec2, bool)>,
    pub entry_edge: Option<usize>,
}

struct Node {
    room: RoomId,
    xform: Mat3,
    frustum: Option<Frustum>,
    depth: usize,
}

fn quant(x: f64, s: f64) -> i64 {
    (x * s).round() as i64
}

fn dedup_key(room: RoomId, xf: &Mat3, fr: &Option<Frustum>) -> (usize, [i64; 6], [i64; 4]) {
    let m = &xf.m;
    let mk = [
        quant(m[0], 1000.0),
        quant(m[1], 1000.0),
        quant(m[2], 4.0),
        quant(m[3], 1000.0),
        quant(m[4], 1000.0),
        quant(m[5], 4.0),
    ];
    let sk = match fr {
        None => [i64::MIN, i64::MIN, i64::MIN, i64::MIN],
        Some(f) => {
            let a = xf.apply(f.a);
            let b = xf.apply(f.b);
            [quant(a.x, 4.0), quant(a.y, 4.0), quant(b.x, 4.0), quant(b.y, 4.0)]
        }
    };
    (room, mk, sk)
}

/// Recursive portal traversal. `cam` maps `camera_room` local coordinates to
/// screen coordinates; the camera/viewpoint is `apex_local` in that room.
/// Returns instances in painter's order (deepest first).
pub fn visible_set(
    world: &World,
    camera_room: RoomId,
    cam: Mat3,
    apex_local: Vec2,
    screen_w: f64,
    screen_h: f64,
    max_depth: usize,
    max_instances: usize,
) -> Vec<RoomInstance> {
    let mut out: Vec<RoomInstance> = Vec::new();
    let mut seen: HashSet<(usize, [i64; 6], [i64; 4])> = HashSet::new();
    let mut stack: Vec<Node> = vec![Node {
        room: camera_room,
        xform: cam,
        frustum: None,
        depth: 0,
    }];
    let margin = 4.0;

    while let Some(node) = stack.pop() {
        if out.len() >= max_instances {
            break;
        }
        let room = match world.rooms.get(node.room) {
            Some(r) => r,
            None => continue,
        };

        let key = dedup_key(node.room, &node.xform, &node.frustum);
        if !seen.insert(key) {
            continue;
        }

        let hps: Vec<HalfPlane> = match &node.frustum {
            None => Vec::new(),
            Some(f) => f.half_planes(world, node.room),
        };
        let clip_local = if hps.is_empty() {
            room.verts.clone()
        } else {
            geom::clip_polygon(&room.verts, &hps)
        };
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
        // Sub-pixel region: nothing to draw or recurse into.
        if geom::signed_area(&clip_screen).abs() < 0.5 {
            continue;
        }

        // Visible wall spans (edges clipped to the frustum).
        let n = room.num_edges();
        let entry_edge = node.frustum.as_ref().map(|f| f.entry_edge);
        let mut walls = Vec::with_capacity(n);
        for i in 0..n {
            let (a, b) = room.edge(i);
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
                        room.portals[i].is_some(),
                    ));
                }
            }
        }

        // Recurse through portals.
        if node.depth < max_depth {
            let apex = match &node.frustum {
                None => apex_local,
                Some(f) => f.apex,
            };
            for i in 0..n {
                if Some(i) == entry_edge {
                    continue;
                }
                let portal = match room.portals[i] {
                    Some(p) => p,
                    None => continue,
                };
                let (ea, eb) = room.edge(i);
                // Nothing is visible through an edge whose line the apex sits
                // well behind (a straight sight line cannot re-cross a
                // half-plane boundary twice). Within EDGE_BAND of the line the
                // view through the portal is a full 180-degree fan.
                let apex_d = (apex - ea).dot(room.normals[i]);
                if apex_d < -EDGE_BAND {
                    continue;
                }
                let wide = apex_d <= EDGE_BAND;
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
                // Skip portals whose visible span projects below a pixel.
                let ssa = node.xform.apply(sa);
                let ssb = node.xform.apply(sb);
                if ssa.dist(ssb) < 0.75 {
                    continue;
                }
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
                    room: portal.target_room,
                    xform: child_xform,
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

        out.push(RoomInstance {
            room: node.room,
            xform: node.xform,
            depth: node.depth,
            clip_local,
            clip_screen,
            walls,
            entry_edge,
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
    fn single_room_renders_fully() {
        let mut w = World::new();
        let a = w.add_room(&square(0.0, 0.0, 50.0)).unwrap();
        let vis = visible_set(&w, a, cam_center(800.0, 600.0), Vec2::ZERO, 800.0, 600.0, 8, 64);
        assert_eq!(vis.len(), 1);
        assert_eq!(vis[0].clip_local.len(), 4);
        assert!((geom::signed_area(&vis[0].clip_local).abs() - 10000.0).abs() < 1e-6);
    }

    #[test]
    fn corridor_of_rooms_renders_neighbors() {
        let mut w = World::new();
        let a = w.add_room(&square(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_room(&square(0.0, 0.0, 50.0)).unwrap();
        let c = w.add_room(&square(0.0, 0.0, 50.0)).unwrap();
        // edge indices for canonical square (see geom tests): 0 left, 1 bottom,
        // 2 right, 3 top -- verts (-,-),(-,+),(+,+),(+,-).
        w.connect(a, 2, b, 0).unwrap();
        w.connect(b, 2, c, 0).unwrap();
        let vis = visible_set(&w, a, cam_center(800.0, 600.0), Vec2::ZERO, 800.0, 600.0, 8, 64);
        let rooms: Vec<RoomId> = vis.iter().map(|i| i.room).collect();
        assert!(rooms.contains(&a) && rooms.contains(&b) && rooms.contains(&c), "{rooms:?}");
        // Painter's order: c (depth 2) must come before a (depth 0).
        let pos_a = vis.iter().position(|i| i.room == a).unwrap();
        let pos_c = vis.iter().position(|i| i.room == c).unwrap();
        assert!(pos_c < pos_a);
        // b is seen through a's right edge: its visible region must lie right
        // of the shared edge (x >= 50 in a's frame == screen x >= 450).
        let ib = vis.iter().find(|i| i.room == b).unwrap();
        for p in &ib.clip_screen {
            assert!(p.x >= 450.0 - 1e-6, "{:?}", p);
        }
    }

    #[test]
    fn mirror_room_terminates() {
        let mut w = World::new();
        let a = w.add_room(&square(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 2, a, 2).unwrap();
        let vis = visible_set(&w, a, cam_center(800.0, 600.0), v(10.0, 0.0), 800.0, 600.0, 32, 512);
        assert!(vis.len() >= 2, "mirror should show reflected copies");
        assert!(vis.len() <= 512);
    }

    #[test]
    fn infinite_corridor_self_loop_terminates_and_repeats() {
        let mut w = World::new();
        let a = w.add_room(&square(0.0, 0.0, 50.0)).unwrap();
        // Loop right edge to own left edge: an endless corridor of copies.
        w.connect(a, 2, a, 0).unwrap();
        let vis = visible_set(&w, a, cam_center(800.0, 600.0), Vec2::ZERO, 800.0, 600.0, 64, 512);
        // 800px wide screen / 100px rooms => roughly 9 copies, not 512.
        assert!(vis.len() >= 5, "expected several copies, got {}", vis.len());
        assert!(vis.len() <= 16, "should cull off-screen copies, got {}", vis.len());
    }

    #[test]
    fn doorway_apex_sees_whole_neighbor() {
        let mut w = World::new();
        let a = w.add_room(&square(0.0, 0.0, 50.0)).unwrap();
        let b = w.add_room(&square(0.0, 0.0, 50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        // Apex exactly on the shared edge line (x = 50).
        let vis = visible_set(&w, a, cam_center(800.0, 600.0), v(50.0, 0.0), 800.0, 600.0, 8, 64);
        let ib = vis.iter().find(|i| i.room == b).expect("b visible");
        // 180-degree view: whole neighbor visible.
        assert!((geom::signed_area(&ib.clip_local).abs() - 10000.0).abs() < 1.0);
    }
}
