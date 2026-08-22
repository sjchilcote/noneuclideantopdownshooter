use std::cmp::Ordering as CmpOrdering;
use std::collections::{BinaryHeap, HashMap, HashSet, VecDeque};

use crate::frames::{Coordinate, SpaceId, Step};
use crate::math::{Mat3, Vec2};
use crate::physics::Sim;
use crate::world::{PolygonId, World};

#[derive(Debug, Clone)]
pub enum RayHit {
    Wall {
        polygon: PolygonId,
        edge: usize,
        pos: Vec2,
        /// Accumulated hit-polygon-local -> origin-polygon-local transform.
        xform: Mat3,
        dist: f64,
        hops: usize,
    },
    Entity {
        id: u64,
        polygon: PolygonId,
        pos: Vec2,
        xform: Mat3,
        dist: f64,
        hops: usize,
    },
    Nothing {
        /// Where the ray gave up, in last-polygon coords.
        polygon: PolygonId,
        pos: Vec2,
        xform: Mat3,
        dist: f64,
        hops: usize,
    },
}

/// Cast a ray through the polygon graph. `mask` selects entity groups the ray can
/// hit (bit per group); walls always stop it. Distances accumulate in each
/// polygon's local metric (correct for rigid portals; intentional for scaling
/// ones -- gameplay ranges breathe with the space).
pub fn raycast(
    sim: &Sim,
    polygon: PolygonId,
    origin: Vec2,
    dir: Vec2,
    max_hops: usize,
    max_len: f64,
    mask: u16,
    ignore: Option<u64>,
) -> RayHit {
    let mut polygon = polygon;
    let mut o = origin;
    let mut d = dir.normalized();
    let mut xform = Mat3::IDENTITY; // current-polygon -> origin-polygon
    let mut travelled = 0.0;
    let mut hops = 0;

    loop {
        let r = &sim.world.polygons[polygon];
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

        // Entity hits within this polygon segment.
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
                polygon,
                pos: o + d * t,
                xform,
                dist: travelled + t,
                hops,
            };
        }

        if travelled + t_exit >= max_len {
            return RayHit::Nothing {
                polygon,
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
                    polygon,
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
                    polygon,
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
                        polygon,
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
                o = p.inv.apply(hit_pos);
                let nd = p.inv.apply_dir(d);
                d = nd.normalized();
                // Nudge forward so we don't re-hit the same line (and keep
                // the travelled distance honest about it).
                o = o + d * 1e-6;
                travelled += 1e-6;
                xform = xform.mul(p.xform);
                polygon = p.target_polygon;
            }
        }
    }
}

/// Routing tables: for each destination, the edge to take from every polygon.
#[derive(Default)]
pub struct Router {
    tables: HashMap<PolygonId, (u64, Vec<Option<usize>>, Vec<u32>)>,
}

impl Router {
    pub fn new() -> Router {
        Router::default()
    }

    fn build(world: &World, dest: PolygonId) -> (Vec<Option<usize>>, Vec<u32>) {
        let n = world.polygons.len();
        let mut next: Vec<Option<usize>> = vec![None; n];
        let mut dist: Vec<u32> = vec![u32::MAX; n];
        let mut q = VecDeque::new();
        dist[dest] = 0;
        q.push_back(dest);
        while let Some(m) = q.pop_front() {
            for (em, p) in world.polygons[m].portals.iter().enumerate() {
                let p = match p {
                    Some(p) => p,
                    None => continue,
                };
                // Portal (m, em) -> (t, et). From polygon t, taking edge et
                // arrives in m.
                let t = p.target_polygon;
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
        from: PolygonId,
        to: PolygonId,
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

    pub fn hop_distance(&mut self, world: &World, from: PolygonId, to: PolygonId) -> Option<u32> {
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

/// Walk-mask terrain as light-occluder geometry for polygon `polygon`, in that
/// polygon's own local coordinates -- the same frame `Polygon::verts`/portal
/// planes live in. Each returned segment is one edge of one terrain rect
/// (`geom::Rect::edges`); a future lighting/shadow pass can treat these
/// exactly like wall segments when building a light's visible wedge.
///
/// **Interface only.** Nothing in `render.py`/the lighting composite
/// consumes this yet (that lane is owned by a sibling in-flight fix, per
/// the director's order) -- this is the clean query surface for it to pick
/// up later. Terrain never affects `visibility.rs`/vision: this function is
/// a separate, additive query, not a change to `visible_set`.
pub fn terrain_light_segments(world: &World, polygon: PolygonId) -> Vec<(Vec2, Vec2)> {
    match world.polygons.get(polygon) {
        Some(r) => r.terrain.iter().flat_map(|rect| rect.edges()).collect(),
        None => Vec::new(),
    }
}

/// Steer a desired direction around walk-mask terrain so bot pathing (which
/// only routes at POLYGON granularity via `Router`) doesn't grind forever
/// against in-polygon obstacles it beelines straight into.
///
/// Physics-level wall sliding (see `physics::Sim::step_entity`) already
/// handles glancing approaches -- any nonzero tangential velocity component
/// carries the entity around a corner. It does NOT handle an exactly
/// head-on approach: the tangential component is zero, sliding kills all
/// velocity, and a caller that re-aims straight at the same blocked target
/// every tick (the game's `_enemy_ai` "seek" behavior) regenerates the same
/// zero-progress velocity forever -- a real deadlock, confirmed by a
/// fail-first test (`entity_slides_along_terrain_and_reaches_far_side`
/// hung at the padded face until this function was used instead of a raw
/// direction-to-target).
///
/// Casts `desired` (normalized) up to `lookahead` units from `pos`; if it
/// would enter a terrain rect, blends in a tangential deflection AWAY from
/// whichever side the obstacle's center leans toward relative to `pos` (a
/// deterministic tie-break -- never zero, never oscillates between ticks for
/// a static obstacle and desired direction). Otherwise returns `desired`
/// unchanged (normalized). Polygon-local in, polygon-local out.
pub fn terrain_avoid_dir(
    world: &World,
    polygon: PolygonId,
    pos: Vec2,
    radius: f64,
    desired: Vec2,
    lookahead: f64,
) -> Vec2 {
    let d = desired.normalized();
    let r = match world.polygons.get(polygon) {
        Some(r) => r,
        None => return d,
    };
    let end = pos + d * lookahead;
    let mut best: Option<(f64, crate::geom::Rect)> = None;
    for rect in &r.terrain {
        if let Some((t, _n)) = crate::geom::swept_circle_vs_rect(pos, end, radius, rect) {
            match best {
                Some((bt, _)) if bt <= t => {}
                _ => best = Some((t, *rect)),
            }
        }
    }
    let rect = match best {
        Some((_, r)) => r,
        None => return d,
    };
    let center = (rect.lo + rect.hi) * 0.5;
    let to_center = center - pos;
    let perp = d.perp_right();
    // Steer away from the side the obstacle's center leans toward -- a
    // sign that only flips when the obstacle's bearing genuinely does,
    // never chatters between ticks for a static scene.
    let side = if perp.dot(to_center) >= 0.0 { -1.0 } else { 1.0 };
    (d + perp * (side * 0.9)).normalized()
}

// ---------------------------------------------------------------------------
// Physical routing: the route policy perception makes on the caller's behalf
// ---------------------------------------------------------------------------
//
// `Router` above answers in HOPS, which is the right metric for "is this
// chamber near mine" and the wrong one for "which way is the player, really".
// A three-hop chain of small chambers is closer than one hop across a hall,
// and a hop-minimal route can bend somewhere the straight line never goes —
// which is how a composed sight position ends up somewhere the raycast then
// refuses to confirm.
//
// So perception routes by TOTAL PHYSICAL DISTANCE through the assembled world.
// Legs are measured between doorway midpoints in each polygon's own local
// metric (the standard portal-graph measure: an upper bound on the true
// geodesic, and exact when the path runs through doorway centres). Distances
// under a scaling portal are deliberately measured in each leg's own space —
// the space really does stretch, and a range constant means what it means on
// the side it was written for.

/// A route through the polygon graph, with the record a `Coordinate` needs to
/// travel it.
#[derive(Debug, Clone)]
pub struct Route {
    /// Polygons entered, in order. The source polygon is not included, so an
    /// empty list means "already there".
    pub polygons: Vec<PolygonId>,
    /// One step per hop: the space entered and the matrix that carried a
    /// coordinate into it.
    pub steps: Vec<Step>,
    /// Physical path length: source point -> doorway -> ... -> final doorway.
    /// It stops AT the last doorway, because the route has no opinion about
    /// where in the destination the caller was heading; add the last leg
    /// yourself when you have a destination point.
    pub dist: f64,
    /// Which edge of the destination polygon the route arrives through, so a
    /// caller can measure that last leg. `None` for the empty route.
    pub entry_edge: Option<usize>,
}

impl Route {
    pub fn hops(&self) -> usize {
        self.steps.len()
    }
}

/// f64 ordering for the priority queues below. Distances here are finite by
/// construction (every leg is a length between two real points), so a NaN
/// would be a bug elsewhere; it sorts last rather than panicking.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Cost(f64);

impl Eq for Cost {}

impl Ord for Cost {
    fn cmp(&self, o: &Cost) -> CmpOrdering {
        // reversed: BinaryHeap is a max-heap, we want the cheapest first
        o.0.partial_cmp(&self.0).unwrap_or(CmpOrdering::Equal)
    }
}

impl PartialOrd for Cost {
    fn partial_cmp(&self, o: &Cost) -> Option<CmpOrdering> {
        Some(self.cmp(o))
    }
}

fn edge_mid(world: &World, r: PolygonId, e: usize) -> Option<Vec2> {
    let polygon = world.polygons.get(r)?;
    if e >= polygon.num_edges() {
        return None;
    }
    let (a, b) = polygon.edge(e);
    Some(a.lerp(b, 0.5))
}

/// The step that crosses edge `e` of polygon `r`: the space entered and the
/// matrix taking `r`-local coordinates into the neighbour's.
fn crossing(world: &World, r: PolygonId, e: usize) -> Option<(PolygonId, usize, Step)> {
    let p = (*world.polygons.get(r)?.portals.get(e)?)?;
    let space = world.polygon_space(p.target_polygon)?.id();
    Some((
        p.target_polygon,
        p.target_edge,
        Step { into: space, xform: p.inv },
    ))
}

/// The shortest PHYSICAL route from `from_pos` in polygon `from` to any point
/// of polygon `to`, using at most `max_hops` doorways. `None` when no such
/// route exists inside the cap.
///
/// Keyed on (polygon, entry edge, hops) so the cap cannot make a cheap deep
/// state hide a dearer shallow one — an approximation that would silently pick
/// the wrong route near the ceiling.
pub fn route(
    world: &World,
    from: PolygonId,
    from_pos: Vec2,
    to: PolygonId,
    max_hops: usize,
) -> Option<Route> {
    if from >= world.polygons.len() || to >= world.polygons.len() {
        return None;
    }
    if from == to {
        return Some(Route {
            polygons: Vec::new(),
            steps: Vec::new(),
            dist: 0.0,
            entry_edge: None,
        });
    }
    type Key = (PolygonId, usize, usize); // polygon, entry edge, hops
    const SOURCE_EDGE: usize = usize::MAX;

    let start: Key = (from, SOURCE_EDGE, 0);
    let mut best: HashMap<Key, f64> = HashMap::new();
    let mut prev: HashMap<Key, (Key, Step)> = HashMap::new();
    let mut heap: BinaryHeap<(Cost, Key)> = BinaryHeap::new();
    best.insert(start, 0.0);
    heap.push((Cost(0.0), start));

    while let Some((Cost(d), key)) = heap.pop() {
        let (r, entry, hops) = key;
        if best.get(&key).map(|b| d > *b + 1e-12).unwrap_or(true) {
            continue; // stale queue entry
        }
        if r == to {
            // reconstruct
            let mut polygons = Vec::new();
            let mut steps = Vec::new();
            let mut cur = key;
            while let Some((p, step)) = prev.get(&cur) {
                polygons.push(cur.0);
                steps.push(*step);
                cur = *p;
            }
            polygons.reverse();
            steps.reverse();
            return Some(Route {
                polygons,
                steps,
                dist: d,
                entry_edge: if entry == SOURCE_EDGE { None } else { Some(entry) },
            });
        }
        if hops >= max_hops {
            continue;
        }
        let here = if entry == SOURCE_EDGE {
            from_pos
        } else {
            match edge_mid(world, r, entry) {
                Some(p) => p,
                None => continue,
            }
        };
        let n_edges = world.polygons[r].num_edges();
        for e in 0..n_edges {
            if e == entry {
                continue; // never back out the way we came in
            }
            let Some((next_r, next_e, step)) = crossing(world, r, e) else {
                continue;
            };
            let Some(mid) = edge_mid(world, r, e) else { continue };
            let nd = d + here.dist(mid);
            let nkey: Key = (next_r, next_e, hops + 1);
            if best.get(&nkey).map(|b| nd < *b - 1e-12).unwrap_or(true) {
                best.insert(nkey, nd);
                prev.insert(nkey, (key, step));
                heap.push((Cost(nd), nkey));
            }
        }
    }
    None
}

/// Every DISTINCT route from `from_pos` in polygon `from` into polygon `to`,
/// shortest first. Distinct means distinct developed image: two routes that
/// put the point in the same place are the same sighting, however differently
/// they got there.
///
/// A portal graph with a loop admits unboundedly many routes, so this is
/// bounded by `max_hops` and `max_images` and the caller raises the budget to
/// see further. That is the honest shape of "the generator may never
/// terminate": there is no complete answer to return.
pub fn routes(
    world: &World,
    from: PolygonId,
    from_pos: Vec2,
    to: PolygonId,
    max_hops: usize,
    max_images: usize,
) -> Vec<Route> {
    let mut out: Vec<Route> = Vec::new();
    if from >= world.polygons.len() || to >= world.polygons.len() || max_images == 0 {
        return out;
    }
    // Distinct-image key: the developed point at 1e-3 units, which is far
    // finer than anything gameplay distinguishes and far coarser than the
    // float noise two different matrix products accumulate.
    let mut seen: HashSet<(PolygonId, i64, i64)> = HashSet::new();
    let quant = |r: PolygonId, p: Vec2| (r, (p.x * 1000.0) as i64, (p.y * 1000.0) as i64);

    struct Partial {
        r: PolygonId,
        entry: usize,
        at: Vec2,       // where we are on the path (a doorway midpoint)
        img: Vec2,      // the developed source point, in r's coordinates
        steps: Vec<Step>,
        polygons: Vec<PolygonId>,
    }
    const SOURCE_EDGE: usize = usize::MAX;
    let mut heap: BinaryHeap<(Cost, usize)> = BinaryHeap::new();
    let mut pool: Vec<Partial> = vec![Partial {
        r: from,
        entry: SOURCE_EDGE,
        at: from_pos,
        img: from_pos,
        steps: Vec::new(),
        polygons: Vec::new(),
    }];
    heap.push((Cost(0.0), 0));
    // A hard expansion ceiling so a loopy graph cannot spin here forever even
    // when it can never produce `max_images` distinct images.
    let mut budget = max_images.saturating_mul(256).saturating_add(4096);

    while let Some((Cost(d), idx)) = heap.pop() {
        if out.len() >= max_images || budget == 0 {
            break;
        }
        budget -= 1;
        let (r, entry, at, img, hops) = {
            let p = &pool[idx];
            (p.r, p.entry, p.at, p.img, p.steps.len())
        };
        if r == to && seen.insert(quant(r, img)) {
            let p = &pool[idx];
            out.push(Route {
                polygons: p.polygons.clone(),
                steps: p.steps.clone(),
                dist: d,
                entry_edge: if entry == SOURCE_EDGE { None } else { Some(entry) },
            });
            if out.len() >= max_images {
                break;
            }
        }
        if hops >= max_hops {
            continue;
        }
        let n_edges = world.polygons[r].num_edges();
        for e in 0..n_edges {
            if e == entry {
                continue;
            }
            let Some((next_r, next_e, step)) = crossing(world, r, e) else {
                continue;
            };
            let Some(mid) = edge_mid(world, r, e) else { continue };
            let (mut steps, mut polygons) = {
                let p = &pool[idx];
                (p.steps.clone(), p.polygons.clone())
            };
            steps.push(step);
            polygons.push(next_r);
            pool.push(Partial {
                r: next_r,
                entry: next_e,
                at: step.xform.apply(mid),
                img: step.xform.apply(img),
                steps,
                polygons,
            });
            heap.push((Cost(d + at.dist(mid)), pool.len() - 1));
        }
    }
    out
}

/// The composed transform from one space into another, along the shortest
/// physical route — or None when no route exists (or either space is not one
/// of this world's polygons).
///
/// WHY THIS EXISTS ALONGSIDE `develop`. `develop` carries ONE place one way.
/// A blast that reaches through a doorway needs both directions at once: each
/// body's place in the blast's space to measure the falloff, and the blast's
/// place in each body's space to push it away — and doing that with two
/// `develop` calls is two graph searches whose routes are not even guaranteed
/// to be the same one. A Transform is invertible, so one search answers both,
/// and the pair provably agrees. (Found by a reader working from the
/// documentation alone, who needed exactly this and correctly reported that
/// nothing offered it.)
pub fn transform_between(
    world: &World,
    from: SpaceId,
    into: SpaceId,
) -> Option<crate::frames::Transform> {
    if from == into {
        return crate::frames::Transform::new(from, into, Mat3::IDENTITY, "identity").ok();
    }
    let a = world.polygon_of_space(from)?;
    let b = world.polygon_of_space(into)?;
    // measured from the source polygon's centroid (its local origin), which is
    // the route a body near the middle of it would take
    let r = route(world, a, Vec2::ZERO, b, world.polygons.len())?;
    let mut m = Mat3::IDENTITY;
    for step in &r.steps {
        m = step.xform.mul(m);
    }
    crate::frames::Transform::new(from, into, m, "composed route").ok()
}

/// Develop a coordinate into another space: the one operation here that
/// consults live topology.
///
/// It belongs to the world, not to the Coordinate — putting it on the
/// Coordinate would imply the answer is derivable from what the Coordinate
/// holds, when in fact it is a search against world state that can fail. It
/// fails (None) when either space is not one of this world's polygons — the
/// screen is a space, and no route through doorways reaches it — or when no
/// route exists.
pub fn develop(world: &World, c: &Coordinate, into: SpaceId) -> Option<Coordinate> {
    if c.space() == into {
        return Some(c.clone());
    }
    let from = world.polygon_of_space(c.space())?;
    let to = world.polygon_of_space(into)?;
    let r = route(world, from, c.local(), to, world.polygons.len())?;
    Some(c.extended(&r.steps))
}

/// One chamber an observer can reach, developed into the OBSERVER's space.
#[derive(Debug, Clone)]
pub struct Reached {
    pub polygon: PolygonId,
    /// Develops this chamber's local coordinates into the observer's.
    pub into_obs: Mat3,
    /// Doorways crossed to get here.
    pub depth: usize,
    /// Path length observer -> doorway -> ... -> the doorway into here,
    /// measured through doorway midpoints. The caller adds the last leg.
    pub path: f64,
    /// A LOWER BOUND on the length of any straight line from the observer
    /// into this chamber: a sightline must cross every doorway on the
    /// route, so it is at least as long as the distance to the farthest
    /// of those doorways. Sound to prune on, unlike `path` (a straight
    /// line through a wide doorway is shorter than the midpoint walk).
    pub near: f64,
}

/// Every chamber within `max_hops` doorways of the observer whose doorway
/// chain admits a sightline no longer than `max_range`, nearest first, each
/// carrying the matrix that develops it into the observer's own space.
///
/// WHY THIS EXISTS. Perception is a question about the observer's
/// NEIGHBOURHOOD, so it must be answered by searching the polygon graph
/// outward from the observer — once — and reading the bodies out of the
/// chambers the search reaches. The alternative, and this engine shipped it
/// for a while, is to take every body in the world and run a route search
/// per body back to the observer: cost proportional to the world's whole
/// population, paid every tick by every eye, to answer a question about one
/// room and its neighbours. On a full level that was 3,200 route searches a
/// tick for 36 turrets and it ate the entire frame budget.
///
/// One walk answers for every body at once because the route is a property
/// of the CHAMBERS, not of the bodies standing in them.
pub fn reach(
    world: &World,
    from: PolygonId,
    from_pos: Vec2,
    max_hops: usize,
    max_range: f64,
) -> Vec<Reached> {
    let mut out: Vec<Reached> = Vec::new();
    if from >= world.polygons.len() {
        return out;
    }
    out.push(Reached {
        polygon: from,
        into_obs: Mat3::IDENTITY,
        depth: 0,
        path: 0.0,
        near: 0.0,
    });
    if max_hops == 0 {
        return out;
    }
    // Keyed on (polygon, entry edge) exactly like `route`: a chamber
    // entered through a different doorway is a different image of it, and
    // collapsing the two would hide the nearer one behind the first found.
    let mut seen: HashSet<(PolygonId, usize)> = HashSet::new();
    seen.insert((from, usize::MAX));
    struct Node {
        polygon: PolygonId,
        entry: usize,
        into_obs: Mat3,
        depth: usize,
        path: f64,
        near: f64,
        /// where we stand on the path, in THIS chamber's coordinates
        at: Vec2,
    }
    let mut pool: Vec<Node> = vec![Node {
        polygon: from,
        entry: usize::MAX,
        into_obs: Mat3::IDENTITY,
        depth: 0,
        path: 0.0,
        near: 0.0,
        at: from_pos,
    }];
    let mut heap: BinaryHeap<(Cost, usize)> = BinaryHeap::new();
    heap.push((Cost(0.0), 0));

    while let Some((_, idx)) = heap.pop() {
        let (r, entry, depth) = {
            let n = &pool[idx];
            (n.polygon, n.entry, n.depth)
        };
        if depth >= max_hops {
            continue;
        }
        let n_edges = world.polygons[r].num_edges();
        for e in 0..n_edges {
            if e == entry {
                continue;
            }
            let Some((next_r, next_e, step)) = crossing(world, r, e) else {
                continue;
            };
            if !seen.insert((next_r, next_e)) {
                continue;
            }
            let Some(mid) = edge_mid(world, r, e) else { continue };
            let Some(p) = world.polygons[r].portals[e] else { continue };
            let (into_obs, path) = {
                let n = &pool[idx];
                // p.xform carries the NEIGHBOUR's coordinates into r's, so
                // composing it under the accumulated matrix develops the
                // neighbour all the way back into the observer's space.
                (n.into_obs.mul(p.xform), n.path + n.at.dist(mid))
            };
            // the doorway we just crossed, seen from the observer: the
            // sound lower bound on any sightline through it
            let door = {
                let polygon = &world.polygons[next_r];
                if next_e >= polygon.num_edges() {
                    continue;
                }
                let (a, b) = polygon.edge(next_e);
                (into_obs.apply(a), into_obs.apply(b))
            };
            let near = {
                let n = &pool[idx];
                n.near.max(point_segment_dist(from_pos, door.0, door.1))
            };
            if near > max_range {
                continue;
            }
            pool.push(Node {
                polygon: next_r,
                entry: next_e,
                into_obs,
                depth: depth + 1,
                path,
                near,
                at: step.xform.apply(mid),
            });
            out.push(Reached {
                polygon: next_r,
                into_obs,
                depth: depth + 1,
                path,
                near,
            });
            heap.push((Cost(path), pool.len() - 1));
        }
    }
    out
}

/// Distance from a point to a segment — the doorway-crossing lower bound.
fn point_segment_dist(p: Vec2, a: Vec2, b: Vec2) -> f64 {
    let ab = b - a;
    let l2 = ab.len2();
    if l2 <= 1e-12 {
        return (p - a).len();
    }
    let t = (((p - a).x * ab.x + (p - a).y * ab.y) / l2).clamp(0.0, 1.0);
    (p - (a + ab * t)).len()
}

pub fn polygons_within(world: &World, center: PolygonId, hops: usize) -> Vec<PolygonId> {
    let mut seen = vec![false; world.polygons.len()];
    let mut out = vec![center];
    seen[center] = true;
    let mut frontier = vec![center];
    for _ in 0..hops {
        let mut nxt = Vec::new();
        for r in frontier {
            for p in world.polygons[r].portals.iter().flatten() {
                if !seen[p.target_polygon] {
                    seen[p.target_polygon] = true;
                    out.push(p.target_polygon);
                    nxt.push(p.target_polygon);
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

    /// A corridor of `n` square chambers, each joined to the next.
    fn corridor(n: usize) -> (World, Vec<PolygonId>) {
        let mut w = World::new();
        let mut ids = Vec::new();
        for _ in 0..n {
            ids.push(w.add_polygon(&square(50.0)).unwrap());
        }
        for i in 0..n - 1 {
            w.connect(ids[i], 2, ids[i + 1], 0).unwrap();
        }
        (w, ids)
    }

    #[test]
    fn reach_develops_each_chamber_into_the_observers_space() {
        let (w, ids) = corridor(3);
        let got = reach(&w, ids[0], v(0.0, 0.0), 4, 10_000.0);
        assert_eq!(got.len(), 3, "one image per chamber: {got:?}");
        // chambers are 100 wide and joined edge to edge, so the centre of
        // the k-th sits 100k away along +x in the observer's frame
        for (k, r) in got.iter().enumerate() {
            let centre = r.into_obs.apply(v(0.0, 0.0));
            assert!(
                (centre.x - 100.0 * k as f64).abs() < 1e-6 && centre.y.abs() < 1e-6,
                "chamber {k} developed to {centre:?}"
            );
            assert_eq!(r.depth, k);
        }
    }

    #[test]
    fn reach_stops_at_the_hop_cap() {
        let (w, ids) = corridor(6);
        let got = reach(&w, ids[0], v(0.0, 0.0), 2, 10_000.0);
        assert_eq!(got.len(), 3, "observer + 2 hops");
        assert!(got.iter().all(|r| r.depth <= 2));
    }

    #[test]
    fn reach_prunes_on_range_but_never_a_chamber_a_sightline_could_enter() {
        let (w, ids) = corridor(6);
        // the doorway into chamber k is 50 + 100(k-1) away, so a 160-unit
        // reach admits chambers 1 and 2 (doorways at 50 and 150) and must
        // refuse chamber 3 (250)
        let got = reach(&w, ids[0], v(0.0, 0.0), 8, 160.0);
        let depths: Vec<usize> = got.iter().map(|r| r.depth).collect();
        assert_eq!(depths, vec![0, 1, 2], "reached {depths:?}");
    }

    #[test]
    fn reach_bound_is_never_longer_than_the_real_sightline() {
        // the prune must be a LOWER bound: if it ever exceeded the true
        // straight-line distance it would hide bodies that are in range
        let (w, ids) = corridor(4);
        for r in reach(&w, ids[0], v(0.0, 0.0), 8, 10_000.0) {
            let centre = r.into_obs.apply(v(0.0, 0.0));
            let real = (centre - v(0.0, 0.0)).len();
            assert!(
                r.near <= real + 1e-9,
                "bound {} exceeds the real distance {real} at depth {}",
                r.near,
                r.depth
            );
        }
    }

    #[test]
    fn reach_agrees_with_route_on_where_a_body_lands() {
        // the walk is an inverted `route`; the two must develop a place to
        // the same point or perception and navigation disagree
        let (w, ids) = corridor(4);
        let target = v(12.0, -7.0);
        let got = reach(&w, ids[0], v(0.0, 0.0), 8, 10_000.0);
        for r in &got {
            let by_walk = r.into_obs.apply(target);
            let rt = route(&w, r.polygon, target, ids[0], 8).expect("route back");
            let by_route = Coordinate::new(
                w.polygon_space(r.polygon).unwrap().id(),
                target,
            )
            .extended(&rt.steps);
            let d = (by_walk - by_route.local()).len();
            assert!(d < 1e-6, "walk and route disagree by {d} at depth {}", r.depth);
        }
    }

    #[test]
    fn raycast_crosses_portals_and_hits_walls() {
        let mut w = World::new();
        let a = w.add_polygon(&square(50.0)).unwrap();
        let b = w.add_polygon(&square(50.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        let sim = Sim::new(w);
        let hit = raycast(&sim, a, v(0.0, 0.0), v(1.0, 0.0), 4, 1000.0, 0xffff, None);
        match hit {
            RayHit::Wall { polygon, dist, .. } => {
                assert_eq!(polygon, b);
                assert!((dist - 150.0).abs() < 1e-6, "dist {dist}");
            }
            other => panic!("expected wall in b, got {other:?}"),
        }
    }

    #[test]
    fn raycast_hits_entity_through_portal() {
        let mut w = World::new();
        let a = w.add_polygon(&square(50.0)).unwrap();
        let b = w.add_polygon(&square(50.0)).unwrap();
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
        let polygons: Vec<_> = (0..5).map(|_| w.add_polygon(&square(50.0)).unwrap()).collect();
        for i in 0..4 {
            w.connect(polygons[i], 2, polygons[i + 1], 0).unwrap();
        }
        let mut router = Router::new();
        // From polygon 0 toward polygon 4: take edge 2 each time.
        assert_eq!(router.next_edge(&w, polygons[0], polygons[4]), Some(2));
        assert_eq!(router.hop_distance(&w, polygons[0], polygons[4]), Some(4));
        assert_eq!(router.next_edge(&w, polygons[4], polygons[0]), Some(0));
        assert_eq!(router.next_edge(&w, polygons[2], polygons[2]), None);
    }

    // ENGINE_INVARIANTS.md W8/Q3 (wave-1): Router caches a BFS table per
    // destination, keyed by `world.topology_version` (query.rs
    // `next_edge`: `if entry.0 != world.topology_version { rebuild }`).
    // That invalidation mechanism had ZERO test coverage before this: the
    // only existing router test never mutates topology after building the
    // router, so a regression that dropped or broke the version check
    // would pass silently. This is exactly the stale-cache bug shape the
    // catalog flags: `split_edge` (the runtime portable-hole feature)
    // mutates topology at runtime, and AI routing depends on
    // `Router::next_edge`/`hop_distance` staying current.
    //
    // Adversarial dimensions: (a) a topology change that shortens an
    // existing cached route (add_polygon/connect shortcut), and (b) a
    // split_edge that shifts the very edge index the cached table names
    // as the correct hop -- if invalidation didn't fire, the router would
    // hand back an edge index into the OLD topology, which after the
    // shift either points at the wrong (or a since-reindexed) edge.
    //
    // Verified fail-first: temporarily hardcoded the cache-freshness
    // check to always reuse the cached entry (`if false { rebuild }`
    // instead of comparing topology_version) and reran -- both cases
    // failed (stale hop count / stale edge index), confirming this is
    // real instrumentation. Reverted before committing.
    #[test]
    fn router_cache_invalidates_on_topology_change() {
        let mut w = World::new();
        let polygons: Vec<_> = (0..5).map(|_| w.add_polygon(&square(50.0)).unwrap()).collect();
        for i in 0..4 {
            w.connect(polygons[i], 2, polygons[i + 1], 0).unwrap();
        }
        let mut router = Router::new();
        assert_eq!(router.hop_distance(&w, polygons[0], polygons[4]), Some(4));
        assert_eq!(router.next_edge(&w, polygons[0], polygons[4]), Some(2));

        // A direct shortcut 0<->4 via each polygon's still-free edge 1.
        // topology_version bumps; the cached table for dest=polygons[4] must
        // be rebuilt, not silently reused.
        w.connect(polygons[0], 1, polygons[4], 1).unwrap();
        assert_eq!(
            router.hop_distance(&w, polygons[0], polygons[4]),
            Some(1),
            "router served a stale (pre-shortcut) hop count after a topology change"
        );
        assert_eq!(
            router.next_edge(&w, polygons[0], polygons[4]),
            Some(1),
            "router served a stale (pre-shortcut) edge after a topology change"
        );

        // split_edge on a wall NOT on the cached route also bumps
        // topology_version; the cached table must still be consistent
        // with a fresh BFS build (same result as a brand-new Router).
        let mid = w.split_edge(polygons[2], 1, 0.3, 0.6).unwrap();
        let _ = mid;
        let mut fresh = Router::new();
        assert_eq!(
            router.hop_distance(&w, polygons[3], polygons[0]),
            fresh.hop_distance(&w, polygons[3], polygons[0]),
            "cached router disagreed with a freshly-built one after split_edge"
        );
        assert_eq!(
            router.next_edge(&w, polygons[3], polygons[0]),
            fresh.next_edge(&w, polygons[3], polygons[0])
        );
    }

    // -- physical routing --------------------------------------------

    fn rect(w: f64, h: f64) -> Vec<Vec2> {
        vec![
            v(-w * 0.5, -h * 0.5),
            v(-w * 0.5, h * 0.5),
            v(w * 0.5, h * 0.5),
            v(w * 0.5, -h * 0.5),
        ]
    }

    /// A world where the hop-minimal route and the physically shortest route
    /// DISAGREE, which is the whole reason this metric exists. `a` is a long
    /// hall; the source sits at its left end. One doorway at the far right end
    /// reaches `t` in a single hop (990 units away). Three small chambers
    /// hanging off the near left edge reach `t` in three hops but 90 units.
    fn hops_vs_distance() -> (World, PolygonId, PolygonId, Vec2) {
        let mut w = World::new();
        let a = w.add_polygon(&rect(1000.0, 200.0)).unwrap();
        let b = w.add_polygon(&rect(40.0, 200.0)).unwrap();
        let c = w.add_polygon(&rect(40.0, 200.0)).unwrap();
        let t = w.add_polygon(&rect(200.0, 200.0)).unwrap();
        w.connect(a, 2, t, 0).unwrap(); // far right end -> t, one hop
        w.connect(a, 0, b, 2).unwrap(); // near left end -> b
        w.connect(b, 0, c, 2).unwrap();
        w.connect(c, 0, t, 3).unwrap();
        (w, a, t, v(-490.0, 0.0))
    }

    #[test]
    fn route_measures_distance_and_not_hops() {
        let (w, a, t, src) = hops_vs_distance();
        // The hop router picks the one-hop door, as it should — that is the
        // right answer to a different question.
        let mut hop = Router::new();
        assert_eq!(hop.hop_distance(&w, a, t), Some(1));

        let r = route(&w, a, src, t, 8).expect("a route must exist");
        assert_eq!(
            r.hops(),
            3,
            "physical routing must take the three short chambers (90u), not \
             the single 990u hall — got {} hops, {:.0}u",
            r.hops(),
            r.dist
        );
        assert!((r.dist - 90.0).abs() < 1e-6, "dist {:.3}", r.dist);
        assert_eq!(r.polygons.last().copied(), Some(t));
        assert_eq!(r.steps.len(), r.polygons.len());
        assert_eq!(
            r.steps.last().unwrap().into,
            w.polygon_space(t).unwrap().id(),
            "the last step must enter the destination's own space"
        );
    }

    #[test]
    fn route_obeys_the_hop_ceiling_without_silently_picking_a_worse_answer() {
        let (w, a, t, src) = hops_vs_distance();
        // Cap below the short route: the long one is still legitimate.
        let r = route(&w, a, src, t, 2).expect("the one-hop route is inside the cap");
        assert_eq!(r.hops(), 1);
        assert!((r.dist - 990.0).abs() < 1e-6, "dist {:.3}", r.dist);
        // Cap at zero: nowhere to go.
        assert!(route(&w, a, src, t, 0).is_none());
        // Same polygon is the empty route, not a failure.
        let same = route(&w, a, src, a, 4).unwrap();
        assert_eq!(same.hops(), 0);
        assert_eq!(same.dist, 0.0);
    }

    #[test]
    fn develop_carries_a_coordinate_into_another_polygons_space() {
        let (w, a, t, src) = hops_vs_distance();
        let here = Coordinate::new(w.polygon_space(a).unwrap().id(), src);
        let there = develop(&w, &here, w.polygon_space(t).unwrap().id()).unwrap();
        assert_eq!(there.space(), w.polygon_space(t).unwrap().id());
        assert_eq!(there.record().len(), 3, "the record must show the route taken");
        // The developed place is comparable with a local one, and the numbers
        // agree with composing the portal matrices by hand.
        let mut m = Mat3::IDENTITY;
        for step in there.record() {
            m = step.xform.mul(m);
        }
        assert!((there.local() - m.apply(src)).len() < 1e-9);
        // Developing to where it already is changes nothing.
        let same = develop(&w, &here, w.polygon_space(a).unwrap().id()).unwrap();
        assert_eq!(same.record().len(), 0);
    }

    #[test]
    fn develop_answers_none_for_a_space_no_doorway_reaches() {
        // The screen is a space. No route of doorways reaches it, and the
        // honest answer is None rather than a plausible number.
        let (w, a, _t, src) = hops_vs_distance();
        let screen = crate::frames::CoordinateSpace::new("Screenspace");
        let here = Coordinate::new(w.polygon_space(a).unwrap().id(), src);
        assert!(develop(&w, &here, screen.id()).is_none());
        // ...and for a polygon with no route at all.
        let mut w2 = World::new();
        let x = w2.add_polygon(&rect(50.0, 50.0)).unwrap();
        let y = w2.add_polygon(&rect(50.0, 50.0)).unwrap();
        let p = Coordinate::new(w2.polygon_space(x).unwrap().id(), v(0.0, 0.0));
        assert!(develop(&w2, &p, w2.polygon_space(y).unwrap().id()).is_none());
    }

    #[test]
    fn routes_enumerates_distinct_images_shortest_first() {
        // Two doorways between the same pair of chambers: two genuinely
        // different images of the same body, and a loop, so the enumeration
        // has no end — only a budget.
        let mut w = World::new();
        let a = w.add_polygon(&rect(200.0, 200.0)).unwrap();
        let b = w.add_polygon(&rect(200.0, 200.0)).unwrap();
        w.connect(a, 2, b, 0).unwrap();
        w.connect(a, 0, b, 2).unwrap();
        let src = v(-50.0, 0.0);
        let got = routes(&w, a, src, b, 6, 4);
        assert!(got.len() >= 2, "two doorways must give at least two images");
        for pair in got.windows(2) {
            assert!(
                pair[0].dist <= pair[1].dist + 1e-9,
                "must come shortest first: {:.1} then {:.1}",
                pair[0].dist,
                pair[1].dist
            );
        }
        // Distinct means distinct developed image.
        let mut images: Vec<(i64, i64)> = got
            .iter()
            .map(|r| {
                let mut p = src;
                for s in &r.steps {
                    p = s.xform.apply(p);
                }
                ((p.x * 1000.0) as i64, (p.y * 1000.0) as i64)
            })
            .collect();
        let n = images.len();
        images.sort_unstable();
        images.dedup();
        assert_eq!(images.len(), n, "the same image must not be listed twice");
        // Raising the budget really does see further — that is what "the
        // generator may never terminate" means in practice.
        assert!(routes(&w, a, src, b, 12, 12).len() > got.len());
        // The shortest of the enumeration agrees with the single-answer route.
        let best = route(&w, a, src, b, 6).unwrap();
        assert!((got[0].dist - best.dist).abs() < 1e-9);
    }

    #[test]
    fn routes_from_a_polygon_to_itself_starts_with_the_empty_route() {
        let (w, a, _t, src) = hops_vs_distance();
        let got = routes(&w, a, src, a, 4, 3);
        assert!(!got.is_empty());
        assert_eq!(got[0].hops(), 0);
        assert_eq!(got[0].dist, 0.0);
    }

    // -- walk-mask terrain queries -----------------------------------

    #[test]
    fn terrain_light_segments_is_empty_absent_a_mask_and_four_edges_once_set() {
        let mut w = World::new();
        let r = w.add_polygon(&square(50.0)).unwrap();
        assert!(
            terrain_light_segments(&w, r).is_empty(),
            "absence must mean walkable/unoccluded, not fabricated occluder geometry"
        );
        w.set_polygon_terrain(r, vec![crate::geom::Rect::new(v(-5.0, -5.0), v(5.0, 5.0))])
            .unwrap();
        let segs = terrain_light_segments(&w, r);
        assert_eq!(segs.len(), 4, "one rect must contribute exactly its 4 edges");
        // Every segment endpoint must lie on the rect boundary.
        for (a, b) in &segs {
            for p in [a, b] {
                let on_boundary = (p.x - (-5.0)).abs() < 1e-9
                    || (p.x - 5.0).abs() < 1e-9
                    || (p.y - (-5.0)).abs() < 1e-9
                    || (p.y - 5.0).abs() < 1e-9;
                assert!(on_boundary, "segment endpoint off the rect boundary: {:?}", p);
            }
        }
        // Unknown polygon: empty, not a panic.
        assert!(terrain_light_segments(&w, 999).is_empty());
    }

    #[test]
    fn terrain_avoid_dir_passes_through_when_the_path_is_clear() {
        let mut w = World::new();
        let r = w.add_polygon(&square(50.0)).unwrap();
        w.set_polygon_terrain(r, vec![crate::geom::Rect::new(v(30.0, 30.0), v(40.0, 40.0))])
            .unwrap();
        // Desired direction doesn't come near the rect at all.
        let desired = v(-1.0, 0.0);
        let steered = terrain_avoid_dir(&w, r, v(0.0, -30.0), 3.0, desired, 25.0);
        assert!(steered.dist(desired) < 1e-9, "deflected an already-clear path: {:?}", steered);
    }

    #[test]
    fn terrain_avoid_dir_deflects_and_is_deterministic_for_a_static_scene() {
        let mut w = World::new();
        let r = w.add_polygon(&square(50.0)).unwrap();
        w.set_polygon_terrain(r, vec![crate::geom::Rect::new(v(-5.0, -5.0), v(5.0, 5.0))])
            .unwrap();
        let desired = v(1.0, 0.0); // straight at the rect, dead center
        let steered = terrain_avoid_dir(&w, r, v(-30.0, 0.0), 3.0, desired, 40.0);
        assert!(steered.dist(desired) > 1e-3, "did not deflect a head-on approach");
        assert!((steered.len() - 1.0).abs() < 1e-9, "steered direction must stay unit length");
        // Same inputs must give the same output every time (no chatter).
        let steered2 = terrain_avoid_dir(&w, r, v(-30.0, 0.0), 3.0, desired, 40.0);
        assert_eq!(steered.x, steered2.x);
        assert_eq!(steered.y, steered2.y);
    }
}
