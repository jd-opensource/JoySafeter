//! Adapters for the independently deployed Agent Gateway management plane.

pub mod client;
pub mod grpc_client;
pub mod network_policy;
pub mod placement;

pub use client::{
    AgentGatewayApi, AgentGatewayClient, AgentGatewayClientConfig, AgentGatewayRequestTimeout,
    AgentGatewayResponseError,
};
pub use grpc_client::AgentGatewayGrpcClient;
pub use network_policy::AgentGatewayNetworkPolicyRuntime;
pub use placement::AgentGatewayPlacementAuthority;
