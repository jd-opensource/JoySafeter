#[cfg(target_os = "linux")]
use crate::memory_fuse::MemoryFuseHandle;
use crate::proto::{self, RunnerHarnessResult, RunnerMessage};
use crate::stream::harness_event_to_proto;

use joysafeter_runtime::AdapterRegistry;
use joysafeter_types::harness::HarnessInput;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, oneshot};
use tracing::{error, info, warn};

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
    pub aborted: bool,
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

    let work_dir = session_config.work_dir.clone()
        .or_else(|| task.work_dir.as_deref().map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from("/workspace"));

    if !work_dir.exists() {
        tokio::fs::create_dir_all(&work_dir).await?;
    }

    // SetupSandbox is the normal path for skills, but pooled/reconnected
    // sandboxes can miss setup if the session link is established late.  StartTask
    // also carries skills, so unpack them here as an idempotent fallback before
    // the Claude process starts.
    unpack_skills(&work_dir, &task.skills).await.map_err(|e| {
        format!("unpack task skills to {}: {e}", work_dir.display())
    })?;

    // Execute environment setup commands (package installs etc.)
    for cmd in &task.setup_commands {
        info!(command = %cmd, "Running setup command");
        let status = tokio::process::Command::new("sh")
            .args(["-c", cmd])
            .current_dir(&work_dir)
            .status()
            .await;
        match status {
            Ok(s) if s.success() => {
                info!(command = %cmd, "Setup command succeeded");
            }
            Ok(s) => {
                warn!(command = %cmd, code = ?s.code(), "Setup command exited with non-zero");
            }
            Err(e) => {
                warn!(command = %cmd, error = %e, "Setup command failed to execute");
            }
        }
    }

    // Write MCP servers and custom tools to .claude/settings.json (per-task overrides only)
    write_settings_json(&work_dir, &task.mcp_servers, &task.custom_tools).await?;

    let env = if session_config.env.is_empty() { task.env.clone() } else { session_config.env.clone() };
    let secrets = if session_config.secrets.is_empty() { task.secrets.clone() } else { session_config.secrets.clone() };
    let model = session_config.model.clone().or(task.model.clone());
    let permission_mode = if session_config.permission_mode.is_empty() {
        task.permission_mode.clone().unwrap_or_else(|| "bypassPermissions".into())
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
        session_id: task.session_id.clone(),
        model,
        max_turns: task.max_turns,
        timeout: Duration::from_secs(task.timeout_seconds),
        env,
        secrets,
        mcp_configs: vec![],
        permission_mode,
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
            aborted: true,
        });
    }

    let result = harness
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
        aborted: false,
    })
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
        tokio::fs::create_dir_all(&work_dir).await.map_err(|e| {
            format!("Failed to create work_dir {}: {e}", work_dir.display())
        })?;
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

    for cmd in &setup.setup_commands {
        info!(command = %cmd, "Running setup command");
        let status = tokio::process::Command::new("sh")
            .args(["-c", cmd])
            .current_dir(&work_dir)
            .status()
            .await;
        match status {
            Ok(s) if s.success() => info!(command = %cmd, "Setup command succeeded"),
            Ok(s) => warn!(command = %cmd, code = ?s.code(), "Setup command non-zero"),
            Err(e) => warn!(command = %cmd, error = %e, "Setup command failed"),
        }
    }

    unpack_skills(&work_dir, &setup.skills).await.map_err(|e| {
        format!("unpack_skills to {}: {e}", work_dir.display())
    })?;
    write_files(&work_dir, &setup.files).await.map_err(|e| {
        format!("write_files to {}: {e}", work_dir.display())
    })?;
    download_file_refs(&setup.file_refs).await.map_err(|e| {
        format!("download_file_refs: {e}")
    })?;
    write_settings_json(&work_dir, &setup.mcp_servers, &setup.custom_tools).await.map_err(|e| {
        format!("write_settings_json to {}: {e}", work_dir.display())
    })?;

    #[cfg(target_os = "linux")]
    let memory_fuse_handle = if setup.provider != "docker"
        && !setup.memory_mounts.is_empty()
        && std::path::Path::new("/dev/fuse").exists()
    {
        match MemoryFuseHandle::mount_all(&setup.memory_mounts, runner_tx) {
            Ok(handle) => {
                info!(count = setup.memory_mounts.len(), "FUSE memory mounts active");
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

    let memory_mount_paths: HashMap<String, PathBuf> = setup.memory_mounts.iter()
        .map(|m| (m.mount_name.clone(), PathBuf::from(&m.mount_path)))
        .collect();

    // Write initial memory files to disk (Docker bind-mount mode)
    // FUSE mode handles this via MemoryFuseHandle above
    #[cfg(target_os = "linux")]
    let fuse_active = memory_fuse_handle.is_some();
    #[cfg(not(target_os = "linux"))]
    let fuse_active = false;

    if !fuse_active {
        for mount in &setup.memory_mounts {
            let mount_path = std::path::Path::new(&mount.mount_path);
            for file in &mount.files {
                let rel = file.relative_path.trim_start_matches('/');
                let file_path = mount_path.join(rel);
                if let Some(parent) = file_path.parent() {
                    if let Err(e) = tokio::fs::create_dir_all(parent).await {
                        warn!(path = %parent.display(), error = %e, "Failed to create memory dir");
                        continue;
                    }
                }
                if let Err(e) = tokio::fs::write(&file_path, &file.content).await {
                    warn!(path = %file_path.display(), error = %e, "Failed to write initial memory file");
                } else {
                    info!(path = %file_path.display(), size = file.content.len(), "Wrote initial memory file");
                }
            }
        }
    }

    let config = SessionConfig {
        env: setup.env,
        secrets: setup.secrets,
        permission_mode: setup.permission_mode.unwrap_or_else(|| "bypassPermissions".into()),
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

async fn unpack_skills(
    work_dir: &PathBuf,
    skills: &[proto::SkillArchive],
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    for skill in skills {
        let target_dir = work_dir.join(".claude").join(&skill.target);
        tokio::fs::create_dir_all(&target_dir).await.map_err(|e| {
            format!("mkdir {}: {e}", target_dir.display())
        })?;
        let cursor = std::io::Cursor::new(&skill.tar_gz);
        let gz = flate2::read::GzDecoder::new(cursor);
        let mut archive = tar::Archive::new(gz);
        archive.unpack(&target_dir).map_err(|e| {
            format!("unpack tar to {}: {e}", target_dir.display())
        })?;
        info!(name = %skill.name, target = %skill.target, "Unpacked to {}", target_dir.display());
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
            tokio::fs::create_dir_all(parent).await.map_err(|e| {
                format!("mkdir {}: {e}", parent.display())
            })?;
        }
        tokio::fs::write(path, &file.content).await.map_err(|e| {
            format!("write {}: {e}", path.display())
        })?;
        info!(path = %file.path, filename = %file.filename, size = file.content.len(), "Wrote file");
    }
    Ok(())
}

async fn download_file_refs(
    file_refs: &[proto::FileRef],
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    for fr in file_refs {
        let path = std::path::Path::new(&fr.path);
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await.map_err(|e| {
                format!("mkdir {}: {e}", parent.display())
            })?;
        }
        info!(url = %fr.url, path = %fr.path, "Downloading file from presigned URL");
        let resp = reqwest::get(&fr.url).await.map_err(|e| {
            format!("download {}: {e}", fr.url)
        })?;
        if !resp.status().is_success() {
            warn!(status = %resp.status(), url = %fr.url, "File download failed");
            continue;
        }
        let bytes = resp.bytes().await.map_err(|e| {
            format!("read body {}: {e}", fr.url)
        })?;
        tokio::fs::write(path, &bytes).await.map_err(|e| {
            format!("write {}: {e}", path.display())
        })?;
        info!(path = %fr.path, filename = %fr.filename, size = bytes.len(), "Downloaded file");
    }
    Ok(())
}

async fn write_settings_json(
    work_dir: &PathBuf,
    mcp_servers: &[proto::McpConfig],
    custom_tools: &[proto::CustomTool],
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    if mcp_servers.is_empty() && custom_tools.is_empty() {
        return Ok(());
    }

    let claude_dir = work_dir.join(".claude");
    tokio::fs::create_dir_all(&claude_dir).await.map_err(|e| {
        format!("mkdir {}: {e}", claude_dir.display())
    })?;
    let settings_path = claude_dir.join("settings.json");

    let mut settings: serde_json::Value = if settings_path.exists() {
        let content = tokio::fs::read_to_string(&settings_path).await.unwrap_or_default();
        serde_json::from_str(&content).unwrap_or(serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    if !mcp_servers.is_empty() {
        let mut mcp_obj = serde_json::Map::new();
        for server in mcp_servers {
            let entry = if server.server_type == "url" && !server.url.is_empty() {
                let mut e = serde_json::json!({"type": "url", "url": server.url});
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
        settings["mcpServers"] = serde_json::Value::Object(mcp_obj);
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

    let content = serde_json::to_string_pretty(&settings).unwrap_or_default();
    tokio::fs::write(&settings_path, content).await?;
    info!("Wrote .claude/settings.json");
    Ok(())
}

/// Handle a MemoryFileUpdate from the orchestrator (cross-session sync).
/// For Docker: writes/deletes the file at the bind mount path.
/// For FUSE (Linux): updates the in-memory filesystem.
pub async fn handle_memory_update(
    update: proto::MemoryFileUpdate,
    config: &SessionConfig,
) {
    let mount_name = &update.store_mount_name;

    #[cfg(target_os = "linux")]
    if let Some(ref fuse_handle) = config.memory_fuse_handle {
        if update.operation == "delete" {
            fuse_handle.remove_file(mount_name, &update.relative_path);
        } else {
            fuse_handle.write_file(mount_name, &update.relative_path, &update.content);
        }
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
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
