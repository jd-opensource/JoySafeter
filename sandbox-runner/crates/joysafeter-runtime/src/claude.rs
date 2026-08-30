use async_trait::async_trait;
use joysafeter_types::harness::{
    HarnessAdapter, HarnessError, HarnessEvent, HarnessInput, HarnessResult, RunningHarness,
};
use joysafeter_types::token_usage::{ModelUsage, TokenUsage};
use serde::Deserialize;
use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::sync::{mpsc, oneshot, Mutex};
use tracing::{info, warn};

type SharedStdin = Arc<Mutex<Option<tokio::process::ChildStdin>>>;
const LIVE_INPUT_PREFIX: &str = "__joysafeter_input_v1__:";

// ---------------------------------------------------------------------------
// Per-turn state (analogous to codex.rs TurnState)
// ---------------------------------------------------------------------------

struct TurnState {
    event_tx: mpsc::Sender<HarnessEvent>,
    turn_done_tx: Option<oneshot::Sender<bool>>,
    usage: Arc<std::sync::Mutex<TokenUsage>>,
    output: Arc<std::sync::Mutex<String>>,
    error: Arc<std::sync::Mutex<Option<String>>>,
    harness_session_id: Arc<std::sync::Mutex<Option<String>>>,
    call_id_to_tool: Arc<std::sync::Mutex<HashMap<String, String>>>,
}

// ---------------------------------------------------------------------------
// Persistent subprocess state
// ---------------------------------------------------------------------------

struct PersistentClaude {
    stdin: SharedStdin,
    #[allow(dead_code)]
    reader_handle: tokio::task::JoinHandle<()>,
    current_turn: Arc<Mutex<Option<TurnState>>>,
    child: tokio::process::Child,
    config_fingerprint: u64,
    last_harness_session_id: Arc<std::sync::Mutex<Option<String>>>,
}

// ---------------------------------------------------------------------------
// ClaudeAdapter — now stateful, holds a persistent session
// ---------------------------------------------------------------------------

pub struct ClaudeAdapter {
    session: Arc<Mutex<Option<PersistentClaude>>>,
}

impl Default for ClaudeAdapter {
    fn default() -> Self {
        Self::new()
    }
}

impl ClaudeAdapter {
    pub fn new() -> Self {
        Self {
            session: Arc::new(Mutex::new(None)),
        }
    }

    fn compute_fingerprint(input: &HarnessInput) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        input.model.hash(&mut hasher);
        input.tool_policy.hash(&mut hasher);
        input.system_prompt.hash(&mut hasher);
        input.system_prompt_mode.hash(&mut hasher);
        serde_json::to_string(&input.mcp_configs)
            .expect("MCP configs must serialize for process fingerprint")
            .hash(&mut hasher);
        serde_json::to_string(&input.custom_tools)
            .expect("custom tools must serialize for process fingerprint")
            .hash(&mut hasher);
        let mut env_keys: Vec<_> = input.env.keys().collect();
        env_keys.sort();
        for k in &env_keys {
            k.hash(&mut hasher);
            input.env[*k].hash(&mut hasher);
        }
        hasher.finish()
    }

    async fn ensure_session(&self, input: &HarnessInput, cwd: &Path) -> Result<(), HarnessError> {
        let mut guard = self.session.lock().await;
        let fp = Self::compute_fingerprint(input);

        let reuse = if let Some(ref mut session) = *guard {
            match session.child.try_wait() {
                Ok(None) if session.config_fingerprint == fp => true,
                Ok(None) => {
                    info!("Config fingerprint changed, restarting claude process");
                    false
                }
                Ok(Some(status)) => {
                    warn!(exit_code = ?status.code(), "Claude process exited, restarting");
                    false
                }
                Err(e) => {
                    warn!(error = %e, "Failed to check claude process status, restarting");
                    false
                }
            }
        } else {
            false
        };

        if reuse {
            return Ok(());
        }

        // Kill old process if it exists
        if let Some(ref mut old) = guard.take() {
            let _ = old.child.start_kill();
            let _ = old.child.wait().await;
        }

        let resume_harness_session_id = input.harness_session_id.clone();
        let permission_mode =
            crate::tool_policy::claude_permission_mode("claude", &input.tool_policy)?;

        let mut args = vec![
            "-p".to_string(),
            "--output-format".to_string(),
            "stream-json".to_string(),
            "--input-format".to_string(),
            "stream-json".to_string(),
            "--verbose".to_string(),
            "--permission-mode".to_string(),
            permission_mode.to_string(),
            "--permission-prompt-tool".to_string(),
            "stdio".to_string(),
        ];

        if let Some(model) = &input.model {
            args.extend(["--model".to_string(), model.clone()]);
        }
        if let Some(harness_session_id) = &resume_harness_session_id {
            args.extend(["--resume".to_string(), harness_session_id.clone()]);
        }
        if let Some(system_prompt) = &input.system_prompt {
            let flag = if input.system_prompt_mode == "replace" {
                "--system-prompt"
            } else {
                "--append-system-prompt"
            };
            args.extend([flag.to_string(), system_prompt.clone()]);
        }

        // Explicitly load the project-scoped MCP config. The runner writes MCP
        // server definitions to `<cwd>/.mcp.json` (see runner::write_mcp_json)
        // and sets `enableAllProjectMcpServers: true` in `.claude/settings.json`
        // to auto-approve them. That approval path is unreliable in headless
        // `-p` mode: the project servers stay stuck in "pending approval"
        // (`claude mcp list` shows ⏸), so they expose no tools and the agent
        // reports "no MCP tools". Servers passed on the command line via
        // `--mcp-config` are treated as explicitly trusted and skip the project
        // approval flow, and `--strict-mcp-config` makes the CLI use ONLY this
        // file (the sole MCP source in a sandbox), eliminating the leftover
        // pending project entry. Only pass these when the file exists so
        // MCP-less sandboxes don't fail on a missing config path.
        let mcp_config_path = cwd.join(".mcp.json");
        if mcp_config_path.exists() {
            args.extend([
                "--mcp-config".to_string(),
                mcp_config_path.to_string_lossy().into_owned(),
                "--strict-mcp-config".to_string(),
            ]);
        }

        let mut cmd = Command::new("claude");
        cmd.args(&args)
            .current_dir(cwd)
            .env("HOME", cwd.to_string_lossy().to_string())
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        for (k, v) in &input.env {
            cmd.env(k, v);
        }
        // JoySafeter controls sandbox egress. Claude Code family runtimes must not
        // emit Anthropic first-party background HTTPS requests through the
        // HTTP-only egress bridge before the model request starts.
        cmd.env("DISABLE_TELEMETRY", "1")
            .env("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1");

        let mut child = cmd
            .spawn()
            .map_err(|e| HarnessError::StartFailed(e.to_string()))?;

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| HarnessError::StartFailed("failed to open stdin".into()))?;
        let shared_stdin: SharedStdin = Arc::new(Mutex::new(Some(stdin)));

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| HarnessError::StartFailed("failed to open stdout".into()))?;

        let current_turn: Arc<Mutex<Option<TurnState>>> = Arc::new(Mutex::new(None));
        let last_harness_session_id: Arc<std::sync::Mutex<Option<String>>> =
            Arc::new(std::sync::Mutex::new(resume_harness_session_id));

        let reader_current_turn = current_turn.clone();
        let reader_last_harness_session_id = last_harness_session_id.clone();
        let reader_handle = tokio::spawn(async move {
            persistent_claude_reader(stdout, reader_current_turn, reader_last_harness_session_id)
                .await;
        });

        info!("Started persistent claude process");

        *guard = Some(PersistentClaude {
            stdin: shared_stdin,
            reader_handle,
            current_turn,
            child,
            config_fingerprint: fp,
            last_harness_session_id,
        });

        Ok(())
    }
}

impl Drop for ClaudeAdapter {
    fn drop(&mut self) {
        let session = self.session.clone();
        tokio::spawn(async move {
            let mut guard = session.lock().await;
            if let Some(ref mut s) = *guard {
                // Try graceful end_session, then force kill
                let msg = serde_json::json!({
                    "type": "control_request",
                    "request_id": "shutdown",
                    "request": { "subtype": "end_session" }
                });
                {
                    let mut stdin_guard = s.stdin.lock().await;
                    if let Some(ref mut stdin) = *stdin_guard {
                        let _ = stdin.write_all(format!("{}\n", msg).as_bytes()).await;
                        let _ = stdin.flush().await;
                    }
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
                let _ = s.child.start_kill();
            }
            *guard = None;
        });
    }
}

// ---------------------------------------------------------------------------
// HarnessAdapter implementation
// ---------------------------------------------------------------------------

#[async_trait]
impl HarnessAdapter for ClaudeAdapter {
    async fn start(&self, input: HarnessInput, cwd: &Path) -> Result<RunningHarness, HarnessError> {
        crate::claude_project_config::prepare_claude_project_config(
            cwd,
            &input.mcp_configs,
            &input.custom_tools,
            &input.tool_policy,
        )
        .await?;
        self.ensure_session(&input, cwd).await?;

        let start = Instant::now();
        let (event_tx, event_rx) = mpsc::channel(256);
        let (result_tx, result_rx) = oneshot::channel();

        let guard = self.session.lock().await;
        let session = guard
            .as_ref()
            .ok_or_else(|| HarnessError::StartFailed("session disappeared after ensure".into()))?;

        let (td_tx, td_rx) = oneshot::channel::<bool>();
        let harness_session_id = Arc::new(std::sync::Mutex::new(None::<String>));
        {
            let mut ct = session.current_turn.lock().await;
            *ct = Some(TurnState {
                event_tx,
                turn_done_tx: Some(td_tx),
                usage: Arc::new(std::sync::Mutex::new(TokenUsage::default())),
                output: Arc::new(std::sync::Mutex::new(String::new())),
                error: Arc::new(std::sync::Mutex::new(None)),
                harness_session_id: harness_session_id.clone(),
                call_id_to_tool: Arc::new(std::sync::Mutex::new(HashMap::new())),
            });
        }

        // Inject prompt via stdin
        let stdin = session.stdin.clone();
        let prompt = input.prompt.clone();
        tokio::spawn(async move {
            let input_msg = build_live_protocol_message(&prompt).unwrap_or_else(|| {
                serde_json::json!({
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}]
                    }
                })
            });
            let mut guard = stdin.lock().await;
            if let Some(ref mut stdin) = *guard {
                let _ = stdin.write_all(format!("{}\n", input_msg).as_bytes()).await;
                let _ = stdin.flush().await;
            }
        });

        let current_turn = session.current_turn.clone();
        let last_harness_session_id = session.last_harness_session_id.clone();
        let shared_stdin_for_harness = session.stdin.clone();
        drop(guard);

        // Spawn completion task: wait for turn_done, then assemble HarnessResult
        tokio::spawn(async move {
            let aborted = td_rx.await.unwrap_or(true);

            let (final_output, final_usage, final_error, final_harness_session_id) = {
                let ct = current_turn.lock().await;
                if let Some(ref turn) = *ct {
                    (
                        turn.output.lock().unwrap().clone(),
                        turn.usage.lock().unwrap().clone(),
                        turn.error.lock().unwrap().clone(),
                        turn.harness_session_id.lock().unwrap().clone(),
                    )
                } else {
                    (String::new(), TokenUsage::default(), None, None)
                }
            };

            if final_harness_session_id.is_some() {
                *last_harness_session_id.lock().unwrap() = final_harness_session_id.clone();
            }

            {
                let mut ct = current_turn.lock().await;
                *ct = None;
            }

            let (status, error) = crate::finish_turn(aborted, final_error);

            let _ = result_tx.send(HarnessResult {
                status,
                output: final_output,
                error,
                harness_session_id: final_harness_session_id,
                usage: final_usage,
                duration: start.elapsed(),
            });
        });

        Ok(RunningHarness {
            events: event_rx,
            result: result_rx,
            child: None,
            input: Some(Box::new(shared_stdin_for_harness)),
        })
    }

    async fn cancel(&self, _harness: &mut RunningHarness) -> Result<(), HarnessError> {
        let guard = self.session.lock().await;
        if let Some(ref session) = *guard {
            // Send interrupt to claude via stdin
            let rid = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis())
                .unwrap_or(0);
            let msg = serde_json::json!({
                "type": "control_request",
                "request_id": format!("cancel_{rid}"),
                "request": { "subtype": "interrupt" }
            });
            {
                let mut stdin_guard = session.stdin.lock().await;
                if let Some(ref mut stdin) = *stdin_guard {
                    let _ = stdin.write_all(format!("{}\n", msg).as_bytes()).await;
                    let _ = stdin.flush().await;
                }
            }
            // Signal turn as aborted
            let mut ct = session.current_turn.lock().await;
            if let Some(ref mut turn) = *ct {
                if let Some(tx) = turn.turn_done_tx.take() {
                    let _ = tx.send(true);
                }
            }
        }
        Ok(())
    }

    async fn send_input(
        &self,
        harness: &mut RunningHarness,
        content: String,
    ) -> Result<(), HarnessError> {
        let Some(any) = harness.input.as_ref() else {
            return Err(HarnessError::UnsupportedInput);
        };
        let Some(shared_stdin) = any.downcast_ref::<SharedStdin>() else {
            return Err(HarnessError::UnsupportedInput);
        };

        let mut guard = shared_stdin.lock().await;
        let Some(stdin) = guard.as_mut() else {
            return Err(HarnessError::StartFailed("stdin closed".into()));
        };

        if let Some(msg) = build_live_protocol_message(&content) {
            stdin.write_all(format!("{}\n", msg).as_bytes()).await?;
            stdin.flush().await?;
            return Ok(());
        }

        let input_msg = serde_json::json!({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": content}]
            }
        });
        stdin
            .write_all(format!("{}\n", input_msg).as_bytes())
            .await?;
        stdin.flush().await?;
        Ok(())
    }

    fn provider(&self) -> &str {
        "claude"
    }

    async fn is_available(&self) -> bool {
        which::which("claude").is_ok()
    }
}

// ---------------------------------------------------------------------------
// Live input protocol translation (unchanged)
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum LiveInputPayload {
    ToolConfirmation {
        tool_use_call_id: String,
        approved: bool,
        #[serde(default)]
        deny_message: Option<String>,
    },
    CustomToolResult {
        tool_use_call_id: String,
        content: String,
    },
    Interrupt,
}

fn build_live_protocol_message(content: &str) -> Option<serde_json::Value> {
    let live_raw = content.strip_prefix(LIVE_INPUT_PREFIX)?;
    let payload = serde_json::from_str::<LiveInputPayload>(live_raw).ok()?;
    match payload {
        LiveInputPayload::ToolConfirmation {
            tool_use_call_id,
            approved,
            deny_message,
        } => {
            let request_id = tool_use_call_id.clone();
            if approved {
                Some(serde_json::json!({
                    "type": "control_response",
                    "response": {
                        "subtype": "success",
                        "request_id": request_id,
                        "response": {
                            "behavior": "allow",
                            "updatedInput": {}
                        }
                    }
                }))
            } else {
                let message = deny_message.unwrap_or_else(|| "denied by user".to_string());
                Some(serde_json::json!({
                    "type": "control_response",
                    "response": {
                        "subtype": "success",
                        "request_id": request_id,
                        "response": {
                            "behavior": "deny",
                            "message": message
                        }
                    }
                }))
            }
        }
        LiveInputPayload::CustomToolResult {
            tool_use_call_id,
            content,
        } => Some(serde_json::json!({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_call_id,
                    "content": content,
                }]
            }
        })),
        LiveInputPayload::Interrupt => {
            let rid = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis())
                .unwrap_or(0);
            Some(serde_json::json!({
                "type": "control_request",
                "request_id": format!("interrupt_{rid}"),
                "request": { "subtype": "interrupt" }
            }))
        }
    }
}

// ---------------------------------------------------------------------------
// Claude NDJSON message types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct ClaudeMessage {
    #[serde(rename = "type")]
    msg_type: String,
    #[serde(default)]
    message: Option<serde_json::Value>,
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    result: Option<String>,
    #[allow(dead_code)]
    #[serde(default)]
    error: Option<String>,
    #[serde(default)]
    subtype: Option<String>,
    #[serde(default)]
    level: Option<String>,
    #[serde(default)]
    request_id: Option<String>,
    #[serde(default)]
    request: Option<serde_json::Value>,
    // ---- system/task_* SDK events (background sub-agents) ----
    #[serde(default)]
    task_id: Option<String>,
    #[serde(default)]
    tool_use_id: Option<String>,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    summary: Option<String>,
    #[serde(default)]
    output_file: Option<String>,
    #[serde(default)]
    last_tool_name: Option<String>,
    #[serde(default)]
    usage: Option<TaskUsage>,
    /// Raw JSON for fields not captured above (e.g. result.usage,
    /// result.modelUsage). Populated post-deser; not from serde.
    #[serde(skip)]
    raw: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct TaskUsage {
    #[serde(default)]
    total_tokens: Option<u64>,
    #[serde(default)]
    tool_uses: Option<u64>,
    #[serde(default)]
    duration_ms: Option<u64>,
}

// ---------------------------------------------------------------------------
// Persistent stdout reader — survives across turns
// ---------------------------------------------------------------------------

async fn persistent_claude_reader(
    stdout: tokio::process::ChildStdout,
    current_turn: Arc<Mutex<Option<TurnState>>>,
    last_harness_session_id: Arc<std::sync::Mutex<Option<String>>>,
) {
    let reader = BufReader::new(stdout);
    let mut lines = reader.lines();

    while let Ok(Some(line)) = lines.next_line().await {
        if line.trim().is_empty() {
            continue;
        }

        // Parse twice: once into the strongly-typed struct, once as a raw
        // Value so handlers can read fields the struct doesn't model (e.g.
        // `result.usage`, `result.modelUsage`).
        let raw_value: Option<serde_json::Value> = serde_json::from_str(&line).ok();
        let mut msg: ClaudeMessage = match serde_json::from_str(&line) {
            Ok(m) => m,
            Err(_) => continue,
        };
        msg.raw = raw_value;

        let turn_refs = {
            let guard = current_turn.lock().await;
            guard.as_ref().map(|turn| {
                (
                    turn.event_tx.clone(),
                    turn.usage.clone(),
                    turn.output.clone(),
                    turn.error.clone(),
                    turn.harness_session_id.clone(),
                    turn.call_id_to_tool.clone(),
                )
            })
        };

        let Some((event_tx, usage, output, turn_error, harness_session_id, call_id_to_tool)) =
            turn_refs
        else {
            continue;
        };

        match msg.msg_type.as_str() {
            "assistant" => {
                if let Some(message) = &msg.message {
                    let model_name = message
                        .get("model")
                        .and_then(|m| m.as_str())
                        .unwrap_or("unknown")
                        .to_string();

                    if let Some(content) = message.get("content").and_then(|c| c.as_array()) {
                        for block in content {
                            let block_type =
                                block.get("type").and_then(|t| t.as_str()).unwrap_or("");
                            match block_type {
                                "text" => {
                                    if let Some(text) = block.get("text").and_then(|t| t.as_str()) {
                                        output.lock().unwrap().push_str(text);
                                        let _ = event_tx
                                            .send(HarnessEvent::Text {
                                                content: text.to_string(),
                                            })
                                            .await;
                                    }
                                }
                                "thinking" => {
                                    if let Some(text) =
                                        block.get("thinking").and_then(|t| t.as_str())
                                    {
                                        let _ = event_tx
                                            .send(HarnessEvent::Thinking {
                                                content: text.to_string(),
                                            })
                                            .await;
                                    }
                                }
                                "tool_use" => {
                                    let tool = block
                                        .get("name")
                                        .and_then(|n| n.as_str())
                                        .unwrap_or("")
                                        .to_string();
                                    let call_id = block
                                        .get("id")
                                        .and_then(|i| i.as_str())
                                        .unwrap_or("")
                                        .to_string();
                                    let input = block
                                        .get("input")
                                        .cloned()
                                        .unwrap_or(serde_json::Value::Null);
                                    call_id_to_tool
                                        .lock()
                                        .unwrap()
                                        .insert(call_id.clone(), tool.clone());
                                    let _ = event_tx
                                        .send(HarnessEvent::ToolUse {
                                            tool,
                                            call_id,
                                            input,
                                            is_control_request: false,
                                        })
                                        .await;
                                }
                                _ => {}
                            }
                        }
                    }

                    // Track the latest usage snapshot from this turn's assistant
                    // messages. claude-code's stream-json sends `usage` on each
                    // incremental `assistant` message and the value is a running
                    // *cumulative total* for the turn — NOT a per-chunk delta.
                    // We previously added each value, which double/triple-counted
                    // and the user saw `output_tokens: 4` because we'd captured
                    // an early streaming snapshot. The authoritative final value
                    // is in the `result` message; here we just keep the latest
                    // snapshot as the running view, replaced (not added).
                    if let Some(msg_usage) = message.get("usage") {
                        let input_tokens = msg_usage
                            .get("input_tokens")
                            .and_then(|v| v.as_u64())
                            .unwrap_or(0);
                        let output_tokens = msg_usage
                            .get("output_tokens")
                            .and_then(|v| v.as_u64())
                            .unwrap_or(0);
                        let cache_read = msg_usage
                            .get("cache_read_input_tokens")
                            .and_then(|v| v.as_u64())
                            .unwrap_or(0);
                        let cache_write = msg_usage
                            .get("cache_creation_input_tokens")
                            .and_then(|v| v.as_u64())
                            .unwrap_or(0);

                        // Overwrite (not accumulate) the running snapshot.
                        {
                            let mut u = usage.lock().unwrap();
                            u.input_tokens = input_tokens;
                            u.output_tokens = output_tokens;
                            u.cache_read_tokens = cache_read;
                            u.cache_write_tokens = cache_write;

                            let entry = u
                                .by_model
                                .entry(model_name.clone())
                                .or_insert_with(ModelUsage::default);
                            entry.input_tokens = input_tokens;
                            entry.output_tokens = output_tokens;
                            entry.cache_read_tokens = cache_read;
                            entry.cache_write_tokens = cache_write;
                        }

                        // Only emit ModelRequestStart from streaming chunks —
                        // the authoritative ModelRequestEnd is emitted from the
                        // `result` message below with the final usage.
                        let _ = event_tx
                            .send(HarnessEvent::ModelRequestStart {
                                model: model_name.clone(),
                            })
                            .await;
                    }
                }
            }
            "user" => {
                if let Some(message) = &msg.message {
                    if let Some(content) = message.get("content").and_then(|c| c.as_array()) {
                        for block in content {
                            if block.get("type").and_then(|t| t.as_str()) == Some("tool_result") {
                                let call_id = block
                                    .get("tool_use_id")
                                    .and_then(|i| i.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let tool_output = block
                                    .get("content")
                                    .and_then(|c| c.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let tool = call_id_to_tool
                                    .lock()
                                    .unwrap()
                                    .get(&call_id)
                                    .cloned()
                                    .unwrap_or_default();
                                let _ = event_tx
                                    .send(HarnessEvent::ToolResult {
                                        tool,
                                        call_id,
                                        output: tool_output,
                                    })
                                    .await;
                            }
                        }
                    }
                }
            }
            "system" => {
                if let Some(sid) = &msg.session_id {
                    *harness_session_id.lock().unwrap() = Some(sid.clone());
                    *last_harness_session_id.lock().unwrap() = Some(sid.clone());
                }
                // Background sub-agent lifecycle SDK events (task_started /
                // task_progress / task_notification) carry rich payload — extract
                // them into a structured HarnessEvent so the orchestrator sees
                // sub-agent completion, output_file path, and summary.
                let subtype = msg.subtype.as_deref().unwrap_or("");
                let phase = match subtype {
                    "task_started" => Some("started"),
                    "task_progress" => Some("progress"),
                    "task_notification" => {
                        // status field discriminates terminal phase
                        match msg.status.as_deref() {
                            Some("failed") => Some("failed"),
                            Some("stopped") | Some("killed") => Some("stopped"),
                            _ => Some("completed"),
                        }
                    }
                    _ => None,
                };

                if let Some(phase) = phase {
                    if let Some(subagent_task_id) = msg.task_id.clone() {
                        let (total_tokens, tool_uses, duration_ms) = match msg.usage {
                            Some(u) => (u.total_tokens, u.tool_uses, u.duration_ms),
                            None => (None, None, None),
                        };
                        let _ = event_tx
                            .send(HarnessEvent::TaskNotification {
                                phase: phase.to_string(),
                                subagent_task_id,
                                tool_use_id: msg.tool_use_id,
                                description: msg.description,
                                status: msg.status,
                                summary: msg.summary,
                                result: None, // SDK event doesn't carry <result>; orchestrator can read output_file
                                output_file: msg.output_file,
                                last_tool_name: msg.last_tool_name,
                                total_tokens,
                                tool_uses,
                                duration_ms,
                            })
                            .await;
                    }
                } else if let Some(subtype) = &msg.subtype {
                    // Non-task system events (e.g. init, session_state_changed)
                    // continue to flow through Status as before.
                    let _ = event_tx
                        .send(HarnessEvent::Status {
                            state: subtype.clone(),
                        })
                        .await;
                }
            }
            "control_request" => {
                let Some(request_id) = msg.request_id else {
                    continue;
                };
                let Some(request) = msg.request else {
                    continue;
                };
                if request.get("subtype").and_then(|v| v.as_str()) != Some("can_use_tool") {
                    continue;
                }
                let tool = request
                    .get("tool_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let input = request
                    .get("input")
                    .cloned()
                    .unwrap_or(serde_json::Value::Null);
                let _ = event_tx
                    .send(HarnessEvent::ToolUse {
                        tool,
                        call_id: request_id,
                        input,
                        is_control_request: true,
                    })
                    .await;
            }
            "result" => {
                if let Some(text) = &msg.result {
                    *output.lock().unwrap() = text.clone();
                }
                if let Some(error_message) = msg.raw.as_ref().and_then(crate::sdk_result_error) {
                    *turn_error.lock().unwrap() = Some(error_message.clone());
                    let _ = event_tx
                        .send(HarnessEvent::Error {
                            message: error_message,
                        })
                        .await;
                }

                // Final, authoritative usage for the turn. claude-code's
                // `result` message carries `usage` (the final aggregate) and
                // optionally `modelUsage` (per-model breakdown for multi-model
                // sub-agents). Streaming `assistant` messages only carry
                // running snapshots so we waited for this final value to emit
                // ModelRequestEnd.
                let raw = msg.raw.as_ref();
                let result_usage = raw.and_then(|r| r.get("usage"));
                let model_usage = raw
                    .and_then(|r| r.get("modelUsage"))
                    .and_then(|m| m.as_object());

                // Helper to pull a u64 field with both snake/kebab fallbacks.
                fn pull(v: Option<&serde_json::Value>, key: &str) -> u64 {
                    v.and_then(|u| u.get(key))
                        .and_then(|x| x.as_u64())
                        .unwrap_or(0)
                }

                if let Some(usage_val) = result_usage {
                    let input_tokens = pull(Some(usage_val), "input_tokens");
                    let output_tokens = pull(Some(usage_val), "output_tokens");
                    let cache_read = pull(Some(usage_val), "cache_read_input_tokens");
                    let cache_write = pull(Some(usage_val), "cache_creation_input_tokens");

                    // Overwrite the running snapshot with the final values.
                    {
                        let mut u = usage.lock().unwrap();
                        u.input_tokens = input_tokens;
                        u.output_tokens = output_tokens;
                        u.cache_read_tokens = cache_read;
                        u.cache_write_tokens = cache_write;

                        // If modelUsage is present, rebuild the per-model map
                        // from scratch so the totals stay consistent. Otherwise
                        // attribute everything to the last-seen model below.
                        if let Some(entries) = model_usage {
                            u.by_model.clear();
                            for (model_name, mu) in entries {
                                let entry = u
                                    .by_model
                                    .entry(model_name.clone())
                                    .or_insert_with(ModelUsage::default);
                                entry.input_tokens = pull(Some(mu), "inputTokens")
                                    .max(pull(Some(mu), "input_tokens"));
                                entry.output_tokens = pull(Some(mu), "outputTokens")
                                    .max(pull(Some(mu), "output_tokens"));
                                entry.cache_read_tokens = pull(Some(mu), "cachedInputTokens")
                                    .max(pull(Some(mu), "cache_read_input_tokens"));
                                entry.cache_write_tokens = pull(Some(mu), "uncachedInputTokens")
                                    .max(pull(Some(mu), "cache_creation_input_tokens"));
                            }
                        }
                    }

                    // Authoritative ModelRequestEnd for this turn. Use whichever
                    // model name is known — either from result.modelUsage (first
                    // key) or the last assistant-message model snapshot we kept.
                    let final_model_name = model_usage
                        .and_then(|m| m.keys().next().cloned())
                        .or_else(|| {
                            let u = usage.lock().unwrap();
                            u.by_model.keys().next().cloned()
                        })
                        .unwrap_or_else(|| "unknown".to_string());

                    let _ = event_tx
                        .send(HarnessEvent::ModelRequestEnd {
                            model: final_model_name,
                            input_tokens,
                            output_tokens,
                            cache_read_tokens: cache_read,
                            cache_write_tokens: cache_write,
                        })
                        .await;
                }

                // Signal turn completion — do NOT break the reader loop
                let mut guard = current_turn.lock().await;
                if let Some(ref mut turn) = *guard {
                    if let Some(tx) = turn.turn_done_tx.take() {
                        let _ = tx.send(false);
                    }
                }
            }
            "log" => {
                let level = msg.level.unwrap_or_else(|| "info".into());
                if let Some(message) = &msg.message {
                    let text = message.as_str().unwrap_or("").to_string();
                    let _ = event_tx
                        .send(HarnessEvent::Log {
                            level,
                            message: text,
                        })
                        .await;
                }
            }
            _ => {}
        }
    }

    // stdout closed = process exited; notify current turn if active
    info!("Claude stdout reader exiting (process closed stdout)");
    let mut guard = current_turn.lock().await;
    if let Some(ref mut turn) = *guard {
        if let Some(tx) = turn.turn_done_tx.take() {
            let _ = tx.send(true);
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use joysafeter_types::tool_policy::{ToolDecision, ToolPolicy, ToolRule};

    fn allow_policy() -> ToolPolicy {
        ToolPolicy::new(ToolDecision::Allow, vec![]).expect("valid allow policy")
    }

    #[test]
    fn result_error_message_uses_sdk_error_payload() {
        let raw = serde_json::json!({
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": true,
            "errors": ["Provider returned 404: route_not_found"]
        });
        assert_eq!(
            crate::sdk_result_error(&raw).as_deref(),
            Some("Provider returned 404: route_not_found")
        );
    }

    #[test]
    fn live_input_tool_confirmation_maps_to_control_response() {
        let raw = "__joysafeter_input_v1__:{\"type\":\"tool_confirmation\",\"tool_use_call_id\":\"req_1\",\"approved\":true}";
        let msg = build_live_protocol_message(raw).expect("expected structured message");
        assert_eq!(
            msg.get("type").and_then(|v| v.as_str()),
            Some("control_response")
        );
        assert_eq!(
            msg.pointer("/response/request_id").and_then(|v| v.as_str()),
            Some("req_1")
        );
        assert_eq!(
            msg.pointer("/response/response/behavior")
                .and_then(|v| v.as_str()),
            Some("allow")
        );
    }

    #[test]
    fn live_input_custom_tool_result_maps_to_tool_result_message() {
        let raw = "__joysafeter_input_v1__:{\"type\":\"custom_tool_result\",\"tool_use_call_id\":\"req_2\",\"content\":\"ok\"}";
        let msg = build_live_protocol_message(raw).expect("expected structured message");
        assert_eq!(msg.get("type").and_then(|v| v.as_str()), Some("user"));
        assert_eq!(
            msg.pointer("/message/content/0/type")
                .and_then(|v| v.as_str()),
            Some("tool_result")
        );
        assert_eq!(
            msg.pointer("/message/content/0/tool_use_id")
                .and_then(|v| v.as_str()),
            Some("req_2")
        );
    }

    #[test]
    fn live_input_interrupt_maps_to_control_request() {
        let raw = "__joysafeter_input_v1__:{\"type\":\"interrupt\"}";
        let msg = build_live_protocol_message(raw).expect("expected structured message");
        assert_eq!(
            msg.get("type").and_then(|v| v.as_str()),
            Some("control_request")
        );
        assert_eq!(
            msg.pointer("/request/subtype").and_then(|v| v.as_str()),
            Some("interrupt")
        );
    }

    #[test]
    fn compute_fingerprint_is_stable() {
        let input = HarnessInput {
            prompt: "hello".into(),
            system_prompt: Some("sys".into()),
            system_prompt_mode: "append".into(),
            harness_session_id: None,
            model: Some("opus".into()),
            max_turns: Some(10),
            timeout: Duration::from_secs(60),
            env: HashMap::from([("A".into(), "1".into())]),
            mcp_configs: vec![],
            custom_tools: vec![],
            tool_policy: allow_policy(),
        };
        let fp1 = ClaudeAdapter::compute_fingerprint(&input);
        let fp2 = ClaudeAdapter::compute_fingerprint(&input);
        assert_eq!(fp1, fp2);
    }

    #[test]
    fn compute_fingerprint_ignores_prompt_and_session_id() {
        let input1 = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
            system_prompt_mode: "append".into(),
            harness_session_id: Some("abc".into()),
            model: Some("opus".into()),
            max_turns: Some(5),
            timeout: Duration::from_secs(30),
            env: HashMap::new(),
            mcp_configs: vec![],
            custom_tools: vec![],
            tool_policy: allow_policy(),
        };
        let input2 = HarnessInput {
            prompt: "different prompt".into(),
            system_prompt: None,
            system_prompt_mode: "append".into(),
            harness_session_id: Some("xyz".into()),
            model: Some("opus".into()),
            max_turns: Some(100),
            timeout: Duration::from_secs(999),
            env: HashMap::new(),
            mcp_configs: vec![],
            custom_tools: vec![],
            tool_policy: allow_policy(),
        };
        assert_eq!(
            ClaudeAdapter::compute_fingerprint(&input1),
            ClaudeAdapter::compute_fingerprint(&input2)
        );
    }

    #[test]
    fn compute_fingerprint_differs_on_model_change() {
        let input1 = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
            system_prompt_mode: "append".into(),
            harness_session_id: None,
            model: Some("opus".into()),
            max_turns: None,
            timeout: Duration::from_secs(60),
            env: HashMap::new(),
            mcp_configs: vec![],
            custom_tools: vec![],
            tool_policy: allow_policy(),
        };
        let input2 = HarnessInput {
            model: Some("sonnet".into()),
            ..input1.clone()
        };
        assert_ne!(
            ClaudeAdapter::compute_fingerprint(&input1),
            ClaudeAdapter::compute_fingerprint(&input2)
        );
    }

    #[test]
    fn compute_fingerprint_differs_on_mcp_and_tool_config_change() {
        let input1 = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
            system_prompt_mode: "append".into(),
            harness_session_id: None,
            model: Some("opus".into()),
            max_turns: None,
            timeout: Duration::from_secs(60),
            env: HashMap::new(),
            mcp_configs: vec![],
            custom_tools: vec![],
            tool_policy: ToolPolicy::new(
                ToolDecision::Allow,
                vec![ToolRule::builtin("Read", ToolDecision::Allow).expect("valid rule")],
            )
            .expect("valid policy"),
        };
        let input2 = HarnessInput {
            mcp_configs: vec![joysafeter_types::agent::McpServerConfig::StreamableHttp {
                name: "legal-knowledge".into(),
                url: "https://ai-legal-test.jd.com/legal-mcp/mcp".into(),
            }],
            tool_policy: ToolPolicy::new(
                ToolDecision::Allow,
                vec![
                    ToolRule::builtin("Read", ToolDecision::Allow).expect("valid rule"),
                    ToolRule::mcp_server("legal-knowledge", ToolDecision::Allow)
                        .expect("valid rule"),
                ],
            )
            .expect("valid policy"),
            ..input1.clone()
        };
        assert_ne!(
            ClaudeAdapter::compute_fingerprint(&input1),
            ClaudeAdapter::compute_fingerprint(&input2)
        );
    }
}
