//! Redis-backed implementations for `multi` HA mode.
//!
//! Provides:
//! - [`RedisBridgeStore`]: local DashMap cache + Redis key registration with TTL
//! - [`RedisTaskDispatcher`]: local-first dispatch, cross-instance via Redis Streams
//! - [`RedisXdsStateStore`]: xDS change notification via Redis Stream
//! - Background loops: inbox consumer, bridge heartbeat, xDS notify consumer

use std::sync::Arc;
use std::time::Duration;

use anyhow::anyhow;
use async_trait::async_trait;
use redis::AsyncCommands;
use serde_json::json;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::kernel::sandbox_bridge::{BridgeRegistry, SandboxBridge};

use super::dispatch::dispatch_to_bridge;
use super::stream::StreamConsumer;
use super::traits::{BridgeStore, DispatchCommand, TaskDispatcher, XdsAction, XdsStateStore};

// ---------------------------------------------------------------------------
// Redis key constants
// ---------------------------------------------------------------------------

/// Bridge ownership: maps sandbox_db_id → instance_id. TTL-based liveness.
const BRIDGE_KEY_PREFIX: &str = "joysafeter:bridge:";
/// Per-instance inbox stream for cross-instance command relay.
const INBOX_KEY_PREFIX: &str = "joysafeter:inbox:";
/// xDS change notification stream (shared across all instances).
const XDS_NOTIFY_KEY: &str = "joysafeter:xds:notify";

/// Bridge key TTL in seconds. Refreshed by heartbeat every 30s.
const BRIDGE_TTL_SECS: u64 = 60;
/// Inbox stream max length (approximate trim).
const INBOX_MAXLEN: usize = 1000;
/// xDS notify stream max length (approximate trim).
const XDS_NOTIFY_MAXLEN: usize = 1000;

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
        let sandbox_db_id = bridge.sandbox_db_id;
        // Local cache (immediate, sync)
        self.inner.register(external_id, bridge);

        // Redis registration (fire-and-forget async)
        let client = self.redis_client.clone();
        let instance_id = self.instance_id.clone();
        tokio::spawn(async move {
            match client.get_multiplexed_async_connection().await {
                Ok(mut conn) => {
                    let key = format!("{BRIDGE_KEY_PREFIX}{sandbox_db_id}");
                    if let Err(e) = conn
                        .set_ex::<_, _, ()>(&key, &instance_id, BRIDGE_TTL_SECS)
                        .await
                    {
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

    fn get_by_db_id(&self, db_id: Uuid) -> Option<Arc<SandboxBridge>> {
        self.inner.get_by_db_id(db_id)
    }

    fn remove(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        let bridge = self.inner.remove(external_id);
        if let Some(ref b) = bridge {
            let sandbox_db_id = b.sandbox_db_id;
            let client = self.redis_client.clone();
            tokio::spawn(async move {
                if let Ok(mut conn) = client.get_multiplexed_async_connection().await {
                    let key = format!("{BRIDGE_KEY_PREFIX}{sandbox_db_id}");
                    let _ = conn.del::<_, ()>(&key).await;
                }
            });
        }
        bridge
    }

    fn all_bridges(&self) -> Vec<Arc<SandboxBridge>> {
        self.inner.all_bridges()
    }

    async fn shutdown_all(&self) {
        self.inner.shutdown_all().await;
    }

    async fn get_owner_instance(&self, sandbox_id: Uuid) -> Option<String> {
        let key = format!("{BRIDGE_KEY_PREFIX}{sandbox_id}");
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

        // Pipeline all EXPIRE commands in one RTT (200 bridges → ~3ms instead of ~200ms)
        let mut pipe = redis::pipe();
        for bridge in &bridges {
            let key = format!("{BRIDGE_KEY_PREFIX}{}", bridge.sandbox_db_id);
            pipe.cmd("EXPIRE").arg(&key).arg(BRIDGE_TTL_SECS as i64);
        }
        let results: Vec<bool> = pipe.query_async(&mut conn).await?;

        // Re-register any keys that didn't exist (EXPIRE returns false)
        let mut re_register_pipe = redis::pipe();
        let mut need_re_register = false;
        for (i, exists) in results.iter().enumerate() {
            if !exists {
                let key = format!("{BRIDGE_KEY_PREFIX}{}", bridges[i].sandbox_db_id);
                re_register_pipe
                    .cmd("SET")
                    .arg(&key)
                    .arg(&self.instance_id)
                    .arg("EX")
                    .arg(BRIDGE_TTL_SECS);
                need_re_register = true;
            }
        }
        if need_re_register {
            let _: Vec<redis::Value> = re_register_pipe.query_async(&mut conn).await?;
        }

        debug!(total = bridges.len(), "Bridge heartbeat complete (pipeline)");
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
    owner_cache: dashmap::DashMap<Uuid, (String, std::time::Instant)>,
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
        sandbox_id: Uuid,
        command: DispatchCommand,
    ) -> anyhow::Result<()> {
        // Fast path: try local bridge first (zero Redis RTT)
        if let Some(bridge) = self.bridge_store.get_by_db_id(sandbox_id) {
            return dispatch_to_bridge(&bridge, sandbox_id, &command).await;
        }

        // Slow path: look up owner instance (cached locally, fallback to Redis)
        let mut conn = self.get_conn().await?;

        // Check local owner cache first (avoids Redis GET on repeated dispatches)
        let target = if let Some(entry) = self.owner_cache.get(&sandbox_id) {
            let (ref cached_owner, cached_at) = *entry;
            if cached_at.elapsed() < OWNER_CACHE_TTL {
                cached_owner.clone()
            } else {
                drop(entry);
                self.owner_cache.remove(&sandbox_id);
                let bridge_key = format!("{BRIDGE_KEY_PREFIX}{sandbox_id}");
                let owner: Option<String> = conn.get(&bridge_key).await?;
                match owner {
                    Some(o) => {
                        self.owner_cache.insert(sandbox_id, (o.clone(), std::time::Instant::now()));
                        o
                    }
                    None => {
                        return Err(anyhow!("sandbox {sandbox_id} not registered on any instance"));
                    }
                }
            }
        } else {
            let bridge_key = format!("{BRIDGE_KEY_PREFIX}{sandbox_id}");
            let owner: Option<String> = conn.get(&bridge_key).await?;
            match owner {
                Some(o) => {
                    self.owner_cache.insert(sandbox_id, (o.clone(), std::time::Instant::now()));
                    o
                }
                None => {
                    return Err(anyhow!("sandbox {sandbox_id} not registered on any instance"));
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
            DispatchCommand::Cancel { reason } => {
                ("cancel", json!({"reason": reason}))
            }
            DispatchCommand::SendInput { content } => {
                ("send_input", json!({"content": content}))
            }
            DispatchCommand::Shutdown { reason } => {
                ("shutdown", json!({"reason": reason}))
            }
            DispatchCommand::TaskWakeup => {
                ("task_wakeup", json!({}))
            }
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
            .arg(sandbox_id.to_string())
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
// RedisXdsStateStore
// ---------------------------------------------------------------------------

/// xDS state notification via Redis Stream.
///
/// Notifies other instances when a listener is added/removed so they can update
/// their local Envoy DaemonSet connections.
pub struct RedisXdsStateStore {
    redis_client: redis::Client,
    instance_id: String,
}

impl RedisXdsStateStore {
    pub fn new(redis_client: redis::Client, instance_id: &str) -> Self {
        Self {
            redis_client,
            instance_id: instance_id.to_string(),
        }
    }
}

#[async_trait]
impl XdsStateStore for RedisXdsStateStore {
    async fn notify_change(&self, sandbox_id: Uuid, action: XdsAction) -> anyhow::Result<()> {
        let mut conn = self
            .redis_client
            .get_multiplexed_async_connection()
            .await
            .map_err(|e| anyhow!("Redis connection failed for xDS notify: {e}"))?;

        let action_str = match action {
            XdsAction::Upsert => "upsert",
            XdsAction::Remove => "remove",
        };

        redis::cmd("XADD")
            .arg(XDS_NOTIFY_KEY)
            .arg("MAXLEN")
            .arg("~")
            .arg(XDS_NOTIFY_MAXLEN)
            .arg("*")
            .arg("sandbox_id")
            .arg(sandbox_id.to_string())
            .arg("action")
            .arg(action_str)
            .arg("instance")
            .arg(&self.instance_id)
            .query_async::<String>(&mut conn)
            .await?;

        debug!(
            sandbox_id = %sandbox_id,
            action = action_str,
            "Published xDS notify"
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
async fn handle_inbox_message(
    bridge_store: &Arc<dyn BridgeStore>,
    fields: &[(String, String)],
) {
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

    let sandbox_id: Uuid = match sandbox_id_str.parse() {
        Ok(id) => id,
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

/// xDS notify consumer loop: reads change notifications and triggers local
/// Envoy xDS updates for sandboxes managed by other instances.
///
/// When a peer instance pushes a new listener, this loop immediately reconciles
/// the sandbox's networking on the local Envoy — no 15s wait for the reconcile
/// tick. This eliminates the 503 window for sandboxes on other nodes.
pub async fn xds_notify_consumer_loop(
    redis_client: redis::Client,
    instance_id: String,
    pool: sqlx::PgPool,
    provider: Arc<dyn crate::sandbox::provider::SandboxProvider>,
    llm_egress_allowed_hosts: Vec<String>,
) {
    let mut consumer = StreamConsumer::new(redis_client, XDS_NOTIFY_KEY.to_string());

    info!("xDS notify consumer loop started");

    loop {
        let Some(entries) = consumer.next_batch().await else {
            continue;
        };

        for (_entry_id, fields) in entries {
            let mut source_instance = "";
            let mut sandbox_id_str = "";
            let mut action = "";

            for (key, value) in &fields {
                match key.as_str() {
                    "instance" => source_instance = value,
                    "sandbox_id" => sandbox_id_str = value,
                    "action" => action = value,
                    _ => {}
                }
            }

            // Skip our own notifications
            if source_instance == instance_id {
                continue;
            }

            let sandbox_id: Uuid = match sandbox_id_str.parse() {
                Ok(id) => id,
                Err(_) => continue,
            };

            debug!(
                sandbox_id = %sandbox_id,
                action = action,
                source = source_instance,
                "xDS notify received from peer — triggering local reconcile"
            );

            match action {
                "upsert" => {
                    let pool = pool.clone();
                    let provider = provider.clone();
                    let hosts = llm_egress_allowed_hosts.clone();
                    tokio::spawn(async move {
                        if let Ok(Some(sandbox)) =
                            crate::db::queries::get_sandbox(&pool, sandbox_id).await
                        {
                            match crate::kernel::sandbox_resolver::reconcile_sandbox_networking(
                                &pool,
                                provider.as_ref(),
                                &sandbox,
                                &hosts,
                                None,
                            )
                            .await
                            {
                                Ok(_) => {
                                    debug!(sandbox_id = %sandbox_id, "xDS notify: reconcile succeeded");
                                }
                                Err(e) => {
                                    debug!(sandbox_id = %sandbox_id, "xDS notify: reconcile failed (will retry): {e}");
                                }
                            }
                        }
                    });
                }
                "remove" => {
                    let provider = provider.clone();
                    tokio::spawn(async move {
                        if let Err(e) = provider.teardown_networking(sandbox_id).await {
                            debug!(sandbox_id = %sandbox_id, "xDS notify: teardown failed: {e}");
                        }
                    });
                }
                _ => {}
            }
        }
    }
}

