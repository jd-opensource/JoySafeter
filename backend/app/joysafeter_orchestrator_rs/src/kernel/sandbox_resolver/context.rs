use std::sync::Arc;

use sqlx::{PgPool, Row};

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::ids::{AgentId, ProjectId, SessionId, TaskId};
use crate::kernel::agent_identity_provider::AgentIdentityProvider;
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::runtime_projection::{
    build_external_egress, build_git_egress, extract_llm_egress, resolve_agent_env_from,
    EnvironmentRow,
};
use crate::kernel::environment_binding;
use crate::kernel::mcp_runtime_plan::{
    effective_network_mode, resolve_mcp_runtime_plan_with_access, EffectiveNetworkMode,
};
use crate::kernel::network_policy::envoy_model::SandboxCredentials;
use crate::kernel::network_policy::DesiredNetworkPolicy;
use crate::kernel::run_spec::{agent_for_execution, environment_for_execution};
#[cfg(test)]
use crate::kernel::task_identity::material::TaskIdentityMaterialAdapter;
use crate::sandbox::mounts::resolve_mount_resources;

use super::identity::{TaskIdentityContextError, TaskIdentityService};
use super::model::{ExpectedFingerprint, ResolveContext};
use super::networking::SandboxNetworkingService;
use super::runtime_plan::{effective_networking_config, effective_prefixes};

#[derive(Clone)]
pub struct ResolveContextBuilder {
    pool: PgPool,
    config: JoySafeterConfig,
    networking: SandboxNetworkingService,
    identity: TaskIdentityService,
}

impl ResolveContextBuilder {
    pub fn new(
        pool: PgPool,
        config: JoySafeterConfig,
        networking: SandboxNetworkingService,
    ) -> Self {
        Self {
            identity: TaskIdentityService::new(pool.clone()),
            pool,
            config,
            networking,
        }
    }

    pub fn with_identity_provider(mut self, provider: Arc<dyn AgentIdentityProvider>) -> Self {
        self.identity = self.identity.with_provider(provider);
        self
    }

    #[cfg(test)]
    pub(crate) fn set_networking(&mut self, networking: SandboxNetworkingService) {
        self.networking = networking;
    }

    #[cfg(test)]
    pub(crate) fn set_identity_provider(&mut self, provider: Arc<dyn AgentIdentityProvider>) {
        self.identity.set_provider(provider);
    }

    #[cfg(test)]
    pub(crate) fn set_identity_allowed_hosts(&mut self, allowed_hosts: Vec<String>) {
        self.identity.set_allowed_hosts(allowed_hosts);
    }

    #[cfg(test)]
    pub(crate) fn set_task_identity_material(&mut self, material: TaskIdentityMaterialAdapter) {
        self.identity.set_material(material);
    }

    #[cfg(test)]
    pub(crate) fn identity(&self) -> &TaskIdentityService {
        &self.identity
    }

    pub(crate) async fn build(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        agent_id: Option<AgentId>,
        project_id: Option<ProjectId>,
    ) -> anyhow::Result<ResolveContext> {
        let live_agent = match agent_id {
            Some(agent_id) => queries::get_agent(&self.pool, agent_id).await?,
            None => None,
        };
        let session = match session_id {
            Some(session_id) => queries::get_session(&self.pool, session_id).await?,
            None => None,
        };
        let snapshot_environment = environment_for_execution(session.as_ref());
        let agent = agent_for_execution(live_agent, session.as_ref())?;
        let project_id = project_id
            .or_else(|| session.as_ref().and_then(|session| session.project_id))
            .or_else(|| agent.as_ref().and_then(|agent| agent.project_id));

        let live_environment = environment_binding::resolve_live_environment_binding(
            &self.pool,
            session.as_ref().and_then(|session| session.environment_id),
            agent.as_ref().and_then(|agent| agent.environment_id),
            project_id,
            session_id,
        )
        .await?;

        let environment = if let Some(snapshot_environment) = snapshot_environment {
            Some(EnvironmentRow {
                config: snapshot_environment.config,
                image_tag: snapshot_environment.image_tag,
            })
        } else {
            live_environment.map(|environment| EnvironmentRow {
                config: environment.config,
                image_tag: environment.image_tag,
            })
        };

        let engine_kind = agent
            .as_ref()
            .and_then(|agent| agent.engine_kind.clone())
            .unwrap_or_else(|| "claude".to_string());
        let image = match environment.as_ref().and_then(|env| env.image_tag.clone()) {
            Some(tag) => tag,
            None => self.config.image_for_provider(&engine_kind)?,
        };
        let access_context = CredentialAccessContext::runtime(
            session_id,
            Some(task_id),
            session
                .as_ref()
                .map(|session| session.runtime_config_generation),
        );
        let credential_access = CredentialMaterialAccessService::new(self.pool.clone());
        let resolved_env = resolve_agent_env_from(
            &credential_access,
            &access_context,
            agent.as_ref(),
            environment.as_ref(),
        )
        .await?;
        let mut env = resolved_env.values;
        let llm_binding = resolved_env.llm_binding;
        let configured_networking = environment
            .as_ref()
            .and_then(|environment| environment.config.get("networking").cloned());
        let networking = effective_networking_config(
            configured_networking,
            self.config.envoy_enabled,
            environment.as_ref(),
        )?;
        let network_mode = effective_network_mode(networking.as_ref(), self.config.envoy_enabled)?;
        let network = match network_mode {
            EffectiveNetworkMode::Limited | EffectiveNetworkMode::Disabled => {
                Some("none".to_string())
            }
            EffectiveNetworkMode::Unrestricted => None,
        };
        let runtime_generation = session
            .as_ref()
            .map(|session| session.runtime_config_generation)
            .unwrap_or(0);
        let mcp_plan = match agent.as_ref() {
            Some(agent) => Some(
                resolve_mcp_runtime_plan_with_access(
                    &credential_access,
                    &access_context,
                    project_id,
                    session_id,
                    agent.id,
                    runtime_generation,
                    network_mode,
                    agent.mcp_servers.as_ref(),
                )
                .await?,
            ),
            None => None,
        };

        let mut credentials = SandboxCredentials::default();
        let mut identity_refresh_after_seconds = None;
        if network_mode == EffectiveNetworkMode::Limited {
            let mut routes = Vec::new();
            routes.extend(extract_llm_egress(
                &mut env,
                llm_binding.as_ref(),
                &self.config.llm_egress_allowed_hosts,
            ));
            routes.extend(
                mcp_plan
                    .as_ref()
                    .map(|plan| plan.egress_routes())
                    .unwrap_or_default(),
            );
            routes.extend(build_git_egress(&self.pool, session_id).await?);
            let (external_routes, identity_targets) = build_external_egress(
                &credential_access,
                &access_context,
                environment.as_ref(),
                project_id,
            )
            .await?;
            routes.extend(external_routes);

            if !identity_targets.is_empty() {
                if self.networking.uses_remote_authority() {
                    anyhow::bail!(
                        "task-scoped Agent Identity requires secure ephemeral delivery to the elected xDS authority"
                    );
                }
                if !self.identity.enabled() {
                    return Err(TaskIdentityContextError::ProviderDisabled.into());
                }
                if let Some(injection) = self
                    .identity
                    .resolve_injection(
                        agent.as_ref(),
                        task_id,
                        session_id,
                        project_id,
                        &identity_targets,
                    )
                    .await?
                {
                    identity_refresh_after_seconds = injection.valid_for_seconds;
                    TaskIdentityService::merge_into_routes(&mut routes, injection)?;
                }
            }

            credentials = SandboxCredentials {
                routes,
                proxy_auth_token: None,
            };
        }
        let egress_policy_hash =
            DesiredNetworkPolicy::from_inputs(networking.as_ref(), &credentials)?
                .revision()
                .to_string();

        let storage_catalog = self.load_storage_volume_catalog(project_id).await?;
        let (mounts, mount_fingerprint) = resolve_mount_resources(
            environment.as_ref().map(|environment| &environment.config),
            &storage_catalog,
            &self.config.sandbox_provider,
        )?;

        Ok(ResolveContext {
            session_id,
            project_id,
            runtime_config_generation: runtime_generation,
            network,
            expected: ExpectedFingerprint {
                image,
                engine_kind,
                networking,
                env,
                mounts: mount_fingerprint,
                egress_policy_hash,
            },
            memory_mounts: vec![],
            mounts,
            credentials,
            identity_refresh_after_seconds,
        })
    }

    async fn load_storage_volume_catalog(
        &self,
        project_id: Option<ProjectId>,
    ) -> anyhow::Result<serde_json::Value> {
        let Some(project_id) = project_id else {
            return Ok(serde_json::Value::Object(serde_json::Map::new()));
        };
        let rows = sqlx::query(
            r#"
            SELECT v.volume_ref, v.backend_type, v.max_access AS volume_max_access,
                   v.allowed_prefixes AS volume_allowed_prefixes, v.docker, v.k8s,
                   og.max_access AS org_grant_max_access, og.allowed_prefixes AS org_grant_allowed_prefixes,
                   g.max_access AS grant_max_access, g.allowed_prefixes AS grant_allowed_prefixes
              FROM joysafeter_storage_volumes v
              JOIN joysafeter_organization_projects p ON p.id = $1
              JOIN joysafeter_storage_organization_grants og
                ON og.volume_id = v.id AND og.org_id = p.org_id
              JOIN joysafeter_storage_project_grants g ON g.volume_id = v.id
             WHERE v.deleted_at IS NULL
               AND v.enabled IS TRUE
               AND og.enabled IS TRUE
               AND g.enabled IS TRUE
               AND g.project_id = $1
            "#,
        )
        .bind(project_id)
        .fetch_all(&self.pool)
        .await?;

        let mut map = serde_json::Map::new();
        for row in rows {
            let volume_ref: String = row.try_get("volume_ref")?;
            let backend_type: String = row.try_get("backend_type")?;
            let volume_max_access: String = row.try_get("volume_max_access")?;
            let org_grant_max_access: Option<String> = row.try_get("org_grant_max_access")?;
            let grant_max_access: Option<String> = row.try_get("grant_max_access")?;
            let volume_allowed_prefixes: serde_json::Value =
                row.try_get("volume_allowed_prefixes")?;
            let org_grant_allowed_prefixes: Option<serde_json::Value> =
                row.try_get("org_grant_allowed_prefixes")?;
            let grant_allowed_prefixes: Option<serde_json::Value> =
                row.try_get("grant_allowed_prefixes")?;
            let docker: serde_json::Value = row.try_get("docker")?;
            let k8s: serde_json::Value = row.try_get("k8s")?;
            let volume_prefixes = volume_allowed_prefixes
                .as_array()
                .cloned()
                .unwrap_or_default();
            let grant_prefixes = grant_allowed_prefixes
                .as_ref()
                .and_then(|value| value.as_array().cloned())
                .unwrap_or_default();
            let org_grant_prefixes = org_grant_allowed_prefixes
                .as_ref()
                .and_then(|value| value.as_array().cloned())
                .unwrap_or_default();
            let allowed_prefixes =
                effective_prefixes(vec![volume_prefixes, org_grant_prefixes, grant_prefixes]);
            let max_access = if volume_max_access == "read_only"
                || org_grant_max_access.as_deref() == Some("read_only")
                || grant_max_access.as_deref() == Some("read_only")
            {
                "read_only"
            } else {
                "read_write"
            };
            map.insert(
                volume_ref,
                serde_json::json!({
                    "backend_type": backend_type,
                    "max_access": max_access,
                    "allowed_prefixes": allowed_prefixes,
                    "docker": docker,
                    "k8s": k8s,
                }),
            );
        }
        Ok(serde_json::Value::Object(map))
    }
}
