use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;

use sqlx::PgPool;
#[cfg(test)]
use tokio::sync::Notify;
use tracing::debug;

use crate::db::queries;
use crate::ids::SandboxId;
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::error::{require_bound_credential_id, CredentialRuntimeError};
#[cfg(test)]
use crate::kernel::credentials::material::ManagedCredentialMaterialAdapter;
use crate::kernel::environment_binding::{self, EnvironmentBinding};
use crate::kernel::harness_contract::{HarnessCustomTool, HarnessInput};
use crate::kernel::mcp_runtime_plan::{
    effective_network_mode, resolve_mcp_runtime_plan_from_metadata,
};
#[cfg(test)]
use crate::kernel::mcp_url;
use crate::kernel::repository_access::material::RepositoryAccessMaterial;
#[cfg(test)]
use crate::kernel::repository_access::material::RepositoryAccessMaterialAdapter;
use crate::kernel::run_spec::{
    agent_for_execution, environment_for_execution, SnapshotEnvironment,
};
use crate::kernel::runtime_freshness::RuntimeFreshnessError;
use crate::kernel::tool_policy::ToolPolicy;

mod conversation_history;
mod generation_fence;
mod session_resources;
mod skill_archives;

#[cfg(test)]
use skill_archives::{
    ensure_skill_entrypoint, parse_semver, published_version_scan_audit,
    resolve_skill_version_request, safe_archive_path, SkillFileForArchive, SkillForArchive,
    SkillVersionForArchive,
};

fn apply_runtime_protocol_env(
    env: &mut HashMap<String, String>,
    engine_kind: &str,
    protocol: &str,
) {
    match protocol.trim() {
        "" | "custom" => {}
        other => {
            env.insert("JOYSAFETER_MODEL_PROTOCOL".to_string(), other.to_string());
        }
    }
    if engine_kind == "native" && matches!(protocol.trim(), "chat_completions" | "openai_responses")
    {
        env.entry("CLAUDE_CODE_USE_OPENAI".to_string())
            .or_insert_with(|| "1".to_string());
    }
}

/// Constructs gRPC SetupSandbox and StartTask messages from task/agent/session data.
///
/// This mirrors Python `build_harness_input`: agent model/env/model credential, MCP
/// credentials (resolved from the session's credential groups), memory stores, packed
/// skills/agents/commands, session file resources, conversation history, custom tools,
/// and a provider-neutral tool policy all flow through one builder.
#[derive(Clone)]
pub struct HarnessInputBuilder {
    pool: PgPool,
    credential_access: CredentialMaterialAccessService,
    repository_material: Arc<dyn RepositoryAccessMaterial>,
    /// When true, all MCP server URLs are downgraded from https to http before
    /// being sent to the sandbox. In Envoy-limited networking, the sandbox cannot
    /// do end-to-end TLS (no trusted CA store); Envoy does TLS origination to the
    /// upstream instead. Without this, MCP servers without credential bindings
    /// keep their https:// URL and the sandbox's TLS handshake fails ("Failed to
    /// connect") because the internal CA cert is untrusted in the container.
    pub envoy_enabled: bool,
    #[cfg(test)]
    checkpoint_hook: Option<HarnessBuildTestHook>,
}

#[cfg(test)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum HarnessBuildCheckpoint {
    AfterInitialRead,
    DuringMaterialization,
    AfterFinalRead,
}

#[cfg(test)]
#[derive(Clone)]
struct HarnessBuildTestHook {
    checkpoint: HarnessBuildCheckpoint,
    reached: Arc<Notify>,
    resume: Arc<Notify>,
}

impl HarnessInputBuilder {
    pub(crate) fn with_services(
        pool: PgPool,
        credential_access: CredentialMaterialAccessService,
        repository_material: Arc<dyn RepositoryAccessMaterial>,
        envoy_enabled: bool,
    ) -> Self {
        Self {
            pool,
            credential_access,
            repository_material,
            envoy_enabled,
            #[cfg(test)]
            checkpoint_hook: None,
        }
    }

    #[cfg(test)]
    pub fn new(pool: PgPool, envoy_enabled: bool) -> Self {
        let credential_access = CredentialMaterialAccessService::new(pool.clone());
        let repository_material = Arc::new(RepositoryAccessMaterialAdapter::from_env());
        Self::with_services(pool, credential_access, repository_material, envoy_enabled)
    }

    #[cfg(test)]
    fn with_credential_material_adapter(
        mut self,
        credential_material: ManagedCredentialMaterialAdapter,
    ) -> Self {
        self.credential_access = CredentialMaterialAccessService::with_material_adapter(
            self.pool.clone(),
            credential_material,
        );
        self
    }

    #[cfg(test)]
    fn with_test_checkpoint(
        mut self,
        checkpoint: HarnessBuildCheckpoint,
        reached: Arc<Notify>,
        resume: Arc<Notify>,
    ) -> Self {
        self.checkpoint_hook = Some(HarnessBuildTestHook {
            checkpoint,
            reached,
            resume,
        });
        self
    }

    #[cfg(test)]
    async fn pause_at_checkpoint(&self, checkpoint: HarnessBuildCheckpoint) {
        let Some(hook) = self
            .checkpoint_hook
            .as_ref()
            .filter(|hook| hook.checkpoint == checkpoint)
        else {
            return;
        };
        hook.reached.notify_one();
        hook.resume.notified().await;
    }

    pub async fn build(
        &self,
        task: &crate::db::models::JoySafeterTask,
        sandbox_external_id: &str,
        sandbox_db_id: SandboxId,
    ) -> anyhow::Result<HarnessInput> {
        let initial_fence = match task.session_id {
            Some(session_id) => {
                let fence = generation_fence::load(&self.pool, session_id, sandbox_db_id).await?;
                fence.validate(sandbox_db_id)?;
                Some(fence)
            }
            None => None,
        };
        let credential_access_context = CredentialAccessContext::runtime(
            task.session_id,
            Some(task.id),
            initial_fence.as_ref().map(|fence| fence.generation),
        );
        let runtime_config_generation = initial_fence
            .as_ref()
            .map(|fence| fence.generation)
            .unwrap_or(0);
        let credential_access = &self.credential_access;
        #[cfg(test)]
        self.pause_at_checkpoint(HarnessBuildCheckpoint::AfterInitialRead)
            .await;

        let live_agent = match task.agent_id {
            Some(aid) => queries::get_agent(&self.pool, aid).await?,
            None => None,
        };
        let session = match task.session_id {
            Some(sid) => queries::get_session(&self.pool, sid).await?,
            None => None,
        };
        let snapshot_environment = environment_for_execution(session.as_ref());
        let agent = agent_for_execution(live_agent, session.as_ref())?;
        let live_environment = self
            .load_live_environment(session.as_ref(), agent.as_ref())
            .await?;

        let mut input = HarnessInput {
            runtime_config_generation,
            provider: agent
                .as_ref()
                .and_then(|a| a.engine_kind.clone())
                .unwrap_or_else(|| "claude".to_string()),
            model: agent.as_ref().and_then(|a| a.model.clone()),
            prompt: task.prompt.clone(),
            work_dir: task
                .session_id
                .map(|_| "/workspace".to_string())
                .or_else(|| Some(sandbox_external_id.to_string())),
            harness_session_id: session
                .as_ref()
                .and_then(|s| s.last_harness_session_id.clone()),
            max_turns: extract_max_turns(agent.as_ref().and_then(|a| a.metadata.as_ref())),
            ..Default::default()
        };

        if let Some(ref agent) = agent {
            let networking = snapshot_environment
                .as_ref()
                .map(|environment| &environment.config)
                .or_else(|| {
                    live_environment
                        .as_ref()
                        .map(|environment| &environment.config)
                })
                .and_then(|config| config.get("networking"));
            let network_mode = effective_network_mode(networking, self.envoy_enabled)?;
            let mcp_metadata = match (session.as_ref(), agent.project_id) {
                (Some(session), Some(project_id)) => {
                    credential_access
                        .load_mcp_member_metadata(&project_id, session.id)
                        .await?
                }
                _ => Vec::new(),
            };
            input.mcp_servers = resolve_mcp_runtime_plan_from_metadata(
                agent.id,
                session
                    .as_ref()
                    .map(|session| session.runtime_config_generation)
                    .unwrap_or(0),
                network_mode,
                agent.mcp_servers.as_ref(),
                &mcp_metadata,
            )?
            .runner_servers();
            input.tool_policy = ToolPolicy::from_agent_tools(agent.tools.as_ref())?;
            input.custom_tools = parse_custom_tools(agent.tools.as_ref())?;
            super::engine_adapter::validate_runtime_capabilities(
                &input.provider,
                &input.tool_policy,
                !input.mcp_servers.is_empty(),
                !input.custom_tools.is_empty(),
            )?;
            input.setup_commands = Self::resolve_environment_setup_commands(
                snapshot_environment.as_ref(),
                live_environment.as_ref(),
            );
            input
                .setup_commands
                .extend(extract_setup_commands(agent.metadata.as_ref()));

            Self::apply_environment_env(
                snapshot_environment.as_ref(),
                live_environment.as_ref(),
                &mut input,
            );
            #[cfg(test)]
            self.pause_at_checkpoint(HarnessBuildCheckpoint::DuringMaterialization)
                .await;
            match self
                .resolve_agent_credential(
                    &credential_access,
                    &credential_access_context,
                    agent,
                    input.model.is_none(),
                )
                .await
            {
                Ok(resolved) => {
                    apply_runtime_protocol_env(
                        &mut input.env,
                        &input.provider,
                        &resolved.binding.protocol_id,
                    );
                    if input.model.is_none() {
                        input.model = resolved.model;
                    }
                }
                Err(error) if error.downcast_ref() == Some(&CredentialRuntimeError::NotBound) => {}
                Err(error) => return Err(error),
            }
            input
                .env
                .extend(json_object_to_string_map(agent.env.as_ref()));
            skill_archives::resolve(&self.pool, agent, &mut input).await?;
        }

        if let Some(ref session) = session {
            session_resources::load_memory_stores(&self.pool, session.id, &mut input).await?;
            session_resources::load_session_files(&self.pool, session.id, &mut input).await?;
            session_resources::load_session_repos(
                &self.pool,
                self.repository_material.as_ref(),
                session.id,
                &mut input,
            )
            .await?;
            input.work_dir = session_container_work_dir(session.last_work_dir.as_deref());
        }

        let base_system = task
            .system_prompt
            .clone()
            .or_else(|| agent.as_ref().and_then(|a| a.system_prompt.clone()));
        input.system_prompt =
            combine_system_prompt(base_system, input.memory_system_prompt.clone());
        input.system_prompt_mode = agent
            .as_ref()
            .and_then(|a| a.metadata.as_ref())
            .and_then(|m| m.get("system_prompt_mode"))
            .and_then(|v| v.as_str())
            .unwrap_or("append")
            .to_string();

        let has_harness_resume = input
            .harness_session_id
            .as_ref()
            .map(|sid| !sid.trim().is_empty())
            .unwrap_or(false);
        if should_inject_conversation_history(&input.provider, has_harness_resume) {
            if let Some(sid) = task.session_id {
                let history = conversation_history::load(&self.pool, sid, task.id).await;
                if !history.is_empty() {
                    input.prompt = format!("{history}\n\n{}", input.prompt);
                }
            }
        }

        if let Some(initial_fence) = initial_fence {
            let final_fence =
                generation_fence::load(&self.pool, initial_fence.session_id, sandbox_db_id).await?;
            if final_fence.generation != initial_fence.generation {
                return Err(RuntimeFreshnessError::GenerationChanged {
                    expected: initial_fence.generation,
                    actual: final_fence.generation,
                }
                .into());
            }
            final_fence.validate(sandbox_db_id)?;
        }
        #[cfg(test)]
        self.pause_at_checkpoint(HarnessBuildCheckpoint::AfterFinalRead)
            .await;

        debug!(task_id = %task.id, "Built harness input");
        Ok(input)
    }

    fn resolve_environment_setup_commands(
        snapshot_environment: Option<&SnapshotEnvironment>,
        live_environment: Option<&EnvironmentBinding>,
    ) -> Vec<String> {
        if let Some(environment) = snapshot_environment {
            return extract_package_install_commands(environment.config.get("packages"));
        }

        live_environment
            .map(|environment| extract_package_install_commands(environment.config.get("packages")))
            .unwrap_or_default()
    }

    async fn load_live_environment(
        &self,
        session: Option<&crate::db::models::JoySafeterSession>,
        agent: Option<&crate::db::models::JoySafeterAgent>,
    ) -> anyhow::Result<Option<EnvironmentBinding>> {
        let project_id = match session {
            Some(session) => session.project_id,
            None => agent.and_then(|agent| agent.project_id),
        };
        environment_binding::resolve_live_environment_binding(
            &self.pool,
            session.and_then(|session| session.environment_id),
            agent.and_then(|agent| agent.environment_id),
            project_id,
            session.map(|session| session.id),
        )
        .await
        .map_err(Into::into)
    }

    async fn resolve_agent_credential(
        &self,
        credential_access: &CredentialMaterialAccessService,
        context: &CredentialAccessContext,
        agent: &crate::db::models::JoySafeterAgent,
        needs_model_value: bool,
    ) -> anyhow::Result<crate::kernel::credentials::access::ResolvedModelRuntimeConfig> {
        let model_credential_id = require_bound_credential_id(agent.model_credential_id)?;
        let project_id = agent
            .project_id
            .ok_or(CredentialRuntimeError::ProjectMismatch)?;
        credential_access
            .resolve_model_runtime_config(
                &project_id,
                model_credential_id,
                agent.engine_kind.as_deref().unwrap_or("claude"),
                needs_model_value,
                context,
            )
            .await
    }

    fn apply_environment_env(
        snapshot_environment: Option<&SnapshotEnvironment>,
        live_environment: Option<&EnvironmentBinding>,
        input: &mut HarnessInput,
    ) {
        let frozen_config = snapshot_environment
            .map(|environment| &environment.config)
            .or_else(|| live_environment.map(|environment| &environment.config));
        input.env.extend(json_object_to_string_map(
            frozen_config.and_then(|config| config.get("env_vars")),
        ));
    }
}

fn should_inject_conversation_history(provider: &str, has_harness_resume: bool) -> bool {
    super::engine_adapter::engine_spec(provider)
        .map(|s| s.injects_conversation_history)
        .unwrap_or(false)
        && !has_harness_resume
}

fn session_container_work_dir(last_work_dir: Option<&str>) -> Option<String> {
    match last_work_dir.map(str::trim).filter(|s| !s.is_empty()) {
        Some(path) if Path::new(path).is_absolute() => Some(path.to_string()),
        _ => Some("/workspace".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::env;
    use std::sync::Arc;

    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;
    use sqlx::PgPool;
    use tokio::sync::Notify;

    use super::{
        apply_runtime_protocol_env, ensure_skill_entrypoint, extract_tool_name_sets,
        parse_custom_tools, parse_semver, published_version_scan_audit,
        resolve_skill_version_request, safe_archive_path, session_container_work_dir,
        should_inject_conversation_history, HarnessBuildCheckpoint, HarnessInputBuilder,
        SkillFileForArchive, SkillForArchive, SkillVersionForArchive,
    };
    use crate::ids::{
        AgentId, CredentialGroupId, CredentialId, EnvironmentId, FileId, OrganizationId, ProjectId,
        SandboxId, SessionId, SessionResourceId, SkillVersionId, TaskId,
    };
    use crate::kernel::credentials::material::ManagedCredentialMaterialAdapter;
    use crate::kernel::runtime_freshness::RuntimeFreshnessError;
    use uuid::Uuid;

    const ENCRYPTED_HELLO_WORLD: &str =
        "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";
    const TEST_CREDENTIAL_KEY: [u8; 32] = [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
        25, 26, 27, 28, 29, 30, 31,
    ];

    fn database_url() -> Option<String> {
        env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    #[test]
    fn custom_tool_projection_rejects_duplicate_names() {
        let tools = json!([
            {"type": "custom", "name": "deploy", "description": "one", "input_schema": {}},
            {"type": "custom", "name": "deploy", "description": "two", "input_schema": {}}
        ]);

        assert!(parse_custom_tools(Some(&tools)).is_err());
    }

    #[test]
    fn custom_tool_projection_rejects_non_object_schema() {
        let tools = json!([{
            "type": "custom",
            "name": "deploy",
            "description": "deploy",
            "input_schema": "not-an-object"
        }]);

        assert!(parse_custom_tools(Some(&tools)).is_err());
    }

    #[test]
    fn event_routing_reads_canonical_mcp_toolset_field() {
        let agent = crate::db::models::JoySafeterAgent {
            id: AgentId::new(),
            project_id: None,
            name: "agent".into(),
            engine_kind: Some("claude".into()),
            model: None,
            system_prompt: None,
            description: None,
            env: None,
            mcp_servers: None,
            skills: None,
            agents: None,
            commands: None,
            tools: Some(json!([{
                "type": "mcp_toolset",
                "mcp_server_name": "docs"
            }])),
            metadata: None,
            multiagent: None,
            version: 1,
            environment_id: None,
            model_credential_id: None,
        };

        let (_, mcp_names) = extract_tool_name_sets(&agent);

        assert!(mcp_names.contains("docs"));
    }

    async fn test_pool() -> Option<PgPool> {
        let Some(url) = database_url() else {
            eprintln!("skipping real Postgres harness test: DATABASE_URL is not set");
            return None;
        };
        Some(
            PgPoolOptions::new()
                .max_connections(3)
                .connect(&url)
                .await
                .expect("connect to migrated Postgres test database"),
        )
    }

    async fn insert_ready_sandbox(
        pool: &PgPool,
        sandbox_id: SandboxId,
        session_id: SessionId,
        project_id: &ProjectId,
        applied_generation: i64,
    ) {
        sqlx::query(
            r#"
            INSERT INTO joysafeter_sandboxes (
                id, external_id, provider, status, config, chat_session_id,
                project_id, image, runtime_config_status,
                runtime_config_applied_generation
            )
            VALUES ($1, $2, 'docker', 'running', '{}'::jsonb, $3, $4,
                    'test-image:latest', 'ready', $5)
            "#,
        )
        .bind(sandbox_id)
        .bind(format!("harness-sandbox-{sandbox_id}"))
        .bind(session_id)
        .bind(project_id)
        .bind(applied_generation)
        .execute(pool)
        .await
        .expect("insert ready sandbox");
    }

    struct GenerationFixture {
        agent_id: AgentId,
        session_id: SessionId,
        task_id: TaskId,
        sandbox_id: SandboxId,
        environment_id: EnvironmentId,
        org_id: OrganizationId,
        project_id: ProjectId,
    }

    async fn insert_generation_fixture(pool: &PgPool) -> GenerationFixture {
        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = OrganizationId::new();
        let project_id = ProjectId::new();
        let snapshot = json!({
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "id": agent_id.to_string(),
            "version": 1,
            "name": format!("harness-generation-agent-{unique}"),
            "engine_kind": "claude",
            "system": "snapshot system",
            "env": {"AGENT_LEVEL": "snapshot-agent"},
            "mcp_servers": [],
            "tools": [],
            "skills": [],
            "agents": [],
            "commands": [],
            "environment_id": environment_id.to_string(),
            "model_credential_id": null,
            "environment": {
                "environment_id": environment_id.to_string(),
                "name": format!("harness-generation-env-{unique}"),
                "image_tag": "snapshot-image:1",
                "image_version": 1,
                "config": {
                    "env_vars": {"FROZEN_VALUE": "snapshot"},
                    "environment_credential_ids": [],
                    "packages": {"pip": ["snapshot-package"]}
                }
            }
        });

        sqlx::query(
            "INSERT INTO joysafeter_organizations (id, name, slug, storage_used_bytes, departed_member_usage) VALUES ($1, $2, $3, 0, 0)",
        )
        .bind(&org_id)
        .bind(format!("Harness Generation Org {unique}"))
        .bind(format!("harness-generation-org-{unique}"))
        .execute(pool)
        .await
        .expect("insert generation organization");
        sqlx::query(
            "INSERT INTO joysafeter_organization_projects (id, org_id, name, slug, is_default) VALUES ($1, $2, $3, $4, false)",
        )
        .bind(&project_id)
        .bind(&org_id)
        .bind(format!("Harness Generation Project {unique}"))
        .bind(format!("harness-generation-project-{unique}"))
        .execute(pool)
        .await
        .expect("insert generation project");
        sqlx::query(
            "INSERT INTO joysafeter_environments (id, project_id, name, description, config, image_tag, image_version) VALUES ($1, $2, $3, '', $4, 'live-image:2', 2)",
        )
        .bind(environment_id)
        .bind(&project_id)
        .bind(format!("harness-generation-env-{unique}"))
        .bind(json!({"env_vars": {"FROZEN_VALUE": "live"}, "environment_credential_ids": []}))
        .execute(pool)
        .await
        .expect("insert generation environment");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (
                id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                agents, commands, metadata, version, environment_id
            )
            VALUES ($1, $2, $3, 'claude', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 1, $4)
            "#,
        )
        .bind(agent_id)
        .bind(&project_id)
        .bind(format!("harness-generation-agent-{unique}"))
        .bind(environment_id)
        .execute(pool)
        .await
        .expect("insert generation agent");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_sessions (
                id, agent_id, project_id, status, agent_version, agent_snapshot,
                environment_id, runtime_config_generation
            )
            VALUES ($1, $2, $3, 'idle', 1, $4, $5, 7)
            "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&project_id)
        .bind(&snapshot)
        .bind(environment_id)
        .execute(pool)
        .await
        .expect("insert generation session");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_sandboxes (
                id, external_id, provider, status, config, chat_session_id,
                project_id, image, runtime_config_status,
                runtime_config_applied_generation
            )
            VALUES ($1, $2, 'docker', 'running', '{}'::jsonb, $3, $4,
                    'snapshot-image:1', 'ready', 7)
            "#,
        )
        .bind(sandbox_id)
        .bind(format!("harness-generation-sandbox-{unique}"))
        .bind(session_id)
        .bind(&project_id)
        .execute(pool)
        .await
        .expect("insert generation sandbox");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, $3, $4, 'running', 'generation fence', '', 7200, 0, 2)
            "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(session_id)
        .bind(sandbox_id)
        .execute(pool)
        .await
        .expect("insert generation task");

        GenerationFixture {
            agent_id,
            session_id,
            task_id,
            sandbox_id,
            environment_id,
            org_id,
            project_id,
        }
    }

    async fn delete_generation_fixture(pool: &PgPool, fixture: &GenerationFixture) {
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(fixture.task_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(fixture.sandbox_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(fixture.session_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(fixture.agent_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
            .bind(fixture.environment_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&fixture.project_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&fixture.org_id)
            .execute(pool)
            .await;
    }

    async fn advance_generation(pool: &PgPool, fixture: &GenerationFixture) {
        sqlx::query(
            r#"
            UPDATE joysafeter_sessions
            SET runtime_config_generation = runtime_config_generation + 1
            WHERE id = $1
            "#,
        )
        .bind(fixture.session_id)
        .execute(pool)
        .await
        .expect("advance desired generation");
        sqlx::query(
            r#"
            UPDATE joysafeter_sandboxes
            SET runtime_config_status = 'restart_required'
            WHERE id = $1
            "#,
        )
        .bind(fixture.sandbox_id)
        .execute(pool)
        .await
        .expect("mark sandbox stale");
    }

    async fn assert_generation_change_rejected(checkpoint: HarnessBuildCheckpoint) {
        let Some(pool) = test_pool().await else {
            return;
        };
        let fixture = insert_generation_fixture(&pool).await;
        let task = crate::db::queries::get_task(&pool, fixture.task_id)
            .await
            .expect("load generation task")
            .expect("generation task exists");
        let reached = Arc::new(Notify::new());
        let resume = Arc::new(Notify::new());
        let builder = HarnessInputBuilder::new(pool.clone(), false).with_test_checkpoint(
            checkpoint,
            reached.clone(),
            resume.clone(),
        );
        let sandbox_id = fixture.sandbox_id;
        let build =
            tokio::spawn(async move { builder.build(&task, "sandbox-ext", sandbox_id).await });

        reached.notified().await;
        advance_generation(&pool, &fixture).await;
        resume.notify_one();

        let error = build
            .await
            .expect("join harness build")
            .expect_err("generation change must reject materialized input");
        assert!(matches!(
            error.downcast_ref::<RuntimeFreshnessError>(),
            Some(RuntimeFreshnessError::GenerationChanged {
                expected: 7,
                actual: 8
            })
        ));
        delete_generation_fixture(&pool, &fixture).await;
    }

    #[tokio::test]
    async fn harness_input_rejects_generation_change_after_initial_read() {
        assert_generation_change_rejected(HarnessBuildCheckpoint::AfterInitialRead).await;
    }

    #[tokio::test]
    async fn harness_input_rejects_generation_change_during_materialization() {
        assert_generation_change_rejected(HarnessBuildCheckpoint::DuringMaterialization).await;
    }

    #[tokio::test]
    async fn harness_input_allows_generation_change_after_final_check() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let fixture = insert_generation_fixture(&pool).await;
        let task = crate::db::queries::get_task(&pool, fixture.task_id)
            .await
            .expect("load generation task")
            .expect("generation task exists");
        let reached = Arc::new(Notify::new());
        let resume = Arc::new(Notify::new());
        let builder = HarnessInputBuilder::new(pool.clone(), false).with_test_checkpoint(
            HarnessBuildCheckpoint::AfterFinalRead,
            reached.clone(),
            resume.clone(),
        );
        let sandbox_id = fixture.sandbox_id;
        let build =
            tokio::spawn(async move { builder.build(&task, "sandbox-ext", sandbox_id).await });

        reached.notified().await;
        advance_generation(&pool, &fixture).await;
        resume.notify_one();

        let input = build
            .await
            .expect("join harness build")
            .expect("post-check mutation may leave the completed old-generation payload valid");
        assert_eq!(
            input.env.get("FROZEN_VALUE").map(String::as_str),
            Some("snapshot")
        );
        delete_generation_fixture(&pool, &fixture).await;
    }

    #[tokio::test]
    async fn harness_input_requires_raw_ready_and_matching_applied_generation() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let fixture = insert_generation_fixture(&pool).await;
        let task = crate::db::queries::get_task(&pool, fixture.task_id)
            .await
            .expect("load generation task")
            .expect("generation task exists");

        sqlx::query("UPDATE joysafeter_sandboxes SET runtime_config_status = 'restart_required' WHERE id = $1")
            .bind(fixture.sandbox_id)
            .execute(&pool)
            .await
            .expect("mark sandbox stale");
        let stale_error = HarnessInputBuilder::new(pool.clone(), false)
            .build(&task, "sandbox-ext", fixture.sandbox_id)
            .await
            .expect_err("raw stale sandbox must reject harness input");
        assert!(matches!(
            stale_error.downcast_ref::<RuntimeFreshnessError>(),
            Some(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id })
                if *sandbox_id == fixture.sandbox_id
        ));

        sqlx::query("UPDATE joysafeter_sandboxes SET runtime_config_status = 'ready', runtime_config_applied_generation = 6 WHERE id = $1")
            .bind(fixture.sandbox_id)
            .execute(&pool)
            .await
            .expect("set applied generation mismatch");
        let generation_error = HarnessInputBuilder::new(pool.clone(), false)
            .build(&task, "sandbox-ext", fixture.sandbox_id)
            .await
            .expect_err("applied generation mismatch must reject harness input");
        assert!(matches!(
            generation_error.downcast_ref::<RuntimeFreshnessError>(),
            Some(RuntimeFreshnessError::GenerationChanged {
                expected: 7,
                actual: 6
            })
        ));

        delete_generation_fixture(&pool, &fixture).await;
    }

    #[tokio::test]
    async fn session_environment_binding_fk_rejects_missing_environment() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let fixture = insert_generation_fixture(&pool).await;
        let missing_environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let error = sqlx::query("UPDATE joysafeter_sessions SET environment_id = $2 WHERE id = $1")
            .bind(fixture.session_id)
            .bind(missing_environment_id)
            .execute(&pool)
            .await
            .expect_err("native environment foreign key must reject missing environment IDs");
        assert_eq!(
            error
                .as_database_error()
                .and_then(|database_error| database_error.code().map(|code| code.into_owned()))
                .as_deref(),
            Some("23503")
        );
        delete_generation_fixture(&pool, &fixture).await;
    }

    #[tokio::test]
    async fn harness_input_global_session_does_not_inherit_agent_project_for_environment_binding() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let fixture = insert_generation_fixture(&pool).await;
        sqlx::query("UPDATE joysafeter_sessions SET project_id = NULL WHERE id = $1")
            .bind(fixture.session_id)
            .execute(&pool)
            .await
            .expect("make session explicitly global");
        sqlx::query("UPDATE joysafeter_sandboxes SET project_id = NULL WHERE id = $1")
            .bind(fixture.sandbox_id)
            .execute(&pool)
            .await
            .expect("keep sandbox ownership aligned with global session");
        let task = crate::db::queries::get_task(&pool, fixture.task_id)
            .await
            .expect("load generation task")
            .expect("generation task exists");

        let error = HarnessInputBuilder::new(pool.clone(), false)
            .build(&task, "sandbox-ext", fixture.sandbox_id)
            .await
            .expect_err("global session must not resolve a project-scoped environment");
        assert!(
            matches!(
            error.downcast_ref::<RuntimeFreshnessError>(),
            Some(RuntimeFreshnessError::SessionBindingInvalid { session_id, .. })
                if *session_id == fixture.session_id
            ),
            "unexpected error: {error:?}"
        );
        delete_generation_fixture(&pool, &fixture).await;
    }

    #[test]
    fn native_runtime_protocol_env_enables_openai_provider() {
        let mut env = HashMap::new();

        apply_runtime_protocol_env(&mut env, "native", "openai_responses");

        assert_eq!(
            env.get("JOYSAFETER_MODEL_PROTOCOL").map(String::as_str),
            Some("openai_responses")
        );
        assert_eq!(
            env.get("CLAUDE_CODE_USE_OPENAI").map(String::as_str),
            Some("1")
        );
    }

    #[test]
    fn non_native_runtime_protocol_env_does_not_enable_claude_openai_provider() {
        let mut env = HashMap::new();

        apply_runtime_protocol_env(&mut env, "codex", "openai_responses");

        assert_eq!(
            env.get("JOYSAFETER_MODEL_PROTOCOL").map(String::as_str),
            Some("openai_responses")
        );
        assert_eq!(env.get("CLAUDE_CODE_USE_OPENAI"), None);
    }

    async fn cleanup(
        pool: &PgPool,
        agent_id: AgentId,
        session_id: SessionId,
        environment_id: EnvironmentId,
        credential_ids: &[CredentialId],
    ) {
        let _ =
            sqlx::query("DELETE FROM joysafeter_tasks WHERE chat_session_id = $1 OR agent_id = $2")
                .bind(session_id)
                .bind(agent_id)
                .execute(pool)
                .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
            .bind(environment_id)
            .execute(pool)
            .await;
        for credential_id in credential_ids {
            let _ = sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
                .bind(credential_id)
                .execute(pool)
                .await;
        }
    }

    #[test]
    fn parse_semver_orders_versions() {
        assert_eq!(parse_semver("1.2.0"), Some((1, 2, 0)));
        assert_eq!(parse_semver("0.1.0"), Some((0, 1, 0)));
        assert_eq!(parse_semver("10.0.3"), Some((10, 0, 3)));
        // non-semver rejected
        assert_eq!(parse_semver("1.2"), None);
        assert_eq!(parse_semver("1.2.0-rc1"), None);
        assert_eq!(parse_semver("latest"), None);
        // ordering: 10.0.0 > 9.9.9, 1.2.0 > 1.1.9
        assert!(parse_semver("10.0.0") > parse_semver("9.9.9"));
        assert!(parse_semver("1.2.0") > parse_semver("1.1.9"));
    }

    fn exposed_skill(same_project: bool, same_org: bool) -> SkillForArchive {
        let project_id = ProjectId::new();
        let skill_org_id = OrganizationId::new();
        SkillForArchive {
            source_type: Some("local".to_string()),
            project_id,
            skill_org_id,
            consumer_project_id: Some(if same_project {
                project_id
            } else {
                ProjectId::new()
            }),
            consumer_org_id: Some(if same_org {
                skill_org_id
            } else {
                OrganizationId::new()
            }),
            org_version: Some("1.0.0".to_string()),
            public_version: Some("0.9.0".to_string()),
        }
    }

    #[test]
    fn same_org_latest_uses_promoted_versions_only() {
        let skill = exposed_skill(false, true);
        assert_eq!(
            resolve_skill_version_request(&skill, "latest", Some("2.0.0")).unwrap(),
            "1.0.0"
        );
    }

    #[test]
    fn cross_org_latest_uses_public_pointer_only() {
        let skill = exposed_skill(false, false);
        assert_eq!(
            resolve_skill_version_request(&skill, "latest", Some("2.0.0")).unwrap(),
            "0.9.0"
        );
    }

    #[test]
    fn cross_project_explicit_private_version_is_rejected() {
        let skill = exposed_skill(false, true);
        let error = resolve_skill_version_request(&skill, "2.0.0", Some("2.0.0")).unwrap_err();
        assert!(error.to_string().contains("not exposed"));
    }

    #[test]
    fn same_project_latest_uses_project_latest() {
        let skill = exposed_skill(true, true);
        assert_eq!(
            resolve_skill_version_request(&skill, "latest", Some("2.0.0")).unwrap(),
            "2.0.0"
        );
    }

    #[test]
    fn usage_audit_does_not_inherit_parent_skill_scan_metadata() {
        let version = SkillVersionForArchive {
            id: SkillVersionId::from_uuid(Uuid::now_v7()),
            skill_name: "published-snapshot".to_string(),
            content: "# Published snapshot".to_string(),
            security_scan_id: None,
            target_hash: None,
        };

        assert_eq!(published_version_scan_audit(&version), (None, None));
    }

    #[test]
    fn skill_archive_backfills_missing_root_skill_md_from_version_content() {
        let skill_md = "---\nname: schema-search\ndescription: Search schemas\n---\n\n# Search";
        let mut files = vec![SkillFileForArchive {
            path: Some("scripts/".to_string()),
            file_name: Some("search.py".to_string()),
            content: Some("print('ok')".to_string()),
        }];
        ensure_skill_entrypoint(&mut files, skill_md).unwrap();
        assert!(files
            .iter()
            .any(|file| safe_archive_path(file).as_deref() == Some("SKILL.md")));
    }

    #[test]
    fn skill_archive_rejects_an_empty_existing_root_skill_md() {
        let mut files = vec![SkillFileForArchive {
            path: Some(String::new()),
            file_name: Some("SKILL.md".to_string()),
            content: Some("   ".to_string()),
        }];
        assert!(ensure_skill_entrypoint(&mut files, "fallback").is_err());
    }

    #[test]
    fn skill_archive_rejects_missing_root_when_version_content_is_empty() {
        let mut files = vec![];
        assert!(ensure_skill_entrypoint(&mut files, " ").is_err());
    }

    #[test]
    fn injects_history_for_cli_providers() {
        assert!(should_inject_conversation_history("claude", false));
        assert!(should_inject_conversation_history("codex", false));
        assert!(!should_inject_conversation_history("claude", true));
        assert!(!should_inject_conversation_history("langgraph_code", false));
    }

    #[test]
    fn session_work_dir_uses_absolute_resume_path_only() {
        assert_eq!(
            session_container_work_dir(Some("/workspace")),
            Some("/workspace".to_string())
        );
        assert_eq!(
            session_container_work_dir(Some("old-sandbox-id")),
            Some("/workspace".to_string())
        );
        assert_eq!(
            session_container_work_dir(None),
            Some("/workspace".to_string())
        );
    }

    #[tokio::test]
    async fn harness_input_uses_session_execution_snapshot_after_live_config_changes() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = OrganizationId::new();
        let project_id = ProjectId::new();
        let snapshot_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let live_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let snapshot_environment_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let live_environment_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let agent_name = format!("snapshot-agent-{unique}");
        let environment_name = format!("snapshot-env-{unique}");
        let snapshot = json!({
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "id": agent_id.to_string(),
            "version": 7,
            "name": agent_name,
            "engine_kind": "claude",
            "model": null,
            "system": "snapshot system",
            "env": {"AGENT_LEVEL": "snapshot-agent-env"},
            "mcp_servers": [{
                "name": "snapshot-mcp",
                "type": "streamable_http",
                "url": "https://mcp.snapshot.example",
                "auth_requirement": "none"
            }],
            "tools": [{
                "type": "custom",
                "name": "snapshot_tool",
                "description": "from snapshot",
                "input_schema": {}
            }],
            "metadata": {"setup_commands": ["echo snapshot-metadata"], "max_turns": 12},
            "skills": [],
            "agents": [],
            "commands": [],
            "environment_id": environment_id.to_string(),
            "model_credential_id": snapshot_credential_id.to_string(),
            "environment": {
                "environment_id": environment_id.to_string(),
                "name": environment_name,
                "image_tag": "snapshot-image:1",
                "image_version": 1,
                "config": {
                    "env_vars": {"ENV_LEVEL": "snapshot-env"},
                    "environment_credential_ids": [snapshot_environment_credential_id.to_string()],
                    "packages": {"pip": ["snapshot-pkg"]}
                }
            }
        });

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
            )
            .bind(&org_id)
            .bind(format!("Snapshot Org {unique}"))
            .bind(format!("snapshot-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert organization");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
            )
            .bind(&project_id)
            .bind(&org_id)
            .bind(format!("Snapshot Project {unique}"))
            .bind(format!("snapshot-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert project");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_environments
                    (id, project_id, name, description, config, image_tag, image_version)
                VALUES ($1, $2, $3, 'snapshot test env', $4, 'live-image:2', 2)
                "#,
            )
            .bind(environment_id)
            .bind(&project_id)
            .bind(&environment_name)
            .bind(json!({
                "env_vars": {"ENV_LEVEL": "live-env", "LIVE_ONLY": "must-not-appear"},
                "environment_credential_ids": [live_environment_credential_id.to_string()],
                "packages": {"pip": ["live-pkg"]}
            }))
            .execute(&pool)
            .await
            .expect("insert live environment");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_credentials
                    (id, project_id, kind, name, provider, protocol, data)
                VALUES ($1, $2, 'model', $3, 'anthropic', 'anthropic_messages', $4)
                "#,
            )
            .bind(snapshot_credential_id)
            .bind(&project_id)
            .bind(format!("snapshot-credential-{unique}"))
            .bind(json!({
                "ANTHROPIC_API_KEY": "invalid-envelope-must-not-be-read",
                "ANTHROPIC_MODEL": ENCRYPTED_HELLO_WORLD
            }))
            .execute(&pool)
            .await
            .expect("insert snapshot test credential");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_credentials
                    (id, project_id, kind, name, provider, protocol, data)
                VALUES ($1, $2, 'model', $3, 'openai', 'openai_responses', $4)
                "#,
            )
            .bind(live_credential_id)
            .bind(&project_id)
            .bind(format!("live-credential-{unique}"))
            .bind(json!({"OPENAI_API_KEY": ENCRYPTED_HELLO_WORLD}))
            .execute(&pool)
            .await
            .expect("insert live test credential");

            for (credential_id, name, field) in [
                (
                    snapshot_environment_credential_id,
                    format!("snapshot-environment-credential-{unique}"),
                    "SNAPSHOT_ENV_SECRET",
                ),
                (
                    live_environment_credential_id,
                    format!("live-environment-credential-{unique}"),
                    "LIVE_ENV_SECRET",
                ),
            ] {
                sqlx::query(
                    r#"
                    INSERT INTO joysafeter_credentials
                        (id, project_id, kind, name, data)
                    VALUES ($1, $2, 'service', $3, $4)
                    "#,
                )
                .bind(credential_id)
                .bind(&project_id)
                .bind(name)
                .bind(json!({(field): "invalid-envelope-must-not-be-read"}))
                .execute(&pool)
                .await
                .expect("insert environment credential");
            }

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata,
                    version, environment_id, model_credential_id
                )
                VALUES (
                    $1, $2, $3, 'codex', $4, 'live system', $5, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 8, $6, $7
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(&agent_name)
            .bind(json!({"id": "live-model"}))
            .bind(json!({"AGENT_LEVEL": "live-agent-env", "LIVE_AGENT_ONLY": "must-not-appear"}))
            .bind(environment_id)
            .bind(live_credential_id)
            .execute(&pool)
            .await
            .expect("insert live agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, project_id, status, agent_version, agent_snapshot, environment_id
                )
                VALUES ($1, $2, $3, 'idle', 7, $4, $5)
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .bind(&snapshot)
            .bind(environment_id)
            .execute(&pool)
            .await
            .expect("insert snapshot session");

            insert_ready_sandbox(&pool, sandbox_id, session_id, &project_id, 0).await;

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, 'running', 'run with snapshot', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .execute(&pool)
            .await
            .expect("insert test task");

            let task = crate::db::queries::get_task(&pool, task_id)
                .await
                .expect("load task")
                .expect("task exists");
            let input = HarnessInputBuilder::new(pool.clone(), true)
                .with_credential_material_adapter(ManagedCredentialMaterialAdapter::from_key(
                    TEST_CREDENTIAL_KEY,
                ))
                .build(&task, "sandbox-ext", sandbox_id)
                .await
                .expect("build harness input");

            assert_eq!(input.provider, "claude");
            assert_eq!(input.model.as_deref(), Some("hello-world"));
            assert_eq!(input.system_prompt.as_deref(), Some("snapshot system"));
            assert_eq!(input.max_turns, 12);
            assert_eq!(
                input.env.get("ENV_LEVEL").map(String::as_str),
                Some("snapshot-env")
            );
            assert_eq!(
                input.env.get("AGENT_LEVEL").map(String::as_str),
                Some("snapshot-agent-env")
            );
            assert!(!input.env.contains_key("LIVE_ONLY"));
            assert!(!input.env.contains_key("LIVE_AGENT_ONLY"));
            let access_rows = sqlx::query_as::<_, (CredentialId, String, serde_json::Value)>(
                r#"
                SELECT credential_id, usage, field_names
                FROM joysafeter_credential_access_audits
                WHERE credential_id = ANY($1)
                ORDER BY created_at, id
                "#,
            )
            .bind(
                &[
                    snapshot_credential_id,
                    snapshot_environment_credential_id,
                    live_environment_credential_id,
                ][..],
            )
            .fetch_all(&pool)
            .await
            .expect("load harness credential access audits");
            assert_eq!(
                access_rows,
                vec![(
                    snapshot_credential_id,
                    "model_inference".to_string(),
                    json!(["ANTHROPIC_MODEL"]),
                )]
            );
            assert_eq!(
                input.setup_commands,
                vec![
                    "pip install snapshot-pkg".to_string(),
                    "echo snapshot-metadata".to_string()
                ]
            );
            assert_eq!(input.mcp_servers.len(), 1);
            assert_eq!(input.mcp_servers[0].name, "snapshot-mcp");
            assert_eq!(input.custom_tools.len(), 1);
            assert_eq!(input.custom_tools[0].name, "snapshot_tool");
        }
        .await;

        cleanup(
            &pool,
            agent_id,
            session_id,
            environment_id,
            &[
                snapshot_credential_id,
                live_credential_id,
                snapshot_environment_credential_id,
                live_environment_credential_id,
            ],
        )
        .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&org_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn harness_input_snapshot_session_file_storage_missing_fails_build() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let file_id = FileId::from_uuid(Uuid::now_v7());
        let session_file_id = SessionResourceId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = OrganizationId::new();
        let project_id = ProjectId::new();
        let missing_storage_key = format!("missing-session-file-{unique}.txt");

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
            )
            .bind(&org_id)
            .bind(format!("Harness File Org {unique}"))
            .bind(format!("harness-file-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert organization");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
            )
            .bind(&project_id)
            .bind(&org_id)
            .bind(format!("Harness File Project {unique}"))
            .bind(format!("harness-file-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert project");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env,
                    mcp_servers, skills, tools, agents, commands,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("harness-file-agent-{unique}"))
            .bind(json!({"id": "claude-sonnet"}))
            .execute(&pool)
            .await
            .expect("insert agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert session");

            insert_ready_sandbox(&pool, sandbox_id, session_id, &project_id, 0).await;

            sqlx::query(
                r#"
                INSERT INTO joysafeter_files (
                    id, project_id, filename, purpose, content_type, size_bytes,
                    sha256, storage_key, downloadable
                )
                VALUES (
                    $1, $2, 'missing.txt', 'user_upload', 'text/plain', 12,
                    'missing-sha', $3, true
                )
                "#,
            )
            .bind(file_id)
            .bind(&project_id)
            .bind(&missing_storage_key)
            .execute(&pool)
            .await
            .expect("insert file metadata");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_files
                    (id, session_id, file_id, mount_path, access)
                VALUES ($1, $2, $3, '/workspace/missing.txt', 'read_only')
                "#,
            )
            .bind(session_file_id)
            .bind(session_id)
            .bind(file_id)
            .execute(&pool)
            .await
            .expect("insert session file mount");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, project_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'running', 'use declared file', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert task");

            let task = crate::db::queries::get_task(&pool, task_id)
                .await
                .expect("load task")
                .expect("task exists");
            let err = HarnessInputBuilder::new(pool.clone(), false)
                .build(&task, "sandbox-ext", sandbox_id)
                .await
                .expect_err("missing session file content must fail harness input build");
            let message = err.to_string();
            assert!(
                message.contains("failed to prepare session file"),
                "{message}"
            );
            assert!(message.contains(&missing_storage_key), "{message}");
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_files WHERE id = $1")
            .bind(session_file_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_files WHERE id = $1")
            .bind(file_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&org_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn harness_input_resolves_mcp_urls_without_revealing_tokens() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let group_id = CredentialGroupId::from_uuid(Uuid::now_v7());
        let credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = OrganizationId::new();
        let project_id = ProjectId::new();
        let mcp_url = "https://mcp.vault-alias.example/api";
        let normalized = super::mcp_url::normalize(mcp_url);

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
            )
            .bind(&org_id)
            .bind(format!("Harness MCP Org {unique}"))
            .bind(format!("harness-mcp-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert organization");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
            )
            .bind(&project_id)
            .bind(&org_id)
            .bind(format!("Harness MCP Project {unique}"))
            .bind(format!("harness-mcp-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert project");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_credential_groups (id, project_id, name, description)
                VALUES ($1, $2, $3, '')
                "#,
            )
            .bind(group_id)
            .bind(&project_id)
            .bind(format!("group-alias-{unique}"))
            .execute(&pool)
            .await
            .expect("insert credential group");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_credentials
                    (id, project_id, kind, name, credential_type, mcp_server_url,
                     normalized_mcp_server_url, group_id, data)
                VALUES ($1, $2, 'mcp', 'alias credential', 'static_bearer', $3,
                        $4, $5, $6)
                "#,
            )
            .bind(credential_id)
            .bind(&project_id)
            .bind(mcp_url)
            .bind(&normalized)
            .bind(group_id)
            .bind(json!({"token_value": "invalid-envelope-must-not-be-read"}))
            .execute(&pool)
            .await
            .expect("insert mcp credential");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb, $5,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("vault-alias-agent-{unique}"))
            .bind(json!({"id": "claude-sonnet"}))
            .bind(json!([{
                "name": "secure-mcp",
                "type": "streamable_http",
                "url": mcp_url,
                "auth_requirement": "required"
            }]))
            .execute(&pool)
            .await
            .expect("insert agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert session");

            insert_ready_sandbox(&pool, sandbox_id, session_id, &project_id, 0).await;

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_credential_groups (session_id, credential_group_id)
                VALUES ($1, $2)
                "#,
            )
            .bind(session_id)
            .bind(group_id)
            .execute(&pool)
            .await
            .expect("bind session credential group");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, 'running', 'run with vault alias', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .execute(&pool)
            .await
            .expect("insert task");

            let task = crate::db::queries::get_task(&pool, task_id)
                .await
                .expect("load task")
                .expect("task exists");
            let input = HarnessInputBuilder::new(pool.clone(), true)
                .build(&task, "sandbox-ext", sandbox_id)
                .await
                .expect("build harness input");

            assert_eq!(input.mcp_servers.len(), 1);
            assert_eq!(input.mcp_servers[0].name, "secure-mcp");
            assert!(input.mcp_servers[0]
                .url
                .starts_with("http://mcp-egress.internal/r/"));
            assert!(!input.mcp_servers[0].url.contains("secure-mcp"));
            assert!(input.mcp_servers[0].headers.is_empty());
            let audit_count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_credential_access_audits WHERE credential_id = $1",
            )
            .bind(credential_id)
            .fetch_one(&pool)
            .await
            .expect("count MCP credential access audits");
            assert_eq!(
                audit_count, 0,
                "metadata-only resolution is not material access"
            );
        }
        .await;

        let _ =
            sqlx::query("DELETE FROM joysafeter_tasks WHERE chat_session_id = $1 OR agent_id = $2")
                .bind(session_id)
                .bind(agent_id)
                .execute(&pool)
                .await;
        let _ =
            sqlx::query("DELETE FROM joysafeter_session_credential_groups WHERE session_id = $1")
                .bind(session_id)
                .execute(&pool)
                .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
            .bind(credential_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_credential_groups WHERE id = $1")
            .bind(group_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&org_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn harness_input_session_mcp_metadata_does_not_reveal_plaintext_token() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let group_id = CredentialGroupId::from_uuid(Uuid::now_v7());
        let credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = OrganizationId::new();
        let project_id = ProjectId::new();
        let mcp_url = "https://mcp.vault-decrypt-fail.example/api";
        let normalized = super::mcp_url::normalize(mcp_url);

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
            )
            .bind(&org_id)
            .bind(format!("Harness Decrypt Org {unique}"))
            .bind(format!("harness-decrypt-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert organization");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
            )
            .bind(&project_id)
            .bind(&org_id)
            .bind(format!("Harness Decrypt Project {unique}"))
            .bind(format!("harness-decrypt-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert project");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_credential_groups (id, project_id, name, description)
                VALUES ($1, $2, $3, '')
                "#,
            )
            .bind(group_id)
            .bind(&project_id)
            .bind(format!("group-decrypt-fail-{unique}"))
            .execute(&pool)
            .await
            .expect("insert credential group");

            // Harness only needs the MCP URL. Token material is resolved later
            // by the sandbox egress boundary, never while building gRPC input.
            sqlx::query(
                r#"
                INSERT INTO joysafeter_credentials
                    (id, project_id, kind, name, credential_type, mcp_server_url,
                     normalized_mcp_server_url, group_id, data)
                VALUES ($1, $2, 'mcp', 'bad encrypted credential', 'static_bearer', $3,
                        $4, $5, $6)
                "#,
            )
            .bind(credential_id)
            .bind(&project_id)
            .bind(mcp_url)
            .bind(&normalized)
            .bind(group_id)
            .bind(json!({"token_value": "plaintext-token"}))
            .execute(&pool)
            .await
            .expect("insert mcp credential");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb, $5,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("vault-decrypt-fail-agent-{unique}"))
            .bind(json!({"id": "claude-sonnet"}))
            .bind(json!([{
                "name": "secure-mcp",
                "type": "streamable_http",
                "url": mcp_url,
                "auth_requirement": "required"
            }]))
            .execute(&pool)
            .await
            .expect("insert agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert session");

            insert_ready_sandbox(&pool, sandbox_id, session_id, &project_id, 0).await;

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_credential_groups (session_id, credential_group_id)
                VALUES ($1, $2)
                "#,
            )
            .bind(session_id)
            .bind(group_id)
            .execute(&pool)
            .await
            .expect("bind session credential group");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, 'running', 'run with broken vault credential', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .execute(&pool)
            .await
            .expect("insert task");

            let task = crate::db::queries::get_task(&pool, task_id)
                .await
                .expect("load task")
                .expect("task exists");
            let input = HarnessInputBuilder::new(pool.clone(), true)
                .build(&task, "sandbox-ext", sandbox_id)
                .await
                .expect("MCP metadata must not reveal token material");
            assert_eq!(input.mcp_servers.len(), 1);
            assert!(input.mcp_servers[0]
                .url
                .starts_with("http://mcp-egress.internal/r/"));
            let access_count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_credential_access_audits WHERE credential_id = $1",
            )
            .bind(credential_id)
            .fetch_one(&pool)
            .await
            .expect("count MCP access audits");
            assert_eq!(access_count, 0);
        }
        .await;

        let _ =
            sqlx::query("DELETE FROM joysafeter_tasks WHERE chat_session_id = $1 OR agent_id = $2")
                .bind(session_id)
                .bind(agent_id)
                .execute(&pool)
                .await;
        let _ =
            sqlx::query("DELETE FROM joysafeter_session_credential_groups WHERE session_id = $1")
                .bind(session_id)
                .execute(&pool)
                .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
            .bind(credential_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_credential_groups WHERE id = $1")
            .bind(group_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&org_id)
            .execute(&pool)
            .await;
    }
}

fn json_object_to_string_map(value: Option<&serde_json::Value>) -> HashMap<String, String> {
    value
        .and_then(|v| v.as_object())
        .map(|obj| {
            obj.iter()
                .map(|(k, v)| {
                    let value = v
                        .as_str()
                        .map(ToOwned::to_owned)
                        .unwrap_or_else(|| v.to_string());
                    (k.clone(), value)
                })
                .collect()
        })
        .unwrap_or_default()
}

fn parse_custom_tools(
    value: Option<&serde_json::Value>,
) -> Result<Vec<HarnessCustomTool>, CustomToolProjectionError> {
    let Some(items) = value.and_then(|value| value.as_array()) else {
        return Ok(Vec::new());
    };
    let mut names = std::collections::HashSet::new();
    let mut custom_tools = Vec::new();

    for item in items
        .iter()
        .filter(|item| item.get("type").and_then(|value| value.as_str()) == Some("custom"))
    {
        let name = item
            .get("name")
            .and_then(|value| value.as_str())
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or(CustomToolProjectionError::MissingName)?
            .to_string();
        if !names.insert(name.clone()) {
            return Err(CustomToolProjectionError::DuplicateName(name));
        }
        let description = item
            .get("description")
            .and_then(|value| value.as_str())
            .ok_or(CustomToolProjectionError::MissingDescription)?
            .to_string();
        let input_schema = item
            .get("input_schema")
            .and_then(|value| value.as_object())
            .ok_or(CustomToolProjectionError::InvalidInputSchema)?;
        custom_tools.push(HarnessCustomTool {
            name,
            description,
            input_schema_json: serde_json::Value::Object(input_schema.clone()).to_string(),
        });
    }

    Ok(custom_tools)
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
enum CustomToolProjectionError {
    #[error("custom tool name must be a non-empty string")]
    MissingName,
    #[error("custom tool description must be a string")]
    MissingDescription,
    #[error("custom tool input_schema must be an object")]
    InvalidInputSchema,
    #[error("duplicate custom tool {0}")]
    DuplicateName(String),
}

/// Parse a strict ``MAJOR.MINOR.PATCH`` version into a comparable tuple.
/// Returns None for anything that isn't three numeric components.

fn extract_package_install_commands(packages: Option<&serde_json::Value>) -> Vec<String> {
    let Some(packages) = packages.and_then(|v| v.as_object()) else {
        return vec![];
    };
    let mut commands = Vec::new();
    for (key, prefix) in [
        ("apt", "apt-get update && apt-get install -y"),
        ("pip", "pip install"),
        ("npm", "npm install -g"),
        ("cargo", "cargo install"),
        ("gem", "gem install"),
        ("go", "go install"),
    ] {
        let items: Vec<String> = packages
            .get(key)
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(str::trim))
                    .filter(|v| !v.is_empty())
                    .map(String::from)
                    .collect()
            })
            .unwrap_or_default();
        if !items.is_empty() {
            commands.push(format!("{prefix} {}", items.join(" ")));
        }
    }
    commands
}

fn extract_setup_commands(metadata: Option<&serde_json::Value>) -> Vec<String> {
    metadata
        .and_then(|v| v.get("setup_commands"))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default()
}

fn extract_max_turns(metadata: Option<&serde_json::Value>) -> u32 {
    metadata
        .and_then(|v| v.get("max_turns"))
        .and_then(|v| v.as_u64())
        .and_then(|v| u32::try_from(v).ok())
        .unwrap_or(100)
}

fn combine_system_prompt(base: Option<String>, memory: Option<String>) -> Option<String> {
    match (
        base.filter(|v| !v.is_empty()),
        memory.filter(|v| !v.is_empty()),
    ) {
        (Some(base), Some(memory)) => Some(format!("{base}\n\n{memory}")),
        (Some(base), None) => Some(base),
        (None, Some(memory)) => Some(memory),
        (None, None) => None,
    }
}

/// Extract custom tool names and MCP server names from agent config.
/// Used by the Runner execution service to route events to correct types.
pub fn extract_tool_name_sets(
    agent: &crate::db::models::JoySafeterAgent,
) -> (
    std::collections::HashSet<String>,
    std::collections::HashSet<String>,
) {
    let mut custom_names = std::collections::HashSet::new();
    let mut mcp_names = std::collections::HashSet::new();

    if let Some(ref tools_val) = agent.tools {
        if let Some(arr) = tools_val.as_array() {
            for item in arr {
                let tool_type = item.get("type").and_then(|v| v.as_str()).unwrap_or("");
                match tool_type {
                    "custom" => {
                        if let Some(name) = item.get("name").and_then(|v| v.as_str()) {
                            custom_names.insert(name.to_string());
                        }
                    }
                    "mcp_toolset" => {
                        if let Some(name) = item.get("mcp_server_name").and_then(|v| v.as_str()) {
                            mcp_names.insert(name.to_string());
                        }
                    }
                    _ => {}
                }
            }
        }
    }

    if let Some(ref mcp_val) = agent.mcp_servers {
        if let Some(arr) = mcp_val.as_array() {
            for item in arr {
                if let Some(name) = item.get("name").and_then(|v| v.as_str()) {
                    mcp_names.insert(name.to_string());
                }
            }
        }
    }

    (custom_names, mcp_names)
}
