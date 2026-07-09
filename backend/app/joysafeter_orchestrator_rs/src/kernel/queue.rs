use std::time::Duration;

use anyhow::{anyhow, bail};
use redis::AsyncCommands;
use tracing::error;
use uuid::Uuid;

const GLOBAL_QUEUE_KEY: &str = "joysafeter:global_queue";

/// Redis-backed runtime queue.
///
/// The database remains the source of truth for task state. Redis carries
/// scheduler candidate task IDs and sandbox wakeup signals. There is
/// intentionally no process-local task fallback: a local queue would strand
/// work on one orchestrator instance and diverge from the API enqueue contract.
#[derive(Clone)]
pub struct TaskQueue {
    redis_client: redis::Client,
}

impl TaskQueue {
    pub fn new(redis_client: redis::Client) -> Self {
        Self { redis_client }
    }

    fn parse_task_id(raw: &str) -> anyhow::Result<Uuid> {
        raw.parse::<Uuid>()
            .map_err(|e| anyhow!("invalid task id in Redis global queue: {raw}: {e}"))
    }

    /// Push a sandbox wakeup signal after a task has been attached in DB.
    pub async fn push(&self, sandbox_id: Uuid, task_id: Uuid) -> anyhow::Result<()> {
        let client = &self.redis_client;
        let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");
        let channel = format!("joysafeter:sandbox_wakeup_channel:{sandbox_id}");

        for attempt in 0..3u32 {
            match client.get_multiplexed_async_connection().await {
                Ok(mut conn) => {
                    let r1 = redis::cmd("SET")
                        .arg(&key)
                        .arg(task_id.to_string())
                        .arg("EX")
                        .arg(60)
                        .query_async::<()>(&mut conn)
                        .await;
                    let r2 = conn
                        .publish::<_, _, ()>(&channel, task_id.to_string())
                        .await;
                    if r1.is_ok() && r2.is_ok() {
                        return Ok(());
                    }

                    let delay_ms = 500 * 2u64.pow(attempt);
                    error!(
                        sandbox_id = %sandbox_id,
                        task_id = %task_id,
                        attempt = attempt + 1,
                        "Redis sandbox wakeup failed, retrying in {delay_ms}ms"
                    );
                    tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                }
                Err(e) => {
                    let delay_ms = 500 * 2u64.pow(attempt);
                    error!(
                        sandbox_id = %sandbox_id,
                        task_id = %task_id,
                        attempt = attempt + 1,
                        "Redis connection failed for sandbox wakeup: {e}, retrying in {delay_ms}ms"
                    );
                    tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                }
            }
        }

        bail!("Redis sandbox wakeup failed after retries for sandbox {sandbox_id}");
    }

    /// Push to the global scheduler queue.
    pub async fn push_to_global(&self, task_id: Uuid) -> anyhow::Result<()> {
        let client = &self.redis_client;
        for attempt in 0..3u32 {
            match client.get_multiplexed_async_connection().await {
                Ok(mut conn) => {
                    match conn
                        .rpush::<_, _, ()>(GLOBAL_QUEUE_KEY, task_id.to_string())
                        .await
                    {
                        Ok(_) => return Ok(()),
                        Err(e) => {
                            let delay_ms = 500 * 2u64.pow(attempt);
                            error!(
                                task_id = %task_id,
                                attempt = attempt + 1,
                                "Redis push_to_global failed: {e}, retrying in {delay_ms}ms"
                            );
                            tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                        }
                    }
                }
                Err(e) => {
                    let delay_ms = 500 * 2u64.pow(attempt);
                    error!(
                        task_id = %task_id,
                        attempt = attempt + 1,
                        "Redis connection failed for global queue push: {e}, retrying in {delay_ms}ms"
                    );
                    tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                }
            }
        }

        bail!("Redis push_to_global failed after retries for task {task_id}");
    }

    /// Pop one task candidate from Redis, blocking up to `timeout`.
    pub async fn pop_from_global(&self, timeout: Duration) -> anyhow::Result<Option<Uuid>> {
        let mut conn = self.redis_client.get_multiplexed_async_connection().await?;
        let result: Option<(String, String)> = redis::cmd("BLPOP")
            .arg(GLOBAL_QUEUE_KEY)
            .arg(timeout.as_secs())
            .query_async(&mut conn)
            .await?;

        match result {
            Some((_key, val)) => Self::parse_task_id(&val).map(Some),
            None => Ok(None),
        }
    }

    /// Drain one immediately available task candidate without blocking.
    pub async fn try_pop_from_global(&self) -> anyhow::Result<Option<Uuid>> {
        let mut conn = self.redis_client.get_multiplexed_async_connection().await?;
        let val: Option<String> = redis::cmd("LPOP")
            .arg(GLOBAL_QUEUE_KEY)
            .query_async(&mut conn)
            .await?;

        match val {
            Some(val) => Self::parse_task_id(&val).map(Some),
            None => Ok(None),
        }
    }

    /// Remove Redis wakeup state for a sandbox.
    pub async fn drain(&self, sandbox_id: Uuid) -> Vec<Uuid> {
        self.drain_sandbox_redis(sandbox_id).await;
        vec![]
    }

    pub async fn drain_sandbox_redis(&self, sandbox_id: Uuid) {
        if let Ok(mut conn) = self.redis_client.get_multiplexed_async_connection().await {
            let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");
            let _ = conn.del::<_, ()>(&key).await;
        }
    }
}
