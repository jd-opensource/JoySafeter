use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Duration;

use redis::AsyncCommands;
use tokio::sync::Mutex;
use uuid::Uuid;

/// Task queue with in-memory primary + optional Redis for HA.
///
/// Full parity with Python `InMemoryRedisQueueBackend`:
/// - Per-sandbox queues (in-memory)
/// - Global queue (Redis rpush/blpop or in-memory fallback)
/// - Per-sandbox wakeup signal (Redis SET+PUBLISH or Notify)
#[derive(Clone)]
pub struct TaskQueue {
    /// Maps sandbox DB ID → wakeup tokens. Task dispatch itself is DB-driven.
    queues: Arc<Mutex<std::collections::HashMap<Uuid, VecDeque<Uuid>>>>,
    /// Global queue (in-memory fallback).
    global: Arc<Mutex<VecDeque<Uuid>>>,
    /// Global queue notification.
    global_notify: Arc<tokio::sync::Notify>,
    /// Redis client for HA queue operations.
    redis_client: Option<redis::Client>,
}

impl TaskQueue {
    pub fn new() -> Self {
        Self {
            queues: Arc::new(Mutex::new(std::collections::HashMap::new())),
            global: Arc::new(Mutex::new(VecDeque::new())),
            global_notify: Arc::new(tokio::sync::Notify::new()),
            redis_client: None,
        }
    }

    pub fn with_redis(mut self, client: redis::Client) -> Self {
        self.redis_client = Some(client);
        self
    }

    /// Push a task ID onto a sandbox's queue and send wakeup signal.
    /// Redis push retries 3 times with backoff (matching Python L154-171).
    pub async fn push(&self, sandbox_id: Uuid, task_id: Uuid) {
        self.signal_sandbox(sandbox_id).await;

        // Redis wakeup signal: SET + PUBLISH with retry
        if let Some(ref client) = self.redis_client {
            let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");
            let channel = format!("joysafeter:sandbox_wakeup_channel:{sandbox_id}");
            for attempt in 0..3u32 {
                match client.get_multiplexed_async_connection().await {
                    Ok(mut conn) => {
                        let r1 = redis::cmd("SET")
                            .arg(&key)
                            .arg("1")
                            .arg("EX")
                            .arg(60)
                            .query_async::<()>(&mut conn)
                            .await;
                        let r2 = conn.publish::<_, _, ()>(&channel, "1").await;
                        if r1.is_ok() && r2.is_ok() {
                            return;
                        }
                        let delay_ms = 500 * 2u64.pow(attempt);
                        tracing::error!(sandbox_id = %sandbox_id, attempt = attempt + 1, "Redis push_to_sandbox failed, retrying in {delay_ms}ms");
                        tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                    }
                    Err(_) => {
                        let delay_ms = 500 * 2u64.pow(attempt);
                        tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                    }
                }
            }
            tracing::error!(sandbox_id = %sandbox_id, "Redis push_to_sandbox failed after 3 retries, local queue only");
        }
    }

    async fn signal_sandbox(&self, sandbox_id: Uuid) {
        let mut queues = self.queues.lock().await;
        let queue = queues.entry(sandbox_id).or_default();
        queue.clear();
        queue.push_back(Uuid::nil());
    }

    /// Push to the global queue (for re-scheduling).
    /// Retries Redis 3 times with exponential backoff before falling back to local.
    pub async fn push_to_global(&self, task_id: Uuid) {
        if let Some(ref client) = self.redis_client {
            for attempt in 0..3u32 {
                match client.get_multiplexed_async_connection().await {
                    Ok(mut conn) => {
                        match conn
                            .rpush::<_, _, ()>("joysafeter:global_queue", task_id.to_string())
                            .await
                        {
                            Ok(_) => return,
                            Err(e) => {
                                let delay_ms = 500 * 2u64.pow(attempt);
                                tracing::error!(task_id = %task_id, attempt = attempt + 1, "Redis push_to_global failed: {e}, retrying in {delay_ms}ms");
                                tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                            }
                        }
                    }
                    Err(e) => {
                        let delay_ms = 500 * 2u64.pow(attempt);
                        tracing::error!(task_id = %task_id, attempt = attempt + 1, "Redis connection failed: {e}, retrying in {delay_ms}ms");
                        tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                    }
                }
            }
            tracing::error!(task_id = %task_id, "Redis push_to_global failed after 3 retries, falling back to local");
        }

        // In-memory fallback
        {
            let mut global = self.global.lock().await;
            global.push_back(task_id);
        }
        self.global_notify.notify_one();
    }

    /// Wake up the scheduler without pushing a specific task.
    ///
    /// Used after resetting tasks to pending (e.g., health check cleanup)
    /// so the scheduler re-scans the DB promptly.
    pub fn notify_global(&self) {
        self.global_notify.notify_one();
    }

    /// Pop from global queue (blocking with timeout).
    pub async fn pop_from_global(&self, timeout: Duration) -> Option<Uuid> {
        // Try Redis first
        if let Some(ref client) = self.redis_client {
            match client.get_multiplexed_async_connection().await {
                Ok(mut conn) => {
                    let result: Result<Option<(String, String)>, _> = redis::cmd("BLPOP")
                        .arg("joysafeter:global_queue")
                        .arg(timeout.as_secs())
                        .query_async(&mut conn)
                        .await;

                    match result {
                        Ok(Some((_key, val))) => return val.parse().ok(),
                        Ok(None) => {
                            // #28: Timeout — check local queue before returning None
                            // (Python L143-145: continue loop; here caller retries)
                        }
                        Err(e) => {
                            tracing::warn!("Redis global pop failed: {e}, checking local queue")
                        }
                    }
                }
                Err(e) => tracing::warn!(
                    "Redis connection failed for global pop: {e}, checking local queue"
                ),
            }
        }

        // In-memory fallback
        let result = tokio::time::timeout(timeout, self.global_notify.notified()).await;
        if result.is_ok() {
            let mut global = self.global.lock().await;
            return global.pop_front();
        }
        None
    }

    /// Pop a sandbox wakeup token. The returned UUID is not a durable task source.
    pub async fn pop(&self, sandbox_id: Uuid) -> Option<Uuid> {
        let mut queues = self.queues.lock().await;
        queues.get_mut(&sandbox_id).and_then(|q| q.pop_front())
    }

    /// Wait for a sandbox wakeup signal (Redis pub/sub or notify).
    pub async fn wait_for_sandbox_wakeup(&self, sandbox_id: Uuid, timeout: Duration) -> bool {
        // Try Redis pub/sub
        if let Some(ref client) = self.redis_client {
            if let Ok(mut pubsub) = client.get_async_pubsub().await {
                let channel = format!("joysafeter:sandbox_wakeup_channel:{sandbox_id}");
                if pubsub.subscribe(&channel).await.is_ok() {
                    let result = tokio::time::timeout(timeout, async {
                        use futures::StreamExt;
                        pubsub.on_message().next().await
                    })
                    .await;
                    return result.is_ok();
                }
            }
        }

        let notified = {
            let mut queues = self.queues.lock().await;
            queues
                .get_mut(&sandbox_id)
                .and_then(|queue| queue.pop_front())
                .is_some()
        };
        if notified {
            return true;
        }

        tokio::time::sleep(timeout).await;
        self.pop(sandbox_id).await.is_some()
    }

    /// Check if a sandbox has pending tasks.
    pub async fn has_pending(&self, sandbox_id: Uuid) -> bool {
        let queues = self.queues.lock().await;
        queues
            .get(&sandbox_id)
            .map(|q| !q.is_empty())
            .unwrap_or(false)
    }

    /// Remove all tasks for a sandbox (in-memory + Redis).
    /// Matches Python drain_sandbox: clears wakeup tokens and returns no task IDs.
    pub async fn drain(&self, sandbox_id: Uuid) -> Vec<Uuid> {
        self.remove_sandbox_queue(sandbox_id).await;

        // Also drain Redis sandbox queue
        self.drain_sandbox_redis(sandbox_id).await;

        vec![]
    }

    /// Remove the sandbox queue entirely (Python L261-262).
    pub async fn remove_sandbox_queue(&self, sandbox_id: Uuid) {
        let mut queues = self.queues.lock().await;
        queues.remove(&sandbox_id);
    }

    /// Drain sandbox queue in Redis.
    pub async fn drain_sandbox_redis(&self, sandbox_id: Uuid) {
        if let Some(ref client) = self.redis_client {
            if let Ok(mut conn) = client.get_multiplexed_async_connection().await {
                let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");
                let _ = conn.del::<_, ()>(&key).await;
            }
        }
    }
}
