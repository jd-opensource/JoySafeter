use std::sync::Arc;

use sqlx::PgPool;
use tokio::sync::broadcast;
use tracing::debug;

use super::envelope::EventEnvelope;
use super::persist::EventPersister;
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
}

impl EventBus {
    pub fn new(
        pool: PgPool,
        config: &JoySafeterConfig,
        runtime_config: Arc<RuntimeConfig>,
        redis_client: Option<redis::Client>,
    ) -> Self {
        let (tx, _) = broadcast::channel(4096);
        let persister = Arc::new(EventPersister::new(
            pool,
            config.event_batch_max_size,
            config.event_batch_max_delay_ms,
            Some(runtime_config),
            redis_client,
            config.instance_id.clone(),
        ));

        Self {
            tx,
            persister,
            // Rust orchestrator runs without the Python worker in local/dev
            // setups, so Redis Stream cannot be the only persistence path.
            // Keep direct DB persistence enabled; stream publishing remains a
            // fan-out path and duplicate DB writes are ignored by event_id.
            persist_to_db: true,
        }
    }

    /// Publish a single event through the bus.
    ///
    /// Persist and broadcast run CONCURRENTLY (not sequentially).
    /// Previously broadcast waited for persist (100ms+ DB batch delay).
    /// Now SSE gets events immediately while DB persist happens in parallel.
    pub async fn publish(&self, envelope: EventEnvelope) {
        let shared = Arc::new(envelope);

        // Phase 1: Persist (fire-and-forget — don't block broadcast)
        // NOTE: status_change events are ALSO persisted here now (E4 fix).
        // Previously they were excluded (`!shared.is_status_change`), relying
        // solely on SessionStateSubscriber via broadcast. But if the broadcast
        // channel lags, the subscriber misses the event and session_events has
        // no record — causing the frontend to never learn about idle/running
        // transitions. The persister's ON CONFLICT (id) DO NOTHING + dedup
        // logic prevents duplicates when SessionStateSubscriber also writes.
        if self.persist_to_db {
            if let Some(event_id) = shared.event_id {
                let persister = self.persister.clone();
                let session_id = shared.session_id;
                let event_type = shared.event_type.clone();
                let payload = shared.payload.clone();
                let seq = shared.seq;
                let flush = shared.flush_immediately;
                tokio::spawn(async move {
                    persister
                        .push(event_id, session_id, &event_type, &payload, seq)
                        .await;
                    if flush {
                        persister.flush().await;
                    }
                });
            }
        }

        // Phase 2: Broadcast (immediate — no wait for persist)
        if self.tx.receiver_count() > 0 {
            if let Err(e) = self.tx.send(shared) {
                debug!("no active subscribers for event: {e}");
            }
        }
    }

    /// #41: Publish a batch of events (Python L45: persist sequentially, broadcast concurrently).
    pub async fn publish_batch(&self, envelopes: Vec<EventEnvelope>) {
        for envelope in envelopes {
            self.publish(envelope).await;
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
