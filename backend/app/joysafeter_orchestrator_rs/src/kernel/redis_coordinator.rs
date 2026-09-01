use std::sync::Arc;

use crate::ids::{SandboxId, TaskId};
use crate::kernel::instance_registry::RedisInstanceRegistry;
use redis::AsyncCommands;

/// Redis-backed HA coordinator for cross-instance orchestration.
///
/// Mirrors the Python `RedisCoordinator`. Provides:
/// - Instance registry + heartbeat
/// - Task-sandbox mapping
/// - Distributed locks (NX set + Lua CAS release)
/// - Pub/sub event publishing
/// - Cross-instance command dispatch
pub struct RedisCoordinator {
    client: redis::Client,
    instance_id: String,
    instance_registry: Arc<RedisInstanceRegistry>,
}

impl RedisCoordinator {
    pub fn new(
        client: redis::Client,
        instance_id: &str,
        heartbeat_interval: u64,
        heartbeat_ttl: u64,
    ) -> Self {
        let instance_registry = Arc::new(RedisInstanceRegistry::new(
            client.clone(),
            instance_id,
            heartbeat_interval,
            heartbeat_ttl,
        ));
        Self {
            client,
            instance_id: instance_id.to_string(),
            instance_registry,
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
        self.instance_registry.register().await
    }

    /// Spawn a background heartbeat task.
    pub fn spawn_heartbeat(&self) -> tokio::task::JoinHandle<()> {
        tokio::spawn(self.instance_registry.clone().run())
    }

    /// Deregister this instance.
    pub async fn deregister_instance(&self) -> anyhow::Result<()> {
        self.instance_registry.deregister().await
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
