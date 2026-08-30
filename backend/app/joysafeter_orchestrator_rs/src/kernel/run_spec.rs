use anyhow::Context;
use serde_json::Value;

use crate::db::models::{JoySafeterAgent, JoySafeterSession};
use crate::ids::CredentialId;
use crate::kernel::credentials::reference::{decode_environment, decode_snapshot};

#[derive(Debug, Clone)]
pub struct SnapshotEnvironment {
    pub config: Value,
    pub image_tag: Option<String>,
}

pub fn agent_for_execution(
    live_agent: Option<JoySafeterAgent>,
    session: Option<&JoySafeterSession>,
) -> anyhow::Result<Option<JoySafeterAgent>> {
    let snapshot = session.and_then(|session| session.agent_snapshot.as_ref());
    if live_agent.is_none() && snapshot.is_none() {
        return Ok(None);
    }

    let live = live_agent.as_ref();
    let session_agent_id = session.and_then(|session| session.agent_id);
    let Some(id) = live
        .map(|agent| agent.id)
        .or(session_agent_id)
        .or_else(|| snapshot.and_then(|snapshot| snapshot_string(snapshot, "id")?.parse().ok()))
    else {
        return Ok(None);
    };
    let project_id = live
        .and_then(|agent| agent.project_id.clone())
        .or_else(|| session.and_then(|session| session.project_id.clone()));
    let session_version = session.and_then(|session| session.agent_version);

    Ok(Some(JoySafeterAgent {
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
        system_prompt: snapshot_string_override(snapshot, "system")
            .unwrap_or_else(|| live.and_then(|agent| agent.system_prompt.clone())),
        description: snapshot_string_override(snapshot, "description")
            .unwrap_or_else(|| live.and_then(|agent| agent.description.clone())),
        env: snapshot_value_override(snapshot, "env")
            .unwrap_or_else(|| live.and_then(|agent| agent.env.clone())),
        mcp_servers: snapshot_value_override(snapshot, "mcp_servers")
            .unwrap_or_else(|| live.and_then(|agent| agent.mcp_servers.clone())),
        skills: snapshot_value_override(snapshot, "skills")
            .unwrap_or_else(|| live.and_then(|agent| agent.skills.clone())),
        agents: snapshot_value_override(snapshot, "agents")
            .unwrap_or_else(|| live.and_then(|agent| agent.agents.clone())),
        commands: snapshot_value_override(snapshot, "commands")
            .unwrap_or_else(|| live.and_then(|agent| agent.commands.clone())),
        tools: snapshot_value_override(snapshot, "tools")
            .unwrap_or_else(|| live.and_then(|agent| agent.tools.clone())),
        metadata: snapshot_value_override(snapshot, "metadata")
            .unwrap_or_else(|| live.and_then(|agent| agent.metadata.clone())),
        multiagent: snapshot_value_override(snapshot, "multiagent")
            .unwrap_or_else(|| live.and_then(|agent| agent.multiagent.clone())),
        version: snapshot_i32(snapshot, "version")
            .or(session_version)
            .or_else(|| live.map(|agent| agent.version))
            .unwrap_or(1),
        environment_id: match session {
            Some(session) => session.environment_id,
            None => live.and_then(|agent| agent.environment_id),
        },
        // The agent's primary model credential is now referenced by id. The
        // snapshot persists it as the canonical public id string under
        // "model_credential_id"; parse it back to a CredentialId, else fall back
        // to the live agent.
        model_credential_id: snapshot_credential_id_override(snapshot)?
            .unwrap_or_else(|| live.and_then(|agent| agent.model_credential_id)),
    }))
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

/// Resolves the model credential override from an agent snapshot.
///
/// Returns:
///   - `None`           → the snapshot has no `model_credential_id` key
///                        (fall back to the live agent);
///   - `Some(None)`     → the key is present but null/blank
///                        (explicitly no credential);
///   - `Some(Some(id))` → the key holds a canonical `cred_` public id.
fn snapshot_credential_id_override(
    snapshot: Option<&Value>,
) -> anyhow::Result<Option<Option<CredentialId>>> {
    let Some(snapshot) = snapshot else {
        return Ok(None);
    };
    decode_snapshot(snapshot)
        .map(|decoded| decoded.model_credential_override)
        .map_err(anyhow::Error::new)
        .context("persisted agent snapshot model_credential_id is invalid")
}

pub(crate) fn environment_credential_ids(config: &Value) -> anyhow::Result<Vec<CredentialId>> {
    decode_environment(config)
        .map(|decoded| decoded.direct_credential_ids)
        .map_err(anyhow::Error::new)
        .context("persisted environment credential references are invalid")
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

#[cfg(test)]
mod tests {
    use serde_json::json;
    use uuid::Uuid;

    use super::{
        environment_credential_ids, environment_for_execution, snapshot_credential_id_override,
    };
    use crate::db::models::JoySafeterSession;
    use crate::ids::{ProjectId, SessionId};

    #[test]
    fn snapshot_model_credential_rejects_malformed_public_id() {
        let snapshot = json!({
            "model_credential_id": "019f891f-6539-71d3-b791-c25814af3efd"
        });

        let error = snapshot_credential_id_override(Some(&snapshot))
            .expect_err("bare UUID in persisted snapshot must fail");

        assert!(error.to_string().contains("model_credential_id"));
    }

    #[test]
    fn environment_credential_ids_reject_malformed_public_id() {
        let config = json!({
            "environment_credential_ids": ["019f891f-6539-71d3-b791-c25814af3efd"]
        });

        let error = environment_credential_ids(&config)
            .expect_err("bare UUID in persisted environment must fail");

        assert!(error.to_string().contains("credential references"));
    }

    #[test]
    fn snapshot_environment_uses_frozen_config_without_identifier_fallback() {
        let session = JoySafeterSession {
            id: SessionId::from_uuid(Uuid::now_v7()),
            agent_id: None,
            project_id: Some(ProjectId::from_uuid(Uuid::from_u128(1))),
            status: "idle".to_string(),
            agent_version: None,
            agent_snapshot: Some(json!({
                "environment": {
                    "environment_id": "env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f011",
                    "config": {"env_vars": {"FROZEN": "yes"}}
                }
            })),
            last_harness_session_id: None,
            last_work_dir: None,
            environment_id: None,
            runtime_config_generation: 0,
            runtime_config_generation_reason: None,
            runtime_config_generation_updated_at: None,
        };

        let environment = environment_for_execution(Some(&session)).expect("snapshot environment");

        assert_eq!(environment.config["env_vars"]["FROZEN"], "yes");
    }
}
