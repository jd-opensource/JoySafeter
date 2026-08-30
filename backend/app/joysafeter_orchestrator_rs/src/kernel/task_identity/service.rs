use std::collections::HashMap;
use std::sync::Arc;

use tracing::{debug, warn};

use crate::ids::{AgentId, ProjectId, SessionId, TaskId, UserId};
use crate::kernel::agent_identity_provider::{
    AgentIdentityInjection, AgentIdentityProvider, IdentityEgressRequestTarget,
    IdentityResolveContext, NoopAgentIdentityProvider,
};

use super::error::TaskIdentityContextError;
use super::material::{TaskIdentityMaterial, TaskIdentityMaterialError};
use super::store::{IdentityMaterialClaim, StoredIdentityMaterial, TaskIdentityStore};

/// Task-scoped identity context loaded from the internal identity table.
pub(crate) struct LoadedIdentityContext {
    /// User's SSO cookie (Web scenario). Empty if auth_code is used.
    identity_token: String,
    /// Provider-approved request metadata captured with the identity token.
    headers_map: HashMap<String, String>,
    /// One-time BotAuthCode (API scenario). None if identity_token is used.
    auth_code: Option<String>,
    /// User name / email for cache keying.
    user_name: String,
    /// Immutable authenticated user ID.
    user_id: UserId,
}

type LoadedIdentityRow = (UserId, Option<String>, String, String);
type PersistedIdentityRow = (UserId, Option<String>, String, Option<String>);

pub(crate) trait TaskIdentitySubject: Sync {
    fn agent_id(&self) -> AgentId;
    fn provider_config(&self) -> Option<&serde_json::Value>;
}

fn require_identity_material(
    row: Option<PersistedIdentityRow>,
) -> Result<Option<LoadedIdentityRow>, TaskIdentityContextError> {
    row.map(
        |(user_id, user_name, credential_kind, encrypted_credential)| {
            Ok((
                user_id,
                user_name,
                credential_kind,
                encrypted_credential.ok_or(TaskIdentityMaterialError::FieldMissing)?,
            ))
        },
    )
    .transpose()
}

fn decode_revealed_identity_material(
    credential_kind: &str,
    credential: String,
) -> Result<(String, HashMap<String, String>, Option<String>), TaskIdentityContextError> {
    match credential_kind {
        "auth_code" => Ok((String::new(), HashMap::new(), Some(credential))),
        "identity_token" => {
            let Ok(envelope) = serde_json::from_str::<serde_json::Value>(&credential) else {
                return Ok((credential, HashMap::new(), None));
            };
            let envelope = envelope
                .as_object()
                .ok_or(TaskIdentityContextError::ContextInvalid)?;
            if envelope.get("version").and_then(serde_json::Value::as_u64) != Some(1) {
                return Err(TaskIdentityContextError::ContextInvalid);
            }
            let identity_token = envelope
                .get("identity_token")
                .and_then(serde_json::Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .ok_or(TaskIdentityContextError::ContextInvalid)?
                .to_string();
            let headers = envelope
                .get("headers_map")
                .and_then(serde_json::Value::as_object)
                .ok_or(TaskIdentityContextError::ContextInvalid)?;
            if headers.len() > 5 {
                return Err(TaskIdentityContextError::ContextInvalid);
            }
            let allowed_headers = [
                "Cookie",
                "Accept-Language",
                "User-Agent",
                "X-Forwarded-For",
                "X-Real-IP",
            ];
            let mut headers_map = HashMap::with_capacity(headers.len());
            for (name, value) in headers {
                if !allowed_headers.contains(&name.as_str()) {
                    return Err(TaskIdentityContextError::ContextInvalid);
                }
                let value = value
                    .as_str()
                    .filter(|value| {
                        !value.is_empty() && value.len() <= 4096 && !value.contains(['\r', '\n'])
                    })
                    .ok_or(TaskIdentityContextError::ContextInvalid)?;
                headers_map.insert(name.clone(), value.to_string());
            }
            Ok((identity_token, headers_map, None))
        }
        _ => Err(TaskIdentityContextError::KindInvalid),
    }
}

impl std::fmt::Debug for LoadedIdentityContext {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LoadedIdentityContext")
            .field("identity_token", &"<redacted>")
            .field("auth_code", &self.auth_code.as_ref().map(|_| "<redacted>"))
            .field("user_name", &self.user_name)
            .field("user_id", &self.user_id)
            .finish()
    }
}

#[derive(Clone)]
pub(crate) struct TaskIdentityService {
    store: Arc<dyn TaskIdentityStore>,
    provider: Arc<dyn AgentIdentityProvider>,
    allowed_hosts: Vec<String>,
    material: Arc<dyn TaskIdentityMaterial>,
}

impl TaskIdentityService {
    pub(crate) fn new(
        store: Arc<dyn TaskIdentityStore>,
        material: Arc<dyn TaskIdentityMaterial>,
        allowed_hosts: Vec<String>,
    ) -> Self {
        Self {
            store,
            provider: Arc::new(NoopAgentIdentityProvider),
            allowed_hosts: allowed_hosts
                .into_iter()
                .map(|host| host.trim().trim_end_matches('.').to_lowercase())
                .filter(|host| !host.is_empty())
                .collect(),
            material,
        }
    }

    pub(crate) fn with_provider(mut self, provider: Arc<dyn AgentIdentityProvider>) -> Self {
        self.provider = provider;
        self
    }

    #[cfg(test)]
    pub(crate) fn set_provider(&mut self, provider: Arc<dyn AgentIdentityProvider>) {
        self.provider = provider;
    }

    #[cfg(test)]
    pub(crate) fn set_allowed_hosts(&mut self, allowed_hosts: Vec<String>) {
        self.allowed_hosts = allowed_hosts;
    }

    #[cfg(test)]
    pub(crate) fn set_material(&mut self, material: Arc<dyn TaskIdentityMaterial>) {
        self.material = material;
    }

    pub(crate) fn enabled(&self) -> bool {
        self.provider.enabled()
    }

    /// Resolve task-scoped agent identity via the pluggable provider.
    pub(crate) async fn resolve_injection(
        &self,
        subject: Option<&dyn TaskIdentitySubject>,
        task_id: TaskId,
        session_id: Option<SessionId>,
        project_id: Option<ProjectId>,
        candidate_targets: &[IdentityEgressRequestTarget],
    ) -> Result<Option<AgentIdentityInjection>, TaskIdentityContextError> {
        let subject = subject.ok_or(TaskIdentityContextError::ScopeMissing)?;
        let session_id = session_id.ok_or(TaskIdentityContextError::ScopeMissing)?;
        let project_id = project_id.ok_or(TaskIdentityContextError::ScopeMissing)?;
        let mut egress_targets = candidate_targets.to_vec();
        egress_targets.sort_by(|left, right| left.route_id.cmp(&right.route_id));
        egress_targets.dedup_by(|left, right| left.route_id == right.route_id);
        if egress_targets.is_empty()
            || egress_targets
                .iter()
                .any(|target| !Self::host_allowed(&target.host, &self.allowed_hosts))
        {
            return Err(TaskIdentityContextError::NoTrustedHosts);
        }
        // Provider config is optional (global mode); pass agent_identity block if
        // present, otherwise an empty object.
        let provider_config = subject
            .provider_config()
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));

        let claim = match self.store.claim_material(task_id, project_id).await? {
            IdentityMaterialClaim::Claimed(claim) => Some(claim),
            IdentityMaterialClaim::Busy => return Err(TaskIdentityContextError::ClaimConflict),
            IdentityMaterialClaim::Unavailable => None,
        };
        let identity_ctx = match claim.as_ref() {
            Some(claim) => match self.decode_stored_context(&claim.material) {
                Ok(context) => context,
                Err(error) => {
                    self.store
                        .release_claim(task_id, project_id, claim.resolution_id)
                        .await?;
                    return Err(error);
                }
            },
            None => {
                let actor = self.store.load_task_actor(task_id, project_id).await?;
                LoadedIdentityContext {
                    identity_token: String::new(),
                    headers_map: HashMap::new(),
                    auth_code: None,
                    user_name: actor.user_name.unwrap_or_else(|| actor.user_id.to_public()),
                    user_id: actor.user_id,
                }
            }
        };
        debug!(
            agent_id = %subject.agent_id(),
            targets = egress_targets.len(),
            "agent identity: resolving with environment routes"
        );

        let context = IdentityResolveContext {
            project_id,
            user_id: identity_ctx.user_id,
            agent_id: subject.agent_id(),
            session_id,
            task_id,
            identity_token: identity_ctx.identity_token,
            headers_map: identity_ctx.headers_map,
            auth_code: identity_ctx.auth_code,
            user_name: identity_ctx.user_name,
            provider_config,
            egress_targets,
        };

        let provider_result = match self.provider.resolve(&context).await {
            Ok(injection) => Self::validate_provider_injection(&context.egress_targets, injection),
            Err(e) => {
                warn!(
                    agent_id = %subject.agent_id(),
                    error = %e,
                    "agent identity provider failed"
                );
                Err(TaskIdentityContextError::Provider)
            }
        };
        let injection = match provider_result {
            Ok(injection) => injection,
            Err(error) => {
                if let Some(claim) = claim {
                    self.store
                        .release_claim(task_id, project_id, claim.resolution_id)
                        .await?;
                }
                return Err(error);
            }
        };
        if let Some(claim) = claim {
            self.store
                .complete_claim(task_id, project_id, claim.resolution_id)
                .await?;
        }
        Ok(Some(injection))
    }

    pub(crate) fn decode_context(
        &self,
        row: Option<LoadedIdentityRow>,
    ) -> Result<Option<LoadedIdentityContext>, TaskIdentityContextError> {
        let Some((user_id, user_name, credential_kind, encrypted_credential)) = row else {
            return Ok(None);
        };
        let credential = self.material.reveal(&encrypted_credential)?;
        let (identity_token, headers_map, auth_code) =
            decode_revealed_identity_material(&credential_kind, credential)?;

        Ok(Some(LoadedIdentityContext {
            identity_token,
            headers_map,
            auth_code,
            user_name: user_name.unwrap_or_else(|| user_id.to_public()),
            user_id,
        }))
    }

    fn decode_stored_context(
        &self,
        row: &StoredIdentityMaterial,
    ) -> Result<LoadedIdentityContext, TaskIdentityContextError> {
        self.decode_context(require_identity_material(Some((
            row.user_id,
            row.user_name.clone(),
            row.credential_kind.clone(),
            Some(row.encrypted_credential.clone()),
        )))?)?
        .ok_or(TaskIdentityContextError::ContextInvalid)
    }

    fn validate_provider_injection(
        expected_targets: &[IdentityEgressRequestTarget],
        injection: AgentIdentityInjection,
    ) -> Result<AgentIdentityInjection, TaskIdentityContextError> {
        if injection.targets.is_empty() {
            return Err(TaskIdentityContextError::EmptyInjection);
        }
        if injection.targets.len() != expected_targets.len() {
            return Err(TaskIdentityContextError::RouteMismatch);
        }
        let mut seen = std::collections::HashSet::with_capacity(injection.targets.len());
        for target in &injection.targets {
            if !seen.insert(target.route_id.as_str()) {
                return Err(TaskIdentityContextError::RouteMismatch);
            }
            let Some(expected) = expected_targets
                .iter()
                .find(|expected| expected.route_id == target.route_id)
            else {
                return Err(TaskIdentityContextError::RouteMismatch);
            };
            if !expected.host.eq_ignore_ascii_case(&target.host)
                || expected.port != target.port
                || expected.tls != target.tls
            {
                return Err(TaskIdentityContextError::RouteMismatch);
            }
        }
        Ok(injection)
    }

    pub(crate) fn host_allowed(host: &str, allowed_hosts: &[String]) -> bool {
        let host = host.trim().trim_end_matches('.').to_lowercase();
        allowed_hosts.iter().any(|allowed| {
            if let Some(suffix) = allowed.strip_prefix("*.") {
                host != suffix && host.ends_with(&format!(".{suffix}"))
            } else {
                host == *allowed
            }
        })
    }
}
