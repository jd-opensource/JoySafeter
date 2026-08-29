use std::collections::BTreeSet;
use std::fmt;
use std::str::FromStr;

use crate::ids::SandboxId;

#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct NodeId(String);

impl NodeId {
    pub fn new(value: impl Into<String>) -> Result<Self, InvalidNodeId> {
        let value = value.into();
        let trimmed = value.trim();
        if trimmed.is_empty() || trimmed.len() > 253 {
            return Err(InvalidNodeId);
        }
        if !trimmed
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_'))
        {
            return Err(InvalidNodeId);
        }
        Ok(Self(trimmed.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for NodeId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.debug_tuple("NodeId").field(&self.0).finish()
    }
}

impl fmt::Display for NodeId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl FromStr for NodeId {
    type Err = InvalidNodeId;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("invalid xDS node id")]
pub struct InvalidNodeId;

macro_rules! numeric_id {
    ($name:ident) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
        pub struct $name(u64);

        impl $name {
            pub const fn new(value: u64) -> Self {
                Self(value)
            }

            pub const fn get(self) -> u64 {
                self.0
            }
        }
    };
}

numeric_id!(AuthorityEpoch);
numeric_id!(PolicyGeneration);
numeric_id!(PlacementRevision);
numeric_id!(StreamId);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
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

    pub fn from_type_url(type_url: &str) -> Option<Self> {
        match type_url {
            value if value == Self::Cluster.type_url() => Some(Self::Cluster),
            value if value == Self::Listener.type_url() => Some(Self::Listener),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApplyTicket {
    sandbox_id: SandboxId,
    authority_epoch: AuthorityEpoch,
    generation: PolicyGeneration,
    placement_revision: PlacementRevision,
    expected_nodes: BTreeSet<NodeId>,
    required_types: BTreeSet<ResourceType>,
}

impl ApplyTicket {
    pub fn new(
        sandbox_id: SandboxId,
        authority_epoch: AuthorityEpoch,
        generation: PolicyGeneration,
        placement_revision: PlacementRevision,
        expected_nodes: impl IntoIterator<Item = NodeId>,
        required_types: impl IntoIterator<Item = ResourceType>,
    ) -> Self {
        Self {
            sandbox_id,
            authority_epoch,
            generation,
            placement_revision,
            expected_nodes: expected_nodes.into_iter().collect(),
            required_types: required_types.into_iter().collect(),
        }
    }

    pub fn sandbox_id(&self) -> SandboxId {
        self.sandbox_id
    }

    pub fn authority_epoch(&self) -> AuthorityEpoch {
        self.authority_epoch
    }

    pub fn generation(&self) -> PolicyGeneration {
        self.generation
    }

    pub fn placement_revision(&self) -> PlacementRevision {
        self.placement_revision
    }

    pub fn expected_nodes(&self) -> &BTreeSet<NodeId> {
        &self.expected_nodes
    }

    pub fn required_types(&self) -> &BTreeSet<ResourceType> {
        &self.required_types
    }
}
