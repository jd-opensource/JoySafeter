use std::collections::HashMap;

use tokio::sync::Mutex;
use tracing::debug;

use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::ids::{MemoryStoreId, SandboxId, SessionId};
use crate::kernel::sandbox_bridge::BridgeRegistry;

/// In-memory tracking of which sessions subscribe to which memory stores.
///
/// Mirrors the Python `MemoryStoreSubscribers`. When a memory file changes
/// in one sandbox, this module notifies all peer sandboxes that share the
/// same memory store.
pub struct MemoryStoreSubscribers {
    /// Maps store_id → set of (session_id, sandbox_db_id) tuples
    subscriptions: Mutex<HashMap<MemoryStoreId, Vec<MemorySubscription>>>,
}

#[derive(Clone, Debug)]
struct MemorySubscription {
    session_id: SessionId,
    sandbox_db_id: SandboxId,
    mount_name: String,
    mount_path: String,
}

impl MemoryStoreSubscribers {
    pub fn new() -> Self {
        Self {
            subscriptions: Mutex::new(HashMap::new()),
        }
    }

    /// Register a session's subscription to a memory store.
    pub async fn register(
        &self,
        store_id: MemoryStoreId,
        session_id: SessionId,
        sandbox_db_id: SandboxId,
        mount_name: &str,
        mount_path: &str,
    ) {
        let mut subs = self.subscriptions.lock().await;
        let entry = subs.entry(store_id).or_default();

        // Avoid duplicate registrations
        if !entry
            .iter()
            .any(|s| s.session_id == session_id && s.sandbox_db_id == sandbox_db_id)
        {
            entry.push(MemorySubscription {
                session_id,
                sandbox_db_id,
                mount_name: mount_name.to_string(),
                mount_path: mount_path.to_string(),
            });
            debug!(
                store_id = %store_id,
                session_id = %session_id,
                "Registered memory store subscription"
            );
        }
    }

    /// Unregister all subscriptions for a session/sandbox pair.
    pub async fn unregister(&self, session_id: SessionId, sandbox_db_id: SandboxId) {
        let mut subs = self.subscriptions.lock().await;
        for entries in subs.values_mut() {
            entries.retain(|s| !(s.session_id == session_id && s.sandbox_db_id == sandbox_db_id));
        }
    }

    /// Notify all peers of a memory file change.
    ///
    /// Sends `MemoryFileUpdate` to all sandbox bridges that share the same
    /// store, excluding the sender.
    pub async fn notify_peers(
        &self,
        store_mount_name: &str,
        relative_path: &str,
        content: &[u8],
        operation: &str,
        sender_sandbox_id: SandboxId,
        bridge_registry: &BridgeRegistry,
    ) {
        // M3 fix: Collect peers under the lock, then drop it before awaiting
        // gRPC sends. Holding a Mutex across await points can cause deadlocks
        // and blocks other tasks from registering/unregistering subscriptions.
        let peers: Vec<(SandboxId, String)> = {
            let subs = self.subscriptions.lock().await;
            let mut result = Vec::new();
            for (_store_id, entries) in subs.iter() {
                for sub in entries {
                    if sub.mount_name == store_mount_name && sub.sandbox_db_id != sender_sandbox_id
                    {
                        result.push((sub.sandbox_db_id, sub.mount_name.clone()));
                    }
                }
            }
            result
            // lock dropped here
        };

        for (peer_sandbox_id, mount_name) in peers {
            if let Some(bridge) = bridge_registry.get_by_db_id(peer_sandbox_id) {
                let msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::MemoryUpdate(
                        proto::MemoryFileUpdate {
                            store_mount_name: mount_name,
                            relative_path: relative_path.to_string(),
                            content: content.to_vec(),
                            operation: operation.to_string(),
                        },
                    )),
                };
                let _ = bridge.send_to_runner(msg).await;
                debug!(
                    peer_sandbox = %peer_sandbox_id,
                    path = relative_path,
                    "Sent memory update to peer"
                );
            }
        }
    }

    pub async fn notify_store_peers(
        &self,
        store_id: MemoryStoreId,
        relative_path: &str,
        content: &[u8],
        operation: &str,
        bridge_registry: &BridgeRegistry,
    ) {
        let peers: Vec<(SandboxId, String)> = {
            let subs = self.subscriptions.lock().await;
            subs.get(&store_id)
                .into_iter()
                .flatten()
                .map(|sub| (sub.sandbox_db_id, sub.mount_name.clone()))
                .collect()
        };

        for (peer_sandbox_id, mount_name) in peers {
            if let Some(bridge) = bridge_registry.get_by_db_id(peer_sandbox_id) {
                let msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::MemoryUpdate(
                        proto::MemoryFileUpdate {
                            store_mount_name: mount_name,
                            relative_path: relative_path.to_string(),
                            content: content.to_vec(),
                            operation: operation.to_string(),
                        },
                    )),
                };
                let _ = bridge.send_to_runner(msg).await;
            }
        }
    }

    /// Get all peer sandbox IDs for a store (excluding the given sandbox).
    pub async fn get_peers(
        &self,
        store_id: MemoryStoreId,
        exclude_sandbox: SandboxId,
    ) -> Vec<SandboxId> {
        let subs = self.subscriptions.lock().await;
        subs.get(&store_id)
            .map(|entries| {
                entries
                    .iter()
                    .filter(|s| s.sandbox_db_id != exclude_sandbox)
                    .map(|s| s.sandbox_db_id)
                    .collect()
            })
            .unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use tokio::sync::mpsc;
    use uuid::Uuid;

    use super::*;
    use crate::kernel::sandbox_bridge::SandboxBridge;

    #[tokio::test]
    async fn notify_store_peers_targets_store_id_and_preserves_mount_name() {
        let subscribers = MemoryStoreSubscribers::new();
        let registry = BridgeRegistry::new();
        let target_store_id = MemoryStoreId::from_uuid(Uuid::now_v7());
        let other_store_id = MemoryStoreId::from_uuid(Uuid::now_v7());
        let target_session_id = SessionId::from_uuid(Uuid::now_v7());
        let other_session_id = SessionId::from_uuid(Uuid::now_v7());
        let target_sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let other_sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let (target_tx, mut target_rx) = mpsc::channel(1);
        let (other_tx, mut other_rx) = mpsc::channel(1);

        registry.register(
            "target-sandbox".to_string(),
            Arc::new(SandboxBridge::new(target_sandbox_id, target_tx)),
        );
        registry.register(
            "other-sandbox".to_string(),
            Arc::new(SandboxBridge::new(other_sandbox_id, other_tx)),
        );
        subscribers
            .register(
                target_store_id,
                target_session_id,
                target_sandbox_id,
                "workspace-memory",
                "/memories/workspace-memory",
            )
            .await;
        subscribers
            .register(
                other_store_id,
                other_session_id,
                other_sandbox_id,
                "workspace-memory",
                "/memories/workspace-memory",
            )
            .await;

        subscribers
            .notify_store_peers(
                target_store_id,
                "notes.txt",
                b"updated",
                "modified",
                &registry,
            )
            .await;

        let message = target_rx
            .try_recv()
            .expect("target store subscriber notified");
        let Some(orchestrator_message::Payload::MemoryUpdate(update)) = message.payload else {
            panic!("expected memory update payload");
        };
        assert_eq!(update.store_mount_name, "workspace-memory");
        assert_eq!(update.relative_path, "notes.txt");
        assert_eq!(update.content, b"updated");
        assert_eq!(update.operation, "modified");
        assert!(
            other_rx.try_recv().is_err(),
            "subscriber for another store must not receive the update"
        );
    }
}
