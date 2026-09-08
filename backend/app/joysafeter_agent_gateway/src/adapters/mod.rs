//! Transport and infrastructure adapters around the application core.

pub mod health;
pub mod management_grpc;
pub(crate) mod proto_conversion;
pub mod replication_grpc;
pub mod server;
