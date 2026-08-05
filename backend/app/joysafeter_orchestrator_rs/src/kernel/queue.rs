use std::time::Duration;

use anyhow::{anyhow, bail};
use redis::AsyncCommands;
use tracing::error;
use uuid::Uuid;

const GLOBAL_QUEUE_KEY: &str = "joysafeter:global_queue";

/// Extra time allowed on top of `BLPOP`'s server-side timeout before the
/// client-side deadline fires. Covers command round-trip on a healthy
/// connection; on a half-open connection this is the bound on how long the
/// scheduler can stall before it recovers with a fresh connection.
const BLPOP_CLIENT_TIMEOUT_MARGIN: Duration = Duration::from_secs(3);

/// Client-side deadline for non-blocking Redis ops (LPOP, connection acquire).
/// These have no server-side timeout, so without this a dead multiplexed
/// connection would hang them forever.
const NONBLOCKING_OP_TIMEOUT: Duration = Duration::from_secs(5);

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

    async fn get_connection(&self) -> anyhow::Result<redis::aio::MultiplexedConnection> {
        match tokio::time::timeout(
            NONBLOCKING_OP_TIMEOUT,
            self.redis_client.get_multiplexed_async_connection(),
        )
        .await
        {
            Ok(Ok(conn)) => Ok(conn),
            Ok(Err(e)) => Err(e.into()),
            Err(_) => bail!(
                "Redis connection acquire exceeded client deadline of {NONBLOCKING_OP_TIMEOUT:?}"
            ),
        }
    }

    /// Push a sandbox wakeup signal after a task has been attached in DB.
    pub async fn push(&self, sandbox_id: Uuid, task_id: Uuid) -> anyhow::Result<()> {
        let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");
        let channel = format!("joysafeter:sandbox_wakeup_channel:{sandbox_id}");

        for attempt in 0..3u32 {
            match self.get_connection().await {
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
        for attempt in 0..3u32 {
            match self.get_connection().await {
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
    ///
    /// `BLPOP`'s `timeout` argument is enforced *server-side*: it only fires once
    /// the command has actually reached Redis. If the underlying multiplexed TCP
    /// connection is half-open (e.g. the Docker/host network dropped it without a
    /// FIN — common after a Docker Desktop restart), the command never reaches the
    /// server, the server-side timeout never triggers, and `query_async().await`
    /// blocks forever. Because the scheduler loop awaits this call inline, a single
    /// wedged connection silently freezes *all* task scheduling with no error and
    /// no log.
    ///
    /// To make this self-healing we wrap the await in a client-side
    /// [`tokio::time::timeout`] with a margin over the server-side timeout. On a
    /// healthy connection the server responds first (data or its own timeout). On a
    /// dead connection the client-side deadline fires, we surface an error, and the
    /// caller drops this connection and retries with a fresh one on the next loop.
    pub async fn pop_from_global(&self, timeout: Duration) -> anyhow::Result<Option<Uuid>> {
        let mut conn = self.get_connection().await?;
        let blpop = async {
            redis::cmd("BLPOP")
                .arg(GLOBAL_QUEUE_KEY)
                .arg(timeout.as_secs())
                .query_async::<Option<(String, String)>>(&mut conn)
                .await
        };

        // Client-side deadline = server-side BLPOP timeout + margin for the
        // round-trip. Guarantees the await returns even on a half-open socket.
        let client_deadline = timeout + BLPOP_CLIENT_TIMEOUT_MARGIN;
        let result = match tokio::time::timeout(client_deadline, blpop).await {
            Ok(inner) => inner?,
            Err(_) => bail!(
                "BLPOP on {GLOBAL_QUEUE_KEY} exceeded client deadline of {client_deadline:?} \
                 (server-side timeout {timeout:?}); treating connection as dead"
            ),
        };

        match result {
            Some((_key, val)) => Self::parse_task_id(&val).map(Some),
            None => Ok(None),
        }
    }

    /// Drain one immediately available task candidate without blocking.
    pub async fn try_pop_from_global(&self) -> anyhow::Result<Option<Uuid>> {
        let mut conn = self.get_connection().await?;
        let lpop = async {
            redis::cmd("LPOP")
                .arg(GLOBAL_QUEUE_KEY)
                .query_async::<Option<String>>(&mut conn)
                .await
        };
        // LPOP has no server-side timeout; bound it client-side so a half-open
        // connection cannot wedge the scheduler drain loop.
        let val = match tokio::time::timeout(NONBLOCKING_OP_TIMEOUT, lpop).await {
            Ok(inner) => inner?,
            Err(_) => bail!(
                "LPOP on {GLOBAL_QUEUE_KEY} exceeded client deadline of \
                 {NONBLOCKING_OP_TIMEOUT:?}; treating connection as dead"
            ),
        };

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
        if let Ok(mut conn) = self.get_connection().await {
            let key = format!("joysafeter:sandbox_wakeup:{sandbox_id}");
            let _ = conn.del::<_, ()>(&key).await;
        }
    }
}
