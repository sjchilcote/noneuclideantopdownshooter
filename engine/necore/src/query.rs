use std::collections::{HashMap, VecDeque};

use crate::math::{Mat3, Vec2};
use crate::physics::Sim;
use crate::world::{RoomId, World};

#[derive(Debug, Clone)]
pub enum RayHit {
    Wall {
        room: RoomId,
        edge: usize,
        pos: Vec2,
        /// Accumulated hit-room-local -> origin-room-local transform.
        xform: Mat3,
        dist: f64,
        hops: usize,
    },
    Entity {
        id: u64,
        room: RoomId,
        pos: Vec2,
        xform: Mat3,
        dist: f64,
        hops: usize,
    },
    Nothing {
        /// Where the ray gave up, in last-room coords.
        room: RoomId,
        pos: Vec2,
        xform: Mat3,
        dist: f64,
        hops: usize,
    },
}

/// Cast a ray through the room graph. `mask` selects entity groups the ray can
/// hit (bit per group); walls always stop it. Distances accumulate in each
/// room's local metric (correct for rigid portals; intentional for scaling
/// ones -- gameplay ranges breathe with the space).
pub fn raycast(
    sim: &Sim,
    room: RoomId,
    origin: Vec2,
    dir: Vec2,
    max_hops: usize,
    max_len: f64,
    mask: u16,
    ignore: Option<u64>,
) -> RayHit {
    let mut room = room;
    let mut o = origin;
    let mut d = dir.normalized();
    let mut xform = Mat3::IDENTITY; // current-room -> origin-room
    let mut travelled = 0.0;
    let mut hops = 0;

    loop {
        let r = &sim.world.rooms[room];
        // Exit point: nearest positive crossing among edges the ray exits.
        let n_edges = r.verts.len();
        let mut t_exit = f64::INFINITY;
        let mut exit_edge = None;
        for i in 0..n_edges {
            let (a, _b) = r.edge(i);
            let n = r.normals[i];
            let dn = d.dot(n);
            if dn >= -1e-12 {
                continue; // parallel or moving inward relative to this edge
            }
            let t = (o - a).dot(n) / -dn;
            if t > 1e-9 && t < t_exit {
                t_exit = t;
                exit_edge = Some(i);
            }
        }
        let seg_end = t_exit.min(max_len - travelled);

        // Entity hits within this room segment.
        let mut best_ent: Option<(u64, f64)> = None;
        for &eid in &r.entities {
            if Some(eid) == ignore {
                continue;
            }
            let e = match sim.entities.get(&eid) {
                Some(e) if e.alive => e,
                _ => continue,
            };
            if mask & (1 << (e.group as usize & 15)) == 0 {
                continue;
            }
            // |o + t d - c|^2 = r^2
            let oc = o - e.pos;
            let b = oc.dot(d);
            let c = oc.len2() - e.radius * e.radius;
            let disc = b * b - c;
            if disc < 0.0 {
                continue;
            }
            let t = -b - disc.sqrt();
            let t = if t > 1e-9 { t } else { -b + disc.sqrt() };
            if t > 1e-9 && t <= seg_end {
                match best_ent {
                    Some((_, bt)) if bt <= t => {}
                    _ => best_ent = Some((eid, t)),
                }
            }
        }
        if let Some((eid, t)) = best_ent {
            return RayHit::Entity {
                id: eid,
                room,
                pos: o + d * t,
                xform,
                dist: travelled + t,
                hops,
            };
        }

        if travelled + t_exit >= max_len {
            return RayHit::Nothing {
                room,
                pos: o + d * (max_len - travelled).max(0.0),
                xform,
                dist: max_len,
                hops,
            };
        }
        let ei = match exit_edge {
            Some(i) => i,
            None => {
                return RayHit::Nothing {
                    room,
                    pos: o,
                    xform,
                    dist: travelled,
                    hops,
                }
            }
        };
        let hit_pos = o + d * t_exit;
        // Portal opening check: exact span, no extension.
        let (a, b) = r.edge(ei);
        let along = (hit_pos - a).dot((b - a).normalized());
        let portal = r.portals[ei].filter(|_| along >= 0.0 && along <= r.edge_len[ei]);
        match portal {
            None => {
                return RayHit::Wall {
                    room,
                    edge: ei,
                    pos: hit_pos,
                    xform,
                    dist: travelled + t_exit,
                    hops,
                }
            }
            Some(p) => {
                if hops >= max_hops {
                    return RayHit::Nothing {
                        room,
                        pos: hit_pos,
                        xform,
                        dist: travelled + t_exit,
                        hops,
                    };
                }
                travelled += t_exit;
                hops += 1;
                // Into the child: positions through inv, direction through the
                // linear part (renormalized; scale portals stretch distances).
                o = p.inv.apply(hit_pos) ;
                let nd = p.inv.apply_dir(d);
                d = nd.normalized();
                // Nudge forward so we don't re-hit the same line.
                o = o + d * 1e-6;
                xform = xform.mul(p.xform);
                room = p.target_room;
            }
        }
    }
}

/// Routing tables: for each destination, the edge to take from every room.
#[derive(Default)]
pub struct Router {
    tables: HashMap<RoomId, (u64, Vec<Option<usize>>, Vec<u32>)>,
}

impl Router {
    pub fn new() -> Router {
        Router::default()
    }

    fn build(world: &World, dest: RoomId) -> (Vec<Option<usize>>, Vec<u32>) {
        let n = world.rooms.len();
        let mut next: Vec<Option<usize>> = vec![None; n];
        let mut dist: Vec<u32> = vec![u32::MAX; n];
        let mut q = VecDeque::new();
        dist[dest] = 0;
        q.push_back(dest);
        while let Some(m) = q.pop_front() {
            for (em, p) in world.rooms[m].portals.iter().enumerate() {
                let p = match p {
                    Some(p) => p,
                    None => continue,
                };
                // Portal (m, em) -> (t, et). From room t, taking edge et
                // arrives in m.
                let t = p.target_room;
                let et = p.target_edge;
                if dist[t] == u32::MAX {
                    dist[t] = dist[m] + 1;
                    next[t] = Some(et);
                    q.push_back(t);
                }
                let _ = em;
            }
        }
        (next, dist)
    }

    pub fn next_edge(
        &mut self,
        world: &World,
        from: RoomId,
        to: RoomId,
    ) -> Option<usize> {
        if from == to {
            return None;
        }
        let entry = self.tables.entry(to).or_insert_with(|| {
            let (n, d) = Self::build(world, to);
            (world.topology_version, n, d)
        });
        if entry.0 != world.topology_version {
            let (n, d) = Self::build(world, to);
            *entry = (world.topology_version, n, d);
        }
        entry.1.get(from).copied().flatten()
    }

    pub fn hop_distance(&mut self, world: &World, from: RoomId, to: RoomId) -> Option<u32> {
        if from == to {
            return Some(0);
        }
        self.next_edge(world, from, to)?;
        let d = self.tables.get(&to)?.2.get(from).copied()?;
        if d == u32::MAX {
            None
        } else {
            Some(d)
        }
    }
}

pub fn rooms_within(world: &World, center: RoomId, hops: usize) -> Vec<RoomId> {
    let mut seen = vec![false; world.rooms.len()];
    let mut out = vec![center];
    seen[center] = true;
    let mut frontier = vec![center];
    for _ in 0..hops {
        let mut nxt = Vec::new();
        for r in frontier {
            for p in world.rooms[r].portals.iter().flatten() {
                if !seen[p.target_room] {
                    seen[p.target_room] = true;
                    out.push(p.target_room);
                    nxt.push(p.target_room);
                }
            }
        }
        frontier = nxt;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::math::v;
    use crate::world::World;

    fn square(half: f64) -> Vec<Vec2> {
        vec![
            v(-half, -half),
            v(-half, half),
            v(half, half),
            v(half, -half),
        ]
    }

    #[test]
    fn raycast_crosses_portals_and_hits_walls() {
        let mut w = World::new();
        let a = w.add_room(&square(50.0)).unwrap();
        let b = w.add_room(&square(50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        let sim = Sim::new(w);
        let hit = raycast(&sim, a, v(0.0, 0.0), v(1.0, 0.0), 4, 1000.0, 0xffff, None);
        match hit {
            RayHit::Wall { room, dist, .. } => {
                assert_eq!(room, b);
                assert!((dist - 150.0).abs() < 1e-6, "dist {dist}");
            }
            other => panic!("expected wall in b, got {other:?}"),
        }
    }

    #[test]
    fn raycast_hits_entity_through_portal() {
        let mut w = World::new();
        let a = w.add_room(&square(50.0)).unwrap();
        let b = w.add_room(&square(50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        let mut sim = Sim::new(w);
        let t = sim.spawn(b, v(0.0, 0.0), 10.0, 1.0, 1).unwrap();
        let hit = raycast(&sim, a, v(0.0, 0.0), v(1.0, 0.0), 4, 1000.0, 0xffff, None);
        match hit {
            RayHit::Entity { id, dist, .. } => {
                assert_eq!(id, t);
                assert!((dist - 90.0).abs() < 1e-6, "dist {dist}");
            }
            other => panic!("expected entity, got {other:?}"),
        }
    }

    #[test]
    fn router_finds_paths_through_chains() {
        let mut w = World::new();
        let rooms: Vec<_> = (0..5).map(|_| w.add_room(&square(50.0)).unwrap()).collect();
        for i in 0..4 {
            w.connect(rooms[i], 2, rooms[i + 1], 0).unwrap();
        }
        let mut router = Router::new();
        // From room 0 toward room 4: take edge 2 each time.
        assert_eq!(router.next_edge(&w, rooms[0], rooms[4]), Some(2));
        assert_eq!(router.hop_distance(&w, rooms[0], rooms[4]), Some(4));
        assert_eq!(router.next_edge(&w, rooms[4], rooms[0]), Some(0));
        assert_eq!(router.next_edge(&w, rooms[2], rooms[2]), None);
    }
}
