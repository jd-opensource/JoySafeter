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
    pub timeout_sec: Option<i32>,
    pub retry_count: i32,
    pub max_retries: i32,
}

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterSession {
    pub id: Uuid,
    pub agent_id: Option<Uuid>,
    pub project_id: Option<String>,
    pub status: String,
    pub last_harness_session_id: Option<String>,
    pub last_work_dir: Option<String>,
    pub vault_ids: Option<serde_json::Value>,
    pub environment_ref: Option<String>,
}

// ---------------------------------------------------------------------------
// JoySafeterSandbox — mirrors Python JoySafeterSandbox (table: joysafeter_sandboxes)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, FromRow)]
pub struct JoySafeterSandbox {
    pub id: Uuid,
    pub external_id: Option<String>,
    pub status: String,
    pub config: Option<serde_json::Value>,
    pub chat_session_id: Option<Uuid>,
    pub image: Option<String>,
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
