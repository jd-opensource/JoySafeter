use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::{
    AgentId, CredentialGroupId, CredentialId, EnvironmentId, SandboxId, SessionId, TaskId,
};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EngineKind {
    Claude,
    Codex,
    Native,
}

impl std::fmt::Display for EngineKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Claude => write!(f, "claude"),
            Self::Codex => write!(f, "codex"),
            Self::Native => write!(f, "native"),
        }
    }
}

impl EngineKind {
    pub fn from_str_lossy(s: &str) -> Self {
        match s {
            "codex" => Self::Codex,
            "native" => Self::Native,
            _ => Self::Claude,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelConfig {
    pub id: String,
    #[serde(default = "default_model_speed")]
    pub speed: String,
}

fn default_model_speed() -> String {
    "standard".to_string()
}

impl ModelConfig {
    pub fn from_id(id: String) -> Self {
        Self {
            id,
            speed: default_model_speed(),
        }
    }
}

fn default_object_type() -> String {
    "agent".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum AgentTool {
    #[serde(rename = "agent_toolset_20260401")]
    AgentToolset {
        #[serde(default)]
        default_config: Option<ToolDefaultConfig>,
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        configs: Vec<ToolItemConfig>,
    },
    #[serde(rename = "mcp_toolset")]
    McpToolset {
        mcp_server_name: String,
        #[serde(default)]
        default_config: Option<ToolDefaultConfig>,
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        configs: Vec<ToolItemConfig>,
    },
    #[serde(rename = "custom")]
    Custom {
        name: String,
        description: String,
        input_schema: serde_json::Value,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolItemConfig {
    pub name: String,
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub permission_policy: Option<PermissionPolicy>,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ToolDefaultConfig {
    #[serde(default)]
    pub permission_policy: PermissionPolicy,
    #[serde(default = "default_true", skip_serializing_if = "is_true")]
    pub enabled: bool,
}

fn is_true(v: &bool) -> bool {
    *v
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum PermissionPolicy {
    #[serde(rename = "always_allow")]
    #[default]
    AlwaysAllow,
    #[serde(rename = "always_ask")]
    AlwaysAsk,
}

impl PermissionPolicy {
    pub fn to_mode_str(&self) -> &'static str {
        match self {
            Self::AlwaysAllow => "bypassPermissions",
            Self::AlwaysAsk => "default",
        }
    }
}

pub fn extract_permission_mode(tools: &[AgentTool]) -> String {
    for tool in tools {
        match tool {
            AgentTool::AgentToolset {
                default_config,
                configs,
            } => {
                let base = default_config
                    .as_ref()
                    .map(|c| &c.permission_policy)
                    .unwrap_or(&PermissionPolicy::AlwaysAllow);
                if matches!(base, PermissionPolicy::AlwaysAsk) {
                    return "default".to_string();
                }
                if configs
                    .iter()
                    .any(|c| matches!(c.permission_policy, Some(PermissionPolicy::AlwaysAsk)))
                {
                    return "default".to_string();
                }
            }
            AgentTool::McpToolset {
                default_config,
                configs,
                ..
            } => {
                let base = default_config
                    .as_ref()
                    .map(|c| &c.permission_policy)
                    .unwrap_or(&PermissionPolicy::AlwaysAsk);
                if matches!(base, PermissionPolicy::AlwaysAsk) {
                    return "default".to_string();
                }
                if configs
                    .iter()
                    .any(|c| matches!(c.permission_policy, Some(PermissionPolicy::AlwaysAsk)))
                {
                    return "default".to_string();
                }
            }
            AgentTool::Custom { .. } => {}
        }
    }
    "bypassPermissions".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PackedItem {
    pub name: String,
    pub tar_gz_b64: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent {
    pub id: AgentId,
    #[serde(rename = "type", default = "default_object_type")]
    pub object_type: String,
    pub name: String,
    pub engine_kind: EngineKind,
    pub model: ModelConfig,
    #[serde(rename = "system")]
    pub system_prompt: Option<String>,
    pub description: Option<String>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, String>,
    #[serde(default)]
    pub env: HashMap<String, String>,
    pub mcp_servers: Vec<McpServerConfig>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub skills: Vec<PackedItem>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub agents: Vec<PackedItem>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub commands: Vec<PackedItem>,
    pub tools: Vec<AgentTool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub multiagent: Option<serde_json::Value>,
    pub version: i32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub environment_id: Option<EnvironmentId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_credential_id: Option<CredentialId>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
    pub archived_at: Option<chrono::DateTime<chrono::Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InjectConfig {
    pub name: String,
    pub target: String,
    pub tar_gz_b64: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum McpServerConfig {
    #[serde(rename = "streamable_http")]
    StreamableHttp { name: String, url: String },
    #[serde(rename = "sse")]
    Sse { name: String, url: String },
    #[serde(rename = "local_stdio")]
    LocalStdio {
        name: String,
        command: String,
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        args: Vec<String>,
        #[serde(default, skip_serializing_if = "HashMap::is_empty")]
        env: HashMap<String, String>,
    },
}

impl McpServerConfig {
    pub fn name(&self) -> &str {
        match self {
            Self::StreamableHttp { name, .. }
            | Self::Sse { name, .. }
            | Self::LocalStdio { name, .. } => name,
        }
    }
}

#[cfg(test)]
mod mcp_server_config_tests {
    use std::collections::HashMap;

    use super::McpServerConfig;

    #[test]
    fn accepts_only_canonical_mcp_transports() {
        let parsed: McpServerConfig = serde_json::from_value(serde_json::json!({
            "type": "streamable_http",
            "name": "remote",
            "url": "https://example.com/mcp"
        }))
        .unwrap();
        assert!(matches!(parsed, McpServerConfig::StreamableHttp { .. }));
        let sse: McpServerConfig = serde_json::from_value(serde_json::json!({
            "type": "sse", "name": "events", "url": "https://example.com/sse"
        }))
        .unwrap();
        assert!(matches!(sse, McpServerConfig::Sse { .. }));
        let local: McpServerConfig = serde_json::from_value(serde_json::json!({
            "type": "local_stdio", "name": "local", "command": "node",
            "args": ["server.js"], "env": {"MODE": "safe"}
        }))
        .unwrap();
        assert_eq!(
            local,
            McpServerConfig::LocalStdio {
                name: "local".to_string(),
                command: "node".to_string(),
                args: vec!["server.js".to_string()],
                env: HashMap::from([("MODE".to_string(), "safe".to_string())]),
            }
        );

        for transport in ["url", "http", "streamable-http", "stdio"] {
            assert!(
                serde_json::from_value::<McpServerConfig>(serde_json::json!({
                    "type": transport,
                    "name": "legacy",
                    "url": "https://example.com/mcp"
                }))
                .is_err()
            );
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatSession {
    pub id: SessionId,
    pub agent_id: AgentId,
    pub title: Option<String>,
    pub status: String,
    pub environment_id: Option<EnvironmentId>,
    pub last_harness_session_id: Option<String>,
    pub last_work_dir: Option<String>,
    pub last_sandbox_id: Option<SandboxId>,
    #[serde(default)]
    pub agent_version: Option<i32>,
    #[serde(default)]
    pub agent_snapshot: Option<serde_json::Value>,
    #[serde(default)]
    pub credential_group_ids: Vec<CredentialGroupId>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxRecord {
    pub id: SandboxId,
    pub external_id: String,
    pub provider: String,
    pub status: String,
    pub config: serde_json::Value,
    pub chat_session_id: Option<SessionId>,
    pub image: String,
    pub last_task_id: Option<TaskId>,
    pub last_used_at: chrono::DateTime<chrono::Utc>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub destroyed_at: Option<chrono::DateTime<chrono::Utc>>,
    pub workspace_path: Option<String>,
}
