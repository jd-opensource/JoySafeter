use std::time::Duration;

use redis::AsyncCommands;
use tokio::sync::Mutex;
use tracing::{debug, info, warn};
use uuid::Uuid;

/// Redis-backed HA coordinator for cross-instance orchestration.
///
/// Mirrors the Python `RedisCoordinator`. Provides:
/// - Instance registry + heartbeat
/// - Sandbox ownership (which instance owns which sandbox)
/// - Task-sandbox mapping
/// - Distributed locks (NX set + Lua CAS release)
/// - Pub/sub event publishing
/// - Cross-instance command dispatch
pub struct RedisCoordinator {
    client: redis::Client,
    instance_id: String,
    heartbeat_interval: Duration,
    heartbeat_ttl: Duration,
    _heartbeat_handle: Mutex<Option<tokio::task::JoinHandle<()>>>,
}

impl RedisCoordinator {
    pub fn new(
        client: redis::Client,
        instance_id: &str,
        heartbeat_interval: u64,
        heartbeat_ttl: u64,
    ) -> Self {
        Self {
            client,
            instance_id: instance_id.to_string(),
            heartbeat_interval: Duration::from_secs(heartbeat_interval),
            heartbeat_ttl: Duration::from_secs(heartbeat_ttl),
            _heartbeat_handle: Mutex::new(None),
        }
    }

    pub fn instance_id(&self) -> &str {
        &self.instance_id
    }

    async fn get_conn(&self) -> Result<redis::aio::MultiplexedConnection, redis::RedisError> {
        self.client.get_multiplexed_async_connection().await
    }

    // -----------------------------------------------------------------------
    // Instance registry
    // -----------------------------------------------------------------------

    /// Register this instance in the Redis instance set.
    /// Stores hash with grpc_addr/http_addr/started_at matching Python L39-53.
    pub async fn register_instance(&self) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:instances:{}", self.instance_id);
        // Store as hash with metadata (matching Python L44-50)
        redis::cmd("HSET")
            .arg(&key)
            .arg("grpc_addr")
            .arg("")
            .arg("http_addr")
            .arg("")
            .arg("started_at")
            .arg(chrono::Utc::now().timestamp().to_string())
            .query_async::<()>(&mut conn)
            .await?;
        conn.expire::<_, ()>(&key, 30).await?;
        info!(instance_id = %self.instance_id, "Registered instance in Redis");
        Ok(())
    }

    /// Spawn a background heartbeat task.
    pub fn spawn_heartbeat(&self) -> tokio::task::JoinHandle<()> {
        let client = self.client.clone();
        let instance_id = self.instance_id.clone();
        let interval = self.heartbeat_interval;
        let ttl = self.heartbeat_ttl;

        tokio::spawn(async move {
            loop {
                tokio::time::sleep(interval).await;
                match client.get_multiplexed_async_connection().await {
                    Ok(mut conn) => {
                        let key = format!("joysafeter:instances:{instance_id}");
                        // M-NEW-8 fix: use config TTL instead of hardcoded 30
                        if let Err(e) = conn.expire::<_, ()>(&key, ttl.as_secs() as i64).await {
                            warn!("Heartbeat failed: {e}");
                        }
                    }
                    Err(e) => {
                        warn!("Heartbeat Redis connection failed: {e}");
                    }
                }
            }
        })
    }

    /// Deregister this instance.
    pub async fn deregister_instance(&self) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:instances:{}", self.instance_id);
        conn.del::<_, ()>(&key).await?;
        info!(instance_id = %self.instance_id, "Deregistered instance from Redis");
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Sandbox ownership
    // -----------------------------------------------------------------------

    /// Register ownership of a sandbox (always sets, for initial registration).
    pub async fn register_sandbox(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{sandbox_id}");
        conn.set_ex::<_, _, ()>(&key, &self.instance_id, 300)
            .await?;
        Ok(())
    }

    /// Claim ownership of a sandbox (NX — only if not already owned).
    /// Returns true if claim succeeded.
    pub async fn claim_sandbox_owner(&self, sandbox_id: Uuid) -> anyhow::Result<bool> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{sandbox_id}");
        let result: bool = redis::cmd("SET")
            .arg(&key)
            .arg(&self.instance_id)
            .arg("NX")
            .arg("EX")
            .arg(300)
            .query_async(&mut conn)
            .await
            .unwrap_or(false);
        Ok(result)
    }

    /// Refresh sandbox ownership TTL (CAS — only if we own it).
    pub async fn refresh_sandbox(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{sandbox_id}");
        // Lua CAS: only refresh if value matches our instance_id
        let script = r#"
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("expire", KEYS[1], ARGV[2])
            else
                return 0
            end
        "#;
        let _: i32 = redis::Script::new(script)
            .key(&key)
            .arg(&self.instance_id)
            .arg(300)
            .invoke_async(&mut conn)
            .await?;
        Ok(())
    }

    /// Remove sandbox ownership (CAS — only if we own it, matching Python L90-94).
    pub async fn remove_sandbox(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{sandbox_id}");
        let script = r#"
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
        "#;
        let _: i32 = redis::Script::new(script)
            .key(&key)
            .arg(&self.instance_id)
            .invoke_async(&mut conn)
            .await?;
        Ok(())
    }

    /// Check which instance owns a sandbox.
    pub async fn get_sandbox_owner(&self, sandbox_id: Uuid) -> anyhow::Result<Option<String>> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{sandbox_id}");
        let owner: Option<String> = conn.get(&key).await?;
        Ok(owner)
    }

    // -----------------------------------------------------------------------
    // Task-sandbox mapping
    // -----------------------------------------------------------------------

    /// Map a task to a sandbox.
    pub async fn map_task_to_sandbox(&self, task_id: Uuid, sandbox_id: Uuid) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:task_sandbox:{task_id}");
        conn.set_ex::<_, _, ()>(&key, sandbox_id.to_string(), 7200) // 2h TTL
            .await?;
        Ok(())
    }

    /// Get the sandbox for a task.
    pub async fn get_task_sandbox(&self, task_id: Uuid) -> anyhow::Result<Option<Uuid>> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:task_sandbox:{task_id}");
        let val: Option<String> = conn.get(&key).await?;
        Ok(val.and_then(|s| s.parse().ok()))
    }

    /// Remove task-sandbox mapping.
    pub async fn remove_task_sandbox(&self, task_id: Uuid) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:task_sandbox:{task_id}");
        conn.del::<_, ()>(&key).await?;
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Distributed locks
    // -----------------------------------------------------------------------

    /// Try to acquire a distributed lock. Returns true if acquired.
    pub async fn try_lock(&self, lock_name: &str, ttl_secs: u64) -> anyhow::Result<bool> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:lock:{lock_name}");
        let result: bool = redis::cmd("SET")
            .arg(&key)
            .arg(&self.instance_id)
            .arg("NX")
            .arg("EX")
            .arg(ttl_secs)
            .query_async(&mut conn)
            .await
            .unwrap_or(false);
        Ok(result)
    }

    /// Release a distributed lock (CAS — only if we own it).
    pub async fn unlock(&self, lock_name: &str) -> anyhow::Result<bool> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:lock:{lock_name}");
        // Lua CAS: only delete if value matches our instance_id
        let script = r#"
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
        "#;
        let result: i32 = redis::Script::new(script)
            .key(&key)
            .arg(&self.instance_id)
            .invoke_async(&mut conn)
            .await?;
        Ok(result == 1)
    }

    // -----------------------------------------------------------------------
    // Pub/sub publishing
    // -----------------------------------------------------------------------

    /// Publish an event to a per-task channel.
    /// Python L159: directly publishes the payload string (no wrapper).
    pub async fn publish_task_event(&self, task_id: Uuid, payload: &str) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let channel = format!("joysafeter:events:{task_id}");
        conn.publish::<_, _, ()>(&channel, payload).await?;
        Ok(())
    }

    /// Publish an event to a per-session channel.
    /// Note: session events use the wrapper format (source_instance + event)
    /// because SessionBroadcaster subscribes and filters by source_instance.
    pub async fn publish_session_event(
        &self,
        session_id: Uuid,
        event: &serde_json::Value,
    ) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let channel = format!("joysafeter:session_events:{session_id}");
        let payload = serde_json::json!({
            "source_instance": self.instance_id,
            "event": event,
        });
        conn.publish::<_, _, ()>(&channel, serde_json::to_string(&payload)?)
            .await?;
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Cross-instance command dispatch
    // -----------------------------------------------------------------------

    /// Send a command to a specific instance (for cancel/input relay).
    pub async fn send_command(
        &self,
        target_instance: &str,
        command: &serde_json::Value,
    ) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let channel = format!("joysafeter:cmd:{target_instance}");
        conn.publish::<_, _, ()>(&channel, serde_json::to_string(command)?)
            .await?;
        debug!(target = target_instance, "Sent cross-instance command");
        Ok(())
    }

    /// Send a cancel command for a task to the instance that owns it.
    pub async fn dispatch_cancel(
        &self,
        task_id: Uuid,
        sandbox_id: Uuid,
        reason: &str,
    ) -> anyhow::Result<()> {
        let cmd = serde_json::json!({
            "type": "cancel",
            "sandbox_id": sandbox_id.to_string(),
            "task_id": task_id.to_string(),
            "reason": reason,
        });
        for target in self.list_instance_ids().await? {
            if target == self.instance_id {
                continue;
            }
            if let Err(e) = self.send_command(&target, &cmd).await {
                tracing::warn!(target = %target, "dispatch_cancel failed: {e}");
            }
        }
        Ok(())
    }

    /// Send an input command for HITL confirmation.
    pub async fn dispatch_input(&self, sandbox_id: Uuid, content: &str) -> anyhow::Result<()> {
        let cmd = serde_json::json!({
            "type": "input",
            "sandbox_id": sandbox_id.to_string(),
            "content": content,
        });
        for target in self.list_instance_ids().await? {
            if target == self.instance_id {
                continue;
            }
            if let Err(e) = self.send_command(&target, &cmd).await {
                tracing::warn!(target = %target, "dispatch_input failed: {e}");
            }
        }
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Cleanup
    // -----------------------------------------------------------------------

    /// Graceful stop: deregister + cancel heartbeat.
    pub async fn stop(&self) -> anyhow::Result<()> {
        let handle = self._heartbeat_handle.lock().await.take();
        if let Some(h) = handle {
            h.abort();
        }
        self.deregister_instance().await?;
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Additional methods for full Python parity
    // -----------------------------------------------------------------------

    /// List all active sandbox owners (SCAN operation).
    pub async fn list_active_sandbox_owners(&self) -> anyhow::Result<Vec<(Uuid, String)>> {
        let mut conn = self.get_conn().await?;
        let mut results = Vec::new();
        let mut cursor = 0u64;

        loop {
            let (new_cursor, keys): (u64, Vec<String>) = redis::cmd("SCAN")
                .arg(cursor)
                .arg("MATCH")
                .arg("joysafeter:sandbox_owner:*")
                .arg("COUNT")
                .arg(100)
                .query_async(&mut conn)
                .await?;

            for key in keys {
                let sandbox_id_str = key.strip_prefix("joysafeter:sandbox_owner:").unwrap_or("");
                if let Ok(sandbox_id) = sandbox_id_str.parse::<Uuid>() {
                    let owner: Option<String> = conn.get(&key).await.unwrap_or(None);
                    if let Some(owner) = owner {
                        results.push((sandbox_id, owner));
                    }
                }
            }

            cursor = new_cursor;
            if cursor == 0 {
                break;
            }
        }

        Ok(results)
    }

    /// List all active instance IDs from the registry.
    pub async fn list_instance_ids(&self) -> anyhow::Result<Vec<String>> {
        let mut conn = self.get_conn().await?;
        let mut results = Vec::new();
        let mut cursor = 0u64;

        loop {
            let (new_cursor, keys): (u64, Vec<String>) = redis::cmd("SCAN")
                .arg(cursor)
                .arg("MATCH")
                .arg("joysafeter:instances:*")
                .arg("COUNT")
                .arg(100)
                .query_async(&mut conn)
                .await?;

            for key in keys {
                if let Some(instance_id) = key.strip_prefix("joysafeter:instances:") {
                    results.push(instance_id.to_string());
                }
            }

            cursor = new_cursor;
            if cursor == 0 {
                break;
            }
        }

        Ok(results)
    }

    /// Check if Redis is healthy (PING).
    pub async fn is_healthy(&self) -> bool {
        match self.get_conn().await {
            Ok(mut conn) => {
                let result: Result<String, _> = redis::cmd("PING").query_async(&mut conn).await;
                result.map(|r| r == "PONG").unwrap_or(false)
            }
            Err(_) => false,
        }
    }

    /// Remove sandbox queue wakeup key.
    pub async fn remove_sandbox_queue(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");
        conn.del::<_, ()>(&key).await?;
        Ok(())
    }

    /// Push to sandbox queue (SET wakeup key + PUBLISH signal).
    pub async fn push_to_sandbox_queue(
        &self,
        sandbox_id: Uuid,
        task_id: Uuid,
    ) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");
        let channel = format!("joysafeter:sandbox_wakeup_channel:{sandbox_id}");
        // Pipeline: SET "1" EX 60 + PUBLISH "1" (matching Python L211-215)
        redis::pipe()
            .cmd("SET")
            .arg(&key)
            .arg("1")
            .arg("EX")
            .arg(60)
            .publish(&channel, "1")
            .query_async::<()>(&mut conn)
            .await?;
        Ok(())
    }

    /// Pop from sandbox queue (check SET key, then subscribe for signal).
    pub async fn pop_from_sandbox_queue(
        &self,
        sandbox_id: Uuid,
        timeout: std::time::Duration,
    ) -> anyhow::Result<Option<Uuid>> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");

        // First check if there's already a wakeup key
        let val: Option<String> = conn.get(&key).await?;
        if val.is_some() {
            // Consume the key
            conn.del::<_, ()>(&key).await?;
            return Ok(Some(sandbox_id));
        }

        // Subscribe and wait for signal
        let channel = format!("joysafeter:sandbox_wakeup_channel:{sandbox_id}");
        let mut pubsub = self.client.get_async_pubsub().await?;
        pubsub.subscribe(&channel).await?;

        let result = tokio::time::timeout(timeout, async {
            use futures::StreamExt;
            pubsub.on_message().next().await
        })
        .await;

        if result.is_ok() {
            // Check the key again after signal
            let mut conn = self.get_conn().await?;
            let val: Option<String> = conn.get(&key).await?;
            if val.is_some() {
                conn.del::<_, ()>(&key).await?;
                return Ok(Some(sandbox_id));
            }
        }

        Ok(None)
    }

    /// Push to global queue.
    pub async fn push_to_global_queue(&self, task_id: Uuid) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        conn.rpush::<_, _, ()>("joysafeter:global_queue", task_id.to_string())
            .await?;
        Ok(())
    }

    /// Pop from global queue (blocking with timeout).
    pub async fn pop_from_global_queue(
        &self,
        timeout: std::time::Duration,
    ) -> anyhow::Result<Option<Uuid>> {
        let mut conn = self.get_conn().await?;
        let result: Option<(String, String)> = redis::cmd("BLPOP")
            .arg("joysafeter:global_queue")
            .arg(timeout.as_secs())
            .query_async(&mut conn)
            .await?;

        Ok(result.and_then(|(_, val)| val.parse().ok()))
    }

    /// Drain sandbox queue (delete wakeup key).
    pub async fn drain_sandbox_queue(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.remove_sandbox_queue(sandbox_id).await
    }
}
