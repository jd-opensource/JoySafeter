//! Local implementations for `standalone` and `leader` HA modes.
//!
//! These wrap the existing in-memory `BridgeRegistry` and dispatch logic
//! unchanged, ensuring zero behavioral difference from the pre-trait codebase.

use std::sync::Arc;

use anyhow::anyhow;
use async_trait::async_trait;

use crate::ids::SandboxId;
use crate::kernel::sandbox_bridge::{BridgeRegistry, SandboxBridge};

use super::dispatch::dispatch_to_bridge;
use super::traits::{BridgeStore, DispatchCommand, TaskDispatcher, XdsAction, XdsStateStore};

// ---------------------------------------------------------------------------
// LocalBridgeStore
// ---------------------------------------------------------------------------

/// In-memory bridge store backed by the existing `BridgeRegistry`.
///
/// Used for `standalone` and `leader` modes.
pub struct LocalBridgeStore {
    inner: BridgeRegistry,
}

impl LocalBridgeStore {
    pub fn new() -> Self {
        Self {
            inner: BridgeRegistry::new(),
        }
    }

    /// Access the underlying `BridgeRegistry` for backward-compat call sites
    /// that need the concrete type (e.g. test helpers).
    pub fn inner(&self) -> &BridgeRegistry {
        &self.inner
    }
}

#[async_trait]
impl BridgeStore for LocalBridgeStore {
    fn register(&self, external_id: String, bridge: Arc<SandboxBridge>) {
        self.inner.register(external_id, bridge);
    }

    fn get(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        self.inner.get(external_id)
    }

    fn get_by_db_id(&self, db_id: SandboxId) -> Option<Arc<SandboxBridge>> {
        self.inner.get_by_db_id(db_id)
    }

    fn remove(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        self.inner.remove(external_id)
    }

    fn all_bridges(&self) -> Vec<Arc<SandboxBridge>> {
        self.inner.all_bridges()
    }

    async fn shutdown_all(&self) {
        self.inner.shutdown_all().await;
    }

    async fn get_owner_instance(&self, _sandbox_id: SandboxId) -> Option<String> {
        Some("self".to_string())
    }

    async fn heartbeat(&self) -> anyhow::Result<()> {
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// LocalTaskDispatcher
// ---------------------------------------------------------------------------

/// Dispatches commands directly via the local bridge channel.
///
/// Used for `standalone` and `leader` modes.
pub struct LocalTaskDispatcher {
    bridge_store: Arc<dyn BridgeStore>,
}

impl LocalTaskDispatcher {
    pub fn new(bridge_store: Arc<dyn BridgeStore>) -> Self {
        Self { bridge_store }
    }
}

#[async_trait]
impl TaskDispatcher for LocalTaskDispatcher {
    async fn dispatch_command(
        &self,
        sandbox_id: SandboxId,
        command: DispatchCommand,
    ) -> anyhow::Result<()> {
        let bridge = self
            .bridge_store
            .get_by_db_id(sandbox_id)
            .ok_or_else(|| anyhow!("no local bridge for sandbox {sandbox_id}"))?;

        dispatch_to_bridge(&bridge, sandbox_id, &command).await
    }
}

// ---------------------------------------------------------------------------
// LocalXdsStateStore
// ---------------------------------------------------------------------------

/// No-op xDS state store for `standalone` and `leader` modes.
///
/// In these modes, xDS state is managed entirely in-memory by the existing
/// `DeltaXdsServer` / `EnvoyManager`. Cross-instance notification is not
/// needed because only one instance runs at a time.
pub struct LocalXdsStateStore;

impl LocalXdsStateStore {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl XdsStateStore for LocalXdsStateStore {
    async fn notify_change(&self, _sandbox_id: SandboxId, _action: XdsAction) -> anyhow::Result<()> {
        Ok(())
    }
}
