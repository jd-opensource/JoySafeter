use std::collections::HashMap;
use std::path::{Component, Path};

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::Engine as _;
use chrono::Utc;
use flate2::write::GzEncoder;
use flate2::Compression;
use sqlx::{FromRow, PgPool};
use tar::{Builder, Header};
use tracing::{debug, warn};
use uuid::Uuid;

use crate::db::queries;
use crate::grpc::proto;

const CONVERSATION_HISTORY_EVENT_LIMIT: i64 = 100;
const CONVERSATION_HISTORY_MAX_CHARS: usize = 24_000;

/// Constructs gRPC SetupSandbox and StartTask messages from task/agent/session data.
///
/// This mirrors Python `build_harness_input`: agent model/env/secret_ref, vault MCP
/// credentials, memory stores, packed skills/agents/commands, session file resources,
/// conversation history, custom tools, and permission mode all flow through one builder.
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
}

impl HarnessInputBuilder {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn build(
        &self,
        task: &crate::db::models::JoySafeterTask,
        sandbox_external_id: &str,
        _sandbox_db_id: Uuid,
    ) -> anyhow::Result<HarnessInput> {
        let agent = match task.agent_id {
            Some(aid) => queries::get_agent(&self.pool, aid).await?,
            None => None,
        };
        let session = match task.session_id {
            Some(sid) => queries::get_session(&self.pool, sid).await?,
            None => None,
        };

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
            input.mcp_servers = parse_mcp_configs(agent.mcp_configs.as_ref());
            input.custom_tools = parse_custom_tools(agent.tools.as_ref());
            let (allowed, ask) = parse_tool_permission_rules(agent.tools.as_ref());
            input.allowed_tools = allowed;
            input.ask_tools = ask;
            input.permission_mode = agent
                .permission_mode
                .clone()
                .or_else(|| Some(derive_permission_mode_from_tools(agent.tools.as_ref())));
            input.setup_commands = self.resolve_environment_setup_commands(agent).await;
            input
                .setup_commands
                .extend(extract_setup_commands(agent.metadata.as_ref()));

            self.resolve_environment_env(agent, &mut input).await?;
            self.resolve_agent_secret(agent, &mut input).await?;
            apply_provider_aliases(&mut input.secrets);
            resolve_model_from_secrets(&mut input);
            input
                .env
                .extend(json_object_to_string_map(agent.env.as_ref()));
            self.resolve_skill_archives(agent, &mut input).await;
        }

        if let Some(ref session) = session {
            if let Some(ref vault_ids) = session.vault_ids {
                self.resolve_vault_credentials(vault_ids, &mut input.mcp_servers)
                    .await;
            }
            self.load_memory_stores(session.id, &mut input).await;
            self.load_session_files(session.id, &mut input).await;
            self.load_session_repos(session.id, &mut input).await;
            input.work_dir = session_container_work_dir(session.last_work_dir.as_deref());
        }

        let base_system = task
            .system_prompt
            .clone()
            .or_else(|| agent.as_ref().and_then(|a| a.system_prompt.clone()));
        input.system_prompt =
            combine_system_prompt(base_system, input.memory_system_prompt.clone());

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
            task_id: task.id.to_string(),
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
        }
    }

    async fn resolve_environment_setup_commands(
        &self,
        agent: &crate::db::models::JoySafeterAgent,
    ) -> Vec<String> {
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
        if let Some(env_id) = parse_prefixed_uuid(env_ref, "env_") {
            return sqlx::query_as::<_, EnvironmentRow>(
                r#"
                SELECT config, image_tag FROM joysafeter_environments
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
            SELECT config, image_tag FROM joysafeter_environments
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
    ) -> anyhow::Result<()> {
        let secret_ref = match agent.secret_ref.as_deref().filter(|v| !v.trim().is_empty()) {
            Some(v) => v,
            None => return Ok(()),
        };

        self.resolve_secret_ref_into_input(secret_ref, agent.project_id.as_deref(), input, true)
            .await?;
        Ok(())
    }

    async fn resolve_environment_env(
        &self,
        agent: &crate::db::models::JoySafeterAgent,
        input: &mut HarnessInput,
    ) -> anyhow::Result<()> {
        let Some(env_ref) = agent
            .environment_ref
            .as_deref()
            .filter(|v| !v.trim().is_empty())
        else {
            return Ok(());
        };

        let Some(environment) = self
            .load_environment(env_ref, agent.project_id.as_deref())
            .await?
        else {
            return Ok(());
        };

        input.env.extend(json_object_to_string_map(
            environment.config.get("env_vars"),
        ));

        if let Some(secret_refs) = environment
            .config
            .get("secret_refs")
            .and_then(|v| v.as_array())
        {
            for secret_ref in secret_refs.iter().filter_map(|v| v.as_str()) {
                self.resolve_secret_ref_into_input(
                    secret_ref,
                    agent.project_id.as_deref(),
                    input,
                    false,
                )
                .await?;
            }
        }

        Ok(())
    }

    async fn resolve_secret_ref_into_input(
        &self,
        secret_ref: &str,
        project_id: Option<&str>,
        input: &mut HarnessInput,
        override_existing: bool,
    ) -> anyhow::Result<()> {
        let secret = sqlx::query_as::<_, SecretRow>(
            r#"
            SELECT data FROM joysafeter_secrets
            WHERE name = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            ORDER BY created_at DESC
            LIMIT 1
            "#,
        )
        .bind(secret_ref)
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await?;

        if let Some(secret) = secret {
            let cipher = VaultCipher::from_env();
            for (key, value) in json_object_to_string_map(Some(&secret.data)) {
                if override_existing || !input.secrets.contains_key(&key) {
                    input
                        .secrets
                        .insert(key, cipher.decrypt_or_passthrough(&value)?);
                }
            }
        }

        Ok(())
    }

    async fn resolve_skill_archives(
        &self,
        agent: &crate::db::models::JoySafeterAgent,
        input: &mut HarnessInput,
    ) {
        for (target, items) in [
            ("skills", agent.skills.as_ref()),
            ("agents", agent.agents.as_ref()),
            ("commands", agent.commands.as_ref()),
        ] {
            let Some(arr) = items.and_then(|v| v.as_array()) else {
                continue;
            };
            for item in arr {
                if let Some(archive) = self.resolve_skill_item(target, item).await {
                    input.skills.push(archive);
                }
            }
        }
    }

    async fn resolve_skill_item(
        &self,
        target: &str,
        item: &serde_json::Value,
    ) -> Option<proto::SkillArchive> {
        if let Some(encoded) = item.get("tar_gz_b64").and_then(|v| v.as_str()) {
            match base64::engine::general_purpose::STANDARD.decode(encoded) {
                Ok(data) => {
                    return Some(proto::SkillArchive {
                        name: item
                            .get("name")
                            .and_then(|v| v.as_str())
                            .unwrap_or("unknown")
                            .to_string(),
                        tar_gz: data,
                        target: target.to_string(),
                    });
                }
                Err(e) => {
                    warn!(target, "Failed to decode packed skill archive: {e}");
                    return None;
                }
            }
        }

        let skill_id = item.get("skill_id").and_then(|v| v.as_str())?;
        let version = item
            .get("version")
            .and_then(|v| v.as_str())
            .unwrap_or("latest");
        let skill_uuid = parse_prefixed_uuid(skill_id, "skill_")?;
        self.pack_skill(skill_uuid, version, target).await
    }

    async fn pack_skill(
        &self,
        skill_id: Uuid,
        version: &str,
        target: &str,
    ) -> Option<proto::SkillArchive> {
        let skill_name = self
            .skill_name(skill_id)
            .await
            .unwrap_or_else(|| "unknown".to_string());
        // Version keyword semantics (mirrors the Python skill_packer):
        //  - "draft"            → the mutable working copy (skill_files)
        //  - "latest"/empty     → the highest published version; falls back to
        //                         draft only when nothing has been published yet
        //  - explicit "x.y.z"   → that exact published version
        let files = if version == "draft" {
            self.load_skill_files(skill_id).await
        } else if version == "latest" || version.is_empty() {
            match self.highest_published_version(skill_id).await {
                Some(v) => self.load_skill_version_files(skill_id, &v).await,
                None => self.load_skill_files(skill_id).await,
            }
        } else {
            self.load_skill_version_files(skill_id, version).await
        };

        let files = match files {
            Ok(files) if !files.is_empty() => files,
            Ok(_) => {
                warn!(skill_id = %skill_id, version, "Skill has no files");
                return None;
            }
            Err(e) => {
                warn!(skill_id = %skill_id, version, "Failed to load skill files: {e}");
                return None;
            }
        };

        match create_targz(&skill_name, &files) {
            Ok(data) => Some(proto::SkillArchive {
                name: skill_name,
                tar_gz: data,
                target: target.to_string(),
            }),
            Err(e) => {
                warn!(skill_id = %skill_id, "Failed to create skill archive: {e}");
                None
            }
        }
    }

    async fn skill_name(&self, skill_id: Uuid) -> Option<String> {
        sqlx::query_scalar::<_, String>("SELECT name FROM joysafeter_skills WHERE id = $1")
            .bind(skill_id)
            .fetch_optional(&self.pool)
            .await
            .ok()
            .flatten()
    }

    /// Return the highest published version string for a skill, or None if it
    /// has never been published. Versions are MAJOR.MINOR.PATCH (the publish
    /// API rejects prerelease/build), so a numeric tuple sort is exact.
    async fn highest_published_version(&self, skill_id: Uuid) -> Option<String> {
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

    async fn load_skill_files(&self, skill_id: Uuid) -> anyhow::Result<Vec<SkillFileForArchive>> {
        sqlx::query_as::<_, SkillFileForArchive>(
            r#"
            SELECT path, file_name, content
            FROM joysafeter_skill_files
            WHERE skill_id = $1
            ORDER BY path, file_name
            "#,
        )
        .bind(skill_id)
        .fetch_all(&self.pool)
        .await
        .map_err(Into::into)
    }

    async fn load_skill_version_files(
        &self,
        skill_id: Uuid,
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
        vault_ids: &serde_json::Value,
        mcp_servers: &mut Vec<proto::McpConfig>,
    ) {
        let ids: Vec<Uuid> = match vault_ids.as_array() {
            Some(arr) => arr
                .iter()
                .filter_map(|v| v.as_str())
                .filter_map(|s| parse_prefixed_uuid(s, "vault_"))
                .collect(),
            None => return,
        };

        let vault_cipher = VaultCipher::from_env();
        let mut creds_by_url: HashMap<String, VaultCredentialRow> = HashMap::new();
        for vault_id in ids {
            match sqlx::query_as::<_, VaultCredentialRow>(
                r#"
                SELECT id, mcp_server_url, token_value, credential_type, oauth_config
                FROM joysafeter_vault_credentials
                WHERE vault_id = $1
                "#,
            )
            .bind(vault_id)
            .fetch_all(&self.pool)
            .await
            {
                Ok(creds) => {
                    for mut cred in creds {
                        let url_val = cred.mcp_server_url.clone();
                        if let Some(url) = url_val {
                            if let Err(e) = vault_cipher.decrypt_row(&mut cred) {
                                warn!(credential_id = %cred.id, "Failed to decrypt vault credential: {e}");
                            }
                            creds_by_url.insert(url, cred);
                        }
                    }
                }
                Err(e) => warn!(vault_id = %vault_id, "Failed to load vault credentials: {e}"),
            }
        }

        for mcp in mcp_servers {
            if let Some(cred) = creds_by_url.get_mut(&mcp.url) {
                // Trigger OAuth refresh so the DB token stays fresh; the actual
                // token is injected at the Envoy egress boundary (built separately
                // from the same DB rows), never written into the sandbox.
                if let Err(e) = self.maybe_refresh_oauth(cred, &vault_cipher).await {
                    warn!(credential_id = %cred.id, "OAuth refresh failed: {e}");
                }
                // Repoint the sandbox's MCP client at the placeholder egress host
                // over plaintext http:// — the sandbox never learns the real MCP
                // address. Envoy matches `/mcp/<name>/`, injects the real token,
                // rewrites host+path to the true upstream, and forwards.
                mcp.url = format!(
                    "http://{}/mcp/{}/",
                    crate::sandbox::lds_backend::MCP_EGRESS_HOST,
                    mcp.name
                );
                mcp.headers.clear();
            }
        }
    }

    async fn maybe_refresh_oauth(
        &self,
        cred: &mut VaultCredentialRow,
        cipher: &VaultCipher,
    ) -> anyhow::Result<String> {
        if cred.credential_type != "oauth" {
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

        let Some(refresh_token) = oauth.get("refresh_token").and_then(|v| v.as_str()) else {
            return Ok(cred.token_value.clone());
        };
        let Some(token_url) = oauth.get("token_url").and_then(|v| v.as_str()) else {
            return Ok(cred.token_value.clone());
        };
        let Some(client_id) = oauth.get("client_id").and_then(|v| v.as_str()) else {
            return Ok(cred.token_value.clone());
        };
        let client_secret = oauth
            .get("client_secret")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .build()?;
        let response = client
            .post(token_url)
            .form(&[
                ("grant_type", "refresh_token"),
                ("refresh_token", refresh_token),
                ("client_id", client_id),
                ("client_secret", client_secret),
            ])
            .send()
            .await?;
        if !response.status().is_success() {
            return Ok(cred.token_value.clone());
        }

        let data: serde_json::Value = response.json().await?;
        let Some(new_token) = data.get("access_token").and_then(|v| v.as_str()) else {
            return Ok(cred.token_value.clone());
        };
        let new_refresh = data
            .get("refresh_token")
            .and_then(|v| v.as_str())
            .unwrap_or(refresh_token);
        let expires_in = data
            .get("expires_in")
            .and_then(|v| v.as_i64())
            .unwrap_or(3600);
        let new_expires = now + expires_in;
        let mut new_oauth = cred
            .oauth_config
            .clone()
            .unwrap_or_else(|| serde_json::json!({}));
        if let Some(obj) = new_oauth.as_object_mut() {
            obj.insert(
                "refresh_token".to_string(),
                serde_json::Value::String(new_refresh.to_string()),
            );
            obj.insert(
                "expires_at".to_string(),
                serde_json::Value::Number(new_expires.into()),
            );
        }
        let stored_token = cipher.encrypt_or_passthrough(new_token)?;
        sqlx::query(
            r#"
            UPDATE joysafeter_vault_credentials
            SET token_value = $2, oauth_config = $3, updated_at = NOW()
            WHERE id = $1
            "#,
        )
        .bind(cred.id)
        .bind(&stored_token)
        .bind(&new_oauth)
        .execute(&self.pool)
        .await?;

        cred.token_value = new_token.to_string();
        cred.oauth_config = Some(new_oauth);
        Ok(cred.token_value.clone())
    }

    async fn load_memory_stores(&self, session_id: Uuid, input: &mut HarnessInput) {
        let stores = match queries::list_session_memory_stores(&self.pool, session_id).await {
            Ok(stores) => stores,
            Err(e) => {
                warn!(session_id = %session_id, "Failed to load memory stores: {e}");
                return;
            }
        };

        let mut prompt_parts = vec![
            "# Memory".to_string(),
            "The following memory stores are mounted. Use them to persist and retrieve information across sessions.".to_string(),
            String::new(),
        ];

        for store in stores {
            let mount_path = format!("/mnt/memory/{}", store.mount_name);
            let mut files = vec![];
            if let Ok(rows) = queries::load_memory_files(&self.pool, store.store_id, 10000).await {
                for row in rows {
                    files.push(proto::MemoryFile {
                        relative_path: row.path,
                        content: row.content.unwrap_or_default().into_bytes(),
                    });
                }
            }

            input.memory_mounts.push(proto::MemoryStoreMount {
                store_id: format!("memstore_{}", store.store_id),
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
            return;
        }
        input.memory_system_prompt = Some(prompt_parts.join("\n"));
    }

    async fn load_session_files(&self, session_id: Uuid, input: &mut HarnessInput) {
        let rows: Vec<SessionFileRow> = match sqlx::query_as(
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
        {
            Ok(rows) => rows,
            Err(e) => {
                warn!(session_id = %session_id, "Failed to load session files: {e}");
                return;
            }
        };

        for row in rows {
            match load_session_file_resource(&row).await {
                Ok(content) => input.files.push(proto::FileMount {
                    path: row.mount_path,
                    content,
                    filename: row.filename,
                }),
                Err(e) => {
                    warn!(storage_key = %row.storage_key, "Failed to prepare session file: {e}")
                }
            }
        }
    }

    /// Load session-scoped GitHub repository resources and decrypt their clone
    /// tokens. Mirrors the Python orchestrator: repos live on the session
    /// (``joysafeter_session_repos``), not on ``agent.metadata``; the token is
    /// stored encrypted and decrypted here just before handing it to the runner.
    async fn load_session_repos(&self, session_id: Uuid, input: &mut HarnessInput) {
        let rows: Vec<SessionRepoRow> = match sqlx::query_as(
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
        {
            Ok(rows) => rows,
            Err(e) => {
                warn!(session_id = %session_id, "Failed to load session repos: {e}");
                return;
            }
        };

        if rows.is_empty() {
            return;
        }

        let cipher = VaultCipher::from_env();
        for (idx, row) in rows.into_iter().enumerate() {
            let has_token = !row.encrypted_token.is_empty();
            // Validate the token decrypts (so we fail fast / skip bad rows), but
            // never hand it to the sandbox. When a token exists, the clone URL is
            // rewritten to the Envoy egress boundary; Envoy injects the real
            // credential. Public repos (no token) keep their original URL.
            if has_token {
                if let Err(e) = cipher.decrypt_or_passthrough(&row.encrypted_token) {
                    warn!(
                        session_id = %session_id,
                        "Failed to decrypt clone token for repo resource: {e}"
                    );
                    continue;
                }
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
    }

    async fn build_conversation_history(&self, session_id: Uuid, task_id: Uuid) -> String {
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
    matches!(provider, "claude" | "codex" | "native") && !has_harness_resume
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
    use super::{
        extract_content_text, parse_semver, session_container_work_dir,
        should_inject_conversation_history, trim_history_lines_to_budget,
    };

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

fn apply_provider_aliases(env: &mut HashMap<String, String>) {
    if env.contains_key("ANTHROPIC_AUTH_TOKEN") && !env.contains_key("ANTHROPIC_API_KEY") {
        if let Some(token) = env.get("ANTHROPIC_AUTH_TOKEN").cloned() {
            env.insert("ANTHROPIC_API_KEY".to_string(), token);
        }
    }
}

fn resolve_model_from_secrets(input: &mut HarnessInput) {
    if input.model.is_some() || input.secrets.is_empty() {
        return;
    }

    input.model = if input.provider == "codex" {
        input.secrets.get("OPENAI_MODEL").cloned()
    } else {
        input
            .secrets
            .get("ANTHROPIC_MODEL")
            .or_else(|| input.secrets.get("MODEL"))
            .cloned()
    };
}

fn parse_mcp_configs(value: Option<&serde_json::Value>) -> Vec<proto::McpConfig> {
    value
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .map(|item| proto::McpConfig {
                    name: item["name"].as_str().unwrap_or("").to_string(),
                    command: item["command"].as_str().unwrap_or("").to_string(),
                    args: item["args"]
                        .as_array()
                        .map(|a| {
                            a.iter()
                                .filter_map(|v| v.as_str().map(String::from))
                                .collect()
                        })
                        .unwrap_or_default(),
                    env: json_object_to_string_map(item.get("env")),
                    // mcp_configs store transport under "type" (schema McpServerConfig);
                    // accept legacy "server_type"/"transport" too. The sandbox runner
                    // ultimately keys off url-present to pick http vs stdio, but pass the
                    // declared type through so sse can be distinguished from http.
                    server_type: item["type"]
                        .as_str()
                        .or_else(|| item["server_type"].as_str())
                        .or_else(|| item["transport"].as_str())
                        .unwrap_or("stdio")
                        .to_string(),
                    url: item["url"].as_str().unwrap_or("").to_string(),
                    headers: json_object_to_string_map(item.get("headers")),
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

fn parse_prefixed_uuid(raw: &str, prefix: &str) -> Option<Uuid> {
    raw.strip_prefix(prefix).unwrap_or(raw).parse().ok()
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
    pub(crate) fn from_env() -> Self {
        let key = std::env::var("JOYSAFETER_VAULT_ENCRYPTION_KEY")
            .ok()
            .and_then(|raw| parse_vault_key(&raw));
        Self { key }
    }

    fn decrypt_row(&self, cred: &mut VaultCredentialRow) -> anyhow::Result<()> {
        cred.token_value = self.decrypt_or_passthrough(&cred.token_value)?;
        Ok(())
    }

    pub(crate) fn decrypt_or_passthrough(&self, stored: &str) -> anyhow::Result<String> {
        let Some(encoded) = stored.strip_prefix("enc:") else {
            return Ok(stored.to_string());
        };
        let Some(key) = self.key else {
            anyhow::bail!("JOYSAFETER_VAULT_ENCRYPTION_KEY is required to decrypt managed secret");
        };
        let raw = base64::engine::general_purpose::STANDARD.decode(encoded)?;
        if raw.len() < 12 {
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
            "enc:{}",
            base64::engine::general_purpose::STANDARD.encode(raw)
        ))
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
    data: serde_json::Value,
}

#[derive(Debug, FromRow)]
struct VaultCredentialRow {
    id: Uuid,
    mcp_server_url: Option<String>,
    token_value: String,
    credential_type: String,
    oauth_config: Option<serde_json::Value>,
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
    image_tag: Option<String>,
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

    if let Some(ref mcp_val) = agent.mcp_configs {
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
