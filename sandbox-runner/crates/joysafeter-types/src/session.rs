use serde::{Deserialize, Serialize, Serializer};
use std::collections::HashMap;

fn serialize_session_id<S: Serializer>(id: &uuid::Uuid, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&format!("sess_{id}"))
}

pub fn parse_session_id(s: &str) -> Option<uuid::Uuid> {
    let s = s.strip_prefix("sess_").unwrap_or(s);
    uuid::Uuid::parse_str(s).ok()
}

fn default_session_type() -> String {
    "session".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    #[serde(serialize_with = "serialize_session_id")]
    pub id: uuid::Uuid,
    #[serde(rename = "type", default = "default_session_type")]
    pub object_type: String,
    pub agent: SessionAgent,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub environment_id: Option<String>,
    pub status: SessionStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stop_reason: Option<StopReason>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub vault_ids: Vec<String>,
    #[serde(default)]
    pub usage: SessionUsage,
    #[serde(default)]
    pub stats: SessionStats,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub archived_at: Option<chrono::DateTime<chrono::Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionAgent {
    #[serde(rename = "type")]
    pub object_type: String,
    #[serde(serialize_with = "crate::agent::serialize_agent_id")]
    pub id: uuid::Uuid,
    pub version: i32,
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    pub model: crate::agent::ModelConfig,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub system: Option<String>,
    #[serde(default)]
    pub tools: Vec<crate::agent::AgentTool>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub skills: Vec<crate::agent::PackedItem>,
    #[serde(default)]
    pub mcp_servers: Vec<crate::agent::McpServerConfig>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub multiagent: Option<serde_json::Value>,
}

impl SessionAgent {
    pub fn from_agent(agent: &crate::agent::Agent) -> Self {
        Self {
            object_type: "agent".into(),
            id: agent.id,
            version: agent.version,
            name: agent.name.clone(),
            description: agent.description.clone(),
            model: agent.model.clone(),
            system: agent.system_prompt.clone(),
            tools: agent.tools.clone(),
            skills: agent.skills.clone(),
            mcp_servers: agent.mcp_servers.clone(),
            multiagent: agent.multiagent.clone(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionStatus {
    Idle,
    Running,
    Rescheduling,
    Terminated,
}

impl Default for SessionStatus {
    fn default() -> Self {
        Self::Idle
    }
}

impl std::fmt::Display for SessionStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Idle => write!(f, "idle"),
            Self::Running => write!(f, "running"),
            Self::Rescheduling => write!(f, "rescheduling"),
            Self::Terminated => write!(f, "terminated"),
        }
    }
}

impl SessionStatus {
    pub fn from_str_lossy(s: &str) -> Self {
        match s {
            "idle" => Self::Idle,
            "running" => Self::Running,
            "rescheduling" => Self::Rescheduling,
            "terminated" => Self::Terminated,
            _ => Self::Terminated,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum StopReason {
    EndTurn,
    #[serde(rename = "requires_action")]
    RequiresAction { event_ids: Vec<String> },
    RetriesExhausted,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SessionStats {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub active_seconds: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_seconds: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SessionUsage {
    #[serde(default)]
    pub input_tokens: u64,
    #[serde(default)]
    pub output_tokens: u64,
    #[serde(default)]
    pub cache_creation_input_tokens: u64,
    #[serde(default)]
    pub cache_read_input_tokens: u64,
}

/// Internal session data not exposed via the API.
/// Kept in the DB alongside Session fields but excluded from serialization.
#[derive(Debug, Clone)]
pub struct SessionInternal {
    pub agent_id: uuid::Uuid,
    pub environment_ref: Option<String>,
    pub last_harness_session_id: Option<String>,
    pub last_work_dir: Option<String>,
    pub last_sandbox_id: Option<uuid::Uuid>,
}

/// Full session including internal fields, used by kernel/dispatcher.
#[derive(Debug, Clone)]
pub struct SessionFull {
    pub session: Session,
    pub internal: SessionInternal,
}
