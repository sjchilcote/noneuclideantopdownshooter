use necore::{v, Event, Sim, Vec2, World, Mat3};

fn square100(cx: f64, cy: f64) -> Vec<Vec2> {
    let h = 50.0;
    vec![v(cx - h, cy - h), v(cx - h, cy + h), v(cx + h, cy + h), v(cx + h, cy - h)]
}

fn run(speed: f64) {
    let mut w = World::new();
    let a = w.add_room(&square100(0.0, 0.0)).unwrap();
    let b = w.add_room(&square100(0.0, 0.0)).unwrap();
    w.connect(a, 0, b, 0).unwrap();

    let mut sim = Sim::new(w);
    let start_pos = Vec2::ZERO;
    let id = sim.spawn(a, start_pos, 5.0, 1.0, 0).unwrap();
    let (ea0, ea1) = sim.world.rooms[a].edge(0);
    let mid = (ea0 + ea1) * 0.5;
    let dir = (mid - start_pos).normalized();
    sim.entities.get_mut(&id).unwrap().vel = dir * speed;

    let mut xform1: Option<Mat3> = None;
    for _ in 0..600 {
        for ev in sim.step(1.0 / 60.0) {
            if let Event::Transfer { xform, .. } = ev { xform1 = Some(xform); }
        }
        if xform1.is_some() { break; }
    }
    let p1 = sim.entities[&id].pos; // position right after transfer 1, before reversal
    sim.entities.get_mut(&id).unwrap().vel = sim.entities[&id].vel * -1.0;

    let mut xform2: Option<Mat3> = None;
    for _ in 0..600 {
        for ev in sim.step(1.0 / 60.0) {
            if let Event::Transfer { xform, .. } = ev { xform2 = Some(xform); }
        }
        if xform2.is_some() { break; }
    }
    let p2 = sim.entities[&id].pos;
    let predicted_p2 = xform2.unwrap().apply(p1);
    println!("speed={speed}: p1={:?} p2={:?} predicted(xform2.apply(p1))={:?} diff={}", p1, p2, predicted_p2, p2.dist(predicted_p2));
}

fn main() {
    for s in [50.0, 100.0, 142.85379442588908, 200.0, 300.0, 499.0] {
        run(s);
    }
}
