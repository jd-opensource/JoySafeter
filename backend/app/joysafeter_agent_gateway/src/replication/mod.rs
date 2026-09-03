//! In-memory replication for hot-standby Gateway replicas.
//!
//! Direct-xDS mode deliberately includes credential material so a follower can
//! promote without a resolver round trip. Replication transport and logs must
//! therefore be treated as sensitive; model Debug implementations redact it.

pub mod coordinator;
pub mod digest;
pub mod follower;
pub mod model;
pub mod projector;
mod snapshot;

pub use coordinator::{ReplicationCoordinator, ReplicationError};
pub use follower::FollowerHandle;
pub use projector::ReplicaProjector;
