use necore::{v, Event, Mat3, Sim, Vec2, World};
use std::time::Instant;

fn square100(cx: f64, cy: f64) -> Vec<Vec2> {
    let h = 50.0;
    vec![v(cx - h, cy - h), v(cx - h, cy + h), v(cx + h, cy + h), v(cx + h, cy - h)]
}

fn approach_portal(
    sim: &mut Sim,
    id: u64,
    edge_point: Vec2,
    normal: Vec2,
    dts: &[(f64, f64)],
) -> (Option<Mat3>, usize, Vec2) {
    let mut iters = 0usize;
    for &(dt, stop_dist) in dts {
        loop {
            let e = &sim.entities[&id];
            let d = (e.pos - edge_point).dot(normal);
            if d < stop_dist { break; }
            iters += 1;
            if iters > 500_000 { return (None, iters, Vec2::ZERO); }
            let pos_before = sim.entities[&id].pos;
            for ev in sim.step(dt) {
                if let Event::Transfer { xform, .. } = ev {
                    return (Some(xform), iters, pos_before);
                }
            }
        }
    }
    (None, iters, Vec2::ZERO)
}

fn run(ea: usize, eb: usize, speed: f64) {
    let mut w = World::new();
    let a = w.add_room(&square100(0.0, 0.0)).unwrap();
    let b = w.add_room(&square100(0.0, 0.0)).unwrap();
    w.connect(a, ea, b, eb).unwrap();

    let mut sim = Sim::new(w);
    let start_pos = Vec2::ZERO;
    let id = sim.spawn(a, start_pos, 5.0, 1.0, 0).unwrap();
    let (ea0, ea1) = sim.world.rooms[a].edge(ea);
    let mid = (ea0 + ea1) * 0.5;
    let dir = (mid - start_pos).normalized();
    sim.entities.get_mut(&id).unwrap().vel = dir * speed;
    let normal_a = sim.world.rooms[a].normals[ea];

    let dts = [(1.0/60.0, 10.0), (1.0/60000.0, 0.02), (1e-7, -1e10)];

    let (xform1, it1, p_pre) = approach_portal(&mut sim, id, ea0, normal_a, &dts);
    let xform1 = xform1.expect("never transferred a->b");
    let room_b = sim.entities[&id].room;
    sim.entities.get_mut(&id).unwrap().vel = sim.entities[&id].vel * -1.0;

    let (eb0, _eb1) = sim.world.rooms[room_b].edge(eb);
    let normal_b = sim.world.rooms[room_b].normals[eb];
    let (xform2, it2, _) = approach_portal(&mut sim, id, eb0, normal_b, &dts);
    let xform2 = xform2.expect("never transferred back b->a");
    let p2 = sim.entities[&id].pos;
    let speed_final = sim.entities[&id].vel.len();

    let prod = xform1.mul(xform2);
    let prod_err = prod.m.iter().zip(Mat3::IDENTITY.m.iter()).map(|(x,y)| (x-y).abs()).fold(0.0, f64::max);

    println!(
        "ea={ea} eb={eb} speed={speed}: p_pre={:?} p2={:?} diff={:.10e} iters=({it1},{it2}) speed_diff={:.3e} prod_err={:.3e}",
        p_pre, p2, p_pre.dist(p2), (speed_final - speed).abs(), prod_err
    );
}

fn main() {
    let start = Instant::now();
    for (ea, eb) in [(0,0),(1,3),(2,0),(3,1)] {
        for s in [50.0, 142.85379442588908, 300.0, 499.0] {
            run(ea, eb, s);
        }
    }
    println!("elapsed: {:?}", start.elapsed());
}
