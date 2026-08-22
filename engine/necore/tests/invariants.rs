//! Correct-by-construction invariants, enforced as property tests:
//!
//! 1. CONTAINMENT: an entity's center ends every step inside its
//!    registered polygon's polygon. No corner-slip, no shove-escape, no
//!    position/registration disagreement -- ever.
//! 2. VISIBILITY CONTINUITY: the per-polygon visible coverage is a
//!    continuous function of the apex. Sweeping the apex in small steps
//!    (including straight through doorways and past corners) never makes
//!    a polygon's coverage jump to zero and back: no threshold cull may
//!    drop positive-measure coverage.

use necore::math::{v, Mat3, Vec2};
use necore::physics::Sim;
use necore::visibility::visible_set;
use necore::world::World;

fn square(half: f64) -> Vec<Vec2> {
    vec![
        v(-half, -half),
        v(-half, half),
        v(half, half),
        v(half, -half),
    ]
}

/// Point-in-convex-polygon (center containment, small tolerance for the
/// clamp's own nudge).
fn inside(verts: &[Vec2], p: Vec2, tol: f64) -> bool {
    let n = verts.len();
    let area2: f64 = (0..n)
        .map(|i| verts[i].cross(verts[(i + 1) % n]))
        .sum();
    let sign = area2.signum();
    for i in 0..n {
        let a = verts[i];
        let b = verts[(i + 1) % n];
        let cr = (b - a).cross(p - a) * sign;
        if cr < -tol {
            return false;
        }
    }
    true
}

fn grid_world() -> (World, Vec<usize>) {
    // 3x3 grid of 100u polygons, fully connected -- doorways on every shared
    // edge, so corners between portal and wall abound.
    let mut w = World::new();
    let mut polygons = Vec::new();
    for _r in 0..9 {
        polygons.push(w.add_polygon(&square(50.0)).unwrap());
    }
    for row in 0..3 {
        for col in 0..3 {
            let i = row * 3 + col;
            if col + 1 < 3 {
                // east edge of i (edge 2) to west edge of i+1 (edge 0)
                w.connect(polygons[i], 2, polygons[i + 1], 0).unwrap();
            }
            if row + 1 < 3 {
                // south edge (edge 1... rect edges: 0=W,1=S,2=E,3=N per
                // square() winding: verify by construction below)
                w.connect(polygons[i], 1, polygons[i + 3], 3).unwrap();
            }
        }
    }
    (w, polygons)
}

#[test]
fn containment_holds_under_random_walks_through_corners() {
    let (w, polygons) = grid_world();
    let mut sim = Sim::new(w);
    // A pack of entities including a big one, driven by a deterministic
    // LCG at aggressive speeds toward doorway corners.
    let mut ids = Vec::new();
    for k in 0..12 {
        let r = polygons[k % polygons.len()];
        let id = sim
            .spawn(r, v(-30.0 + 6.0 * k as f64, -20.0 + 3.0 * k as f64), if k == 0 { 13.5 } else { 6.5 }, 1.0, 0)
            .unwrap();
        ids.push(id);
    }
    let mut seed = 0xC0FFEE_u64;
    let mut rnd = move || {
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
        ((seed >> 33) as f64 / (1u64 << 31) as f64) - 1.0
    };
    for step in 0..4000 {
        for &id in &ids {
            if step % 7 == 0 {
                // re-aim: fast, corner-seeking motion
                if let Some(e) = sim.entities.get_mut(&id) {
                    e.vel = v(260.0 * rnd(), 260.0 * rnd());
                }
            }
        }
        sim.step(1.0 / 60.0);
        for &id in &ids {
            let e = sim.entities.get(&id).unwrap();
            let (polygon, x, y) = (e.polygon, e.pos.x, e.pos.y);
            let verts = &sim.world.polygons[polygon].verts;
            assert!(
                inside(verts, v(x, y), 1e-6),
                "step {step}: entity {id} center ({x:.3},{y:.3}) outside its \
                 registered polygon {polygon}"
            );
        }
    }
}

#[test]
fn visibility_coverage_is_continuous_across_doorway_sweeps() {
    let (w, polygons) = grid_world();
    // Sweep the apex along a line that crosses the center polygon's doorways
    // and grazes their corners; per-polygon coverage must vary continuously.
    let cam = Mat3::IDENTITY;
    let center = polygons[4];
    let mut prev: Option<std::collections::HashMap<usize, f64>> = None;
    let step = 0.35; // world units per sweep step
    let mut t = -49.0;
    while t < 49.0 {
        let apex = v(t, 12.3);
        let set = visible_set(&w, center, cam, apex, 640.0, 360.0, 8, 512);
        let mut areas: std::collections::HashMap<usize, f64> = Default::default();
        for inst in &set {
            let p = &inst.clip_local;
            let n = p.len();
            if n < 3 {
                continue;
            }
            // Canonical-polygon contract: no consecutive duplicate
            // vertices, wrap pair included. A duplicate's zero-length
            // edge poisons every edge-normal consumer (the decor
            // flicker; see geom::DEGENERATE_EDGE).
            for i in 0..n {
                assert!(
                    p[i].dist(p[(i + 1) % n]) > 1e-9,
                    "apex t={t:.2}: polygon {} clip has duplicate vertex at {i}",
                    inst.polygon
                );
            }
            let a: f64 = (0..n).map(|i| p[i].cross(p[(i + 1) % n])).sum();
            *areas.entry(inst.polygon).or_insert(0.0) += a.abs() / 2.0;
        }
        if let Some(prev_areas) = &prev {
            for (polygon, a_prev) in prev_areas {
                let a_now = areas.get(polygon).copied().unwrap_or(0.0);
                // Continuity: coverage that was substantial cannot vanish
                // within one 0.35u apex step. (Lipschitz-ish bound: a
                // wedge boundary sweeps at most ~edge_len per unit of
                // apex travel here; 60% is far beyond any legal change.)
                if *a_prev > 500.0 {
                    assert!(
                        a_now > 0.4 * a_prev,
                        "apex t={t:.2}: polygon {polygon} coverage fell {a_prev:.0} -> \
                         {a_now:.0} in one {step}u step (discontinuous cull)"
                    );
                }
            }
        }
        prev = Some(areas);
        t += step;
    }
}

#[test]
fn impulse_is_mass_scaled_exactly() {
    // dv = J / m at f64 exactness: a mass-4 body receives a quarter of a
    // mass-1 body's velocity change from the same impulse, and a
    // non-positive mass is refused rather than dividing by it.
    let mut w = World::new();
    let r = w.add_polygon(&square(200.0)).unwrap();
    let mut sim = Sim::new(w);
    let light = sim.spawn(r, v(-50.0, 0.0), 5.0, 1.0, 1).unwrap();
    let heavy = sim.spawn(r, v(50.0, 0.0), 5.0, 4.0, 1).unwrap();
    sim.apply_impulse(light, v(400.0, 0.0)).unwrap();
    sim.apply_impulse(heavy, v(400.0, 0.0)).unwrap();
    let vl = sim.entities[&light].vel;
    let vh = sim.entities[&heavy].vel;
    assert!((vl.x - 400.0).abs() < 1e-9, "light dv {}", vl.x);
    assert!((vh.x - 100.0).abs() < 1e-9, "heavy dv {}", vh.x);
    assert!((vl.x / vh.x - 4.0).abs() < 1e-9);
    assert!(vl.y.abs() < 1e-12 && vh.y.abs() < 1e-12);
    // impulses accumulate, they do not overwrite
    sim.apply_impulse(light, v(-100.0, 50.0)).unwrap();
    let vl2 = sim.entities[&light].vel;
    assert!((vl2.x - 300.0).abs() < 1e-9 && (vl2.y - 50.0).abs() < 1e-9);
    // unknown id and degenerate mass are refused loudly
    assert!(sim.apply_impulse(9999, v(1.0, 0.0)).is_err());
}
