use std::collections::HashMap;

use tokio::sync::Mutex;
use tracing::debug;
use uuid::Uuid;

use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::kernel::ha::BridgeStore;

/// In-memory tracking of which sessions subscribe to which memory stores.
///
/// Mirrors the Python `MemoryStoreSubscribers`. When a memory file changes
/// in one sandbox, this module notifies all peer sandboxes that share the
/// same memory store.
pub struct MemoryStoreSubscribers {
    /// Maps store_id → set of (session_id, sandbox_db_id) tuples
    subscriptions: Mutex<HashMap<String, Vec<MemorySubscription>>>,
}

#[derive(Clone, Debug)]
struct MemorySubscription {
    session_id: Uuid,
    sandbox_db_id: Uuid,
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
        store_id: &str,
        session_id: Uuid,
        sandbox_db_id: Uuid,
        mount_name: &str,
        mount_path: &str,
    ) {
        let mut subs = self.subscriptions.lock().await;
        let entry = subs.entry(store_id.to_string()).or_default();

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
                store_id = store_id,
                session_id = %session_id,
                "Registered memory store subscription"
            );
        }
    }

    /// Unregister all subscriptions for a session/sandbox pair.
    pub async fn unregister(&self, session_id: Uuid, sandbox_db_id: Uuid) {
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
        sender_sandbox_id: Uuid,
        bridge_store: &dyn BridgeStore,
    ) {
        // M3 fix: Collect peers under the lock, then drop it before awaiting
        // gRPC sends. Holding a Mutex across await points can cause deadlocks
        // and blocks other tasks from registering/unregistering subscriptions.
        let peers: Vec<(Uuid, String)> = {
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
            if let Some(bridge) = bridge_store.get_by_db_id(peer_sandbox_id) {
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

    /// Get all peer sandbox IDs for a store (excluding the given sandbox).
    pub async fn get_peers(&self, store_id: &str, exclude_sandbox: Uuid) -> Vec<Uuid> {
        let subs = self.subscriptions.lock().await;
        subs.get(store_id)
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
