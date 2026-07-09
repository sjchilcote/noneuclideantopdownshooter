use std::collections::{BTreeMap, HashSet};

use crate::geom;
use crate::math::{Mat3, Vec2};
use crate::world::{RoomId, World};

pub const TRANSFER_NUDGE: f64 = 1e-3;
/// Wall collision spans extend this far past edge endpoints so the seam where
/// two walls meet has no gap to slip through (safe by convexity: the extended
/// region lies outside the room).
pub const EDGE_SPAN_EXT: f64 = 1.0;
/// Absolute per-tick iteration backstop (a 4000 u/s bullet legitimately takes
/// dozens of substeps; this only exists to bound pathological cases).
const MAX_ITERS: usize = 512;
/// Consecutive iterations that consume almost no time before we declare a
/// corner trap and kill motion rather than hang.
const MAX_STALLS: usize = 8;

#[derive(Debug, Clone)]
pub struct Entity {
    pub id: u64,
    pub room: RoomId,
    pub pos: Vec2,
    pub vel: Vec2,
    pub dir: Vec2,
    pub radius: f64,
    pub mass: f64,
    pub rest_wall: f64,
    pub rest_ent: f64,
    pub group: u8,
    pub max_substep: f64,
    /// Entities that never transfer stay put at portals (turrets, decals).
    pub transfers: bool,
    pub alive: bool,
}

#[derive(Debug, Clone)]
pub enum Event {
    /// xform maps from-room coordinates into to-room coordinates: apply it to
    /// anything you were tracking in the old frame (camera, trails).
    Transfer {
        ent: u64,
        from: RoomId,
        to: RoomId,
        edge: usize,
        xform: Mat3,
    },
    WallHit {
        ent: u64,
        room: RoomId,
        edge: usize,
        pos: Vec2,
        normal: Vec2,
        speed: f64,
    },
    Contact {
        a: u64,
        b: u64,
        pos: Vec2,
        /// Unit vector from b toward a.
        normal: Vec2,
        rel_speed: f64,
    },
}

pub struct Sim {
    pub world: World,
    pub entities: BTreeMap<u64, Entity>,
    next_id: u64,
    /// collision_mask[g] bit h => groups g and h collide.
    pub collision_mask: [u16; 16],
    pub active_rooms: Vec<bool>,
    pub all_active: bool,
}

impl Sim {
    pub fn new(world: World) -> Sim {
        let n = world.rooms.len();
        Sim {
            world,
            entities: BTreeMap::new(),
            next_id: 1,
            collision_mask: [0xffff; 16],
            active_rooms: vec![true; n],
            all_active: true,
        }
    }

    pub fn set_collision_pair(&mut self, g: u8, h: u8, collide: bool) {
        let (g, h) = (g as usize & 15, h as usize & 15);
        if collide {
            self.collision_mask[g] |= 1 << h;
            self.collision_mask[h] |= 1 << g;
        } else {
            self.collision_mask[g] &= !(1 << h);
            self.collision_mask[h] &= !(1 << g);
        }
    }

    fn groups_collide(&self, g: u8, h: u8) -> bool {
        self.collision_mask[g as usize & 15] & (1 << (h as usize & 15)) != 0
    }

    pub fn set_active_within(&mut self, center: RoomId, hops: usize) {
        self.all_active = false;
        self.active_rooms = vec![false; self.world.rooms.len()];
        let mut frontier = vec![center];
        if center < self.active_rooms.len() {
            self.active_rooms[center] = true;
        }
        for _ in 0..hops {
            let mut next = Vec::new();
            for r in frontier {
                for p in self.world.rooms[r].portals.iter().flatten() {
                    if !self.active_rooms[p.target_room] {
                        self.active_rooms[p.target_room] = true;
                        next.push(p.target_room);
                    }
                }
            }
            frontier = next;
        }
    }

    pub fn spawn(
        &mut self,
        room: RoomId,
        pos: Vec2,
        radius: f64,
        mass: f64,
        group: u8,
    ) -> Result<u64, String> {
        if room >= self.world.rooms.len() {
            return Err(format!("no room {room}"));
        }
        let id = self.next_id;
        self.next_id += 1;
        // Clamp the spawn point decisively inside the room.
        let verts = &self.world.rooms[room].verts;
        let mut p = pos;
        let want = radius.min(self.world.rooms[room].radius * 0.5);
        for _ in 0..8 {
            let d = geom::depth_in_polygon(p, verts);
            if d >= want {
                break;
            }
            // Push along the most-violated edge normal.
            let n = verts.len();
            let mut worst = (f64::INFINITY, Vec2::ZERO);
            for i in 0..n {
                let a = verts[i];
                let b = verts[(i + 1) % n];
                let nn = geom::inward_normal(a, b);
                let dd = (p - a).dot(nn);
                if dd < worst.0 {
                    worst = (dd, nn);
                }
            }
            p = p + worst.1 * (want - worst.0 + 1e-6);
        }
        self.entities.insert(
            id,
            Entity {
                id,
                room,
                pos: p,
                vel: Vec2::ZERO,
                dir: Vec2 { x: 1.0, y: 0.0 },
                radius,
                mass,
                rest_wall: 0.0,
                rest_ent: 0.3,
                group,
                max_substep: radius.max(1.0),
                transfers: true,
                alive: true,
            },
        );
        self.world.rooms[room].entities.push(id);
        Ok(id)
    }

    pub fn remove(&mut self, id: u64) {
        if let Some(e) = self.entities.remove(&id) {
            let list = &mut self.world.rooms[e.room].entities;
            if let Some(i) = list.iter().position(|&x| x == id) {
                list.remove(i);
            }
        }
    }

    fn room_active(&self, r: RoomId) -> bool {
        self.all_active || self.active_rooms.get(r).copied().unwrap_or(false)
    }

    pub fn step(&mut self, dt: f64) -> Vec<Event> {
        let mut events = Vec::new();
        let mut contacts_seen: HashSet<(u64, u64)> = HashSet::new();
        let ids: Vec<u64> = self.entities.keys().copied().collect();
        for id in ids {
            let (room, alive) = match self.entities.get(&id) {
                Some(e) => (e.room, e.alive),
                None => continue,
            };
            if !alive || !self.room_active(room) {
                continue;
            }
            self.step_entity(id, dt, &mut events, &mut contacts_seen);
        }
        events
    }

    fn step_entity(
        &mut self,
        id: u64,
        dt: f64,
        events: &mut Vec<Event>,
        contacts_seen: &mut HashSet<(u64, u64)>,
    ) {
        let mut remaining = dt;
        let mut iters = 0;
        let mut stalls = 0;
        let mut last_remaining = f64::INFINITY;
        while remaining > 1e-9 {
            iters += 1;
            if last_remaining - remaining < 1e-7 * dt {
                stalls += 1;
            } else {
                stalls = 0;
            }
            last_remaining = remaining;
            if iters > MAX_ITERS || stalls > MAX_STALLS {
                // Corner trap: kill motion rather than tunnel or hang.
                if let Some(e) = self.entities.get_mut(&id) {
                    e.vel = Vec2::ZERO;
                }
                break;
            }
            let e = match self.entities.get(&id) {
                Some(e) => e.clone(),
                None => return,
            };
            let speed = e.vel.len();
            if speed < 1e-9 {
                break;
            }
            let step_dt = remaining.min(e.max_substep / speed);
            let target = e.pos + e.vel * step_dt;

            // --- entity-entity: earliest overlap along this substep's end ---
            let mut hit_ent: Option<(u64, Vec2, f64)> = None; // (other, normal b->a, dist)
            let room_ents: Vec<u64> = self.world.rooms[e.room].entities.clone();
            for oid in room_ents {
                if oid == id {
                    continue;
                }
                let o = match self.entities.get(&oid) {
                    Some(o) if o.alive => o.clone(),
                    _ => continue,
                };
                if !self.groups_collide(e.group, o.group) {
                    continue;
                }
                let rr = e.radius + o.radius;
                let d = target.dist(o.pos);
                if d < rr {
                    let n = if d > 1e-9 {
                        (target - o.pos) * (1.0 / d)
                    } else {
                        Vec2 { x: 1.0, y: 0.0 }
                    };
                    match hit_ent {
                        Some((_, _, best)) if best <= d => {}
                        _ => hit_ent = Some((oid, n, d)),
                    }
                }
            }

            // --- walls & portals: earliest center-line crossing ---
            // Portals: the center crossing the open span transfers the entity.
            // Walls: the circle (center at distance `radius`) reflects.
            let verts_len = self.world.rooms[e.room].verts.len();
            let mut best_wall: Option<(usize, f64, Vec2)> = None; // (edge, tcol in [0,1] of step, normal)
            let mut best_portal: Option<(usize, f64)> = None;
            for i in 0..verts_len {
                let room_ref = &self.world.rooms[e.room];
                let (a, b) = room_ref.edge(i);
                let n = room_ref.normals[i];
                // Entities that never transfer treat portals as walls.
                let is_portal = room_ref.portals[i].is_some() && e.transfers;
                let d0 = (e.pos - a).dot(n);
                let d1 = (target - a).dot(n);
                let rad = if is_portal { 0.0 } else { e.radius };
                if d1 >= rad || d0 < d1 {
                    continue; // not crossing inward-boundary, or moving inward
                }
                let denom = d0 - d1;
                if denom < 1e-12 {
                    continue;
                }
                let t = ((d0 - rad) / denom).clamp(0.0, 1.0);
                let cross_pt = e.pos.lerp(target, t);
                // Span check along the edge.
                let along = (cross_pt - a).dot((b - a).normalized());
                let len = room_ref.edge_len[i];
                if is_portal {
                    if along >= 0.0 && along <= len {
                        match best_portal {
                            Some((_, bt)) if bt <= t => {}
                            _ => best_portal = Some((i, t)),
                        }
                        continue;
                    }
                    // Beyond the opening: the wall corner still stops you.
                }
                if along >= -EDGE_SPAN_EXT && along <= len + EDGE_SPAN_EXT {
                    match best_wall {
                        Some((_, bt, _)) if bt <= t => {}
                        _ => best_wall = Some((i, t, n)),
                    }
                }
            }

            // Resolve the earliest event among entity hit / portal / wall.
            // Entity hits use end-of-step detection, so walls/portals (which
            // have exact times) win ties; entity contact resolves otherwise.
            let portal_first = match (&best_portal, &best_wall) {
                (Some((_, tp)), Some((_, tw, _))) => tp <= tw,
                (Some(_), None) => true,
                _ => false,
            };

            if let Some((pi, tp)) = best_portal.filter(|_| portal_first) {
                // Advance to the portal line, then transfer.
                let room_ref = &self.world.rooms[e.room];
                let portal = room_ref.portals[pi].unwrap();
                let cross_pt = e.pos.lerp(target, tp);
                let inv = portal.inv; // this-room -> target-room
                let new_room = portal.target_room;
                let new_pos = inv.apply(cross_pt);
                let new_vel = inv.apply_dir(e.vel);
                let new_dir = inv.apply_dir(e.dir).normalized();
                // Nudge decisively into the new interior.
                let n_child = self.world.rooms[new_room].normals[portal.target_edge];
                let new_pos = new_pos + n_child * TRANSFER_NUDGE;
                let from = e.room;
                {
                    let list = &mut self.world.rooms[from].entities;
                    if let Some(ix) = list.iter().position(|&x| x == id) {
                        list.remove(ix);
                    }
                    self.world.rooms[new_room].entities.push(id);
                }
                if let Some(me) = self.entities.get_mut(&id) {
                    me.room = new_room;
                    me.pos = new_pos;
                    me.vel = new_vel;
                    me.dir = new_dir;
                }
                events.push(Event::Transfer {
                    ent: id,
                    from,
                    to: new_room,
                    edge: pi,
                    xform: inv,
                });
                remaining -= step_dt * tp.max(1e-3);
                continue;
            }

            if let Some((oid, n, _)) = hit_ent {
                let wall_t = best_wall.map(|(_, t, _)| t).unwrap_or(1.0);
                if wall_t >= 1.0 - 1e-9 {
                    // Entity contact this substep: impulse + separation.
                    let o = self.entities.get(&oid).unwrap().clone();
                    let rel = e.vel - o.vel;
                    let rel_n = rel.dot(n);
                    let rest = e.rest_ent.min(o.rest_ent);
                    let (im_a, im_b) = (1.0 / e.mass.max(1e-9), 1.0 / o.mass.max(1e-9));
                    let mut new_vel_a = e.vel;
                    let mut new_vel_b = o.vel;
                    if rel_n < 0.0 {
                        let j = -(1.0 + rest) * rel_n / (im_a + im_b);
                        new_vel_a = new_vel_a + n * (j * im_a);
                        new_vel_b = new_vel_b - n * (j * im_b);
                    }
                    // Positional separation split by inverse mass.
                    let d = (e.pos + e.vel * step_dt).dist(o.pos);
                    let overlap = (e.radius + o.radius - d).max(0.0) + 1e-6;
                    let total = im_a + im_b;
                    let push_a = n * (overlap * im_a / total);
                    let push_b = -n * (overlap * im_b / total);
                    let contact_pos = e.pos.lerp(o.pos, e.radius / (e.radius + o.radius));
                    if let Some(me) = self.entities.get_mut(&id) {
                        me.vel = new_vel_a;
                        me.pos = me.pos + me.vel * step_dt + push_a;
                    }
                    if let Some(other) = self.entities.get_mut(&oid) {
                        other.vel = new_vel_b;
                        other.pos = other.pos + push_b;
                    }
                    // Contain both in-room after the push (cheap correction).
                    self.contain_in_room(id);
                    self.contain_in_room(oid);
                    let key = (id.min(oid), id.max(oid));
                    if contacts_seen.insert(key) {
                        events.push(Event::Contact {
                            a: id,
                            b: oid,
                            pos: contact_pos,
                            normal: n,
                            rel_speed: rel_n.abs(),
                        });
                    }
                    remaining -= step_dt;
                    continue;
                }
            }

            if let Some((wi, tw, n)) = best_wall {
                let cross_pt = e.pos.lerp(target, tw);
                let speed_into = -e.vel.dot(n);
                let new_pos = cross_pt + n * 1e-6;
                let rest = e.rest_wall;
                let vn = e.vel.dot(n);
                let new_vel = e.vel - n * ((1.0 + rest) * vn);
                let room = e.room;
                if let Some(me) = self.entities.get_mut(&id) {
                    me.pos = new_pos;
                    me.vel = new_vel;
                }
                events.push(Event::WallHit {
                    ent: id,
                    room,
                    edge: wi,
                    pos: cross_pt - n * e.radius,
                    normal: n,
                    speed: speed_into,
                });
                remaining -= step_dt * tw.max(1e-3);
                continue;
            }

            // Free flight.
            if let Some(me) = self.entities.get_mut(&id) {
                me.pos = target;
            }
            remaining -= step_dt;
        }
    }

    /// Cheap positional correction: push the entity back inside its room if a
    /// separation push left it slightly out (never lets it cross a portal
    /// implicitly; portal crossings must come from step motion).
    fn contain_in_room(&mut self, id: u64) {
        let e = match self.entities.get(&id) {
            Some(e) => e.clone(),
            None => return,
        };
        let room = &self.world.rooms[e.room];
        let n = room.verts.len();
        let mut pos = e.pos;
        for i in 0..n {
            let (a, _b) = room.edge(i);
            let nn = room.normals[i];
            let rad = if room.portals[i].is_some() { 0.0 } else { e.radius };
            let d = (pos - a).dot(nn);
            if d < rad - 1e-9 && rad > 0.0 {
                pos = pos + nn * (rad - d);
            }
        }
        if pos.dist(e.pos) > 1e-12 {
            if let Some(me) = self.entities.get_mut(&id) {
                me.pos = pos;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::math::v;

    fn square(half: f64) -> Vec<Vec2> {
        vec![
            v(-half, -half),
            v(-half, half),
            v(half, half),
            v(half, -half),
        ]
    }

    fn two_room_world() -> (Sim, RoomId, RoomId) {
        let mut w = World::new();
        let a = w.add_room(&square(50.0)).unwrap();
        let b = w.add_room(&square(50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        (Sim::new(w), a, b)
    }

    #[test]
    fn wall_slide_keeps_entity_inside() {
        let (mut sim, a, _) = two_room_world();
        let id = sim.spawn(a, v(0.0, 0.0), 8.0, 1.0, 0).unwrap();
        sim.entities.get_mut(&id).unwrap().vel = v(-300.0, 40.0);
        for _ in 0..120 {
            sim.step(1.0 / 60.0);
            let e = &sim.entities[&id];
            assert!(
                geom::depth_in_polygon(e.pos, &sim.world.rooms[e.room].verts) >= -1e-6,
                "escaped room at {:?}",
                e.pos
            );
        }
        // rest_wall = 0: velocity into the wall is absorbed, tangential kept.
        let e = &sim.entities[&id];
        assert!(e.vel.x.abs() < 1e-6, "normal component not absorbed: {:?}", e.vel);
    }

    #[test]
    fn portal_transfer_preserves_motion_and_roundtrips() {
        let (mut sim, a, b) = two_room_world();
        let id = sim.spawn(a, v(30.0, 5.0), 6.0, 1.0, 0).unwrap();
        sim.entities.get_mut(&id).unwrap().vel = v(200.0, 0.0);
        let mut transferred = false;
        'outer: for _ in 0..60 {
            for ev in sim.step(1.0 / 60.0) {
                if let Event::Transfer { ent, from, to, .. } = ev {
                    assert_eq!(ent, id);
                    assert_eq!(from, a);
                    assert_eq!(to, b);
                    transferred = true;
                    break 'outer; // stop before it reaches b's far wall
                }
            }
        }
        assert!(transferred);
        let e = sim.entities[&id].clone();
        assert_eq!(e.room, b);
        // Two aligned squares: b's frame is rotated 180 relative to a's when
        // glued flush (edge directions oppose), so velocity in b's local frame
        // points in -x... whatever the orientation, speed must be preserved.
        assert!((e.vel.len() - 200.0).abs() < 1e-6);

        // Send it back: reverse velocity, must land in a with mirrored state.
        sim.entities.get_mut(&id).unwrap().vel = e.vel * -1.0;
        let mut back = false;
        for _ in 0..120 {
            for ev in sim.step(1.0 / 60.0) {
                if let Event::Transfer { to, .. } = ev {
                    assert_eq!(to, a);
                    back = true;
                }
            }
        }
        assert!(back);
        assert_eq!(sim.entities[&id].room, a);
    }

    #[test]
    fn fast_bullet_does_not_tunnel_through_wall() {
        let (mut sim, a, _) = two_room_world();
        let id = sim.spawn(a, v(0.0, 0.0), 1.5, 0.001, 3).unwrap();
        {
            let e = sim.entities.get_mut(&id).unwrap();
            e.vel = v(0.0, -4000.0); // top wall, 66 units per tick
            e.rest_wall = 0.5;
            e.max_substep = 3.0;
        }
        sim.step(1.0 / 60.0);
        let e = &sim.entities[&id];
        assert_eq!(e.room, a);
        assert!(geom::depth_in_polygon(e.pos, &sim.world.rooms[a].verts) >= -1e-6);
        assert!(e.vel.y > 0.0, "should have bounced: {:?}", e.vel);
    }

    #[test]
    fn entity_collision_conserves_energy_bound() {
        let (mut sim, a, _) = two_room_world();
        let p = sim.spawn(a, v(-20.0, 0.0), 8.0, 1.0, 0).unwrap();
        let q = sim.spawn(a, v(20.0, 0.0), 8.0, 1.0, 0).unwrap();
        sim.entities.get_mut(&p).unwrap().vel = v(150.0, 0.0);
        let ke0: f64 = sim
            .entities
            .values()
            .map(|e| 0.5 * e.mass * e.vel.len2())
            .sum();
        let mut contact = false;
        for _ in 0..30 {
            for ev in sim.step(1.0 / 60.0) {
                if matches!(ev, Event::Contact { .. }) {
                    contact = true;
                }
            }
            let ke: f64 = sim
                .entities
                .values()
                .map(|e| 0.5 * e.mass * e.vel.len2())
                .sum();
            assert!(ke <= ke0 * (1.0 + 1e-9), "energy grew: {ke} > {ke0}");
        }
        assert!(contact);
        assert!(sim.entities[&q].vel.x > 10.0, "momentum not passed on");
    }

    #[test]
    fn non_transferring_entity_treats_portal_as_open_but_stays() {
        let (mut sim, a, _) = two_room_world();
        let id = sim.spawn(a, v(30.0, 0.0), 6.0, 1.0, 0).unwrap();
        {
            let e = sim.entities.get_mut(&id).unwrap();
            e.transfers = false;
            e.vel = v(300.0, 0.0);
        }
        for _ in 0..60 {
            sim.step(1.0 / 60.0);
        }
        // transfers=false: portals act as walls; it slides along the doorway
        // and never leaves the room (or its polygon).
        let e = &sim.entities[&id];
        assert_eq!(e.room, a);
        assert!(geom::depth_in_polygon(e.pos, &sim.world.rooms[a].verts) >= -1e-6);
    }
}
