use async_trait::async_trait;
use joysafeter_types::harness::{
    HarnessAdapter, HarnessError, HarnessEvent, HarnessInput, HarnessResult, HarnessResultStatus,
    RunningHarness,
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
    session_id: Arc<std::sync::Mutex<Option<String>>>,
    call_id_to_tool: Arc<std::sync::Mutex<HashMap<String, String>>>,
}

// ---------------------------------------------------------------------------
// Persistent subprocess state
// ---------------------------------------------------------------------------

struct PersistentNative {
    stdin: SharedStdin,
    #[allow(dead_code)]
    reader_handle: tokio::task::JoinHandle<()>,
    current_turn: Arc<Mutex<Option<TurnState>>>,
    child: tokio::process::Child,
    config_fingerprint: u64,
    last_session_id: Arc<std::sync::Mutex<Option<String>>>,
}

// ---------------------------------------------------------------------------
// NativeAdapter — now stateful, holds a persistent session
// ---------------------------------------------------------------------------

pub struct NativeAdapter {
    session: Arc<Mutex<Option<PersistentNative>>>,
}

impl Default for NativeAdapter {
    fn default() -> Self {
        Self::new()
    }
}

impl NativeAdapter {
    pub fn new() -> Self {
        Self {
            session: Arc::new(Mutex::new(None)),
        }
    }

    fn compute_fingerprint(input: &HarnessInput) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        input.model.hash(&mut hasher);
        input.permission_mode.hash(&mut hasher);
        input.system_prompt.hash(&mut hasher);
        let mut env_keys: Vec<_> = input.env.keys().collect();
        env_keys.sort();
        for k in &env_keys {
            k.hash(&mut hasher);
            input.env[*k].hash(&mut hasher);
        }
        let mut secret_keys: Vec<_> = input.secrets.keys().collect();
        secret_keys.sort();
        for k in &secret_keys {
            k.hash(&mut hasher);
            input.secrets[*k].hash(&mut hasher);
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
                    info!("Config fingerprint changed, restarting native process");
                    false
                }
                Ok(Some(status)) => {
                    warn!(exit_code = ?status.code(), "Native process exited, restarting");
                    false
                }
                Err(e) => {
                    warn!(error = %e, "Failed to check native process status, restarting");
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

        // Determine session_id for --resume: prefer input.session_id (from orchestrator DB),
        // fall back to last_session_id from previous turn (for crash recovery within same adapter).
        let resume_session_id = input.session_id.clone();

        let mut args = vec![
            "-p".to_string(),
            "--output-format".to_string(),
            "stream-json".to_string(),
            "--input-format".to_string(),
            "stream-json".to_string(),
            "--verbose".to_string(),
            "--permission-mode".to_string(),
            input.permission_mode.clone(),
            "--permission-prompt-tool".to_string(),
            "stdio".to_string(),
        ];

        if let Some(model) = &input.model {
            args.extend(["--model".to_string(), model.clone()]);
        }
        if let Some(session_id) = &resume_session_id {
            args.extend(["--resume".to_string(), session_id.clone()]);
        }
        if let Some(system_prompt) = &input.system_prompt {
            let flag = if input.system_prompt_mode == "replace" {
                "--system-prompt"
            } else {
                "--append-system-prompt"
            };
            args.extend([flag.to_string(), system_prompt.clone()]);
        }

        let mut cmd = Command::new("ccb");
        cmd.args(&args)
            .current_dir(cwd)
            .env("HOME", cwd.to_string_lossy().to_string())
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        for (k, v) in &input.env {
            cmd.env(k, v);
        }
        for (k, v) in &input.secrets {
            cmd.env(k, v);
        }

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
        let last_session_id: Arc<std::sync::Mutex<Option<String>>> =
            Arc::new(std::sync::Mutex::new(resume_session_id));

        let reader_current_turn = current_turn.clone();
        let reader_last_session_id = last_session_id.clone();
        let reader_handle = tokio::spawn(async move {
            persistent_native_reader(stdout, reader_current_turn, reader_last_session_id).await;
        });

        info!("Started persistent native process");

        *guard = Some(PersistentNative {
            stdin: shared_stdin,
            reader_handle,
            current_turn,
            child,
            config_fingerprint: fp,
            last_session_id,
        });

        Ok(())
    }
}

impl Drop for NativeAdapter {
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
impl HarnessAdapter for NativeAdapter {
    async fn start(&self, input: HarnessInput, cwd: &Path) -> Result<RunningHarness, HarnessError> {
        self.ensure_session(&input, cwd).await?;

        let start = Instant::now();
        let (event_tx, event_rx) = mpsc::channel(256);
        let (result_tx, result_rx) = oneshot::channel();

        let guard = self.session.lock().await;
        let session = guard
            .as_ref()
            .ok_or_else(|| HarnessError::StartFailed("session disappeared after ensure".into()))?;

        let (td_tx, td_rx) = oneshot::channel::<bool>();
        let session_id_arc = Arc::new(std::sync::Mutex::new(None::<String>));
        {
            let mut ct = session.current_turn.lock().await;
            *ct = Some(TurnState {
                event_tx,
                turn_done_tx: Some(td_tx),
                usage: Arc::new(std::sync::Mutex::new(TokenUsage::default())),
                output: Arc::new(std::sync::Mutex::new(String::new())),
                session_id: session_id_arc.clone(),
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
        let last_session_id = session.last_session_id.clone();
        let shared_stdin_for_harness = session.stdin.clone();
        drop(guard);

        // Spawn completion task: wait for turn_done, then assemble HarnessResult
        tokio::spawn(async move {
            let aborted = td_rx.await.unwrap_or(true);

            let (final_output, final_usage, final_session_id) = {
                let ct = current_turn.lock().await;
                if let Some(ref turn) = *ct {
                    (
                        turn.output.lock().unwrap().clone(),
                        turn.usage.lock().unwrap().clone(),
                        turn.session_id.lock().unwrap().clone(),
                    )
                } else {
                    (String::new(), TokenUsage::default(), None)
                }
            };

            // Update last_session_id for crash recovery
            if final_session_id.is_some() {
                *last_session_id.lock().unwrap() = final_session_id.clone();
            }

            {
                let mut ct = current_turn.lock().await;
                *ct = None;
            }

            let status = if aborted {
                HarnessResultStatus::Aborted
            } else {
                HarnessResultStatus::Completed
            };

            let _ = result_tx.send(HarnessResult {
                status,
                output: final_output,
                error: None,
                session_id: final_session_id,
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
            // Send interrupt to native via stdin
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
        "native"
    }

    async fn is_available(&self) -> bool {
        which::which("ccb").is_ok()
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
// Native NDJSON message types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct NativeMessage {
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
}

// ---------------------------------------------------------------------------
// Persistent stdout reader — survives across turns
// ---------------------------------------------------------------------------

async fn persistent_native_reader(
    stdout: tokio::process::ChildStdout,
    current_turn: Arc<Mutex<Option<TurnState>>>,
    last_session_id: Arc<std::sync::Mutex<Option<String>>>,
) {
    let reader = BufReader::new(stdout);
    let mut lines = reader.lines();

    while let Ok(Some(line)) = lines.next_line().await {
        if line.trim().is_empty() {
            continue;
        }

        let msg: NativeMessage = match serde_json::from_str(&line) {
            Ok(m) => m,
            Err(_) => continue,
        };

        let turn_refs = {
            let guard = current_turn.lock().await;
            guard.as_ref().map(|turn| {
                (
                    turn.event_tx.clone(),
                    turn.usage.clone(),
                    turn.output.clone(),
                    turn.session_id.clone(),
                    turn.call_id_to_tool.clone(),
                )
            })
        };

        let Some((event_tx, usage, output, session_id, call_id_to_tool)) = turn_refs else {
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

                        {
                            let mut u = usage.lock().unwrap();
                            u.input_tokens += input_tokens;
                            u.output_tokens += output_tokens;
                            u.cache_read_tokens += cache_read;
                            u.cache_write_tokens += cache_write;

                            let entry = u
                                .by_model
                                .entry(model_name.clone())
                                .or_insert_with(ModelUsage::default);
                            entry.input_tokens += input_tokens;
                            entry.output_tokens += output_tokens;
                            entry.cache_read_tokens += cache_read;
                            entry.cache_write_tokens += cache_write;
                        }

                        let _ = event_tx
                            .send(HarnessEvent::ModelRequestStart {
                                model: model_name.clone(),
                            })
                            .await;
                        let _ = event_tx
                            .send(HarnessEvent::ModelRequestEnd {
                                model: model_name,
                                input_tokens,
                                output_tokens,
                                cache_read_tokens: cache_read,
                                cache_write_tokens: cache_write,
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
                if let Some(sid) = msg.session_id {
                    *session_id.lock().unwrap() = Some(sid.clone());
                    *last_session_id.lock().unwrap() = Some(sid);
                }
                if let Some(subtype) = &msg.subtype {
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
    info!("Native stdout reader exiting (process closed stdout)");
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
            session_id: None,
            model: Some("opus".into()),
            max_turns: Some(10),
            timeout: Duration::from_secs(60),
            env: HashMap::from([("A".into(), "1".into())]),
            secrets: HashMap::new(),
            mcp_configs: vec![],
            permission_mode: "bypassPermissions".into(),
            allowed_tools: vec![],
            ask_tools: vec![],
        };
        let fp1 = NativeAdapter::compute_fingerprint(&input);
        let fp2 = NativeAdapter::compute_fingerprint(&input);
        assert_eq!(fp1, fp2);
    }

    #[test]
    fn compute_fingerprint_ignores_prompt_and_session_id() {
        let input1 = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
            system_prompt_mode: "append".into(),
            session_id: Some("abc".into()),
            model: Some("opus".into()),
            max_turns: Some(5),
            timeout: Duration::from_secs(30),
            env: HashMap::new(),
            secrets: HashMap::new(),
            mcp_configs: vec![],
            permission_mode: "bypassPermissions".into(),
            allowed_tools: vec![],
            ask_tools: vec![],
        };
        let input2 = HarnessInput {
            prompt: "different prompt".into(),
            system_prompt: None,
            system_prompt_mode: "append".into(),
            session_id: Some("xyz".into()),
            model: Some("opus".into()),
            max_turns: Some(100),
            timeout: Duration::from_secs(999),
            env: HashMap::new(),
            secrets: HashMap::new(),
            mcp_configs: vec![],
            permission_mode: "bypassPermissions".into(),
            allowed_tools: vec![],
            ask_tools: vec![],
        };
        assert_eq!(
            NativeAdapter::compute_fingerprint(&input1),
            NativeAdapter::compute_fingerprint(&input2)
        );
    }

    #[test]
    fn compute_fingerprint_differs_on_model_change() {
        let input1 = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
            system_prompt_mode: "append".into(),
            session_id: None,
            model: Some("opus".into()),
            max_turns: None,
            timeout: Duration::from_secs(60),
            env: HashMap::new(),
            secrets: HashMap::new(),
            mcp_configs: vec![],
            permission_mode: "bypassPermissions".into(),
            allowed_tools: vec![],
            ask_tools: vec![],
        };
        let input2 = HarnessInput {
            model: Some("sonnet".into()),
            ..input1.clone()
        };
        assert_ne!(
            NativeAdapter::compute_fingerprint(&input1),
            NativeAdapter::compute_fingerprint(&input2)
        );
    }
}
