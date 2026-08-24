//! HA abstraction traits for the three deployment modes.
//!
//! These traits allow the orchestrator to run in `standalone`, `leader`, or
//! `multi` mode. For `standalone`/`leader`, the [`LocalBridgeStore`],
//! and [`LocalTaskDispatcher`] delegate to the existing in-memory
//! implementations. For `multi`, Redis-backed implementations coordinate
//! runner ownership and wake the elected xDS authority.

use std::sync::Arc;

use async_trait::async_trait;

use crate::db::queries::NetworkPolicyGeneration;
use crate::ids::SandboxId;
use crate::kernel::sandbox_bridge::SandboxBridge;

// ---------------------------------------------------------------------------
// BridgeStore
// ---------------------------------------------------------------------------

/// Abstraction over the sandbox bridge registry.
///
/// For `standalone`/`leader` mode this is backed by an in-memory `DashMap`.
/// For `multi` mode it adds Redis key registration (with TTL) on top of the
/// local cache.
#[async_trait]
pub trait BridgeStore: Send + Sync + 'static {
    /// Register a new sandbox bridge (called when runner gRPC connects).
    fn register(&self, external_id: String, bridge: Arc<SandboxBridge>);

    /// Get a bridge by external (provider) ID.
    fn get(&self, external_id: &str) -> Option<Arc<SandboxBridge>>;

    /// Get a bridge by database UUID.
    fn get_by_db_id(&self, db_id: SandboxId) -> Option<Arc<SandboxBridge>>;

    /// Remove a bridge by external ID.
    fn remove(&self, external_id: &str) -> Option<Arc<SandboxBridge>>;

    /// Get all currently registered bridges.
    fn all_bridges(&self) -> Vec<Arc<SandboxBridge>>;

    /// Send shutdown to all connected runners.
    async fn shutdown_all(&self);

    /// Which orchestrator instance owns this sandbox.
    /// Returns `Some("self")` for local modes, `Some(instance_id)` for multi.
    async fn get_owner_instance(&self, sandbox_id: SandboxId) -> Option<String>;

    /// Heartbeat to refresh TTLs (no-op for local mode).
    async fn heartbeat(&self) -> anyhow::Result<()>;
}

// ---------------------------------------------------------------------------
// TaskDispatcher
// ---------------------------------------------------------------------------

/// Command types that can be dispatched to a runner.
#[derive(Debug, Clone)]
pub enum DispatchCommand {
    Cancel {
        reason: String,
    },
    SendInput {
        content: String,
    },
    Shutdown {
        reason: String,
    },
    /// Wake the multi_task_loop to claim a newly-assigned task.
    /// Only used in multi mode when scheduler and bridge are on different replicas.
    TaskWakeup,
}

/// Abstraction for dispatching commands to sandbox runners.
///
/// For `standalone`/`leader`, dispatches directly via the local bridge channel.
/// For `multi`, routes via Redis inbox streams when the sandbox lives on
/// another replica.
#[async_trait]
pub trait TaskDispatcher: Send + Sync + 'static {
    /// Send a command to the runner managing this sandbox.
    async fn dispatch_command(
        &self,
        sandbox_id: SandboxId,
        command: DispatchCommand,
    ) -> anyhow::Result<()>;
}

// ---------------------------------------------------------------------------
// NetworkPolicyRequestQueue
// ---------------------------------------------------------------------------

/// Commands accepted by the elected xDS authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkPolicyAction {
    Reconcile,
    Remove,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkPolicyRequest {
    pub sandbox_id: SandboxId,
    pub action: NetworkPolicyAction,
    pub generation: Option<NetworkPolicyGeneration>,
}

impl NetworkPolicyRequest {
    pub fn reconcile(sandbox_id: SandboxId, generation: NetworkPolicyGeneration) -> Self {
        Self {
            sandbox_id,
            action: NetworkPolicyAction::Reconcile,
            generation: Some(generation),
        }
    }

    pub fn remove(sandbox_id: SandboxId) -> Self {
        Self {
            sandbox_id,
            action: NetworkPolicyAction::Remove,
            generation: None,
        }
    }
}

/// Durable wakeup channel for the elected xDS authority.
///
/// PostgreSQL remains authoritative for desired policy and generation. Queue
/// messages may be duplicated or missed; authority recovery reconciles from DB.
#[async_trait]
pub trait NetworkPolicyRequestQueue: Send + Sync + 'static {
    async fn publish(&self, request: NetworkPolicyRequest) -> anyhow::Result<()>;
}

#[cfg(test)]
mod network_policy_request_tests {
    use super::{NetworkPolicyAction, NetworkPolicyRequest};
    use crate::db::queries::NetworkPolicyGeneration;
    use crate::ids::SandboxId;
    use uuid::Uuid;

    #[test]
    fn reconcile_request_carries_exact_generation() {
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let generation = NetworkPolicyGeneration {
            policy_hash: "policy-hash".to_string(),
            policy_version: 7,
        };

        let request = NetworkPolicyRequest::reconcile(sandbox_id, generation.clone());

        assert_eq!(request.sandbox_id, sandbox_id);
        assert_eq!(request.action, NetworkPolicyAction::Reconcile);
        assert_eq!(request.generation, Some(generation));
    }

    #[test]
    fn removal_request_has_no_policy_generation() {
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

        let request = NetworkPolicyRequest::remove(sandbox_id);

        assert_eq!(request.action, NetworkPolicyAction::Remove);
        assert_eq!(request.generation, None);
    }
}
