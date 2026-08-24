//! HA (High Availability) mode abstractions.
//!
//! Three deployment modes are supported, selected by `JOYSAFETER_HA_MODE`:
//!
//! * **`standalone`** (default) — single instance, no HA coordination. Used for
//!   Docker Compose / local development.
//!
//! * **`leader`** — two K8s replicas with Lease-based leader election. Only the
//!   leader runs services; the standby waits for the Lease to expire. Uses local
//!   in-memory state (identical to standalone once leadership is acquired).
//!
//! * **`multi`** — N stateless replicas coordinated via Redis. All replicas run
//!   services concurrently; task dispatch, bridge registration, and xDS state
//!   are shared through Redis Streams.

pub mod dispatch;
pub mod local;
pub mod redis_impl;
pub mod stream;
pub mod traits;

use std::sync::Arc;

use tokio::task::JoinHandle;
use tracing::info;

use crate::config::JoySafeterConfig;

pub use local::{LocalBridgeStore, LocalTaskDispatcher};
pub use redis_impl::{RedisBridgeStore, RedisNetworkPolicyRequestQueue, RedisTaskDispatcher};
pub use traits::{
    BridgeStore, DispatchCommand, NetworkPolicyAction, NetworkPolicyRequest,
    NetworkPolicyRequestQueue, TaskDispatcher,
};

// ---------------------------------------------------------------------------
// HaMode
// ---------------------------------------------------------------------------

/// Deployment mode for the orchestrator.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HaMode {
    /// Single instance, no HA. Default for Docker Compose.
    Standalone,
    /// K8s Lease-based leader election (2 replicas, only leader runs services).
    Leader,
    /// Multi-replica stateless (N replicas, Redis-coordinated).
    Multi,
}

impl HaMode {
    pub fn from_config(config: &JoySafeterConfig) -> Self {
        match config.ha_mode.as_str() {
            "leader" => Self::Leader,
            "multi" => Self::Multi,
            _ => {
                // Backward compat: infer leader mode from old flag
                if config.leader_election_enabled && config.ha_mode.is_empty() {
                    Self::Leader
                } else {
                    Self::Standalone
                }
            }
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Standalone => "standalone",
            Self::Leader => "leader",
            Self::Multi => "multi",
        }
    }
}

// ---------------------------------------------------------------------------
// HaComponents
// ---------------------------------------------------------------------------

/// Assembled HA components for the orchestrator.
///
/// Passed to all services (gRPC server, scheduler, sandbox controller, etc.)
/// so they dispatch through the appropriate implementation.
pub struct HaComponents {
    pub mode: HaMode,
    pub bridge_store: Arc<dyn BridgeStore>,
    pub task_dispatcher: Arc<dyn TaskDispatcher>,
    pub network_policy_queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
    /// Background task handles for multi mode (inbox, heartbeat, authority requests).
    /// Empty for standalone/leader.
    pub background_handles: Vec<JoinHandle<()>>,
}

/// Build HA components based on the configured mode.
///
/// For `standalone`/`leader`, creates local (in-memory) implementations.
/// For `multi`, creates Redis-backed implementations with background loops.
pub fn build_ha_components(
    config: &JoySafeterConfig,
    redis_client: Option<&redis::Client>,
) -> HaComponents {
    let mode = HaMode::from_config(config);

    match mode {
        HaMode::Standalone | HaMode::Leader => {
            let bridge_store: Arc<dyn BridgeStore> = Arc::new(LocalBridgeStore::new());
            let task_dispatcher: Arc<dyn TaskDispatcher> =
                Arc::new(LocalTaskDispatcher::new(bridge_store.clone()));
            info!(mode = mode.as_str(), "HA components initialized (local)");

            HaComponents {
                mode,
                bridge_store,
                task_dispatcher,
                network_policy_queue: None,
                background_handles: Vec::new(),
            }
        }
        HaMode::Multi => {
            let client = redis_client
                .expect("Redis is required for JOYSAFETER_HA_MODE=multi")
                .clone();
            let instance_id = config.instance_id.clone();

            let bridge_store: Arc<dyn BridgeStore> =
                Arc::new(RedisBridgeStore::new(client.clone(), &instance_id));
            let task_dispatcher: Arc<dyn TaskDispatcher> = Arc::new(RedisTaskDispatcher::new(
                bridge_store.clone(),
                client.clone(),
                &instance_id,
            ));
            let network_policy_queue: Arc<dyn NetworkPolicyRequestQueue> = Arc::new(
                RedisNetworkPolicyRequestQueue::new(client.clone(), &instance_id),
            );

            // Spawn background loops
            let mut handles = Vec::new();

            // Inbox consumer — receives cross-instance commands
            let inbox_handle = tokio::spawn(redis_impl::inbox_consumer_loop(
                client.clone(),
                instance_id.clone(),
                bridge_store.clone(),
            ));
            handles.push(inbox_handle);

            // Bridge heartbeat — refreshes Redis TTLs
            let heartbeat_handle =
                tokio::spawn(redis_impl::bridge_heartbeat_loop(bridge_store.clone()));
            handles.push(heartbeat_handle);

            info!(
                mode = mode.as_str(),
                instance_id = %instance_id,
                "HA components initialized (redis, {} background loops)",
                handles.len()
            );

            HaComponents {
                mode,
                bridge_store,
                task_dispatcher,
                network_policy_queue: Some(network_policy_queue),
                background_handles: handles,
            }
        }
    }
}
