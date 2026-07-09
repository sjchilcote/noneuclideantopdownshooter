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

/// Clip a polyline to a convex polygon; returns the visible sub-polylines.
pub fn clip_polyline_convex(pts: &[Vec2], clip: &[Vec2]) -> Vec<Vec<Vec2>> {
    let n = clip.len();
    let mut hps = Vec::with_capacity(n);
    for i in 0..n {
        let a = clip[i];
        let b = clip[(i + 1) % n];
        hps.push(HalfPlane {
            point: a,
            normal: inward_normal(a, b),
        });
    }
    let mut out: Vec<Vec<Vec2>> = Vec::new();
    let mut cur: Vec<Vec2> = Vec::new();
    for w in pts.windows(2) {
        match clip_segment(w[0], w[1], &hps) {
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
        d = d.min((p - a).dot(inward_normal(a, b)));
    }
    d
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
}
