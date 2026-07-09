use necore::{v, Event, Sim, Vec2, World};

fn square100(cx: f64, cy: f64) -> Vec<Vec2> {
    let h = 50.0;
    vec![v(cx - h, cy - h), v(cx - h, cy + h), v(cx + h, cy + h), v(cx + h, cy - h)]
}

fn main() {
    let mut w = World::new();
    let a = w.add_room(&square100(0.0, 0.0)).unwrap();
    let b = w.add_room(&square100(0.0, 0.0)).unwrap();
    w.connect(a, 0, b, 0).unwrap();
    let speed = 142.85379442588908;

    let mut sim = Sim::new(w);
    let start_pos = Vec2::ZERO;
    let id = sim.spawn(a, start_pos, 5.0, 1.0, 0).unwrap();
    let (ea0, ea1) = sim.world.rooms[a].edge(0);
    let mid = (ea0 + ea1) * 0.5;
    let dir = (mid - start_pos).normalized();
    sim.entities.get_mut(&id).unwrap().vel = dir * speed;

    let mut xform1 = None;
    let mut pos_before_crossing = start_pos;
    for step in 0..600 {
        let pos_before = sim.entities[&id].pos;
        for ev in sim.step(1.0 / 60.0) {
            if let Event::Transfer { xform, to, from, .. } = ev {
                println!("step {}: TRANSFER1 from={} to={} pos_before={:?}", step, from, to, pos_before);
                xform1 = Some(xform);
                pos_before_crossing = pos_before;
            }
        }
        if xform1.is_some() { break; }
    }
    println!("pos_before_crossing={:?}", pos_before_crossing);
    println!("after transfer1: room={} pos={:?} vel={:?}", sim.entities[&id].room, sim.entities[&id].pos, sim.entities[&id].vel);

    sim.entities.get_mut(&id).unwrap().vel = sim.entities[&id].vel * -1.0;
    println!("reversed vel={:?}", sim.entities[&id].vel);

    let mut xform2 = None;
    for step in 0..600 {
        let pos_before = sim.entities[&id].pos;
        for ev in sim.step(1.0 / 60.0) {
            if let Event::Transfer { xform, to, from, .. } = ev {
                println!("step {}: TRANSFER2 from={} to={} pos_before={:?}", step, from, to, pos_before);
                xform2 = Some(xform);
            }
        }
        if xform2.is_some() { break; }
        println!("  step {} pos={:?} room={} vel={:?}", step, sim.entities[&id].pos, sim.entities[&id].room, sim.entities[&id].vel);
    }
    println!("final: room={} pos={:?} vel={:?}", sim.entities[&id].room, sim.entities[&id].pos, sim.entities[&id].vel);
    println!("diff = {}", sim.entities[&id].pos.dist(pos_before_crossing));
}
