use serde::{Deserialize, Serialize};

use crate::{AgentId, SandboxId, SessionId, TaskId};

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

impl std::fmt::Display for TaskStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            Self::Pending => "pending",
            Self::Scheduling => "scheduling",
            Self::Running => "running",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Aborted => "aborted",
            Self::Timeout => "timeout",
            Self::Cancelled => "cancelled",
        };
        f.write_str(s)
    }
}

impl TaskStatus {
    pub fn from_str_lossy(s: &str) -> Self {
        match s {
            "pending" => Self::Pending,
            "scheduling" => Self::Scheduling,
            "running" => Self::Running,
            "completed" => Self::Completed,
            "failed" => Self::Failed,
            "aborted" => Self::Aborted,
            "timeout" => Self::Timeout,
            "cancelled" => Self::Cancelled,
            _ => Self::Failed,
        }
    }

    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            Self::Completed | Self::Failed | Self::Aborted | Self::Timeout | Self::Cancelled
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub id: TaskId,
    pub agent_id: AgentId,
    pub chat_session_id: Option<SessionId>,
    pub status: TaskStatus,
    pub prompt: String,
    pub system_prompt: Option<String>,
    pub sandbox_id: Option<SandboxId>,
    pub output: String,
    pub error: Option<String>,
    pub usage: Option<serde_json::Value>,
    pub timeout_sec: i32,
    pub retry_count: i32,
    pub max_retries: i32,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub started_at: Option<chrono::DateTime<chrono::Utc>>,
    pub completed_at: Option<chrono::DateTime<chrono::Utc>>,
}
