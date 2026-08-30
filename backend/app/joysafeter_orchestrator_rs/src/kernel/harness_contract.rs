use std::collections::HashMap;
use std::fmt;

use crate::kernel::tool_policy::ToolPolicy;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HarnessMcpTransport {
    StreamableHttp,
    Sse,
    LocalStdio,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessMcpServer {
    pub name: String,
    pub command: String,
    pub args: Vec<String>,
    pub env: HashMap<String, String>,
    pub url: String,
    pub headers: HashMap<String, String>,
    pub transport: HarnessMcpTransport,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessCustomTool {
    pub name: String,
    pub description: String,
    pub input_schema_json: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessSkillArchive {
    pub name: String,
    pub tar_gz: Vec<u8>,
    pub target: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessMemoryFile {
    pub relative_path: String,
    pub content: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessMemoryStoreMount {
    pub mount_name: String,
    pub mount_path: String,
    pub access: String,
    pub files: Vec<HarnessMemoryFile>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessFileMount {
    pub path: String,
    pub content: Vec<u8>,
    pub filename: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessFileRef {
    pub path: String,
    pub url: String,
    pub filename: String,
    pub size_bytes: i64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HarnessRepository {
    pub url: String,
    pub branch: String,
    pub path: String,
    pub mount_name: String,
}

#[derive(Clone, Default)]
pub struct HarnessInput {
    pub provider: String,
    pub model: Option<String>,
    pub system_prompt: Option<String>,
    pub prompt: String,
    pub env: HashMap<String, String>,
    pub tool_policy: ToolPolicy,
    pub harness_session_id: Option<String>,
    pub mcp_servers: Vec<HarnessMcpServer>,
    pub custom_tools: Vec<HarnessCustomTool>,
    pub skills: Vec<HarnessSkillArchive>,
    pub setup_commands: Vec<String>,
    pub memory_system_prompt: Option<String>,
    pub memory_mounts: Vec<HarnessMemoryStoreMount>,
    pub files: Vec<HarnessFileMount>,
    pub file_refs: Vec<HarnessFileRef>,
    pub repos: Vec<HarnessRepository>,
    pub work_dir: Option<String>,
    pub max_turns: u32,
    pub system_prompt_mode: String,
}

impl fmt::Debug for HarnessInput {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HarnessInput")
            .field("provider", &self.provider)
            .field("model", &self.model)
            .field("system_prompt", &"<redacted>")
            .field("prompt", &"<redacted>")
            .field("env", &"<redacted>")
            .field("tool_policy", &self.tool_policy)
            .field("harness_session_id", &self.harness_session_id)
            .field("mcp_servers", &self.mcp_servers.len())
            .field("custom_tools", &self.custom_tools.len())
            .field("skills", &self.skills.len())
            .field("setup_commands", &"<redacted>")
            .field("memory_system_prompt", &"<redacted>")
            .field("memory_mounts", &self.memory_mounts.len())
            .field("files", &self.files.len())
            .field("file_refs", &self.file_refs.len())
            .field("repos", &self.repos.len())
            .field("work_dir", &self.work_dir)
            .field("max_turns", &self.max_turns)
            .field("system_prompt_mode", &self.system_prompt_mode)
            .finish()
    }
}
