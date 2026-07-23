use std::sync::Arc;

use async_trait::async_trait;
use tokio::sync::broadcast;
use tracing::{error, warn};

use super::envelope::EventEnvelope;
use super::persist::EventPersister;
use super::sink::EventSink;

/// EventStreamPersistSubscriber — PERSIST phase.
///
/// Appends joysafeter events to a Redis Stream (XADD) with maxlen cap.
/// Falls back to DB persistence when Redis unavailable.
/// Mirrors the Python `EventStreamPersistSubscriber`.
pub struct EventStreamPublisher {
    redis_client: redis::Client,
    stream_key: String,
    max_len: usize,
    fallback_persister: Option<Arc<EventPersister>>,
    fallback_enabled: bool,
}

impl EventStreamPublisher {
    pub fn new(
        redis_client: redis::Client,
        stream_key: &str,
        max_len: usize,
        fallback_persister: Option<Arc<EventPersister>>,
        fallback_enabled: bool,
    ) -> Self {
        Self {
            redis_client,
            stream_key: stream_key.to_string(),
            max_len,
            fallback_persister,
            fallback_enabled,
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
                            continue;
                        }
                        self.publish(&envelope).await;
                    }
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        warn!("EventStreamPublisher lagged by {n} messages");
                    }
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }
        })
    }

    pub async fn publish(&self, envelope: &EventEnvelope) {
        let event_id = match envelope.event_id {
            Some(id) => id,
            None => return,
        };

        // Build stream entry fields
        let payload_str = serde_json::to_string(&envelope.payload).unwrap_or_default();
        let fields: Vec<(&str, String)> = vec![
            ("event_id", event_id.to_string()),
            ("session_id", envelope.session_id.to_string()),
            ("event_type", envelope.event_type.clone()),
            ("payload", payload_str),
            ("seq", envelope.session_seq.unwrap_or(0).to_string()),
            ("session_seq", envelope.session_seq.unwrap_or(0).to_string()),
            ("runner_seq", envelope.runner_seq.unwrap_or(0).to_string()),
        ];

        // Try Redis XADD
        match self.redis_client.get_multiplexed_async_connection().await {
            Ok(mut conn) => {
                let result: Result<String, _> = redis::cmd("XADD")
                    .arg(&self.stream_key)
                    .arg("MAXLEN")
                    .arg("~")
                    .arg(self.max_len)
                    .arg("*")
                    .arg(&fields[0].0)
                    .arg(&fields[0].1)
                    .arg(&fields[1].0)
                    .arg(&fields[1].1)
                    .arg(&fields[2].0)
                    .arg(&fields[2].1)
                    .arg(&fields[3].0)
                    .arg(&fields[3].1)
                    .arg(&fields[4].0)
                    .arg(&fields[4].1)
                    .arg(&fields[5].0)
                    .arg(&fields[5].1)
                    .arg(&fields[6].0)
                    .arg(&fields[6].1)
                    .query_async(&mut conn)
                    .await;

                if let Err(e) = result {
                    error!("Redis XADD failed: {e}");
                    self.fallback(envelope).await;
                }
            }
            Err(e) => {
                error!("Redis connection failed for stream publish: {e}");
                self.fallback(envelope).await;
            }
        }
    }

    async fn fallback(&self, envelope: &EventEnvelope) {
        if !self.fallback_enabled {
            return;
        }
        if envelope.db_persisted {
            return;
        }
        if let Some(ref persister) = self.fallback_persister {
            if let Some(event_id) = envelope.event_id {
                persister
                    .push(
                        event_id,
                        envelope.session_id,
                        &envelope.event_type,
                        &envelope.payload,
                        envelope.session_seq,
                    )
                    .await;
                if envelope.flush_immediately {
                    persister.flush().await;
                }
            }
        }
    }
}

#[async_trait]
impl EventSink for EventStreamPublisher {
    fn name(&self) -> &str {
        "redis_stream"
    }

    async fn publish(&self, envelope: &EventEnvelope) {
        EventStreamPublisher::publish(self, envelope).await;
    }

    async fn flush(&self) {
        // Redis Stream publish is immediate (no buffering) — no-op.
    }
}
