use std::time::Duration;

use crate::ids::{SandboxId, TaskId};
use redis::AsyncCommands;
use tokio::sync::Mutex;
use tracing::{info, warn};

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
    pub async fn register_sandbox(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{}", sandbox_id.as_uuid());
        conn.set_ex::<_, _, ()>(&key, &self.instance_id, 300)
            .await?;
        Ok(())
    }

    /// Refresh sandbox ownership TTL (CAS — only if we own it).
    pub async fn refresh_sandbox(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{}", sandbox_id.as_uuid());
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
    pub async fn remove_sandbox(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{}", sandbox_id.as_uuid());
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
    pub async fn get_sandbox_owner(&self, sandbox_id: SandboxId) -> anyhow::Result<Option<String>> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_owner:{}", sandbox_id.as_uuid());
        let owner: Option<String> = conn.get(&key).await?;
        Ok(owner)
    }

    // -----------------------------------------------------------------------
    // Task-sandbox mapping
    // -----------------------------------------------------------------------

    /// Map a task to a sandbox.
    pub async fn map_task_to_sandbox(
        &self,
        task_id: TaskId,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:task_sandbox:{}", task_id.as_uuid());
        conn.set_ex::<_, _, ()>(&key, sandbox_id.as_uuid().to_string(), 7200) // 2h TTL
            .await?;
        Ok(())
    }

    /// Remove task-sandbox mapping.
    pub async fn remove_task_sandbox(&self, task_id: TaskId) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:task_sandbox:{}", task_id.as_uuid());
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
    pub async fn publish_task_event(&self, task_id: TaskId, payload: &str) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let channel = format!("joysafeter:events:{}", task_id.as_uuid());
        conn.publish::<_, _, ()>(&channel, payload).await?;
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

    /// Remove sandbox queue wakeup key.
    pub async fn remove_sandbox_queue(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let mut conn = self.get_conn().await?;
        let key = format!("joysafeter:sandbox_wakeup:{}", sandbox_id.as_uuid());
        conn.del::<_, ()>(&key).await?;
        Ok(())
    }
}
