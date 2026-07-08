use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

// ---------------------------------------------------------------------------
// JoySafeterTask — mirrors Python JoySafeterTask (table: joysafeter_tasks)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Pending,
    Scheduling,
    Running,
    Completed,
    Failed,
    Aborted,
    Timeout,
    Cancelled,
}

impl TaskStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Scheduling => "scheduling",
            Self::Running => "running",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Aborted => "aborted",
            Self::Timeout => "timeout",
            Self::Cancelled => "cancelled",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "pending" => Some(Self::Pending),
            "scheduling" => Some(Self::Scheduling),
            "running" => Some(Self::Running),
            "completed" => Some(Self::Completed),
            "failed" => Some(Self::Failed),
            "aborted" => Some(Self::Aborted),
            "timeout" => Some(Self::Timeout),
            "cancelled" => Some(Self::Cancelled),
            _ => None,
        }
    }

    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            Self::Completed | Self::Failed | Self::Aborted | Self::Timeout | Self::Cancelled
        )
    }
}

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterTask {
    pub id: Uuid,
    pub project_id: Option<String>,
    pub agent_id: Option<Uuid>,
    #[sqlx(rename = "chat_session_id")]
    pub session_id: Option<Uuid>,
    pub sandbox_id: Option<Uuid>,
    pub status: String,
    pub prompt: String,
    pub system_prompt: Option<String>,
    pub output: Option<String>,
    pub error: Option<String>,
    pub usage: Option<serde_json::Value>,
    pub timeout_sec: Option<i32>,
    pub retry_count: i32,
    pub max_retries: i32,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub duration_ms: Option<i64>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

// ---------------------------------------------------------------------------
// JoySafeterSession — mirrors Python JoySafeterSession (table: joysafeter_sessions)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionStatus {
    Idle,
    Running,
    Rescheduling,
    Terminated,
}

impl SessionStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Running => "running",
            Self::Rescheduling => "rescheduling",
            Self::Terminated => "terminated",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "idle" => Some(Self::Idle),
            "running" => Some(Self::Running),
            "rescheduling" => Some(Self::Rescheduling),
            "terminated" => Some(Self::Terminated),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterSession {
    pub id: Uuid,
    pub agent_id: Option<Uuid>,
    pub project_id: Option<String>,
    pub title: Option<String>,
    pub status: String,
    pub stop_reason: Option<serde_json::Value>,
    pub usage: Option<serde_json::Value>,
    pub last_sandbox_id: Option<Uuid>,
    pub last_harness_session_id: Option<String>,
    pub last_work_dir: Option<String>,
    pub vault_ids: Option<serde_json::Value>,
    pub environment_ref: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

// ---------------------------------------------------------------------------
// JoySafeterSandbox — mirrors Python JoySafeterSandbox (table: joysafeter_sandboxes)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterSandbox {
    pub id: Uuid,
    pub external_id: Option<String>,
    pub provider: String,
    pub status: String,
    pub config: Option<serde_json::Value>,
    pub chat_session_id: Option<Uuid>,
    pub image: Option<String>,
    pub last_task_id: Option<Uuid>,
    pub last_used_at: Option<DateTime<Utc>>,
    /// Set when the runner reports RunnerIdle (precise "all done" signal —
    /// cc's heldBackResult covers background sub-agents; codex multi-agent
    /// is aggregated in the runtime adapter). Cleared when the sandbox
    /// transitions back to running. The idle sweeper uses this instead of
    /// last_used_at to avoid per-heartbeat DB churn.
    pub idle_since: Option<DateTime<Utc>>,
    /// Set when the runner gRPC bridge drops; cleared on next attach.
    /// Fallback sweeper reaps after a grace window so a crashed runner
    /// doesn't leave a zombie sandbox forever.
    pub disconnected_at: Option<DateTime<Utc>>,
    pub destroyed_at: Option<DateTime<Utc>>,
    pub workspace_path: Option<String>,
    pub project_id: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

// ---------------------------------------------------------------------------
// JoySafeterSessionEvent — mirrors Python JoySafeterSessionEvent
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterSessionEvent {
    pub id: Uuid,
    pub session_id: Uuid,
    pub event_type: String,
    pub payload: Option<serde_json::Value>,
    pub seq: Option<i64>,
    pub created_at: DateTime<Utc>,
    pub processed_at: Option<DateTime<Utc>>,
}

// ---------------------------------------------------------------------------
// JoySafeterAgent — minimal fields needed by orchestrator
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterAgent {
    pub id: Uuid,
    pub project_id: Option<String>,
    pub name: String,
    pub engine_kind: Option<String>,
    pub model: Option<String>,
    pub system_prompt: Option<String>,
    pub description: Option<String>,
    pub env: Option<serde_json::Value>,
    pub mcp_configs: Option<serde_json::Value>,
    pub skills: Option<serde_json::Value>,
    pub agents: Option<serde_json::Value>,
    pub commands: Option<serde_json::Value>,
    pub tools: Option<serde_json::Value>,
    pub permission_mode: Option<String>,
    pub metadata: Option<serde_json::Value>,
    pub multiagent: Option<serde_json::Value>,
    pub version: i32,
    pub environment_ref: Option<String>,
    pub secret_ref: Option<String>,
}
