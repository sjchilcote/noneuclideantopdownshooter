//! necore: the non-Euclidean engine core.
//!
//! A world is a graph of convex polygonal polygons connected edge-to-edge by
//! invertible affine transforms. There is no world space: every coordinate is
//! polygon-local and only portal transforms relate polygons. The crate owns the
//! math that never changes -- geometry, visibility, simulation, queries --
//! and emits events; deciding what any of it *means* belongs to the game
//! layer above.

pub mod frames;
pub mod geom;
pub mod math;
pub mod signals;
pub mod physics;
pub mod query;
pub mod raster;
pub mod soft;
pub mod visibility;
pub mod world;

pub use frames::{Coordinate, CoordinateSpace, FrameError, Offset, SpaceId, Step, Transform};
pub use math::{v, Mat3, Vec2};
pub use physics::{Entity, Event, Sim};
pub use query::{
    develop, polygons_within, raycast, reach, route, routes, terrain_avoid_dir,
    terrain_light_segments, transform_between, RayHit, Reached, Route, Router,
};
pub use raster::{Raster, RasterError};
pub use signals::SignalField as CoreSignalField;
pub use visibility::{visible_set, Frustum, PolygonInstance};
pub use world::{Portal, Polygon, PolygonId, World, WorldError};
