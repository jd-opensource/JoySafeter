use serde::ser::SerializeMap;
use serde::{Deserialize, Serialize, Serializer};

pub fn parse_event_id(s: &str) -> Option<uuid::Uuid> {
    let s = s.strip_prefix("evt_").unwrap_or(s);
    uuid::Uuid::parse_str(s).ok()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ContentBlock {
    Text { text: String },
    Image { source: serde_json::Value },
    Document { source: serde_json::Value },
}

impl ContentBlock {
    pub fn text(s: impl Into<String>) -> Self {
        Self::Text { text: s.into() }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct SessionEvent {
    pub id: uuid::Uuid,
    pub event_type: String,
    pub session_id: uuid::Uuid,
    #[serde(default)]
    pub payload: serde_json::Value,
    pub seq: i64,
    pub created_at: chrono::DateTime<chrono::Utc>,
    #[serde(default)]
    pub processed_at: Option<chrono::DateTime<chrono::Utc>>,
}

impl Serialize for SessionEvent {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let payload_fields = self.payload.as_object();
        let extra_count = payload_fields.map(|m| m.len()).unwrap_or(0);
        let mut map = serializer.serialize_map(Some(4 + extra_count))?;

        map.serialize_entry("id", &format!("evt_{}", self.id))?;
        map.serialize_entry("type", &self.event_type)?;
        map.serialize_entry("seq", &self.seq)?;

        if let Some(fields) = payload_fields {
            for (k, v) in fields {
                map.serialize_entry(k, v)?;
            }
        }

        map.serialize_entry("processed_at", &self.processed_at)?;
        map.end()
    }
}

impl SessionEvent {
    pub fn new(
        session_id: uuid::Uuid,
        event_type: &str,
        payload: serde_json::Value,
        seq: i64,
    ) -> Self {
        Self {
            id: uuid::Uuid::now_v7(),
            event_type: event_type.to_string(),
            session_id,
            payload,
            seq,
            created_at: chrono::Utc::now(),
            processed_at: None,
        }
    }

    pub fn new_processed(
        session_id: uuid::Uuid,
        event_type: &str,
        payload: serde_json::Value,
        seq: i64,
    ) -> Self {
        let now = chrono::Utc::now();
        Self {
            id: uuid::Uuid::now_v7(),
            event_type: event_type.to_string(),
            session_id,
            payload,
            seq,
            created_at: now,
            processed_at: Some(now),
        }
    }
}
