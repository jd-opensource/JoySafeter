use serde_json::Value;

use crate::db::models::{JoySafeterAgent, JoySafeterSession};

#[derive(Debug, Clone)]
pub struct SnapshotEnvironment {
    pub config: Value,
    pub image_tag: Option<String>,
}

pub fn agent_for_execution(
    live_agent: Option<JoySafeterAgent>,
    session: Option<&JoySafeterSession>,
) -> Option<JoySafeterAgent> {
    let snapshot = session.and_then(|session| session.agent_snapshot.as_ref());
    if live_agent.is_none() && snapshot.is_none() {
        return None;
    }

    let live = live_agent.as_ref();
    let session_agent_id = session.and_then(|session| session.agent_id);
    let id = live
        .map(|agent| agent.id)
        .or(session_agent_id)
        .or_else(|| snapshot.and_then(|snapshot| snapshot_string(snapshot, "id")?.parse().ok()))?;
    let project_id = live
        .and_then(|agent| agent.project_id.clone())
        .or_else(|| session.and_then(|session| session.project_id.clone()));
    let session_version = session.and_then(|session| session.agent_version);

    Some(JoySafeterAgent {
        id,
        project_id,
        name: snapshot_string_override(snapshot, "name")
            .flatten()
            .or_else(|| live.map(|agent| agent.name.clone()))
            .unwrap_or_else(|| "snapshot-agent".to_string()),
        engine_kind: snapshot_string_override(snapshot, "engine_kind")
            .flatten()
            .or_else(|| live.and_then(|agent| agent.engine_kind.clone())),
        model: snapshot_model_override(snapshot)
            .unwrap_or_else(|| live.and_then(|agent| agent.model.clone())),
        system_prompt: snapshot_string_override(snapshot, "system_prompt")
            .or_else(|| snapshot_string_override(snapshot, "system"))
            .unwrap_or_else(|| live.and_then(|agent| agent.system_prompt.clone())),
        description: snapshot_string_override(snapshot, "description")
            .unwrap_or_else(|| live.and_then(|agent| agent.description.clone())),
        env: snapshot_value_override(snapshot, "env")
            .unwrap_or_else(|| live.and_then(|agent| agent.env.clone())),
        mcp_configs: snapshot_value_override(snapshot, "mcp_configs")
            .or_else(|| snapshot_value_override(snapshot, "mcp_servers"))
            .unwrap_or_else(|| live.and_then(|agent| agent.mcp_configs.clone())),
        skills: snapshot_value_override(snapshot, "skills")
            .unwrap_or_else(|| live.and_then(|agent| agent.skills.clone())),
        agents: snapshot_value_override(snapshot, "agents")
            .unwrap_or_else(|| live.and_then(|agent| agent.agents.clone())),
        commands: snapshot_value_override(snapshot, "commands")
            .unwrap_or_else(|| live.and_then(|agent| agent.commands.clone())),
        tools: snapshot_value_override(snapshot, "tools")
            .unwrap_or_else(|| live.and_then(|agent| agent.tools.clone())),
        permission_mode: snapshot_string_override(snapshot, "permission_mode")
            .unwrap_or_else(|| live.and_then(|agent| agent.permission_mode.clone())),
        metadata: snapshot_value_override(snapshot, "metadata")
            .unwrap_or_else(|| live.and_then(|agent| agent.metadata.clone())),
        multiagent: snapshot_value_override(snapshot, "multiagent")
            .unwrap_or_else(|| live.and_then(|agent| agent.multiagent.clone())),
        version: snapshot_i32(snapshot, "version")
            .or(session_version)
            .or_else(|| live.map(|agent| agent.version))
            .unwrap_or(1),
        environment_ref: snapshot_string_override(snapshot, "environment_ref").unwrap_or_else(
            || {
                session
                    .and_then(|session| session.environment_ref.clone())
                    .or_else(|| live.and_then(|agent| agent.environment_ref.clone()))
            },
        ),
        secret_ref: snapshot_string_override(snapshot, "secret_ref")
            .unwrap_or_else(|| live.and_then(|agent| agent.secret_ref.clone())),
    })
}

pub fn environment_for_execution(
    session: Option<&JoySafeterSession>,
) -> Option<SnapshotEnvironment> {
    let environment = session?
        .agent_snapshot
        .as_ref()?
        .get("environment")?
        .as_object()?;
    let config = environment
        .get("config")
        .filter(|value| !value.is_null())
        .cloned()
        .unwrap_or_else(|| serde_json::json!({}));
    let image_tag = environment
        .get("image_tag")
        .and_then(|value| value.as_str())
        .map(ToOwned::to_owned);
    Some(SnapshotEnvironment { config, image_tag })
}

fn snapshot_value_override(snapshot: Option<&Value>, key: &str) -> Option<Option<Value>> {
    snapshot.and_then(|snapshot| {
        snapshot
            .as_object()
            .and_then(|object| object.get(key))
            .map(|value| {
                if value.is_null() {
                    None
                } else {
                    Some(value.clone())
                }
            })
    })
}

fn snapshot_string_override(snapshot: Option<&Value>, key: &str) -> Option<Option<String>> {
    snapshot.and_then(|snapshot| {
        snapshot
            .as_object()
            .and_then(|object| object.get(key))
            .map(|value| value.as_str().map(ToOwned::to_owned))
    })
}

fn snapshot_string(snapshot: &Value, key: &str) -> Option<String> {
    snapshot.get(key)?.as_str().map(ToOwned::to_owned)
}

fn snapshot_i32(snapshot: Option<&Value>, key: &str) -> Option<i32> {
    snapshot?
        .get(key)?
        .as_i64()
        .and_then(|value| i32::try_from(value).ok())
}

fn snapshot_model_override(snapshot: Option<&Value>) -> Option<Option<String>> {
    snapshot.and_then(|snapshot| {
        snapshot
            .as_object()
            .and_then(|object| object.get("model"))
            .map(|value| {
                if value.is_null() {
                    None
                } else if let Some(model) = value.as_str() {
                    Some(model.to_string())
                } else {
                    value
                        .get("id")
                        .and_then(|id| id.as_str())
                        .map(ToOwned::to_owned)
                }
            })
    })
}
