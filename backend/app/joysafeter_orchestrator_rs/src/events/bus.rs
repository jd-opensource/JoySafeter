use std::sync::Arc;

use sqlx::PgPool;
use tokio::sync::broadcast;
use tracing::debug;

use super::envelope::EventEnvelope;
use super::persist::EventPersister;
use super::sink::EventSink;
use super::stream_publisher::EventStreamPublisher;
use crate::config::JoySafeterConfig;
use crate::runtime_config::RuntimeConfig;

/// Two-phase event bus for joysafeter events.
///
/// Mirrors the Python `JoySafeterEventBus`:
/// - Phase 1 (PERSIST): dispatch events to registered sinks
/// - Phase 2 (BROADCAST): fan-out to subscribers (WebSocket, Redis, etc.)
#[derive(Clone)]
pub struct EventBus {
    /// Broadcast channel for subscribers to receive events.
    tx: broadcast::Sender<Arc<EventEnvelope>>,
    /// Registered event sinks (exactly one active: either stream or db).
    sinks: Vec<Arc<dyn EventSink>>,
    /// Keep a reference to the DB persister for spawn_flush_timer() and
    /// direct flush access.
    persister: Arc<EventPersister>,
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

        // Build persist sinks. Redis Stream + Worker remains the async fanout
        // path when enabled, but we also keep the direct DB batch persister as
        // a durability fallback. The session event primary key is the event_id,
        // so worker redelivery later becomes a no-op instead of duplicating
        // rows. This prevents a stuck/missing worker from making agent events
        // invisible in the UI.
        let sinks: Vec<Arc<dyn EventSink>> = if config.event_stream_enabled {
            let stream_publisher = Arc::new(EventStreamPublisher::new(
                redis_client.clone(),
                &config.event_stream_key,
                config.event_stream_max_len,
                Some(persister.clone()),
                config.event_stream_fallback_to_db,
            ));
            vec![stream_publisher, persister.clone()]
        } else {
            vec![persister.clone()]
        };

        Self {
            tx,
            sinks,
            persister,
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
        // The generic sinks only own non-status events. Events already
        // persisted upstream (`db_persisted`) are skipped as well.
        if !shared.db_persisted && !shared.is_status_change {
            for sink in &self.sinks {
                if shared.flush_immediately {
                    sink.publish(&shared).await;
                } else {
                    let sink = sink.clone();
                    let envelope = shared.clone();
                    tokio::spawn(async move {
                        sink.publish(&envelope).await;
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

    /// Force-flush any buffered events across all sinks.
    pub async fn flush(&self) {
        for sink in &self.sinks {
            sink.flush().await;
        }
    }
}
