use std::collections::HashMap;
use std::fmt;
use std::path::{Component, Path};
#[cfg(test)]
use std::sync::Arc;

use base64::Engine as _;
use flate2::write::GzEncoder;
use flate2::Compression;
use sha2::{Digest, Sha256};
use sqlx::{FromRow, PgPool};
use tar::{Builder, Header};
#[cfg(test)]
use tokio::sync::Notify;
use tracing::{debug, warn};
use uuid::Uuid;

use crate::db::queries;
use crate::grpc::proto;
use crate::ids::{
    SandboxId, SessionId, SkillId, SkillSecurityScanId, SkillUsageId, SkillVersionId, TaskId,
};
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::error::{require_bound_credential_id, CredentialRuntimeError};
use crate::kernel::credentials::mcp::resolve_mcp_member_urls;
use crate::kernel::credentials::record::ProjectId;
use crate::kernel::credentials::store::CredentialStore;
use crate::kernel::environment_binding::{self, EnvironmentBinding};
use crate::kernel::mcp_url;
use crate::kernel::repository_access::material::RepositoryAccessMaterialAdapter;
use crate::kernel::run_spec::{
    agent_for_execution, environment_for_execution, SnapshotEnvironment,
};
use crate::kernel::runtime_freshness::RuntimeFreshnessError;

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

const CONVERSATION_HISTORY_EVENT_LIMIT: i64 = 100;
const CONVERSATION_HISTORY_MAX_CHARS: usize = 24_000;

/// Constructs gRPC SetupSandbox and StartTask messages from task/agent/session data.
///
/// This mirrors Python `build_harness_input`: agent model/env/model credential, MCP
/// credentials (resolved from the session's credential groups), memory stores, packed
/// skills/agents/commands, session file resources, conversation history, custom tools,
/// and permission mode all flow through one builder.
pub struct HarnessInputBuilder {
    pool: PgPool,
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
struct HarnessBuildTestHook {
    checkpoint: HarnessBuildCheckpoint,
    reached: Arc<Notify>,
    resume: Arc<Notify>,
}

#[derive(Clone, Default)]
pub struct HarnessInput {
    pub provider: String,
    pub model: Option<String>,
    pub system_prompt: Option<String>,
    pub prompt: String,
    pub env: HashMap<String, String>,
    pub permission_mode: Option<String>,
    pub session_id: Option<String>,
    pub mcp_servers: Vec<proto::McpConfig>,
    pub custom_tools: Vec<proto::CustomTool>,
    pub skills: Vec<proto::SkillArchive>,
    pub setup_commands: Vec<String>,
    pub memory_system_prompt: Option<String>,
    pub memory_mounts: Vec<proto::MemoryStoreMount>,
    pub files: Vec<proto::FileMount>,
    pub file_refs: Vec<proto::FileRef>,
    pub repos: Vec<proto::RepoConfig>,
    pub allowed_tools: Vec<String>,
    pub ask_tools: Vec<String>,
    pub work_dir: Option<String>,
    pub max_turns: u32,
    /// "append" (default) or "replace" — controls --append-system-prompt vs --system-prompt
    pub system_prompt_mode: String,
}

impl fmt::Debug for HarnessInput {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HarnessInput")
            .field("provider", &self.provider)
            .field("model", &self.model)
            .field("system_prompt", &"<redacted>")
            .field("prompt", &"<redacted>")
            .field("env", &"<redacted>")
            .field("permission_mode", &self.permission_mode)
            .field("session_id", &self.session_id)
            .field("mcp_servers", &self.mcp_servers.len())
            .field("custom_tools", &self.custom_tools.len())
            .field("skills", &self.skills.len())
            .field("setup_commands", &"<redacted>")
            .field("memory_system_prompt", &"<redacted>")
            .field("memory_mounts", &self.memory_mounts.len())
            .field("files", &self.files.len())
            .field("file_refs", &self.file_refs.len())
            .field("repos", &self.repos.len())
            .field("allowed_tools", &self.allowed_tools.len())
            .field("ask_tools", &self.ask_tools.len())
            .field("work_dir", &self.work_dir)
            .field("max_turns", &self.max_turns)
            .field("system_prompt_mode", &self.system_prompt_mode)
            .finish()
    }
}

impl HarnessInputBuilder {
    pub fn new(pool: PgPool, envoy_enabled: bool) -> Self {
        Self {
            pool,
            envoy_enabled,
            #[cfg(test)]
            checkpoint_hook: None,
        }
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
                let fence = self
                    .load_generation_fence(session_id, sandbox_db_id)
                    .await?;
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
        let credential_access = CredentialMaterialAccessService::new(self.pool.clone());
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
            .load_live_environment(
                session.as_ref(),
                agent.as_ref(),
                snapshot_environment.as_ref(),
            )
            .await?;

        let mut input = HarnessInput {
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
            session_id: session
                .as_ref()
                .and_then(|s| s.last_harness_session_id.clone()),
            max_turns: extract_max_turns(agent.as_ref().and_then(|a| a.metadata.as_ref())),
            ..Default::default()
        };

        if let Some(ref agent) = agent {
            input.mcp_servers = parse_mcp_servers(agent.mcp_servers.as_ref());
            input.custom_tools = parse_custom_tools(agent.tools.as_ref());
            let (allowed, ask) = parse_tool_permission_rules(agent.tools.as_ref());
            input.allowed_tools = allowed;
            input.ask_tools = ask;
            input.permission_mode = agent
                .permission_mode
                .clone()
                .or_else(|| Some(derive_permission_mode_from_tools(agent.tools.as_ref())));
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
            self.resolve_skill_archives(agent, task, &mut input).await?;
        }

        if let Some(ref session) = session {
            self.resolve_mcp_group_credentials(
                session.id,
                session
                    .project_id
                    .as_deref()
                    .or_else(|| agent.as_ref().and_then(|agent| agent.project_id.as_deref())),
                &mut input.mcp_servers,
            )
            .await?;
            self.load_memory_stores(session.id, &mut input).await?;
            self.load_session_files(session.id, &mut input).await?;
            self.load_session_repos(session.id, &mut input).await?;
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
            .session_id
            .as_ref()
            .map(|sid| !sid.trim().is_empty())
            .unwrap_or(false);
        if should_inject_conversation_history(&input.provider, has_harness_resume) {
            if let Some(sid) = task.session_id {
                let history = self.build_conversation_history(sid, task.id).await;
                if !history.is_empty() {
                    input.prompt = format!("{history}\n\n{}", input.prompt);
                }
            }
        }

        // When Envoy-limited networking is active, downgrade ALL MCP server URLs
        // from https:// to http://. The sandbox has no trusted CA store and cannot
        // do end-to-end TLS; Envoy does TLS origination to the upstream instead.
        // The credential-bound path (resolve_vault_credentials) already does this
        // for servers with credentials; here we catch the rest so uncredentialed
        // MCP servers (e.g. internal services with no auth) also work.
        if self.envoy_enabled {
            for mcp in &mut input.mcp_servers {
                if mcp.url.starts_with("https://") {
                    mcp.url = mcp.url.replace("https://", "http://");
                }
            }
        }

        if let Some(initial_fence) = initial_fence {
            let final_fence = self
                .load_generation_fence(initial_fence.session_id, sandbox_db_id)
                .await?;
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

    pub fn build_setup_sandbox(input: &HarnessInput) -> proto::SetupSandbox {
        proto::SetupSandbox {
            skills: input.skills.clone(),
            mcp_servers: input.mcp_servers.clone(),
            custom_tools: input.custom_tools.clone(),
            setup_commands: input.setup_commands.clone(),
            work_dir: input.work_dir.clone(),
            env: input.env.clone(),
            // Keep the protobuf field for rolling compatibility with runners that
            // still understand it. Current orchestration injects credential material
            // at sandbox creation or the Envoy boundary, so it must remain empty.
            secrets: HashMap::new(),
            permission_mode: input.permission_mode.clone(),
            provider: input.provider.clone(),
            model: input.model.clone(),
            memory_system_prompt: input.memory_system_prompt.clone(),
            memory_mounts: input.memory_mounts.clone(),
            files: input.files.clone(),
            file_refs: input.file_refs.clone(),
            allowed_tools: input.allowed_tools.clone(),
            disallowed_tools: vec![],
            ask_tools: input.ask_tools.clone(),
            repos: input.repos.clone(),
        }
    }

    pub fn build_start_task(
        input: &HarnessInput,
        task: &crate::db::models::JoySafeterTask,
        timeout_seconds: u64,
    ) -> proto::StartTask {
        proto::StartTask {
            task_id: task.id.as_uuid().to_string(),
            provider: input.provider.clone(),
            prompt: input.prompt.clone(),
            system_prompt: input.system_prompt.clone(),
            session_id: input.session_id.clone(),
            model: input.model.clone(),
            max_turns: Some(input.max_turns),
            timeout_seconds,
            env: input.env.clone(),
            // Keep the protobuf field for rolling compatibility with runners that
            // still understand it. Current orchestration never sends credentials
            // over the task-control stream.
            secrets: HashMap::new(),
            mcp_servers: input.mcp_servers.clone(),
            repos: input.repos.clone(),
            work_dir: input.work_dir.clone(),
            skills: input.skills.clone(),
            allowed_tools: input.allowed_tools.clone(),
            disallowed_tools: vec![],
            ask_tools: input.ask_tools.clone(),
            permission_mode: input.permission_mode.clone(),
            setup_commands: input.setup_commands.clone(),
            custom_tools: input.custom_tools.clone(),
            system_prompt_mode: if input.system_prompt_mode.is_empty() {
                None
            } else {
                Some(input.system_prompt_mode.clone())
            },
        }
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
        snapshot_environment: Option<&SnapshotEnvironment>,
    ) -> anyhow::Result<Option<EnvironmentBinding>> {
        let project_id = match session {
            Some(session) => session.project_id.as_deref(),
            None => agent.and_then(|agent| agent.project_id.as_deref()),
        };
        environment_binding::resolve_live_environment_binding(
            &self.pool,
            session.and_then(|session| session.environment_ref.as_deref()),
            snapshot_environment.and_then(|environment| environment.reference.as_deref()),
            agent.and_then(|agent| agent.environment_ref.as_deref()),
            project_id,
            session.map(|session| session.id),
        )
        .await
        .map_err(Into::into)
    }

    async fn load_generation_fence(
        &self,
        session_id: SessionId,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<HarnessGenerationFence> {
        sqlx::query_as::<_, HarnessGenerationFence>(
            r#"
            SELECT
                session.id AS session_id,
                session.project_id AS session_project_id,
                session.status AS session_status,
                session.archived_at AS session_archived_at,
                session.runtime_config_generation AS generation,
                sandbox.chat_session_id AS sandbox_session_id,
                sandbox.project_id AS sandbox_project_id,
                sandbox.runtime_config_status,
                sandbox.runtime_config_applied_generation AS applied_generation
            FROM joysafeter_sessions AS session
            JOIN joysafeter_sandboxes AS sandbox ON sandbox.id = $2
            WHERE session.id = $1
            "#,
        )
        .bind(session_id)
        .bind(sandbox_id)
        .fetch_optional(&self.pool)
        .await?
        .ok_or_else(|| RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id }.into())
    }

    async fn resolve_agent_credential(
        &self,
        credential_access: &CredentialMaterialAccessService,
        context: &CredentialAccessContext,
        agent: &crate::db::models::JoySafeterAgent,
        needs_model_value: bool,
    ) -> anyhow::Result<crate::kernel::credentials::access::ResolvedModelRuntimeConfig> {
        let model_credential_id = require_bound_credential_id(agent.model_credential_id)?;
        let project_id = ProjectId::parse(
            agent
                .project_id
                .as_deref()
                .ok_or(CredentialRuntimeError::ProjectMismatch)?,
        )?;
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

    async fn resolve_skill_archives(
        &self,
        agent: &crate::db::models::JoySafeterAgent,
        task: &crate::db::models::JoySafeterTask,
        input: &mut HarnessInput,
    ) -> anyhow::Result<()> {
        for (target, items) in [
            ("skills", agent.skills.as_ref()),
            ("agents", agent.agents.as_ref()),
            ("commands", agent.commands.as_ref()),
        ] {
            let Some(arr) = items.and_then(|v| v.as_array()) else {
                continue;
            };
            for item in arr {
                let archive = self.resolve_skill_item(target, item, agent, task).await?;
                input.skills.push(archive);
            }
        }
        Ok(())
    }

    async fn resolve_skill_item(
        &self,
        target: &str,
        item: &serde_json::Value,
        agent: &crate::db::models::JoySafeterAgent,
        task: &crate::db::models::JoySafeterTask,
    ) -> anyhow::Result<proto::SkillArchive> {
        if target != "skills" {
            let encoded = item
                .get("tar_gz_b64")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow::anyhow!("packed {target} item is missing tar_gz_b64"))?;
            let data = base64::engine::general_purpose::STANDARD
                .decode(encoded)
                .map_err(|error| {
                    anyhow::anyhow!("failed to decode packed {target} archive: {error}")
                })?;
            let name = item
                .get("name")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow::anyhow!("packed {target} item is missing name"))?;
            return Ok(proto::SkillArchive {
                name: name.to_string(),
                tar_gz: data,
                target: target.to_string(),
            });
        }

        let Some(skill_id) = item.get("skill_id").and_then(|v| v.as_str()) else {
            anyhow::bail!("skill item is missing skill_id");
        };
        let version = item
            .get("version")
            .and_then(|v| v.as_str())
            .unwrap_or("latest");
        let skill_id = SkillId::from_public(skill_id)
            .map_err(|_| anyhow::anyhow!("invalid skill_id for target {target}: {skill_id}"))?;
        self.pack_skill(skill_id, version, target, agent, task)
            .await
    }

    async fn pack_skill(
        &self,
        skill_id: SkillId,
        version: &str,
        target: &str,
        agent: &crate::db::models::JoySafeterAgent,
        task: &crate::db::models::JoySafeterTask,
    ) -> anyhow::Result<proto::SkillArchive> {
        let skill = self
            .load_skill_for_archive(skill_id, agent.project_id.as_deref())
            .await?
            .ok_or_else(|| anyhow::anyhow!("skill not found: {skill_id}"))?;
        let project_latest = if version == "latest" && skill.same_project() {
            self.highest_published_version(skill_id).await
        } else {
            None
        };
        let resolved_version =
            resolve_skill_version_request(&skill, version, project_latest.as_deref())?;
        let version_meta = self
            .load_skill_version_meta(skill_id, &resolved_version)
            .await?
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "skill version not found: skill={skill_id} version={resolved_version}"
                )
            })?;
        let files = self
            .load_skill_version_files(skill_id, &resolved_version)
            .await?;

        if files.is_empty() {
            anyhow::bail!("skill {skill_id} version {resolved_version} has no files");
        }

        let skill_name = version_meta.skill_name.clone();
        let data = create_targz(&skill_name, &files)?;
        let artifact_hash = hex::encode(Sha256::digest(&data));
        self.record_skill_usage(
            skill_id,
            &resolved_version,
            &version_meta,
            &skill,
            &artifact_hash,
            target,
            agent,
            task,
        )
        .await;

        Ok(proto::SkillArchive {
            name: skill_name,
            tar_gz: data,
            target: target.to_string(),
        })
    }

    async fn load_skill_for_archive(
        &self,
        skill_id: SkillId,
        consumer_project_id: Option<&str>,
    ) -> anyhow::Result<Option<SkillForArchive>> {
        sqlx::query_as::<_, SkillForArchive>(
            r#"
            SELECT s.source_type,
                   s.project_id,
                   skill_project.org_id AS skill_org_id,
                   $2::text AS consumer_project_id,
                   consumer_project.org_id AS consumer_org_id,
                   org_version.version AS org_version,
                   public_version.version AS public_version
            FROM joysafeter_skills s
            JOIN joysafeter_organization_projects skill_project
              ON skill_project.id = s.project_id
            LEFT JOIN joysafeter_organization_projects consumer_project
              ON consumer_project.id = $2
            LEFT JOIN joysafeter_skill_versions org_version
              ON org_version.id = s.org_version_id
            LEFT JOIN joysafeter_skill_versions public_version
              ON public_version.id = s.public_version_id
            WHERE s.id = $1
            "#,
        )
        .bind(skill_id)
        .bind(consumer_project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(Into::into)
    }

    async fn load_skill_version_meta(
        &self,
        skill_id: SkillId,
        version: &str,
    ) -> anyhow::Result<Option<SkillVersionForArchive>> {
        sqlx::query_as::<_, SkillVersionForArchive>(
            r#"
            SELECT id, skill_name, security_scan_id, target_hash
            FROM joysafeter_skill_versions
            WHERE skill_id = $1 AND version = $2
            "#,
        )
        .bind(skill_id)
        .bind(version)
        .fetch_optional(&self.pool)
        .await
        .map_err(Into::into)
    }

    async fn record_skill_usage(
        &self,
        skill_id: SkillId,
        skill_version: &str,
        version_meta: &SkillVersionForArchive,
        skill: &SkillForArchive,
        artifact_hash: &str,
        target: &str,
        agent: &crate::db::models::JoySafeterAgent,
        task: &crate::db::models::JoySafeterTask,
    ) {
        let skill_version_id = Some(version_meta.id);
        let (security_scan_id, target_hash) = published_version_scan_audit(version_meta);
        if let Err(e) = sqlx::query(
            r#"
            INSERT INTO joysafeter_skill_usage_log
              (id, skill_id, skill_name, skill_source_type, skill_version, skill_version_id,
               target, security_scan_id, target_hash, artifact_hash,
               session_id, agent_id, project_id, user_id, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5,
                    CASE WHEN $6::uuid IS NULL THEN NULL
                         WHEN EXISTS (SELECT 1 FROM joysafeter_skill_versions WHERE id = $6) THEN $6
                         ELSE NULL END,
                    $7, $8, $9, $10, $11, $12, $13, NULL, NOW(), NOW())
            "#,
        )
        .bind(SkillUsageId::from_uuid(Uuid::now_v7()))
        .bind(skill_id)
        .bind(&version_meta.skill_name)
        .bind(skill.source_type.as_deref())
        .bind(skill_version)
        .bind(skill_version_id)
        .bind(target)
        .bind(security_scan_id)
        .bind(target_hash)
        .bind(artifact_hash)
        .bind(task.session_id.map(|id| id.as_uuid()))
        .bind(agent.id.as_uuid())
        .bind(agent.project_id.as_deref())
        .execute(&self.pool)
        .await
        {
            warn!(skill_id = %skill_id, "Failed to write skill usage audit row: {e}");
        }
    }

    /// Return the highest published version string for a skill, or None if it
    /// has never been published. Versions are MAJOR.MINOR.PATCH (the publish
    /// API rejects prerelease/build), so a numeric tuple sort is exact.
    async fn highest_published_version(&self, skill_id: SkillId) -> Option<String> {
        let versions: Vec<String> = sqlx::query_scalar::<_, String>(
            "SELECT version FROM joysafeter_skill_versions WHERE skill_id = $1",
        )
        .bind(skill_id)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();

        versions
            .into_iter()
            .filter_map(|v| parse_semver(&v).map(|key| (key, v)))
            .max_by(|a, b| a.0.cmp(&b.0))
            .map(|(_, v)| v)
    }

    async fn load_skill_version_files(
        &self,
        skill_id: SkillId,
        version: &str,
    ) -> anyhow::Result<Vec<SkillFileForArchive>> {
        sqlx::query_as::<_, SkillFileForArchive>(
            r#"
            SELECT vf.path, vf.file_name, vf.content
            FROM joysafeter_skill_version_files vf
            JOIN joysafeter_skill_versions sv ON sv.id = vf.version_id
            WHERE sv.skill_id = $1 AND sv.version = $2
            ORDER BY vf.path, vf.file_name
            "#,
        )
        .bind(skill_id)
        .bind(version)
        .fetch_all(&self.pool)
        .await
        .map_err(Into::into)
    }

    async fn resolve_mcp_group_credentials(
        &self,
        session_id: SessionId,
        project_id: Option<&str>,
        mcp_servers: &mut Vec<proto::McpConfig>,
    ) -> anyhow::Result<()> {
        let project_id =
            ProjectId::parse(project_id.ok_or(CredentialRuntimeError::ProjectMismatch)?)?;
        let members = CredentialStore::new(self.pool.clone())
            .load_session_mcp_member_metadata(&project_id, session_id)
            .await?;
        let credential_urls = resolve_mcp_member_urls(&members)?;

        for mcp in mcp_servers {
            let normalized = mcp_url::normalize(&mcp.url);
            if credential_urls.contains(&normalized) {
                // Downgrade the URL to plaintext http:// so the sandbox sends a
                // normal HTTP proxy request (not a CONNECT tunnel). This lets Envoy
                // see the request headers and inject the credential. Envoy then
                // does TLS origination to the real upstream via the shared
                // dynamic_forward_proxy_tls cluster. The real host is preserved so
                // the DFP filter can resolve DNS directly.
                mcp.url = mcp.url.replace("https://", "http://");
                mcp.headers.clear();
            }
        }
        Ok(())
    }

    async fn load_memory_stores(
        &self,
        session_id: SessionId,
        input: &mut HarnessInput,
    ) -> anyhow::Result<()> {
        let stores = queries::list_session_memory_stores(&self.pool, session_id)
            .await
            .map_err(|e| {
                anyhow::anyhow!("failed to load memory stores for session {session_id}: {e}")
            })?;

        let mut prompt_parts = vec![
            "# Memory".to_string(),
            "The following memory stores are mounted. Use them to persist and retrieve information across sessions.".to_string(),
            String::new(),
        ];

        for store in stores {
            let mount_path = format!("/mnt/memory/{}", store.mount_name);
            let mut files = vec![];
            let rows = queries::load_memory_files(&self.pool, store.store_id, 10000)
                .await
                .map_err(|e| {
                    anyhow::anyhow!(
                        "failed to load memory files for store {} mounted on session {}: {e}",
                        store.store_id,
                        session_id
                    )
                })?;
            for row in rows {
                files.push(proto::MemoryFile {
                    relative_path: row.path,
                    content: row.content.unwrap_or_default().into_bytes(),
                });
            }

            input.memory_mounts.push(proto::MemoryStoreMount {
                store_id: store.store_id.as_uuid().to_string(),
                mount_name: store.mount_name.clone(),
                mount_path: mount_path.clone(),
                access: store.access.clone(),
                files,
            });

            prompt_parts.push(format!("- `{}` (access: {})", mount_path, store.access));
            if let Some(instructions) = store.instructions.as_deref().filter(|v| !v.is_empty()) {
                prompt_parts.push(format!("  Instructions: {instructions}"));
            }
        }

        if input.memory_mounts.is_empty() {
            return Ok(());
        }
        input.memory_system_prompt = Some(prompt_parts.join("\n"));
        Ok(())
    }

    async fn load_session_files(
        &self,
        session_id: SessionId,
        input: &mut HarnessInput,
    ) -> anyhow::Result<()> {
        let rows: Vec<SessionFileRow> = sqlx::query_as(
            r#"
            SELECT sf.mount_path, f.filename, f.storage_key, f.size_bytes
            FROM joysafeter_session_files sf
            JOIN joysafeter_files f ON f.id = sf.file_id
            WHERE sf.session_id = $1 AND f.deleted_at IS NULL
            ORDER BY sf.mount_path
            "#,
        )
        .bind(session_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| {
            anyhow::anyhow!("failed to load session file rows for session {session_id}: {e}")
        })?;

        for row in rows {
            let content = load_session_file_resource(&row).await.map_err(|e| {
                anyhow::anyhow!(
                    "failed to prepare session file '{}' from storage key '{}': {e}",
                    row.filename,
                    row.storage_key
                )
            })?;
            input.files.push(proto::FileMount {
                path: row.mount_path,
                content,
                filename: row.filename,
            });
        }
        Ok(())
    }

    /// Load session-scoped GitHub repository resources and validate their clone
    /// material through the Repository Access adapter. Repos live on the session
    /// (``joysafeter_session_repos``), not on ``agent.metadata``; the token is
    /// and never expose clone material to the runner.
    async fn load_session_repos(
        &self,
        session_id: SessionId,
        input: &mut HarnessInput,
    ) -> anyhow::Result<()> {
        let rows: Vec<SessionRepoRow> = sqlx::query_as(
            r#"
            SELECT url, branch, mount_path, mount_name,
                   CASE
                       WHEN token_expires_at IS NULL OR token_expires_at > NOW()
                       THEN encrypted_token
                       ELSE ''
                   END AS encrypted_token
            FROM joysafeter_session_repos
            WHERE session_id = $1
            ORDER BY created_at
            "#,
        )
        .bind(session_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| {
            anyhow::anyhow!("failed to load session repos for session {session_id}: {e}")
        })?;

        if rows.is_empty() {
            return Ok(());
        }

        let material_adapter = RepositoryAccessMaterialAdapter::from_env();
        for (idx, row) in rows.into_iter().enumerate() {
            let token = material_adapter.reveal_optional(&row.encrypted_token)?;
            let has_token = token.is_some();
            // Validate the token through the adapter, but
            // never hand it to the sandbox. When a token exists, the clone URL is
            // rewritten to the Envoy egress boundary; Envoy injects the real
            // credential. Public repos (no token) keep their original URL.
            let url = if has_token {
                // Repoint the clone URL at the placeholder egress host + a stable
                // per-repo slug over plaintext http:// — the sandbox never learns
                // the real git host. Envoy matches `/git/<slug>/`, injects the
                // credential, and rewrites host+path to the real remote.
                let slug = crate::sandbox::lds_backend::git_repo_slug(&row.mount_name, idx);
                format!(
                    "http://{}/git/{}/",
                    crate::sandbox::lds_backend::GIT_EGRESS_HOST,
                    slug
                )
            } else {
                row.url
            };
            input.repos.push(proto::RepoConfig {
                url,
                branch: row.branch,
                path: row.mount_path,
                // Token never enters the sandbox — injected at the egress boundary.
                authorization_token: String::new(),
                mount_name: row.mount_name,
            });
        }
        Ok(())
    }

    async fn build_conversation_history(&self, session_id: SessionId, task_id: TaskId) -> String {
        // I-NEW-12 fix: find the user.message seq BEFORE status_running as the boundary.
        // The user.message immediately before the current turn's status_running is the
        // current prompt — it should be excluded from history (matching Python).
        let current_turn_running_seq: Option<i64> = sqlx::query_scalar(
            r#"
            SELECT MAX(seq) FROM joysafeter_session_events
            WHERE session_id = $1
              AND event_type = 'session.status_running'
              AND payload->>'task_id' = $2
            "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_optional(&self.pool)
        .await
        .ok()
        .flatten()
        .flatten();

        // Find the last user.message before the status_running event
        let boundary_seq: Option<i64> = if let Some(running_seq) = current_turn_running_seq {
            let user_msg_seq: Option<i64> = sqlx::query_scalar(
                r#"
                SELECT MAX(seq) FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'user.message'
                  AND seq < $2
                "#,
            )
            .bind(session_id)
            .bind(running_seq)
            .fetch_optional(&self.pool)
            .await
            .ok()
            .flatten()
            .flatten();
            // Use user.message seq if found, else fall back to status_running seq
            user_msg_seq.or(current_turn_running_seq)
        } else {
            None
        };

        // Load the most recent events BEFORE the boundary (excludes current turn's user message).
        // A long session must keep the newest context, not the first 500 events ever recorded.
        let rows: Vec<(String, Option<serde_json::Value>)> = match sqlx::query_as(
            r#"
            SELECT event_type, payload FROM (
                SELECT event_type, payload, seq, created_at
                FROM joysafeter_session_events
                WHERE session_id = $1 AND ($2::bigint IS NULL OR seq < $2)
                ORDER BY seq DESC, created_at DESC
                LIMIT $3
            ) recent
            ORDER BY seq ASC, created_at ASC
            "#,
        )
        .bind(session_id)
        .bind(boundary_seq)
        .bind(CONVERSATION_HISTORY_EVENT_LIMIT)
        .fetch_all(&self.pool)
        .await
        {
            Ok(rows) => rows,
            Err(_) => return String::new(),
        };

        let mut lines = Vec::new();
        for (event_type, payload) in rows {
            let Some(payload) = payload else { continue };
            match event_type.as_str() {
                "user.message" => {
                    // I16 fix: content may be a plain string OR an array of blocks
                    // [{type: "text", text: "..."}]. Handle both formats.
                    let text = extract_content_text(&payload);
                    if !text.is_empty() {
                        lines.push(format!("User: {text}"));
                    }
                }
                "agent.message" => {
                    let text = extract_content_text(&payload);
                    if !text.is_empty() {
                        lines.push(format!("Assistant: {text}"));
                    }
                }
                _ => {}
            }
        }
        if lines.is_empty() {
            return String::new();
        }
        let body = trim_history_lines_to_budget(lines, CONVERSATION_HISTORY_MAX_CHARS);
        if body.is_empty() {
            return String::new();
        }

        format!(
            "[CONVERSATION HISTORY - Prior turns in this session]\n{}\n[END CONVERSATION HISTORY]",
            body
        )
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

fn trim_history_lines_to_budget(lines: Vec<String>, max_chars: usize) -> String {
    if lines.is_empty() || max_chars == 0 {
        return String::new();
    }

    let mut selected = Vec::new();
    let mut used = 0usize;
    for line in lines.into_iter().rev() {
        let line_chars = line.chars().count();
        let separator_chars = if selected.is_empty() { 0 } else { 2 };
        if used + separator_chars + line_chars <= max_chars {
            used += separator_chars + line_chars;
            selected.push(line);
            continue;
        }

        if selected.is_empty() {
            let remaining = max_chars.saturating_sub(separator_chars);
            let truncated = truncate_start_chars(&line, remaining);
            if !truncated.is_empty() {
                selected.push(truncated);
            }
        }
        break;
    }

    selected.reverse();
    selected.join("\n\n")
}

fn truncate_start_chars(value: &str, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value.to_string();
    }
    if max_chars == 0 {
        return String::new();
    }
    const PREFIX: &str = "...";
    if max_chars <= PREFIX.len() {
        return value
            .chars()
            .rev()
            .take(max_chars)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect();
    }

    let keep_chars = max_chars - PREFIX.len();
    let suffix: String = value
        .chars()
        .rev()
        .take(keep_chars)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    format!("{PREFIX}{suffix}")
}

/// Extract text content from a session event payload.
///
/// Content may be stored as:
/// - A plain string: `{"content": "hello"}`
/// - An array of blocks: `{"content": [{"type": "text", "text": "hello"}]}`
///
/// Returns the concatenated text, trimmed.  Empty string if nothing found.
fn extract_content_text(payload: &serde_json::Value) -> String {
    let content = match payload.get("content") {
        Some(c) => c,
        None => return String::new(),
    };

    // Case 1: plain string
    if let Some(s) = content.as_str() {
        return s.trim().to_string();
    }

    // Case 2: array of blocks [{type: "text", text: "..."}]
    if let Some(blocks) = content.as_array() {
        let mut parts = Vec::new();
        for block in blocks {
            if block.get("type").and_then(|t| t.as_str()) == Some("text") {
                if let Some(text) = block.get("text").and_then(|t| t.as_str()) {
                    parts.push(text);
                }
            }
        }
        let joined = parts.join("");
        return joined.trim().to_string();
    }

    String::new()
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
        apply_runtime_protocol_env, extract_content_text, parse_semver,
        published_version_scan_audit, resolve_skill_version_request, session_container_work_dir,
        should_inject_conversation_history, trim_history_lines_to_budget, HarnessBuildCheckpoint,
        HarnessInputBuilder, SkillForArchive, SkillVersionForArchive,
    };
    use crate::ids::{
        AgentId, CredentialGroupId, CredentialId, EnvironmentId, FileId, SandboxId, SessionId,
        SessionResourceId, SkillVersionId, TaskId,
    };
    use crate::kernel::runtime_freshness::RuntimeFreshnessError;
    use uuid::Uuid;

    const ENCRYPTED_HELLO_WORLD: &str =
        "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";

    fn database_url() -> Option<String> {
        env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
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
        project_id: &str,
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
        org_id: String,
        project_id: String,
    }

    async fn insert_generation_fixture(pool: &PgPool) -> GenerationFixture {
        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = format!("harness-generation-org-{unique}");
        let project_id = format!("harness-generation-project-{unique}");
        let environment_ref = environment_id.to_string();
        let snapshot = json!({
            "schema": "joysafeter.agent_execution_snapshot.v1",
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
            "environment_ref": environment_ref,
            "model_credential_id": null,
            "environment": {
                "ref": environment_ref,
                "id": environment_id.to_string(),
                "name": format!("harness-generation-env-{unique}"),
                "image_tag": "snapshot-image:1",
                "image_version": 1,
                "config": {
                    "env_vars": {"FROZEN_VALUE": "snapshot"},
                    "secret_refs": [],
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
        .bind(json!({"env_vars": {"FROZEN_VALUE": "live"}, "secret_refs": []}))
        .execute(pool)
        .await
        .expect("insert generation environment");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (
                id, project_id, name, engine_kind, env, mcp_servers, skills, tools,
                agents, commands, permission_mode, metadata, version, environment_ref
            )
            VALUES ($1, $2, $3, 'claude', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'default', '{}'::jsonb, 1, $4)
            "#,
        )
        .bind(agent_id)
        .bind(&project_id)
        .bind(format!("harness-generation-agent-{unique}"))
        .bind(&environment_ref)
        .execute(pool)
        .await
        .expect("insert generation agent");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_sessions (
                id, agent_id, project_id, status, agent_version, agent_snapshot,
                environment_ref, runtime_config_generation
            )
            VALUES ($1, $2, $3, 'idle', 1, $4, $5, 7)
            "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&project_id)
        .bind(&snapshot)
        .bind(&environment_ref)
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
    async fn harness_input_explicit_invalid_environment_binding_fails_closed() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let fixture = insert_generation_fixture(&pool).await;
        let missing_environment = EnvironmentId::from_uuid(Uuid::now_v7()).to_string();
        sqlx::query("UPDATE joysafeter_sessions SET environment_ref = $2 WHERE id = $1")
            .bind(fixture.session_id)
            .bind(&missing_environment)
            .execute(&pool)
            .await
            .expect("replace canonical environment binding");
        let task = crate::db::queries::get_task(&pool, fixture.task_id)
            .await
            .expect("load generation task")
            .expect("generation task exists");

        let error = HarnessInputBuilder::new(pool.clone(), false)
            .build(&task, "sandbox-ext", fixture.sandbox_id)
            .await
            .expect_err("explicit missing binding must not fall back to the snapshot");
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

    fn exposed_skill(
        consumer_project_id: Option<&str>,
        consumer_org_id: Option<&str>,
    ) -> SkillForArchive {
        SkillForArchive {
            source_type: Some("local".to_string()),
            project_id: "project-source".to_string(),
            skill_org_id: "org-source".to_string(),
            consumer_project_id: consumer_project_id.map(str::to_string),
            consumer_org_id: consumer_org_id.map(str::to_string),
            org_version: Some("1.0.0".to_string()),
            public_version: Some("0.9.0".to_string()),
        }
    }

    #[test]
    fn same_org_latest_uses_promoted_versions_only() {
        let skill = exposed_skill(Some("project-consumer"), Some("org-source"));
        assert_eq!(
            resolve_skill_version_request(&skill, "latest", Some("2.0.0")).unwrap(),
            "1.0.0"
        );
    }

    #[test]
    fn cross_org_latest_uses_public_pointer_only() {
        let skill = exposed_skill(Some("project-consumer"), Some("org-consumer"));
        assert_eq!(
            resolve_skill_version_request(&skill, "latest", Some("2.0.0")).unwrap(),
            "0.9.0"
        );
    }

    #[test]
    fn cross_project_explicit_private_version_is_rejected() {
        let skill = exposed_skill(Some("project-consumer"), Some("org-source"));
        let error = resolve_skill_version_request(&skill, "2.0.0", Some("2.0.0")).unwrap_err();
        assert!(error.to_string().contains("not exposed"));
    }

    #[test]
    fn same_project_latest_uses_project_latest() {
        let skill = exposed_skill(Some("project-source"), Some("org-source"));
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
            security_scan_id: None,
            target_hash: None,
        };

        assert_eq!(published_version_scan_audit(&version), (None, None));
    }

    #[test]
    fn injects_history_for_cli_providers() {
        assert!(should_inject_conversation_history("claude", false));
        assert!(should_inject_conversation_history("codex", false));
        assert!(!should_inject_conversation_history("claude", true));
        assert!(!should_inject_conversation_history("langgraph_code", false));
    }

    #[test]
    fn trims_history_to_newest_lines_under_budget() {
        let body = trim_history_lines_to_budget(
            vec![
                "User: older".to_string(),
                "Assistant: middle".to_string(),
                "User: newest".to_string(),
            ],
            31,
        );

        assert_eq!(body, "Assistant: middle\n\nUser: newest");
    }

    #[test]
    fn extracts_plain_string_content() {
        let payload = serde_json::json!({ "content": " hello " });

        assert_eq!(extract_content_text(&payload), "hello");
    }

    #[test]
    fn extracts_text_block_content() {
        let payload = serde_json::json!({
            "content": [
                { "type": "text", "text": "hello" },
                { "type": "image", "url": "ignored" },
                { "type": "text", "text": " world" }
            ]
        });

        assert_eq!(extract_content_text(&payload), "hello world");
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
        let org_id = format!("org-{unique}");
        let project_id = format!("proj-{unique}");
        let environment_ref = environment_id.to_string();
        let snapshot_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let live_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let snapshot_environment_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let live_environment_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let agent_name = format!("snapshot-agent-{unique}");
        let environment_name = format!("snapshot-env-{unique}");
        let snapshot = json!({
            "schema": "joysafeter.agent_execution_snapshot.v1",
            "id": agent_id.to_string(),
            "version": 7,
            "name": agent_name,
            "engine_kind": "claude",
            "model": null,
            "system": "snapshot system",
            "env": {"AGENT_LEVEL": "snapshot-agent-env"},
            "mcp_servers": [{
                "name": "snapshot-mcp",
                "type": "http",
                "url": "https://mcp.snapshot.example"
            }],
            "tools": [{
                "type": "custom",
                "name": "snapshot_tool",
                "description": "from snapshot"
            }],
            "permission_mode": "bypassPermissions",
            "metadata": {"setup_commands": ["echo snapshot-metadata"], "max_turns": 12},
            "skills": [],
            "agents": [],
            "commands": [],
            "environment_ref": environment_ref,
            "model_credential_id": snapshot_credential_id.to_string(),
            "environment": {
                "ref": environment_ref,
                "id": environment_id.to_string(),
                "name": environment_name,
                "image_tag": "snapshot-image:1",
                "image_version": 1,
                "config": {
                    "env_vars": {"ENV_LEVEL": "snapshot-env"},
                    "secret_refs": [snapshot_environment_credential_id.to_string()],
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
                "secret_refs": [live_environment_credential_id.to_string()],
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
                    skills, tools, agents, commands, permission_mode, metadata,
                    version, environment_ref, model_credential_id
                )
                VALUES (
                    $1, $2, $3, 'codex', $4, 'live system', $5, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'default', '{}'::jsonb, 8, $6, $7
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(&agent_name)
            .bind(json!({"id": "live-model"}))
            .bind(json!({"AGENT_LEVEL": "live-agent-env", "LIVE_AGENT_ONLY": "must-not-appear"}))
            .bind(&environment_ref)
            .bind(live_credential_id)
            .execute(&pool)
            .await
            .expect("insert live agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, project_id, status, agent_version, agent_snapshot, environment_ref
                )
                VALUES ($1, $2, $3, 'idle', 7, $4, $5)
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .bind(&snapshot)
            .bind(&environment_ref)
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
            let input = HarnessInputBuilder::new(pool.clone(), false)
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
        let org_id = format!("org-{unique}");
        let project_id = format!("proj-{unique}");
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
                    mcp_servers, skills, tools, agents, commands, permission_mode,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, 'bypassPermissions', '{}'::jsonb, 1
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
        let org_id = format!("org-{unique}");
        let project_id = format!("proj-{unique}");
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
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb, $5,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("vault-alias-agent-{unique}"))
            .bind(json!({"id": "claude-sonnet"}))
            .bind(json!([{
                "name": "secure-mcp",
                "type": "http",
                "url": mcp_url
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
            let input = HarnessInputBuilder::new(pool.clone(), false)
                .build(&task, "sandbox-ext", sandbox_id)
                .await
                .expect("build harness input");

            assert_eq!(input.mcp_servers.len(), 1);
            assert_eq!(input.mcp_servers[0].name, "secure-mcp");
            assert_eq!(
                input.mcp_servers[0].url,
                "http://mcp.vault-alias.example/api"
            );
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
        let org_id = format!("org-{unique}");
        let project_id = format!("proj-{unique}");
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
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb, $5,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("vault-decrypt-fail-agent-{unique}"))
            .bind(json!({"id": "claude-sonnet"}))
            .bind(json!([{
                "name": "secure-mcp",
                "type": "http",
                "url": mcp_url
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
            let input = HarnessInputBuilder::new(pool.clone(), false)
                .build(&task, "sandbox-ext", sandbox_id)
                .await
                .expect("MCP metadata must not reveal token material");
            assert_eq!(input.mcp_servers.len(), 1);
            assert_eq!(
                input.mcp_servers[0].url,
                mcp_url.replace("https://", "http://")
            );
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

fn parse_mcp_servers(value: Option<&serde_json::Value>) -> Vec<proto::McpConfig> {
    value
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .map(|item| proto::McpConfig {
                    name: item["name"].as_str().unwrap_or("").to_string(),
                    command: String::new(),
                    args: Vec::new(),
                    env: HashMap::new(),
                    server_type: item["type"].as_str().unwrap_or("url").to_string(),
                    url: item["url"].as_str().unwrap_or("").to_string(),
                    headers: HashMap::new(),
                })
                .collect()
        })
        .unwrap_or_default()
}

fn parse_custom_tools(value: Option<&serde_json::Value>) -> Vec<proto::CustomTool> {
    value
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter(|item| item.get("type").and_then(|v| v.as_str()) == Some("custom"))
                .filter_map(|item| {
                    let name = item.get("name").and_then(|v| v.as_str())?;
                    Some(proto::CustomTool {
                        name: name.to_string(),
                        description: item
                            .get("description")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        input_schema_json: item
                            .get("input_schema")
                            .map(|v| v.to_string())
                            .unwrap_or_else(|| "{}".to_string()),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Parse agent toolsets into (allow, ask) permission rule lists, matching the
/// official Anthropic Managed Agents permission model: the only policies are
/// `always_allow` and `always_ask` (no "disable"). Defaults match the API:
/// agent_toolset_20260401 -> always_allow, mcp_toolset -> always_ask.
/// A per-tool configs[].permission_policy overrides the toolset default.
/// MCP tool names map to `mcp__<server>__*` / `mcp__<server>__<tool>`.
fn parse_tool_permission_rules(value: Option<&serde_json::Value>) -> (Vec<String>, Vec<String>) {
    let mut allow = vec![];
    let mut ask = vec![];
    let Some(arr) = value.and_then(|v| v.as_array()) else {
        return (allow, ask);
    };
    for tool in arr {
        let tool_type = tool.get("type").and_then(|v| v.as_str());
        let default_policy = tool
            .get("default_config")
            .and_then(|c| c.get("permission_policy"))
            .and_then(|p| p.get("type"))
            .and_then(|v| v.as_str());

        let cfg_policy = |cfg: &serde_json::Value| -> Option<String> {
            cfg.get("permission_policy")
                .and_then(|p| p.get("type"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
                .or_else(|| default_policy.map(|s| s.to_string()))
        };

        match tool_type {
            Some("agent_toolset_20260401") => {
                let Some(configs) = tool.get("configs").and_then(|v| v.as_array()) else {
                    continue;
                };
                for cfg in configs {
                    let Some(name) = cfg.get("name").and_then(|v| v.as_str()) else {
                        continue;
                    };
                    // Agent toolset default is always_allow.
                    if cfg_policy(cfg).as_deref() == Some("always_ask") {
                        ask.push(name.to_string());
                    } else {
                        allow.push(name.to_string());
                    }
                }
            }
            Some("mcp_toolset") => {
                let server = tool
                    .get("name")
                    .and_then(|v| v.as_str())
                    .or_else(|| tool.get("mcp_server_name").and_then(|v| v.as_str()))
                    .unwrap_or("");
                if server.is_empty() {
                    continue;
                }
                let configs = tool.get("configs").and_then(|v| v.as_array());
                match configs {
                    Some(cfgs) if !cfgs.is_empty() => {
                        for cfg in cfgs {
                            let tool_name = cfg.get("name").and_then(|v| v.as_str()).unwrap_or("");
                            let rule = if tool_name.is_empty() || tool_name == server {
                                format!("mcp__{server}__*")
                            } else {
                                format!("mcp__{server}__{tool_name}")
                            };
                            // MCP toolset default is always_ask.
                            if cfg_policy(cfg).as_deref() == Some("always_allow") {
                                allow.push(rule);
                            } else {
                                ask.push(rule);
                            }
                        }
                    }
                    _ => {
                        let rule = format!("mcp__{server}__*");
                        // MCP toolset default is always_ask.
                        if default_policy == Some("always_allow") {
                            allow.push(rule);
                        } else {
                            ask.push(rule);
                        }
                    }
                }
            }
            _ => continue,
        }
    }
    (allow, ask)
}

fn derive_permission_mode_from_tools(tools: Option<&serde_json::Value>) -> String {
    if let Some(arr) = tools.and_then(|v| v.as_array()) {
        for tool in arr {
            if tool
                .get("default_config")
                .and_then(|cfg| cfg.get("permission_policy"))
                .and_then(|p| p.get("type"))
                .and_then(|v| v.as_str())
                == Some("always_ask")
            {
                return "default".to_string();
            }
            if let Some(configs) = tool.get("configs").and_then(|v| v.as_array()) {
                for cfg in configs {
                    if cfg
                        .get("permission_policy")
                        .and_then(|p| p.get("type"))
                        .and_then(|v| v.as_str())
                        == Some("always_ask")
                    {
                        return "default".to_string();
                    }
                }
            }
        }
    }
    "bypassPermissions".to_string()
}

/// Parse a strict ``MAJOR.MINOR.PATCH`` version into a comparable tuple.
/// Returns None for anything that isn't three numeric components.
fn parse_semver(v: &str) -> Option<(u64, u64, u64)> {
    let mut parts = v.split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next()?.parse().ok()?;
    let patch = parts.next()?.parse().ok()?;
    if parts.next().is_some() {
        return None;
    }
    Some((major, minor, patch))
}

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

fn create_targz(root_dir: &str, files: &[SkillFileForArchive]) -> anyhow::Result<Vec<u8>> {
    let safe_root = safe_archive_component(root_dir).unwrap_or_else(|| "unknown".to_string());
    let encoder = GzEncoder::new(Vec::new(), Compression::default());
    let mut tar = Builder::new(encoder);

    for file in files {
        let Some(path) = safe_archive_path(file) else {
            continue;
        };
        let archive_path = format!("{safe_root}/{path}");
        let content = file.content.clone().unwrap_or_default().into_bytes();
        let mut header = Header::new_gnu();
        header.set_size(content.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        tar.append_data(&mut header, archive_path, content.as_slice())?;
    }

    let encoder = tar.into_inner()?;
    Ok(encoder.finish()?)
}

fn safe_archive_component(value: &str) -> Option<String> {
    let normalized = value.replace('\\', "/");
    let component = Path::new(&normalized)
        .file_name()?
        .to_string_lossy()
        .to_string();
    if component.is_empty() || component == "." || component == ".." || component.contains('/') {
        return None;
    }
    Some(component)
}

fn safe_archive_path(file: &SkillFileForArchive) -> Option<String> {
    let raw_path = file.path.clone().unwrap_or_default().replace('\\', "/");
    let file_name = file
        .file_name
        .clone()
        .unwrap_or_default()
        .replace('\\', "/");
    let candidate = if raw_path.is_empty() || raw_path == "." {
        file_name
    } else if raw_path.ends_with('/') {
        format!("{raw_path}{file_name}")
    } else if !file_name.is_empty()
        && Path::new(&raw_path).file_name().and_then(|v| v.to_str()) != Some(file_name.as_str())
    {
        format!("{raw_path}/{file_name}")
    } else {
        raw_path
    };

    let mut parts = Vec::new();
    for component in Path::new(&candidate).components() {
        match component {
            Component::Normal(v) => parts.push(v.to_string_lossy().to_string()),
            Component::CurDir => {}
            _ => return None,
        }
    }
    if parts.is_empty() {
        None
    } else {
        Some(parts.join("/"))
    }
}

// Storage read is now handled by `sandbox::storage::read_file()`.

async fn load_session_file_resource(row: &SessionFileRow) -> anyhow::Result<Vec<u8>> {
    crate::sandbox::storage::read_file(&row.storage_key).await
}

#[derive(Debug, FromRow)]
struct SkillForArchive {
    source_type: Option<String>,
    project_id: String,
    skill_org_id: String,
    consumer_project_id: Option<String>,
    consumer_org_id: Option<String>,
    org_version: Option<String>,
    public_version: Option<String>,
}

impl SkillForArchive {
    fn same_project(&self) -> bool {
        self.consumer_project_id.as_deref() == Some(self.project_id.as_str())
    }

    fn same_org(&self) -> bool {
        self.consumer_org_id.as_deref() == Some(self.skill_org_id.as_str())
    }

    fn exposed_versions(&self) -> Vec<&str> {
        if self.same_project() {
            return Vec::new();
        }
        let mut versions = Vec::new();
        if let Some(version) = self.public_version.as_deref() {
            versions.push(version);
        }
        if self.same_org() {
            if let Some(version) = self.org_version.as_deref() {
                if !versions.contains(&version) {
                    versions.push(version);
                }
            }
        }
        versions
    }
}

fn resolve_skill_version_request(
    skill: &SkillForArchive,
    requested: &str,
    project_latest: Option<&str>,
) -> anyhow::Result<String> {
    if skill.same_project() {
        if requested == "latest" {
            return project_latest
                .map(str::to_string)
                .ok_or_else(|| anyhow::anyhow!("skill has no published version"));
        }
        return Ok(requested.to_string());
    }

    let exposed = skill.exposed_versions();
    if requested == "latest" {
        return exposed
            .into_iter()
            .filter_map(|version| parse_semver(version).map(|key| (key, version)))
            .max_by(|left, right| left.0.cmp(&right.0))
            .map(|(_, version)| version.to_string())
            .ok_or_else(|| anyhow::anyhow!("skill has no version exposed to this project"));
    }
    if exposed.contains(&requested) {
        return Ok(requested.to_string());
    }
    anyhow::bail!("skill version {requested} is not exposed to this project")
}

#[derive(Debug, FromRow)]
struct SkillVersionForArchive {
    id: SkillVersionId,
    skill_name: String,
    security_scan_id: Option<SkillSecurityScanId>,
    target_hash: Option<String>,
}

fn published_version_scan_audit(
    version_meta: &SkillVersionForArchive,
) -> (Option<SkillSecurityScanId>, Option<&str>) {
    (
        version_meta.security_scan_id,
        version_meta.target_hash.as_deref(),
    )
}

#[derive(Debug, FromRow)]
struct SkillFileForArchive {
    path: Option<String>,
    file_name: Option<String>,
    content: Option<String>,
}

#[derive(Debug, FromRow)]
struct SessionFileRow {
    mount_path: String,
    filename: String,
    storage_key: String,
    size_bytes: i64,
}

#[derive(Debug, FromRow)]
struct SessionRepoRow {
    url: String,
    branch: String,
    mount_path: String,
    mount_name: String,
    encrypted_token: String,
}

#[derive(Debug, FromRow)]
struct HarnessGenerationFence {
    session_id: SessionId,
    session_project_id: Option<String>,
    session_status: String,
    session_archived_at: Option<chrono::DateTime<chrono::Utc>>,
    sandbox_session_id: Option<SessionId>,
    sandbox_project_id: Option<String>,
    runtime_config_status: String,
    generation: i64,
    applied_generation: i64,
}

impl HarnessGenerationFence {
    fn validate(&self, sandbox_id: SandboxId) -> Result<(), RuntimeFreshnessError> {
        if self.session_archived_at.is_some() || self.session_status == "terminated" {
            return Err(RuntimeFreshnessError::SessionBindingInvalid {
                session_id: self.session_id,
                reason: "inactive session",
            });
        }
        if self.sandbox_session_id != Some(self.session_id)
            || self.sandbox_project_id != self.session_project_id
        {
            return Err(RuntimeFreshnessError::Conflict(format!(
                "sandbox {sandbox_id} ownership changed"
            )));
        }
        if self.applied_generation != self.generation {
            return Err(RuntimeFreshnessError::GenerationChanged {
                expected: self.generation,
                actual: self.applied_generation,
            });
        }
        if self.runtime_config_status != "ready" {
            return Err(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id });
        }
        Ok(())
    }
}

/// Extract custom tool names and MCP server names from agent config.
/// Used by grpc/server.rs to route events to correct types.
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
                        if let Some(name) = item.get("name").and_then(|v| v.as_str()) {
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
