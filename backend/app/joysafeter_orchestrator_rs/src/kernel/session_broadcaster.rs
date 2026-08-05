use redis::AsyncCommands;
use uuid::Uuid;

/// Publish session events to Redis for API/SSE consumers.
#[derive(Clone)]
pub struct SessionBroadcaster {
    redis_client: redis::Client,
    instance_id: String,
}

impl SessionBroadcaster {
    pub fn new(redis_client: redis::Client, instance_id: &str) -> Self {
        Self {
            redis_client,
            instance_id: instance_id.to_string(),
        }
    }

    /// Publish an event to the session Redis channel.
    pub async fn send(&self, session_id: Uuid, event: serde_json::Value) {
        let channel = format!("joysafeter:session_events:{session_id}");
        let wrapper = serde_json::json!({
            "source_instance": self.instance_id,
            "event": event,
        });

        match self.redis_client.get_multiplexed_async_connection().await {
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
