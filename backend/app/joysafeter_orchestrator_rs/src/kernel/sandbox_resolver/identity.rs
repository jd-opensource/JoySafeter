use std::collections::HashMap;
use std::sync::Arc;

use sqlx::{PgPool, Postgres, Transaction};
use tracing::{debug, warn};

use crate::db::models::JoySafeterAgent;
use crate::ids::{ProjectId, SessionId, TaskId, UserId};
use crate::kernel::agent_identity_provider::{
    AgentIdentityInjection, AgentIdentityProvider, IdentityEgressRequestTarget,
    IdentityResolveContext, NoopAgentIdentityProvider,
};
use crate::kernel::network_policy::envoy_model::EgressCredentialRoute;
use crate::kernel::task_identity::material::{
    TaskIdentityMaterialAdapter, TaskIdentityMaterialError,
};

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

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub(crate) enum TaskIdentityContextError {
    #[error("task identity database operation failed")]
    Database,
    #[error("task identity project does not match")]
    ProjectMismatch,
    #[error("task identity requires project and session scope")]
    ScopeMissing,
    #[error("task identity requires an authenticated task actor")]
    ActorMissing,
    #[error(transparent)]
    Material(#[from] TaskIdentityMaterialError),
    #[error("task identity credential kind is invalid")]
    KindInvalid,
    #[error("task identity context is invalid")]
    ContextInvalid,
    #[error("task identity provider is disabled for a requested route")]
    ProviderDisabled,
    #[error("task identity has no trusted egress hosts")]
    NoTrustedHosts,
    #[error("task identity provider returned no injection targets")]
    EmptyInjection,
    #[error("task identity provider failed")]
    Provider,
    #[error("task identity provider returned a mismatched route")]
    RouteMismatch,
    #[error("task identity claim changed while locked")]
    ClaimConflict,
}

#[derive(Clone)]
pub(crate) struct TaskIdentityService {
    pool: PgPool,
    provider: Arc<dyn AgentIdentityProvider>,
    allowed_hosts: Vec<String>,
    material: Option<TaskIdentityMaterialAdapter>,
}

impl TaskIdentityService {
    pub(crate) fn new(pool: PgPool) -> Self {
        Self {
            pool,
            provider: Arc::new(NoopAgentIdentityProvider),
            allowed_hosts: Self::allowed_hosts_from_env(),
            material: None,
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
    pub(crate) fn set_material(&mut self, material: TaskIdentityMaterialAdapter) {
        self.material = Some(material);
    }

    pub(crate) fn enabled(&self) -> bool {
        self.provider.enabled()
    }

    /// Resolve task-scoped agent identity via the pluggable provider.
    pub(crate) async fn resolve_injection(
        &self,
        agent: Option<&JoySafeterAgent>,
        task_id: TaskId,
        session_id: Option<SessionId>,
        project_id: Option<ProjectId>,
        candidate_targets: &[IdentityEgressRequestTarget],
    ) -> Result<Option<AgentIdentityInjection>, TaskIdentityContextError> {
        let agent = agent.ok_or(TaskIdentityContextError::ScopeMissing)?;
        // Provider config is optional (global mode); pass agent_identity block if
        // present, otherwise an empty object.
        let provider_config = agent
            .metadata
            .as_ref()
            .and_then(|m| m.get("agent_identity"))
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));

        let mut transaction = self
            .pool
            .begin()
            .await
            .map_err(|_| TaskIdentityContextError::Database)?;
        let captured_identity_ctx = self
            .load_context_for_update(&mut transaction, task_id, project_id)
            .await?;
        let has_captured_material = captured_identity_ctx.is_some();
        let identity_ctx = match captured_identity_ctx {
            Some(context) => context,
            None => {
                self.load_task_actor_context_for_update(&mut transaction, task_id, project_id)
                    .await?
            }
        };
        if candidate_targets.is_empty()
            || candidate_targets
                .iter()
                .any(|target| !Self::host_allowed(&target.host, &self.allowed_hosts))
        {
            return Err(TaskIdentityContextError::NoTrustedHosts);
        }
        if has_captured_material
            && !Self::consume_locked_context(&mut transaction, task_id, project_id).await?
        {
            return Err(TaskIdentityContextError::ClaimConflict);
        }
        transaction
            .commit()
            .await
            .map_err(|_| TaskIdentityContextError::Database)?;

        let mut egress_targets = candidate_targets.to_vec();
        egress_targets.sort_by(|left, right| left.route_id.cmp(&right.route_id));
        egress_targets.dedup_by(|left, right| left.route_id == right.route_id);
        if egress_targets.is_empty() {
            return Err(TaskIdentityContextError::NoTrustedHosts);
        }
        debug!(
            agent_id = %agent.id,
            targets = egress_targets.len(),
            "agent identity: resolving with environment routes"
        );

        let context = IdentityResolveContext {
            project_id: project_id.ok_or(TaskIdentityContextError::ScopeMissing)?,
            user_id: identity_ctx.user_id,
            agent_id: agent.id,
            session_id: session_id.ok_or(TaskIdentityContextError::ScopeMissing)?,
            task_id,
            identity_token: identity_ctx.identity_token,
            headers_map: identity_ctx.headers_map,
            auth_code: identity_ctx.auth_code,
            user_name: identity_ctx.user_name,
            provider_config,
            egress_targets,
        };

        match self.provider.resolve(&context).await {
            Ok(injection) if !injection.targets.is_empty() => Ok(Some(injection)),
            Ok(_) => Err(TaskIdentityContextError::EmptyInjection),
            Err(e) => {
                warn!(
                    agent_id = %agent.id,
                    error = %e,
                    "agent identity provider failed"
                );
                Err(TaskIdentityContextError::Provider)
            }
        }
    }

    async fn load_task_actor_context_for_update(
        &self,
        transaction: &mut Transaction<'_, Postgres>,
        task_id: TaskId,
        project_id: Option<ProjectId>,
    ) -> Result<LoadedIdentityContext, TaskIdentityContextError> {
        let row: Option<(Option<ProjectId>, Option<UserId>, Option<String>)> = sqlx::query_as(
            r#"
            SELECT task.project_id, task.user_id, actor.email
            FROM joysafeter_tasks AS task
            LEFT JOIN joysafeter_users AS actor ON actor.id = task.user_id
            WHERE task.id = $1
            FOR UPDATE OF task
            "#,
        )
        .bind(task_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        let Some((task_project_id, user_id, user_name)) = row else {
            return Err(TaskIdentityContextError::Database);
        };
        if task_project_id != project_id {
            return Err(TaskIdentityContextError::ProjectMismatch);
        }
        let user_id = user_id.ok_or(TaskIdentityContextError::ActorMissing)?;
        Ok(LoadedIdentityContext {
            identity_token: String::new(),
            headers_map: HashMap::new(),
            auth_code: None,
            user_name: user_name.unwrap_or_else(|| user_id.to_public()),
            user_id,
        })
    }

    async fn load_context_for_update(
        &self,
        transaction: &mut Transaction<'_, Postgres>,
        task_id: TaskId,
        project_id: Option<ProjectId>,
    ) -> Result<Option<LoadedIdentityContext>, TaskIdentityContextError> {
        let persisted_project: Option<Option<ProjectId>> = sqlx::query_scalar(
            r#"
            SELECT project_id
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
            FOR UPDATE
            "#,
        )
        .bind(task_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        let Some(persisted_project) = persisted_project else {
            return Ok(None);
        };
        if persisted_project != project_id {
            return Err(TaskIdentityContextError::ProjectMismatch);
        }

        let row: Option<PersistedIdentityRow> = sqlx::query_as(
            r#"
            SELECT user_id, user_name, credential_kind, encrypted_credential
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
              AND consumed_at IS NULL
              AND expires_at > NOW()
            "#,
        )
        .bind(task_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;

        self.decode_context(task_id, require_identity_material(row)?)
    }

    #[cfg(test)]
    pub(crate) async fn load_context(
        &self,
        task_id: TaskId,
        project_id: Option<ProjectId>,
    ) -> Result<Option<LoadedIdentityContext>, TaskIdentityContextError> {
        let persisted_project: Option<Option<ProjectId>> = sqlx::query_scalar(
            r#"
            SELECT project_id
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
            "#,
        )
        .bind(task_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        let Some(persisted_project) = persisted_project else {
            return Ok(None);
        };
        if persisted_project != project_id {
            return Err(TaskIdentityContextError::ProjectMismatch);
        }

        let row: Option<PersistedIdentityRow> = sqlx::query_as(
            r#"
            SELECT user_id, user_name, credential_kind, encrypted_credential
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
              AND consumed_at IS NULL
              AND expires_at > NOW()
            "#,
        )
        .bind(task_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;

        self.decode_context(task_id, require_identity_material(row)?)
    }

    pub(crate) fn decode_context(
        &self,
        _task_id: TaskId,
        row: Option<LoadedIdentityRow>,
    ) -> Result<Option<LoadedIdentityContext>, TaskIdentityContextError> {
        let Some((user_id, user_name, credential_kind, encrypted_credential)) = row else {
            return Ok(None);
        };
        let credential = match &self.material {
            Some(material) => material.reveal(&encrypted_credential)?,
            None => TaskIdentityMaterialAdapter::from_env().reveal(&encrypted_credential)?,
        };
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

    async fn consume_locked_context(
        transaction: &mut Transaction<'_, Postgres>,
        task_id: TaskId,
        project_id: Option<ProjectId>,
    ) -> Result<bool, TaskIdentityContextError> {
        let result = sqlx::query(
            r#"
            UPDATE joysafeter_task_identity_contexts
            SET consumed_at = NOW(), erased_at = NOW(), encrypted_credential = NULL, updated_at = NOW()
            WHERE task_id = $1
              AND project_id IS NOT DISTINCT FROM $2
              AND consumed_at IS NULL
              AND expires_at > NOW()
              AND encrypted_credential IS NOT NULL
            "#,
        )
        .bind(task_id)
        .bind(project_id)
        .execute(&mut **transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        Ok(result.rows_affected() == 1)
    }

    fn allowed_hosts_from_env() -> Vec<String> {
        std::env::var("AGENT_IDENTITY_ALLOWED_HOSTS")
            .unwrap_or_default()
            .split(',')
            .map(|host| host.trim().trim_end_matches('.').to_lowercase())
            .filter(|host| !host.is_empty())
            .collect()
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

    pub(crate) fn merge_into_routes(
        routes: &mut [EgressCredentialRoute],
        injection: AgentIdentityInjection,
    ) -> Result<(), TaskIdentityContextError> {
        for target in injection.targets {
            let route = routes
                .iter_mut()
                .find(|route| route.id == target.route_id)
                .ok_or(TaskIdentityContextError::RouteMismatch)?;
            if !route.upstream_host.eq_ignore_ascii_case(&target.host)
                || route.upstream_port != target.port
                || route.upstream_tls != target.tls
            {
                return Err(TaskIdentityContextError::RouteMismatch);
            }
            for (name, value) in &target.inject_headers {
                route
                    .inject_headers
                    .retain(|(existing, _)| !existing.eq_ignore_ascii_case(name));
                route.inject_headers.push((name.clone(), value.clone()));
            }
            for header in &target.remove_headers {
                if !route
                    .remove_headers
                    .iter()
                    .any(|existing| existing.eq_ignore_ascii_case(header))
                {
                    route.remove_headers.push(header.clone());
                }
            }
        }
        Ok(())
    }
}

pub(crate) fn identity_lease_metadata(
    task_id: TaskId,
    refresh_after_seconds: Option<u64>,
) -> serde_json::Value {
    serde_json::json!({
        "task_id": task_id.to_string(),
        "refresh_after_seconds": refresh_after_seconds,
    })
}

pub(crate) fn identity_lease_matches(config: Option<&serde_json::Value>, task_id: TaskId) -> bool {
    config
        .and_then(|value| value.get("agent_identity_lease"))
        .and_then(|lease| lease.get("task_id"))
        .and_then(serde_json::Value::as_str)
        == Some(task_id.to_string().as_str())
}

pub(crate) fn identity_lease_refresh_after_seconds(
    config: Option<&serde_json::Value>,
) -> Option<u64> {
    config
        .and_then(|value| value.get("agent_identity_lease"))
        .and_then(|lease| lease.get("refresh_after_seconds"))
        .and_then(serde_json::Value::as_u64)
}
