use std::collections::HashMap;

use crate::db::models::JoySafeterAgent;
use crate::ids::{CredentialId, ProjectId};
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::error::CredentialRuntimeError;
use crate::kernel::credentials::service::ResolvedServiceCredential;
use crate::kernel::llm_catalog::RuntimeCredentialBinding;
use crate::kernel::run_spec::environment_credential_ids;

/// Normalizes a stored secret `protocol` into the container-env signal read by
/// pi-entrypoint.sh. Returns `None` for `custom`/blank so we never emit a
/// meaningless `JOYSAFETER_MODEL_PROTOCOL`.
pub(crate) fn model_protocol_env_value(protocol: &str) -> Option<String> {
    match protocol.trim() {
        "" | "custom" => None,
        other => Some(other.to_string()),
    }
}

/// Maps a stored secret `protocol` to the ccb provider-switch env var that flips
/// the native harness off its default Anthropic path. ccb ignores `OPENAI_BASE_URL`
/// on its own — without `CLAUDE_CODE_USE_OPENAI` set it stays in first-party
/// Anthropic mode and demands a login, so OpenAI-family models fail with
/// "Not logged in". Returns `None` for Anthropic/custom/blank, which need no switch.
pub(crate) fn model_protocol_provider_switch(protocol: &str) -> Option<&'static str> {
    match protocol.trim() {
        "openai_responses" | "chat_completions" => Some("CLAUDE_CODE_USE_OPENAI"),
        _ => None,
    }
}

pub(crate) async fn resolve_agent_env_from(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    agent: Option<&JoySafeterAgent>,
    environment: Option<&EnvironmentRow>,
) -> anyhow::Result<ResolvedAgentEnv> {
    let mut env = HashMap::new();
    let Some(agent) = agent else {
        return Ok(ResolvedAgentEnv::default());
    };

    if let Some(environment) = environment {
        if let Some(env_vars) = environment
            .config
            .get("env_vars")
            .and_then(|v| v.as_object())
        {
            for (key, value) in env_vars {
                let value = value
                    .as_str()
                    .map(ToOwned::to_owned)
                    .unwrap_or_else(|| value.to_string());
                env.insert(key.clone(), value);
            }
        }

        // Environment-level credentials use canonical `cred_` ids and resolve
        // against `joysafeter_credentials` with kind=service.
        for credential_id in environment_credential_ids(&environment.config)? {
            merge_credential_ref_into_env(
                credential_access,
                access_context,
                &mut env,
                credential_id,
                agent.project_id,
                false,
                None,
            )
            .await?;
        }
    }

    if let Some(model_credential_id) = agent.model_credential_id {
        let llm_binding = merge_credential_ref_into_env(
            credential_access,
            access_context,
            &mut env,
            model_credential_id,
            agent.project_id,
            true,
            Some(agent.engine_kind.as_deref().unwrap_or("claude")),
        )
        .await?;
        if let Some(obj) = agent.env.as_ref().and_then(|v| v.as_object()) {
            for (key, value) in obj {
                let value = value
                    .as_str()
                    .map(ToOwned::to_owned)
                    .unwrap_or_else(|| value.to_string());
                env.insert(key.clone(), value);
            }
        }
        return Ok(ResolvedAgentEnv {
            values: env,
            llm_binding,
        });
    }

    if let Some(obj) = agent.env.as_ref().and_then(|v| v.as_object()) {
        for (key, value) in obj {
            let value = value
                .as_str()
                .map(ToOwned::to_owned)
                .unwrap_or_else(|| value.to_string());
            env.insert(key.clone(), value);
        }
    }

    Ok(ResolvedAgentEnv {
        values: env,
        llm_binding: None,
    })
}

async fn merge_credential_ref_into_env(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    env: &mut HashMap<String, String>,
    credential_id: CredentialId,
    project_id: Option<ProjectId>,
    override_existing: bool,
    runtime_engine_kind: Option<&str>,
) -> anyhow::Result<Option<RuntimeCredentialBinding>> {
    let project_id = project_id.ok_or(CredentialRuntimeError::ProjectMismatch)?;
    if let Some(engine_kind) = runtime_engine_kind {
        let resolved = credential_access
            .resolve_model(&project_id, credential_id, engine_kind, access_context)
            .await?;
        if override_existing {
            if let Some(value) = model_protocol_env_value(&resolved.protocol_id) {
                env.insert("JOYSAFETER_MODEL_PROTOCOL".to_string(), value);
            }
        }
        // ccb only routes to a non-Anthropic provider when the matching
        // CLAUDE_CODE_USE_* switch is set; the egress-repointed base URL and
        // placeholder key are otherwise ignored and the native harness falls
        // back to the Anthropic /login gate ("Not logged in"). Only the native
        // ccb harness reads CLAUDE_CODE_USE_*; other engines (codex, pi) handle
        // OpenAI-compatible providers natively and must not get the switch.
        if engine_kind == "native" {
            if let Some(switch) = model_protocol_provider_switch(&resolved.protocol_id) {
                if override_existing || !env.contains_key(switch) {
                    env.insert(switch.to_string(), "1".to_string());
                }
            }
        }
        for (key, value) in resolved.material.iter() {
            if override_existing || !env.contains_key(key) {
                env.insert(key.to_string(), value.to_string());
            }
        }
        return Ok(Some(resolved.runtime_binding()));
    }

    let resolved = credential_access
        .resolve_environment(&project_id, credential_id, access_context)
        .await?;
    let ResolvedServiceCredential::Environment(material) = resolved else {
        return Err(CredentialRuntimeError::CorruptRecord.into());
    };
    let material = material
        .as_object()
        .ok_or(CredentialRuntimeError::CorruptRecord)?;
    for (key, value) in material {
        if override_existing || !env.contains_key(key) {
            let value = value
                .as_str()
                .ok_or(CredentialRuntimeError::CorruptRecord)?;
            env.insert(key.clone(), value.to_string());
        }
    }
    Ok(None)
}

#[derive(Debug)]
pub(crate) struct EnvironmentRow {
    pub(crate) config: serde_json::Value,
    pub(crate) image_tag: Option<String>,
}

#[derive(Debug, Default)]
pub(crate) struct ResolvedAgentEnv {
    pub(crate) values: HashMap<String, String>,
    pub(crate) llm_binding: Option<RuntimeCredentialBinding>,
}

#[cfg(test)]
mod tests {
    use super::{model_protocol_env_value, model_protocol_provider_switch};

    #[test]
    fn maps_known_protocols() {
        assert_eq!(
            model_protocol_env_value("openai_responses"),
            Some("openai_responses".to_string())
        );
        assert_eq!(
            model_protocol_env_value("chat_completions"),
            Some("chat_completions".to_string())
        );
        assert_eq!(
            model_protocol_env_value("anthropic_messages"),
            Some("anthropic_messages".to_string())
        );
    }

    #[test]
    fn ignores_custom_and_blank_protocols() {
        assert_eq!(model_protocol_env_value("custom"), None);
        assert_eq!(model_protocol_env_value(""), None);
        assert_eq!(model_protocol_env_value("   "), None);
    }

    #[test]
    fn openai_family_protocols_enable_native_provider_switch() {
        assert_eq!(
            model_protocol_provider_switch("openai_responses"),
            Some("CLAUDE_CODE_USE_OPENAI")
        );
        assert_eq!(
            model_protocol_provider_switch(" chat_completions "),
            Some("CLAUDE_CODE_USE_OPENAI")
        );
    }

    #[test]
    fn non_openai_protocols_do_not_enable_native_provider_switch() {
        assert_eq!(model_protocol_provider_switch("anthropic_messages"), None);
        assert_eq!(model_protocol_provider_switch("custom"), None);
        assert_eq!(model_protocol_provider_switch(""), None);
    }
}
