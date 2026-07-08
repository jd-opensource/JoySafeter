use std::sync::Arc;

use sqlx::PgPool;
use tokio::sync::broadcast;
use tracing::{debug, error, warn};
use uuid::Uuid;

use super::envelope::EventEnvelope;
use super::realtime::publish_session_event_realtime;

/// SessionStateSubscriber — PERSIST phase.
///
/// Updates session DB status when a status-change event flows through the bus.
/// Mirrors the Python `SessionStateSubscriber`.
pub struct SessionStateSubscriber {
    pool: PgPool,
    redis_client: Option<redis::Client>,
    instance_id: String,
}

impl SessionStateSubscriber {
    pub fn new(pool: PgPool, redis_client: Option<redis::Client>, instance_id: String) -> Self {
        Self {
            pool,
            redis_client,
            instance_id,
        }
    }

    /// Spawn as a background task listening on the event bus.
    pub fn spawn(
        self,
        mut rx: broadcast::Receiver<Arc<EventEnvelope>>,
    ) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            loop {
                match rx.recv().await {
                    Ok(envelope) => {
                        if envelope.is_status_change {
                            self.handle(&envelope).await;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        warn!("SessionStateSubscriber lagged by {n} messages");
                    }
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }
        })
    }

    async fn handle(&self, envelope: &EventEnvelope) {
        let status = match envelope.event_type.as_str() {
            "session.status_running" => "running",
            "session.status_idle" => "idle",
            "session.status_rescheduling" => "rescheduling",
            "session.status_terminated" => "terminated",
            _ => return,
        };

        let stop_reason = envelope.stop_reason.as_ref();

        // Use a single transaction with advisory lock to prevent:
        // 1. Deadlocks with EventPersister (consistent lock ordering: advisory → row)
        // 2. Seq races on session_events (serialized by advisory lock)
        // Matches Python SessionService.update_session_status + send_event lock ordering.
        let result: Result<Option<(Uuid, i64)>, sqlx::Error> = async {
            let mut tx = self.pool.begin().await?;

            // Acquire advisory lock FIRST (same key derivation as Python)
            let lock_key = i64::from_be_bytes(
                envelope.session_id.as_bytes()[8..16].try_into().unwrap(),
            );
            sqlx::query("SELECT pg_advisory_xact_lock($1)")
                .bind(lock_key)
                .execute(&mut *tx)
                .await?;

            if status == "running" {
                let task_id = envelope
                    .payload
                    .get("task_id")
                    .and_then(|v| v.as_str())
                    .map(ToOwned::to_owned)
                    .or_else(|| envelope.task_id.map(|id| id.to_string()));
                if let Some(task_id) = task_id.as_deref() {
                    if let Ok(task_uuid) = Uuid::parse_str(task_id) {
                        let task_status: Option<String> = sqlx::query_scalar(
                            "SELECT status FROM joysafeter_tasks WHERE id = $1",
                        )
                        .bind(task_uuid)
                        .fetch_optional(&mut *tx)
                        .await?;
                        if !matches!(task_status.as_deref(), Some("pending" | "scheduling" | "running")) {
                            tx.commit().await?;
                            return Ok(None);
                        }
                    }

                    let latest_status = sqlx::query_as::<_, (String, serde_json::Value)>(
                        r#"
                        SELECT event_type, payload
                        FROM joysafeter_session_events
                        WHERE session_id = $1 AND event_type LIKE 'session.status_%'
                        ORDER BY seq DESC, id DESC
                        LIMIT 1
                        "#,
                    )
                    .bind(envelope.session_id)
                    .fetch_optional(&mut *tx)
                    .await?;

                    if let Some((latest_type, latest_payload)) = latest_status {
                        let latest_task_id = latest_payload
                            .get("task_id")
                            .and_then(|v| v.as_str())
                            .or_else(|| latest_payload.get("task").and_then(|v| v.as_str()));
                        if latest_type == "session.status_idle" && latest_task_id == Some(task_id) {
                            tx.commit().await?;
                            return Ok(None);
                        }
                    }
                }
            }

            // CAS guard on status transitions. Keep this identical to
            // Python SessionService._VALID_TRANSITIONS.
            let allowed_from = match status {
                "running" => "'idle','running','rescheduling'",
                "idle" => "'running'",
                "terminated" => "'idle','running','rescheduling'",
                "rescheduling" => "'running','idle'",
                _ => "'idle','running','rescheduling','terminated'",
            };

            let sql = format!(
                r#"
                UPDATE joysafeter_sessions
                SET status = $2,
                    stop_reason = CASE
                        WHEN $3::jsonb IS NOT NULL OR $2 IN ('idle', 'terminated') THEN $3::jsonb
                        ELSE stop_reason
                    END,
                    updated_at = NOW()
                WHERE id = $1 AND status IN ({allowed_from})
                  AND NOT (status = $2 AND COALESCE(stop_reason, '{{}}'::jsonb) = COALESCE($3::jsonb, '{{}}'::jsonb))
                "#,
            );
            let update_result = sqlx::query(&sql)
                .bind(envelope.session_id)
                .bind(status)
                .bind(stop_reason)
                .execute(&mut *tx)
                .await?;

            if update_result.rows_affected() == 0 {
                // CAS failed or session not found — skip event persistence
                tx.commit().await?;
                return Ok(None);
            }

            let mut inserted_event: Option<(Uuid, i64)> = None;
            // Persist the status event (seq protected by advisory lock in same txn)
            if let Some(event_id) = envelope.event_id {
                let latest = sqlx::query_as::<_, (String, serde_json::Value)>(
                    r#"
                    SELECT event_type, payload
                    FROM joysafeter_session_events
                    WHERE session_id = $1
                    ORDER BY seq DESC, id DESC
                    LIMIT 1
                    "#,
                )
                .bind(envelope.session_id)
                .fetch_optional(&mut *tx)
                .await?;

                if let Some((latest_type, latest_payload)) = latest {
                    let latest_key = serde_json::json!({
                        "task_id": latest_payload.get("task_id").cloned().unwrap_or(serde_json::Value::Null),
                        "stop_reason": latest_payload.get("stop_reason").cloned().unwrap_or_else(|| serde_json::json!({})),
                    });
                    let current_key = serde_json::json!({
                        "task_id": envelope.payload.get("task_id").cloned().unwrap_or(serde_json::Value::Null),
                        "stop_reason": envelope.payload.get("stop_reason").cloned().unwrap_or_else(|| serde_json::json!({})),
                    });
                    if latest_type == envelope.event_type && latest_key == current_key {
                        tx.commit().await?;
                        return Ok(None);
                    }
                }

                let seq: i64 = sqlx::query_scalar(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM joysafeter_session_events WHERE session_id = $1",
                )
                .bind(envelope.session_id)
                .fetch_one(&mut *tx)
                .await?;

                let result = sqlx::query(
                    r#"
                    INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq, created_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    ON CONFLICT (id) DO NOTHING
                    "#,
                )
                .bind(event_id)
                .bind(envelope.session_id)
                .bind(&envelope.event_type)
                .bind(&envelope.payload)
                .bind(seq)
                .execute(&mut *tx)
                .await?;
                if result.rows_affected() > 0 {
                    inserted_event = Some((event_id, seq));
                }
            }

            tx.commit().await?;
            Ok(inserted_event)
        }
        .await;

        match result {
            Ok(inserted_event) => {
                debug!(
                    session_id = %envelope.session_id,
                    status = status,
                    "Session status updated"
                );
                if let Some((event_id, seq)) = inserted_event {
                    publish_session_event_realtime(
                        self.redis_client.as_ref(),
                        &self.instance_id,
                        envelope.session_id,
                        Some(event_id),
                        &envelope.event_type,
                        Some(seq),
                        &envelope.payload,
                    )
                    .await;
                }
            }
            Err(e) => {
                error!(
                    session_id = %envelope.session_id,
                    status = status,
                    "Failed to update session status: {e}"
                );
            }
        }
    }
}
