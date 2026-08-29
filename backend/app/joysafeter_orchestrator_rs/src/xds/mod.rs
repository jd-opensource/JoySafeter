//! In-process xDS control-plane subsystem.
//!
//! This package owns control-plane authentication, authority lifecycle,
//! transport, and the typed resource model. Durable desired/applied state stays
//! in PostgreSQL; sandbox modules remain rendering and provider adapters.

pub mod auth;
pub mod authority;
pub mod authority_worker;
pub mod control_plane;
pub mod delivery;
pub mod delta;
pub mod inventory;
pub mod leader;
pub mod metrics;
pub mod model;
pub mod node_ownership;
pub mod resource_store;
pub mod transport;
