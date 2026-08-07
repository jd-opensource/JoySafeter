use crate::ids::{EventId, SandboxId, SessionId, TaskId};
use serde_json::Value;

/// A single event flowing through the joysafeter event bus.
///
/// Mirrors the Python `JoySafeterEventEnvelope` dataclass.
#[derive(Debug, Clone)]
pub struct EventEnvelope {
    pub session_id: SessionId,
    pub event_type: String,
    pub payload: Value,
    pub task_id: Option<TaskId>,
    pub sandbox_id: Option<SandboxId>,
    pub event_id: Option<EventId>,
    pub session_seq: Option<i64>,
    pub runner_seq: Option<i64>,
    pub flush_immediately: bool,
    pub is_status_change: bool,
    pub db_persisted: bool,
    pub stop_reason: Option<Value>,
    /// Pre-built payload for task-level WebSocket broadcast.
    pub task_broadcast_payload: Option<Value>,
}

impl EventEnvelope {
    pub fn new(session_id: SessionId, event_type: impl Into<String>, payload: Value) -> Self {
        Self {
            session_id,
            event_type: event_type.into(),
            payload,
            task_id: None,
            sandbox_id: None,
            event_id: Some(EventId::from_uuid(uuid::Uuid::now_v7())),
            session_seq: None,
            runner_seq: None,
            flush_immediately: false,
            is_status_change: false,
            db_persisted: false,
            stop_reason: None,
            task_broadcast_payload: None,
        }
    }

    pub fn with_task(mut self, task_id: TaskId) -> Self {
        self.task_id = Some(task_id);
        self
    }

    pub fn with_sandbox(mut self, sandbox_id: SandboxId) -> Self {
        self.sandbox_id = Some(sandbox_id);
        self
    }

    pub fn with_runner_seq(mut self, seq: i64) -> Self {
        self.runner_seq = Some(seq);
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

    pub fn with_db_persisted(mut self, event_id: EventId, seq: i64) -> Self {
        self.event_id = Some(event_id);
        self.session_seq = Some(seq);
        self.db_persisted = true;
        self
    }
}
