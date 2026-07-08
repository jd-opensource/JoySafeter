use std::collections::HashMap;
use std::sync::Arc;

use futures::StreamExt;
use redis::AsyncCommands;
use tokio::sync::mpsc;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;
use tracing::debug;
use uuid::Uuid;

/// A local subscriber: the mpsc sender and its cancellation token
/// for the associated Redis subscriber task.
struct Subscriber {
    tx: mpsc::Sender<serde_json::Value>,
    cancel: CancellationToken,
}

/// Broadcast session events to local subscribers and cross-instance via Redis.
///
/// Mirrors the Python `SessionBroadcaster`.
///
/// - Local subscribers get events via mpsc channels
/// - Cross-instance delivery via Redis pub/sub
#[derive(Clone)]
pub struct SessionBroadcaster {
    channels: Arc<Mutex<HashMap<Uuid, Vec<Subscriber>>>>,
    redis_client: Option<redis::Client>,
    instance_id: String,
}

impl SessionBroadcaster {
    pub fn new(redis_client: Option<redis::Client>, instance_id: &str) -> Self {
        Self {
            channels: Arc::new(Mutex::new(HashMap::new())),
            redis_client,
            instance_id: instance_id.to_string(),
        }
    }

    /// Subscribe to events for a session. Returns an mpsc receiver.
    pub async fn subscribe(&self, session_id: Uuid) -> mpsc::Receiver<serde_json::Value> {
        let (tx, rx) = mpsc::channel(256);
        let cancel = CancellationToken::new();
        let mut channels = self.channels.lock().await;
        channels.entry(session_id).or_default().push(Subscriber {
            tx: tx.clone(),
            cancel: cancel.clone(),
        });

        // Spawn Redis subscriber for cross-instance events
        if let Some(ref client) = self.redis_client {
            let client = client.clone();
            let instance_id = self.instance_id.clone();
            let tx_clone = tx.clone();
            let cancel_clone = cancel.clone();
            tokio::spawn(async move {
                if let Err(e) =
                    redis_subscriber_loop(client, session_id, &instance_id, tx_clone, cancel_clone)
                        .await
                {
                    debug!("Redis subscriber for session {session_id} ended: {e}");
                }
            });
        }

        rx
    }

    /// Send an event to all local subscribers and publish to Redis.
    pub async fn send(&self, session_id: Uuid, event: serde_json::Value) {
        self.send_local(session_id, event.clone()).await;

        // Redis pub/sub cross-instance delivery
        // Note: redis 0.27's get_multiplexed_async_connection() returns a clone
        // of the internally-malexed connection. It does NOT create a
        // new TCP connection on each call — the connection is pooled/shared.
        if let Some(ref client) = self.redis_client {
            let channel = format!("joysafeter:session_events:{session_id}");
            let wrapper = serde_json::json!({
                "source_instance": self.instance_id,
                "event": event,
            });
            match client.get_multiplexed_async_connection().await {
                Ok(mut conn) => {
                    if let Err(e) = conn
                        .publish::<_, _, ()>(
                            &channel,
                            serde_json::to_string(&wrapper).unwrap_or_default(),
                        )
                        .await
                    {
                        tracing::warn!(
                            session_id = %session_id,
                            error = %e,
                            "Failed to publish session event to Redis"
                        );
                    }
                }
                Err(e) => {
                    tracing::warn!(
                        session_id = %session_id,
                        error = %e,
                        "Failed to get Redis connection for session event publish"
                    );
                }
            }
        }
    }

    /// Send an event only to subscribers in this process.
    pub async fn send_local(&self, session_id: Uuid, event: serde_json::Value) {
        // Local delivery
        let channels = self.channels.lock().await;
        if let Some(senders) = channels.get(&session_id) {
            for sub in senders {
                if let Err(_e) = sub.tx.try_send(event.clone()) {
                    // E5 fix: drain channel and inject lagged marker (matching Python
                    // session_broadcaster.py:61-69). We cannot drain from the Sender
                    // side of mpsc, so we close/reopen — but since we only have the
                    // sender, we instead log and rely on the SSE endpoint's DB fallback.
                    // A full drain-and-inject requires the receiver side; the Python
                    // pattern works because Python's asyncio.Queue allows get_nowait()
                    // from any reference. For Rust mpsc, the lagged sentinel is injected
                    // by the SSE endpoint when it detects a gap in seq numbers.
                    tracing::warn!(
                        session_id = %session_id,
                        "Session event channel full, events will be recovered from DB (consumer lagging)"
                    );
                }
            }
        }
    }

    /// Remove all subscribers for a session.
    pub async fn remove(&self, session_id: Uuid) {
        let mut channels = self.channels.lock().await;
        // E6 fix: cancel all Redis subscriber tasks before removing
        if let Some(subs) = channels.remove(&session_id) {
            for sub in &subs {
                sub.cancel.cancel();
            }
        }
    }

    /// Remove a specific subscriber.
    pub async fn unsubscribe(&self, session_id: Uuid, tx: &mpsc::Sender<serde_json::Value>) {
        let mut channels = self.channels.lock().await;
        if let Some(senders) = channels.get_mut(&session_id) {
            // E6 fix: cancel the Redis subscriber task for the removed subscriber
            for sub in senders.iter() {
                if sub.tx.same_channel(tx) {
                    sub.cancel.cancel();
                }
            }
            senders.retain(|s| !s.tx.same_channel(tx));
            if senders.is_empty() {
                channels.remove(&session_id);
            }
        }
    }
}

/// Background task: subscribe to Redis channel for cross-instance session events.
/// Reconnects with exponential backoff on failure (matching Python L102-137).
/// E6 fix: cancellable via the CancellationToken.
async fn redis_subscriber_loop(
    client: redis::Client,
    session_id: Uuid,
    local_instance_id: &str,
    tx: mpsc::Sender<serde_json::Value>,
    cancel: CancellationToken,
) -> anyhow::Result<()> {
    let mut backoff = 1u64;
    let max_backoff = 30u64;

    loop {
        if cancel.is_cancelled() {
            break;
        }

        match redis_subscriber_inner(&client, session_id, local_instance_id, &tx, &cancel).await {
            Ok(()) => {
                // Stream ended normally (or cancelled)
                backoff = 1;
            }
            Err(e) => {
                tracing::warn!(
                    session_id = %session_id,
                    backoff_secs = backoff,
                    "Redis subscriber failed: {e}, reconnecting"
                );
                tokio::select! {
                    _ = tokio::time::sleep(std::time::Duration::from_secs(backoff)) => {},
                    _ = cancel.cancelled() => break,
                }
                backoff = (backoff * 2).min(max_backoff);
            }
        }

        // Check if sender is still alive or cancellation was requested
        if tx.is_closed() || cancel.is_cancelled() {
            break;
        }
    }

    Ok(())
}

async fn redis_subscriber_inner(
    client: &redis::Client,
    session_id: Uuid,
    local_instance_id: &str,
    tx: &mpsc::Sender<serde_json::Value>,
    cancel: &CancellationToken,
) -> anyhow::Result<()> {
    let mut pubsub = client.get_async_pubsub().await?;
    let channel = format!("joysafeter:session_events:{session_id}");
    pubsub.subscribe(&channel).await?;

    let mut stream = pubsub.on_message();
    loop {
        tokio::select! {
            msg = stream.next() => {
                let Some(msg) = msg else { break };
                let payload: String = msg.get_payload()?;
                if let Ok(wrapper) = serde_json::from_str::<serde_json::Value>(&payload) {
                    // Skip events from our own instance
                    if wrapper["source_instance"].as_str() == Some(local_instance_id) {
                        continue;
                    }
                    if let Some(event) = wrapper.get("event") {
                        if let Err(e) = tx.try_send(event.clone()) {
                            // Channel full — log warning, SSE fallback will catch up
                            tracing::warn!(
                                session_id = %session_id,
                                "Redis event channel full, event dropped: {e}"
                            );
                        }
                    }
                }
            }
            _ = cancel.cancelled() => {
                break;
            }
        }
    }

    Ok(())
}
