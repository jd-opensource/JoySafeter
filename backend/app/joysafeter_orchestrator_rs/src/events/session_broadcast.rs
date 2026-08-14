use std::sync::Arc;

use tokio::sync::broadcast;
use tracing::warn;

use super::envelope::EventEnvelope;
use crate::kernel::session_broadcaster::SessionBroadcaster;

/// SessionBroadcastSubscriber — BROADCAST phase.
///
/// Sends session-level events to WebSocket/SSE subscribers via SessionBroadcaster.
/// Mirrors the Python `SessionBroadcastSubscriber`.
pub struct SessionBroadcastSubscriber {
    broadcaster: SessionBroadcaster,
}

impl SessionBroadcastSubscriber {
    pub fn new(broadcaster: SessionBroadcaster) -> Self {
        Self { broadcaster }
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
                        self.handle(&envelope).await;
                    }
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        warn!("SessionBroadcastSubscriber lagged by {n} messages");
                    }
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }
        })
    }

    async fn handle(&self, envelope: &EventEnvelope) {
        // Runner/status envelopes must only reach the UI after they have been
        // persisted and assigned the canonical DB seq. Raw envelopes can carry
        // runner seq/no-seq values, which makes live ordering differ from the
        // refresh path that reads from DB.
        if !envelope.is_status_change || !envelope.db_persisted || envelope.session_seq.is_none() {
            return;
        }

        let mut event = envelope.payload.clone();
        if !event.is_object() {
            event = serde_json::json!({});
        }
        if let Some(obj) = event.as_object_mut() {
            obj.insert("type".to_string(), serde_json::json!(envelope.event_type));
            if let Some(id) = envelope.event_id {
                obj.insert("id".to_string(), serde_json::json!(id.to_public()));
            }
            if let Some(seq) = envelope.session_seq {
                obj.insert("seq".to_string(), serde_json::json!(seq));
            }
            if !obj.contains_key("stop_reason") {
                obj.insert(
                    "stop_reason".to_string(),
                    envelope.stop_reason.clone().unwrap_or_default(),
                );
            }
        }

        self.broadcaster.send(envelope.session_id, event).await;
    }
}
