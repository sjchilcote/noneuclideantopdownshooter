//! Otherworld soft-wall invariants, as integration tests (they build the
//! lib without cfg(test), so they run independent of in-flight unit-test
//! scaffolding elsewhere in the crate).

use necore::math::{v, Vec2};
use necore::physics::Sim;
use necore::world::World;

fn square(half: f64) -> Vec<Vec2> {
    vec![
        v(-half, -half),
        v(-half, half),
        v(half, half),
        v(half, -half),
    ]
}

fn soft_pair() -> (Sim, usize, usize) {
    let mut w = World::new();
    let a = w.add_polygon(&square(50.0)).unwrap();
    let b = w.add_polygon(&square(50.0)).unwrap();
    w.connect(a, 2, b, 0).unwrap();
    let mut sim = Sim::new(w);
    sim.soften_polygon(a);
    sim.soften_polygon(b);
    (sim, a, b)
}

fn max_len_err(sim: &Sim, polygon: usize) -> f64 {
    let r = &sim.world.polygons[polygon];
    let rest = &sim.soft.polygons[&polygon].rest_len;
    r.edge_len
        .iter()
        .zip(rest.iter())
        .map(|(l, r)| (l - r).abs())
        .fold(0.0, f64::max)
}

// ENGINE_INVARIANTS.md S4 (wave-1): `SoftSystem::on_split` had ZERO test
// coverage -- exactly the kind of array-shape-realignment bookkeeping the
// director's directive singles out as silently-corrupting on an untested
// path. `world::split_edge` (world.rs) inserts TWO new vertices per call
// (three collinear sub-edges from one wall, per ENGINE_DESIGN.md
// addenda), but `on_split`'s own doc comment says "a vertex was
// inserted... edge, edge+1 are the halves" and its body performs exactly
// ONE `Vec::insert` on `vel` and `rest_len` -- a one-vertex vs two-vertex
// mismatch between what actually happened to the polygon and what the soft
// state thinks happened.
//
// This property checks the actual consequence: after `soften` + a real
// `world.split_edge` + `on_split` (called the way a caller integrating
// the two features would), do `sr.vel`/`sr.rest_len` stay the same length
// as `polygon.verts`? `SoftSystem::step` has its own defensive fallback for
// exactly this mismatch (re-soften from current geometry, silently
// dropping velocity/rest-length state) -- so this is not a crash-class
// bug, but it IS a real, previously undocumented behavior: `on_split` is
// currently a no-op-shaped stub that does not correctly track
// `split_edge`'s actual two-vertex insert, so a runtime doorway-split on
// a soft (Otherworld) wall silently discards in-flight deformation state
// on the very next `step` rather than continuing it smoothly.
//
// This is reported as an OPEN VIOLATION in ENGINE_INVARIANTS.md (not
// fixed here -- soft.rs/on_split is in-lane but the game does not
// currently call `split_edge` on a soft polygon at all, per the game-layer
// catalog's H3/portable-hole audit, so this is latent, not
// player-visible today; fixing the split-count would require redesigning
// on_split's two-vertex case, out of scope for a PBT-enforcement pass).
#[test]
fn on_split_array_length_tracks_world_split_edge() {
    let mut w = World::new();
    let a = w.add_polygon(&square(50.0)).unwrap();
    let mut sim = Sim::new(w);
    sim.soften_polygon(a);
    let n_before = sim.world.polygons[a].verts.len();
    assert_eq!(sim.soft.polygons[&a].vel.len(), n_before);
    assert_eq!(sim.soft.polygons[&a].rest_len.len(), n_before);

    // Edge 0 is a free wall (no portal) -- split_edge accepts it.
    let world = &mut sim.world;
    world.split_edge(a, 0, 0.3, 0.6).unwrap();
    let n_after = world.polygons[a].verts.len();
    assert_eq!(n_after, n_before + 2, "split_edge itself inserts two vertices");

    sim.soft.on_split(&sim.world, a, 0);
    let sr = &sim.soft.polygons[&a];
    // THE FINDING: on_split only ever inserts one entry per call, so it
    // cannot track a two-vertex split; document the actual (mismatched)
    // outcome precisely rather than asserting the wrong postcondition.
    assert_eq!(
        sr.vel.len(),
        n_before + 1,
        "on_split's actual insert count (documents the vel/verts mismatch -- see ENGINE_INVARIANTS.md open violations)"
    );
    assert_ne!(
        sr.vel.len(),
        n_after,
        "on_split does NOT keep pace with split_edge's two-vertex insert (n_after={}); \
         SoftSystem::step's defensive re-soften fallback is what actually prevents this \
         from being a hard array-index panic on the next step",
        n_after
    );
}

#[test]
fn impulse_deforms_then_lengths_restore() {
    let (mut sim, a, _) = soft_pair();
    let before: Vec<Vec2> = sim.world.polygons[a].verts.clone();
    sim.soft_wall_impulse(a, 0, 0.5, 120.0);
    for _ in 0..12 {
        sim.step(1.0 / 60.0);
    }
    let moved = sim.world.polygons[a]
        .verts
        .iter()
        .zip(before.iter())
        .map(|(p, q)| p.dist(*q))
        .fold(0.0, f64::max);
    assert!(moved > 1.0, "impulse did not deform the wall ({moved})");
    for _ in 0..1800 {
        sim.step(1.0 / 60.0);
    }
    let err = max_len_err(&sim, a);
    assert!(err < 1.5, "edge lengths did not restore: max err {err}");
}

#[test]
fn wave_crosses_the_portal() {
    let (mut sim, a, b) = soft_pair();
    let before_b: Vec<Vec2> = sim.world.polygons[b].verts.clone();
    // hit a wall of polygon a far from the portal; the wave must reach b.
    sim.soft_wall_impulse(a, 0, 0.5, 150.0);
    for _ in 0..90 {
        sim.step(1.0 / 60.0);
    }
    let moved_b = sim.world.polygons[b]
        .verts
        .iter()
        .zip(before_b.iter())
        .map(|(p, q)| p.dist(*q))
        .fold(0.0, f64::max);
    assert!(
        moved_b > 0.35,
        "wave did not propagate into the neighbor ({moved_b})"
    );
}

#[test]
fn convexity_holds_under_bombardment() {
    let (mut sim, a, b) = soft_pair();
    let mut seed = 0x5EED_u64;
    for i in 0..240 {
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
        let edge = (seed >> 32) as usize % 4;
        let t = ((seed >> 16) & 0xff) as f64 / 255.0;
        if i % 3 == 0 {
            sim.soft_wall_impulse(if i % 2 == 0 { a } else { b }, edge, t, 90.0);
        }
        sim.step(1.0 / 60.0);
        for &polygon in &[a, b] {
            let vs = &sim.world.polygons[polygon].verts;
            let n = vs.len();
            let area2: f64 = (0..n).map(|k| vs[k].cross(vs[(k + 1) % n])).sum();
            for k in 0..n {
                let p = vs[(k + n - 1) % n];
                let c = vs[k];
                let q = vs[(k + 1) % n];
                let cr = (c - p).cross(q - c);
                assert!(
                    cr * area2.signum() >= -1e-6,
                    "reflex vertex in polygon {polygon} at step {i}"
                );
            }
        }
    }
}

#[test]
fn portal_transform_stays_exact_under_deformation() {
    let (mut sim, a, b) = soft_pair();
    sim.soft_wall_impulse(a, 1, 0.3, 140.0);
    for _ in 0..300 {
        sim.step(1.0 / 60.0);
        let p = sim.world.polygons[a].portals[2].unwrap();
        let (pa0, pa1) = sim.world.polygons[a].edge(2);
        let (pb0, pb1) = sim.world.polygons[b].edge(0);
        assert!(p.xform.apply(pb1).dist(pa0) < 1e-6, "portal map drifted");
        assert!(p.xform.apply(pb0).dist(pa1) < 1e-6, "portal map drifted");
    }
}

#[test]
fn hard_hit_reaches_a_new_stable_shape() {
    let (mut sim, a, _) = soft_pair();
    let before: Vec<Vec2> = sim.world.polygons[a].verts.clone();
    sim.soft_wall_impulse(a, 0, 0.2, 200.0);
    sim.soft_wall_impulse(a, 0, 0.8, 200.0);
    for _ in 0..3600 {
        sim.step(1.0 / 60.0);
    }
    // settled: lengths near rest...
    let err = max_len_err(&sim, a);
    assert!(err < 2.0, "not settled: len err {err}");
    // ...but the configuration moved: vertices have no rest position.
    let net = sim.world.polygons[a]
        .verts
        .iter()
        .zip(before.iter())
        .map(|(p, q)| p.dist(*q))
        .fold(0.0, f64::max);
    assert!(
        net > 2.0,
        "shape snapped back exactly; equilibria are not degenerate ({net})"
    );
}
