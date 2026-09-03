//! Redis-backed implementations for `multi` HA mode.
//!
//! Provides:
//! - [`RedisBridgeStore`]: local DashMap cache + Redis key registration with TTL
//! - [`RedisTaskDispatcher`]: local-first dispatch, cross-instance via Redis Streams
//! - [`RedisNetworkPolicyRequestQueue`]: wakeups for the elected xDS authority
//! - Background loops: inbox consumer, bridge heartbeat, authority request consumer

use std::sync::Arc;
use std::time::Duration;

use anyhow::anyhow;
use async_trait::async_trait;
use redis::AsyncCommands;
use serde_json::json;
use tracing::{debug, info, warn};
use uuid::Uuid;

use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::ids::SandboxId;
use crate::kernel::network_policy::ports::NetworkPolicyRequestQueue;
use crate::kernel::network_policy::{
    NetworkPolicyAction, NetworkPolicyGeneration, NetworkPolicyRequest,
};
use crate::kernel::sandbox_bridge::{BridgeRegistry, SandboxBridge};
use crate::xds::authority_worker::{AuthorityRequestEnvelope, AuthorityRequestSource};

use super::dispatch::dispatch_to_bridge;
use super::stream::StreamConsumer;
use super::traits::{BridgeStore, DispatchCommand, TaskDispatcher};

// ---------------------------------------------------------------------------
// Redis key constants
// ---------------------------------------------------------------------------

/// Bridge ownership: maps sandbox_db_id → instance_id. TTL-based liveness.
const BRIDGE_KEY_PREFIX: &str = "joysafeter:bridge:";
/// Per-instance inbox stream for cross-instance command relay.
const INBOX_KEY_PREFIX: &str = "joysafeter:inbox:";
/// Network-policy request stream (shared across all instances).
const NETWORK_POLICY_REQUEST_KEY: &str = "joysafeter:network-policy:requests";

/// Bridge key TTL in seconds. Refreshed by heartbeat every 30s.
const BRIDGE_TTL_SECS: u64 = 60;
/// Inbox stream max length (approximate trim).
const INBOX_MAXLEN: usize = 1000;
/// Network-policy request stream max length (approximate trim).
const NETWORK_POLICY_REQUEST_MAXLEN: usize = 1000;

const REGISTER_BRIDGE_OWNERSHIP_SCRIPT: &str = r#"
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3])
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
return 1
"#;

const REMOVE_BRIDGE_OWNERSHIP_SCRIPT: &str = r#"
local owner = redis.call('GET', KEYS[1])
local generation = redis.call('GET', KEYS[2])
if generation == ARGV[1] or (generation == false and owner == ARGV[2]) then
    redis.call('DEL', KEYS[1], KEYS[2])
    return 1
end
return 0
"#;

const REFRESH_BRIDGE_OWNERSHIP_SCRIPT: &str = r#"
local owner = redis.call('GET', KEYS[1])
local generation = redis.call('GET', KEYS[2])
if generation == ARGV[1]
    or (generation == false and owner == ARGV[2])
    or (generation == false and owner == false) then
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[3])
    return 1
end
return 0
"#;

fn bridge_registration_token(instance_id: &str, connection_id: Uuid) -> String {
    format!("{instance_id}\n{connection_id}")
}

/// Keep the ownership and connection-generation keys in the same Redis Cluster
/// slot. Redis hashes only the substring enclosed in `{...}`, so both keys use
/// the sandbox ID as their shared hash tag. This is required by the Lua scripts,
/// which operate on both keys atomically without Redis MULTI/EXEC transactions.
fn bridge_owner_key(sandbox_id: Uuid) -> String {
    format!("{BRIDGE_KEY_PREFIX}{{{sandbox_id}}}:owner")
}

fn bridge_generation_key(sandbox_id: Uuid) -> String {
    format!("{BRIDGE_KEY_PREFIX}{{{sandbox_id}}}:generation")
}

fn schedule_bridge_owner_removal(
    client: redis::Client,
    instance_id: String,
    sandbox_id: Uuid,
    connection_id: Uuid,
) {
    tokio::spawn(async move {
        if let Ok(mut conn) = client.get_multiplexed_async_connection().await {
            let owner_key = bridge_owner_key(sandbox_id);
            let generation_key = bridge_generation_key(sandbox_id);
            let token = bridge_registration_token(&instance_id, connection_id);
            let _ = redis::Script::new(REMOVE_BRIDGE_OWNERSHIP_SCRIPT)
                .key(owner_key)
                .key(generation_key)
                .arg(token)
                .arg(instance_id)
                .invoke_async::<i64>(&mut conn)
                .await;
        }
    });
}
// ---------------------------------------------------------------------------
// RedisBridgeStore
// ---------------------------------------------------------------------------

/// Bridge store with local DashMap cache + Redis key registration.
///
/// The local cache serves all read operations (zero Redis RTT on the hot path).
/// Redis keys provide cross-instance ownership discovery and TTL-based liveness.
pub struct RedisBridgeStore {
    /// Local in-memory cache (same performance as standalone mode).
    inner: BridgeRegistry,
    /// Redis client for ownership registration.
    redis_client: redis::Client,
    /// This orchestrator instance's unique ID.
    instance_id: String,
}

impl RedisBridgeStore {
    pub fn new(redis_client: redis::Client, instance_id: &str) -> Self {
        Self {
            inner: BridgeRegistry::new(),
            redis_client,
            instance_id: instance_id.to_string(),
        }
    }

    async fn get_conn(&self) -> anyhow::Result<redis::aio::MultiplexedConnection> {
        self.redis_client
            .get_multiplexed_async_connection()
            .await
            .map_err(|e| anyhow!("Redis connection failed: {e}"))
    }
}

#[async_trait]
impl BridgeStore for RedisBridgeStore {
    fn register(&self, external_id: String, bridge: Arc<SandboxBridge>) {
        let sandbox_db_id = bridge.sandbox_db_id.as_uuid();
        let connection_id = bridge.connection_id();
        let registered_bridge = bridge.clone();
        let registry = self.inner.clone();
        let registered_external_id = external_id.clone();
        // Local cache (immediate, sync)
        self.inner.register(external_id, bridge);

        // Redis registration (fire-and-forget async)
        let client = self.redis_client.clone();
        let instance_id = self.instance_id.clone();
        tokio::spawn(async move {
            if !registry
                .get(&registered_external_id)
                .is_some_and(|current| Arc::ptr_eq(&current, &registered_bridge))
            {
                return;
            }
            match client.get_multiplexed_async_connection().await {
                Ok(mut conn) => {
                    let owner_key = bridge_owner_key(sandbox_db_id);
                    let generation_key = bridge_generation_key(sandbox_db_id);
                    let token = bridge_registration_token(&instance_id, connection_id);
                    let result = redis::Script::new(REGISTER_BRIDGE_OWNERSHIP_SCRIPT)
                        .key(owner_key)
                        .key(generation_key)
                        .arg(&instance_id)
                        .arg(token)
                        .arg(BRIDGE_TTL_SECS)
                        .invoke_async::<i64>(&mut conn)
                        .await;
                    if let Err(e) = result {
                        warn!(
                            sandbox_id = %sandbox_db_id,
                            "Failed to register bridge in Redis: {e}"
                        );
                    }
                }
                Err(e) => {
                    warn!(
                        sandbox_id = %sandbox_db_id,
                        "Redis connection failed during bridge registration: {e}"
                    );
                }
            }
        });
    }

    fn get(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        self.inner.get(external_id)
    }

    fn get_by_db_id(&self, db_id: SandboxId) -> Option<Arc<SandboxBridge>> {
        self.inner.get_by_db_id(db_id)
    }

    fn remove(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        let bridge = self.inner.remove(external_id);
        if let Some(ref b) = bridge {
            schedule_bridge_owner_removal(
                self.redis_client.clone(),
                self.instance_id.clone(),
                b.sandbox_db_id.as_uuid(),
                b.connection_id(),
            );
        }
        bridge
    }

    fn remove_if_current(&self, external_id: &str, bridge: &Arc<SandboxBridge>) -> bool {
        if !self.inner.remove_if_current(external_id, bridge) {
            return false;
        }
        schedule_bridge_owner_removal(
            self.redis_client.clone(),
            self.instance_id.clone(),
            bridge.sandbox_db_id.as_uuid(),
            bridge.connection_id(),
        );
        true
    }

    fn all_bridges(&self) -> Vec<Arc<SandboxBridge>> {
        self.inner.all_bridges()
    }

    async fn shutdown_all(&self) {
        self.inner.shutdown_all().await;
    }

    async fn get_owner_instance(&self, sandbox_id: SandboxId) -> Option<String> {
        let key = bridge_owner_key(sandbox_id.as_uuid());
        match self.get_conn().await {
            Ok(mut conn) => conn.get::<_, Option<String>>(&key).await.unwrap_or(None),
            Err(_) => None,
        }
    }

    async fn heartbeat(&self) -> anyhow::Result<()> {
        let bridges = self.inner.all_bridges();
        if bridges.is_empty() {
            return Ok(());
        }

        let mut conn = self.get_conn().await?;

        // Refresh only the exact local connection generation. This prevents a
        // displaced connection from extending or deleting a replacement owner.
        let mut pipe = redis::pipe();
        for bridge in &bridges {
            let sandbox_id = bridge.sandbox_db_id.as_uuid();
            let owner_key = bridge_owner_key(sandbox_id);
            let generation_key = bridge_generation_key(sandbox_id);
            pipe.cmd("EVAL")
                .arg(REFRESH_BRIDGE_OWNERSHIP_SCRIPT)
                .arg(2)
                .arg(owner_key)
                .arg(generation_key)
                .arg(bridge_registration_token(
                    &self.instance_id,
                    bridge.connection_id(),
                ))
                .arg(&self.instance_id)
                .arg(BRIDGE_TTL_SECS);
        }
        let _: Vec<i64> = pipe.query_async(&mut conn).await?;

        debug!(
            total = bridges.len(),
            "Bridge heartbeat complete (pipeline)"
        );
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// RedisTaskDispatcher
// ---------------------------------------------------------------------------

/// Dispatches commands with local-first semantics + Redis Stream relay.
///
/// If the target sandbox's bridge is local, dispatches directly (zero Redis).
/// Otherwise, looks up the owner instance in Redis and relays via the target's
/// inbox stream. Owner lookups are cached locally for 5s to avoid repeated
/// Redis GETs on hot paths (e.g., streaming events triggering multiple dispatches).
pub struct RedisTaskDispatcher {
    bridge_store: Arc<dyn BridgeStore>,
    redis_client: redis::Client,
    instance_id: String,
    /// Local cache: sandbox_id → (instance_id, cached_at). Avoids repeated Redis GETs.
    owner_cache: dashmap::DashMap<SandboxId, (String, std::time::Instant)>,
}

/// How long to cache a remote owner lookup before re-checking Redis.
const OWNER_CACHE_TTL: Duration = Duration::from_secs(5);

impl RedisTaskDispatcher {
    pub fn new(
        bridge_store: Arc<dyn BridgeStore>,
        redis_client: redis::Client,
        instance_id: &str,
    ) -> Self {
        Self {
            bridge_store,
            redis_client,
            instance_id: instance_id.to_string(),
            owner_cache: dashmap::DashMap::new(),
        }
    }

    async fn get_conn(&self) -> anyhow::Result<redis::aio::MultiplexedConnection> {
        self.redis_client
            .get_multiplexed_async_connection()
            .await
            .map_err(|e| anyhow!("Redis connection failed: {e}"))
    }
}

#[async_trait]
impl TaskDispatcher for RedisTaskDispatcher {
    async fn dispatch_command(
        &self,
        sandbox_id: SandboxId,
        command: DispatchCommand,
    ) -> anyhow::Result<()> {
        // Fast path: try local bridge first (zero Redis RTT)
        if let Some(bridge) = self.bridge_store.get_by_db_id(sandbox_id) {
            return dispatch_to_bridge(&bridge, sandbox_id, &command).await;
        }

        // Slow path: look up owner instance (cached locally, fallback to Redis)
        let mut conn = self.get_conn().await?;
        let bridge_key = bridge_owner_key(sandbox_id.as_uuid());

        // Check local owner cache first (avoids Redis GET on repeated dispatches)
        let target = if let Some(entry) = self.owner_cache.get(&sandbox_id) {
            let (ref cached_owner, cached_at) = *entry;
            if cached_at.elapsed() < OWNER_CACHE_TTL {
                cached_owner.clone()
            } else {
                drop(entry);
                self.owner_cache.remove(&sandbox_id);
                let owner: Option<String> = conn.get(&bridge_key).await?;
                match owner {
                    Some(o) => {
                        self.owner_cache
                            .insert(sandbox_id, (o.clone(), std::time::Instant::now()));
                        o
                    }
                    None => {
                        return Err(anyhow!(
                            "sandbox {sandbox_id} not registered on any instance"
                        ));
                    }
                }
            }
        } else {
            let owner: Option<String> = conn.get(&bridge_key).await?;
            match owner {
                Some(o) => {
                    self.owner_cache
                        .insert(sandbox_id, (o.clone(), std::time::Instant::now()));
                    o
                }
                None => {
                    return Err(anyhow!(
                        "sandbox {sandbox_id} not registered on any instance"
                    ));
                }
            }
        };

        if target == self.instance_id {
            // Registered to us but bridge not in local cache — stale Redis key.
            // Invalidate cache and return error (bridge likely gone).
            self.owner_cache.remove(&sandbox_id);
            return Err(anyhow!(
                "sandbox {sandbox_id} registered to self but bridge not found locally"
            ));
        }

        // Serialize command and relay via target's inbox stream
        let (cmd_type, payload) = match &command {
            DispatchCommand::Cancel { reason } => ("cancel", json!({"reason": reason})),
            DispatchCommand::SendInput { content } => ("send_input", json!({"content": content})),
            DispatchCommand::Shutdown { reason } => ("shutdown", json!({"reason": reason})),
            DispatchCommand::TaskWakeup => ("task_wakeup", json!({})),
        };

        let inbox_key = format!("{INBOX_KEY_PREFIX}{target}");
        redis::cmd("XADD")
            .arg(&inbox_key)
            .arg("MAXLEN")
            .arg("~")
            .arg(INBOX_MAXLEN)
            .arg("*")
            .arg("type")
            .arg(cmd_type)
            .arg("sandbox_id")
            .arg(sandbox_id.as_uuid().to_string())
            .arg("payload")
            .arg(payload.to_string())
            .query_async::<String>(&mut conn)
            .await?;

        debug!(
            sandbox_id = %sandbox_id,
            target_instance = %target,
            cmd_type = cmd_type,
            "Relayed command via Redis inbox"
        );
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// RedisNetworkPolicyRequestQueue
// ---------------------------------------------------------------------------

/// Durable wakeups for the elected xDS authority.
pub struct RedisNetworkPolicyRequestQueue {
    redis_client: redis::Client,
    instance_id: String,
}

impl RedisNetworkPolicyRequestQueue {
    pub fn new(redis_client: redis::Client, instance_id: &str) -> Self {
        Self {
            redis_client,
            instance_id: instance_id.to_string(),
        }
    }
}

#[async_trait]
impl NetworkPolicyRequestQueue for RedisNetworkPolicyRequestQueue {
    async fn publish(&self, request: NetworkPolicyRequest) -> anyhow::Result<()> {
        let mut conn = self
            .redis_client
            .get_multiplexed_async_connection()
            .await
            .map_err(|e| anyhow!("Redis connection failed for network-policy request: {e}"))?;

        let action_str = match request.action {
            NetworkPolicyAction::Reconcile => "reconcile",
            NetworkPolicyAction::Remove => "remove",
        };
        let policy_hash = request
            .generation
            .as_ref()
            .map(|generation| generation.policy_hash.as_str())
            .unwrap_or("");
        let policy_version = request
            .generation
            .as_ref()
            .map(|generation| generation.policy_version)
            .unwrap_or_default();

        redis::cmd("XADD")
            .arg(NETWORK_POLICY_REQUEST_KEY)
            .arg("MAXLEN")
            .arg("~")
            .arg(NETWORK_POLICY_REQUEST_MAXLEN)
            .arg("*")
            .arg("sandbox_id")
            .arg(request.sandbox_id.as_uuid().to_string())
            .arg("action")
            .arg(action_str)
            .arg("instance")
            .arg(&self.instance_id)
            .arg("policy_hash")
            .arg(policy_hash)
            .arg("policy_version")
            .arg(policy_version)
            .query_async::<String>(&mut conn)
            .await?;

        debug!(
            sandbox_id = %request.sandbox_id,
            action = action_str,
            "Published network-policy authority request"
        );
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Background Loops
// ---------------------------------------------------------------------------

/// Inbox consumer loop: reads commands from this instance's Redis Stream inbox
/// and dispatches them to local bridges.
///
/// Commands arrive when another instance's `RedisTaskDispatcher` relays a
/// cancel/input/shutdown targeting a sandbox on this instance.
pub async fn inbox_consumer_loop(
    redis_client: redis::Client,
    instance_id: String,
    bridge_store: Arc<dyn BridgeStore>,
) {
    let inbox_key = format!("{INBOX_KEY_PREFIX}{instance_id}");
    let mut consumer = StreamConsumer::new(redis_client, inbox_key.clone());

    info!(inbox_key = %inbox_key, "Inbox consumer loop started");

    loop {
        if let Some(entries) = consumer.next_batch().await {
            for (_entry_id, fields) in entries {
                handle_inbox_message(&bridge_store, &fields).await;
            }
        }
    }
}

/// Handle a single inbox message by dispatching to the local bridge.
async fn handle_inbox_message(bridge_store: &Arc<dyn BridgeStore>, fields: &[(String, String)]) {
    let mut cmd_type = "";
    let mut sandbox_id_str = "";
    let mut payload_str = "";

    for (key, value) in fields {
        match key.as_str() {
            "type" => cmd_type = value,
            "sandbox_id" => sandbox_id_str = value,
            "payload" => payload_str = value,
            _ => {}
        }
    }

    let sandbox_id: SandboxId = match sandbox_id_str.parse::<Uuid>() {
        Ok(id) => SandboxId::from_uuid(id),
        Err(_) => {
            warn!("Inbox message has invalid sandbox_id: {sandbox_id_str}");
            return;
        }
    };

    let bridge = match bridge_store.get_by_db_id(sandbox_id) {
        Some(b) => b,
        None => {
            debug!(
                sandbox_id = %sandbox_id,
                cmd_type = cmd_type,
                "Inbox message for sandbox without local bridge, ignoring"
            );
            return;
        }
    };

    let payload: serde_json::Value =
        serde_json::from_str(payload_str).unwrap_or(serde_json::Value::Null);

    match cmd_type {
        "cancel" => {
            let reason = payload["reason"].as_str().unwrap_or("remote cancel");
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Cancel(proto::CancelTask {
                    reason: reason.to_string(),
                })),
            };
            let _ = bridge.send_to_runner(msg).await;
            bridge.request_cancel().await;
            debug!(sandbox_id = %sandbox_id, "Inbox: dispatched cancel");
        }
        "send_input" => {
            let content = payload["content"].as_str().unwrap_or("");
            let _ = bridge.send_control_input(content.to_string()).await;
            debug!(sandbox_id = %sandbox_id, "Inbox: dispatched send_input");
        }
        "shutdown" => {
            let reason = payload["reason"].as_str().unwrap_or("remote shutdown");
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Shutdown(proto::Shutdown {
                    reason: reason.to_string(),
                })),
            };
            let _ = bridge.send_to_runner(msg).await;
            debug!(sandbox_id = %sandbox_id, "Inbox: dispatched shutdown");
        }
        "task_wakeup" => {
            bridge.task_available.notify_one();
            debug!(sandbox_id = %sandbox_id, "Inbox: dispatched task_wakeup");
        }
        other => {
            warn!(
                sandbox_id = %sandbox_id,
                cmd_type = other,
                "Inbox: unknown command type"
            );
        }
    }
}

/// Bridge heartbeat loop: refreshes TTL on all locally-registered bridges.
pub async fn bridge_heartbeat_loop(bridge_store: Arc<dyn BridgeStore>) {
    let interval = Duration::from_secs(30);
    info!("Bridge heartbeat loop started (interval=30s)");

    loop {
        tokio::time::sleep(interval).await;
        if let Err(e) = bridge_store.heartbeat().await {
            warn!("Bridge heartbeat failed: {e}");
        }
    }
}

fn parse_network_policy_request(
    fields: &[(String, String)],
) -> anyhow::Result<NetworkPolicyRequest> {
    let field = |name: &str| {
        fields
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.as_str())
    };
    let sandbox_id = field("sandbox_id")
        .ok_or_else(|| anyhow!("network policy request missing sandbox_id"))?
        .parse::<Uuid>()
        .map(SandboxId::from_uuid)
        .map_err(|error| anyhow!("invalid sandbox_id in network policy request: {error}"))?;
    match field("action") {
        Some("reconcile") => {
            let policy_hash = field("policy_hash")
                .filter(|value| !value.is_empty())
                .ok_or_else(|| anyhow!("network policy request missing policy_hash"))?;
            let policy_version = field("policy_version")
                .ok_or_else(|| anyhow!("network policy request missing policy_version"))?
                .parse::<i64>()
                .map_err(|error| anyhow!("invalid network policy version: {error}"))?;
            Ok(NetworkPolicyRequest::reconcile(
                sandbox_id,
                NetworkPolicyGeneration {
                    policy_hash: policy_hash.to_string(),
                    policy_version,
                },
            ))
        }
        Some("remove") => {
            let policy_hash = field("policy_hash")
                .filter(|value| !value.is_empty())
                .ok_or_else(|| anyhow!("network policy removal missing policy_hash"))?;
            let policy_version = field("policy_version")
                .ok_or_else(|| anyhow!("network policy removal missing policy_version"))?
                .parse::<i64>()
                .map_err(|error| anyhow!("invalid network policy version: {error}"))?;
            Ok(NetworkPolicyRequest::remove(
                sandbox_id,
                NetworkPolicyGeneration {
                    policy_hash: policy_hash.to_string(),
                    policy_version,
                },
            ))
        }
        Some(action) => anyhow::bail!("unsupported network policy action: {action}"),
        None => anyhow::bail!("network policy request missing action"),
    }
}

/// Redis transport adapter for network-policy authority wakeups.
pub struct RedisNetworkPolicyRequestSource {
    consumer: StreamConsumer,
}

impl RedisNetworkPolicyRequestSource {
    pub fn new(redis_client: redis::Client) -> Self {
        Self {
            consumer: StreamConsumer::new(redis_client, NETWORK_POLICY_REQUEST_KEY.to_string()),
        }
    }
}

#[async_trait]
impl AuthorityRequestSource<NetworkPolicyRequest> for RedisNetworkPolicyRequestSource {
    async fn next_batch(&mut self) -> Option<Vec<AuthorityRequestEnvelope<NetworkPolicyRequest>>> {
        let entries = self.consumer.next_batch().await?;
        let requests = entries
            .into_iter()
            .filter_map(|(_entry_id, fields)| {
                let source = fields
                    .iter()
                    .find(|(key, _)| key == "instance")
                    .map(|(_, value)| value.clone())
                    .unwrap_or_else(|| "unknown".to_string());
                match parse_network_policy_request(&fields) {
                    Ok(request) => Some(AuthorityRequestEnvelope { request, source }),
                    Err(error) => {
                        warn!(error = %error, "Ignoring invalid network-policy authority request");
                        None
                    }
                }
            })
            .collect::<Vec<_>>();
        (!requests.is_empty()).then_some(requests)
    }
}

#[cfg(test)]
mod network_policy_request_tests {
    use super::parse_network_policy_request;
    use crate::kernel::network_policy::NetworkPolicyAction;

    #[test]
    fn parses_exact_generation_reconcile_request() {
        let fields = vec![
            ("sandbox_id".to_string(), uuid::Uuid::now_v7().to_string()),
            ("action".to_string(), "reconcile".to_string()),
            ("policy_hash".to_string(), "hash-7".to_string()),
            ("policy_version".to_string(), "7".to_string()),
        ];

        let request = parse_network_policy_request(&fields).expect("valid request");

        assert_eq!(request.action, NetworkPolicyAction::Reconcile);
        let generation = request.generation.expect("generation");
        assert_eq!(generation.policy_hash, "hash-7");
        assert_eq!(generation.policy_version, 7);
    }

    #[test]
    fn parses_generation_fenced_remove_request() {
        let fields = vec![
            ("sandbox_id".to_string(), uuid::Uuid::now_v7().to_string()),
            ("action".to_string(), "remove".to_string()),
            ("policy_hash".to_string(), "hash-7".to_string()),
            ("policy_version".to_string(), "7".to_string()),
        ];

        let request = parse_network_policy_request(&fields).expect("valid removal request");

        assert_eq!(request.action, NetworkPolicyAction::Remove);
        let generation = request.generation.expect("removal generation");
        assert_eq!(generation.policy_hash, "hash-7");
        assert_eq!(generation.policy_version, 7);
    }

    #[test]
    fn rejects_unfenced_remove_request() {
        let fields = vec![
            ("sandbox_id".to_string(), uuid::Uuid::now_v7().to_string()),
            ("action".to_string(), "remove".to_string()),
        ];

        assert!(parse_network_policy_request(&fields).is_err());
    }

    #[test]
    fn rejects_legacy_upsert_without_generation() {
        let fields = vec![
            ("sandbox_id".to_string(), uuid::Uuid::now_v7().to_string()),
            ("action".to_string(), "upsert".to_string()),
        ];

        assert!(parse_network_policy_request(&fields).is_err());
    }
}

#[cfg(test)]
mod bridge_owner_tests {
    use std::sync::Arc;
    use std::time::Duration;

    use redis::AsyncCommands;
    use tokio::sync::mpsc;

    use super::{
        bridge_generation_key, bridge_owner_key, bridge_registration_token, BridgeStore,
        RedisBridgeStore,
    };
    use crate::ids::SandboxId;
    use crate::kernel::sandbox_bridge::SandboxBridge;

    async fn redis_client() -> Option<redis::Client> {
        let url =
            std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379/".to_string());
        let client = redis::Client::open(url).ok()?;
        let mut connection = client.get_multiplexed_async_connection().await.ok()?;
        redis::cmd("PING")
            .query_async::<String>(&mut connection)
            .await
            .ok()?;
        Some(client)
    }

    async fn wait_for_owner(
        client: &redis::Client,
        sandbox_id: SandboxId,
        expected_owner: Option<&str>,
        expected_generation: Option<&str>,
    ) {
        let owner_key = bridge_owner_key(sandbox_id.as_uuid());
        let generation_key = bridge_generation_key(sandbox_id.as_uuid());
        tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                let mut connection = client
                    .get_multiplexed_async_connection()
                    .await
                    .expect("connect to test Redis");
                let owner: Option<String> = connection.get(&owner_key).await.expect("read owner");
                let generation: Option<String> = connection
                    .get(&generation_key)
                    .await
                    .expect("read generation");
                if owner.as_deref() == expected_owner
                    && generation.as_deref() == expected_generation
                {
                    return;
                }
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        })
        .await
        .expect("Redis bridge ownership reached expected state");
    }

    async fn clear_owner(client: &redis::Client, sandbox_id: SandboxId) {
        let mut connection = client
            .get_multiplexed_async_connection()
            .await
            .expect("connect to test Redis");
        let owner_key = bridge_owner_key(sandbox_id.as_uuid());
        let generation_key = bridge_generation_key(sandbox_id.as_uuid());
        connection
            .del::<_, ()>((owner_key, generation_key))
            .await
            .expect("clear test ownership");
    }

    #[test]
    fn bridge_registration_token_versions_connections_on_the_same_instance() {
        let first = bridge_registration_token("orchestrator-a", uuid::Uuid::now_v7());
        let second = bridge_registration_token("orchestrator-a", uuid::Uuid::now_v7());

        assert!(first.starts_with("orchestrator-a\n"));
        assert_ne!(first, second);
    }

    #[test]
    fn bridge_ownership_keys_share_the_sandbox_redis_hash_tag() {
        let sandbox_id = uuid::Uuid::now_v7();
        let owner_key = bridge_owner_key(sandbox_id);
        let generation_key = bridge_generation_key(sandbox_id);
        let expected_hash_tag = format!("{{{sandbox_id}}}");

        assert_eq!(
            owner_key,
            format!("joysafeter:bridge:{expected_hash_tag}:owner")
        );
        assert_eq!(
            generation_key,
            format!("joysafeter:bridge:{expected_hash_tag}:generation")
        );
        assert!(owner_key.contains(&expected_hash_tag));
        assert!(generation_key.contains(&expected_hash_tag));
    }

    #[tokio::test]
    async fn stale_remote_connection_cannot_remove_or_refresh_replacement_owner() {
        let Some(client) = redis_client().await else {
            return;
        };
        let sandbox_id = SandboxId::new();
        clear_owner(&client, sandbox_id).await;

        let old_store = RedisBridgeStore::new(client.clone(), "orchestrator-old");
        let (old_tx, _old_rx) = mpsc::channel(1);
        let old_bridge = Arc::new(SandboxBridge::new(sandbox_id, old_tx));
        old_store.register("runtime-id".to_string(), old_bridge.clone());
        let old_generation =
            bridge_registration_token("orchestrator-old", old_bridge.connection_id());
        wait_for_owner(
            &client,
            sandbox_id,
            Some("orchestrator-old"),
            Some(&old_generation),
        )
        .await;

        let replacement_store = RedisBridgeStore::new(client.clone(), "orchestrator-new");
        let (replacement_tx, _replacement_rx) = mpsc::channel(1);
        let replacement_bridge = Arc::new(SandboxBridge::new(sandbox_id, replacement_tx));
        replacement_store.register("runtime-id".to_string(), replacement_bridge.clone());
        let replacement_generation =
            bridge_registration_token("orchestrator-new", replacement_bridge.connection_id());
        wait_for_owner(
            &client,
            sandbox_id,
            Some("orchestrator-new"),
            Some(&replacement_generation),
        )
        .await;

        assert!(old_store.remove_if_current("runtime-id", &old_bridge));
        old_store
            .heartbeat()
            .await
            .expect("stale heartbeat must be safely ignored");
        wait_for_owner(
            &client,
            sandbox_id,
            Some("orchestrator-new"),
            Some(&replacement_generation),
        )
        .await;

        assert!(replacement_store.remove_if_current("runtime-id", &replacement_bridge));
        wait_for_owner(&client, sandbox_id, None, None).await;
    }
}
