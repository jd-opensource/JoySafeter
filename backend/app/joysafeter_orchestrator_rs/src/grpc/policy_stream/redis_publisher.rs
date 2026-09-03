use std::collections::HashMap;
use std::sync::Arc;

use prost::Message;
use redis::aio::MultiplexedConnection;
use redis::{AsyncCommands, RedisError};
use tokio::sync::mpsc;
use tokio::sync::RwLock;
use tracing::{debug, error, info, warn};

use crate::proto::policy_stream::PolicyEvent;

const SUBSCRIBER_BUFFER_SIZE: usize = 2048;
const STREAM_KEY: &str = "joysafeter:policy_events";
const XREAD_BLOCK_MS: usize = 5000;
const XREAD_COUNT: usize = 100;

pub type SubscriberTx = mpsc::Sender<Arc<PolicyEvent>>;
pub type SubscriberRx = mpsc::Receiver<Arc<PolicyEvent>>;

#[derive(Debug, Clone)]
struct SubscriberState {
    tx: SubscriberTx,
    last_ack_seq: u64,
    pending_count: u32,
}

/// Redis Stream-backed event publisher for multi-replica correctness.
///
/// - Any orchestrator replica publishes via XADD → Redis Stream entry ID = seq
/// - Serving replica XREAD BLOCK → push to local subscribers
/// - Gateway resume_from_seq = Redis entry ID → cross-replica correct
pub struct RedisEventPublisher {
    redis_client: redis::Client,
    subscribers: Arc<RwLock<HashMap<String, SubscriberState>>>,
}

impl RedisEventPublisher {
    pub fn new(redis_client: redis::Client) -> Self {
        Self {
            redis_client,
            subscribers: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Publish a policy event: XADD to Redis Stream.
    ///
    /// Returns the Redis Stream entry ID (e.g., "1672531200000-0") as seq.
    pub async fn publish_event(&self, event: PolicyEvent) -> anyhow::Result<u64> {
        let mut conn = self.redis_client.get_multiplexed_async_connection().await?;

        // Encode event to protobuf binary
        let event_bytes = event.encode_to_vec();

        // XADD joysafeter:policy_events * event <binary>
        let entry_id: String = conn
            .xadd(STREAM_KEY, "*", &[("event", event_bytes)])
            .await?;

        // Parse entry ID "timestamp-sequence" → use timestamp as seq
        let seq = parse_entry_id_to_seq(&entry_id)?;

        debug!(seq, entry_id = %entry_id, event_type = ?event.event, "Published policy event to Redis Stream");
        Ok(seq)
    }

    /// Load events from Redis Stream for replay (used on reconnect).
    pub async fn load_events(
        &self,
        from_seq: u64,
        to_seq: u64,
    ) -> anyhow::Result<Vec<PolicyEvent>> {
        let mut conn = self.redis_client.get_multiplexed_async_connection().await?;

        let start_id = seq_to_entry_id(from_seq);
        let end_id = seq_to_entry_id(to_seq);

        // XRANGE joysafeter:policy_events start_id end_id COUNT 1000
        let results: redis::streams::StreamRangeReply = conn
            .xrange_count(STREAM_KEY, &start_id, &end_id, 1000)
            .await?;

        let mut events = Vec::new();
        for stream_id in results.ids {
            if let Some(event_data) = stream_id.map.get("event") {
                match event_data {
                    redis::Value::BulkString(bytes) => {
                        if let Ok(event) = PolicyEvent::decode(&bytes[..]) {
                            events.push(event);
                        } else {
                            warn!(entry_id = %stream_id.id, "Failed to decode event from Redis Stream");
                        }
                    }
                    _ => warn!(entry_id = %stream_id.id, "Unexpected value type for event field"),
                }
            }
        }

        Ok(events)
    }

    /// Current maximum seq (latest Redis Stream entry ID).
    pub async fn current_seq(&self) -> anyhow::Result<u64> {
        let mut conn = self.redis_client.get_multiplexed_async_connection().await?;

        // XREVRANGE joysafeter:policy_events + - COUNT 1
        let results: redis::streams::StreamRangeReply =
            conn.xrevrange_count(STREAM_KEY, "+", "-", 1).await?;

        if let Some(stream_id) = results.ids.first() {
            parse_entry_id_to_seq(&stream_id.id)
        } else {
            Ok(0)
        }
    }

    /// Add a subscriber (called by the replica serving the gateway's gRPC connection).
    pub async fn add_subscriber(
        &self,
        session_id: String,
        buffer_size: Option<usize>,
    ) -> SubscriberRx {
        let (tx, rx) = mpsc::channel(buffer_size.unwrap_or(SUBSCRIBER_BUFFER_SIZE));
        let state = SubscriberState {
            tx,
            last_ack_seq: 0,
            pending_count: 0,
        };
        self.subscribers
            .write()
            .await
            .insert(session_id.clone(), state);
        info!(session_id = %session_id, "Added subscriber");
        rx
    }

    /// Remove a subscriber (on disconnect).
    pub async fn remove_subscriber(&self, session_id: &str) {
        self.subscribers.write().await.remove(session_id);
        info!(session_id = %session_id, "Removed subscriber");
    }

    /// Update subscriber ACK state (for observability/backpressure).
    pub async fn update_subscriber_ack(&self, session_id: &str, seq: u64, pending_count: u32) {
        if let Some(state) = self.subscribers.write().await.get_mut(session_id) {
            state.last_ack_seq = seq;
            state.pending_count = pending_count;
        }
    }

    /// Broadcast an event to all local subscribers (called by XREAD loop).
    pub async fn broadcast_to_subscribers(&self, event: Arc<PolicyEvent>) {
        let subscribers = self.subscribers.read().await;
        for (session_id, state) in subscribers.iter() {
            if state.tx.try_send(event.clone()).is_err() {
                warn!(session_id = %session_id, seq = event.seq, "Subscriber channel full, skipping event");
            }
        }
    }

    /// Start the Redis Stream XREAD loop (called once by the serving replica).
    ///
    /// This replica XREAD BLOCKs on the stream, receives new entries,
    /// and broadcasts them to its local subscribers.
    pub async fn start_xread_loop(self: Arc<Self>) -> anyhow::Result<()> {
        let mut conn = self.redis_client.get_multiplexed_async_connection().await?;

        info!("RedisEventPublisher XREAD loop started");

        let mut last_id = "0-0".to_string(); // Start from beginning

        loop {
            // Check if we have any subscribers
            let has_subscribers = !self.subscribers.read().await.is_empty();
            if !has_subscribers {
                // No subscribers, sleep and retry
                tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
                continue;
            }

            // XREAD BLOCK 5000 COUNT 100 STREAMS joysafeter:policy_events <last_id>
            let opts = redis::streams::StreamReadOptions::default()
                .block(XREAD_BLOCK_MS)
                .count(XREAD_COUNT);

            let result: Result<redis::streams::StreamReadReply, RedisError> =
                conn.xread_options(&[STREAM_KEY], &[&last_id], &opts).await;

            match result {
                Ok(reply) => {
                    for stream_key in reply.keys {
                        for stream_id in stream_key.ids {
                            last_id = stream_id.id.clone();

                            if let Some(event_data) = stream_id.map.get("event") {
                                match event_data {
                                    redis::Value::BulkString(bytes) => {
                                        match PolicyEvent::decode(&bytes[..]) {
                                            Ok(event) => {
                                                self.broadcast_to_subscribers(Arc::new(event))
                                                    .await;
                                            }
                                            Err(e) => {
                                                warn!(entry_id = %stream_id.id, error = %e, "Failed to decode event");
                                            }
                                        }
                                    }
                                    _ => {
                                        warn!(entry_id = %stream_id.id, "Unexpected value type for event field")
                                    }
                                }
                            }
                        }
                    }
                }
                Err(e) => {
                    error!(error = %e, "XREAD loop error, reconnecting");
                    tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
                    // Re-establish connection
                    conn = self.redis_client.get_multiplexed_async_connection().await?;
                }
            }
        }
    }
}

/// Parse Redis Stream entry ID "timestamp-sequence" to seq (use timestamp).
fn parse_entry_id_to_seq(entry_id: &str) -> anyhow::Result<u64> {
    let parts: Vec<&str> = entry_id.split('-').collect();
    if parts.len() != 2 {
        anyhow::bail!("Invalid Redis Stream entry ID: {}", entry_id);
    }
    let timestamp: u64 = parts[0].parse()?;
    Ok(timestamp)
}

/// Convert seq back to Redis Stream entry ID (for XRANGE).
fn seq_to_entry_id(seq: u64) -> String {
    format!("{}-0", seq)
}
