use crate::ids::{AgentId, CredentialId, EnvironmentId, ProjectId, SandboxId, SessionId, TaskId};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

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
    pub id: TaskId,
    pub project_id: Option<ProjectId>,
    pub agent_id: Option<AgentId>,
    #[sqlx(rename = "chat_session_id")]
    pub session_id: Option<SessionId>,
    pub sandbox_id: Option<SandboxId>,
    pub status: String,
    pub prompt: String,
    pub system_prompt: Option<String>,
    pub output: String,
    pub error: Option<String>,
    pub usage: Option<serde_json::Value>,
    pub timeout_sec: Option<i32>,
    pub retry_count: i32,
    pub max_retries: i32,
    pub schedule_attempts: i32,
    pub next_schedule_at: Option<chrono::DateTime<chrono::Utc>>,
    pub last_schedule_error: Option<String>,
    pub last_schedule_error_type: Option<String>,
    pub scheduling_started_at: Option<chrono::DateTime<chrono::Utc>>,
    pub started_at: Option<chrono::DateTime<chrono::Utc>>,
    pub completed_at: Option<chrono::DateTime<chrono::Utc>>,
    pub duration_ms: Option<i64>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
    pub owner_epoch: Option<i64>,
}

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterSession {
    pub id: SessionId,
    pub agent_id: Option<AgentId>,
    pub project_id: Option<ProjectId>,
    pub status: String,
    pub agent_version: Option<i32>,
    pub agent_snapshot: Option<serde_json::Value>,
    pub last_harness_session_id: Option<String>,
    pub last_work_dir: Option<String>,
    pub environment_id: Option<EnvironmentId>,
    pub runtime_config_generation: i64,
    pub runtime_config_generation_reason: Option<String>,
    pub runtime_config_generation_updated_at: Option<chrono::DateTime<chrono::Utc>>,
}

// ---------------------------------------------------------------------------
// JoySafeterSandbox — mirrors Python JoySafeterSandbox (table: joysafeter_sandboxes)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterSandbox {
    pub id: SandboxId,
    pub external_id: Option<String>,
    pub status: String,
    pub config: Option<serde_json::Value>,
    pub chat_session_id: Option<SessionId>,
    pub image: Option<String>,
    pub disconnected_at: Option<chrono::DateTime<chrono::Utc>>,
    pub networking_status: String,
    pub networking_policy_hash: Option<String>,
    pub networking_policy_version: i64,
    pub networking_applied_hash: Option<String>,
    pub networking_applied_version: Option<i64>,
    pub networking_last_error: Option<String>,
    pub networking_ready_at: Option<chrono::DateTime<chrono::Utc>>,
    pub runtime_config_status: String,
    pub runtime_config_last_reason: Option<String>,
    pub runtime_config_required_at: Option<chrono::DateTime<chrono::Utc>>,
    pub runtime_config_applied_generation: i64,
}

// ---------------------------------------------------------------------------
// JoySafeterAgent — minimal fields needed by orchestrator
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterAgent {
    pub id: AgentId,
    pub project_id: Option<ProjectId>,
    pub name: String,
    pub engine_kind: Option<String>,
    pub model: Option<String>,
    pub system_prompt: Option<String>,
    pub description: Option<String>,
    pub env: Option<serde_json::Value>,
    pub mcp_servers: Option<serde_json::Value>,
    pub skills: Option<serde_json::Value>,
    pub agents: Option<serde_json::Value>,
    pub commands: Option<serde_json::Value>,
    pub tools: Option<serde_json::Value>,
    pub permission_mode: Option<String>,
    pub metadata: Option<serde_json::Value>,
    pub multiagent: Option<serde_json::Value>,
    pub version: i32,
    pub environment_id: Option<EnvironmentId>,
    pub model_credential_id: Option<CredentialId>,
}
