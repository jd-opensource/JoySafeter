use std::sync::Arc;

use anyhow::Context;
use sqlx::PgPool;

use crate::db::queries;
use crate::ids::SandboxId;
use crate::kernel::credentials::access::CredentialMaterialAccessService;
use crate::kernel::credentials::runtime_projection::rebuild_sandbox_credentials;
use crate::kernel::credentials::runtime_projection::rebuild_sandbox_credentials_with_identity_routes;
use crate::kernel::network_policy::identity::merge_identity_injection;
use crate::kernel::network_policy::material::NetworkPolicyMaterialResolver;
use crate::kernel::network_policy::DesiredNetworkPolicy;
use crate::kernel::repository_access::material::{
    RepositoryAccessMaterial, RepositoryAccessMaterialAdapter,
};
use crate::kernel::task_identity::{TaskIdentityService, TaskIdentitySubject};

pub(crate) fn build_network_policy_material_resolver(
    pool: PgPool,
    llm_egress_allowed_hosts: Vec<String>,
    identity: TaskIdentityService,
) -> Arc<dyn NetworkPolicyMaterialResolver> {
    Arc::new(PostgresNetworkPolicyMaterialResolver {
        credential_access: CredentialMaterialAccessService::new(pool.clone()),
        repository_material: Arc::new(RepositoryAccessMaterialAdapter::from_env()),
        pool,
        llm_egress_allowed_hosts,
        identity,
    })
}

#[derive(Clone)]
struct PostgresNetworkPolicyMaterialResolver {
    pool: PgPool,
    credential_access: CredentialMaterialAccessService,
    repository_material: Arc<dyn RepositoryAccessMaterial>,
    llm_egress_allowed_hosts: Vec<String>,
    identity: TaskIdentityService,
}

#[async_trait::async_trait]
impl NetworkPolicyMaterialResolver for PostgresNetworkPolicyMaterialResolver {
    async fn resolve(&self, sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy> {
        let sandbox = queries::get_sandbox(&self.pool, sandbox_id)
            .await?
            .ok_or_else(|| anyhow::anyhow!("sandbox {sandbox_id} was not found"))?;
        let networking = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("fingerprint"))
            .and_then(|fingerprint| fingerprint.get("networking"));
        let has_identity_lease = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("agent_identity_lease"))
            .is_some_and(|lease| !lease.is_null());
        let credentials = if has_identity_lease {
            self.resolve_with_task_identity(&sandbox).await?
        } else {
            rebuild_sandbox_credentials(
                &self.pool,
                &self.credential_access,
                self.repository_material.as_ref(),
                &sandbox,
                &self.llm_egress_allowed_hosts,
            )
            .await?
        };
        DesiredNetworkPolicy::from_inputs(networking, &credentials)
    }

    async fn resolve_base(&self, sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy> {
        let sandbox = queries::get_sandbox(&self.pool, sandbox_id)
            .await?
            .ok_or_else(|| anyhow::anyhow!("sandbox {sandbox_id} was not found"))?;
        let networking = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("fingerprint"))
            .and_then(|fingerprint| fingerprint.get("networking"));
        let credentials = rebuild_sandbox_credentials(
            &self.pool,
            &self.credential_access,
            self.repository_material.as_ref(),
            &sandbox,
            &self.llm_egress_allowed_hosts,
        )
        .await?;
        DesiredNetworkPolicy::from_inputs(networking, &credentials)
    }
}

impl PostgresNetworkPolicyMaterialResolver {
    async fn resolve_with_task_identity(
        &self,
        sandbox: &crate::db::models::JoySafeterSandbox,
    ) -> anyhow::Result<crate::kernel::network_policy::envoy_model::SandboxCredentials> {
        let task_id = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("agent_identity_lease"))
            .and_then(|lease| lease.get("task_id"))
            .and_then(serde_json::Value::as_str)
            .context("Agent Identity recovery lease has no task_id")?
            .parse()
            .context("Agent Identity recovery lease has an invalid task_id")?;
        let task = queries::get_task(&self.pool, task_id)
            .await?
            .context("Agent Identity recovery task was not found")?;
        if task.status != "running" || task.sandbox_id != Some(sandbox.id) {
            anyhow::bail!("Agent Identity recovery task is not active on this sandbox");
        }
        let session_id = task
            .session_id
            .context("Agent Identity recovery task has no session")?;
        if sandbox.chat_session_id != Some(session_id) {
            anyhow::bail!("Agent Identity recovery task does not match the sandbox session");
        }
        let project_id = task
            .project_id
            .context("Agent Identity recovery task has no project")?;
        let agent_id = task
            .agent_id
            .context("Agent Identity recovery task has no agent")?;
        let agent = queries::get_agent(&self.pool, agent_id)
            .await?
            .context("Agent Identity recovery agent was not found")?;
        if agent.project_id != Some(project_id) {
            anyhow::bail!("Agent Identity recovery agent does not match the task project");
        }

        let (mut credentials, identity_targets) = rebuild_sandbox_credentials_with_identity_routes(
            &self.pool,
            &self.credential_access,
            self.repository_material.as_ref(),
            sandbox,
            &self.llm_egress_allowed_hosts,
        )
        .await?;
        if identity_targets.is_empty() {
            anyhow::bail!("Agent Identity recovery lease has no matching egress routes");
        }
        if !self.identity.enabled() {
            anyhow::bail!("Agent Identity provider is disabled during policy recovery");
        }
        let injection = self
            .identity
            .resolve_injection(
                Some(&agent as &dyn TaskIdentitySubject),
                task_id,
                Some(session_id),
                Some(project_id),
                &identity_targets,
            )
            .await?
            .context("Agent Identity provider returned no recovery injection")?;
        merge_identity_injection(&mut credentials.routes, injection)?;
        Ok(credentials)
    }
}
