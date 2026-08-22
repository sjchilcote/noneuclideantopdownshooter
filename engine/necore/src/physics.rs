use std::collections::{BTreeMap, HashSet};

use crate::geom;
use crate::math::{Mat3, Vec2};
use crate::world::{PolygonId, World};

pub const TRANSFER_NUDGE: f64 = 1e-3;
/// Wall collision spans extend this far past edge endpoints so the seam where
/// two walls meet has no gap to slip through (safe by convexity: the extended
/// region lies outside the polygon).
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
    pub polygon: PolygonId,
    pub pos: Vec2,
    pub vel: Vec2,
    pub dir: Vec2,
    pub radius: f64,
    pub mass: f64,
    pub rest_wall: f64,
    pub rest_ent: f64,
    pub group: u8,
    /// Whether this body takes part in body-to-body collision at all.
    ///
    /// This replaced a 16x16 group collision matrix that encoded exactly one
    /// fact: a pickup is not a physics object. Everything else in the matrix
    /// was either "yes" or a way of sparing the game a consequence it should
    /// have (an enemy's round passing through an enemy). Friendly fire is on,
    /// so the matrix had nothing left to say, and the one surviving fact
    /// belongs on the body it is a fact about.
    pub physical: bool,
    pub max_substep: f64,
    /// Entities that never transfer stay put at portals (turrets, decals).
    pub transfers: bool,
    pub alive: bool,
}

#[derive(Debug, Clone)]
pub enum Event {
    /// xform maps from-polygon coordinates into to-polygon coordinates: apply it to
    /// anything you were tracking in the old frame (camera, trails).
    Transfer {
        ent: u64,
        from: PolygonId,
        to: PolygonId,
        edge: usize,
        xform: Mat3,
    },
    WallHit {
        ent: u64,
        polygon: PolygonId,
        edge: usize,
        pos: Vec2,
        normal: Vec2,
        speed: f64,
    },
    /// Same shape as `WallHit`, for walk-mask terrain instead of a polygon
    /// edge -- `terrain` is the index into `Polygon::terrain` that was hit.
    /// Physics response is identical to a wall (see `step_entity`); this is
    /// a distinct variant only so the game layer can tell "hit painted
    /// equipment" from "hit the polygon boundary" for sound/feedback.
    TerrainHit {
        ent: u64,
        polygon: PolygonId,
        terrain: usize,
        pos: Vec2,
        normal: Vec2,
        speed: f64,
    },
    Contact {
        a: u64,
        b: u64,
        /// The polygon the contact HAPPENED IN, and therefore the space
        /// `pos` and `normal` are expressed in.
        ///
        /// Recorded here, at contact time, because it is not recoverable
        /// afterwards: the rest of the step can transfer either body through a
        /// doorway, and a consumer that looked up "a's polygon" when it read
        /// the event would get the space the body ENDED in and silently
        /// misread the normal. Caught by the coordinate types the first time
        /// a turret round's knockback crossed a threshold mid-step.
        polygon: PolygonId,
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

    /// Bit `g` set => entities of group `g` are blocked by walk-mask
    /// terrain (default: every group, matching the director's "blocked is
    /// the default" spec). Cleared per-group via `set_terrain_block` for
    /// the rare entity that should pass through painted equipment (a ghost
    /// enemy, a decorative-only particle group, etc).
    pub terrain_blocks: u16,
    pub active_polygons: Vec<bool>,
    pub all_active: bool,
    /// Otherworld soft-wall system (empty = zero cost).
    pub soft: crate::soft::SoftSystem,
}

impl Sim {
    pub fn new(world: World) -> Sim {
        let n = world.polygons.len();
        Sim {
            world,
            entities: BTreeMap::new(),
            next_id: 1,
            terrain_blocks: 0xffff,
            active_polygons: vec![true; n],
            all_active: true,
            soft: crate::soft::SoftSystem::default(),
        }
    }

    /// Mark a polygon's walls soft (Otherworld). Idempotent.
    pub fn soften_polygon(&mut self, polygon: PolygonId) {
        if polygon < self.world.polygons.len() && !self.soft.is_soft(polygon) {
            self.soft.soften(&self.world, polygon);
        }
    }

    /// Impulse a soft polygon's wall (t in [0,1] along the edge; positive
    /// pushes outward). No-op on rigid polygons.
    pub fn soft_wall_impulse(&mut self, polygon: PolygonId, edge: usize, t: f64, magnitude: f64) {
        self.soft
            .wall_impulse(&self.world, polygon, edge, t, magnitude);
    }

    /// Set whether entities of `group` are blocked by walk-mask terrain
    /// (on by default for every group -- see `terrain_blocks`).
    pub fn set_terrain_block(&mut self, group: u8, blocked: bool) {
        let bit = 1 << (group as usize & 15);
        if blocked {
            self.terrain_blocks |= bit;
        } else {
            self.terrain_blocks &= !bit;
        }
    }

    fn terrain_blocks_group(&self, g: u8) -> bool {
        self.terrain_blocks & (1 << (g as usize & 15)) != 0
    }

    /// Additive activation: OR another region into the current active
    /// set (breach-route chambers must simulate even when the player is
    /// far — a dispatched unit frozen mid-transit reads as a dead AI).
    pub fn activate_also(&mut self, center: PolygonId, hops: usize) {
        if self.all_active {
            return;
        }
        if self.active_polygons.len() != self.world.polygons.len() {
            self.active_polygons = vec![false; self.world.polygons.len()];
        }
        let mut frontier = vec![center];
        if center < self.active_polygons.len() {
            self.active_polygons[center] = true;
        }
        for _ in 0..hops {
            let mut next = Vec::new();
            for r in frontier {
                for p in self.world.polygons[r].portals.iter().flatten() {
                    if !self.active_polygons[p.target_polygon] {
                        self.active_polygons[p.target_polygon] = true;
                        next.push(p.target_polygon);
                    }
                }
            }
            frontier = next;
        }
    }

    pub fn set_active_within(&mut self, center: PolygonId, hops: usize) {
        self.all_active = false;
        self.active_polygons = vec![false; self.world.polygons.len()];
        let mut frontier = vec![center];
        if center < self.active_polygons.len() {
            self.active_polygons[center] = true;
        }
        for _ in 0..hops {
            let mut next = Vec::new();
            for r in frontier {
                for p in self.world.polygons[r].portals.iter().flatten() {
                    if !self.active_polygons[p.target_polygon] {
                        self.active_polygons[p.target_polygon] = true;
                        next.push(p.target_polygon);
                    }
                }
            }
            frontier = next;
        }
    }

    pub fn spawn(
        &mut self,
        polygon: PolygonId,
        pos: Vec2,
        radius: f64,
        mass: f64,
        group: u8,
    ) -> Result<u64, String> {
        if polygon >= self.world.polygons.len() {
            return Err(format!("no polygon {polygon}"));
        }
        let id = self.next_id;
        self.next_id += 1;
        // Clamp the spawn point decisively inside the polygon.
        let verts = &self.world.polygons[polygon].verts;
        let mut p = pos;
        let want = radius.min(self.world.polygons[polygon].radius * 0.5);
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
                polygon,
                pos: p,
                vel: Vec2::ZERO,
                dir: Vec2 { x: 1.0, y: 0.0 },
                radius,
                mass,
                rest_wall: 0.0,
                rest_ent: 0.3,
                group,
                physical: true,
                max_substep: radius.max(1.0),
                transfers: true,
                alive: true,
            },
        );
        self.world.polygons[polygon].entities.push(id);
        Ok(id)
    }

    pub fn remove(&mut self, id: u64) {
        if let Some(e) = self.entities.remove(&id) {
            let list = &mut self.world.polygons[e.polygon].entities;
            if let Some(i) = list.iter().position(|&x| x == id) {
                list.remove(i);
            }
        }
    }

    /// Mass-scaled impulse: dv = J / m. The ONLY sanctioned way gameplay
    /// pushes a body — knockback as force through the physics, never a
    /// direct velocity write (DESIGN_7_25 combat canon).
    pub fn apply_impulse(&mut self, id: u64, j: Vec2) -> Result<(), String> {
        let e = self
            .entities
            .get_mut(&id)
            .ok_or_else(|| format!("no entity {id}"))?;
        if !(e.mass > 0.0) {
            return Err(format!("entity {id} has non-positive mass {}", e.mass));
        }
        e.vel = e.vel + j * (1.0 / e.mass);
        Ok(())
    }

    fn polygon_active(&self, r: PolygonId) -> bool {
        self.all_active || self.active_polygons.get(r).copied().unwrap_or(false)
    }

    /// Every currently active polygon id — the canonical set built by
    /// set_active_within plus every activate_also addition. Game-side
    /// systems that gate on activity must consume this, never rebuild
    /// their own region.
    pub fn active_polygon_ids(&self) -> Vec<PolygonId> {
        if self.all_active {
            return (0..self.world.polygons.len()).collect();
        }
        self.active_polygons
            .iter()
            .enumerate()
            .filter_map(|(i, &a)| if a { Some(i) } else { None })
            .collect()
    }

    pub fn step(&mut self, dt: f64) -> Vec<Event> {
        {
            // Otherworld soft walls integrate first so entity collision this
            // step sees the fresh geometry.
            let mut soft = std::mem::take(&mut self.soft);
            soft.step(&mut self.world, dt);
            self.soft = soft;
        }
        let mut events = Vec::new();
        let mut contacts_seen: HashSet<(u64, u64)> = HashSet::new();
        let ids: Vec<u64> = self.entities.keys().copied().collect();
        for id in ids {
            let (polygon, alive) = match self.entities.get(&id) {
                Some(e) => (e.polygon, e.alive),
                None => continue,
            };
            if !alive || !self.polygon_active(polygon) {
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
            let polygon_ents: Vec<u64> = self.world.polygons[e.polygon].entities.clone();
            for oid in polygon_ents {
                if oid == id {
                    continue;
                }
                let o = match self.entities.get(&oid) {
                    Some(o) if o.alive => o.clone(),
                    _ => continue,
                };
                if !(e.physical && o.physical) {
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
            let verts_len = self.world.polygons[e.polygon].verts.len();
            let mut best_wall: Option<(usize, f64, Vec2)> = None; // (edge, tcol in [0,1] of step, normal)
            let mut best_portal: Option<(usize, f64)> = None;
            for i in 0..verts_len {
                let polygon_ref = &self.world.polygons[e.polygon];
                let (a, b) = polygon_ref.edge(i);
                let n = polygon_ref.normals[i];
                // Entities that never transfer treat portals as walls, and an
                // entity only fits through an opening wider than itself.
                let fits = 2.0 * e.radius <= polygon_ref.edge_len[i] * 1.05;
                let is_portal = polygon_ref.portals[i].is_some() && e.transfers && fits;
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
                let len = polygon_ref.edge_len[i];
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

            // --- walk-mask terrain: swept-circle-vs-rect, same substep ---
            // Terrain blocks movement exactly like a wall (director's spec):
            // fold it into the same "earliest blocking obstacle" resolution
            // as best_wall so slide/stop/no-tunnel all come from the one
            // mechanism the wall path already proves out.
            let mut best_terrain: Option<(usize, f64, Vec2)> = None;
            if self.terrain_blocks_group(e.group) {
                let polygon_ref = &self.world.polygons[e.polygon];
                for (ti, rect) in polygon_ref.terrain.iter().enumerate() {
                    if let Some((t, n)) = geom::swept_circle_vs_rect(e.pos, target, e.radius, rect)
                    {
                        match best_terrain {
                            Some((_, bt, _)) if bt <= t => {}
                            _ => best_terrain = Some((ti, t, n)),
                        }
                    }
                }
            }
            enum Block {
                Wall(usize),
                Terrain(usize),
            }
            let best_block: Option<(Block, f64, Vec2)> = match (best_wall, best_terrain) {
                (Some((wi, wt, wn)), Some((ti, tt, tn))) => {
                    if wt <= tt {
                        Some((Block::Wall(wi), wt, wn))
                    } else {
                        Some((Block::Terrain(ti), tt, tn))
                    }
                }
                (Some((wi, wt, wn)), None) => Some((Block::Wall(wi), wt, wn)),
                (None, Some((ti, tt, tn))) => Some((Block::Terrain(ti), tt, tn)),
                (None, None) => None,
            };

            // Resolve the earliest event among entity hit / portal / obstacle
            // (wall or terrain). Entity hits use end-of-step detection, so
            // walls/terrain/portals (which have exact times) win ties;
            // entity contact resolves otherwise.
            let portal_first = match (&best_portal, &best_block) {
                (Some((_, tp)), Some((_, tw, _))) => *tp <= *tw,
                (Some(_), None) => true,
                _ => false,
            };

            if let Some((pi, tp)) = best_portal.filter(|_| portal_first) {
                // Advance to the portal line, then transfer.
                let polygon_ref = &self.world.polygons[e.polygon];
                let portal = polygon_ref.portals[pi].unwrap();
                let cross_pt = e.pos.lerp(target, tp);
                let inv = portal.inv; // this-polygon -> target-polygon
                let new_polygon = portal.target_polygon;
                let new_pos = inv.apply(cross_pt);
                let new_vel = inv.apply_dir(e.vel);
                let new_dir = inv.apply_dir(e.dir).normalized();
                // Nudge decisively into the new interior.
                let n_child = self.world.polygons[new_polygon].normals[portal.target_edge];
                let mut new_pos = new_pos + n_child * TRANSFER_NUDGE;
                // A crowd-shoved entity can cross from a position already
                // past the portal plane (t clamps to 0 and cross_pt IS the
                // outside position); mapping it raw deposits the entity
                // outside the target interior, where near-parallel motion
                // never re-triggers wall resolution and it drifts free.
                // Clamp into the target polygon: convex, so pushing off
                // each violated half-plane (twice, for corners) suffices.
                {
                    let target_ref = &self.world.polygons[new_polygon];
                    for _ in 0..2 {
                        for i in 0..target_ref.verts.len() {
                            let (a, _b) = target_ref.edge(i);
                            let n = target_ref.normals[i];
                            let d = (new_pos - a).dot(n);
                            let min_d = if target_ref.portals[i].is_some() {
                                0.0
                            } else {
                                (e.radius * 0.5).min(target_ref.edge_len[i] * 0.25)
                            };
                            if d < min_d {
                                new_pos = new_pos + n * (min_d - d);
                            }
                        }
                    }
                }
                let from = e.polygon;
                {
                    let list = &mut self.world.polygons[from].entities;
                    if let Some(ix) = list.iter().position(|&x| x == id) {
                        list.remove(ix);
                    }
                    self.world.polygons[new_polygon].entities.push(id);
                }
                if let Some(me) = self.entities.get_mut(&id) {
                    me.polygon = new_polygon;
                    me.pos = new_pos;
                    me.vel = new_vel;
                    me.dir = new_dir;
                }
                events.push(Event::Transfer {
                    ent: id,
                    from,
                    to: new_polygon,
                    edge: pi,
                    xform: inv,
                });
                remaining -= step_dt * tp.max(1e-3);
                continue;
            }

            if let Some((oid, n, _)) = hit_ent {
                let wall_t = best_block.as_ref().map(|(_, t, _)| *t).unwrap_or(1.0);
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
                    // Contain both in-polygon after the push (cheap correction).
                    self.contain_in_polygon(id);
                    self.contain_in_polygon(oid);
                    let key = (id.min(oid), id.max(oid));
                    if contacts_seen.insert(key) {
                        events.push(Event::Contact {
                            a: id,
                            b: oid,
                            polygon: e.polygon,
                            pos: contact_pos,
                            normal: n,
                            rel_speed: rel_n.abs(),
                        });
                    }
                    remaining -= step_dt;
                    continue;
                }
            }

            if let Some((kind, tw, n)) = best_block {
                let cross_pt = e.pos.lerp(target, tw);
                let speed_into = -e.vel.dot(n);
                let new_pos = cross_pt + n * 1e-6;
                let rest = e.rest_wall;
                let vn = e.vel.dot(n);
                let new_vel = e.vel - n * ((1.0 + rest) * vn);
                let polygon = e.polygon;
                if let Some(me) = self.entities.get_mut(&id) {
                    me.pos = new_pos;
                    me.vel = new_vel;
                }
                match kind {
                    Block::Wall(wi) => events.push(Event::WallHit {
                        ent: id,
                        polygon,
                        edge: wi,
                        pos: cross_pt - n * e.radius,
                        normal: n,
                        speed: speed_into,
                    }),
                    Block::Terrain(ti) => events.push(Event::TerrainHit {
                        ent: id,
                        polygon,
                        terrain: ti,
                        pos: cross_pt - n * e.radius,
                        normal: n,
                        speed: speed_into,
                    }),
                }
                remaining -= step_dt * tw.max(1e-3);
                continue;
            }

            // Free flight.
            if let Some(me) = self.entities.get_mut(&id) {
                me.pos = target;
            }
            remaining -= step_dt;
        }
        // The invariant, enforced unconditionally: whatever the substep
        // loop did (walls, portals, contacts, corner traps, stall breaks),
        // the entity ends the tick with its center inside its registered
        // polygon. Everything downstream (visibility apex, polygon queries,
        // the game's containment sweep) is allowed to assume this.
        self.contain_in_polygon(id);
        self.push_out_of_terrain(id);
    }

    /// Defense-in-depth companion to `contain_in_polygon`: if an entity's
    /// center ends the tick embedded in a padded terrain rect anyway (a
    /// portal transfer depositing it there, a mask hot-loaded under a
    /// standing entity, radius changed via `set_props` mid-overlap -- none
    /// of these go through the swept per-substep test above), push it out
    /// along the shallowest axis. Unconditional, like `contain_in_polygon`;
    /// cheap no-op when the polygon has no terrain.
    fn push_out_of_terrain(&mut self, id: u64) {
        let e = match self.entities.get(&id) {
            Some(e) => e.clone(),
            None => return,
        };
        if !self.terrain_blocks_group(e.group) {
            return;
        }
        let polygon = &self.world.polygons[e.polygon];
        if polygon.terrain.is_empty() {
            return;
        }
        let mut pos = e.pos;
        for _pass in 0..2 {
            for rect in &polygon.terrain {
                let padded = rect.inflate(e.radius);
                if !padded.contains(pos) {
                    continue;
                }
                let dl = pos.x - padded.lo.x;
                let dr = padded.hi.x - pos.x;
                let dt = pos.y - padded.lo.y;
                let db = padded.hi.y - pos.y;
                let m = dl.min(dr).min(dt).min(db);
                if m == dl {
                    pos.x = padded.lo.x - 1e-6;
                } else if m == dr {
                    pos.x = padded.hi.x + 1e-6;
                } else if m == dt {
                    pos.y = padded.lo.y - 1e-6;
                } else {
                    pos.y = padded.hi.y + 1e-6;
                }
            }
        }
        if pos.dist(e.pos) > 1e-12 {
            if let Some(me) = self.entities.get_mut(&id) {
                me.pos = pos;
            }
        }
    }

    /// Containment invariant: an entity's CENTER ends every correction
    /// inside its registered polygon's polygon. Walls push out by radius;
    /// portal planes clamp the center to the plane itself (a nudge inside)
    /// -- never an implicit crossing: a center legitimately going through
    /// re-triggers the sweep from d~0 next substep and transfers with
    /// events. The old version skipped portal edges entirely (`rad > 0.0`
    /// guard), so a corner-slip past a portal plane OUTSIDE its open span
    /// left the entity permanently outside its polygon: polygon registration
    /// and position disagreed, the visibility apex went exterior, and
    /// everything behind the entry portal blacked out for those ticks
    /// (the campaign flicker's blackout class), while escaped entities
    /// needed the game-side containment sweep to recover at all.
    fn contain_in_polygon(&mut self, id: u64) {
        let e = match self.entities.get(&id) {
            Some(e) => e.clone(),
            None => return,
        };
        let polygon = &self.world.polygons[e.polygon];
        let n = polygon.verts.len();
        let mut pos = e.pos;
        // Convex polygon: two passes settle corner interactions.
        for _pass in 0..2 {
            for i in 0..n {
                let (a, _b) = polygon.edge(i);
                let nn = polygon.normals[i];
                // Containment is CENTER-IN-POLYGON: d >= 0 on every
                // half-plane, portal or wall. The plane itself counts as
                // inside -- any positive floor is a repulsive barrier (slow
                // portal approaches could never cross), and a radius floor
                // on walls uses the INFINITE line, which walls split by
                // the doorway-carver share with their portal: it would pin
                // entities a radius short of every carved doorway. Radius
                // standoff from walls is the sweep/reflection's job.
                let d = (pos - a).dot(nn);
                if d < -1e-9 {
                    pos = pos - nn * d;
                }
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

    fn two_polygon_world() -> (Sim, PolygonId, PolygonId) {
        let mut w = World::new();
        let a = w.add_polygon(&square(50.0)).unwrap();
        let b = w.add_polygon(&square(50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        (Sim::new(w), a, b)
    }

    #[test]
    fn wall_slide_keeps_entity_inside() {
        let (mut sim, a, _) = two_polygon_world();
        let id = sim.spawn(a, v(0.0, 0.0), 8.0, 1.0, 0).unwrap();
        sim.entities.get_mut(&id).unwrap().vel = v(-300.0, 40.0);
        for _ in 0..120 {
            sim.step(1.0 / 60.0);
            let e = &sim.entities[&id];
            assert!(
                geom::depth_in_polygon(e.pos, &sim.world.polygons[e.polygon].verts) >= -1e-6,
                "escaped polygon at {:?}",
                e.pos
            );
        }
        // rest_wall = 0: velocity into the wall is absorbed, tangential kept.
        let e = &sim.entities[&id];
        assert!(
            e.vel.x.abs() < 1e-6,
            "normal component not absorbed: {:?}",
            e.vel
        );
    }

    #[test]
    fn transfer_from_shoved_outside_position_lands_inside_target() {
        // A crowded fight can press an entity past the portal plane before
        // the crossing is detected (t clamps to 0). The transfer must still
        // deposit it INSIDE the target polygon, or it drifts unreachable
        // (found by a 1,900-campaign soak: a fleeing shrieker escaped this
        // way and wedged the run).
        let (mut sim, a, b) = two_polygon_world();
        let id = sim.spawn(a, v(30.0, 5.0), 6.0, 1.0, 0).unwrap();
        // simulate the shove: already 12u past polygon a's east portal plane
        sim.entities.get_mut(&id).unwrap().pos = v(62.0, 5.0);
        sim.entities.get_mut(&id).unwrap().vel = v(80.0, 3.0);
        let mut transferred = false;
        for _ in 0..30 {
            for ev in sim.step(1.0 / 60.0) {
                if let Event::Transfer { ent, to, .. } = ev {
                    assert_eq!(ent, id);
                    assert_eq!(to, b);
                    transferred = true;
                }
            }
            let e = &sim.entities[&id];
            assert!(
                geom::depth_in_polygon(e.pos, &sim.world.polygons[e.polygon].verts) >= -1e-6,
                "outside polygon {:?} at {:?}",
                e.polygon,
                e.pos
            );
        }
        assert!(transferred, "never transferred");
    }

    #[test]
    fn portal_transfer_preserves_motion_and_roundtrips() {
        let (mut sim, a, b) = two_polygon_world();
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
        assert_eq!(e.polygon, b);
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
        assert_eq!(sim.entities[&id].polygon, a);
    }

    #[test]
    fn fast_bullet_does_not_tunnel_through_wall() {
        let (mut sim, a, _) = two_polygon_world();
        let id = sim.spawn(a, v(0.0, 0.0), 1.5, 0.001, 3).unwrap();
        {
            let e = sim.entities.get_mut(&id).unwrap();
            e.vel = v(0.0, -4000.0); // top wall, 66 units per tick
            e.rest_wall = 0.5;
            e.max_substep = 3.0;
        }
        sim.step(1.0 / 60.0);
        let e = &sim.entities[&id];
        assert_eq!(e.polygon, a);
        assert!(geom::depth_in_polygon(e.pos, &sim.world.polygons[a].verts) >= -1e-6);
        assert!(e.vel.y > 0.0, "should have bounced: {:?}", e.vel);
    }

    #[test]
    fn entity_collision_conserves_energy_bound() {
        let (mut sim, a, _) = two_polygon_world();
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
        let (mut sim, a, _) = two_polygon_world();
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
        // and never leaves the polygon (or its polygon).
        let e = &sim.entities[&id];
        assert_eq!(e.polygon, a);
        assert!(geom::depth_in_polygon(e.pos, &sim.world.polygons[a].verts) >= -1e-6);
    }

    // -- ENGINE_INVARIANTS.md T. walk-mask terrain -----------------------

    #[test]
    fn entity_head_on_into_terrain_stops_short_never_tunnels() {
        // A slow entity walking straight at a terrain rect must stop at its
        // padded face, exactly like a wall -- never pass through it.
        let (mut sim, a, _) = two_polygon_world();
        sim.world
            .set_polygon_terrain(a, vec![geom::Rect::new(v(10.0, -10.0), v(20.0, 10.0))])
            .unwrap();
        let id = sim.spawn(a, v(-30.0, 0.0), 3.0, 1.0, 0).unwrap();
        sim.entities.get_mut(&id).unwrap().vel = v(120.0, 0.0);
        for _ in 0..180 {
            sim.step(1.0 / 60.0);
        }
        let e = &sim.entities[&id];
        // Must have stopped at (or very near) the padded face x=10-3=7, and
        // categorically never crossed into/through the rect (x < 10).
        assert!(e.pos.x < 10.0, "tunneled through terrain: pos {:?}", e.pos);
        assert!((e.pos.x - 7.0).abs() < 0.5, "did not settle at the padded face: {:?}", e.pos);
    }

    #[test]
    fn fast_bullet_does_not_tunnel_through_terrain() {
        // Mirrors fast_bullet_does_not_tunnel_through_wall but for terrain:
        // a high-speed thin projectile crossing a terrain rect in one nominal
        // tick must still be caught by the per-substep swept test.
        let (mut sim, a, _) = two_polygon_world();
        sim.world
            .set_polygon_terrain(a, vec![geom::Rect::new(v(-2.0, -40.0), v(2.0, 40.0))])
            .unwrap();
        let id = sim.spawn(a, v(-30.0, 0.0), 1.5, 0.001, 3).unwrap();
        {
            let e = sim.entities.get_mut(&id).unwrap();
            e.vel = v(4000.0, 0.0); // would cross the 4-unit-thick rect in << 1 tick
            e.rest_wall = 0.5;
            e.max_substep = 3.0;
        }
        sim.step(1.0 / 60.0);
        let e = &sim.entities[&id];
        assert!(e.pos.x < -2.0, "bullet tunneled through terrain: pos {:?}", e.pos);
        assert!(e.vel.x < 0.0, "should have bounced: {:?}", e.vel);
    }

    #[test]
    fn naive_seek_deadlocks_head_on_against_terrain() {
        // Documents the failure mode `terrain_avoid_dir` exists to fix
        // (found fail-first while writing this wave): a bot that always
        // re-aims straight at a target directly behind a terrain rect's
        // flat face generates zero tangential velocity every tick and
        // grinds forever -- physics-level sliding alone does not route
        // around terrain the way it routes an entity along a convex polygon
        // wall (a wall never has a "straight through" target on the other
        // side of itself; terrain, sitting mid-polygon, does).
        let (mut sim, a, _) = two_polygon_world();
        sim.world
            .set_polygon_terrain(a, vec![geom::Rect::new(v(-5.0, -40.0), v(5.0, 5.0))])
            .unwrap();
        let id = sim.spawn(a, v(-30.0, -20.0), 3.0, 1.0, 0).unwrap();
        let target = v(30.0, -20.0);
        for _ in 0..600 {
            let e = &sim.entities[&id];
            let to_target = target - e.pos;
            let dl = to_target.len();
            if dl < 4.0 {
                break;
            }
            let dir = to_target * (1.0 / dl);
            sim.entities.get_mut(&id).unwrap().vel = dir * 80.0;
            sim.step(1.0 / 60.0);
        }
        let e = &sim.entities[&id];
        assert!(
            e.pos.dist(target) > 4.0,
            "expected the naive-seek deadlock (this documents the bug \
             terrain_avoid_dir fixes); it unexpectedly reached the target: {:?}",
            e.pos
        );
    }

    #[test]
    fn terrain_avoid_dir_steering_reaches_far_side() {
        // Same scenario as the deadlock above, but steering through
        // `query::terrain_avoid_dir` (what `sim.py`'s enemy AI now calls):
        // must route around the rect and actually arrive, not grind.
        let (mut sim, a, _) = two_polygon_world();
        sim.world
            .set_polygon_terrain(a, vec![geom::Rect::new(v(-5.0, -40.0), v(5.0, 5.0))])
            .unwrap();
        let id = sim.spawn(a, v(-30.0, -20.0), 3.0, 1.0, 0).unwrap();
        let target = v(30.0, -20.0);
        for _ in 0..600 {
            let e = &sim.entities[&id];
            let to_target = target - e.pos;
            let dl = to_target.len();
            if dl < 4.0 {
                break;
            }
            let desired = to_target * (1.0 / dl);
            let steered =
                crate::query::terrain_avoid_dir(&sim.world, e.polygon, e.pos, e.radius, desired, 25.0);
            sim.entities.get_mut(&id).unwrap().vel = steered * 80.0;
            sim.step(1.0 / 60.0);
        }
        let e = &sim.entities[&id];
        assert!(e.pos.dist(target) < 4.0, "never reached the far side: {:?}", e.pos);
    }

    #[test]
    fn terrain_blocks_projectiles_by_default() {
        let (mut sim, a, _) = two_polygon_world();
        sim.world
            .set_polygon_terrain(a, vec![geom::Rect::new(v(10.0, -10.0), v(20.0, 10.0))])
            .unwrap();
        let id = sim.spawn(a, v(-30.0, 0.0), 1.5, 0.001, 3).unwrap(); // group 3: a bullet group
        sim.entities.get_mut(&id).unwrap().vel = v(3000.0, 0.0);
        for _ in 0..30 {
            sim.step(1.0 / 60.0);
        }
        let e = &sim.entities[&id];
        assert!(e.pos.x < 10.0, "projectile passed through terrain unblocked: {:?}", e.pos);
    }

    #[test]
    fn set_terrain_block_false_lets_a_group_pass_through() {
        // The per-group opt-out flag: a group with terrain-blocking disabled
        // must fly straight through the rect it would otherwise stop at.
        let (mut sim, a, _) = two_polygon_world();
        sim.world
            .set_polygon_terrain(a, vec![geom::Rect::new(v(10.0, -10.0), v(20.0, 10.0))])
            .unwrap();
        sim.set_terrain_block(0, false);
        let id = sim.spawn(a, v(-30.0, 0.0), 3.0, 1.0, 0).unwrap();
        sim.entities.get_mut(&id).unwrap().vel = v(120.0, 0.0);
        for _ in 0..90 {
            sim.step(1.0 / 60.0);
        }
        let e = &sim.entities[&id];
        assert!(e.pos.x > 20.0, "opted-out group was still blocked by terrain: {:?}", e.pos);
    }

    #[test]
    fn empty_terrain_mask_is_fully_walkable() {
        // Absence of a mask (no set_polygon_terrain call at all) must mean
        // fully walkable -- no fabricated terrain, straight-line travel
        // reaches the far wall unimpeded.
        let (mut sim, a, _) = two_polygon_world();
        let id = sim.spawn(a, v(-30.0, 0.0), 3.0, 1.0, 0).unwrap();
        sim.entities.get_mut(&id).unwrap().vel = v(200.0, 0.0);
        for _ in 0..60 {
            sim.step(1.0 / 60.0);
        }
        let e = &sim.entities[&id];
        assert!(e.pos.x > 40.0, "phantom terrain blocked an unmasked polygon: {:?}", e.pos);
    }

    #[test]
    fn spawn_embedded_in_terrain_is_pushed_out_not_left_tunneled() {
        // The defense-in-depth path (push_out_of_terrain): an entity placed
        // directly inside a terrain rect (e.g. a mask hot-loaded under a
        // standee, or a portal transfer landing there) must be corrected
        // out, not left embedded indefinitely.
        let (mut sim, a, _) = two_polygon_world();
        sim.world
            .set_polygon_terrain(a, vec![geom::Rect::new(v(-10.0, -10.0), v(10.0, 10.0))])
            .unwrap();
        let id = sim.spawn(a, v(-30.0, 0.0), 3.0, 1.0, 0).unwrap();
        sim.entities.get_mut(&id).unwrap().pos = v(0.0, 0.0); // dead center of the rect
        sim.entities.get_mut(&id).unwrap().vel = v(0.0, 0.0);
        sim.step(1.0 / 60.0);
        let e = &sim.entities[&id];
        let rect = geom::Rect::new(v(-10.0, -10.0), v(10.0, 10.0));
        assert!(
            !rect.inflate(e.radius).contains(e.pos),
            "entity still embedded in terrain after a step: {:?}",
            e.pos
        );
    }
}
