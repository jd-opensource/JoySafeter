use std::sync::Arc;

use sqlx::PgPool;
use tokio::sync::{broadcast, mpsc, oneshot};
use tracing::{debug, warn};

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
    /// Ordered persistence sinks (DB only, or DB mirror plus Redis Stream).
    sinks: Vec<OrderedSink>,
    /// Keep a reference to the DB persister for spawn_flush_timer() and
    /// direct flush access.
    persister: Arc<EventPersister>,
}

enum SinkCommand {
    Publish {
        envelope: Arc<EventEnvelope>,
        completion: Option<oneshot::Sender<()>>,
    },
    Flush {
        completion: oneshot::Sender<()>,
    },
}

#[derive(Clone)]
struct OrderedSink {
    name: String,
    tx: mpsc::Sender<SinkCommand>,
}

impl OrderedSink {
    fn new(sink: Arc<dyn EventSink>) -> Self {
        let name = sink.name().to_string();
        let (tx, mut rx) = mpsc::channel::<SinkCommand>(4096);
        tokio::spawn(async move {
            while let Some(command) = rx.recv().await {
                match command {
                    SinkCommand::Publish {
                        envelope,
                        completion,
                    } => {
                        sink.publish(&envelope).await;
                        if envelope.flush_immediately {
                            sink.flush().await;
                        }
                        if let Some(completion) = completion {
                            let _ = completion.send(());
                        }
                    }
                    SinkCommand::Flush { completion } => {
                        sink.flush().await;
                        let _ = completion.send(());
                    }
                }
            }
        });
        Self { name, tx }
    }

    async fn publish(&self, envelope: Arc<EventEnvelope>, wait: bool) {
        let (completion, receiver) = if wait {
            let (completion, receiver) = oneshot::channel();
            (Some(completion), Some(receiver))
        } else {
            (None, None)
        };
        if self
            .tx
            .send(SinkCommand::Publish {
                envelope,
                completion,
            })
            .await
            .is_err()
        {
            warn!(sink = %self.name, "event sink worker stopped");
            return;
        }
        if let Some(receiver) = receiver {
            if receiver.await.is_err() {
                warn!(sink = %self.name, "event sink completion dropped");
            }
        }
    }

    async fn flush(&self) {
        let (completion, receiver) = oneshot::channel();
        if self
            .tx
            .send(SinkCommand::Flush { completion })
            .await
            .is_err()
        {
            warn!(sink = %self.name, "event sink worker stopped before flush");
            return;
        }
        if receiver.await.is_err() {
            warn!(sink = %self.name, "event sink flush completion dropped");
        }
    }
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

        // Stream mode keeps an ordered direct-DB durability mirror before the
        // Redis Stream publisher. Both paths use the same event_id, so whichever
        // persists first wins and the other becomes an idempotent no-op. The
        // per-sink FIFO workers below are essential: without them, the mirror's
        // concurrent pushes reordered token chunks. Keeping the mirror lets a
        // task-result flush persist all agent output before the atomic idle
        // status event assigns the next canonical DB sequence number.
        let sinks: Vec<OrderedSink> = if config.event_stream_enabled {
            let stream_publisher = Arc::new(EventStreamPublisher::new(
                redis_client.clone(),
                &config.event_stream_key,
                config.event_stream_max_len,
                Some(persister.clone()),
                config.event_stream_fallback_to_db,
            ));
            vec![
                OrderedSink::new(persister.clone()),
                OrderedSink::new(stream_publisher),
            ]
        } else {
            vec![OrderedSink::new(persister.clone())]
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
        // Each sink has one FIFO worker. Ordinary events enqueue without waiting
        // for I/O, while `flush_immediately` waits for the queued publish+flush
        // barrier. This keeps live fanout decoupled from persistence latency
        // without reordering events through one tokio task per event.
        // Session status events are state transitions, not ordinary log events:
        // they must be persisted by the atomic status helper or by
        // SessionStateSubscriber so the session row and replay event agree.
        // The generic sinks only own non-status events. Events already
        // persisted upstream (`db_persisted`) are skipped as well.
        if !shared.db_persisted && !shared.is_status_change {
            for sink in &self.sinks {
                sink.publish(shared.clone(), shared.flush_immediately).await;
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

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use async_trait::async_trait;
    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;
    use tokio::sync::Mutex;

    use super::*;
    use crate::ids::SessionId;

    struct DelayedRecordingSink {
        seen: Arc<Mutex<Vec<u64>>>,
    }

    #[async_trait]
    impl EventSink for DelayedRecordingSink {
        fn name(&self) -> &str {
            "delayed_recording"
        }

        async fn publish(&self, envelope: &EventEnvelope) {
            let ordinal = envelope
                .payload
                .get("ordinal")
                .and_then(|value| value.as_u64())
                .expect("test event ordinal");
            if ordinal == 1 {
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            self.seen.lock().await.push(ordinal);
        }

        async fn flush(&self) {}
    }

    #[tokio::test]
    async fn ordinary_sink_delivery_preserves_publish_order() {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://postgres:postgres@127.0.0.1/unused")
            .expect("construct lazy test pool");
        let redis_client =
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
        let persister = Arc::new(EventPersister::new(
            pool,
            100,
            60_000,
            None,
            redis_client,
            "event-order-test".to_string(),
        ));
        let seen = Arc::new(Mutex::new(Vec::new()));
        let sink: Arc<dyn EventSink> = Arc::new(DelayedRecordingSink { seen: seen.clone() });
        let (tx, _) = broadcast::channel(8);
        let event_bus = EventBus {
            tx,
            sinks: vec![OrderedSink::new(sink)],
            persister,
        };
        let session_id = SessionId::from_uuid(uuid::Uuid::now_v7());

        event_bus
            .publish(EventEnvelope::new(
                session_id,
                "agent.message",
                json!({"ordinal": 1}),
            ))
            .await;
        event_bus
            .publish(EventEnvelope::new(
                session_id,
                "agent.message",
                json!({"ordinal": 2}),
            ))
            .await;

        event_bus.flush().await;
        assert_eq!(*seen.lock().await, vec![1, 2]);
    }
}
