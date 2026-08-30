use std::path::Path;

use joysafeter_types::agent::McpServerConfig;
use joysafeter_types::harness::{CustomToolDefinition, HarnessError};
use joysafeter_types::tool_policy::{ToolDecision, ToolPolicy, ToolSelector};

pub async fn prepare_claude_project_config(
    work_dir: &Path,
    mcp_servers: &[McpServerConfig],
    custom_tools: &[CustomToolDefinition],
    tool_policy: &ToolPolicy,
) -> Result<(), HarnessError> {
    let mcp_path = work_dir.join(".mcp.json");
    let mcp_servers = mcp_servers
        .iter()
        .map(|server| match server {
            McpServerConfig::StreamableHttp { name, url } => (
                name.clone(),
                serde_json::json!({"type": "http", "url": url}),
            ),
            McpServerConfig::Sse { name, url } => {
                (name.clone(), serde_json::json!({"type": "sse", "url": url}))
            }
            McpServerConfig::LocalStdio {
                name,
                command,
                args,
                env,
            } => {
                let mut entry = serde_json::json!({"command": command, "args": args});
                if !env.is_empty() {
                    entry["env"] = serde_json::json!(env);
                }
                (name.clone(), entry)
            }
        })
        .collect::<serde_json::Map<_, _>>();
    write_json(&mcp_path, &serde_json::json!({"mcpServers": mcp_servers})).await?;

    let claude_dir = work_dir.join(".claude");
    tokio::fs::create_dir_all(&claude_dir)
        .await
        .map_err(|error| {
            HarnessError::StartFailed(format!("mkdir {}: {error}", claude_dir.display()))
        })?;

    let mut settings = serde_json::Map::new();
    if !mcp_servers.is_empty() {
        settings.insert(
            "enableAllProjectMcpServers".to_string(),
            serde_json::Value::Bool(true),
        );
    }
    if !custom_tools.is_empty() {
        settings.insert(
            "customTools".to_string(),
            serde_json::to_value(custom_tools).map_err(|error| {
                HarnessError::StartFailed(format!("serialize custom tools: {error}"))
            })?,
        );
    }

    let (allow, ask, deny) = claude_permission_rules(tool_policy);
    if !allow.is_empty() || !ask.is_empty() || !deny.is_empty() {
        let mut permissions = serde_json::Map::new();
        if !allow.is_empty() {
            permissions.insert("allow".to_string(), serde_json::json!(allow));
        }
        if !ask.is_empty() {
            permissions.insert("ask".to_string(), serde_json::json!(ask));
        }
        if !deny.is_empty() {
            permissions.insert("deny".to_string(), serde_json::json!(deny));
        }
        settings.insert(
            "permissions".to_string(),
            serde_json::Value::Object(permissions),
        );
    }

    write_json(
        &claude_dir.join("settings.json"),
        &serde_json::Value::Object(settings),
    )
    .await
}

fn claude_permission_rules(tool_policy: &ToolPolicy) -> (Vec<String>, Vec<String>, Vec<String>) {
    let mut allow = Vec::new();
    let mut ask = Vec::new();
    let mut deny = Vec::new();
    for rule in tool_policy.rules() {
        let name = match &rule.selector {
            ToolSelector::Builtin { name } => name.clone(),
            ToolSelector::Mcp { server, tool } => {
                format!("mcp__{server}__{}", tool.as_deref().unwrap_or("*"))
            }
        };
        match rule.decision {
            ToolDecision::Allow => allow.push(name),
            ToolDecision::Ask => ask.push(name),
            ToolDecision::Deny => deny.push(name),
        }
    }
    (allow, ask, deny)
}

async fn write_json(path: &Path, value: &serde_json::Value) -> Result<(), HarnessError> {
    let content = serde_json::to_vec_pretty(value).map_err(|error| {
        HarnessError::StartFailed(format!("serialize {}: {error}", path.display()))
    })?;
    tokio::fs::write(path, content)
        .await
        .map_err(|error| HarnessError::StartFailed(format!("write {}: {error}", path.display())))
}
