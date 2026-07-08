use std::sync::Arc;
use std::time::Duration;

use sqlx::PgPool;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio::time::Instant;
use uuid::Uuid;

use super::realtime::publish_session_event_realtime;
use crate::runtime_config::RuntimeConfig;

/// Batched event persister — collects events and flushes them to the DB
/// when the batch is full or the delay timer expires.
///
/// Mirrors the Python `EventBatchSender`.
///
/// Clone-friendly: all mutable state is behind Arc<Mutex<..>>.
/// Use `spawn_flush_timer()` to start a background task that periodically
/// flushes buffered events even when no new events arrive.
#[derive(Clone)]
pub struct EventPersister {
    pool: PgPool,
    buffer: Arc<Mutex<EventBuffer>>,
    max_size: usize,
    max_delay: Duration,
    runtime_config: Option<Arc<RuntimeConfig>>,
    redis_client: Option<redis::Client>,
    instance_id: String,
}

struct EventBuffer {
    events: Vec<PendingEvent>,
    last_flush: Instant,
}

#[derive(Clone)]
struct PendingEvent {
    id: Uuid,
    session_id: Uuid,
    event_type: String,
    payload: serde_json::Value,
    seq: Option<i64>,
}

fn is_dedup_event_type(event_type: &str) -> bool {
    matches!(
        event_type,
        "session.status_idle"
            | "session.status_rescheduled"
            | "session.status_rescheduling"
            | "session.status_running"
            | "session.status_terminated"
            | "session.thread_status_idle"
            | "session.thread_status_running"
            | "session.thread_status_terminated"
            | "span.model_request_start"
            | "span.model_request_end"
    )
}

fn dedup_payload_key(event_type: &str, payload: &serde_json::Value) -> serde_json::Value {
    if event_type.starts_with("session.") {
        serde_json::json!({
            "task_id": payload.get("task_id").cloned().unwrap_or(serde_json::Value::Null),
            "stop_reason": payload.get("stop_reason").cloned().unwrap_or_else(|| serde_json::json!({})),
        })
    } else if event_type == "span.model_request_start" {
        serde_json::json!({
            "model": payload.get("model").cloned().unwrap_or(serde_json::Value::Null),
        })
    } else if event_type == "span.model_request_end" {
        serde_json::json!({
            "model": payload.get("model").cloned().unwrap_or(serde_json::Value::Null),
            "usage": payload.get("usage").cloned().unwrap_or_else(|| serde_json::json!({})),
        })
    } else {
        payload.clone()
    }
}

fn is_duplicate_event(previous: Option<&PendingEvent>, current: &PendingEvent) -> bool {
    let Some(previous) = previous else {
        return false;
    };
    previous.event_type == current.event_type
        && is_dedup_event_type(&current.event_type)
        && dedup_payload_key(&previous.event_type, &previous.payload)
            == dedup_payload_key(&current.event_type, &current.payload)
}

impl EventPersister {
    pub fn new(
        pool: PgPool,
        max_size: usize,
        max_delay_ms: u64,
        runtime_config: Option<Arc<RuntimeConfig>>,
        redis_client: Option<redis::Client>,
        instance_id: String,
    ) -> Self {
        Self {
            pool,
            buffer: Arc::new(Mutex::new(EventBuffer {
                events: Vec::with_capacity(max_size),
                last_flush: Instant::now(),
            })),
            max_size,
            max_delay: Duration::from_millis(max_delay_ms),
            runtime_config,
            redis_client,
            instance_id,
        }
    }

    /// Push an event into the buffer. Flushes automatically if full.
    pub async fn push(
        &self,
        id: Uuid,
        session_id: Uuid,
        event_type: &str,
        payload: &serde_json::Value,
        seq: Option<i64>,
    ) {
        let should_flush = {
            let mut buf = self.buffer.lock().await;
            buf.events.push(PendingEvent {
                id,
                session_id,
                event_type: event_type.to_string(),
                payload: payload.clone(),
                seq,
            });
            let max_size = self
                .runtime_config
                .as_ref()
                .map(|rc| rc.event_batch_max_size() as usize)
                .unwrap_or(self.max_size);
            let max_delay = self
                .runtime_config
                .as_ref()
                .map(|rc| Duration::from_millis(rc.event_batch_max_delay_ms()))
                .unwrap_or(self.max_delay);
            buf.events.len() >= max_size || buf.last_flush.elapsed() >= max_delay
        };

        if should_flush {
            self.flush().await;
        }
    }

    /// Flush all buffered events to the database.
    pub async fn flush(&self) {
        let events = {
            let mut buf = self.buffer.lock().await;
            if buf.events.is_empty() {
                return;
            }
            buf.last_flush = Instant::now();
            std::mem::take(&mut buf.events)
        };

        let count = events.len();

        // Group events by session_id and sort keys to prevent deadlocks
        // (matching Python batch_writer sort fix).
        use std::collections::BTreeMap;
        let mut groups: BTreeMap<Uuid, Vec<&PendingEvent>> = BTreeMap::new();
        for event in &events {
            groups.entry(event.session_id).or_default().push(event);
        }

        let result: Result<Vec<PendingEvent>, sqlx::Error> = async {
            let mut tx = self.pool.begin().await?;
            let mut inserted = Vec::new();

            // Acquire advisory locks in sorted session_id order (prevent deadlocks)
            for session_id in groups.keys() {
                let lock_key = i64::from_be_bytes(
                    session_id.as_bytes()[8..16].try_into().unwrap(),
                );
                sqlx::query("SELECT pg_advisory_xact_lock($1)")
                    .bind(lock_key)
                    .execute(&mut *tx)
                    .await?;
            }

            // Assign DB sequence numbers under the same session advisory lock.
            // This matches Python EventBatchSender: caller/runner seq is not the
            // canonical persisted session seq.
            for (session_id, session_events) in &groups {
                let base_seq: i64 = sqlx::query_scalar(
                    "SELECT COALESCE(MAX(seq), 0) FROM joysafeter_session_events WHERE session_id = $1",
                )
                .bind(session_id)
                .fetch_one(&mut *tx)
                .await?;

                let latest = sqlx::query_as::<_, (Uuid, String, serde_json::Value, i64)>(
                    r#"
                    SELECT id, event_type, payload, seq
                    FROM joysafeter_session_events
                    WHERE session_id = $1
                    ORDER BY seq DESC, id DESC
                    LIMIT 1
                    "#,
                )
                .bind(session_id)
                .fetch_optional(&mut *tx)
                .await?;

                let mut previous_event = latest.map(|(id, event_type, payload, seq)| PendingEvent {
                    id,
                    session_id: *session_id,
                    event_type,
                    payload,
                    seq: Some(seq),
                });
                let mut next_seq = base_seq;

                for event in session_events {
                    if is_duplicate_event(previous_event.as_ref(), event) {
                        continue;
                    }

                    next_seq += 1;
                    let result = sqlx::query(
                        r#"
                        INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq, created_at)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                        ON CONFLICT (id) DO NOTHING
                        "#,
                    )
                    .bind(event.id)
                    .bind(event.session_id)
                    .bind(&event.event_type)
                    .bind(&event.payload)
                    .bind(next_seq)
                    .execute(&mut *tx)
                    .await?;
                    let persisted_event = PendingEvent {
                        id: event.id,
                        session_id: event.session_id,
                        event_type: event.event_type.clone(),
                        payload: event.payload.clone(),
                        seq: Some(next_seq),
                    };
                    if result.rows_affected() > 0 {
                        inserted.push(persisted_event.clone());
                    }
                    previous_event = Some(persisted_event);
                }
            }

            tx.commit().await?;
            Ok(inserted)
        }
        .await;

        match result {
            Ok(inserted) => {
                tracing::debug!(count, "flushed events to DB");
                for event in inserted {
                    publish_session_event_realtime(
                        self.redis_client.as_ref(),
                        &self.instance_id,
                        event.session_id,
                        Some(event.id),
                        &event.event_type,
                        event.seq,
                        &event.payload,
                    )
                    .await;
                }
            }
            Err(e) => {
                // E1 fix: re-queue events on flush failure instead of dropping them.
                // Cap total buffer to 4x max_size to prevent unbounded growth
                // on persistent DB outage.
                tracing::error!(count, error = %e, "failed to flush events to DB, re-queuing");
                let mut buf = self.buffer.lock().await;
                let max_requeue = self.max_size * 4;
                if buf.events.len() + events.len() <= max_requeue {
                    let mut combined = events;
                    combined.append(&mut buf.events);
                    buf.events = combined;
                } else {
                    tracing::warn!(
                        dropped = events.len(),
                        "DB outage persists, dropping oldest events to prevent OOM"
                    );
                }
            }
        }
    }

    /// Spawn a periodic flush timer that ensures buffered events are persisted
    /// even when no new events arrive (matching Python's background flush loop).
    ///
    /// Returns the JoinHandle for the spawned task. The task runs until the
    /// handle is aborted or the runtime shuts down.
    pub fn spawn_flush_timer(&self) -> JoinHandle<()> {
        let this = self.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(this.max_delay);
            // The first tick completes immediately; skip it.
            interval.tick().await;
            loop {
                interval.tick().await;
                this.flush().await;
            }
        })
    }
}
