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
use super::traits::{BridgeStore, DispatchCommand, TaskDispatcher};

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

    fn remove_if_current(&self, external_id: &str, bridge: &Arc<SandboxBridge>) -> bool {
        self.inner.remove_if_current(external_id, bridge)
    }

    fn all_bridges(&self) -> Vec<Arc<SandboxBridge>> {
        self.inner.all_bridges()
    }

    async fn shutdown_all(&self) {
        self.inner.shutdown_all().await;
    }

    async fn get_owner_instance(&self, sandbox_id: SandboxId) -> Option<String> {
        self.inner
            .get_by_db_id(sandbox_id)
            .map(|_| "self".to_string())
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

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use tokio::sync::mpsc;

    use super::{BridgeStore, LocalBridgeStore};
    use crate::ids::SandboxId;
    use crate::kernel::sandbox_bridge::SandboxBridge;

    #[tokio::test]
    async fn owner_exists_only_while_a_local_bridge_is_registered() {
        let store = LocalBridgeStore::new();
        let sandbox_id = SandboxId::new();
        let (runner_tx, _runner_rx) = mpsc::channel(1);
        let bridge = Arc::new(SandboxBridge::new(sandbox_id, runner_tx));

        assert_eq!(store.get_owner_instance(sandbox_id).await, None);
        store.register("runtime-id".to_string(), bridge.clone());
        assert_eq!(
            store.get_owner_instance(sandbox_id).await.as_deref(),
            Some("self")
        );
        assert!(store.remove_if_current("runtime-id", &bridge));
        assert_eq!(store.get_owner_instance(sandbox_id).await, None);
    }
}
