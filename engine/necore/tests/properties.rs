//! Property-based verification suite for necore (ENGINE_DESIGN.md §2.6).
//! Added incrementally; each property is a separate `proptest!` block below.

use necore::{geom, raycast, v, Event, Mat3, RayHit, Sim, Vec2, World};
use proptest::prelude::*;

// ---------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------

/// Andrew's monotone-chain convex hull. Orientation of the result is
/// whatever falls out of the input order; `World::add_room` canonicalizes
/// winding itself, so callers don't need to care.
fn convex_hull(mut pts: Vec<Vec2>) -> Vec<Vec2> {
    pts.sort_by(|a, b| a.x.partial_cmp(&b.x).unwrap().then(a.y.partial_cmp(&b.y).unwrap()));
    pts.dedup_by(|a, b| (a.x - b.x).abs() < 1e-9 && (a.y - b.y).abs() < 1e-9);
    if pts.len() < 3 {
        return pts;
    }
    let cross = |o: Vec2, a: Vec2, b: Vec2| (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    let mut lower: Vec<Vec2> = Vec::new();
    for &p in &pts {
        while lower.len() >= 2
            && cross(lower[lower.len() - 2], lower[lower.len() - 1], p) <= 0.0
        {
            lower.pop();
        }
        lower.push(p);
    }
    let mut upper: Vec<Vec2> = Vec::new();
    for &p in pts.iter().rev() {
        while upper.len() >= 2
            && cross(upper[upper.len() - 2], upper[upper.len() - 1], p) <= 0.0
        {
            upper.pop();
        }
        upper.push(p);
    }
    lower.pop();
    upper.pop();
    lower.extend(upper);
    lower
}

fn min_edge_len(pts: &[Vec2]) -> f64 {
    let n = pts.len();
    let mut m = f64::INFINITY;
    for i in 0..n {
        let a = pts[i];
        let b = pts[(i + 1) % n];
        m = m.min(a.dist(b));
    }
    m
}

/// Random convex polygon: random point cloud in +-300, hull filtered to
/// 3-8 vertices with min edge length >= 5 (per task spec).
fn convex_polygon_strategy() -> impl Strategy<Value = Vec<Vec2>> {
    proptest::collection::vec((-300.0f64..300.0, -300.0f64..300.0), 8..18)
        .prop_map(|pts| convex_hull(pts.into_iter().map(|(x, y)| v(x, y)).collect()))
        .prop_filter("hull must have 3-8 verts and min edge len >= 5", |h| {
            h.len() >= 3 && h.len() <= 8 && min_edge_len(h) >= 5.0
        })
}

fn mat_max_abs_diff(a: Mat3, b: Mat3) -> f64 {
    a.m.iter()
        .zip(b.m.iter())
        .map(|(x, y)| (x - y).abs())
        .fold(0.0, f64::max)
}

// ---------------------------------------------------------------------
// Sanity check that the hull strategy itself produces valid convex rooms.
// ---------------------------------------------------------------------

proptest! {
    #[test]
    fn hull_strategy_produces_valid_convex_polygons(poly in convex_polygon_strategy()) {
        prop_assert!(poly.len() >= 3 && poly.len() <= 8);
        prop_assert!(min_edge_len(&poly) >= 5.0);
        let mut w = World::new();
        let r = w.add_room(&poly);
        prop_assert!(r.is_ok(), "add_room rejected hull: {:?}", r.err());
    }
}

// ---------------------------------------------------------------------
// 1. connect() invariants: paired transforms mutually inverse, edge
//    endpoints coincide with the t -> 1-t orientation flip.
// ---------------------------------------------------------------------

proptest! {
    #[test]
    fn connect_invariants(
        poly_a in convex_polygon_strategy(),
        poly_b in convex_polygon_strategy(),
        ea_seed in any::<usize>(),
        eb_seed in any::<usize>(),
    ) {
        let mut w = World::new();
        let a = w.add_room(&poly_a).unwrap();
        let b = w.add_room(&poly_b).unwrap();
        let ea = ea_seed % w.rooms[a].num_edges();
        let eb = eb_seed % w.rooms[b].num_edges();
        w.connect(a, ea, b, eb).unwrap();

        let pa = w.rooms[a].portals[ea].unwrap();
        let pb = w.rooms[b].portals[eb].unwrap();

        // Mutually inverse.
        let prod = pa.xform.mul(pb.xform);
        prop_assert!(mat_max_abs_diff(prod, Mat3::IDENTITY) < 1e-9, "{:?}", prod);
        let self_inv = pa.xform.mul(pa.xform.inverse());
        prop_assert!(mat_max_abs_diff(self_inv, Mat3::IDENTITY) < 1e-9);

        // Orientation-flipped endpoint correspondence, tolerance scaled by
        // the edge-length ratio (connect() scales when lengths differ).
        let (a0, a1) = w.rooms[a].edge(ea);
        let (b0, b1) = w.rooms[b].edge(eb);
        let la = a0.dist(a1);
        let lb = b0.dist(b1);
        let s = (la / lb).max(1.0);
        let tol = 1e-6 * s;
        prop_assert!(pa.xform.apply(b1).dist(a0) < tol);
        prop_assert!(pa.xform.apply(b0).dist(a1) < tol);
    }
}

// ---------------------------------------------------------------------
// 2. Mirror involution: connect(a, e, a, e) (self edge to itself) must
//    produce a transform that is its own inverse: xform . xform == I.
// ---------------------------------------------------------------------

proptest! {
    #[test]
    fn mirror_involution(
        poly in convex_polygon_strategy(),
        e_seed in any::<usize>(),
    ) {
        let mut w = World::new();
        let a = w.add_room(&poly).unwrap();
        let e = e_seed % w.rooms[a].num_edges();
        w.connect(a, e, a, e).unwrap();
        let p = w.rooms[a].portals[e].unwrap();
        let twice = p.xform.mul(p.xform);
        prop_assert!(mat_max_abs_diff(twice, Mat3::IDENTITY) < 1e-9, "{:?}", twice);
    }
}

// ---------------------------------------------------------------------
// 3. Containment: an entity under random velocity impulses never leaves
//    its (single, portal-less) room polygon. The anti-tunneling invariant.
// ---------------------------------------------------------------------

proptest! {
    #[test]
    fn containment_after_impulses(
        poly in convex_polygon_strategy(),
        radius in 2.0f64..15.0,
        rest_idx in 0..3usize,
        impulses in proptest::collection::vec((-2000.0f64..2000.0, -2000.0f64..2000.0), 12),
    ) {
        let mut w = World::new();
        let room = w.add_room(&poly).unwrap();
        let inradius = geom::depth_in_polygon(Vec2::ZERO, &w.rooms[room].verts);
        // Entity must plausibly fit with room to move; skip degenerate rooms.
        prop_assume!(inradius >= radius + 5.0);

        let mut sim = Sim::new(w);
        let id = sim.spawn(room, Vec2::ZERO, radius, 1.0, 0).unwrap();
        let rest_wall = [0.0, 0.5, 1.0][rest_idx];
        sim.entities.get_mut(&id).unwrap().rest_wall = rest_wall;

        for step in 0..120usize {
            if step % 10 == 0 {
                let (ix, iy) = impulses[(step / 10) % impulses.len()];
                let e = sim.entities.get_mut(&id).unwrap();
                e.vel = e.vel + v(ix, iy);
            }
            sim.step(1.0 / 60.0);
            let e = &sim.entities[&id];
            let verts = &sim.world.rooms[e.room].verts;
            let d = geom::depth_in_polygon(e.pos, verts);
            prop_assert!(d >= -1e-6, "escaped room at step {}: pos={:?} depth={}", step, e.pos, d);
        }
    }
}

// ---------------------------------------------------------------------
// 4. Energy: collisions with restitution <= 1 never increase total KE.
// ---------------------------------------------------------------------

proptest! {
    #[test]
    fn energy_never_increases(
        poly in convex_polygon_strategy(),
        n_ent in 2usize..=4,
        specs in proptest::collection::vec(
            (
                0.01f64..10.0,     // mass
                -500.0f64..500.0,  // vx
                -500.0f64..500.0,  // vy
                0.0f64..=1.0,      // rest_ent
                0.0f64..=1.0,      // rest_wall
                3.0f64..10.0,      // radius
                -40.0f64..40.0,    // pos x offset
                -40.0f64..40.0,    // pos y offset
            ),
            4,
        ),
    ) {
        let mut w = World::new();
        let room = w.add_room(&poly).unwrap();
        let inradius = geom::depth_in_polygon(Vec2::ZERO, &w.rooms[room].verts);
        prop_assume!(inradius >= 60.0);

        let mut sim = Sim::new(w);
        for i in 0..n_ent {
            let (mass, vx, vy, rest_ent, rest_wall, radius, ox, oy) = specs[i];
            let id = sim.spawn(room, v(ox, oy), radius, mass, 0).unwrap();
            let e = sim.entities.get_mut(&id).unwrap();
            e.vel = v(vx, vy);
            e.rest_ent = rest_ent;
            e.rest_wall = rest_wall;
        }

        let ke = |sim: &Sim| -> f64 {
            sim.entities.values().map(|e| 0.5 * e.mass * e.vel.len2()).sum()
        };
        let mut ke_prev = ke(&sim);
        for step in 0..90usize {
            sim.step(1.0 / 60.0);
            let ke_now = ke(&sim);
            let slack = 1e-9 * ke_prev.max(1e-6) + 1e-9;
            prop_assert!(
                ke_now <= ke_prev + slack,
                "KE grew at step {}: {} -> {}",
                step, ke_prev, ke_now
            );
            ke_prev = ke_now;
        }
    }
}

// ---------------------------------------------------------------------
// 5. Transfer roundtrip: cross a portal, reverse velocity exactly, cross
//    back. Speed must be restored exactly; since the reversal happens
//    right at the boundary, position must return to (near) the spot the
//    entity occupied the tick before it first crossed -- not the distant
//    launch point. The two Transfer xforms must compose to identity
//    (rigid connect).
// ---------------------------------------------------------------------

fn square100(cx: f64, cy: f64) -> Vec<Vec2> {
    let h = 50.0;
    vec![v(cx - h, cy - h), v(cx - h, cy + h), v(cx + h, cy + h), v(cx + h, cy - h)]
}

proptest! {
    #[test]
    fn transfer_roundtrip(
        ea_seed in any::<usize>(),
        eb_seed in any::<usize>(),
        speed in 50.0f64..500.0,
    ) {
        let mut w = World::new();
        let a = w.add_room(&square100(0.0, 0.0)).unwrap();
        let b = w.add_room(&square100(0.0, 0.0)).unwrap();
        let ea = ea_seed % 4;
        let eb = eb_seed % 4;
        w.connect(a, ea, b, eb).unwrap();

        let mut sim = Sim::new(w);
        let start_pos = Vec2::ZERO;
        let id = sim.spawn(a, start_pos, 5.0, 1.0, 0).unwrap();
        let (ea0, ea1) = sim.world.rooms[a].edge(ea);
        let mid = (ea0 + ea1) * 0.5;
        let dir = (mid - start_pos).normalized();
        sim.entities.get_mut(&id).unwrap().vel = dir * speed;

        let mut xform1 = None;
        let mut pos_before_crossing = start_pos;
        for _ in 0..600 {
            let pos_before = sim.entities[&id].pos;
            for ev in sim.step(1.0 / 60.0) {
                if let Event::Transfer { xform, to, .. } = ev {
                    prop_assert_eq!(to, b);
                    xform1 = Some(xform);
                    pos_before_crossing = pos_before;
                }
            }
            if xform1.is_some() { break; }
        }
        let xform1 = xform1.expect("never transferred a->b");
        prop_assert_eq!(sim.entities[&id].room, b);
        let speed_after_1 = sim.entities[&id].vel.len();
        prop_assert!((speed_after_1 - speed).abs() < 1e-9);

        sim.entities.get_mut(&id).unwrap().vel = sim.entities[&id].vel * -1.0;

        let mut xform2 = None;
        for _ in 0..600 {
            for ev in sim.step(1.0 / 60.0) {
                if let Event::Transfer { xform, to, .. } = ev {
                    prop_assert_eq!(to, a);
                    xform2 = Some(xform);
                }
            }
            if xform2.is_some() { break; }
        }
        let xform2 = xform2.expect("never transferred back b->a");
        prop_assert_eq!(sim.entities[&id].room, a);

        let speed_final = sim.entities[&id].vel.len();
        prop_assert!((speed_final - speed).abs() < 1e-9, "{} vs {}", speed_final, speed);

        // Velocity was reversed right at the boundary, so the round trip
        // returns the entity to (very near) where it stood the tick before
        // it first crossed -- not the original distant spawn point.
        let pos_final = sim.entities[&id].pos;
        prop_assert!(
            pos_final.dist(pos_before_crossing) < 1e-3,
            "{:?} vs pre-crossing {:?}",
            pos_final, pos_before_crossing
        );

        let prod = xform1.mul(xform2);
        prop_assert!(mat_max_abs_diff(prod, Mat3::IDENTITY) < 1e-9, "{:?}", prod);
    }
}

// ---------------------------------------------------------------------
// 6. Euclidean raycast oracle: a 3x2 grid of 100-unit square rooms glued
//    by pure-translation portals must agree exactly with flat-rectangle
//    ray/boundary intersection in world coordinates.
// ---------------------------------------------------------------------

/// World-space true center of grid room (i, j): rooms are 100x100, tiled
/// with no gaps across a 300x200 rectangle (i in 0..3, j in 0..2).
fn true_center(i: usize, j: usize) -> Vec2 {
    v(i as f64 * 100.0 + 50.0, j as f64 * 100.0 + 50.0)
}

/// 3x2 grid of 100-unit squares glued edge-to-edge by `connect` (rigid).
/// Identically-oriented squares glued this way produce pure translations
/// (no rotation), which is asserted below before returning.
fn build_translation_grid() -> (World, Vec<Vec<usize>>) {
    let mut w = World::new();
    let mut ids = vec![vec![0usize; 2]; 3];
    for (i, col) in ids.iter_mut().enumerate() {
        for (j, id) in col.iter_mut().enumerate() {
            let _ = (i, j);
            *id = w.add_room(&square100(0.0, 0.0)).unwrap();
        }
    }
    for j in 0..2 {
        for i in 0..2 {
            w.connect(ids[i][j], 2, ids[i + 1][j], 0).unwrap();
        }
    }
    for i in 0..3 {
        w.connect(ids[i][0], 1, ids[i][1], 3).unwrap();
    }
    for room in &w.rooms {
        for p in room.portals.iter().flatten() {
            let m = &p.xform.m;
            assert!(
                (m[0] - 1.0).abs() < 1e-12 && m[1].abs() < 1e-12
                    && m[3].abs() < 1e-12 && (m[4] - 1.0).abs() < 1e-12,
                "grid portal xform is not a pure translation: {:?}", p.xform
            );
        }
    }
    (w, ids)
}

/// Analytic ray-vs-boundary hit for a ray starting strictly inside
/// [0,w]x[0,h], via the slab method (dir must be non-degenerate).
fn analytic_rect_hit(origin: Vec2, dir: Vec2, w: f64, h: f64) -> (Vec2, f64) {
    let mut t = f64::INFINITY;
    if dir.x > 1e-15 {
        t = t.min((w - origin.x) / dir.x);
    } else if dir.x < -1e-15 {
        t = t.min((0.0 - origin.x) / dir.x);
    }
    if dir.y > 1e-15 {
        t = t.min((h - origin.y) / dir.y);
    } else if dir.y < -1e-15 {
        t = t.min((0.0 - origin.y) / dir.y);
    }
    (origin + dir * t, t)
}

proptest! {
    #[test]
    fn euclidean_raycast_oracle(
        i0 in 0usize..3,
        j0 in 0usize..2,
        ox in -45.0f64..45.0,
        oy in -45.0f64..45.0,
        theta in 0.0f64..std::f64::consts::TAU,
    ) {
        let (w, ids) = build_translation_grid();
        let sim = Sim::new(w);
        let start_room = ids[i0][j0];
        let origin_local = v(ox, oy);
        let dir = v(theta.cos(), theta.sin());

        let hit = raycast(&sim, start_room, origin_local, dir, 10, 1000.0, 0, None);
        let (world_hit, hit_dist) = match hit {
            RayHit::Wall { pos, xform, dist, .. } => {
                (true_center(i0, j0) + xform.apply(pos), dist)
            }
            other => {
                prop_assert!(false, "expected a wall hit, got {:?}", other);
                unreachable!()
            }
        };

        let world_origin = true_center(i0, j0) + origin_local;
        let (analytic_hit, analytic_dist) = analytic_rect_hit(world_origin, dir, 300.0, 200.0);

        prop_assert!(
            world_hit.dist(analytic_hit) < 1e-6,
            "engine {:?} vs analytic {:?} dir={:?} start=({},{})",
            world_hit, analytic_hit, dir, i0, j0
        );
        prop_assert!((hit_dist - analytic_dist).abs() < 1e-6, "{} vs {}", hit_dist, analytic_dist);
    }
}
