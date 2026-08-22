use std::ops::{Add, Sub, Mul, Neg};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Vec2 {
    pub x: f64,
    pub y: f64,
}

pub const fn v(x: f64, y: f64) -> Vec2 {
    Vec2 { x, y }
}

impl Vec2 {
    pub const ZERO: Vec2 = v(0.0, 0.0);

    pub fn dot(self, o: Vec2) -> f64 {
        self.x * o.x + self.y * o.y
    }

    pub fn cross(self, o: Vec2) -> f64 {
        self.x * o.y - self.y * o.x
    }

    pub fn len(self) -> f64 {
        self.dot(self).sqrt()
    }

    pub fn len2(self) -> f64 {
        self.dot(self)
    }

    pub fn dist(self, o: Vec2) -> f64 {
        (self - o).len()
    }

    pub fn perp_left(self) -> Vec2 {
        v(-self.y, self.x)
    }

    /// Engine convention: coordinates are y-down (screen-like), polygons are
    /// wound visually counter-clockwise (negative shoelace area). For an edge
    /// a->b of such a polygon, `(b-a).perp_right()` points into the interior.
    pub fn perp_right(self) -> Vec2 {
        v(self.y, -self.x)
    }

    pub fn normalized(self) -> Vec2 {
        let l = self.len();
        if l < 1e-12 {
            v(1.0, 0.0)
        } else {
            v(self.x / l, self.y / l)
        }
    }

    pub fn lerp(self, o: Vec2, t: f64) -> Vec2 {
        self + (o - self) * t
    }
}

impl Add for Vec2 {
    type Output = Vec2;
    fn add(self, o: Vec2) -> Vec2 {
        v(self.x + o.x, self.y + o.y)
    }
}

impl Sub for Vec2 {
    type Output = Vec2;
    fn sub(self, o: Vec2) -> Vec2 {
        v(self.x - o.x, self.y - o.y)
    }
}

impl Mul<f64> for Vec2 {
    type Output = Vec2;
    fn mul(self, s: f64) -> Vec2 {
        v(self.x * s, self.y * s)
    }
}

impl Neg for Vec2 {
    type Output = Vec2;
    fn neg(self) -> Vec2 {
        v(-self.x, -self.y)
    }
}

/// Row-major 3x3 homogeneous transform. Affine today; the full 3x3 is kept so
/// projective connections stay possible. Points map through the whole matrix,
/// directions through the linear part only.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Mat3 {
    pub m: [f64; 9],
}

impl Mat3 {
    pub const IDENTITY: Mat3 = Mat3 {
        m: [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
    };

    pub fn translate(t: Vec2) -> Mat3 {
        Mat3 {
            m: [1.0, 0.0, t.x, 0.0, 1.0, t.y, 0.0, 0.0, 1.0],
        }
    }

    pub fn rotate(theta: f64) -> Mat3 {
        let (s, c) = theta.sin_cos();
        Mat3 {
            m: [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0],
        }
    }

    pub fn scale(sx: f64, sy: f64) -> Mat3 {
        Mat3 {
            m: [sx, 0.0, 0.0, 0.0, sy, 0.0, 0.0, 0.0, 1.0],
        }
    }

    pub fn mul(self, o: Mat3) -> Mat3 {
        let a = &self.m;
        let b = &o.m;
        let mut r = [0.0; 9];
        for i in 0..3 {
            for j in 0..3 {
                r[i * 3 + j] =
                    a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j];
            }
        }
        Mat3 { m: r }
    }

    pub fn apply(self, p: Vec2) -> Vec2 {
        let m = &self.m;
        let w = m[6] * p.x + m[7] * p.y + m[8];
        v(
            (m[0] * p.x + m[1] * p.y + m[2]) / w,
            (m[3] * p.x + m[4] * p.y + m[5]) / w,
        )
    }

    /// Linear part only: how velocities and facing directions transform.
    pub fn apply_dir(self, d: Vec2) -> Vec2 {
        let m = &self.m;
        v(m[0] * d.x + m[1] * d.y, m[3] * d.x + m[4] * d.y)
    }

    pub fn det(self) -> f64 {
        let m = &self.m;
        m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6])
            + m[2] * (m[3] * m[7] - m[4] * m[6])
    }

    pub fn inverse(self) -> Mat3 {
        let m = &self.m;
        let det = self.det();
        let inv_det = 1.0 / det;
        Mat3 {
            m: [
                (m[4] * m[8] - m[5] * m[7]) * inv_det,
                (m[2] * m[7] - m[1] * m[8]) * inv_det,
                (m[1] * m[5] - m[2] * m[4]) * inv_det,
                (m[5] * m[6] - m[3] * m[8]) * inv_det,
                (m[0] * m[8] - m[2] * m[6]) * inv_det,
                (m[2] * m[3] - m[0] * m[5]) * inv_det,
                (m[3] * m[7] - m[4] * m[6]) * inv_det,
                (m[1] * m[6] - m[0] * m[7]) * inv_det,
                (m[0] * m[4] - m[1] * m[3]) * inv_det,
            ],
        }
    }

    pub fn is_invertible(self) -> bool {
        self.det().abs() > 1e-12
    }

    /// Uniform-ish scale factor of the linear part (sqrt of |det of linear part|).
    /// Used to convert local lengths to screen lengths for culling thresholds.
    pub fn linear_scale(self) -> f64 {
        let m = &self.m;
        (m[0] * m[4] - m[1] * m[3]).abs().sqrt()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    #[test]
    fn inverse_roundtrip() {
        let t = Mat3::translate(v(3.0, -2.0))
            .mul(Mat3::rotate(0.7))
            .mul(Mat3::scale(2.0, 0.5));
        let r = t.mul(t.inverse());
        for (i, e) in Mat3::IDENTITY.m.iter().enumerate() {
            assert!((r.m[i] - e).abs() < 1e-9, "{:?}", r);
        }
    }

    #[test]
    fn perp_right_is_inward_for_visual_ccw() {
        // y-down visual-CCW square: (0,0) (0,1) (1,1) (1,0).
        // Edge (0,0)->(0,1): interior (center (0.5,0.5)) lies along perp_right.
        let d = v(0.0, 1.0);
        let n = d.perp_right().normalized();
        assert!(n.dot(v(1.0, 0.0)) > 0.99);
    }

    // ------------------------------------------------------------------
    // ENGINE_INVARIANTS.md M5: Vec2::normalized()'s near-zero fallback is
    // THE FLICKER's documented root cause (geom.rs DEGENERATE_EDGE comment):
    // a zero-length polygon edge's "normal" came from this fallback, an
    // arbitrary (1,0), fabricating a phantom half-plane. Every caller in
    // geom.rs is now guarded by DEGENERATE_EDGE upstream of normalized(),
    // but the fallback itself, at the source, had zero direct test
    // coverage before this. Adversarial dimensions: exact zero, sub-
    // threshold-but-nonzero, and ordinary-magnitude vectors in every
    // quadrant/sign combination, plus huge magnitudes (no overflow-to-NaN).
    //
    // Verified fail-first: temporarily changed the fallback threshold
    // check from `l < 1e-12` to `l <= 0.0` (so a nonzero-but-tiny length
    // like 1e-15 falls through to `x/l, y/l`) and reran — this property
    // failed with a NaN/inf component (the exact class of corruption
    // DEGENERATE_EDGE exists to prevent one layer up), confirming this is
    // real instrumentation, not a tautology. Reverted before committing.
    proptest! {
        #[test]
        fn normalized_fallback_is_unit_and_never_nan(
            x in prop_oneof![
                -1e-13f64..1e-13,
                -1e6f64..1e6,
                Just(0.0f64),
            ],
            y in prop_oneof![
                -1e-13f64..1e-13,
                -1e6f64..1e6,
                Just(0.0f64),
            ],
        ) {
            let n = v(x, y).normalized();
            prop_assert!(n.x.is_finite() && n.y.is_finite(), "non-finite: {:?}", n);
            let len = n.len();
            let orig_len = v(x, y).len();
            if orig_len < 1e-12 {
                // Below-threshold input: must hit the defined fallback exactly.
                prop_assert!((n.x - 1.0).abs() < 1e-15 && n.y.abs() < 1e-15,
                    "fallback did not return (1,0): {:?}", n);
            } else {
                prop_assert!((len - 1.0).abs() < 1e-9, "not unit length: {:?} (len {})", n, len);
            }
        }
    }
}
