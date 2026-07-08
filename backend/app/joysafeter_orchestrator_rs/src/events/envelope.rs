use serde_json::Value;
use uuid::Uuid;

/// A single event flowing through the joysafeter event bus.
///
/// Mirrors the Python `JoySafeterEventEnvelope` dataclass.
#[derive(Debug, Clone)]
pub struct EventEnvelope {
    pub session_id: Uuid,
    pub event_type: String,
    pub payload: Value,
    pub task_id: Option<Uuid>,
    pub sandbox_id: Option<Uuid>,
    pub event_id: Option<Uuid>,
    pub seq: Option<i64>,
    pub flush_immediately: bool,
    pub is_status_change: bool,
    pub stop_reason: Option<Value>,
    /// Pre-built payload for task-level WebSocket broadcast.
    pub task_broadcast_payload: Option<Value>,
}

impl EventEnvelope {
    pub fn new(session_id: Uuid, event_type: impl Into<String>, payload: Value) -> Self {
        Self {
            session_id,
            event_type: event_type.into(),
            payload,
            task_id: None,
            sandbox_id: None,
            event_id: Some(Uuid::now_v7()),
            seq: None,
            flush_immediately: false,
            is_status_change: false,
            stop_reason: None,
            task_broadcast_payload: None,
        }
    }

    pub fn with_task(mut self, task_id: Uuid) -> Self {
        self.task_id = Some(task_id);
        self
    }

    pub fn with_sandbox(mut self, sandbox_id: Uuid) -> Self {
        self.sandbox_id = Some(sandbox_id);
        self
    }

    pub fn with_seq(mut self, seq: i64) -> Self {
        self.seq = Some(seq);
        self
    }

    pub fn flush_immediately(mut self) -> Self {
        self.flush_immediately = true;
        self
    }

    pub fn status_change(mut self, stop_reason: Option<Value>) -> Self {
        self.is_status_change = true;
        self.flush_immediately = true;
        self.stop_reason = stop_reason;
        self
    }
}
