use necore::{v, geom, Event, Sim, Vec2, World};

fn square100(cx: f64, cy: f64) -> Vec<Vec2> {
    let h = 50.0;
    vec![v(cx - h, cy - h), v(cx - h, cy + h), v(cx + h, cy + h), v(cx + h, cy - h)]
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

    let normal = sim.world.rooms[a].normals[ea];
    let dt_fine = 1e-7;

    // Phase 1: coarse approach.
    let mut iters = 0;
    loop {
        let e = &sim.entities[&id];
        if e.room != a { break; }
        let d = (e.pos - ea0).dot(normal);
        if d < 10.0 { break; }
        sim.step(1.0 / 60.0);
        iters += 1;
        if iters > 100000 { panic!("phase1 stuck"); }
    }

    // Phase 2: fine approach to first transfer.
    let mut xform1 = None;
    let mut p_pre = sim.entities[&id].pos;
    iters = 0;
    while xform1.is_none() {
        let pos_before = sim.entities[&id].pos;
        for ev in sim.step(dt_fine) {
            if let Event::Transfer { xform, .. } = ev {
                xform1 = Some(xform);
                p_pre = pos_before;
            }
        }
        iters += 1;
        if iters > 2_000_000 { panic!("phase2 stuck"); }
    }
    let p1 = sim.entities[&id].pos;
    sim.entities.get_mut(&id).unwrap().vel = sim.entities[&id].vel * -1.0;

    let mut xform2 = None;
    iters = 0;
    while xform2.is_none() {
        for ev in sim.step(dt_fine) {
            if let Event::Transfer { xform, .. } = ev { xform2 = Some(xform); }
        }
        iters += 1;
        if iters > 2_000_000 { panic!("phase3 stuck"); }
    }
    let p2 = sim.entities[&id].pos;
    let speed_final = sim.entities[&id].vel.len();
    println!(
        "ea={ea} eb={eb} speed={speed}: p_pre={:?} p1={:?} p2={:?} diff={} speed_diff={}",
        p_pre, p1, p2, p2.dist(p_pre), (speed_final - speed).abs()
    );
    let _ = geom::depth_in_polygon;
}

fn main() {
    for (ea, eb) in [(0,0),(1,3),(2,0),(3,1)] {
        for s in [50.0, 142.85379442588908, 300.0, 499.0] {
            run(ea, eb, s);
        }
    }
}
