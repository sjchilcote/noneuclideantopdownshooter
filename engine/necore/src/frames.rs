//! Coordinate spaces: the machinery that makes a frame mismatch LOUD.
//!
//! A pair of numbers is only meaningful in one coordinate space, and until
//! this module existed nothing in the code said which. So code could ask two
//! bodies for their positions, subtract, and receive a number that was
//! silently wrong because the two were in different chambers. That shipped:
//! gate 66 failed the Adversary's shove at p=0.04 because aim, the range gate
//! and the knockback direction all subtracted the shooter's frame from the
//! player's, and 63 of 64 filmed fires crossed a chamber.
//!
//! Three failures are targeted, no more (docs/FRAME_SYSTEM_DESIGN_20260729.md):
//!
//!   1. subtract two positions from different spaces and receive a number;
//!   2. transform along a legitimate route to the WRONG destination and use
//!      the result as though it were where the code assumed;
//!   3. be pushed into restricting work to one polygon because transforming
//!      properly is inconvenient.
//!
//! In all three the defect is SILENCE. A loud refusal is fine, which is why
//! everything here returns `Result` rather than guessing.
//!
//! WHY IDS ARE ALLOCATED AT RUNTIME. There is no intrinsic property of a
//! coordinate system to identify it by, and no sentinel value that recovers a
//! destination space from transported numbers — two portals A<->C, one the
//! identity and one a translation, send any sentinel to two different places
//! while both results are genuine C-coordinates. Detecting frame identity from
//! the numbers would need an invariant section (h.s == s for every holonomy),
//! which needs a common fixed point, which a pure translation does not have.
//! The proof is in docs/FRAME_ALGEBRA_NOTES_20260729.md. So identity is a
//! runtime integer, and a `Coordinate` carries the record of where it has been.
//!
//! WHY THE RECORD, AND NOT JUST THE TERMINAL SPACE. Two coordinates that share
//! no terminal space can still be compared when their records share an EARLIER
//! space: invert the right one back to the shared space and carry it forward
//! along the left one's steps. Doing that from the records alone is what keeps
//! a `Coordinate` independent of live topology — it can never be invalidated by
//! a carve or a seal, because it replays only matrices it already holds.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use crate::math::{Mat3, Vec2};

pub type SpaceId = u64;

/// Space ids are unique for the life of the process, not of a world: a
/// `Coordinate` does not know which world produced it, and tests build many
/// worlds at once. Never reused, so a stale id is a miss and never a
/// wrong-but-plausible hit.
static NEXT_SPACE_ID: AtomicU64 = AtomicU64::new(1);

/// id -> name, for MESSAGES ONLY.
///
/// A `Coordinate` carries space ids, not spaces, because a record of a dozen
/// hops should not carry a dozen strings. But an error that reads "space 41 and
/// space 58 share no coordinate space" costs the reader a grep, and this is a
/// system whose entire value is in its refusals being understood. So names live
/// here, written once when a space is created and read only when something is
/// being explained. Nothing about behaviour consults this.
static SPACE_NAMES: Mutex<Option<HashMap<SpaceId, String>>> = Mutex::new(None);

fn register_name(id: SpaceId, name: &str) {
    if let Ok(mut g) = SPACE_NAMES.lock() {
        g.get_or_insert_with(HashMap::new).insert(id, name.to_string());
    }
}

/// The name a space was created with, or a bare id when it is unknown (which
/// happens only if a lock was poisoned — a message, never a decision).
pub fn name_of(id: SpaceId) -> String {
    match SPACE_NAMES.lock() {
        Ok(g) => g
            .as_ref()
            .and_then(|m| m.get(&id))
            .cloned()
            .unwrap_or_else(|| format!("space {id}")),
        Err(_) => format!("space {id}"),
    }
}

/// A handle to an existing space, by id. For crossing a language boundary
/// where the id travelled but the name did not; it does NOT mint a space.
pub fn space_handle(id: SpaceId) -> CoordinateSpace {
    CoordinateSpace { id, name: name_of(id) }
}

/// Held as a component by anything that defines a space — today every polygon,
/// and the screen.
///
/// `id` is identity; comparison uses only it. `name` is for messages only and
/// is never load-bearing, so a duplicate name after a seal reuses a number is
/// cosmetic rather than a correctness problem.
#[derive(Debug, Clone)]
pub struct CoordinateSpace {
    id: SpaceId,
    name: String,
}

impl CoordinateSpace {
    pub fn new(name: impl Into<String>) -> CoordinateSpace {
        let id = NEXT_SPACE_ID.fetch_add(1, Ordering::Relaxed);
        let name = name.into();
        register_name(id, &name);
        CoordinateSpace { id, name }
    }

    pub fn id(&self) -> SpaceId {
        self.id
    }

    pub fn name(&self) -> &str {
        &self.name
    }
}

impl PartialEq for CoordinateSpace {
    fn eq(&self, other: &CoordinateSpace) -> bool {
        self.id == other.id
    }
}

impl Eq for CoordinateSpace {}

/// One step of a record: the space this step moved INTO, and the matrix that
/// moved it. The space it moved out of is the previous step's `into` (or the
/// record's origin, for the first step).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Step {
    pub into: SpaceId,
    pub xform: Mat3,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FrameError {
    /// A transform was applied to a coordinate that is not in its source space.
    /// A cheap backstop: the algebra check below catches the same error later,
    /// but later means further from the mistake.
    WrongSource {
        expected: SpaceId,
        found: SpaceId,
        transform: String,
    },
    /// Neither record mentions a space the other has been in, so there is no
    /// route between these two numbers that this coordinate can justify. The
    /// caller wanted an answer the world alone can give — `World::develop`.
    NoSharedSpace {
        left: SpaceId,
        right: SpaceId,
        left_chain: Vec<SpaceId>,
        right_chain: Vec<SpaceId>,
    },
    NotInvertible,
}

impl std::fmt::Display for FrameError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FrameError::WrongSource { expected, found, transform } => write!(
                f,
                "{transform} maps out of {}, but this value is in {}",
                name_of(*expected),
                name_of(*found)
            ),
            FrameError::NoSharedSpace { left, right, left_chain, right_chain } => write!(
                f,
                "{} and {} share no coordinate space: left has been through \
                 [{}], right through [{}]. These numbers are not comparable; \
                 ask the world to develop one into the other's space.",
                name_of(*left),
                name_of(*right),
                left_chain.iter().map(|s| name_of(*s)).collect::<Vec<_>>().join(" -> "),
                right_chain.iter().map(|s| name_of(*s)).collect::<Vec<_>>().join(" -> ")
            ),
            FrameError::NotInvertible => write!(f, "transform is not invertible"),
        }
    }
}

/// The chain of spaces a value has been in, oldest first. `chain[0]` is where
/// it started; `chain[n]` is where step `n-1` put it; the last is where it is.
fn chain(origin: SpaceId, record: &[Step]) -> Vec<SpaceId> {
    let mut out = Vec::with_capacity(record.len() + 1);
    out.push(origin);
    out.extend(record.iter().map(|s| s.into));
    out
}

fn terminal(origin: SpaceId, record: &[Step]) -> SpaceId {
    record.last().map(|s| s.into).unwrap_or(origin)
}

/// Find the shared space to reconcile through: the one that appears LATEST in
/// the left chain, and (among ties) latest in the right.
///
/// Which shared space is chosen genuinely matters — the groupoid of frames is
/// not thin, so two routes between the same pair of spaces can differ by a
/// holonomy, and reconciling through a different meeting point gives a
/// different (equally real) answer. Latest-in-left is the least
/// re-derivation: when both values already terminate in the same space it
/// picks that space and does no matrix work at all, which is the common case.
fn shared(left: &[SpaceId], right: &[SpaceId]) -> Option<(usize, usize)> {
    for (i, l) in left.iter().enumerate().rev() {
        if let Some(j) = right.iter().rposition(|r| r == l) {
            return Some((i, j));
        }
    }
    None
}

/// Move `value` (living at the end of the right chain) into the space at index
/// `i` of the left chain, via the shared space at index `j` of the right chain.
///
/// Backwards along the right record from its end down to `j` (inverses), then
/// forwards along the left record from `i` to its end. `point` selects the full
/// affine map (a place) or the linear part only (a difference): a difference
/// pushed through the full matrix collects a spurious translation.
fn transport(
    value: Vec2,
    left_record: &[Step],
    i: usize,
    right_record: &[Step],
    j: usize,
    point: bool,
) -> Vec2 {
    let mut p = value;
    for step in right_record[j..].iter().rev() {
        let inv = step.xform.inverse();
        p = if point { inv.apply(p) } else { inv.apply_dir(p) };
    }
    for step in &left_record[i..] {
        p = if point {
            step.xform.apply(p)
        } else {
            step.xform.apply_dir(p)
        };
    }
    p
}

/// A place. Carries its values, its space, and the record of every transform
/// applied to it.
///
/// Never consults the world: it replays only the matrices in its own record, so
/// it keeps meaning what it meant however the topology changes around it.
#[derive(Debug, Clone)]
pub struct Coordinate {
    pos: Vec2,
    origin: SpaceId,
    record: Vec<Step>,
}

/// A difference between two places. Belongs to a space but is not a place, so
/// it moves by the LINEAR part of a transform only — portals rotate and scale,
/// and a difference pushed through the full affine map collects the
/// translation twice.
#[derive(Debug, Clone)]
pub struct Offset {
    d: Vec2,
    origin: SpaceId,
    record: Vec<Step>,
}

/// A matrix plus the two spaces it maps between.
#[derive(Debug, Clone)]
pub struct Transform {
    pub from: SpaceId,
    pub to: SpaceId,
    pub m: Mat3,
    /// For error messages only ("portal 3:2", "camera").
    pub name: String,
}

impl Coordinate {
    /// Only the engine calls this. A coordinate is minted where the numbers
    /// come from — an entity's position, a vertex, a portal midpoint — and
    /// never assembled from a pair of floats by a caller who then has to be
    /// trusted about which space they are in.
    pub fn new(space: SpaceId, pos: Vec2) -> Coordinate {
        Coordinate { pos, origin: space, record: Vec::new() }
    }

    pub fn space(&self) -> SpaceId {
        terminal(self.origin, &self.record)
    }

    pub fn origin_space(&self) -> SpaceId {
        self.origin
    }

    pub fn chain(&self) -> Vec<SpaceId> {
        chain(self.origin, &self.record)
    }

    pub fn record(&self) -> &[Step] {
        &self.record
    }

    /// The raw pair, in this coordinate's own space. For handing to a channel
    /// that names the space alongside it (a sound, a decal, an engine call) —
    /// never for arithmetic against another coordinate, which is what the rest
    /// of this file exists to make unnecessary.
    pub fn local(&self) -> Vec2 {
        self.pos
    }

    /// An offset expressed in THIS place's space. The ergonomic path for AI
    /// that wants to say "five units along my own +x" without ever naming a
    /// space id.
    pub fn offset(&self, d: Vec2) -> Offset {
        Offset { d, origin: self.space(), record: Vec::new() }
    }

    /// `self - other`, in SELF's space. The right operand is the one that
    /// moves, per the reconciliation rule.
    pub fn sub(&self, other: &Coordinate) -> Result<Offset, FrameError> {
        let there = self.develop_other(other)?;
        Ok(Offset {
            d: self.pos - there,
            origin: self.space(),
            record: Vec::new(),
        })
    }

    pub fn add(&self, o: &Offset) -> Result<Coordinate, FrameError> {
        let d = o.in_space_of(self.space(), &self.chain(), &self.record)?;
        Ok(Coordinate {
            pos: self.pos + d,
            origin: self.space(),
            record: Vec::new(),
        })
    }

    /// Distance to another place, measured in SELF's space. Scaling portals
    /// make that a real choice rather than a formality: the same pair of
    /// bodies is genuinely further apart measured from one side than the
    /// other, and the observer's own space is the one whose ranges its own
    /// constants are written in.
    pub fn distance(&self, other: &Coordinate) -> Result<f64, FrameError> {
        Ok((self.pos - self.develop_other(other)?).len())
    }

    /// The other coordinate's values, expressed in this one's space.
    fn develop_other(&self, other: &Coordinate) -> Result<Vec2, FrameError> {
        let (lc, rc) = (self.chain(), other.chain());
        match shared(&lc, &rc) {
            Some((i, j)) => Ok(transport(other.pos, &self.record, i, &other.record, j, true)),
            None => Err(FrameError::NoSharedSpace {
                left: self.space(),
                right: other.space(),
                left_chain: lc,
                right_chain: rc,
            }),
        }
    }

    /// Extend by a whole route's steps at once. ENGINE ONLY: the steps come
    /// from a search that began in this coordinate's own space, so there is no
    /// source to validate against — which is exactly why this is not on the
    /// Python surface, where `Transform` and its source check are.
    pub fn extended(&self, steps: &[Step]) -> Coordinate {
        let mut pos = self.pos;
        for s in steps {
            pos = s.xform.apply(pos);
        }
        let mut record = self.record.clone();
        record.extend_from_slice(steps);
        Coordinate { pos, origin: self.origin, record }
    }

    /// Apply a transform, appending to the record. Refuses a transform whose
    /// source is not this coordinate's space.
    pub fn transformed(&self, t: &Transform) -> Result<Coordinate, FrameError> {
        if t.from != self.space() {
            return Err(FrameError::WrongSource {
                expected: t.from,
                found: self.space(),
                transform: t.name.clone(),
            });
        }
        let mut record = self.record.clone();
        record.push(Step { into: t.to, xform: t.m });
        Ok(Coordinate { pos: t.m.apply(self.pos), origin: self.origin, record })
    }
}

impl Offset {
    /// An offset in a named space. Legitimate for a caller who HAS a space —
    /// an AI deciding on a heading in its own frame — which is why this exists
    /// while `Coordinate::new` stays engine-only: a difference invented in
    /// your own frame is a decision, a place invented in your own frame is a
    /// claim about the world.
    pub fn new(space: SpaceId, d: Vec2) -> Offset {
        Offset { d, origin: space, record: Vec::new() }
    }

    pub fn space(&self) -> SpaceId {
        terminal(self.origin, &self.record)
    }

    pub fn chain(&self) -> Vec<SpaceId> {
        chain(self.origin, &self.record)
    }

    pub fn record(&self) -> &[Step] {
        &self.record
    }

    pub fn local(&self) -> Vec2 {
        self.d
    }

    pub fn len(&self) -> f64 {
        self.d.len()
    }

    pub fn is_empty(&self) -> bool {
        self.d.len2() == 0.0
    }

    /// Angle within this space. A scalar, so it carries no space of its own —
    /// meaningful only against other angles measured in the same space.
    pub fn angle(&self) -> f64 {
        self.d.y.atan2(self.d.x)
    }

    pub fn scaled(&self, k: f64) -> Offset {
        Offset { d: self.d * k, origin: self.origin, record: self.record.clone() }
    }

    pub fn normalized(&self) -> Offset {
        Offset {
            d: self.d.normalized(),
            origin: self.origin,
            record: self.record.clone(),
        }
    }

    /// Rotate within this space. Handedness is a property of the space, so
    /// this is only meaningful where it is applied — a mirror portal flips it,
    /// which is exactly why the rotation happens before any transport.
    pub fn rotated(&self, theta: f64) -> Offset {
        Offset {
            d: Mat3::rotate(theta).apply_dir(self.d),
            origin: self.origin,
            record: self.record.clone(),
        }
    }

    pub fn add(&self, o: &Offset) -> Result<Offset, FrameError> {
        let d = o.in_space_of(self.space(), &self.chain(), &self.record)?;
        Ok(Offset { d: self.d + d, origin: self.space(), record: Vec::new() })
    }

    pub fn sub(&self, o: &Offset) -> Result<Offset, FrameError> {
        let d = o.in_space_of(self.space(), &self.chain(), &self.record)?;
        Ok(Offset { d: self.d - d, origin: self.space(), record: Vec::new() })
    }

    pub fn dot(&self, o: &Offset) -> Result<f64, FrameError> {
        let d = o.in_space_of(self.space(), &self.chain(), &self.record)?;
        Ok(self.d.dot(d))
    }

    pub fn cross(&self, o: &Offset) -> Result<f64, FrameError> {
        let d = o.in_space_of(self.space(), &self.chain(), &self.record)?;
        Ok(self.d.cross(d))
    }

    /// This offset's values in the space the left operand terminates in.
    fn in_space_of(
        &self,
        left_space: SpaceId,
        left_chain: &[SpaceId],
        left_record: &[Step],
    ) -> Result<Vec2, FrameError> {
        let rc = self.chain();
        match shared(left_chain, &rc) {
            Some((i, j)) => Ok(transport(self.d, left_record, i, &self.record, j, false)),
            None => Err(FrameError::NoSharedSpace {
                left: left_space,
                right: self.space(),
                left_chain: left_chain.to_vec(),
                right_chain: rc,
            }),
        }
    }

    /// Extend by a whole route's steps at once, linear part only. ENGINE
    /// ONLY, for the same reason as `Coordinate::extended`.
    pub fn extended(&self, steps: &[Step]) -> Offset {
        let mut d = self.d;
        for s in steps {
            d = s.xform.apply_dir(d);
        }
        let mut record = self.record.clone();
        record.extend_from_slice(steps);
        Offset { d, origin: self.origin, record }
    }

    pub fn transformed(&self, t: &Transform) -> Result<Offset, FrameError> {
        if t.from != self.space() {
            return Err(FrameError::WrongSource {
                expected: t.from,
                found: self.space(),
                transform: t.name.clone(),
            });
        }
        let mut record = self.record.clone();
        record.push(Step { into: t.to, xform: t.m });
        Ok(Offset { d: t.m.apply_dir(self.d), origin: self.origin, record })
    }
}

impl Transform {
    pub fn new(from: SpaceId, to: SpaceId, m: Mat3, name: impl Into<String>) -> Result<Transform, FrameError> {
        if !m.is_invertible() {
            return Err(FrameError::NotInvertible);
        }
        Ok(Transform { from, to, m, name: name.into() })
    }

    pub fn inverse(&self) -> Transform {
        Transform {
            from: self.to,
            to: self.from,
            m: self.m.inverse(),
            name: format!("{} (inverse)", self.name),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::math::v;

    fn spaces(n: usize) -> Vec<CoordinateSpace> {
        (0..n).map(|i| CoordinateSpace::new(format!("S{i}"))).collect()
    }

    #[test]
    fn ids_are_unique_and_never_reused() {
        let a = CoordinateSpace::new("Polygon 1");
        let b = CoordinateSpace::new("Polygon 1"); // same NAME on purpose
        assert_ne!(a.id(), b.id(), "name is cosmetic; id is identity");
        assert_ne!(a, b);
        drop(a);
        let c = CoordinateSpace::new("Polygon 1");
        assert_ne!(b.id(), c.id());
    }

    #[test]
    fn same_space_arithmetic_is_the_torsor() {
        let s = spaces(1);
        let a = Coordinate::new(s[0].id(), v(10.0, 4.0));
        let b = Coordinate::new(s[0].id(), v(4.0, 4.0));
        let d = a.sub(&b).unwrap();
        assert_eq!(d.local(), v(6.0, 0.0));
        assert_eq!(d.space(), s[0].id());
        // Coordinate + Offset -> Coordinate; there is no Coordinate +
        // Coordinate to test, which is the point of the split.
        let c = b.add(&d).unwrap();
        assert_eq!(c.local(), a.local());
        assert!((a.distance(&b).unwrap() - 6.0).abs() < 1e-12);
    }

    #[test]
    fn two_fresh_coordinates_in_different_spaces_refuse() {
        let s = spaces(2);
        let a = Coordinate::new(s[0].id(), v(10.0, 0.0));
        let b = Coordinate::new(s[1].id(), v(4.0, 0.0));
        // THE gate-66 shape: two positions straight from the engine, in
        // different chambers, subtracted.
        let err = a.sub(&b).unwrap_err();
        match err {
            FrameError::NoSharedSpace { left, right, .. } => {
                assert_eq!(left, s[0].id());
                assert_eq!(right, s[1].id());
            }
            other => panic!("expected NoSharedSpace, got {other:?}"),
        }
        assert!(a.distance(&b).is_err());
    }

    #[test]
    fn a_transported_coordinate_meets_a_local_one() {
        let s = spaces(2);
        let t = Transform::new(s[1].id(), s[0].id(), Mat3::translate(v(100.0, 0.0)), "portal")
            .unwrap();
        let far = Coordinate::new(s[1].id(), v(5.0, 0.0)).transformed(&t).unwrap();
        assert_eq!(far.space(), s[0].id());
        assert_eq!(far.local(), v(105.0, 0.0));
        let here = Coordinate::new(s[0].id(), v(5.0, 0.0));
        assert!((here.distance(&far).unwrap() - 100.0).abs() < 1e-9);
    }

    #[test]
    fn a_transform_refuses_a_value_from_the_wrong_space() {
        let s = spaces(3);
        let t = Transform::new(s[1].id(), s[0].id(), Mat3::translate(v(1.0, 0.0)), "portal 1")
            .unwrap();
        let wrong = Coordinate::new(s[2].id(), v(0.0, 0.0));
        match wrong.transformed(&t).unwrap_err() {
            FrameError::WrongSource { expected, found, .. } => {
                assert_eq!(expected, s[1].id());
                assert_eq!(found, s[2].id());
            }
            other => panic!("expected WrongSource, got {other:?}"),
        }
    }

    #[test]
    fn reconciliation_through_a_shared_earlier_space() {
        // A -> B and A -> C. Neither terminates where the other does, but
        // both remember A, so they are comparable without asking the world.
        let s = spaces(3);
        let ab = Transform::new(s[0].id(), s[1].id(), Mat3::translate(v(10.0, 0.0)), "A->B").unwrap();
        let ac = Transform::new(s[0].id(), s[2].id(), Mat3::translate(v(0.0, 7.0)), "A->C").unwrap();
        let in_b = Coordinate::new(s[0].id(), v(1.0, 1.0)).transformed(&ab).unwrap();
        let in_c = Coordinate::new(s[0].id(), v(4.0, 1.0)).transformed(&ac).unwrap();
        assert_eq!(in_b.space(), s[1].id());
        assert_eq!(in_c.space(), s[2].id());
        // in_b - in_c, answered in B: (1,1) - (4,1) = (-3,0), then B's
        // translation is linear-part-free so the difference is unchanged.
        let d = in_b.sub(&in_c).unwrap();
        assert_eq!(d.space(), s[1].id());
        assert!((d.local() - v(-3.0, 0.0)).len() < 1e-9, "{:?}", d.local());
    }

    #[test]
    fn an_offset_moves_by_the_linear_part_only() {
        // A rotation-plus-translation portal. The place moves by both; the
        // difference moves by the rotation alone, or it collects the
        // translation a second time.
        let s = spaces(2);
        let m = Mat3::translate(v(1000.0, -500.0)).mul(Mat3::rotate(std::f64::consts::FRAC_PI_2));
        let t = Transform::new(s[0].id(), s[1].id(), m, "portal").unwrap();
        let o = Offset::new(s[0].id(), v(3.0, 0.0)).transformed(&t).unwrap();
        // rotate (3,0) by +90deg (y-down convention) -> (0,3); no translation.
        assert!((o.local() - v(0.0, 3.0)).len() < 1e-9, "{:?}", o.local());
        assert!((o.len() - 3.0).abs() < 1e-9, "length must survive a rigid portal");
        // The same difference derived by subtracting two transported places
        // must agree — that equality is the whole reason for the split.
        let p0 = Coordinate::new(s[0].id(), v(1.0, 1.0)).transformed(&t).unwrap();
        let p1 = Coordinate::new(s[0].id(), v(4.0, 1.0)).transformed(&t).unwrap();
        let d = p1.sub(&p0).unwrap();
        assert!((d.local() - o.local()).len() < 1e-9, "{:?} vs {:?}", d.local(), o.local());
    }

    #[test]
    fn a_scaling_portal_scales_a_difference() {
        let s = spaces(2);
        let t = Transform::new(s[0].id(), s[1].id(), Mat3::scale(2.0, 2.0), "wide portal").unwrap();
        let o = Offset::new(s[0].id(), v(3.0, 4.0));
        assert!((o.len() - 5.0).abs() < 1e-12);
        // A length is a scalar and a scalar has no space: the SAME separation
        // measures 5 on one side of this portal and 10 on the other, and
        // there is no fact of the matter about which is "the" distance.
        assert!((o.transformed(&t).unwrap().len() - 10.0).abs() < 1e-12);
    }

    #[test]
    fn the_groupoid_is_not_thin_and_the_algebra_shows_it() {
        // Two DIFFERENT routes from A to C: one via B (identity legs), one
        // direct but translating. Both land genuinely in C. Subtracting the
        // same original place developed both ways must NOT be zero — that
        // difference IS the holonomy, and a system that pretended the two
        // agreed would be lying.
        let s = spaces(3);
        let ab = Transform::new(s[0].id(), s[1].id(), Mat3::IDENTITY, "A->B").unwrap();
        let bc = Transform::new(s[1].id(), s[2].id(), Mat3::IDENTITY, "B->C").unwrap();
        let ac = Transform::new(s[0].id(), s[2].id(), Mat3::translate(v(100.0, 0.0)), "A->C").unwrap();
        let start = Coordinate::new(s[0].id(), v(0.0, 0.0));
        let via_b = start.transformed(&ab).unwrap().transformed(&bc).unwrap();
        let direct = start.transformed(&ac).unwrap();
        assert_eq!(via_b.space(), direct.space(), "both are in C");
        let d = via_b.sub(&direct).unwrap();
        assert!(
            (d.local() - v(-100.0, 0.0)).len() < 1e-9,
            "holonomy must be reported, not smoothed away: {:?}",
            d.local()
        );
    }

    #[test]
    fn the_deepest_shared_space_is_the_meeting_point() {
        // Same terminal space => no matrix work at all, even though an
        // earlier space is also shared. Checked by giving the earlier leg a
        // translation that would show up if it were used.
        let s = spaces(2);
        let ab = Transform::new(s[0].id(), s[1].id(), Mat3::translate(v(9.0, 0.0)), "A->B").unwrap();
        let x = Coordinate::new(s[0].id(), v(1.0, 0.0)).transformed(&ab).unwrap();
        let y = Coordinate::new(s[0].id(), v(4.0, 0.0)).transformed(&ab).unwrap();
        let d = x.sub(&y).unwrap();
        assert_eq!(d.space(), s[1].id());
        assert!((d.local() - v(-3.0, 0.0)).len() < 1e-12);
    }

    #[test]
    fn a_record_survives_topology_it_knows_nothing_about() {
        // The design's explicit non-goal: a transform derived across a link
        // that no longer exists still passes. Nothing here consults a world,
        // so there is no way for it not to.
        let s = spaces(2);
        let t = Transform::new(s[1].id(), s[0].id(), Mat3::translate(v(50.0, 0.0)), "sealed door")
            .unwrap();
        let far = Coordinate::new(s[1].id(), v(0.0, 0.0)).transformed(&t).unwrap();
        let here = Coordinate::new(s[0].id(), v(0.0, 0.0));
        assert!((here.distance(&far).unwrap() - 50.0).abs() < 1e-12);
    }

    #[test]
    fn a_mirror_portal_round_trips() {
        let s = spaces(2);
        let m = Mat3 { m: [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0] };
        let t = Transform::new(s[0].id(), s[1].id(), m, "mirror").unwrap();
        let p = Coordinate::new(s[0].id(), v(3.0, 5.0));
        let there = p.transformed(&t).unwrap();
        assert_eq!(there.local(), v(-3.0, 5.0));
        let back = there.transformed(&t.inverse()).unwrap();
        assert_eq!(back.space(), s[0].id());
        assert!((back.local() - p.local()).len() < 1e-12);
        // and the round trip is comparable to where it started
        assert!(p.distance(&back).unwrap() < 1e-12);
    }

    #[test]
    fn offsets_refuse_across_unrelated_spaces() {
        let s = spaces(2);
        let a = Offset::new(s[0].id(), v(1.0, 0.0));
        let b = Offset::new(s[1].id(), v(0.0, 1.0));
        assert!(a.add(&b).is_err());
        assert!(a.dot(&b).is_err());
        let p = Coordinate::new(s[0].id(), v(0.0, 0.0));
        assert!(p.add(&b).is_err());
    }

    #[test]
    fn coord_offset_is_the_ergonomic_same_space_path() {
        let s = spaces(1);
        let p = Coordinate::new(s[0].id(), v(10.0, 10.0));
        let q = p.add(&p.offset(v(0.0, -4.0))).unwrap();
        assert_eq!(q.local(), v(10.0, 6.0));
        assert!((p.distance(&q).unwrap() - 4.0).abs() < 1e-12);
    }
}
