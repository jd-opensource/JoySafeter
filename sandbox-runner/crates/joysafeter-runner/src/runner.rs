#[cfg(target_os = "linux")]
use crate::memory_fuse::MemoryFuseHandle;
use crate::proto::{self, RunnerHarnessResult, RunnerMessage};
use crate::stream::harness_event_to_proto;

use joysafeter_runtime::AdapterRegistry;
use joysafeter_types::harness::HarnessInput;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, oneshot};
use tracing::{debug, error, info, warn};

#[derive(Clone, Default)]
pub struct SessionConfig {
    pub env: HashMap<String, String>,
    pub secrets: HashMap<String, String>,
    pub permission_mode: String,
    pub provider: String,
    pub model: Option<String>,
    pub work_dir: Option<PathBuf>,
    pub memory_system_prompt: Option<String>,
    #[cfg(target_os = "linux")]
    pub memory_fuse_handle: Option<Arc<MemoryFuseHandle>>,
    /// mount_name → mount_path, for cross-session memory updates (Docker bind mount mode)
    pub memory_mount_paths: HashMap<String, PathBuf>,
}

pub struct TaskMetadata {
    pub work_dir: String,
    pub session_id: Option<String>,
}

pub enum RunnerControl {
    SendInput(String),
}

const LIVE_INPUT_PREFIX: &str = "__joysafeter_input_v1__:";

fn structured_control_input_key(content: &str) -> Option<String> {
    let live_raw = content.strip_prefix(LIVE_INPUT_PREFIX)?;
    let value: serde_json::Value = serde_json::from_str(live_raw).ok()?;
    if let Some(source_event_id) = value.get("source_event_id").and_then(|v| v.as_str()) {
        return Some(format!("source_event_id:{source_event_id}"));
    }
    let ty = value.get("type").and_then(|v| v.as_str())?;
    match ty {
        "tool_confirmation" => {
            let call_id = value.get("tool_use_call_id").and_then(|v| v.as_str())?;
            let approved = value.get("approved").and_then(|v| v.as_bool())?;
            Some(format!("tool_confirmation:{call_id}:{approved}"))
        }
        "custom_tool_result" => {
            let call_id = value.get("tool_use_call_id").and_then(|v| v.as_str())?;
            let content = value.get("content").and_then(|v| v.as_str())?;
            Some(format!("custom_tool_result:{call_id}:{content}"))
        }
        "interrupt" => Some("interrupt".to_string()),
        _ => Some(content.to_string()),
    }
}

fn should_forward_control_input(seen: &mut HashSet<String>, content: &str) -> bool {
    let Some(key) = structured_control_input_key(content) else {
        return true;
    };
    seen.insert(key)
}

pub async fn handle_task(
    task: proto::StartTask,
    session_config: &SessionConfig,
    adapters: Arc<AdapterRegistry>,
    runner_tx: mpsc::Sender<RunnerMessage>,
    mut cancel_rx: oneshot::Receiver<()>,
    mut control_rx: mpsc::Receiver<RunnerControl>,
) -> Result<TaskMetadata, Box<dyn std::error::Error + Send + Sync>> {
    let provider = if session_config.provider.is_empty() {
        &task.provider
    } else {
        &session_config.provider
    };
    let adapter = adapters
        .get(provider)
        .ok_or_else(|| format!("No adapter for provider: {}", provider))?;

    let work_dir = session_config
        .work_dir
        .clone()
        .or_else(|| task.work_dir.as_deref().map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from("/workspace"));

    if !work_dir.exists() {
        tokio::fs::create_dir_all(&work_dir).await?;
    }

    // SetupSandbox is the normal path for skills, but pooled/reconnected
    // sandboxes can miss setup if the session link is established late.  StartTask
    // also carries skills, so unpack them here as an idempotent fallback before
    // the Claude process starts.
    unpack_skills(&work_dir, &task.skills, provider)
        .await
        .map_err(|e| format!("unpack task skills to {}: {e}", work_dir.display()))?;

    run_setup_commands(&work_dir, &task.setup_commands, "StartTask").await?;

    // Clone configured repos (idempotent fallback for pooled/reconnected sandboxes
    // that may have missed SetupSandbox).
    crate::repos::clone_repos(&work_dir, &task.repos)
        .await
        .map_err(|e| format!("clone task repos to {}: {e}", work_dir.display()))?;

    // Write MCP servers and custom tools to .claude/settings.json (Claude Code only)
    write_settings_json(
        &work_dir,
        provider,
        &task.mcp_servers,
        &task.custom_tools,
        &task.allowed_tools,
        &task.ask_tools,
    )
    .await?;

    let mut env = if session_config.env.is_empty() {
        task.env.clone()
    } else {
        session_config.env.clone()
    };
    merge_process_proxy_env(&mut env);
    let secrets = if session_config.secrets.is_empty() {
        task.secrets.clone()
    } else {
        session_config.secrets.clone()
    };
    let model = session_config.model.clone().or(task.model.clone());
    let permission_mode = if session_config.permission_mode.is_empty() {
        task.permission_mode
            .clone()
            .unwrap_or_else(|| "bypassPermissions".into())
    } else {
        session_config.permission_mode.clone()
    };

    let input = HarnessInput {
        prompt: task.prompt.clone(),
        system_prompt: match (&session_config.memory_system_prompt, &task.system_prompt) {
            (Some(mem_prompt), Some(sys_prompt)) => Some(format!("{mem_prompt}\n\n{sys_prompt}")),
            (Some(mem_prompt), None) => Some(mem_prompt.clone()),
            (None, sp) => sp.clone(),
        },
        system_prompt_mode: task
            .system_prompt_mode
            .clone()
            .unwrap_or_else(|| "append".to_string()),
        session_id: task.session_id.clone(),
        model,
        max_turns: task.max_turns,
        timeout: Duration::from_secs(task.timeout_seconds),
        env,
        secrets,
        // Forward MCP servers from the orchestrator-built proto into the
        // engine adapter. Adapters that target HTTP MCP (e.g. codex) write
        // these into their CLI's config; adapters that already write their
        // own config via task.mcp_servers (claude) simply ignore this.
        mcp_configs: task
            .mcp_servers
            .iter()
            .filter(|s| !s.url.is_empty())
            .map(|s| joysafeter_types::agent::McpServerConfig::Url {
                name: s.name.clone(),
                url: s.url.clone(),
            })
            .collect(),
        permission_mode,
        allowed_tools: task.allowed_tools.clone(),
        ask_tools: task.ask_tools.clone(),
    };

    info!(provider = %provider, "Dispatching task to agent CLI...");
    let mut harness = adapter.start(input, &work_dir).await?;

    let mut seq = 0u64;
    let mut cancelled = false;
    let mut seen_control_inputs: HashSet<String> = HashSet::new();
    // Track ToolUse call_ids that write to /mnt/memory/ (Docker path only; FUSE handles this natively)
    #[cfg(target_os = "linux")]
    let use_tool_interception = session_config.memory_fuse_handle.is_none();
    #[cfg(not(target_os = "linux"))]
    let use_tool_interception = true;
    let mut memory_write_calls: HashMap<String, String> = HashMap::new();

    loop {
        tokio::select! {
            event = harness.events.recv() => {
                match event {
                    Some(ref event) => {
                        // Track tool writes to /mnt/memory/ paths (Docker bind-mount path only)
                        if use_tool_interception {
                            match event {
                                joysafeter_types::harness::HarnessEvent::ToolUse { tool, call_id, input, .. } => {
                                    if tool == "Write" || tool == "Edit" {
                                        if let Some(path) = input.get("file_path").and_then(|v| v.as_str()) {
                                            if path.starts_with("/mnt/memory/") {
                                                memory_write_calls.insert(call_id.clone(), path.to_string());
                                            }
                                        }
                                    }
                                }
                                joysafeter_types::harness::HarnessEvent::ToolResult { call_id, output, .. } => {
                                    if let Some(path) = memory_write_calls.remove(call_id) {
                                        if !output.contains("error") && !output.contains("Error") {
                                            let mem_path = &path["/mnt/memory/".len()..];
                                            if let Some(slash) = mem_path.find('/') {
                                                let mount_name = &mem_path[..slash];
                                                let rel_path = &mem_path[slash..];
                                                match tokio::fs::read_to_string(&path).await {
                                                    Ok(content) => {
                                                        let sync_msg = RunnerMessage {
                                                            payload: Some(proto::runner_message::Payload::MemorySync(
                                                                proto::MemoryFileSync {
                                                                    store_mount_name: mount_name.to_string(),
                                                                    relative_path: rel_path.to_string(),
                                                                    content,
                                                                    operation: "write".to_string(),
                                                                }
                                                            )),
                                                        };
                                                        if runner_tx.send(sync_msg).await.is_err() {
                                                            warn!("Failed to send MemoryFileSync, orchestrator disconnected");
                                                        }
                                                    }
                                                    Err(e) => {
                                                        warn!(error = %e, path = %path, "Failed to read memory file for sync");
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                _ => {}
                            }
                        }

                        seq += 1;
                        let proto_event = harness_event_to_proto(seq, event);
                        let msg = RunnerMessage {
                            payload: Some(proto::runner_message::Payload::Event(proto_event)),
                        };
                        if runner_tx.send(msg).await.is_err() {
                            warn!("Failed to send event to orchestrator, continuing task");
                        }
                    }
                    None => break,
                }
            }
            _ = &mut cancel_rx => {
                warn!("Cancel signal received, aborting agent");
                cancelled = true;
                if let Err(e) = adapter.cancel(&mut harness).await {
                    error!(error = %e, "adapter.cancel() failed");
                }
                break;
            }
            maybe_ctrl = control_rx.recv() => {
                match maybe_ctrl {
                    Some(RunnerControl::SendInput(content)) => {
                        if !should_forward_control_input(&mut seen_control_inputs, &content) {
                            warn!("duplicate structured control input dropped");
                            continue;
                        }
                        if let Err(e) = adapter.send_input(&mut harness, content).await {
                            warn!(error = %e, "send_input failed");
                        }
                    }
                    None => {}
                }
            }
        }
    }

    if let Some(ref mut child) = harness.child {
        let _ = child.start_kill();
    }

    let work_dir_str = work_dir.to_string_lossy().to_string();

    if cancelled {
        let proto_result = RunnerHarnessResult {
            status: "aborted".into(),
            output: String::new(),
            error: Some("Task cancelled".into()),
            session_id: task.session_id.clone(),
            usage: Some(proto::TokenUsage {
                input_tokens: 0,
                output_tokens: 0,
                cache_read_tokens: 0,
                cache_write_tokens: 0,
                by_model: vec![],
            }),
            duration_ms: 0,
            work_dir: Some(work_dir_str.clone()),
        };

        let msg = RunnerMessage {
            payload: Some(proto::runner_message::Payload::Result(proto_result)),
        };
        runner_tx.send(msg).await.ok();

        return Ok(TaskMetadata {
            work_dir: work_dir_str,
            session_id: task.session_id,
        });
    }

    let result =
        harness
            .result
            .await
            .unwrap_or_else(|_| joysafeter_types::harness::HarnessResult {
                status: joysafeter_types::harness::HarnessResultStatus::Failed,
                output: String::new(),
                error: Some("Failed to receive result".into()),
                session_id: None,
                usage: Default::default(),
                duration: Duration::ZERO,
            });

    info!(status = %result.status, "Task completed");

    let result_session_id = result.session_id.clone();

    let proto_result = RunnerHarnessResult {
        status: result.status.to_string(),
        output: result.output,
        error: result.error,
        session_id: result.session_id,
        usage: Some(proto::TokenUsage {
            input_tokens: result.usage.input_tokens,
            output_tokens: result.usage.output_tokens,
            cache_read_tokens: result.usage.cache_read_tokens,
            cache_write_tokens: result.usage.cache_write_tokens,
            by_model: result
                .usage
                .by_model
                .iter()
                .map(|(model, mu)| proto::ModelUsageEntry {
                    model: model.clone(),
                    input_tokens: mu.input_tokens,
                    output_tokens: mu.output_tokens,
                    cache_read_tokens: mu.cache_read_tokens,
                    cache_write_tokens: mu.cache_write_tokens,
                })
                .collect(),
        }),
        duration_ms: result.duration.as_millis() as i64,
        work_dir: Some(work_dir_str.clone()),
    };

    let msg = RunnerMessage {
        payload: Some(proto::runner_message::Payload::Result(proto_result)),
    };
    if runner_tx.send(msg).await.is_err() {
        warn!("Failed to send HarnessResult to orchestrator, result may be lost until reconnect");
    }

    Ok(TaskMetadata {
        work_dir: work_dir_str,
        session_id: result_session_id,
    })
}

fn merge_process_proxy_env(env: &mut std::collections::HashMap<String, String>) {
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ] {
        if env.contains_key(key) {
            continue;
        }
        if let Ok(value) = std::env::var(key) {
            env.insert(key.to_string(), value);
        }
    }
}

pub async fn handle_setup(
    setup: proto::SetupSandbox,
    #[allow(unused_variables)] runner_tx: mpsc::Sender<RunnerMessage>,
) -> Result<SessionConfig, Box<dyn std::error::Error + Send + Sync>> {
    let work_dir = setup
        .work_dir
        .as_deref()
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/workspace"));

    if !work_dir.exists() {
        tokio::fs::create_dir_all(&work_dir)
            .await
            .map_err(|e| format!("Failed to create work_dir {}: {e}", work_dir.display()))?;
    }

    // Ensure work_dir is writable by the current user
    match tokio::fs::metadata(&work_dir).await {
        Ok(meta) => {
            use std::os::unix::fs::MetadataExt;
            info!(
                work_dir = %work_dir.display(),
                uid = meta.uid(),
                gid = meta.gid(),
                mode = format!("{:o}", meta.mode()),
                "Work dir metadata"
            );
        }
        Err(e) => warn!(work_dir = %work_dir.display(), error = %e, "Cannot stat work_dir"),
    }

    run_setup_commands(&work_dir, &setup.setup_commands, "SetupSandbox").await?;

    unpack_skills(&work_dir, &setup.skills, &setup.provider)
        .await
        .map_err(|e| format!("unpack_skills to {}: {e}", work_dir.display()))?;
    write_files(&work_dir, &setup.files)
        .await
        .map_err(|e| format!("write_files to {}: {e}", work_dir.display()))?;
    download_file_refs(&setup.file_refs)
        .await
        .map_err(|e| format!("download_file_refs: {e}"))?;
    crate::repos::clone_repos(&work_dir, &setup.repos)
        .await
        .map_err(|e| format!("clone setup repos to {}: {e}", work_dir.display()))?;
    write_settings_json(
        &work_dir,
        &setup.provider,
        &setup.mcp_servers,
        &setup.custom_tools,
        &setup.allowed_tools,
        &setup.ask_tools,
    )
    .await
    .map_err(|e| format!("write_settings_json to {}: {e}", work_dir.display()))?;

    #[cfg(target_os = "linux")]
    let memory_fuse_handle = if setup.provider != "docker"
        && !setup.memory_mounts.is_empty()
        && std::path::Path::new("/dev/fuse").exists()
    {
        match MemoryFuseHandle::mount_all(&setup.memory_mounts, runner_tx) {
            Ok(handle) => {
                info!(
                    count = setup.memory_mounts.len(),
                    "FUSE memory mounts active"
                );
                Some(Arc::new(handle))
            }
            Err(e) => {
                warn!(error = %e, "Failed to mount FUSE memory stores, falling back to no mount");
                None
            }
        }
    } else {
        None
    };

    let memory_mount_paths: HashMap<String, PathBuf> = setup
        .memory_mounts
        .iter()
        .map(|m| (m.mount_name.clone(), PathBuf::from(&m.mount_path)))
        .collect();

    // Write initial memory files to disk (Docker bind-mount mode)
    // FUSE mode handles this via MemoryFuseHandle above
    #[cfg(target_os = "linux")]
    let fuse_active = memory_fuse_handle.is_some();
    #[cfg(not(target_os = "linux"))]
    let fuse_active = false;

    if !fuse_active {
        write_initial_memory_files(&setup.memory_mounts)
            .await
            .map_err(|e| format!("write initial memory files: {e}"))?;
    }

    let config = SessionConfig {
        env: setup.env,
        secrets: setup.secrets,
        permission_mode: setup
            .permission_mode
            .unwrap_or_else(|| "bypassPermissions".into()),
        provider: setup.provider,
        model: setup.model,
        work_dir: Some(work_dir.clone()),
        memory_system_prompt: setup.memory_system_prompt,
        #[cfg(target_os = "linux")]
        memory_fuse_handle,
        memory_mount_paths,
    };

    info!(work_dir = %work_dir.display(), "Sandbox setup complete");
    Ok(config)
}

async fn run_setup_commands(
    work_dir: &Path,
    setup_commands: &[String],
    phase: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    for (idx, cmd) in setup_commands.iter().enumerate() {
        info!(command = %cmd, "Running setup command");
        let status = tokio::process::Command::new("sh")
            .args(["-c", cmd])
            .current_dir(work_dir)
            .status()
            .await;
        match status {
            Ok(s) if s.success() => info!(command = %cmd, "Setup command succeeded"),
            Ok(s) => {
                let detail = s
                    .code()
                    .map(|code| format!("exit code {code}"))
                    .unwrap_or_else(|| "terminated by signal".to_string());
                error!(
                    command = %cmd,
                    code = ?s.code(),
                    phase = %phase,
                    "Setup command failed"
                );
                return Err(format!(
                    "{phase} setup command #{} failed in {}: {detail}",
                    idx + 1,
                    work_dir.display()
                )
                .into());
            }
            Err(e) => {
                error!(
                    command = %cmd,
                    error = %e,
                    phase = %phase,
                    "Setup command failed to execute"
                );
                return Err(format!(
                    "{phase} setup command #{} could not execute in {}: {e}",
                    idx + 1,
                    work_dir.display()
                )
                .into());
            }
        }
    }
    Ok(())
}

/// Resolve the skill directory layout for a given engine/provider.
///
/// Each agent CLI discovers skills from a different directory convention:
/// - Claude Code / native (claude binary) → `<work_dir>/.claude/skills/...`
/// - Codex → `<work_dir>/.agents/skills/...`
///   (codex scans `.agents/skills` from cwd up to the project root, see
///   codex-rs/core-skills/src/loader.rs `repo_agents_skill_roots`)
///
/// `target` is the leaf subdir name supplied by the orchestrator (always
/// "skills" today); we honour it under the engine-specific parent so future
/// targets keep working.
fn skill_base_dir(work_dir: &Path, provider: &str, target: &str) -> PathBuf {
    match provider {
        "codex" => work_dir.join(".agents").join(target),
        "pi" => work_dir.join(".pi").join(target),
        // "claude", "native", and anything else default to Claude's layout.
        _ => work_dir.join(".claude").join(target),
    }
}

async fn unpack_skills(
    work_dir: &Path,
    skills: &[proto::SkillArchive],
    provider: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use sha2::{Digest, Sha256};

    for skill in skills {
        let target_dir = skill_base_dir(work_dir, provider, &skill.target);
        let marker_path = target_dir.join(&skill.name).join(".skill_hash");

        // Fast path: if the skill is already unpacked with the same content, skip.
        let content_hash = format!("{:x}", Sha256::digest(&skill.tar_gz));
        if let Ok(existing_hash) = tokio::fs::read_to_string(&marker_path).await {
            if existing_hash.trim() == content_hash {
                debug!(
                    name = %skill.name,
                    target = %skill.target,
                    "Skill already unpacked (hash match), skipping"
                );
                continue;
            }
        }

        // Unpack (first time or content changed)
        tokio::fs::create_dir_all(&target_dir)
            .await
            .map_err(|e| format!("mkdir {}: {e}", target_dir.display()))?;
        crate::archive::extract_tar_gz_bytes_to_dir(&skill.tar_gz, &target_dir)
            .map_err(|e| format!("unpack tar to {}: {e}", target_dir.display()))?;

        // Write marker for next time
        if let Some(parent) = marker_path.parent() {
            let _ = tokio::fs::create_dir_all(parent).await;
        }
        let _ = tokio::fs::write(&marker_path, &content_hash).await;

        info!(
            name = %skill.name,
            target = %skill.target,
            provider = %provider,
            "Unpacked to {}",
            target_dir.display()
        );
    }
    Ok(())
}

async fn write_files(
    _work_dir: &PathBuf,
    files: &[proto::FileMount],
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    for file in files {
        let path = std::path::Path::new(&file.path);
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent)
                .await
                .map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
        }
        tokio::fs::write(path, &file.content)
            .await
            .map_err(|e| format!("write {}: {e}", path.display()))?;
        auto_extract_file_archive(path, &file.path, &file.filename).await?;
        info!(path = %file.path, filename = %file.filename, size = file.content.len(), "Wrote file");
    }
    Ok(())
}

async fn download_file_refs(
    file_refs: &[proto::FileRef],
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    if file_refs.is_empty() {
        return Ok(());
    }

    // Download up to 8 files concurrently for reduced wall-clock time.
    let semaphore = Arc::new(tokio::sync::Semaphore::new(8));
    let mut join_set = tokio::task::JoinSet::new();

    for fr in file_refs {
        let url = fr.url.clone();
        let path = fr.path.clone();
        let filename = fr.filename.clone();
        let sem = semaphore.clone();

        join_set.spawn(async move {
            let _permit = sem
                .acquire()
                .await
                .map_err(|e| format!("semaphore: {e}"))?;
            download_single_file_ref(&url, &path, &filename).await
        });
    }

    while let Some(result) = join_set.join_next().await {
        match result {
            Ok(Ok(())) => {}
            Ok(Err(e)) => return Err(e),
            Err(e) => return Err(format!("download task panicked: {e}").into()),
        }
    }
    Ok(())
}

async fn download_single_file_ref(
    url: &str,
    file_path: &str,
    filename: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let path = std::path::Path::new(file_path);
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    info!(url = %url, path = %file_path, "Downloading file from presigned URL");
    let resp = reqwest::get(url)
        .await
        .map_err(|e| format!("download file ref {}: {e}", file_path))?;
    if !resp.status().is_success() {
        return Err(format!(
            "download file ref {} returned HTTP {}",
            file_path,
            resp.status()
        )
        .into());
    }
    let bytes = resp
        .bytes()
        .await
        .map_err(|e| format!("read file ref body {}: {e}", file_path))?;
    tokio::fs::write(path, &bytes)
        .await
        .map_err(|e| format!("write {}: {e}", path.display()))?;
    auto_extract_file_archive(path, file_path, filename).await?;
    info!(path = %file_path, filename = %filename, size = bytes.len(), "Downloaded file");
    Ok(())
}

async fn auto_extract_file_archive(
    path: &Path,
    display_path: &str,
    filename: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    if let Some(target_dir) = crate::archive::auto_extract_archive(path)
        .await
        .map_err(|e| {
            format!(
                "auto-extract archive {} ({}) to workspace failed: {e}",
                display_path, filename
            )
        })?
    {
        info!(
            path = %display_path,
            filename = %filename,
            target = %target_dir.display(),
            "Auto-extracted file archive"
        );
    }
    Ok(())
}

async fn write_initial_memory_files(
    memory_mounts: &[proto::MemoryStoreMount],
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    for mount in memory_mounts {
        let mount_path = Path::new(&mount.mount_path);
        for file in &mount.files {
            let rel = file.relative_path.trim_start_matches('/');
            let file_path = mount_path.join(rel);
            if let Some(parent) = file_path.parent() {
                tokio::fs::create_dir_all(parent).await.map_err(|e| {
                    format!(
                        "create memory dir {} for mount {}: {e}",
                        parent.display(),
                        mount.mount_name
                    )
                })?;
            }
            tokio::fs::write(&file_path, &file.content)
                .await
                .map_err(|e| {
                    format!(
                        "write initial memory file {} for mount {}: {e}",
                        file_path.display(),
                        mount.mount_name
                    )
                })?;
            info!(
                path = %file_path.display(),
                size = file.content.len(),
                "Wrote initial memory file"
            );
        }
    }
    Ok(())
}

async fn write_settings_json(
    work_dir: &Path,
    provider: &str,
    mcp_servers: &[proto::McpConfig],
    custom_tools: &[proto::CustomTool],
    allowed_tools: &[String],
    ask_tools: &[String],
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // ``.claude/settings.json`` is consumed only by the Claude Code CLI. Codex
    // reads ``~/.codex/config.toml`` (merged separately by the codex runtime
    // adapter) and the native adapter spawns processes directly without any
    // config file, so writing this file for them just litters the sandbox
    // workspace with an inert file that misleads operators (e.g. an empty
    // ``.claude/`` showing up inside a codex sandbox).
    if !matches!(provider, "claude" | "claude_code") {
        return Ok(());
    }
    if mcp_servers.is_empty()
        && custom_tools.is_empty()
        && allowed_tools.is_empty()
        && ask_tools.is_empty()
    {
        return Ok(());
    }

    // MCP server *definitions* must live in the project-root `.mcp.json` file.
    // Claude Code discovers project-scoped servers from `<cwd>/.mcp.json`
    // (key: "mcpServers"); it does NOT read server definitions from
    // `.claude/settings.json`. See claude-code src/services/mcp/config.ts
    // (getMcpConfigsByScope -> 'project' reads `.mcp.json`).
    if !mcp_servers.is_empty() {
        write_mcp_json(work_dir, mcp_servers).await?;
    }

    // `.claude/settings.json` carries the *approval* + custom tools + permission rules.
    // Project-scoped servers from `.mcp.json` are pending approval by default; the
    // sandbox runs non-interactively so there is no approval dialog.
    // `enableAllProjectMcpServers: true` auto-approves them.
    let need_settings = !mcp_servers.is_empty()
        || !custom_tools.is_empty()
        || !allowed_tools.is_empty()
        || !ask_tools.is_empty();
    if !need_settings {
        return Ok(());
    }

    let claude_dir = work_dir.join(".claude");
    tokio::fs::create_dir_all(&claude_dir)
        .await
        .map_err(|e| format!("mkdir {}: {e}", claude_dir.display()))?;
    let settings_path = claude_dir.join("settings.json");

    let mut settings: serde_json::Value = if settings_path.exists() {
        let content = tokio::fs::read_to_string(&settings_path)
            .await
            .unwrap_or_default();
        serde_json::from_str(&content).unwrap_or(serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    if !mcp_servers.is_empty() {
        // Auto-approve all project-scoped (.mcp.json) servers in this sandbox.
        settings["enableAllProjectMcpServers"] = serde_json::Value::Bool(true);
    }

    if !custom_tools.is_empty() {
        let tools: Vec<serde_json::Value> = custom_tools
            .iter()
            .map(|t| {
                let schema: serde_json::Value =
                    serde_json::from_str(&t.input_schema_json).unwrap_or(serde_json::json!({}));
                serde_json::json!({
                    "type": "custom",
                    "name": t.name,
                    "description": t.description,
                    "input_schema": schema,
                })
            })
            .collect();
        settings["customTools"] = serde_json::Value::Array(tools);
    }

    // Tool permission rules (official Managed Agents model: allow + ask only).
    if !allowed_tools.is_empty() || !ask_tools.is_empty() {
        let mut perms = serde_json::Map::new();
        if !allowed_tools.is_empty() {
            perms.insert("allow".to_string(), serde_json::json!(allowed_tools));
        }
        if !ask_tools.is_empty() {
            perms.insert("ask".to_string(), serde_json::json!(ask_tools));
        }
        settings["permissions"] = serde_json::Value::Object(perms);
    }

    let content = serde_json::to_string_pretty(&settings).unwrap_or_default();
    tokio::fs::write(&settings_path, content).await?;
    info!("Wrote .claude/settings.json");
    Ok(())
}

/// Write MCP server definitions to the project-root `.mcp.json` so Claude Code
/// discovers them as project-scoped servers.
///
/// Structure: `{ "mcpServers": { "<name>": { ... } } }`.
/// Remote servers (url present) use `type: "http"` (Claude Code accepts
/// `streamable-http` as an alias; `sse` is honored when explicitly requested).
/// Local servers use `command` / `args` / `env`.
async fn write_mcp_json(
    work_dir: &Path,
    mcp_servers: &[proto::McpConfig],
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mcp_json_path = work_dir.join(".mcp.json");

    // Merge into any existing `.mcp.json` (e.g. one checked into the repo).
    let mut root: serde_json::Value = if mcp_json_path.exists() {
        let content = tokio::fs::read_to_string(&mcp_json_path)
            .await
            .unwrap_or_default();
        serde_json::from_str(&content).unwrap_or(serde_json::json!({}))
    } else {
        serde_json::json!({})
    };
    if !root.is_object() {
        root = serde_json::json!({});
    }

    let mut mcp_obj = root
        .get("mcpServers")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();

    for server in mcp_servers {
        let is_remote = !server.url.is_empty();
        let entry = if is_remote {
            // `server_type` may arrive as "sse", "url", "streamable-http", or
            // empty. Only "sse" needs the distinct transport; everything else
            // (including the legacy "url") maps to Claude Code's "http".
            let transport = if server.server_type == "sse" {
                "sse"
            } else {
                "http"
            };
            let mut e = serde_json::json!({"type": transport, "url": server.url});
            if !server.headers.is_empty() {
                e["headers"] = serde_json::json!(server.headers);
            }
            e
        } else {
            let mut e = serde_json::json!({"command": server.command, "args": server.args});
            if !server.env.is_empty() {
                e["env"] = serde_json::json!(server.env);
            }
            e
        };
        mcp_obj.insert(server.name.clone(), entry);
    }

    root["mcpServers"] = serde_json::Value::Object(mcp_obj);

    let content = serde_json::to_string_pretty(&root).unwrap_or_default();
    tokio::fs::write(&mcp_json_path, content).await?;
    info!(
        servers = mcp_servers.len(),
        "Wrote .mcp.json with project-scoped MCP servers"
    );
    Ok(())
}

/// Handle a MemoryFileUpdate from the orchestrator (cross-session sync).
/// For Docker: writes/deletes the file at the bind mount path.
/// For FUSE (Linux): updates the in-memory filesystem.
pub async fn handle_memory_update(update: proto::MemoryFileUpdate, config: &SessionConfig) {
    let mount_name = &update.store_mount_name;

    #[cfg(target_os = "linux")]
    if let Some(ref fuse_handle) = config.memory_fuse_handle {
        if update.operation == "delete" {
            fuse_handle.remove_file(mount_name, &update.relative_path);
        } else {
            fuse_handle.write_file(mount_name, &update.relative_path, &update.content);
        }
        info!(mount_name = %mount_name, path = %update.relative_path, "Applied memory update via FUSE");
        return;
    }

    // Docker bind mount path
    if let Some(mount_path) = config.memory_mount_paths.get(mount_name) {
        let rel = update.relative_path.trim_start_matches('/');
        let file_path = mount_path.join(rel);
        if update.operation == "delete" {
            if let Err(e) = tokio::fs::remove_file(&file_path).await {
                warn!(path = %file_path.display(), error = %e, "Failed to delete memory file from peer update");
            }
        } else {
            if let Some(parent) = file_path.parent() {
                let _ = tokio::fs::create_dir_all(parent).await;
            }
            if let Err(e) = tokio::fs::write(&file_path, &update.content).await {
                warn!(path = %file_path.display(), error = %e, "Failed to write memory file from peer update");
            }
        }
        info!(path = %file_path.display(), "Applied memory update via bind mount");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn skill_base_dir_pi_uses_dot_pi() {
        let base = skill_base_dir(std::path::Path::new("/w"), "pi", "skills");
        assert_eq!(base, std::path::Path::new("/w/.pi/skills"));
    }

    #[test]
    fn dedupe_only_applies_to_structured_live_input() {
        let mut seen = HashSet::new();
        let a = "__joysafeter_input_v1__:{\"type\":\"interrupt\"}";
        let b = "__joysafeter_input_v1__:{\"type\":\"interrupt\"}";
        let plain = "hello";

        assert!(should_forward_control_input(&mut seen, a));
        assert!(!should_forward_control_input(&mut seen, b));
        assert!(should_forward_control_input(&mut seen, plain));
        assert!(should_forward_control_input(&mut seen, plain));
    }

    #[test]
    fn dedupe_structured_control_input_by_semantics() {
        let mut seen = HashSet::new();
        let a = "__joysafeter_input_v1__:{\"type\":\"tool_confirmation\",\"tool_use_call_id\":\"req_1\",\"approved\":true}";
        let b = "__joysafeter_input_v1__:{\"approved\":true,\"tool_use_call_id\":\"req_1\",\"type\":\"tool_confirmation\"}";

        assert!(should_forward_control_input(&mut seen, a));
        assert!(!should_forward_control_input(&mut seen, b));
    }

    #[test]
    fn dedupe_prefers_source_event_id_when_present() {
        let mut seen = HashSet::new();
        let a = "__joysafeter_input_v1__:{\"type\":\"interrupt\",\"source_event_id\":\"evt_1\"}";
        let b = "__joysafeter_input_v1__:{\"type\":\"interrupt\",\"source_event_id\":\"evt_1\"}";

        assert!(should_forward_control_input(&mut seen, a));
        assert!(!should_forward_control_input(&mut seen, b));
    }

    #[tokio::test]
    async fn handle_setup_fails_when_declared_repo_clone_fails() {
        let dir = tempfile::tempdir().unwrap();
        let missing_source = dir.path().join("missing-source.git");
        let setup = proto::SetupSandbox {
            work_dir: Some(dir.path().to_string_lossy().to_string()),
            repos: vec![proto::RepoConfig {
                url: missing_source.to_string_lossy().to_string(),
                path: "repo".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let (runner_tx, _runner_rx) = mpsc::channel(1);

        let result = handle_setup(setup, runner_tx).await;

        assert!(result.is_err());
        assert!(result
            .err()
            .unwrap()
            .to_string()
            .contains("clone setup repos"));
        assert!(!dir.path().join("repo/.git").exists());
    }

    #[tokio::test]
    async fn handle_setup_fails_when_setup_command_exits_non_zero() {
        let dir = tempfile::tempdir().unwrap();
        let setup = proto::SetupSandbox {
            work_dir: Some(dir.path().to_string_lossy().to_string()),
            setup_commands: vec!["exit 23".to_string(), "touch should_not_run".to_string()],
            ..Default::default()
        };
        let (runner_tx, _runner_rx) = mpsc::channel(1);

        let err = match handle_setup(setup, runner_tx).await {
            Ok(_) => panic!("failing setup command must fail sandbox setup"),
            Err(err) => err.to_string(),
        };

        assert!(err.contains("SetupSandbox setup command #1 failed"));
        assert!(err.contains("exit code 23"));
        assert!(!dir.path().join("should_not_run").exists());
    }

    #[tokio::test]
    async fn handle_setup_fails_when_initial_memory_file_cannot_be_written() {
        let dir = tempfile::tempdir().unwrap();
        let blocked_mount_path = dir.path().join("memory-blocker");
        tokio::fs::write(&blocked_mount_path, b"not a directory")
            .await
            .unwrap();
        let setup = proto::SetupSandbox {
            work_dir: Some(dir.path().to_string_lossy().to_string()),
            provider: "docker".to_string(),
            memory_mounts: vec![proto::MemoryStoreMount {
                mount_name: "mem".to_string(),
                mount_path: blocked_mount_path.to_string_lossy().to_string(),
                files: vec![proto::MemoryFile {
                    relative_path: "seed.md".to_string(),
                    content: b"seed".to_vec(),
                }],
                ..Default::default()
            }],
            ..Default::default()
        };
        let (runner_tx, _runner_rx) = mpsc::channel(1);

        let err = match handle_setup(setup, runner_tx).await {
            Ok(_) => panic!("unwritable initial memory file must fail sandbox setup"),
            Err(err) => err.to_string(),
        };

        assert!(err.contains("write initial memory files"));
        assert!(err.contains("memory-blocker"));
        assert!(!dir.path().join("memory-blocker/seed.md").exists());
    }

    #[tokio::test]
    async fn handle_setup_fails_when_inline_archive_file_cannot_be_extracted() {
        let dir = tempfile::tempdir().unwrap();
        let archive_path = dir.path().join("broken.zip");
        let setup = proto::SetupSandbox {
            work_dir: Some(dir.path().to_string_lossy().to_string()),
            files: vec![proto::FileMount {
                path: archive_path.to_string_lossy().to_string(),
                filename: "broken.zip".to_string(),
                content: b"not a valid zip".to_vec(),
            }],
            ..Default::default()
        };
        let (runner_tx, _runner_rx) = mpsc::channel(1);

        let err = match handle_setup(setup, runner_tx).await {
            Ok(_) => panic!("invalid inline archive must fail sandbox setup"),
            Err(err) => err.to_string(),
        };

        assert!(err.contains("write_files"));
        assert!(err.contains("auto-extract archive"));
        assert!(err.contains("broken.zip"));
        assert!(archive_path.exists());
    }

    #[tokio::test]
    async fn handle_setup_fails_when_file_ref_download_returns_non_success_status() {
        let dir = tempfile::tempdir().unwrap();
        let (url, server) = spawn_single_response_server(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec(),
        )
        .await;
        let file_path = dir.path().join("missing.bin");
        let setup = proto::SetupSandbox {
            work_dir: Some(dir.path().to_string_lossy().to_string()),
            file_refs: vec![proto::FileRef {
                path: file_path.to_string_lossy().to_string(),
                url,
                filename: "missing.bin".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let (runner_tx, _runner_rx) = mpsc::channel(1);

        let err = match handle_setup(setup, runner_tx).await {
            Ok(_) => panic!("non-success file ref download must fail sandbox setup"),
            Err(err) => err.to_string(),
        };
        server.await.unwrap();

        assert!(err.contains("download_file_refs"));
        assert!(err.contains("HTTP 404"));
        assert!(!file_path.exists());
    }

    #[tokio::test]
    async fn handle_setup_fails_when_downloaded_archive_cannot_be_extracted() {
        let dir = tempfile::tempdir().unwrap();
        let body = b"not a valid zip";
        let mut response =
            b"HTTP/1.1 200 OK\r\nContent-Type: application/zip\r\nContent-Length: ".to_vec();
        response.extend_from_slice(body.len().to_string().as_bytes());
        response.extend_from_slice(b"\r\nConnection: close\r\n\r\n");
        response.extend_from_slice(body);
        let (url, server) = spawn_single_response_server(response).await;
        let archive_path = dir.path().join("downloaded.zip");
        let setup = proto::SetupSandbox {
            work_dir: Some(dir.path().to_string_lossy().to_string()),
            file_refs: vec![proto::FileRef {
                path: archive_path.to_string_lossy().to_string(),
                url,
                filename: "downloaded.zip".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let (runner_tx, _runner_rx) = mpsc::channel(1);

        let err = match handle_setup(setup, runner_tx).await {
            Ok(_) => panic!("invalid downloaded archive must fail sandbox setup"),
            Err(err) => err.to_string(),
        };
        server.await.unwrap();

        assert!(err.contains("download_file_refs"));
        assert!(err.contains("auto-extract archive"));
        assert!(err.contains("downloaded.zip"));
        assert!(archive_path.exists());
    }

    #[tokio::test]
    async fn handle_task_fails_when_fallback_setup_command_exits_before_adapter_run() {
        std::env::set_var("JOYSAFETER_MOCK_ADAPTER", "1");
        let dir = tempfile::tempdir().unwrap();
        let adapters = Arc::new(AdapterRegistry::discover().await);
        assert!(adapters.get("claude").is_some());
        let task = proto::StartTask {
            provider: "claude".to_string(),
            work_dir: Some(dir.path().to_string_lossy().to_string()),
            setup_commands: vec!["exit 24".to_string(), "touch should_not_run".to_string()],
            ..Default::default()
        };
        let session_config = SessionConfig::default();
        let (runner_tx, mut runner_rx) = mpsc::channel(1);
        let (_cancel_tx, cancel_rx) = oneshot::channel();
        let (_control_tx, control_rx) = mpsc::channel(1);

        let err = match handle_task(
            task,
            &session_config,
            adapters,
            runner_tx,
            cancel_rx,
            control_rx,
        )
        .await
        {
            Ok(_) => panic!("failing StartTask setup command must fail before adapter starts"),
            Err(err) => err.to_string(),
        };

        assert!(err.contains("StartTask setup command #1 failed"));
        assert!(err.contains("exit code 24"));
        assert!(!dir.path().join("should_not_run").exists());
        assert!(runner_rx.try_recv().is_err());
    }

    async fn spawn_single_response_server(
        response: Vec<u8>,
    ) -> (String, tokio::task::JoinHandle<()>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut request = [0_u8; 1024];
            let _ = tokio::io::AsyncReadExt::read(&mut socket, &mut request).await;
            tokio::io::AsyncWriteExt::write_all(&mut socket, &response)
                .await
                .unwrap();
        });
        (format!("http://{addr}/file"), server)
    }

    #[tokio::test]
    async fn write_settings_json_emits_permissions_and_mcp() {
        let dir = std::env::temp_dir().join(format!("jsf_test_{}", std::process::id()));
        let _ = tokio::fs::remove_dir_all(&dir).await;
        tokio::fs::create_dir_all(&dir).await.unwrap();

        let mcp = vec![proto::McpConfig {
            name: "github".into(),
            url: "https://mcp.example.com".into(),
            server_type: "url".into(),
            ..Default::default()
        }];
        let allowed = vec!["Bash".to_string(), "Read".to_string()];
        let ask = vec!["mcp__github__*".to_string()];

        write_settings_json(&dir, "claude", &mcp, &[], &allowed, &ask)
            .await
            .unwrap();

        // settings.json: permissions (allow/ask) + enableAllProjectMcpServers, NO mcpServers
        let settings: serde_json::Value = serde_json::from_str(
            &tokio::fs::read_to_string(dir.join(".claude/settings.json"))
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            settings["permissions"]["allow"],
            serde_json::json!(["Bash", "Read"])
        );
        assert_eq!(
            settings["permissions"]["ask"],
            serde_json::json!(["mcp__github__*"])
        );
        assert_eq!(
            settings["enableAllProjectMcpServers"],
            serde_json::json!(true)
        );
        assert!(
            settings.get("mcpServers").is_none(),
            "MCP defs must NOT be in settings.json"
        );
        assert!(
            settings["permissions"].get("deny").is_none(),
            "no deny in official model"
        );

        // .mcp.json: server definition lives here
        let mcp_json: serde_json::Value = serde_json::from_str(
            &tokio::fs::read_to_string(dir.join(".mcp.json"))
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            mcp_json["mcpServers"]["github"]["type"],
            serde_json::json!("http")
        );
        assert_eq!(
            mcp_json["mcpServers"]["github"]["url"],
            serde_json::json!("https://mcp.example.com")
        );

        let _ = tokio::fs::remove_dir_all(&dir).await;
    }
}
