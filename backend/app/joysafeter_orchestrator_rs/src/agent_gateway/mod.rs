//! Adapters for the independently deployed Agent Gateway management plane.

pub mod client;
pub mod grpc_client;
pub(crate) mod metrics;
pub mod network_policy;
pub mod placement;

pub use client::{AgentGatewayApi, AgentGatewayResponseError};
pub use grpc_client::{AgentGatewayGrpcClient, AgentGatewayGrpcClientConfig};
pub use network_policy::AgentGatewayNetworkPolicyRuntime;
pub use placement::AgentGatewayPlacementAuthority;
