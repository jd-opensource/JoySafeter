//! HA abstraction traits for the three deployment modes.
//!
//! These traits allow the orchestrator to run in `standalone`, `leader`, or
//! `multi` mode. For `standalone`/`leader`, the [`LocalBridgeStore`],
//! [`LocalTaskDispatcher`], and [`LocalXdsStateStore`] delegate to the existing
//! in-memory implementations. For `multi`, Redis-backed implementations
//! coordinate across replicas.

use std::sync::Arc;

use async_trait::async_trait;
use uuid::Uuid;

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
    fn get_by_db_id(&self, db_id: Uuid) -> Option<Arc<SandboxBridge>>;

    /// Remove a bridge by external ID.
    fn remove(&self, external_id: &str) -> Option<Arc<SandboxBridge>>;

    /// Get all currently registered bridges.
    fn all_bridges(&self) -> Vec<Arc<SandboxBridge>>;

    /// Send shutdown to all connected runners.
    async fn shutdown_all(&self);

    /// Which orchestrator instance owns this sandbox.
    /// Returns `Some("self")` for local modes, `Some(instance_id)` for multi.
    async fn get_owner_instance(&self, sandbox_id: Uuid) -> Option<String>;

    /// Heartbeat to refresh TTLs (no-op for local mode).
    async fn heartbeat(&self) -> anyhow::Result<()>;
}

// ---------------------------------------------------------------------------
// TaskDispatcher
// ---------------------------------------------------------------------------

/// Command types that can be dispatched to a runner.
#[derive(Debug, Clone)]
pub enum DispatchCommand {
    Cancel { reason: String },
    SendInput { content: String },
    Shutdown { reason: String },
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
        sandbox_id: Uuid,
        command: DispatchCommand,
    ) -> anyhow::Result<()>;
}

// ---------------------------------------------------------------------------
// XdsStateStore
// ---------------------------------------------------------------------------

/// Actions for xDS change notifications.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum XdsAction {
    Upsert,
    Remove,
}

/// Abstraction over xDS listener state storage and cross-instance notification.
///
/// For `standalone`/`leader`, wraps the existing `EnvoyManager` — state lives
/// in memory and is pushed directly to the local Envoy. For `multi`, state is
/// persisted to Redis and changes are broadcast via a notify stream.
#[async_trait]
pub trait XdsStateStore: Send + Sync + 'static {
    /// Notify other instances of an xDS change (no-op for local mode).
    async fn notify_change(&self, sandbox_id: Uuid, action: XdsAction) -> anyhow::Result<()>;
}
