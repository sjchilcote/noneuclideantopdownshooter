//! The Python surface of coordinate spaces.
//!
//! What crosses this boundary decides what the game can express. Two rules
//! shape everything below:
//!
//! 1. **Python cannot build a Coordinate from numbers.** There is no `#[new]`
//!    on `Coordinate`, so a place can only come from somewhere that knows which
//!    space it is in — an entity, a doorway, a sighting. A caller who could
//!    write `Coordinate(space, x, y)` would be trusted about the space, and
//!    that trust is exactly what gate 66 spent.
//! 2. **An Offset can be built freely.** A difference invented in your own
//!    frame is a decision ("five units along my own +x"); a place invented in
//!    your own frame is a claim about the world.
//!
//! Mismatches raise `necore.FrameMismatch`, a ValueError subclass — loud, and
//! catchable by anything that genuinely wants to handle "not comparable".

use pyo3::create_exception;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use necore_core::frames as core;
use necore_core::{v, Mat3, Vec2};

create_exception!(
    necore,
    FrameMismatch,
    PyValueError,
    "Two values were combined across coordinate spaces that share no route."
);

pub type M9 = (f64, f64, f64, f64, f64, f64, f64, f64, f64);

pub fn frame_err(e: core::FrameError) -> PyErr {
    FrameMismatch::new_err(e.to_string())
}

fn mat_from_tuple(m: M9) -> Mat3 {
    Mat3 { m: [m.0, m.1, m.2, m.3, m.4, m.5, m.6, m.7, m.8] }
}

fn mat_to_tuple(m: Mat3) -> M9 {
    let a = m.m;
    (a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8])
}

/// A coordinate space's identity. Constructing one MINTS a new space — the
/// renderer's `Space("Screenspace")` is a real, distinct space, and calling it
/// twice gives two spaces, because that is what happened.
#[pyclass(frozen, name = "Space")]
#[derive(Clone)]
pub struct PySpace {
    pub inner: core::CoordinateSpace,
}

impl PySpace {
    pub fn of(inner: core::CoordinateSpace) -> PySpace {
        PySpace { inner }
    }
}

#[pymethods]
impl PySpace {
    #[new]
    fn new(name: &str) -> PySpace {
        PySpace { inner: core::CoordinateSpace::new(name) }
    }

    #[getter]
    fn id(&self) -> u64 {
        self.inner.id()
    }

    #[getter]
    fn name(&self) -> &str {
        self.inner.name()
    }

    fn __eq__(&self, other: &PySpace) -> bool {
        self.inner.id() == other.inner.id()
    }

    fn __hash__(&self) -> u64 {
        self.inner.id()
    }

    /// The place in THIS space at (x, y).
    ///
    /// The other door for numbers whose space is known but which no engine
    /// query produced — screen-space input, chiefly: a mouse point arrives from
    /// the OS in screen coordinates and something has to say so before it can
    /// meet anything else.
    ///
    /// Note precisely what is still impossible. A place cannot be built without
    /// naming its space IN THE SAME EXPRESSION, which is the invariant that
    /// matters: the gate-66 defect was numbers whose space was never stated
    /// anywhere, not numbers whose space is stated out loud and then checked by
    /// the algebra.
    fn place(&self, x: f64, y: f64) -> PyCoordinate {
        PyCoordinate { inner: core::Coordinate::new(self.inner.id(), v(x, y)) }
    }

    fn __repr__(&self) -> String {
        format!("Space({:?}, id={})", self.inner.name(), self.inner.id())
    }
}

/// A place: values, the space they are in, and the record of how they got
/// there.
#[pyclass(frozen, name = "Coordinate")]
#[derive(Clone)]
pub struct PyCoordinate {
    pub inner: core::Coordinate,
}

impl PyCoordinate {
    pub fn of(inner: core::Coordinate) -> PyCoordinate {
        PyCoordinate { inner }
    }
}

#[pymethods]
impl PyCoordinate {
    /// The space this place is in NOW (the end of its record).
    #[getter]
    fn space(&self) -> PySpace {
        PySpace { inner: core::space_handle(self.inner.space()) }
    }

    /// Every space this place has been in, oldest first. Diagnostic: it is
    /// what a refusal prints, and what tells you which route a value took.
    #[getter]
    fn chain(&self) -> Vec<PySpace> {
        self.inner
            .chain()
            .into_iter()
            .map(|s| PySpace { inner: core::space_handle(s) })
            .collect()
    }

    /// The raw pair, in this place's own space.
    ///
    /// For handing to a channel that names the space alongside it — a sound at
    /// (polygon, x, y), a decal, an engine call. NEVER for arithmetic against
    /// another coordinate: `a.local()[0] - b.local()[0]` is the bug this whole
    /// module exists to stop, and writing it that way at least makes it a
    /// deliberate act instead of a silent one.
    fn local(&self) -> (f64, f64) {
        let p = self.inner.local();
        (p.x, p.y)
    }

    /// An offset expressed in THIS place's space — the path for AI that wants
    /// to say "five units along my own +x" without naming a space at all.
    fn offset(&self, dx: f64, dy: f64) -> PyOffset {
        PyOffset { inner: self.inner.offset(v(dx, dy)) }
    }

    /// `self - other` -> Offset, in SELF's space. Raises when the two records
    /// share no space.
    fn __sub__(&self, other: &PyCoordinate) -> PyResult<PyOffset> {
        self.inner
            .sub(&other.inner)
            .map(|o| PyOffset { inner: o })
            .map_err(frame_err)
    }

    fn __add__(&self, o: &PyOffset) -> PyResult<PyCoordinate> {
        self.inner
            .add(&o.inner)
            .map(|c| PyCoordinate { inner: c })
            .map_err(frame_err)
    }

    /// Distance, measured in SELF's space. Under a scaling portal that is a
    /// real choice and not a formality: the same pair of bodies is genuinely
    /// further apart measured from one side than from the other, and an
    /// observer's own space is the one its own range constants were written in.
    fn distance_to(&self, other: &PyCoordinate) -> PyResult<f64> {
        self.inner.distance(&other.inner).map_err(frame_err)
    }

    /// The offset FROM self TO other — the heading a chaser wants, in self's
    /// space. Exactly `other - self`, named for the direction it points,
    /// because the reversed subtraction is the second-easiest frame mistake to
    /// make after the cross-frame one.
    fn toward(&self, other: &PyCoordinate) -> PyResult<PyOffset> {
        other
            .inner
            .sub(&self.inner)
            .map(|o| PyOffset { inner: o })
            .map_err(frame_err)
    }

    fn transformed(&self, t: &PyTransform) -> PyResult<PyCoordinate> {
        self.inner
            .transformed(&t.inner)
            .map(|c| PyCoordinate { inner: c })
            .map_err(frame_err)
    }

    fn __repr__(&self) -> String {
        let p = self.inner.local();
        format!(
            "Coordinate({:.2}, {:.2} in {} via {} hop{})",
            p.x,
            p.y,
            core::name_of(self.inner.space()),
            self.inner.record().len(),
            if self.inner.record().len() == 1 { "" } else { "s" }
        )
    }
}

/// A difference. Belongs to a space but is not a place, so it moves by the
/// linear part of a transform only.
#[pyclass(frozen, name = "Offset")]
#[derive(Clone)]
pub struct PyOffset {
    pub inner: core::Offset,
}

impl PyOffset {
    pub fn of(inner: core::Offset) -> PyOffset {
        PyOffset { inner }
    }
}

#[pymethods]
impl PyOffset {
    #[new]
    fn new(space: &PySpace, dx: f64, dy: f64) -> PyOffset {
        PyOffset { inner: core::Offset::new(space.inner.id(), v(dx, dy)) }
    }

    #[getter]
    fn space(&self) -> PySpace {
        PySpace { inner: core::space_handle(self.inner.space()) }
    }

    fn local(&self) -> (f64, f64) {
        let d = self.inner.local();
        (d.x, d.y)
    }

    /// Length. A scalar, so it has no space of its own: a threshold written in
    /// one space is not comparable with a length measured in another, which is
    /// live wherever a portal scales.
    #[getter]
    fn length(&self) -> f64 {
        self.inner.len()
    }

    /// Angle within this space, radians. Same caveat as length.
    #[getter]
    fn angle(&self) -> f64 {
        self.inner.angle()
    }

    fn normalized(&self) -> PyOffset {
        PyOffset { inner: self.inner.normalized() }
    }

    /// Rotate within this space. Handedness belongs to the space, so a mirror
    /// portal flips it — which is why this happens before any transport.
    fn rotated(&self, theta: f64) -> PyOffset {
        PyOffset { inner: self.inner.rotated(theta) }
    }

    fn dot(&self, o: &PyOffset) -> PyResult<f64> {
        self.inner.dot(&o.inner).map_err(frame_err)
    }

    fn cross(&self, o: &PyOffset) -> PyResult<f64> {
        self.inner.cross(&o.inner).map_err(frame_err)
    }

    fn __add__(&self, o: &PyOffset) -> PyResult<PyOffset> {
        self.inner.add(&o.inner).map(PyOffset::of).map_err(frame_err)
    }

    fn __sub__(&self, o: &PyOffset) -> PyResult<PyOffset> {
        self.inner.sub(&o.inner).map(PyOffset::of).map_err(frame_err)
    }

    fn __mul__(&self, k: f64) -> PyOffset {
        PyOffset { inner: self.inner.scaled(k) }
    }

    fn __rmul__(&self, k: f64) -> PyOffset {
        PyOffset { inner: self.inner.scaled(k) }
    }

    fn __truediv__(&self, k: f64) -> PyResult<PyOffset> {
        if k == 0.0 {
            return Err(PyValueError::new_err("cannot divide an offset by zero"));
        }
        Ok(PyOffset { inner: self.inner.scaled(1.0 / k) })
    }

    fn __neg__(&self) -> PyOffset {
        PyOffset { inner: self.inner.scaled(-1.0) }
    }

    fn __bool__(&self) -> bool {
        !self.inner.is_empty()
    }

    fn transformed(&self, t: &PyTransform) -> PyResult<PyOffset> {
        self.inner.transformed(&t.inner).map(PyOffset::of).map_err(frame_err)
    }

    fn __repr__(&self) -> String {
        let d = self.inner.local();
        format!(
            "Offset({:.2}, {:.2} in {})",
            d.x,
            d.y,
            core::name_of(self.inner.space())
        )
    }
}

/// A matrix plus the two spaces it maps between. Applying it to a value whose
/// space is not its source raises rather than producing a plausible number.
#[pyclass(frozen, name = "Transform")]
#[derive(Clone)]
pub struct PyTransform {
    pub inner: core::Transform,
}

impl PyTransform {
    pub fn of(inner: core::Transform) -> PyTransform {
        PyTransform { inner }
    }
}

#[pymethods]
impl PyTransform {
    #[new]
    #[pyo3(signature = (from_space, to_space, m9, name = "transform"))]
    fn new(from_space: &PySpace, to_space: &PySpace, m9: M9, name: &str) -> PyResult<PyTransform> {
        core::Transform::new(from_space.inner.id(), to_space.inner.id(), mat_from_tuple(m9), name)
            .map(PyTransform::of)
            .map_err(frame_err)
    }

    #[getter]
    fn from_space(&self) -> PySpace {
        PySpace { inner: core::space_handle(self.inner.from) }
    }

    #[getter]
    fn to_space(&self) -> PySpace {
        PySpace { inner: core::space_handle(self.inner.to) }
    }

    #[getter]
    fn m9(&self) -> M9 {
        mat_to_tuple(self.inner.m)
    }

    fn inverse(&self) -> PyTransform {
        PyTransform { inner: self.inner.inverse() }
    }

    fn __repr__(&self) -> String {
        format!(
            "Transform({:?}: {} -> {})",
            self.inner.name,
            core::name_of(self.inner.from),
            core::name_of(self.inner.to)
        )
    }
}

/// One entity's state, read at one instant.
///
/// Replaces the seven-float tuple `sim.get` used to return. The tuple was
/// unpacked at 28 sites as `_, ex, ey, *_ =`, and every one of those floats
/// was a number with no space attached — which is how a shooter's coordinates
/// came to be subtracted from a player's. The fields here allocate only when
/// asked, so reading `.polygon` costs nothing.
#[pyclass(frozen, name = "EntityState")]
pub struct PyEntityState {
    pub polygon: usize,
    pub space: core::SpaceId,
    pub pos: Vec2,
    pub vel: Vec2,
    pub dir: Vec2,
    pub radius: f64,
}

#[pymethods]
impl PyEntityState {
    /// Which polygon the body is physically in. An index, not a coordinate:
    /// comparing two of these is a topology question and always meaningful.
    #[getter]
    fn polygon(&self) -> usize {
        self.polygon
    }

    /// The space that polygon's coordinates live in.
    #[getter]
    fn space(&self) -> PySpace {
        PySpace { inner: core::space_handle(self.space) }
    }

    #[getter]
    fn pos(&self) -> PyCoordinate {
        PyCoordinate { inner: core::Coordinate::new(self.space, self.pos) }
    }

    #[getter]
    fn vel(&self) -> PyOffset {
        PyOffset { inner: core::Offset::new(self.space, self.vel) }
    }

    /// Facing. A unit offset, because a facing is a direction and directions
    /// move by the linear part of a portal transform.
    #[getter]
    fn dir(&self) -> PyOffset {
        PyOffset { inner: core::Offset::new(self.space, self.dir) }
    }

    /// Body radius: a length, and lengths have no space (see Offset.length).
    #[getter]
    fn radius(&self) -> f64 {
        self.radius
    }

    /// Speed — the length of the velocity, same caveat.
    #[getter]
    fn speed(&self) -> f64 {
        self.vel.len()
    }

    fn __repr__(&self) -> String {
        format!(
            "EntityState(polygon={}, pos=({:.1}, {:.1}) in {})",
            self.polygon,
            self.pos.x,
            self.pos.y,
            core::name_of(self.space)
        )
    }
}

/// What a ray found.
///
/// `pos` is in the HIT polygon's space, which is what a caller who wants to
/// carve that wall or decal that floor needs; `to_origin` carries it back to
/// the space the ray was fired from, which is what a caller who wants to aim
/// needs. Both are available and neither is implied, because the old 8-tuple
/// handed back two floats and a bare matrix and left the reader to guess which
/// of the two frames they were in.
#[pyclass(frozen, name = "RayResult")]
pub struct PyRayResult {
    pub kind: String,
    pub entity_id: Option<u64>,
    pub polygon: usize,
    pub edge: Option<usize>,
    pub pos: core::Coordinate,
    pub to_origin: core::Transform,
    pub distance: f64,
    pub hops: usize,
}

#[pymethods]
impl PyRayResult {
    /// "wall", "ent" or "none".
    #[getter]
    fn kind(&self) -> &str {
        &self.kind
    }

    /// The body struck, or None for a wall/nothing.
    #[getter]
    fn entity_id(&self) -> Option<u64> {
        self.entity_id
    }

    /// The polygon the ray ended in.
    #[getter]
    fn polygon(&self) -> usize {
        self.polygon
    }

    /// The wall edge struck, or None.
    #[getter]
    fn edge(&self) -> Option<usize> {
        self.edge
    }

    /// Where it ended, in the HIT polygon's space.
    #[getter]
    fn pos(&self) -> PyCoordinate {
        PyCoordinate { inner: self.pos.clone() }
    }

    /// Hit space -> the space the ray was fired from.
    #[getter]
    fn to_origin(&self) -> PyTransform {
        PyTransform { inner: self.to_origin.clone() }
    }

    /// Distance travelled, accumulated in each leg's own metric.
    #[getter]
    fn distance(&self) -> f64 {
        self.distance
    }

    #[getter]
    fn hops(&self) -> usize {
        self.hops
    }

    fn __repr__(&self) -> String {
        format!(
            "RayResult({} in polygon {} at {:.0}u, {} hops)",
            self.kind, self.polygon, self.distance, self.hops
        )
    }
}

/// A report of a sighting: what perception hands back.
///
/// Not a proxy for an entity — a record ABOUT one. The developed coordinate
/// cannot come from the entity, because the entity does not know who is asking
/// or by what route; one entity yields many Tracks when it is visible by more
/// than one route; and the relational facts (distance, depth) are properties of
/// the observer-subject pair with no home on the subject.
///
/// `tick` is not decoration. Every value here was computed at one instant, and
/// an old answer read as current is the same silent-wrongness shape as a frame
/// mismatch, in time rather than space.
#[pyclass(frozen, name = "Track")]
pub struct PyTrack {
    pub entity_id: u64,
    pub polygon: usize,
    pub pos: core::Coordinate,
    /// The subject's velocity, carried along the SAME route as `pos`.
    ///
    /// Not decoration and not a convenience: anything that leads a moving
    /// target needs the target's velocity in the SHOOTER's space, and the only
    /// way to get it right is to transport it along the route the sighting
    /// itself took. Developing the position and a one-second-ahead point
    /// through two independently-chosen routes gives an answer polluted by the
    /// holonomy between them — real, but not the velocity of anything.
    pub vel: core::Offset,
    /// The subject's FACING, carried along the same route.
    ///
    /// Same reason as `vel`, and it retires a punt: the shrieker's mark used
    /// the player's raw facing to aim at the ground behind him, and had an
    /// explicit "a rotated frame: just close in" branch that gave up whenever
    /// the shot crossed a doorway. A facing transported along the sighting's
    /// own route works at any depth, so there is nothing to give up on.
    pub dir: core::Offset,
    /// Physical path length along the route taken, in the legs' own metrics.
    pub path_distance: f64,
    /// Straight-line distance in the OBSERVER's space, which is what a range
    /// constant written for that observer means.
    pub distance: f64,
    pub portal_depth: usize,
    pub tick: i64,
}

#[pymethods]
impl PyTrack {
    #[getter]
    fn entity_id(&self) -> u64 {
        self.entity_id
    }

    /// The polygon the body was in when it was seen.
    #[getter]
    fn polygon(&self) -> usize {
        self.polygon
    }

    /// Where it was, in the space the observer asked for.
    #[getter]
    fn pos(&self) -> PyCoordinate {
        PyCoordinate { inner: self.pos.clone() }
    }

    /// How fast it was going, in the space the observer asked for.
    #[getter]
    fn vel(&self) -> PyOffset {
        PyOffset { inner: self.vel.clone() }
    }

    /// Which way it was facing, in the space the observer asked for.
    #[getter]
    fn dir(&self) -> PyOffset {
        PyOffset { inner: self.dir.clone() }
    }

    #[getter]
    fn path_distance(&self) -> f64 {
        self.path_distance
    }

    #[getter]
    fn distance(&self) -> f64 {
        self.distance
    }

    #[getter]
    fn portal_depth(&self) -> usize {
        self.portal_depth
    }

    /// The tick this sighting was taken. Compare it with the current tick
    /// before acting on anything else here.
    #[getter]
    fn tick(&self) -> i64 {
        self.tick
    }

    fn __repr__(&self) -> String {
        format!(
            "Track(entity {}, {:.0}u away, depth {}, tick {})",
            self.entity_id, self.distance, self.portal_depth, self.tick
        )
    }
}
