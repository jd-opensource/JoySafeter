use std::sync::Arc;

use sqlx::PgPool;
use tokio::sync::broadcast;
use tracing::debug;

use super::envelope::EventEnvelope;
use super::persist::EventPersister;
use super::stream_publisher::EventStreamPublisher;
use crate::config::JoySafeterConfig;
use crate::runtime_config::RuntimeConfig;

/// Two-phase event bus for joysafeter events.
///
/// Mirrors the Python `JoySafeterEventBus`:
/// - Phase 1 (PERSIST): persist events to DB via batch sender
/// - Phase 2 (BROADCAST): fan-out to subscribers (WebSocket, Redis, etc.)
#[derive(Clone)]
pub struct EventBus {
    /// Broadcast channel for subscribers to receive events.
    tx: broadcast::Sender<Arc<EventEnvelope>>,
    /// Event persister (batched DB writes).
    persister: Arc<EventPersister>,
    /// Whether DB persistence is the primary persist phase.
    persist_to_db: bool,
    /// Redis Stream publisher used as the primary persist phase when enabled.
    stream_publisher: Option<Arc<EventStreamPublisher>>,
}

impl EventBus {
    pub fn new(
        pool: PgPool,
        config: &JoySafeterConfig,
        runtime_config: Arc<RuntimeConfig>,
        redis_client: redis::Client,
    ) -> Self {
        let (tx, _) = broadcast::channel(4096);
        let persister = Arc::new(EventPersister::new(
            pool,
            config.event_batch_max_size,
            config.event_batch_max_delay_ms,
            Some(runtime_config),
            redis_client.clone(),
            config.instance_id.clone(),
        ));

        let stream_publisher = if config.event_stream_enabled {
            Some(Arc::new(EventStreamPublisher::new(
                redis_client.clone(),
                &config.event_stream_key,
                config.event_stream_max_len,
                Some(persister.clone()),
                config.event_stream_fallback_to_db,
            )))
        } else {
            None
        };

        Self {
            tx,
            persister,
            // Redis Stream + Worker is the primary non-status event persistence
            // path when enabled. Without it, local/dev deployments keep the
            // direct DB batch persister as the primary path.
            persist_to_db: !config.event_stream_enabled,
            stream_publisher,
        }
    }

    /// Publish a single event through the bus.
    ///
    /// Persist and broadcast run CONCURRENTLY (not sequentially).
    /// Previously broadcast waited for persist (100ms+ DB batch delay).
    /// Now SSE gets events immediately while DB persist happens in parallel.
    pub async fn publish(&self, envelope: EventEnvelope) {
        let shared = Arc::new(envelope);

        // Phase 1: Persist.
        //
        // Ordinary events keep the previous fire-and-forget behavior so live
        // fanout is not coupled to batch DB latency. `flush_immediately`
        // events are different: callers use that flag for durability-sensitive
        // boundaries (for example control/HITL requests), so persistence must
        // complete before `publish` returns.
        // Session status events are state transitions, not ordinary log events:
        // they must be persisted by the atomic status helper or by
        // SessionStateSubscriber so the session row and replay event agree.
        // The generic batch persister only owns non-status events.
        if let Some(stream_publisher) = self.stream_publisher.clone() {
            if !shared.db_persisted && !shared.is_status_change {
                if shared.flush_immediately {
                    stream_publisher.publish(&shared).await;
                } else {
                    let stream_envelope = shared.clone();
                    tokio::spawn(async move {
                        stream_publisher.publish(&stream_envelope).await;
                    });
                }
            }
        } else if self.persist_to_db && !shared.db_persisted && !shared.is_status_change {
            if let Some(event_id) = shared.event_id {
                let persister = self.persister.clone();
                let session_id = shared.session_id;
                let event_type = shared.event_type.clone();
                let payload = shared.payload.clone();
                let session_seq = shared.session_seq;
                let flush = shared.flush_immediately;
                if flush {
                    persister
                        .push(event_id, session_id, &event_type, &payload, session_seq)
                        .await;
                    persister.flush().await;
                } else {
                    tokio::spawn(async move {
                        persister
                            .push(event_id, session_id, &event_type, &payload, session_seq)
                            .await;
                    });
                }
            }
        }

        // Phase 2: Broadcast (immediate — no wait for persist)
        if self.tx.receiver_count() > 0 {
            if let Err(e) = self.tx.send(shared) {
                debug!("no active subscribers for event: {e}");
            }
        }
    }

    /// Subscribe to events from this bus.
    pub fn subscribe(&self) -> broadcast::Receiver<Arc<EventEnvelope>> {
        self.tx.subscribe()
    }

    /// Return the DB persister used by the bus, for Redis Stream fallback.
    pub fn persister(&self) -> Arc<EventPersister> {
        self.persister.clone()
    }

    /// Force-flush any buffered events to DB.
    pub async fn flush(&self) {
        self.persister.flush().await;
    }
}
