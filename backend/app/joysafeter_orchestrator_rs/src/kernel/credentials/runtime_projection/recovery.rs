use sqlx::PgPool;
use tracing::warn;

use crate::db::queries;
use crate::ids::{EnvironmentId, ProjectId};
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::error::CredentialRuntimeError;
use crate::kernel::mcp_runtime_plan::{
    effective_network_mode, resolve_mcp_runtime_plan_with_access,
};
use crate::kernel::network_policy::envoy_model::{EgressCredentialRoute, SandboxCredentials};
use crate::kernel::repository_access::material::RepositoryAccessMaterial;
use crate::kernel::run_spec::{agent_for_execution, environment_for_execution};
use crate::kernel::runtime_auth;

use super::{
    build_external_egress, build_git_egress, extract_llm_egress, resolve_agent_env_from,
    EnvironmentRow,
};

/// Rebuild the egress credentials for a live sandbox during orchestrator startup
/// recovery. Re-derives the same LLM/MCP/git secrets that were injected at
/// creation time by decrypting the current DB rows, so a restarted orchestrator
/// (whose in-memory/gRPC xDS state was wiped) restores credential injection for
/// still-running sandboxes. Returns empty when the sandbox has no session/agent.
pub(crate) async fn rebuild_sandbox_credentials(
    pool: &PgPool,
    credential_access: &CredentialMaterialAccessService,
    repository_material: &dyn RepositoryAccessMaterial,
    sandbox: &crate::db::models::JoySafeterSandbox,
    llm_egress_allowed_hosts: &[String],
) -> anyhow::Result<SandboxCredentials> {
    let mut routes = Vec::new();

    let Some(session_id) = sandbox.chat_session_id else {
        return Ok(SandboxCredentials {
            routes,
            proxy_auth_token: runtime_auth::egress_proxy_token(sandbox.config.as_ref()),
        });
    };
    let session = queries::get_session(pool, session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("sandbox recovery session {session_id} was not found"))?;
    let networking = sandbox
        .config
        .as_ref()
        .and_then(|config| config.get("fingerprint"))
        .and_then(|fingerprint| fingerprint.get("networking"));
    let live_agent = match session.agent_id {
        Some(aid) => queries::get_agent(pool, aid).await?,
        None => None,
    };
    let snapshot_environment = environment_for_execution(Some(&session));
    let agent = agent_for_execution(live_agent, Some(&session))?;
    let access_context = CredentialAccessContext::runtime(
        Some(session_id),
        None,
        Some(session.runtime_config_generation),
    );
    // Re-resolve the agent env (with decrypted secrets) exactly as at creation,
    // then extract the LLM egress from it. We discard the env itself — only the
    // extracted egress credential is needed for recovery.
    if let Some(agent_ref) = agent.as_ref() {
        let environment = if let Some(snapshot_environment) = snapshot_environment {
            Some(EnvironmentRow {
                config: snapshot_environment.config,
                image_tag: snapshot_environment.image_tag,
            })
        } else {
            match agent_ref.environment_id {
                Some(environment_id) => {
                    load_environment_row(pool, environment_id, agent_ref.project_id).await?
                }
                None => None,
            }
        };
        let resolved_env = resolve_agent_env_from(
            credential_access,
            &access_context,
            agent.as_ref(),
            environment.as_ref(),
        )
        .await?;
        let mut env = resolved_env.values;
        routes.extend(extract_llm_egress(
            &mut env,
            resolved_env.llm_binding.as_ref(),
            llm_egress_allowed_hosts,
        ));
        let (external_routes, _) = build_external_egress(
            credential_access,
            &access_context,
            environment.as_ref(),
            session.project_id.or(agent_ref.project_id),
        )
        .await?;
        routes.extend(external_routes);
        remove_agent_identity_routes(&mut routes);
        let network_mode = effective_network_mode(networking, false)?;
        let mcp_plan = resolve_mcp_runtime_plan_with_access(
            credential_access,
            &access_context,
            session.project_id.or(agent_ref.project_id),
            Some(session_id),
            agent_ref.id,
            session.runtime_config_generation,
            network_mode,
            agent_ref.mcp_servers.as_ref(),
        )
        .await?;
        routes.extend(mcp_plan.egress_routes());
    }
    match build_git_egress(pool, repository_material, Some(session_id)).await {
        Ok(git) => routes.extend(git),
        Err(e) => warn!(
            session_id = %session_id,
            sandbox_id = %sandbox.id,
            "Failed to rebuild Git egress credentials during sandbox recovery: {e}"
        ),
    }
    Ok(SandboxCredentials {
        routes,
        proxy_auth_token: runtime_auth::egress_proxy_token(sandbox.config.as_ref()),
    })
}

pub(crate) fn remove_agent_identity_routes(routes: &mut Vec<EgressCredentialRoute>) {
    routes.retain(|route| !route.id.starts_with("external-identity:"));
}

/// Standalone environment loader for recovery (mirrors `load_environment`).
async fn load_environment_row(
    pool: &PgPool,
    environment_id: EnvironmentId,
    project_id: Option<ProjectId>,
) -> anyhow::Result<Option<EnvironmentRow>> {
    let project_id = project_id.ok_or(CredentialRuntimeError::ProjectMismatch)?;
    let environment = sqlx::query_as::<_, (serde_json::Value, Option<String>)>(
        r#"
        SELECT config, image_tag FROM joysafeter_environments
        WHERE id = $1 AND deleted_at IS NULL AND project_id = $2
        "#,
    )
    .bind(environment_id)
    .bind(project_id)
    .fetch_optional(pool)
    .await?
    .map(|(config, image_tag)| EnvironmentRow { config, image_tag });
    let diagnostic_project = if environment.is_none() {
        sqlx::query_as::<_, (ProjectId,)>(
            "SELECT project_id FROM joysafeter_environments WHERE id = $1 AND deleted_at IS NULL",
        )
        .bind(environment_id)
        .fetch_optional(pool)
        .await?
    } else {
        None
    };
    if environment.is_some() {
        return Ok(environment);
    }
    match diagnostic_project {
        Some((actual_project,)) if actual_project != project_id => {
            Err(CredentialRuntimeError::ProjectMismatch.into())
        }
        Some(_) => Err(CredentialRuntimeError::CorruptRecord.into()),
        None => Err(CredentialRuntimeError::NotFound.into()),
    }
}
