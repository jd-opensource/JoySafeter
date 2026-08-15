use std::collections::HashMap;
use std::path::{Component, Path};

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::Engine as _;
use chrono::Utc;
use flate2::write::GzEncoder;
use flate2::Compression;
use sha2::{Digest, Sha256};
use sqlx::{FromRow, PgPool};
use tar::{Builder, Header};
use tracing::{debug, warn};
use uuid::Uuid;

use crate::db::queries;
use crate::grpc::proto;
use crate::ids::{
    CredentialGroupId, CredentialId, EnvironmentId, SandboxId, SessionId, SkillId,
    SkillSecurityScanId, SkillUsageId, SkillVersionId, TaskId,
};
use crate::kernel::llm_catalog::{validate_runtime_secret, RuntimeSecretBinding};
use crate::kernel::mcp_url;
use crate::kernel::run_spec::{
    agent_for_execution, environment_for_execution, SnapshotEnvironment,
};

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
}

#[derive(Debug, Clone, Default)]
pub struct HarnessInput {
    pub provider: String,
    pub model: Option<String>,
    pub system_prompt: Option<String>,
    pub prompt: String,
    pub env: HashMap<String, String>,
    pub secrets: HashMap<String, String>,
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

impl HarnessInputBuilder {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn build(
        &self,
        task: &crate::db::models::JoySafeterTask,
        sandbox_external_id: &str,
        _sandbox_db_id: SandboxId,
    ) -> anyhow::Result<HarnessInput> {
        let live_agent = match task.agent_id {
            Some(aid) => queries::get_agent(&self.pool, aid).await?,
            None => None,
        };
        let session = match task.session_id {
            Some(sid) => queries::get_session(&self.pool, sid).await?,
            None => None,
        };
        let snapshot_environment = environment_for_execution(session.as_ref());
        let agent = agent_for_execution(live_agent, session.as_ref());

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
            input.setup_commands = self
                .resolve_environment_setup_commands(agent, snapshot_environment.as_ref())
                .await;
            input
                .setup_commands
                .extend(extract_setup_commands(agent.metadata.as_ref()));

            self.resolve_environment_env(agent, snapshot_environment.as_ref(), &mut input)
                .await?;
            if let Some(binding) = self.resolve_agent_secret(agent, &mut input).await? {
                resolve_model_from_binding(&mut input, &binding);
            }
            input
                .env
                .extend(json_object_to_string_map(agent.env.as_ref()));
            self.resolve_skill_archives(agent, task, &mut input).await?;
        }

        if let Some(ref session) = session {
            self.resolve_vault_credentials(session.id, &mut input.mcp_servers)
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

    async fn resolve_environment_setup_commands(
        &self,
        agent: &crate::db::models::JoySafeterAgent,
        snapshot_environment: Option<&SnapshotEnvironment>,
    ) -> Vec<String> {
        if let Some(environment) = snapshot_environment {
            return extract_package_install_commands(environment.config.get("packages"));
        }

        let Some(env_ref) = agent
            .environment_ref
            .as_deref()
            .filter(|v| !v.trim().is_empty())
        else {
            return vec![];
        };
        let environment = match self
            .load_environment(env_ref, agent.project_id.as_deref())
            .await
        {
            Ok(Some(env)) => env,
            Ok(None) => return vec![],
            Err(e) => {
                warn!(environment_ref = env_ref, "Failed to load environment: {e}");
                return vec![];
            }
        };
        extract_package_install_commands(environment.config.get("packages"))
    }

    async fn load_environment(
        &self,
        env_ref: &str,
        project_id: Option<&str>,
    ) -> anyhow::Result<Option<EnvironmentRow>> {
        if let Ok(env_id) = EnvironmentId::from_public(env_ref) {
            return sqlx::query_as::<_, EnvironmentRow>(
                r#"
                SELECT config FROM joysafeter_environments
                WHERE id = $1 AND deleted_at IS NULL
                  AND ($2::text IS NULL OR project_id = $2)
                "#,
            )
            .bind(env_id)
            .bind(project_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(Into::into);
        }

        sqlx::query_as::<_, EnvironmentRow>(
            r#"
            SELECT config FROM joysafeter_environments
            WHERE name = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            "#,
        )
        .bind(env_ref)
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(Into::into)
    }

    async fn resolve_agent_secret(
        &self,
        agent: &crate::db::models::JoySafeterAgent,
        input: &mut HarnessInput,
    ) -> anyhow::Result<Option<RuntimeSecretBinding>> {
        let Some(model_credential_id) = agent.model_credential_id else {
            return Ok(None);
        };

        let engine_kind = input.provider.clone();
        self.resolve_secret_ref_into_input(
            model_credential_id,
            agent.project_id.as_deref(),
            input,
            true,
            Some(&engine_kind),
        )
        .await
    }

    async fn resolve_environment_env(
        &self,
        agent: &crate::db::models::JoySafeterAgent,
        snapshot_environment: Option<&SnapshotEnvironment>,
        input: &mut HarnessInput,
    ) -> anyhow::Result<()> {
        let environment_config = if let Some(environment) = snapshot_environment {
            Some(environment.config.clone())
        } else {
            let Some(env_ref) = agent
                .environment_ref
                .as_deref()
                .filter(|v| !v.trim().is_empty())
            else {
                return Ok(());
            };

            self.load_environment(env_ref, agent.project_id.as_deref())
                .await?
                .map(|environment| environment.config)
        };

        let Some(environment_config) = environment_config else {
            return Ok(());
        };

        input.env.extend(json_object_to_string_map(
            environment_config.get("env_vars"),
        ));

        // Environment-level credentials are referenced by id. Both the legacy
        // list form (`secret_refs`) and the single `service_credential_id` now
        // hold canonical `cred_` ids resolved against `joysafeter_credentials`.
        let mut env_credential_ids: Vec<CredentialId> = Vec::new();
        if let Some(service_credential_id) = environment_config
            .get("service_credential_id")
            .and_then(|v| v.as_str())
            .filter(|v| !v.trim().is_empty())
            .and_then(|raw| CredentialId::from_public(raw).ok())
        {
            env_credential_ids.push(service_credential_id);
        }
        if let Some(secret_refs) = environment_config
            .get("secret_refs")
            .and_then(|v| v.as_array())
        {
            for raw in secret_refs.iter().filter_map(|v| v.as_str()) {
                if let Ok(credential_id) = CredentialId::from_public(raw) {
                    env_credential_ids.push(credential_id);
                }
            }
        }
        for credential_id in env_credential_ids {
            self.resolve_secret_ref_into_input(
                credential_id,
                agent.project_id.as_deref(),
                input,
                false,
                None,
            )
            .await?;
        }

        Ok(())
    }

    async fn resolve_secret_ref_into_input(
        &self,
        credential_id: CredentialId,
        project_id: Option<&str>,
        input: &mut HarnessInput,
        override_existing: bool,
        runtime_engine_kind: Option<&str>,
    ) -> anyhow::Result<Option<RuntimeSecretBinding>> {
        let secret = sqlx::query_as::<_, SecretRow>(
            r#"
            SELECT kind, provider, protocol, data FROM joysafeter_credentials
            WHERE id = $1 AND archived_at IS NULL AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            "#,
        )
        .bind(credential_id)
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await?;

        let Some(secret) = secret else {
            return Ok(None);
        };

        let binding = runtime_engine_kind
            .map(|engine_kind| {
                validate_runtime_secret(
                    engine_kind,
                    &secret.kind,
                    secret.provider.as_deref(),
                    secret.protocol.as_deref(),
                )
            })
            .transpose()?;

        let cipher = VaultCipher::from_env();
        for (key, value) in json_object_to_string_map(Some(&secret.data)) {
            if override_existing || !input.secrets.contains_key(&key) {
                input.secrets.insert(key, cipher.decrypt_envelope(&value)?);
            }
        }

        Ok(binding)
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
            .load_skill_for_archive(skill_id)
            .await?
            .ok_or_else(|| anyhow::anyhow!("skill not found: {skill_id}"))?;
        ensure_skill_runtime_ready(&skill)?;
        let (resolved_version, version_meta, files) = if version == "latest" {
            let resolved = self
                .highest_published_version(skill_id)
                .await
                .ok_or_else(|| anyhow::anyhow!("skill {skill_id} has no published version"))?;
            let meta = self
                .load_skill_version_meta(skill_id, &resolved)
                .await?
                .ok_or_else(|| {
                    anyhow::anyhow!("skill version not found: skill={skill_id} version={resolved}")
                })?;
            let files = self.load_skill_version_files(skill_id, &resolved).await?;
            (resolved, Some(meta), files)
        } else {
            let meta = self
                .load_skill_version_meta(skill_id, version)
                .await?
                .ok_or_else(|| {
                    anyhow::anyhow!("skill version not found: skill={skill_id} version={version}")
                })?;
            let files = self.load_skill_version_files(skill_id, version).await?;
            (version.to_string(), Some(meta), files)
        };

        if files.is_empty() {
            anyhow::bail!("skill {skill_id} version {resolved_version} has no files");
        }

        let data = create_targz(&skill.name, &files)?;
        let artifact_hash = hex::encode(Sha256::digest(&data));
        self.record_skill_usage(
            skill_id,
            &resolved_version,
            version_meta.as_ref(),
            &skill,
            &artifact_hash,
            target,
            agent,
            task,
        )
        .await;

        Ok(proto::SkillArchive {
            name: skill.name,
            tar_gz: data,
            target: target.to_string(),
        })
    }

    async fn load_skill_for_archive(
        &self,
        skill_id: SkillId,
    ) -> anyhow::Result<Option<SkillForArchive>> {
        sqlx::query_as::<_, SkillForArchive>(
            r#"
            SELECT name, source_type, lifecycle_status, security_status, security_scan_hash, security_scan_id
            FROM joysafeter_skills
            WHERE id = $1
            "#,
        )
        .bind(skill_id)
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
            SELECT id, security_scan_id, target_hash
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
        version_meta: Option<&SkillVersionForArchive>,
        skill: &SkillForArchive,
        artifact_hash: &str,
        target: &str,
        agent: &crate::db::models::JoySafeterAgent,
        task: &crate::db::models::JoySafeterTask,
    ) {
        let (skill_version_id, security_scan_id, target_hash) = match version_meta {
            Some(meta) => (
                Some(meta.id),
                meta.security_scan_id.or(skill.security_scan_id),
                meta.target_hash
                    .as_deref()
                    .or(skill.security_scan_hash.as_deref()),
            ),
            None => (
                None,
                skill.security_scan_id,
                skill.security_scan_hash.as_deref(),
            ),
        };
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
        .bind(&skill.name)
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

    async fn resolve_vault_credentials(
        &self,
        session_id: SessionId,
        mcp_servers: &mut Vec<proto::McpConfig>,
    ) -> anyhow::Result<()> {
        // Credential groups bound to the session gate which MCP credentials the
        // session may use.
        let group_ids: Vec<CredentialGroupId> = sqlx::query_as::<_, (CredentialGroupId,)>(
            r#"
            SELECT credential_group_id
            FROM joysafeter_session_credential_groups
            WHERE session_id = $1
            "#,
        )
        .bind(session_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| {
            anyhow::anyhow!(
                "failed to load session credential groups for session {session_id}: {e}"
            )
        })?
        .into_iter()
        .map(|(id,)| id)
        .collect();
        if group_ids.is_empty() {
            return Ok(());
        }

        let vault_cipher = VaultCipher::from_env();
        // Map normalized_url -> credential. Python enforces a per-group unique
        // index on normalized_mcp_server_url and rejects cross-group URL conflicts
        // at write time, so a single deterministic key per normalized URL suffices
        // (no last-write-wins nondeterminism).
        let mut creds_by_url: HashMap<String, VaultCredentialRow> = HashMap::new();
        let creds = sqlx::query_as::<_, VaultCredentialRow>(
            r#"
            SELECT id, normalized_mcp_server_url,
                   COALESCE(data->>'token_value', '') AS token_value,
                   credential_type, oauth_config
            FROM joysafeter_credentials
            WHERE group_id = ANY($1)
              AND kind = 'mcp'
              AND archived_at IS NULL
              AND deleted_at IS NULL
            "#,
        )
        .bind(&group_ids)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| {
            anyhow::anyhow!("failed to load MCP credentials for session {session_id}: {e}")
        })?;
        for mut cred in creds {
            let Some(normalized_url) = cred.normalized_mcp_server_url.clone() else {
                continue;
            };
            vault_cipher.decrypt_row(&mut cred).map_err(|e| {
                anyhow::anyhow!(
                    "failed to decrypt vault credential {} for session {}: {e}",
                    cred.id,
                    session_id
                )
            })?;
            creds_by_url.insert(normalized_url, cred);
        }

        for mcp in mcp_servers {
            let normalized = mcp_url::normalize(&mcp.url);
            if let Some(cred) = creds_by_url.get_mut(&normalized) {
                // Trigger OAuth refresh so the DB token stays fresh; the actual
                // token is injected at the Envoy egress boundary (built separately
                // from the same DB rows), never written into the sandbox.
                if let Err(e) = self.maybe_refresh_oauth(cred, &vault_cipher).await {
                    warn!(credential_id = %cred.id, "OAuth refresh failed: {e}");
                }
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

    async fn maybe_refresh_oauth(
        &self,
        cred: &mut VaultCredentialRow,
        _cipher: &VaultCipher,
    ) -> anyhow::Result<String> {
        // Only OAuth-backed credentials are refreshable; static bearers resolve
        // their token as-is.
        if cred.credential_type != "oauth" && cred.credential_type != "mcp_oauth" {
            return Ok(cred.token_value.clone());
        }
        let Some(oauth) = cred.oauth_config.as_ref().and_then(|v| v.as_object()) else {
            return Ok(cred.token_value.clone());
        };

        let now = Utc::now().timestamp();
        let expires_at = oauth
            .get("expires_at")
            .and_then(|v| {
                v.as_i64()
                    .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
            })
            .unwrap_or(0);
        if expires_at != 0 && now < expires_at - 300 {
            return Ok(cred.token_value.clone());
        }

        // P2B: OAuth refresh not yet migrated. The unified `joysafeter_credentials`
        // schema stores the token inside the encrypted `data` JSONB and the
        // per-provider refresh flow (network call + write-back) is deferred to
        // P2B (design §3.14). Until then we resolve the token that is already
        // present in `data`/`oauth_config` and skip the network refresh + DB
        // write-back entirely (the old UPDATE targeted the dropped
        // `joysafeter_vault_credentials` table and is intentionally NOT retargeted
        // here). Static-bearer credentials are unaffected and keep working.
        Ok(cred.token_value.clone())
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

    /// Load session-scoped GitHub repository resources and decrypt their clone
    /// tokens. Repos live on the session
    /// (``joysafeter_session_repos``), not on ``agent.metadata``; the token is
    /// stored encrypted and decrypted here just before handing it to the runner.
    async fn load_session_repos(
        &self,
        session_id: SessionId,
        input: &mut HarnessInput,
    ) -> anyhow::Result<()> {
        let rows: Vec<SessionRepoRow> = sqlx::query_as(
            r#"
            SELECT url, branch, mount_path, mount_name, encrypted_token
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

        let cipher = VaultCipher::from_env();
        for (idx, row) in rows.into_iter().enumerate() {
            let has_token = !row.encrypted_token.is_empty();
            // Validate the token decrypts (so we fail fast / skip bad rows), but
            // never hand it to the sandbox. When a token exists, the clone URL is
            // rewritten to the Envoy egress boundary; Envoy injects the real
            // credential. Public repos (no token) keep their original URL.
            if has_token {
                cipher.decrypt_envelope(&row.encrypted_token).map_err(|e| {
                    anyhow::anyhow!(
                        "failed to decrypt clone token for repo resource '{}' on session {}: {e}",
                        row.mount_name,
                        session_id
                    )
                })?;
            }
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

    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;
    use sqlx::PgPool;

    use super::{
        ensure_skill_runtime_ready, extract_content_text, parse_semver, resolve_model_from_binding,
        session_container_work_dir, should_inject_conversation_history,
        trim_history_lines_to_budget, HarnessInput, HarnessInputBuilder, SkillForArchive,
    };
    use crate::ids::{
        AgentId, CredentialGroupId, CredentialId, EnvironmentId, FileId, SandboxId, SessionId,
        SessionResourceId, SkillSecurityScanId, TaskId,
    };
    use crate::kernel::llm_catalog::validate_runtime_secret;
    use uuid::Uuid;

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

    #[test]
    fn model_resolution_uses_catalog_profile_key_only() {
        let binding =
            validate_runtime_secret("native", "llm", Some("deepseek"), Some("chat_completions"))
                .expect("DeepSeek Chat Completions must be valid for Native");
        let mut input = HarnessInput {
            provider: "native".to_string(),
            secrets: HashMap::from([
                ("OPENAI_MODEL".to_string(), "deepseek-reasoner".to_string()),
                ("ANTHROPIC_MODEL".to_string(), "wrong-model".to_string()),
                ("MODEL".to_string(), "legacy-fallback".to_string()),
            ]),
            ..Default::default()
        };

        resolve_model_from_binding(&mut input, &binding);

        assert_eq!(input.model.as_deref(), Some("deepseek-reasoner"));
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

    fn ready_skill() -> SkillForArchive {
        SkillForArchive {
            name: "skill-a".to_string(),
            source_type: Some("manual".to_string()),
            lifecycle_status: "approved".to_string(),
            security_status: "passed".to_string(),
            security_scan_hash: Some("a".repeat(64)),
            security_scan_id: Some(SkillSecurityScanId::from_uuid(Uuid::nil())),
        }
    }

    #[test]
    fn skill_runtime_ready_accepts_approved_scanned_skill() {
        assert!(ensure_skill_runtime_ready(&ready_skill()).is_ok());
    }

    #[test]
    fn skill_runtime_ready_rejects_unapproved_or_unscanned_skill() {
        let mut skill = ready_skill();
        skill.lifecycle_status = "draft".to_string();
        assert!(ensure_skill_runtime_ready(&skill).is_err());

        let mut skill = ready_skill();
        skill.security_status = "blocked".to_string();
        assert!(ensure_skill_runtime_ready(&skill).is_err());

        let mut skill = ready_skill();
        skill.security_scan_hash = None;
        assert!(ensure_skill_runtime_ready(&skill).is_err());
    }

    #[tokio::test]
    async fn harness_input_uses_session_execution_snapshot_after_live_config_changes() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = format!("org-{unique}");
        let project_id = format!("proj-{unique}");
        let environment_ref = environment_id.to_string();
        let snapshot_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let live_credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let agent_name = format!("snapshot-agent-{unique}");
        let environment_name = format!("snapshot-env-{unique}");
        let snapshot = json!({
            "schema": "joysafeter.agent_execution_snapshot.v1",
            "id": agent_id.to_string(),
            "version": 7,
            "name": agent_name,
            "engine_kind": "claude",
            "model": {"id": "snapshot-model"},
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
                    "secret_refs": [],
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
                "secret_refs": [],
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
            .bind(json!({"ANTHROPIC_API_KEY": "snapshot-key"}))
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
            .bind(json!({"OPENAI_API_KEY": "live-key"}))
            .execute(&pool)
            .await
            .expect("insert live test credential");

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
                    id, agent_id, status, agent_version, agent_snapshot, environment_ref
                )
                VALUES ($1, $2, 'idle', 7, $3, $4)
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&snapshot)
            .bind(&environment_ref)
            .execute(&pool)
            .await
            .expect("insert snapshot session");

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
            let input = HarnessInputBuilder::new(pool.clone())
                .build(&task, "sandbox-ext", SandboxId::from_uuid(Uuid::now_v7()))
                .await
                .expect("build harness input");

            assert_eq!(input.provider, "claude");
            assert_eq!(input.model.as_deref(), Some("snapshot-model"));
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
            assert_eq!(
                input.secrets.get("ANTHROPIC_API_KEY").map(String::as_str),
                Some("snapshot-key")
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
            &[snapshot_credential_id, live_credential_id],
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
            let err = HarnessInputBuilder::new(pool.clone())
                .build(&task, "sandbox-ext", SandboxId::from_uuid(Uuid::now_v7()))
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
    async fn harness_input_resolves_session_credential_groups_for_mcp_egress() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
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
            .bind(json!({"token_value": "vault-token"}))
            .execute(&pool)
            .await
            .expect("insert mcp credential");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, '', '{}'::jsonb, $4,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
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
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert session");

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
            let input = HarnessInputBuilder::new(pool.clone())
                .build(&task, "sandbox-ext", SandboxId::from_uuid(Uuid::now_v7()))
                .await
                .expect("build harness input");

            assert_eq!(input.mcp_servers.len(), 1);
            assert_eq!(input.mcp_servers[0].name, "secure-mcp");
            assert_eq!(
                input.mcp_servers[0].url,
                format!(
                    "http://{}/mcp/secure-mcp/",
                    crate::sandbox::lds_backend::MCP_EGRESS_HOST
                )
            );
            assert!(input.mcp_servers[0].headers.is_empty());
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
    async fn harness_input_session_plaintext_credential_fails_build() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
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

            // Residual plaintext must fail the harness build rather than being
            // injected into the sandbox or egress boundary.
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
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, '', '{}'::jsonb, $4,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
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
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert session");

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
            let err = HarnessInputBuilder::new(pool.clone())
                .build(&task, "sandbox-ext", SandboxId::from_uuid(Uuid::now_v7()))
                .await
                .expect_err("broken vault credential must fail harness input build");
            let message = err.to_string();
            assert!(
                message.contains("failed to decrypt vault credential"),
                "{message}"
            );
            assert!(message.contains(&credential_id.to_string()), "{message}");
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

    #[test]
    fn resolve_model_uses_openai_profile_for_pi() {
        let binding =
            validate_runtime_secret("pi", "llm", Some("openai"), Some("chat_completions"))
                .expect("OpenAI Chat Completions must be valid for Pi");
        let mut input = HarnessInput {
            provider: "pi".to_string(),
            secrets: HashMap::from([
                ("OPENAI_MODEL".to_string(), "gpt-4.1".to_string()),
                ("ANTHROPIC_MODEL".to_string(), "wrong-model".to_string()),
            ]),
            ..Default::default()
        };
        resolve_model_from_binding(&mut input, &binding);
        assert_eq!(input.model.as_deref(), Some("gpt-4.1"));
    }

    #[test]
    fn resolve_model_uses_anthropic_profile_for_pi() {
        let binding =
            validate_runtime_secret("pi", "llm", Some("anthropic"), Some("anthropic_messages"))
                .expect("Anthropic Messages must be valid for Pi");
        let mut input = HarnessInput {
            provider: "pi".to_string(),
            secrets: HashMap::from([
                ("OPENAI_MODEL".to_string(), "wrong-model".to_string()),
                ("ANTHROPIC_MODEL".to_string(), "claude-opus-4.6".to_string()),
            ]),
            ..Default::default()
        };
        resolve_model_from_binding(&mut input, &binding);
        assert_eq!(input.model.as_deref(), Some("claude-opus-4.6"));
    }

    #[test]
    fn resolve_model_noop_when_already_set() {
        let binding =
            validate_runtime_secret("pi", "llm", Some("openai"), Some("openai_responses"))
                .expect("OpenAI Responses must be valid for Pi");
        let mut input = HarnessInput {
            provider: "pi".to_string(),
            model: Some("preset".to_string()),
            secrets: HashMap::from([("OPENAI_MODEL".to_string(), "gpt-4.1".to_string())]),
            ..Default::default()
        };
        resolve_model_from_binding(&mut input, &binding);
        assert_eq!(input.model.as_deref(), Some("preset"));
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

fn resolve_model_from_binding(input: &mut HarnessInput, binding: &RuntimeSecretBinding) {
    if input.model.is_some() || input.secrets.is_empty() {
        return;
    }

    if let Some(model_key) = binding.model_key.as_deref() {
        input.model = input.secrets.get(model_key).cloned();
    }
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

fn ensure_skill_runtime_ready(skill: &SkillForArchive) -> anyhow::Result<()> {
    if skill.lifecycle_status != "approved" {
        anyhow::bail!(
            "skill {} is not approved: {}",
            skill.name,
            skill.lifecycle_status
        );
    }
    // When security scanning is disabled, skip scan-related checks.
    // Mirrors the Python `settings.skill_security_scan_enabled` gate.
    let scan_enabled = std::env::var("SKILL_SECURITY_SCAN_ENABLED")
        .map(|v| !matches!(v.to_lowercase().as_str(), "false" | "0" | "no"))
        .unwrap_or(true);
    if !scan_enabled {
        return Ok(());
    }
    if !matches!(skill.security_status.as_str(), "passed" | "warning") {
        anyhow::bail!(
            "skill {} security status is not runtime-ready: {}",
            skill.name,
            skill.security_status
        );
    }
    if skill
        .security_scan_hash
        .as_deref()
        .unwrap_or_default()
        .is_empty()
    {
        anyhow::bail!("skill {} has no security scan hash", skill.name);
    }
    Ok(())
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

pub(crate) struct VaultCipher {
    key: Option<[u8; 32]>,
}

impl VaultCipher {
    pub(crate) fn validate_env_key() -> anyhow::Result<()> {
        let raw = std::env::var("JOYSAFETER_VAULT_ENCRYPTION_KEY").map_err(|_| {
            anyhow::anyhow!(
                "JOYSAFETER_VAULT_ENCRYPTION_KEY is required when AGENT_IDENTITY_PROVIDER=jd"
            )
        })?;
        parse_vault_key(&raw).ok_or_else(|| {
            anyhow::anyhow!("JOYSAFETER_VAULT_ENCRYPTION_KEY must encode a 32-byte key")
        })?;
        Ok(())
    }

    pub(crate) fn from_env() -> Self {
        // The vault key is process-constant, so parse it once and memoize.
        // `from_env()` is called on every credential-decrypt path (egress
        // builders, harness input, secret merge); re-reading the env var and
        // re-parsing the key each time is wasted work.
        static KEY: std::sync::OnceLock<Option<[u8; 32]>> = std::sync::OnceLock::new();
        let key = *KEY.get_or_init(|| {
            std::env::var("JOYSAFETER_VAULT_ENCRYPTION_KEY")
                .ok()
                .and_then(|raw| parse_vault_key(&raw))
        });
        Self { key }
    }

    fn decrypt_row(&self, cred: &mut VaultCredentialRow) -> anyhow::Result<()> {
        cred.token_value = self.decrypt_envelope(&cred.token_value)?;
        Ok(())
    }

    pub(crate) fn decrypt_envelope(&self, stored: &str) -> anyhow::Result<String> {
        if stored.is_empty() {
            return Ok(String::new());
        }
        let encoded = if let Some(encoded) = stored.strip_prefix("enc:v1:") {
            encoded
        } else if stored.starts_with("enc:v") && stored["enc:v".len()..].contains(':') {
            anyhow::bail!("unsupported credential envelope");
        } else if let Some(encoded) = stored.strip_prefix("enc:") {
            encoded
        } else {
            anyhow::bail!("stored credential is not encrypted");
        };
        let Some(key) = self.key else {
            anyhow::bail!("JOYSAFETER_VAULT_ENCRYPTION_KEY is required to decrypt managed secret");
        };
        let raw = base64::engine::general_purpose::STANDARD.decode(encoded)?;
        if raw.len() < 28 {
            anyhow::bail!("encrypted vault value is too short");
        }
        let (nonce_bytes, ciphertext) = raw.split_at(12);
        let cipher = Aes256Gcm::new_from_slice(&key)
            .map_err(|_| anyhow::anyhow!("invalid vault encryption key"))?;
        let plaintext = cipher
            .decrypt(Nonce::from_slice(nonce_bytes), ciphertext)
            .map_err(|_| anyhow::anyhow!("failed to decrypt vault credential"))?;
        Ok(String::from_utf8(plaintext)?)
    }

    #[cfg(test)]
    fn encrypt_or_passthrough(&self, plaintext: &str) -> anyhow::Result<String> {
        let Some(key) = self.key else {
            return Ok(plaintext.to_string());
        };
        let nonce_bytes: [u8; 12] = rand::random();
        let cipher = Aes256Gcm::new_from_slice(&key)
            .map_err(|_| anyhow::anyhow!("invalid vault encryption key"))?;
        let ciphertext = cipher
            .encrypt(Nonce::from_slice(&nonce_bytes), plaintext.as_bytes())
            .map_err(|_| anyhow::anyhow!("failed to encrypt vault credential"))?;
        let mut raw = nonce_bytes.to_vec();
        raw.extend_from_slice(&ciphertext);
        Ok(format!(
            "enc:v1:{}",
            base64::engine::general_purpose::STANDARD.encode(raw)
        ))
    }
}

#[cfg(test)]
impl VaultCipher {
    fn with_key(key: [u8; 32]) -> Self {
        Self { key: Some(key) }
    }
}

#[cfg(test)]
mod vault_cipher_tests {
    use super::{parse_vault_key, VaultCipher};
    use std::path::PathBuf;

    /// Loads the shared `cipher_vectors.json` produced by the Python cipher and
    /// proves Python-encrypt -> Rust-decrypt interop: every `enc:v1:` ciphertext
    /// must decrypt to its recorded plaintext under the fixed fixture key.
    #[test]
    fn decrypts_python_generated_v1_vectors() {
        // CARGO_MANIFEST_DIR = backend/app/joysafeter_orchestrator_rs;
        // fixture lives at backend/tests/fixtures/cipher_vectors.json.
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/cipher_vectors.json");
        let doc: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).expect("read cipher vectors"))
                .expect("parse cipher vectors");

        assert_eq!(doc["envelope"], "enc:v1:");
        let key = parse_vault_key(doc["key"].as_str().expect("key string")).expect("valid key");
        let cipher = VaultCipher::with_key(key);

        let vectors = doc["vectors"].as_array().expect("vectors array");
        assert!(!vectors.is_empty(), "expected cross-language vectors");
        for entry in vectors {
            let ciphertext = entry["ciphertext"].as_str().expect("ciphertext");
            let plaintext = entry["plaintext"].as_str().expect("plaintext");
            assert!(ciphertext.starts_with("enc:v1:"));
            let decrypted = cipher
                .decrypt_envelope(ciphertext)
                .expect("decrypt python vector");
            assert_eq!(decrypted, plaintext);
        }
    }

    #[test]
    fn bare_enc_prefix_is_read_as_v1() {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/cipher_vectors.json");
        let doc: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).expect("read cipher vectors"))
                .expect("parse cipher vectors");
        let key = parse_vault_key(doc["key"].as_str().unwrap()).unwrap();
        let cipher = VaultCipher::with_key(key);

        let v1 = doc["vectors"][0]["ciphertext"].as_str().unwrap();
        let bare = format!("enc:{}", v1.strip_prefix("enc:v1:").unwrap());
        let out = cipher
            .decrypt_envelope(&bare)
            .expect("decrypt legacy envelope");
        assert_eq!(out, doc["vectors"][0]["plaintext"].as_str().unwrap());
    }

    /// Rust round-trip stays on the v1 envelope.
    #[test]
    fn round_trip_uses_v1_envelope() {
        let cipher = VaultCipher::with_key([7u8; 32]);
        let stored = cipher
            .encrypt_or_passthrough("secret-value")
            .expect("encrypt");
        assert!(stored.starts_with("enc:v1:"));
        assert_eq!(
            cipher.decrypt_envelope(&stored).expect("decrypt"),
            "secret-value"
        );
    }

    #[test]
    fn empty_string_is_the_absent_credential_sentinel() {
        let cipher = VaultCipher::with_key([7u8; 32]);
        assert_eq!(cipher.decrypt_envelope("").expect("empty sentinel"), "");
    }

    #[test]
    fn plaintext_and_unknown_versions_fail_closed() {
        let cipher = VaultCipher::with_key([7u8; 32]);
        assert!(cipher.decrypt_envelope("plaintext-secret").is_err());
        assert!(cipher.decrypt_envelope("enc:v2:not-supported").is_err());
        assert!(cipher.decrypt_envelope("enc:v1:not-valid-base64").is_err());
    }
}

fn parse_vault_key(raw: &str) -> Option<[u8; 32]> {
    let bytes = hex::decode(raw)
        .or_else(|_| base64::engine::general_purpose::STANDARD.decode(raw))
        .ok()?;
    bytes.try_into().ok()
}

#[derive(Debug, FromRow)]
struct SecretRow {
    kind: String,
    provider: Option<String>,
    protocol: Option<String>,
    data: serde_json::Value,
}

#[derive(Debug, Clone, FromRow)]
struct VaultCredentialRow {
    id: CredentialId,
    normalized_mcp_server_url: Option<String>,
    /// Static-bearer token, sourced from the encrypted `data->>'token_value'`
    /// JSONB field (see the SELECT that populates this row). Empty when the
    /// credential carries no static bearer (e.g. OAuth-only, deferred to P2B).
    token_value: String,
    credential_type: String,
    oauth_config: Option<serde_json::Value>,
}

#[derive(Debug, FromRow)]
struct SkillForArchive {
    name: String,
    source_type: Option<String>,
    lifecycle_status: String,
    security_status: String,
    security_scan_hash: Option<String>,
    security_scan_id: Option<SkillSecurityScanId>,
}

#[derive(Debug, FromRow)]
struct SkillVersionForArchive {
    id: SkillVersionId,
    security_scan_id: Option<SkillSecurityScanId>,
    target_hash: Option<String>,
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
struct EnvironmentRow {
    config: serde_json::Value,
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
