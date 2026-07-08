use redis::AsyncCommands;
use serde_json::Value;
use uuid::Uuid;

pub fn build_session_event_payload(
    event_id: Option<Uuid>,
    event_type: &str,
    seq: Option<i64>,
    payload: &Value,
) -> Value {
    let mut event = match payload.as_object() {
        Some(obj) => Value::Object(obj.clone()),
        None => serde_json::json!({}),
    };
    if let Some(obj) = event.as_object_mut() {
        obj.insert("type".to_string(), serde_json::json!(event_type));
        if let Some(id) = event_id {
            obj.insert("id".to_string(), serde_json::json!(format!("evt_{id}")));
        }
        if let Some(seq) = seq {
            obj.insert("seq".to_string(), serde_json::json!(seq));
        }
    }
    event
}

pub async fn publish_session_event_realtime(
    redis_client: Option<&redis::Client>,
    instance_id: &str,
    session_id: Uuid,
    event_id: Option<Uuid>,
    event_type: &str,
    seq: Option<i64>,
    payload: &Value,
) {
    let Some(client) = redis_client else {
        return;
    };
    // Note: redis 0.27's get_multiplexed_async_connection() returns a clone of
    // the internally-managed multipxed connection. It does NOT create a new TCP
    // connection on each call — the underlying connection is pooled/shared.
    let Ok(mut conn) = client.get_multiplexed_async_connection().await else {
        tracing::warn!(
            session_id = %session_id,
            event_type,
            "Failed to get Redis connection for realtime event publish"
        );
        return;
    };
    let event = build_session_event_payload(event_id, event_type, seq, payload);
    let wrapper = serde_json::json!({
        "source_instance": instance_id,
        "event": event,
    });
    let channel = format!("joysafeter:session_events:{session_id}");
    let payload = serde_json::to_string(&wrapper).unwrap_or_default();
    if let Err(e) = conn.publish::<_, _, ()>(channel, payload).await {
        tracing::warn!(
            session_id = %session_id,
            event_type,
            error = %e,
            "Failed to publish session event to Redis"
        );
    }
}
