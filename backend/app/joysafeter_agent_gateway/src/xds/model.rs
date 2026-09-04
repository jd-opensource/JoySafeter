//! Stable types shared by xDS control-plane components.

use crate::ids::SandboxId;
use envoy_types::pb::google::protobuf::Any;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct DeliveryGeneration {
    pub policy_hash: String,
    pub policy_version: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ResourceType {
    Cluster,
    Listener,
}

impl ResourceType {
    pub const fn type_url(self) -> &'static str {
        match self {
            Self::Cluster => "type.googleapis.com/envoy.config.cluster.v3.Cluster",
            Self::Listener => "type.googleapis.com/envoy.config.listener.v3.Listener",
        }
    }

    pub(crate) const fn delivery_order(self) -> u8 {
        match self {
            Self::Cluster => 0,
            Self::Listener => 1,
        }
    }

    pub fn from_type_url(type_url: &str) -> Option<Self> {
        match type_url {
            "type.googleapis.com/envoy.config.cluster.v3.Cluster" => Some(Self::Cluster),
            "type.googleapis.com/envoy.config.listener.v3.Listener" => Some(Self::Listener),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ResourceOwner {
    Shared,
    Sandbox(SandboxId),
}

#[derive(Debug, Clone, PartialEq)]
pub struct ManagedXdsResource {
    pub name: String,
    pub resource_type: ResourceType,
    pub owner: ResourceOwner,
    /// Reference-counted so snapshots/reconciliation can clone the resource
    /// cheaply; the encoded protobuf body is only deep-copied when it is actually
    /// placed into an outbound Delta response for a node that can see it. (E2)
    pub payload: std::sync::Arc<Any>,
}
