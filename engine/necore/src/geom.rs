use crate::math::{v, Vec2};

/// Shoelace signed area. Engine-canonical polygons (y-down, visually CCW)
/// have NEGATIVE signed area.
pub fn signed_area(pts: &[Vec2]) -> f64 {
    let n = pts.len();
    let mut a = 0.0;
    for i in 0..n {
        let p = pts[i];
        let q = pts[(i + 1) % n];
        a += p.x * q.y - q.x * p.y;
    }
    a * 0.5
}

pub fn centroid(pts: &[Vec2]) -> Vec2 {
    let n = pts.len();
    let a = signed_area(pts);
    if a.abs() < 1e-12 {
        let mut c = Vec2::ZERO;
        for p in pts {
            c = c + *p;
        }
        return c * (1.0 / n as f64);
    }
    let mut cx = 0.0;
    let mut cy = 0.0;
    for i in 0..n {
        let p = pts[i];
        let q = pts[(i + 1) % n];
        let w = p.x * q.y - q.x * p.y;
        cx += (p.x + q.x) * w;
        cy += (p.y + q.y) * w;
    }
    v(cx / (6.0 * a), cy / (6.0 * a))
}

/// Canonical winding: negative shoelace area (visual CCW in y-down coords).
/// Returns true if the polygon had to be reversed.
pub fn canonicalize_winding(pts: &mut Vec<Vec2>) -> bool {
    if signed_area(pts) > 0.0 {
        pts.reverse();
        true
    } else {
        false
    }
}

/// Strict convexity check for a canonical-wound polygon. Every consecutive
/// edge pair must turn the same way (cross <= 0 for canonical winding);
/// near-zero cross (collinear) is tolerated.
pub fn is_convex(pts: &[Vec2]) -> bool {
    let n = pts.len();
    if n < 3 {
        return false;
    }
    for i in 0..n {
        let a = pts[i];
        let b = pts[(i + 1) % n];
        let c = pts[(i + 2) % n];
        let cr = (b - a).cross(c - b);
        if cr > 1e-9 {
            return false;
        }
    }
    true
}

/// Inward normal of edge a->b of a canonical-wound polygon (unit length).
pub fn inward_normal(a: Vec2, b: Vec2) -> Vec2 {
    (b - a).perp_right().normalized()
}

/// Edges shorter than this are treated as nonexistent by every edge-loop
/// half-plane builder below. A zero-length edge has no direction: its
/// "normal" out of `normalized()`'s fallback is the arbitrary (1,0), which
/// fabricates a phantom vertical half-plane anchored at the duplicate
/// vertex. One duplicated clip vertex then annihilates (or spares — pure
/// luck of position) everything clipped against that polygon. This was THE
/// polygon-decor flicker: `visible_set` wedge clips can carry an adjacent
/// duplicate vertex whose position shifts per tick, so prims/entities of a
/// whole polygon blinked at up to 30Hz while floor and walls (scanline fill /
/// engine wall spans, no edge normals) stayed. A degenerate edge is not a
/// constraint; skip it.
pub const DEGENERATE_EDGE: f64 = 1e-9;

/// A half-plane {p : dot(p - point, normal) >= 0}. `normal` points INTO the
/// kept region.
#[derive(Debug, Clone, Copy)]
pub struct HalfPlane {
    pub point: Vec2,
    pub normal: Vec2,
}

impl HalfPlane {
    pub fn signed_dist(&self, p: Vec2) -> f64 {
        (p - self.point).dot(self.normal)
    }
}

/// Sutherland-Hodgman clip of a convex polygon against one half-plane.
/// Output winding matches input. Result may be empty.
pub fn clip_polygon_halfplane(pts: &[Vec2], hp: &HalfPlane) -> Vec<Vec2> {
    let n = pts.len();
    let mut out = Vec::with_capacity(n + 2);
    if n == 0 {
        return out;
    }
    let mut prev = pts[n - 1];
    let mut prev_d = hp.signed_dist(prev);
    for i in 0..n {
        let cur = pts[i];
        let cur_d = hp.signed_dist(cur);
        if cur_d >= 0.0 {
            if prev_d < 0.0 {
                let t = prev_d / (prev_d - cur_d);
                out.push(prev.lerp(cur, t));
            }
            out.push(cur);
        } else if prev_d >= 0.0 {
            let t = prev_d / (prev_d - cur_d);
            out.push(prev.lerp(cur, t));
        }
        prev = cur;
        prev_d = cur_d;
    }
    out
}

pub fn clip_polygon(pts: &[Vec2], hps: &[HalfPlane]) -> Vec<Vec2> {
    let mut cur = pts.to_vec();
    for hp in hps {
        if cur.len() < 3 {
            return Vec::new();
        }
        cur = clip_polygon_halfplane(&cur, hp);
    }
    if cur.len() < 3 {
        Vec::new()
    } else {
        cur
    }
}

/// Clip convex polygon `subject` against convex polygon `clip` (both canonical
/// winding): builds clip's edge half-planes and applies them.
pub fn clip_polygon_convex(subject: &[Vec2], clip: &[Vec2]) -> Vec<Vec2> {
    let n = clip.len();
    let mut cur = subject.to_vec();
    for i in 0..n {
        if cur.len() < 3 {
            return Vec::new();
        }
        let a = clip[i];
        let b = clip[(i + 1) % n];
        if a.dist(b) < DEGENERATE_EDGE {
            continue;
        }
        let hp = HalfPlane {
            point: a,
            normal: inward_normal(a, b),
        };
        cur = clip_polygon_halfplane(&cur, &hp);
    }
    if cur.len() < 3 {
        Vec::new()
    } else {
        cur
    }
}

/// Clip segment [a,b] to a set of half-planes. Returns the surviving
/// parametric range as points, or None if fully clipped.
pub fn clip_segment(a: Vec2, b: Vec2, hps: &[HalfPlane]) -> Option<(Vec2, Vec2)> {
    let mut t0 = 0.0f64;
    let mut t1 = 1.0f64;
    let d = b - a;
    for hp in hps {
        let da = hp.signed_dist(a);
        let dd = d.dot(hp.normal);
        if dd.abs() < 1e-12 {
            if da < 0.0 {
                return None;
            }
            continue;
        }
        let t = -da / dd;
        if dd > 0.0 {
            // entering the half-plane at t
            t0 = t0.max(t);
        } else {
            t1 = t1.min(t);
        }
        if t0 >= t1 {
            return None;
        }
    }
    Some((a.lerp(b, t0), a.lerp(b, t1)))
}

/// Inward-normal half-planes of a convex polygon's edges, in edge order —
/// exactly the planes `clip_polygon_convex` / `clip_polyline_convex` build
/// internally. Exposed so callers (the rasterizer) can build them once per
/// clip polygon and reuse them across many prims.
pub fn polygon_halfplanes(clip: &[Vec2]) -> Vec<HalfPlane> {
    let n = clip.len();
    let mut hps = Vec::with_capacity(n);
    for i in 0..n {
        let a = clip[i];
        let b = clip[(i + 1) % n];
        if a.dist(b) < DEGENERATE_EDGE {
            continue;
        }
        hps.push(HalfPlane {
            point: a,
            normal: inward_normal(a, b),
        });
    }
    hps
}

/// Clip a polyline to a convex polygon; returns the visible sub-polylines.
pub fn clip_polyline_convex(pts: &[Vec2], clip: &[Vec2]) -> Vec<Vec<Vec2>> {
    clip_polyline_halfplanes(pts, &polygon_halfplanes(clip))
}

/// `clip_polyline_convex` with the clip polygon's half-planes precomputed.
pub fn clip_polyline_halfplanes(pts: &[Vec2], hps: &[HalfPlane]) -> Vec<Vec<Vec2>> {
    let mut out: Vec<Vec<Vec2>> = Vec::new();
    let mut cur: Vec<Vec2> = Vec::new();
    for w in pts.windows(2) {
        match clip_segment(w[0], w[1], hps) {
            Some((p, q)) => {
                if let Some(last) = cur.last() {
                    if last.dist(p) > 1e-9 {
                        out.push(std::mem::take(&mut cur));
                        cur.push(p);
                    }
                } else {
                    cur.push(p);
                }
                cur.push(q);
            }
            None => {
                if !cur.is_empty() {
                    out.push(std::mem::take(&mut cur));
                }
            }
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

pub fn point_in_polygon(p: Vec2, pts: &[Vec2], eps: f64) -> bool {
    let n = pts.len();
    for i in 0..n {
        let a = pts[i];
        let b = pts[(i + 1) % n];
        if a.dist(b) < DEGENERATE_EDGE {
            continue;
        }
        if (p - a).dot(inward_normal(a, b)) < -eps {
            return false;
        }
    }
    true
}

/// Distance from point to the polygon boundary going inward: the minimum
/// signed distance over edges (positive inside).
pub fn depth_in_polygon(p: Vec2, pts: &[Vec2]) -> f64 {
    let n = pts.len();
    let mut d = f64::INFINITY;
    for i in 0..n {
        let a = pts[i];
        let b = pts[(i + 1) % n];
        if a.dist(b) < DEGENERATE_EDGE {
            continue;
        }
        d = d.min((p - a).dot(inward_normal(a, b)));
    }
    d
}

/// Axis-aligned rect in a polygon's own local coordinates (same frame as the
/// polygon's `verts`/floor texture). This is the terrain-mask collision
/// primitive: a downsampled walk-mask PNG is reduced to a small set of these
/// (see `game/perihelion/terrain.py`), one per blocked equipment footprint.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Rect {
    pub lo: Vec2,
    pub hi: Vec2,
}

impl Rect {
    /// Normalizes corners so `lo <= hi` componentwise regardless of input order.
    pub fn new(a: Vec2, b: Vec2) -> Rect {
        Rect {
            lo: v(a.x.min(b.x), a.y.min(b.y)),
            hi: v(a.x.max(b.x), a.y.max(b.y)),
        }
    }

    pub fn inflate(&self, r: f64) -> Rect {
        Rect {
            lo: v(self.lo.x - r, self.lo.y - r),
            hi: v(self.hi.x + r, self.hi.y + r),
        }
    }

    pub fn contains(&self, p: Vec2) -> bool {
        p.x >= self.lo.x && p.x <= self.hi.x && p.y >= self.lo.y && p.y <= self.hi.y
    }

    /// The four edges of the rect as (a, b) segments, winding order matching
    /// the polygon's own canonical CCW convention closely enough for occluder
    /// use (a light/shadow pass only needs the segment geometry, not a
    /// polygon interior test).
    pub fn edges(&self) -> [(Vec2, Vec2); 4] {
        let (lo, hi) = (self.lo, self.hi);
        let tl = v(lo.x, lo.y);
        let tr = v(hi.x, lo.y);
        let br = v(hi.x, hi.y);
        let bl = v(lo.x, hi.y);
        [(tl, tr), (tr, br), (br, bl), (bl, tl)]
    }
}

/// Swept-circle-vs-rect entry test along the moving segment `pos -> target`
/// (circle of `radius`, axis-aligned `rect`, both in the same polygon-local
/// frame). Returns the earliest entry parameter `t` in `(0, 1]` and the
/// OUTWARD face normal (pointing away from the rect, back toward where the
/// circle came from -- the same convention `physics.rs` wall code uses for
/// its reflection normal) at first contact, or `None` if the segment never
/// enters the radius-padded rect during this substep.
///
/// The padding is a square (Minkowski-sum-with-radius) expansion, not a
/// rounded rect: a superset of the true rounded corner region, so a
/// diagonal approach to a corner is stopped a hair early rather than ever
/// tunneling past it -- the same "safe over exact" trade `EDGE_SPAN_EXT`
/// makes for wall seams.
///
/// A circle whose center is ALREADY inside the padded rect at `pos` (t=0
/// would be the "crossing") returns `None`: that is not a crossing this
/// substep, and callers handle an already-embedded center with a separate
/// positional correction (mirroring how polygon-wall containment is a
/// standalone pass, not part of the crossing test).
pub fn swept_circle_vs_rect(pos: Vec2, target: Vec2, radius: f64, rect: &Rect) -> Option<(f64, Vec2)> {
    let padded = rect.inflate(radius);
    let d = target - pos;
    let mut t0 = 0.0f64;
    let mut t1 = 1.0f64;
    let mut normal = Vec2::ZERO;

    if d.x.abs() < 1e-12 {
        if pos.x < padded.lo.x || pos.x > padded.hi.x {
            return None;
        }
    } else {
        let inv = 1.0 / d.x;
        let (tmin, tmax, n_near) = if d.x > 0.0 {
            ((padded.lo.x - pos.x) * inv, (padded.hi.x - pos.x) * inv, v(-1.0, 0.0))
        } else {
            ((padded.hi.x - pos.x) * inv, (padded.lo.x - pos.x) * inv, v(1.0, 0.0))
        };
        if tmin > t0 {
            t0 = tmin;
            normal = n_near;
        }
        t1 = t1.min(tmax);
        if t0 > t1 {
            return None;
        }
    }

    if d.y.abs() < 1e-12 {
        if pos.y < padded.lo.y || pos.y > padded.hi.y {
            return None;
        }
    } else {
        let inv = 1.0 / d.y;
        let (tmin, tmax, n_near) = if d.y > 0.0 {
            ((padded.lo.y - pos.y) * inv, (padded.hi.y - pos.y) * inv, v(0.0, -1.0))
        } else {
            ((padded.hi.y - pos.y) * inv, (padded.lo.y - pos.y) * inv, v(0.0, 1.0))
        };
        if tmin > t0 {
            t0 = tmin;
            normal = n_near;
        }
        t1 = t1.min(tmax);
        if t0 > t1 {
            return None;
        }
    }

    if t0 <= 1e-12 || t0 > 1.0 {
        return None;
    }
    Some((t0, normal))
}

pub fn polygon_bbox(pts: &[Vec2]) -> (Vec2, Vec2) {
    let mut lo = v(f64::INFINITY, f64::INFINITY);
    let mut hi = v(f64::NEG_INFINITY, f64::NEG_INFINITY);
    for p in pts {
        lo.x = lo.x.min(p.x);
        lo.y = lo.y.min(p.y);
        hi.x = hi.x.max(p.x);
        hi.y = hi.y.max(p.y);
    }
    (lo, hi)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn square() -> Vec<Vec2> {
        // canonical: y-down visual CCW, negative area
        vec![v(0.0, 0.0), v(0.0, 2.0), v(2.0, 2.0), v(2.0, 0.0)]
    }

    #[test]
    fn canonical_square_checks() {
        let sq = square();
        assert!(signed_area(&sq) < 0.0);
        assert!(is_convex(&sq));
        assert!(point_in_polygon(v(1.0, 1.0), &sq, 1e-9));
        assert!(!point_in_polygon(v(3.0, 1.0), &sq, 1e-9));
        let c = centroid(&sq);
        assert!(c.dist(v(1.0, 1.0)) < 1e-9);
    }

    #[test]
    fn clip_square_by_halfplane() {
        let sq = square();
        let hp = HalfPlane {
            point: v(1.0, 0.0),
            normal: v(1.0, 0.0),
        };
        let clipped = clip_polygon(&sq, &[hp]);
        assert_eq!(clipped.len(), 4);
        assert!((signed_area(&clipped).abs() - 2.0).abs() < 1e-9);
        for p in &clipped {
            assert!(p.x >= 1.0 - 1e-9);
        }
    }

    #[test]
    fn clip_convex_by_convex() {
        let sq = square();
        let tri = vec![v(1.0, -1.0), v(1.0, 3.0), v(5.0, 1.0)];
        let mut tri = tri;
        canonicalize_winding(&mut tri);
        let out = clip_polygon_convex(&sq, &tri);
        assert!(out.len() >= 3);
        for p in &out {
            assert!(point_in_polygon(*p, &sq, 1e-6));
            assert!(point_in_polygon(*p, &tri, 1e-6));
        }
    }

    #[test]
    fn segment_clip() {
        let hps = [HalfPlane {
            point: v(1.0, 0.0),
            normal: v(1.0, 0.0),
        }];
        let r = clip_segment(v(0.0, 0.0), v(2.0, 0.0), &hps).unwrap();
        assert!(r.0.dist(v(1.0, 0.0)) < 1e-9);
        assert!(r.1.dist(v(2.0, 0.0)) < 1e-9);
        assert!(clip_segment(v(0.0, 0.0), v(0.5, 0.0), &hps).is_none());
    }

    /// THE FLICKER REGRESSION: a clip polygon carrying an adjacent
    /// duplicate vertex (any position, including the first/last wrap
    /// pair) must clip exactly like the clean polygon. Before the
    /// degenerate-edge guards, the duplicate's zero-length edge got the
    /// arbitrary (1,0) fallback normal — a phantom vertical half-plane
    /// that annihilated the result whenever the duplicate sat on the
    /// right-hand boundary. Polygon decor blinked at up to 30Hz.
    #[test]
    fn duplicate_clip_vertex_is_inert() {
        let sq = vec![v(0.0, 0.0), v(0.0, 2.0), v(2.0, 2.0), v(2.0, 0.0)];
        let subject = vec![v(0.2, 0.2), v(0.2, 1.8), v(1.8, 1.8), v(1.8, 0.2)];
        let clean = clip_polygon_convex(&subject, &sq);
        assert_eq!(clean.len(), 4);
        for dup_at in 0..4 {
            let mut dirty = sq.clone();
            dirty.insert(dup_at, sq[dup_at]);
            let got = clip_polygon_convex(&subject, &dirty);
            assert_eq!(got.len(), clean.len(),
                "duplicate at {dup_at} changed the clip result");
            // wrap-pair variant: rotate so the duplicate spans the seam
            let mut wrapped = dirty.clone();
            wrapped.rotate_left(dup_at + 1);
            let got_w = clip_polygon_convex(&subject, &wrapped);
            assert_eq!(got_w.len(), clean.len(),
                "wrap duplicate rotated from {dup_at} changed the clip result");
        }
        // point/depth tests must also ignore the degenerate edge
        let mut wrap_dup = sq.clone();
        wrap_dup.push(sq[0]);
        assert!(point_in_polygon(v(1.0, 1.0), &wrap_dup, 1e-9));
        assert!(!point_in_polygon(v(3.0, 1.0), &wrap_dup, 1e-9));
        assert!(depth_in_polygon(v(1.0, 1.0), &wrap_dup) > 0.9);
        // polyline clipping through a wrap-duplicated clip polygon
        let segs = clip_polyline_convex(&[v(-1.0, 1.0), v(3.0, 1.0)], &wrap_dup);
        assert_eq!(segs.len(), 1);
        assert!(segs[0][0].dist(v(0.0, 1.0)) < 1e-9);
        assert!(segs[0].last().unwrap().dist(v(2.0, 1.0)) < 1e-9);
    }

    // -- terrain-mask primitives (director's walk-mask directive) --------

    #[test]
    fn swept_circle_vs_rect_stops_at_padded_face_from_every_side() {
        let rect = Rect::new(v(10.0, 10.0), v(20.0, 20.0));
        // Approach from the left along +x.
        let (t, n) = swept_circle_vs_rect(v(0.0, 15.0), v(30.0, 15.0), 2.0, &rect).unwrap();
        let hit = v(0.0, 15.0).lerp(v(30.0, 15.0), t);
        assert!((hit.x - 8.0).abs() < 1e-9, "hit {:?}", hit); // 10 - radius
        assert!(n.dist(v(-1.0, 0.0)) < 1e-9);

        // From the right along -x.
        let (t, n) = swept_circle_vs_rect(v(30.0, 15.0), v(0.0, 15.0), 2.0, &rect).unwrap();
        let hit = v(30.0, 15.0).lerp(v(0.0, 15.0), t);
        assert!((hit.x - 22.0).abs() < 1e-9, "hit {:?}", hit);
        assert!(n.dist(v(1.0, 0.0)) < 1e-9);

        // From above along +y.
        let (t, n) = swept_circle_vs_rect(v(15.0, 0.0), v(15.0, 30.0), 2.0, &rect).unwrap();
        let hit = v(15.0, 0.0).lerp(v(15.0, 30.0), t);
        assert!((hit.y - 8.0).abs() < 1e-9, "hit {:?}", hit);
        assert!(n.dist(v(0.0, -1.0)) < 1e-9);

        // From below along -y.
        let (t, n) = swept_circle_vs_rect(v(15.0, 30.0), v(15.0, 0.0), 2.0, &rect).unwrap();
        let hit = v(15.0, 30.0).lerp(v(15.0, 0.0), t);
        assert!((hit.y - 22.0).abs() < 1e-9, "hit {:?}", hit);
        assert!(n.dist(v(0.0, 1.0)) < 1e-9);
    }

    #[test]
    fn swept_circle_vs_rect_never_tunnels_on_a_fast_diagonal_pass() {
        // A "bullet"-speed diagonal crossing straight through the rect must
        // still register an entry, not skip clean through.
        let rect = Rect::new(v(-5.0, -5.0), v(5.0, 5.0));
        let hit = swept_circle_vs_rect(v(-200.0, -200.0), v(200.0, 200.0), 1.0, &rect);
        assert!(hit.is_some(), "diagonal pass tunneled through the rect");
    }

    #[test]
    fn swept_circle_vs_rect_misses_a_parallel_near_pass() {
        let rect = Rect::new(v(0.0, 0.0), v(10.0, 10.0));
        // Passes well clear of the padded rect (radius 1, gap 5).
        let hit = swept_circle_vs_rect(v(-10.0, 16.0), v(10.0, 16.0), 1.0, &rect);
        assert!(hit.is_none(), "phantom hit on a clean miss: {:?}", hit);
    }

    #[test]
    fn swept_circle_vs_rect_already_embedded_is_not_a_crossing() {
        let rect = Rect::new(v(0.0, 0.0), v(10.0, 10.0));
        // Starts already inside the rect: not a "crossing" this substep --
        // the caller's separate positional correction owns this case.
        let hit = swept_circle_vs_rect(v(5.0, 5.0), v(5.0, 6.0), 1.0, &rect);
        assert!(hit.is_none());
    }
}
