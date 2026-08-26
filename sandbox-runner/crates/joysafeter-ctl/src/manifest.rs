use anyhow::{bail, Context};
use joysafeter_entity_id::{CredentialId, EnvironmentId};
use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RawResource {
    kind: String,
    #[allow(dead_code)]
    metadata: Metadata,
    #[serde(flatten)]
    #[allow(dead_code)]
    rest: serde_json::Value,
}

#[derive(Debug, Deserialize)]
pub struct Metadata {
    pub name: String,
}

#[derive(Debug)]
pub enum Resource {
    Agent(AgentManifest),
    Task(TaskManifest),
    Environment(EnvironmentManifest),
    MemoryStore(MemoryStoreManifest),
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AgentManifest {
    pub metadata: Metadata,
    pub spec: AgentSpec,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AgentSpec {
    pub engine_kind: String,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default, alias = "system")]
    pub system_prompt: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub env: HashMap<String, String>,
    #[serde(default)]
    pub mcp_servers: Vec<McpServerSpec>,
    #[serde(default)]
    pub skills: Vec<InjectSpec>,
    #[serde(default)]
    pub agents: Vec<InjectSpec>,
    #[serde(default)]
    pub commands: Vec<InjectSpec>,
    #[serde(default)]
    pub tools: Vec<AgentToolSpec>,
    #[serde(default)]
    pub environment_id: Option<EnvironmentId>,
    #[serde(default)]
    pub model_credential_id: Option<CredentialId>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", tag = "type")]
pub enum AgentToolSpec {
    #[serde(rename = "agent_toolset_20260401")]
    AgentToolset {
        #[serde(default)]
        default_config: Option<ToolDefaultConfigSpec>,
        #[serde(default)]
        configs: Vec<ToolItemConfigSpec>,
    },
    #[serde(rename = "mcp_toolset")]
    McpToolset {
        mcp_server_name: String,
        #[serde(default)]
        default_config: Option<ToolDefaultConfigSpec>,
        #[serde(default)]
        configs: Vec<ToolItemConfigSpec>,
    },
    #[serde(rename = "custom")]
    Custom {
        name: String,
        description: String,
        input_schema: serde_json::Value,
    },
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolItemConfigSpec {
    pub name: String,
    #[serde(default = "default_true")]
    pub enabled: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolDefaultConfigSpec {
    #[serde(default)]
    pub permission_policy: Option<PermissionPolicySpec>,
    #[serde(default)]
    pub enabled: Option<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PermissionPolicySpec {
    #[serde(rename = "type")]
    pub policy_type: String,
}

#[derive(Debug, Deserialize)]
pub struct InjectSpec {
    pub name: String,
    pub path: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", tag = "type")]
pub enum McpServerSpec {
    #[serde(rename = "streamable_http")]
    StreamableHttp {
        name: String,
        url: String,
        #[serde(
            default = "default_mcp_auth_requirement",
            rename = "authRequirement",
            alias = "auth_requirement"
        )]
        auth_requirement: McpAuthRequirement,
    },
    #[serde(rename = "sse")]
    Sse {
        name: String,
        url: String,
        #[serde(
            default = "default_sse_auth_requirement",
            rename = "authRequirement",
            alias = "auth_requirement",
            deserialize_with = "deserialize_sse_auth_requirement"
        )]
        auth_requirement: McpAuthRequirement,
    },
    #[serde(rename = "local_stdio")]
    LocalStdio {
        name: String,
        command: String,
        #[serde(default)]
        args: Vec<String>,
        #[serde(default)]
        env: HashMap<String, String>,
    },
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum McpAuthRequirement {
    Required,
    Optional,
    None,
}

impl McpAuthRequirement {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Required => "required",
            Self::Optional => "optional",
            Self::None => "none",
        }
    }
}

fn default_mcp_auth_requirement() -> McpAuthRequirement {
    McpAuthRequirement::Required
}

fn default_sse_auth_requirement() -> McpAuthRequirement {
    McpAuthRequirement::None
}

fn deserialize_sse_auth_requirement<'de, D>(deserializer: D) -> Result<McpAuthRequirement, D::Error>
where
    D: Deserializer<'de>,
{
    let requirement = McpAuthRequirement::deserialize(deserializer)?;
    if requirement != McpAuthRequirement::None {
        return Err(D::Error::custom(
            "SSE MCP servers require authRequirement: none",
        ));
    }
    Ok(requirement)
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnvironmentManifest {
    pub metadata: Metadata,
    pub spec: EnvironmentSpec,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnvironmentSpec {
    #[serde(rename = "type", default)]
    pub env_type: Option<String>,
    #[serde(default)]
    pub packages: Option<PackagesSpec>,
    #[serde(default)]
    pub networking: Option<NetworkingSpec>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PackagesSpec {
    #[serde(default)]
    pub apt: Vec<String>,
    #[serde(default)]
    pub pip: Vec<String>,
    #[serde(default)]
    pub npm: Vec<String>,
    #[serde(default)]
    pub cargo: Vec<String>,
    #[serde(default)]
    pub gem: Vec<String>,
    #[serde(default)]
    pub go: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NetworkingSpec {
    #[serde(rename = "type", default)]
    pub network_type: Option<String>,
    #[serde(default)]
    pub allowed_hosts: Vec<String>,
    #[serde(default)]
    pub allow_package_managers: Option<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskManifest {
    pub metadata: Metadata,
    pub spec: TaskSpec,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryStoreManifest {
    pub metadata: Metadata,
    pub spec: MemoryStoreSpec,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryStoreSpec {
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub metadata: Option<HashMap<String, String>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TaskSpec {
    pub agent: String,
    pub prompt: String,
    #[serde(default)]
    pub system_prompt: Option<String>,
    #[serde(default)]
    #[allow(dead_code)]
    pub session: Option<String>,
    #[serde(default)]
    pub environment_id: Option<EnvironmentId>,
    #[serde(default)]
    pub timeout: Option<String>,
    #[serde(default = "default_max_retries")]
    pub max_retries: i32,
}

fn default_max_retries() -> i32 {
    2
}

pub fn expand_env_vars(input: &str) -> String {
    let mut result = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '$' && chars.peek() == Some(&'{') {
            chars.next(); // consume '{'
            let mut var_expr = String::new();
            while let Some(&ch) = chars.peek() {
                if ch == '}' {
                    chars.next();
                    break;
                }
                var_expr.push(ch);
                chars.next();
            }
            let (var_name, default) = if let Some(pos) = var_expr.find(":-") {
                (&var_expr[..pos], Some(&var_expr[pos + 2..]))
            } else {
                (var_expr.as_str(), None)
            };
            match std::env::var(var_name) {
                Ok(val) => result.push_str(&val),
                Err(_) => {
                    if let Some(d) = default {
                        result.push_str(d);
                    }
                }
            }
        } else {
            result.push(c);
        }
    }
    result
}

pub fn parse_duration(s: &str) -> i32 {
    let s = s.trim();
    if let Some(n) = s.strip_suffix('s') {
        n.parse().unwrap_or(7200)
    } else if let Some(n) = s.strip_suffix('m') {
        n.parse::<i32>().unwrap_or(120) * 60
    } else if let Some(n) = s.strip_suffix('h') {
        n.parse::<i32>().unwrap_or(2) * 3600
    } else {
        s.parse().unwrap_or(7200)
    }
}

pub fn parse_manifests(path: &str) -> anyhow::Result<Vec<Resource>> {
    let p = Path::new(path);
    if p.is_dir() {
        let mut resources = Vec::new();
        for entry in fs::read_dir(p).context("Failed to read directory")? {
            let entry = entry?;
            let ep = entry.path();
            if ep
                .extension()
                .map(|e| e == "yaml" || e == "yml")
                .unwrap_or(false)
            {
                resources.extend(parse_file(&ep)?);
            }
        }
        Ok(resources)
    } else {
        parse_file(p)
    }
}

fn parse_file(path: &Path) -> anyhow::Result<Vec<Resource>> {
    let content =
        fs::read_to_string(path).with_context(|| format!("Failed to read {}", path.display()))?;
    let expanded = expand_env_vars(&content);

    let mut resources = Vec::new();
    for doc in expanded.split("\n---") {
        let trimmed = doc.trim();
        if trimmed.is_empty() {
            continue;
        }
        let raw: RawResource =
            serde_yaml::from_str(trimmed).with_context(|| "Failed to parse YAML document")?;

        let resource = match raw.kind.as_str() {
            "Agent" => {
                let manifest: AgentManifest = serde_yaml::from_str(trimmed)?;
                Resource::Agent(manifest)
            }
            "Task" => {
                let manifest: TaskManifest = serde_yaml::from_str(trimmed)?;
                Resource::Task(manifest)
            }
            "Environment" => {
                let manifest: EnvironmentManifest = serde_yaml::from_str(trimmed)?;
                Resource::Environment(manifest)
            }
            "MemoryStore" => {
                let manifest: MemoryStoreManifest = serde_yaml::from_str(trimmed)?;
                Resource::MemoryStore(manifest)
            }
            other => bail!("Unknown resource kind: {other}"),
        };
        resources.push(resource);
    }
    Ok(resources)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_expand_env_vars() {
        std::env::set_var("TEST_CTL_VAR", "hello");
        assert_eq!(expand_env_vars("${TEST_CTL_VAR}"), "hello");
        assert_eq!(expand_env_vars("${NONEXIST_VAR:-fallback}"), "fallback");
        assert_eq!(expand_env_vars("${NONEXIST_VAR}"), "");
        assert_eq!(
            expand_env_vars("prefix-${TEST_CTL_VAR}-suffix"),
            "prefix-hello-suffix"
        );
        std::env::remove_var("TEST_CTL_VAR");
    }

    #[test]
    fn test_parse_duration() {
        assert_eq!(parse_duration("300s"), 300);
        assert_eq!(parse_duration("5m"), 300);
        assert_eq!(parse_duration("1h"), 3600);
        assert_eq!(parse_duration("7200"), 7200);
    }

    #[test]
    fn test_parse_agent_yaml() {
        let yaml = r#"
apiVersion: joysafeter/v1
kind: Agent
metadata:
  name: test-agent
spec:
  engineKind: claude
  model: claude-sonnet-4-5-20250514
  systemPrompt: You are helpful.
  env:
    KEY: value
  mcpServers:
    - type: local_stdio
      name: fs
      command: npx
      args: ["-y", "@anthropic/mcp-filesystem"]
"#;
        let expanded = expand_env_vars(yaml);
        let manifest: AgentManifest = serde_yaml::from_str(&expanded).unwrap();
        assert_eq!(manifest.metadata.name, "test-agent");
        assert_eq!(manifest.spec.engine_kind, "claude");
        assert_eq!(
            manifest.spec.model.as_deref(),
            Some("claude-sonnet-4-5-20250514")
        );
        assert_eq!(manifest.spec.env.get("KEY").unwrap(), "value");
        assert_eq!(manifest.spec.mcp_servers.len(), 1);
    }

    #[test]
    fn test_parse_agent_yaml_requires_canonical_environment_id() {
        let yaml = r#"
apiVersion: joysafeter/v1
kind: Agent
metadata:
  name: test-agent
spec:
  engineKind: claude
  environmentId: env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f011
"#;

        let manifest: AgentManifest = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(
            manifest.spec.environment_id,
            Some("env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f011".parse().unwrap())
        );

        let legacy_key = ["environment", "Ref"].concat();
        let legacy = yaml.replace("environmentId", &legacy_key);
        assert!(serde_yaml::from_str::<AgentManifest>(&legacy).is_err());
    }

    #[test]
    fn test_parse_agent_yaml_rejects_sse_managed_auth() {
        for auth_requirement in ["required", "optional"] {
            let yaml = format!(
                r#"
apiVersion: joysafeter/v1
kind: Agent
metadata:
  name: test-agent
spec:
  engineKind: claude
  mcpServers:
    - type: sse
      name: events
      url: https://example.com/sse
      authRequirement: {auth_requirement}
"#
            );

            let error = serde_yaml::from_str::<AgentManifest>(&yaml).unwrap_err();
            assert!(
                error
                    .to_string()
                    .contains("SSE MCP servers require authRequirement: none"),
                "unexpected error: {error}"
            );
        }
    }

    #[test]
    fn test_parse_agent_yaml_rejects_unknown_mcp_auth_requirement() {
        let yaml = r#"
apiVersion: joysafeter/v1
kind: Agent
metadata:
  name: test-agent
spec:
  engineKind: claude
  mcpServers:
    - type: streamable_http
      name: tools
      url: https://example.com/mcp
      authRequirement: sometimes
"#;

        assert!(serde_yaml::from_str::<AgentManifest>(yaml).is_err());
    }

    #[test]
    fn test_parse_agent_yaml_defaults_sse_auth_to_none() {
        let yaml = r#"
apiVersion: joysafeter/v1
kind: Agent
metadata:
  name: test-agent
spec:
  engineKind: claude
  mcpServers:
    - type: sse
      name: events
      url: https://example.com/sse
"#;

        let manifest: AgentManifest = serde_yaml::from_str(yaml).unwrap();
        let McpServerSpec::Sse {
            auth_requirement, ..
        } = manifest.spec.mcp_servers.first().unwrap()
        else {
            panic!("expected SSE server");
        };
        assert_eq!(*auth_requirement, McpAuthRequirement::None);
    }

    #[test]
    fn test_parse_task_yaml() {
        let yaml = r#"
apiVersion: joysafeter/v1
kind: Task
metadata:
  name: my-task
spec:
  agent: test-agent
  prompt: Do something.
  timeout: 5m
  maxRetries: 3
"#;
        let manifest: TaskManifest = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(manifest.metadata.name, "my-task");
        assert_eq!(manifest.spec.agent, "test-agent");
        assert_eq!(manifest.spec.max_retries, 3);
        assert_eq!(
            parse_duration(manifest.spec.timeout.as_deref().unwrap()),
            300
        );
    }
}
