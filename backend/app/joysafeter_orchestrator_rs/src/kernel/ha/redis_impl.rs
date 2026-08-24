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
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::ids::SandboxId;
use crate::kernel::sandbox_bridge::{BridgeRegistry, SandboxBridge};

use super::dispatch::dispatch_to_bridge;
use super::stream::StreamConsumer;
use super::traits::{
    BridgeStore, DispatchCommand, NetworkPolicyAction, NetworkPolicyRequest,
    NetworkPolicyRequestQueue, TaskDispatcher,
};

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
/// Periodic PostgreSQL-to-xDS inventory reconciliation bounds how long a
/// dropped remove wakeup can leave a stale listener behind.
const XDS_AUTHORITY_INVENTORY_RECONCILE_INTERVAL: Duration = Duration::from_secs(30);

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

    fn get_by_db_id(&self, db_id: SandboxId) -> Option<Arc<SandboxBridge>> {
        self.inner.get_by_db_id(db_id)
    }

    fn remove(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        let bridge = self.inner.remove(external_id);
        if let Some(ref b) = bridge {
            let sandbox_db_id = b.sandbox_db_id.as_uuid();
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

    async fn get_owner_instance(&self, sandbox_id: SandboxId) -> Option<String> {
        let key = format!("{BRIDGE_KEY_PREFIX}{}", sandbox_id.as_uuid());
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
            let key = format!("{BRIDGE_KEY_PREFIX}{}", bridge.sandbox_db_id.as_uuid());
            pipe.cmd("EXPIRE").arg(&key).arg(BRIDGE_TTL_SECS as i64);
        }
        let results: Vec<bool> = pipe.query_async(&mut conn).await?;

        // Re-register any keys that didn't exist (EXPIRE returns false)
        let mut re_register_pipe = redis::pipe();
        let mut need_re_register = false;
        for (i, exists) in results.iter().enumerate() {
            if !exists {
                let key = format!("{BRIDGE_KEY_PREFIX}{}", bridges[i].sandbox_db_id.as_uuid());
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
        let bridge_key = format!("{BRIDGE_KEY_PREFIX}{}", sandbox_id.as_uuid());

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
                crate::db::queries::NetworkPolicyGeneration {
                    policy_hash: policy_hash.to_string(),
                    policy_version,
                },
            ))
        }
        Some("remove") => Ok(NetworkPolicyRequest::remove(sandbox_id)),
        Some(action) => anyhow::bail!("unsupported network policy action: {action}"),
        None => anyhow::bail!("network policy request missing action"),
    }
}

/// Single consumer for the elected xDS authority. All replicas observe the
/// wakeup stream, but only the replica with a recovered, advertised authority
/// epoch is allowed to touch provider-local xDS state or persist ACKs.
pub async fn xds_authority_loop(
    redis_client: redis::Client,
    pool: sqlx::PgPool,
    provider: Arc<dyn crate::sandbox::provider::SandboxProvider>,
    llm_egress_allowed_hosts: Vec<String>,
    authority: crate::kernel::xds_authority::XdsAuthorityState,
) {
    let mut consumer = StreamConsumer::new(redis_client, NETWORK_POLICY_REQUEST_KEY.to_string());
    let mut recovered_epoch = None;
    let mut last_inventory_reconcile = None;

    info!("xDS authority reconcile loop started");

    loop {
        if let Some(guard) = authority.advertised_guard() {
            if recovered_epoch != Some(guard.epoch()) {
                let _application_lock = authority.lock_application().await;
                match provider.recover_networking(&pool, &guard).await {
                    Ok(()) if authority.mark_ready(&guard) => {
                        recovered_epoch = Some(guard.epoch());
                        last_inventory_reconcile = Some(tokio::time::Instant::now());
                        info!(epoch = guard.epoch(), "xDS authority recovery completed");
                    }
                    Ok(()) => {
                        recovered_epoch = None;
                        warn!(
                            epoch = guard.epoch(),
                            "xDS authority changed during recovery"
                        );
                    }
                    Err(error) => {
                        recovered_epoch = None;
                        error!(epoch = guard.epoch(), error = %error, "xDS authority recovery failed; will retry");
                    }
                }
            }
        } else {
            recovered_epoch = None;
            last_inventory_reconcile = None;
        }

        if let Some(guard) = authority.ready_guard() {
            let elapsed = last_inventory_reconcile
                .map(|last| last.elapsed())
                .unwrap_or(XDS_AUTHORITY_INVENTORY_RECONCILE_INTERVAL);
            if should_reconcile_authority_inventory(recovered_epoch, guard.epoch(), elapsed) {
                match reconcile_authority_inventory(&pool, provider.as_ref(), &authority, &guard)
                    .await
                {
                    Ok(removed) => {
                        last_inventory_reconcile = Some(tokio::time::Instant::now());
                        if removed > 0 {
                            info!(removed, "Pruned stale xDS sandbox networking");
                        }
                    }
                    Err(error) => {
                        warn!(epoch = guard.epoch(), error = %error, "xDS authority inventory reconcile failed; will retry");
                    }
                }
            }
        }

        let Some(entries) = consumer.next_batch().await else {
            continue;
        };

        for (_entry_id, fields) in entries {
            let Some(guard) = authority.ready_guard() else {
                continue;
            };
            let request = match parse_network_policy_request(&fields) {
                Ok(request) => request,
                Err(error) => {
                    warn!(error = %error, "Ignoring invalid xDS authority request");
                    continue;
                }
            };
            let sandbox_id = request.sandbox_id;
            let source_instance = fields
                .iter()
                .find(|(key, _)| key == "instance")
                .map(|(_, value)| value.as_str())
                .unwrap_or("unknown");

            debug!(
                sandbox_id = %sandbox_id,
                action = ?request.action,
                source = source_instance,
                "xDS authority request received"
            );

            let pool = pool.clone();
            let provider = provider.clone();
            let hosts = llm_egress_allowed_hosts.clone();
            let authority = authority.clone();
            tokio::spawn(async move {
                match apply_network_policy_request_as_authority(
                    &pool,
                    provider.as_ref(),
                    request,
                    &hosts,
                    &authority,
                    &guard,
                )
                .await
                {
                    Ok(()) => {
                        debug!(sandbox_id = %sandbox_id, "xDS authority request succeeded");
                    }
                    Err(error) => {
                        debug!(sandbox_id = %sandbox_id, error = %error, "xDS authority request skipped or failed");
                    }
                }
            });
        }
    }
}

fn should_reconcile_authority_inventory(
    recovered_epoch: Option<u64>,
    current_epoch: u64,
    elapsed: Duration,
) -> bool {
    recovered_epoch == Some(current_epoch) && elapsed >= XDS_AUTHORITY_INVENTORY_RECONCILE_INTERVAL
}

async fn reconcile_authority_inventory(
    pool: &sqlx::PgPool,
    provider: &dyn crate::sandbox::provider::SandboxProvider,
    authority: &crate::kernel::xds_authority::XdsAuthorityState,
    guard: &crate::kernel::xds_authority::XdsAuthorityGuard,
) -> anyhow::Result<usize> {
    let _application_lock = authority.lock_application().await;
    if !guard.is_current() {
        anyhow::bail!("xDS authority changed before inventory reconciliation");
    }
    let live_sandbox_ids = crate::db::queries::list_live_sandboxes_for_recovery(pool)
        .await?
        .into_iter()
        .filter(|sandbox| {
            sandbox
                .config
                .as_ref()
                .and_then(|config| config.get("fingerprint"))
                .and_then(|fingerprint| fingerprint.get("networking"))
                .and_then(|networking| networking.get("type"))
                .and_then(|kind| kind.as_str())
                == Some("limited")
        })
        .map(|sandbox| sandbox.id)
        .collect();
    if !guard.is_current() {
        anyhow::bail!("xDS authority changed before inventory pruning");
    }
    provider.prune_networking(&live_sandbox_ids).await
}

async fn apply_network_policy_request_as_authority(
    pool: &sqlx::PgPool,
    provider: &dyn crate::sandbox::provider::SandboxProvider,
    request: NetworkPolicyRequest,
    llm_egress_allowed_hosts: &[String],
    authority: &crate::kernel::xds_authority::XdsAuthorityState,
    guard: &crate::kernel::xds_authority::XdsAuthorityGuard,
) -> anyhow::Result<()> {
    let _application_lock = authority.lock_application().await;
    if !guard.is_current() {
        anyhow::bail!("xDS authority changed before request application");
    }
    match request.action {
        NetworkPolicyAction::Reconcile => {
            let generation = request
                .generation
                .ok_or_else(|| anyhow!("reconcile request is missing generation"))?;
            crate::kernel::sandbox_resolver::apply_sandbox_networking_generation_as_authority(
                pool,
                provider,
                request.sandbox_id,
                &generation,
                llm_egress_allowed_hosts,
                guard,
            )
            .await?;
        }
        NetworkPolicyAction::Remove => {
            if !crate::db::queries::network_policy_removal_is_current(pool, request.sandbox_id)
                .await?
            {
                anyhow::bail!(
                    "stale xDS remove request for live limited-networking sandbox {}",
                    request.sandbox_id
                );
            }
            if !guard.is_current() {
                anyhow::bail!("xDS authority changed before networking removal");
            }
            provider.teardown_networking(request.sandbox_id).await?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod network_policy_request_tests {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::Duration;

    use async_trait::async_trait;
    use sqlx::postgres::PgPoolOptions;

    use super::{
        apply_network_policy_request_as_authority, parse_network_policy_request,
        should_reconcile_authority_inventory,
    };
    use crate::kernel::ha::{NetworkPolicyAction, NetworkPolicyRequest};
    use crate::kernel::xds_authority::XdsAuthorityState;
    use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};

    struct TeardownRecordingProvider {
        calls: AtomicUsize,
    }

    #[async_trait]
    impl SandboxProvider for TeardownRecordingProvider {
        async fn create(&self, _config: &SandboxCreateConfig) -> anyhow::Result<String> {
            Ok("unused".to_string())
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn destroy(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn status(&self, _external_id: &str) -> anyhow::Result<SandboxStatus> {
            Ok(SandboxStatus::Running)
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        fn provider_name(&self) -> &'static str {
            "teardown-recording"
        }

        async fn teardown_networking(
            &self,
            _sandbox_id: crate::ids::SandboxId,
        ) -> anyhow::Result<()> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

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
    fn rejects_legacy_upsert_without_generation() {
        let fields = vec![
            ("sandbox_id".to_string(), uuid::Uuid::now_v7().to_string()),
            ("action".to_string(), "upsert".to_string()),
        ];

        assert!(parse_network_policy_request(&fields).is_err());
    }

    #[test]
    fn authority_inventory_reconcile_runs_periodically_after_recovery() {
        assert!(!should_reconcile_authority_inventory(
            Some(7),
            7,
            Duration::from_secs(29)
        ));
        assert!(should_reconcile_authority_inventory(
            Some(7),
            7,
            Duration::from_secs(30)
        ));
        assert!(!should_reconcile_authority_inventory(
            Some(6),
            7,
            Duration::from_secs(30)
        ));
    }

    #[tokio::test]
    async fn revoked_authority_cannot_remove_networking() {
        let authority = XdsAuthorityState::managed();
        let guard = authority.advertise();
        assert!(authority.mark_ready(&guard));
        authority.revoke();
        let provider = Arc::new(TeardownRecordingProvider {
            calls: AtomicUsize::new(0),
        });
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://unused:unused@127.0.0.1:1/unused")
            .expect("lazy pool");

        let error = apply_network_policy_request_as_authority(
            &pool,
            provider.as_ref(),
            NetworkPolicyRequest::remove(crate::ids::SandboxId::from_uuid(uuid::Uuid::now_v7())),
            &[],
            &authority,
            &guard,
        )
        .await
        .expect_err("revoked authority must be fenced");

        assert!(error.to_string().contains("authority changed"));
        assert_eq!(provider.calls.load(Ordering::SeqCst), 0);
    }
}
