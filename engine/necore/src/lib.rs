//! necore: the non-Euclidean engine core.
//!
//! A world is a graph of convex polygonal rooms connected edge-to-edge by
//! invertible affine transforms. There is no world space: every coordinate is
//! room-local and only portal transforms relate rooms. The crate owns the
//! math that never changes -- geometry, visibility, simulation, queries --
//! and emits events; deciding what any of it *means* belongs to the game
//! layer above.

pub mod geom;
pub mod math;
pub mod physics;
pub mod query;
pub mod visibility;
pub mod world;

pub use math::{v, Mat3, Vec2};
pub use physics::{Entity, Event, Sim};
pub use query::{raycast, rooms_within, RayHit, Router};
pub use visibility::{visible_set, Frustum, RoomInstance};
pub use world::{Portal, Room, RoomId, World, WorldError};
