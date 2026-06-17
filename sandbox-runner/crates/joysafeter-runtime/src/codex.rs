use async_trait::async_trait;
use joysafeter_types::harness::{
    HarnessAdapter, HarnessError, HarnessEvent, HarnessInput, HarnessResult, HarnessResultStatus,
    RunningHarness,
};
use joysafeter_types::token_usage::TokenUsage;
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;
use std::time::Instant;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::sync::{mpsc, oneshot, Mutex};
use tracing::{debug, info, warn};

type SharedStdin = Arc<Mutex<Option<tokio::process::ChildStdin>>>;
type PendingMap = Arc<Mutex<HashMap<i64, oneshot::Sender<Result<Value, String>>>>>;

struct TurnState {
    event_tx: mpsc::Sender<HarnessEvent>,
    turn_done_tx: Option<oneshot::Sender<bool>>,
    usage: Arc<std::sync::Mutex<TokenUsage>>,
    output: Arc<std::sync::Mutex<String>>,
    call_id_to_tool: Arc<std::sync::Mutex<HashMap<String, String>>>,
    agent_message_text_by_id: Arc<std::sync::Mutex<HashMap<String, String>>>,
    model: String,
}

struct PersistentCodex {
    stdin: SharedStdin,
    next_id: Arc<AtomicI64>,
    pending: PendingMap,
    #[allow(dead_code)]
    reader_handle: tokio::task::JoinHandle<()>,
    current_turn: Arc<Mutex<Option<TurnState>>>,
    #[allow(dead_code)]
    notification_protocol: Arc<std::sync::Mutex<String>>,
    child: tokio::process::Child,
    thread_id: String,
    #[allow(dead_code)]
    cwd: String,
    last_usage: Arc<std::sync::Mutex<TokenUsage>>,
}

pub struct CodexAdapter {
    session: Arc<Mutex<Option<PersistentCodex>>>,
}

impl CodexAdapter {
    pub fn new() -> Self {
        Self {
            session: Arc::new(Mutex::new(None)),
        }
    }

    async fn ensure_session(&self, input: &HarnessInput, cwd: &Path) -> Result<(), HarnessError> {
        let mut guard = self.session.lock().await;

        let alive = if let Some(ref mut session) = *guard {
            match session.child.try_wait() {
                Ok(None) => true,
                _ => false,
            }
        } else {
            false
        };

        if alive {
            return Ok(());
        }

        // Drop old session if dead
        if guard.is_some() {
            info!("Codex process died, restarting");
            *guard = None;
        }

        let cwd_str = cwd.to_string_lossy().to_string();

        let mut cmd = Command::new("codex");
        cmd.args(["app-server", "--listen", "stdio://"])
            .current_dir(cwd)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null());

        for (k, v) in &input.env {
            cmd.env(k, v);
        }
        for (k, v) in &input.secrets {
            cmd.env(k, v);
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| HarnessError::StartFailed(format!("failed to spawn codex: {e}")))?;

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| HarnessError::StartFailed("failed to open stdin".into()))?;

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| HarnessError::StartFailed("failed to open stdout".into()))?;

        let stdin: SharedStdin = Arc::new(Mutex::new(Some(stdin)));
        let next_id = Arc::new(AtomicI64::new(1));
        let pending: PendingMap = Arc::new(Mutex::new(HashMap::new()));
        let current_turn: Arc<Mutex<Option<TurnState>>> = Arc::new(Mutex::new(None));
        let notification_protocol: Arc<std::sync::Mutex<String>> =
            Arc::new(std::sync::Mutex::new("unknown".into()));
        let last_usage: Arc<std::sync::Mutex<TokenUsage>> =
            Arc::new(std::sync::Mutex::new(TokenUsage::default()));

        let reader_pending = pending.clone();
        let reader_stdin = stdin.clone();
        let reader_current_turn = current_turn.clone();
        let reader_protocol = notification_protocol.clone();
        let reader_last_usage = last_usage.clone();

        let reader_handle = tokio::spawn(async move {
            let reader = BufReader::new(stdout);
            let mut lines = reader.lines();

            while let Ok(Some(line)) = lines.next_line().await {
                if line.trim().is_empty() {
                    continue;
                }

                let msg: RpcMessage = match serde_json::from_str(&line) {
                    Ok(m) => m,
                    Err(_) => {
                        debug!(line = %line, "Non-JSON line from codex");
                        continue;
                    }
                };

                let has_id = msg.id.as_ref().map(|v| !v.is_null()).unwrap_or(false);
                let has_result_or_error = msg.result.is_some() || msg.error.is_some();
                let has_method = msg.method.is_some();

                if has_id && has_result_or_error {
                    if let Some(Value::Number(n)) = &msg.id {
                        if let Some(id) = n.as_i64() {
                            let sender = {
                                let mut p = reader_pending.lock().await;
                                p.remove(&id)
                            };
                            if let Some(tx) = sender {
                                if let Some(err) = msg.error {
                                    let err_msg = err
                                        .get("message")
                                        .and_then(|m| m.as_str())
                                        .unwrap_or("unknown RPC error")
                                        .to_string();
                                    let _ = tx.send(Err(err_msg));
                                } else {
                                    let _ = tx.send(Ok(msg.result.unwrap_or(Value::Null)));
                                }
                            }
                        }
                    }
                } else if has_id && has_method {
                    let method = msg.method.as_deref().unwrap_or("");
                    let response_result = match method {
                        "item/commandExecution/requestApproval"
                        | "execCommandApproval"
                        | "item/fileChange/requestApproval"
                        | "applyPatchApproval" => serde_json::json!({"decision": "accept"}),
                        _ => serde_json::json!({}),
                    };

                    let response = serde_json::json!({
                        "jsonrpc": "2.0",
                        "id": msg.id,
                        "result": response_result,
                    });

                    let line = format!("{}\n", response);
                    let mut guard = reader_stdin.lock().await;
                    if let Some(ref mut stdin) = *guard {
                        let _ = stdin.write_all(line.as_bytes()).await;
                        let _ = stdin.flush().await;
                    }
                } else if has_method {
                    let method = msg.method.as_deref().unwrap_or("");
                    let params = msg.params.unwrap_or(Value::Null);
                    info!(method = %method, "Codex notification received");

                    let turn_refs = {
                        let turn_guard = reader_current_turn.lock().await;
                        turn_guard.as_ref().map(|turn| {
                            (
                                turn.event_tx.clone(),
                                turn.usage.clone(),
                                turn.output.clone(),
                                turn.call_id_to_tool.clone(),
                                turn.agent_message_text_by_id.clone(),
                                turn.model.clone(),
                            )
                        })
                    };

                    if let Some((
                        event_tx,
                        usage,
                        output,
                        call_id_to_tool,
                        agent_message_text_by_id,
                        model,
                    )) = turn_refs
                    {
                        handle_notification(
                            method,
                            &params,
                            &reader_protocol,
                            &event_tx,
                            &usage,
                            &output,
                            &call_id_to_tool,
                            &agent_message_text_by_id,
                            &reader_current_turn,
                            &model,
                        )
                        .await;
                    } else {
                        if method == "thread/tokenUsage/updated" {
                            replace_usage(&params, &reader_last_usage);
                            info!(method = %method, "Late tokenUsage update applied to session-level usage");
                        } else if method == "turn/completed" {
                            let turn = params.get("turn").unwrap_or(&params);
                            replace_usage(turn, &reader_last_usage);
                            debug!(method = %method, "Late turn/completed");
                        } else {
                            debug!(method = %method, "Notification received but no active turn");
                        }
                    }
                }
            }

            info!("Codex stdout reader exiting (process closed stdout)");
        });

        // initialize handshake
        let init_result = rpc_request(
            &stdin,
            &next_id,
            &pending,
            "initialize",
            serde_json::json!({
                "clientInfo": {
                    "name": "joysafeter-runner",
                    "title": "Agentd Runner",
                    "version": "0.1.0"
                },
                "capabilities": {
                    "experimentalApi": true
                }
            }),
        )
        .await;

        if let Err(e) = init_result {
            let _ = child.start_kill();
            return Err(HarnessError::StartFailed(format!(
                "codex initialize failed: {e}"
            )));
        }

        send_notification(&stdin, "initialized", Value::Null).await;

        // thread/start
        let thread_result = rpc_request(
            &stdin,
            &next_id,
            &pending,
            "thread/start",
            serde_json::json!({
                "model": input.model.as_deref(),
                "modelProvider": null,
                "profile": null,
                "cwd": cwd_str,
                "approvalPolicy": null,
                "sandbox": null,
                "config": null,
                "baseInstructions": null,
                "developerInstructions": input.system_prompt.as_deref(),
                "compactPrompt": null,
                "includeApplyPatchTool": null,
                "experimentalRawEvents": false,
                "persistExtendedHistory": true
            }),
        )
        .await;

        let thread_id = match thread_result {
            Ok(val) => val
                .get("thread")
                .and_then(|t| t.get("id"))
                .and_then(|id| id.as_str())
                .unwrap_or("")
                .to_string(),
            Err(e) => {
                let _ = child.start_kill();
                return Err(HarnessError::StartFailed(format!(
                    "codex thread/start failed: {e}"
                )));
            }
        };

        debug!(thread_id = %thread_id, "Codex thread started (persistent)");

        *guard = Some(PersistentCodex {
            stdin,
            next_id,
            pending,
            reader_handle,
            current_turn,
            notification_protocol,
            child,
            thread_id,
            cwd: cwd_str,
            last_usage,
        });

        Ok(())
    }
}

#[async_trait]
impl HarnessAdapter for CodexAdapter {
    async fn start(&self, input: HarnessInput, cwd: &Path) -> Result<RunningHarness, HarnessError> {
        self.ensure_session(&input, cwd).await?;

        let start = Instant::now();
        let (event_tx, event_rx) = mpsc::channel(256);
        let (result_tx, result_rx) = oneshot::channel();

        let guard = self.session.lock().await;
        let session = guard
            .as_ref()
            .ok_or_else(|| HarnessError::StartFailed("session disappeared after ensure".into()))?;

        let turn_state = TurnState {
            event_tx: event_tx.clone(),
            turn_done_tx: None,
            usage: Arc::new(std::sync::Mutex::new(TokenUsage::default())),
            output: Arc::new(std::sync::Mutex::new(String::new())),
            call_id_to_tool: Arc::new(std::sync::Mutex::new(HashMap::new())),
            agent_message_text_by_id: Arc::new(std::sync::Mutex::new(HashMap::new())),
            model: input.model.clone().unwrap_or_else(|| "codex".to_string()),
        };

        let (td_tx, td_rx) = oneshot::channel::<bool>();
        {
            let mut ct = session.current_turn.lock().await;
            *ct = Some(TurnState {
                turn_done_tx: Some(td_tx),
                ..turn_state
            });
        }

        let thread_id = session.thread_id.clone();
        let stdin = session.stdin.clone();
        let next_id = session.next_id.clone();
        let pending = session.pending.clone();
        let current_turn = session.current_turn.clone();
        let session_last_usage = session.last_usage.clone();
        // Reset session-level usage before each turn
        {
            let mut u = session_last_usage.lock().unwrap();
            *u = TokenUsage::default();
        }

        drop(guard);

        // turn/start
        let turn_result = rpc_request(
            &stdin,
            &next_id,
            &pending,
            "turn/start",
            serde_json::json!({
                "threadId": thread_id,
                "input": [{"type": "text", "text": input.prompt}]
            }),
        )
        .await;

        if let Err(e) = turn_result {
            let mut ct = current_turn.lock().await;
            *ct = None;
            return Err(HarnessError::StartFailed(format!(
                "codex turn/start failed: {e}"
            )));
        }

        let current_turn_for_completion = current_turn.clone();
        let last_usage_for_completion = session_last_usage.clone();
        tokio::spawn(async move {
            let aborted = match td_rx.await {
                Ok(aborted) => aborted,
                Err(_) => true,
            };

            // Wait briefly for late notifications (tokenUsage, turn/completed)
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;

            let (final_output, turn_usage) = {
                let ct = current_turn_for_completion.lock().await;
                if let Some(ref turn) = *ct {
                    let o = turn.output.lock().unwrap().clone();
                    let u = turn.usage.lock().unwrap().clone();
                    (o, u)
                } else {
                    (String::new(), TokenUsage::default())
                }
            };

            // Use turn-level usage if available, otherwise fall back to session-level late usage
            let final_usage = if turn_usage.input_tokens > 0 || turn_usage.output_tokens > 0 {
                turn_usage
            } else {
                last_usage_for_completion.lock().unwrap().clone()
            };

            {
                let mut ct = current_turn_for_completion.lock().await;
                *ct = None;
            }

            let duration = start.elapsed();
            let status = if aborted {
                HarnessResultStatus::Aborted
            } else {
                HarnessResultStatus::Completed
            };

            let _ = result_tx.send(HarnessResult {
                status,
                output: final_output,
                error: None,
                session_id: None,
                usage: final_usage,
                duration,
            });
        });

        Ok(RunningHarness {
            events: event_rx,
            result: result_rx,
            child: None,
            input: None,
        })
    }

    async fn cancel(&self, _harness: &mut RunningHarness) -> Result<(), HarnessError> {
        let guard = self.session.lock().await;
        if let Some(ref session) = *guard {
            let mut ct = session.current_turn.lock().await;
            if let Some(ref mut turn) = *ct {
                if let Some(tx) = turn.turn_done_tx.take() {
                    let _ = tx.send(true);
                }
            }
        }
        Ok(())
    }

    fn provider(&self) -> &str {
        "codex"
    }

    async fn is_available(&self) -> bool {
        which::which("codex").is_ok()
    }
}

impl Drop for CodexAdapter {
    fn drop(&mut self) {
        let session = self.session.clone();
        tokio::spawn(async move {
            let mut guard = session.lock().await;
            if let Some(ref mut s) = *guard {
                let _ = s.child.start_kill();
            }
            *guard = None;
        });
    }
}

#[derive(Debug, Deserialize)]
struct RpcMessage {
    #[serde(default)]
    id: Option<Value>,
    #[serde(default)]
    method: Option<String>,
    #[serde(default)]
    result: Option<Value>,
    #[serde(default)]
    error: Option<Value>,
    #[serde(default)]
    params: Option<Value>,
}

async fn rpc_request(
    stdin: &SharedStdin,
    next_id: &AtomicI64,
    pending: &PendingMap,
    method: &str,
    params: Value,
) -> Result<Value, String> {
    let id = next_id.fetch_add(1, Ordering::SeqCst);

    let (tx, rx) = oneshot::channel();
    {
        let mut p = pending.lock().await;
        p.insert(id, tx);
    }

    let msg = serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "method": method,
        "params": params,
    });

    {
        let mut guard = stdin.lock().await;
        if let Some(ref mut stdin) = *guard {
            let line = format!("{}\n", msg);
            stdin
                .write_all(line.as_bytes())
                .await
                .map_err(|e| format!("stdin write failed: {e}"))?;
            stdin
                .flush()
                .await
                .map_err(|e| format!("stdin flush: {e}"))?;
        } else {
            return Err("stdin closed".into());
        }
    }

    match rx.await {
        Ok(result) => result,
        Err(_) => Err("response channel dropped".into()),
    }
}

async fn send_notification(stdin: &SharedStdin, method: &str, params: Value) {
    let msg = if params.is_null() {
        serde_json::json!({
            "jsonrpc": "2.0",
            "method": method,
        })
    } else {
        serde_json::json!({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })
    };

    let mut guard = stdin.lock().await;
    if let Some(ref mut stdin) = *guard {
        let line = format!("{}\n", msg);
        let _ = stdin.write_all(line.as_bytes()).await;
        let _ = stdin.flush().await;
    }
}

async fn handle_notification(
    method: &str,
    params: &Value,
    protocol: &Arc<std::sync::Mutex<String>>,
    event_tx: &mpsc::Sender<HarnessEvent>,
    usage: &Arc<std::sync::Mutex<TokenUsage>>,
    output: &Arc<std::sync::Mutex<String>>,
    call_id_to_tool: &Arc<std::sync::Mutex<HashMap<String, String>>>,
    agent_message_text_by_id: &Arc<std::sync::Mutex<HashMap<String, String>>>,
    current_turn: &Arc<Mutex<Option<TurnState>>>,
    model: &str,
) {
    let is_legacy = method == "codex/event" || method.starts_with("codex/event/");
    let is_raw = method == "turn/started"
        || method == "turn/completed"
        || method == "thread/started"
        || method == "thread/status/changed"
        || method == "thread/tokenUsage/updated"
        || method == "account/rateLimits/updated"
        || method.starts_with("item/");

    {
        let mut proto = protocol.lock().unwrap();
        if is_legacy && *proto == "unknown" {
            *proto = "legacy".into();
        } else if is_raw && *proto != "legacy" {
            *proto = "raw".into();
        }
    }

    let current_protocol = protocol.lock().unwrap().clone();

    if is_legacy || current_protocol == "legacy" {
        handle_legacy_event(
            params,
            event_tx,
            usage,
            output,
            call_id_to_tool,
            current_turn,
        )
        .await;
    } else if is_raw {
        handle_raw_notification(
            method,
            params,
            event_tx,
            usage,
            output,
            call_id_to_tool,
            agent_message_text_by_id,
            current_turn,
            model,
        )
        .await;
    } else if method == "error" {
        let error_msg = params
            .get("error")
            .and_then(|e| e.get("message"))
            .and_then(|m| m.as_str())
            .unwrap_or("unknown codex error");
        warn!(error = %error_msg, "Codex error notification");
        let _ = event_tx
            .send(HarnessEvent::Error {
                message: error_msg.to_string(),
            })
            .await;
        output
            .lock()
            .unwrap()
            .push_str(&format!("[error] {error_msg}\n"));
    } else {
        warn!(method = %method, "Codex unhandled notification");
    }
}

async fn handle_legacy_event(
    params: &Value,
    event_tx: &mpsc::Sender<HarnessEvent>,
    usage: &Arc<std::sync::Mutex<TokenUsage>>,
    output: &Arc<std::sync::Mutex<String>>,
    call_id_to_tool: &Arc<std::sync::Mutex<HashMap<String, String>>>,
    current_turn: &Arc<Mutex<Option<TurnState>>>,
) {
    let msg = match params.get("msg") {
        Some(m) => m,
        None => return,
    };

    let msg_type = msg.get("type").and_then(|t| t.as_str()).unwrap_or("");

    match msg_type {
        "task_started" => {
            let _ = event_tx
                .send(HarnessEvent::Status {
                    state: "running".into(),
                })
                .await;
        }
        "agent_message" => {
            let text = msg
                .get("message")
                .and_then(|m| m.as_str())
                .unwrap_or("")
                .to_string();
            output.lock().unwrap().push_str(&text);
            let _ = event_tx.send(HarnessEvent::Text { content: text }).await;
        }
        "exec_command_begin" => {
            let call_id = msg
                .get("call_id")
                .and_then(|c| c.as_str())
                .unwrap_or("")
                .to_string();
            let command = msg
                .get("command")
                .and_then(|c| c.as_str())
                .unwrap_or("")
                .to_string();
            call_id_to_tool
                .lock()
                .unwrap()
                .insert(call_id.clone(), "exec_command".into());
            let _ = event_tx
                .send(HarnessEvent::ToolUse {
                    tool: "exec_command".into(),
                    call_id,
                    input: serde_json::json!({"command": command}),
                    is_control_request: false,
                })
                .await;
        }
        "exec_command_end" => {
            let call_id = msg
                .get("call_id")
                .and_then(|c| c.as_str())
                .unwrap_or("")
                .to_string();
            let output_text = msg
                .get("output")
                .and_then(|o| o.as_str())
                .unwrap_or("")
                .to_string();
            let tool = call_id_to_tool
                .lock()
                .unwrap()
                .get(&call_id)
                .cloned()
                .unwrap_or_else(|| "exec_command".into());
            let _ = event_tx
                .send(HarnessEvent::ToolResult {
                    tool,
                    call_id,
                    output: output_text,
                })
                .await;
        }
        "patch_apply_begin" => {
            let call_id = msg
                .get("call_id")
                .and_then(|c| c.as_str())
                .unwrap_or("")
                .to_string();
            call_id_to_tool
                .lock()
                .unwrap()
                .insert(call_id.clone(), "patch_apply".into());
            let _ = event_tx
                .send(HarnessEvent::ToolUse {
                    tool: "patch_apply".into(),
                    call_id,
                    input: Value::Null,
                    is_control_request: false,
                })
                .await;
        }
        "patch_apply_end" => {
            let call_id = msg
                .get("call_id")
                .and_then(|c| c.as_str())
                .unwrap_or("")
                .to_string();
            let tool = call_id_to_tool
                .lock()
                .unwrap()
                .get(&call_id)
                .cloned()
                .unwrap_or_else(|| "patch_apply".into());
            let _ = event_tx
                .send(HarnessEvent::ToolResult {
                    tool,
                    call_id,
                    output: String::new(),
                })
                .await;
        }
        "task_complete" => {
            replace_usage(msg, usage);
            signal_turn_done(current_turn, false).await;
        }
        "turn_aborted" => {
            signal_turn_done(current_turn, true).await;
        }
        _ => {}
    }
}

async fn handle_raw_notification(
    method: &str,
    params: &Value,
    event_tx: &mpsc::Sender<HarnessEvent>,
    usage: &Arc<std::sync::Mutex<TokenUsage>>,
    output: &Arc<std::sync::Mutex<String>>,
    call_id_to_tool: &Arc<std::sync::Mutex<HashMap<String, String>>>,
    agent_message_text_by_id: &Arc<std::sync::Mutex<HashMap<String, String>>>,
    current_turn: &Arc<Mutex<Option<TurnState>>>,
    model: &str,
) {
    match method {
        "turn/started" => {
            let _ = event_tx
                .send(HarnessEvent::Status {
                    state: "running".into(),
                })
                .await;
            let _ = event_tx
                .send(HarnessEvent::ModelRequestStart {
                    model: model.to_string(),
                })
                .await;
        }
        "turn/completed" => {
            info!(params = %params, "Codex turn/completed");
            let turn = params.get("turn").unwrap_or(params);
            let status = turn.get("status").and_then(|s| s.as_str()).unwrap_or("");
            let aborted = matches!(status, "cancelled" | "canceled" | "aborted" | "interrupted");
            let effective_usage =
                replace_usage(turn, usage).unwrap_or_else(|| usage.lock().unwrap().clone());
            let (it, ot, crt, cwt) = usage_values(&effective_usage);
            let _ = event_tx
                .send(HarnessEvent::ModelRequestEnd {
                    model: model.to_string(),
                    input_tokens: it,
                    output_tokens: ot,
                    cache_read_tokens: crt,
                    cache_write_tokens: cwt,
                })
                .await;
            signal_turn_done(current_turn, aborted).await;
        }
        "thread/status/changed" => {
            let status_type = params
                .get("status")
                .and_then(|s| s.get("type"))
                .and_then(|t| t.as_str())
                .unwrap_or("");
            if status_type == "idle" {
                signal_turn_done(current_turn, false).await;
            }
        }
        "thread/tokenUsage/updated" => {
            info!(params = %params, "Codex token usage updated");
            replace_usage(params, usage);
        }
        "account/rateLimits/updated" => {
            debug!(params = %params, "Codex rate limits updated");
        }
        _ if method.starts_with("item/") => {
            handle_item_notification(
                method,
                params,
                event_tx,
                output,
                call_id_to_tool,
                agent_message_text_by_id,
                current_turn,
            )
            .await;
        }
        _ => {}
    }
}

async fn handle_item_notification(
    method: &str,
    params: &Value,
    event_tx: &mpsc::Sender<HarnessEvent>,
    output: &Arc<std::sync::Mutex<String>>,
    call_id_to_tool: &Arc<std::sync::Mutex<HashMap<String, String>>>,
    agent_message_text_by_id: &Arc<std::sync::Mutex<HashMap<String, String>>>,
    current_turn: &Arc<Mutex<Option<TurnState>>>,
) {
    let item = match params.get("item") {
        Some(i) => i,
        None => return,
    };

    let item_type = item.get("type").and_then(|t| t.as_str()).unwrap_or("");
    let item_id = item
        .get("id")
        .and_then(|i| i.as_str())
        .unwrap_or("")
        .to_string();

    match method {
        "item/started" => match item_type {
            "commandExecution" => {
                let command = item
                    .get("command")
                    .and_then(|c| c.as_str())
                    .unwrap_or("")
                    .to_string();
                call_id_to_tool
                    .lock()
                    .unwrap()
                    .insert(item_id.clone(), "exec_command".into());
                let _ = event_tx
                    .send(HarnessEvent::ToolUse {
                        tool: "exec_command".into(),
                        call_id: item_id,
                        input: serde_json::json!({"command": command}),
                        is_control_request: false,
                    })
                    .await;
            }
            "fileChange" => {
                call_id_to_tool
                    .lock()
                    .unwrap()
                    .insert(item_id.clone(), "patch_apply".into());
                let _ = event_tx
                    .send(HarnessEvent::ToolUse {
                        tool: "patch_apply".into(),
                        call_id: item_id,
                        input: Value::Null,
                        is_control_request: false,
                    })
                    .await;
            }
            _ => {}
        },
        "item/agentMessage/delta" => {
            if item_type == "agentMessage" {
                if let Some(text) = extract_agent_message_delta(params) {
                    if !text.is_empty() {
                        agent_message_text_by_id
                            .lock()
                            .unwrap()
                            .entry(item_id)
                            .or_default()
                            .push_str(&text);
                        output.lock().unwrap().push_str(&text);
                        let _ = event_tx.send(HarnessEvent::Text { content: text }).await;
                    }
                }
            }
        }
        "item/completed" => match item_type {
            "commandExecution" => {
                let output_text = item
                    .get("aggregatedOutput")
                    .and_then(|o| o.as_str())
                    .unwrap_or("")
                    .to_string();
                let tool = call_id_to_tool
                    .lock()
                    .unwrap()
                    .get(&item_id)
                    .cloned()
                    .unwrap_or_else(|| "exec_command".into());
                let _ = event_tx
                    .send(HarnessEvent::ToolResult {
                        tool,
                        call_id: item_id,
                        output: output_text,
                    })
                    .await;
            }
            "fileChange" => {
                let tool = call_id_to_tool
                    .lock()
                    .unwrap()
                    .get(&item_id)
                    .cloned()
                    .unwrap_or_else(|| "patch_apply".into());
                let _ = event_tx
                    .send(HarnessEvent::ToolResult {
                        tool,
                        call_id: item_id,
                        output: String::new(),
                    })
                    .await;
            }
            "agentMessage" => {
                let text = item
                    .get("text")
                    .and_then(|t| t.as_str())
                    .unwrap_or("")
                    .to_string();
                let already_sent = agent_message_text_by_id.lock().unwrap().remove(&item_id);
                let remaining_text = match already_sent {
                    Some(sent) if !sent.is_empty() => {
                        text.strip_prefix(&sent).unwrap_or("").to_string()
                    }
                    _ => text,
                };
                if !remaining_text.is_empty() {
                    output.lock().unwrap().push_str(&remaining_text);
                    let _ = event_tx
                        .send(HarnessEvent::Text {
                            content: remaining_text,
                        })
                        .await;
                }

                let phase = item.get("phase").and_then(|p| p.as_str()).unwrap_or("");
                if phase == "final_answer" {
                    signal_turn_done(current_turn, false).await;
                }
            }
            _ => {}
        },
        _ => {}
    }
}

fn text_from_value(value: &Value) -> Option<String> {
    if let Some(text) = value.as_str() {
        return Some(text.to_string());
    }

    if let Some(obj) = value.as_object() {
        for key in ["text", "content", "delta"] {
            if let Some(text) = obj.get(key).and_then(text_from_value) {
                return Some(text);
            }
        }
    }

    if let Some(array) = value.as_array() {
        let text = array.iter().filter_map(text_from_value).collect::<String>();
        if !text.is_empty() {
            return Some(text);
        }
    }

    None
}

fn extract_agent_message_delta(params: &Value) -> Option<String> {
    for key in ["delta", "textDelta", "contentDelta", "text", "content"] {
        if let Some(text) = params.get(key).and_then(text_from_value) {
            return Some(text);
        }
    }

    let item = params.get("item")?;
    for key in ["delta", "textDelta", "contentDelta"] {
        if let Some(text) = item.get(key).and_then(text_from_value) {
            return Some(text);
        }
    }

    None
}

fn find_usage_object(data: &Value) -> Option<&serde_json::Map<String, Value>> {
    ["usage", "token_usage", "tokens"]
        .iter()
        .find_map(|key| data.get(key))
        .and_then(|v| v.as_object())
        .or_else(|| {
            // Codex sends both last and total. total is thread-cumulative, so
            // prefer last for per-turn events and task usage accounting.
            data.get("tokenUsage").and_then(|tu| {
                tu.get("last")
                    .or_else(|| tu.get("total"))
                    .or(Some(tu))
                    .and_then(|v| v.as_object())
            })
        })
}

fn usage_from_value(data: &Value) -> Option<TokenUsage> {
    let usage_obj = match find_usage_object(data) {
        Some(obj) => obj,
        None => return None,
    };

    let get_u64 = |keys: &[&str]| -> u64 {
        for key in keys {
            if let Some(v) = usage_obj.get(*key) {
                if let Some(n) = v.as_u64() {
                    if n > 0 {
                        return n;
                    }
                }
                if let Some(n) = v.as_f64() {
                    if n > 0.0 {
                        return n as u64;
                    }
                }
            }
        }
        0
    };

    Some(TokenUsage {
        input_tokens: get_u64(&["input_tokens", "input", "prompt_tokens", "inputTokens"]),
        output_tokens: get_u64(&[
            "output_tokens",
            "output",
            "completion_tokens",
            "outputTokens",
        ]),
        cache_read_tokens: get_u64(&[
            "cache_read_tokens",
            "cache_read_input_tokens",
            "cachedInputTokens",
        ]),
        cache_write_tokens: get_u64(&[
            "cache_write_tokens",
            "cache_creation_input_tokens",
            "cacheWriteTokens",
        ]),
        by_model: HashMap::new(),
    })
}

fn usage_values(usage: &TokenUsage) -> (u64, u64, u64, u64) {
    (
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
    )
}

fn replace_usage(data: &Value, usage: &Arc<std::sync::Mutex<TokenUsage>>) -> Option<TokenUsage> {
    let parsed = usage_from_value(data)?;
    let mut u = usage.lock().unwrap();
    *u = parsed.clone();
    Some(parsed)
}

async fn signal_turn_done(current_turn: &Arc<Mutex<Option<TurnState>>>, aborted: bool) {
    let mut guard = current_turn.lock().await;
    if let Some(ref mut turn) = *guard {
        if let Some(tx) = turn.turn_done_tx.take() {
            let _ = tx.send(aborted);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codex_token_usage_prefers_last_and_normalizes_fields() {
        let data = serde_json::json!({
            "tokenUsage": {
                "last": {
                    "inputTokens": 10,
                    "outputTokens": 4,
                    "cachedInputTokens": 3,
                    "cacheWriteTokens": 2
                },
                "total": {
                    "inputTokens": 99,
                    "outputTokens": 88,
                    "cachedInputTokens": 77,
                    "cacheWriteTokens": 66
                }
            }
        });

        let usage = usage_from_value(&data).expect("usage should parse");

        assert_eq!(usage.input_tokens, 10);
        assert_eq!(usage.output_tokens, 4);
        assert_eq!(usage.cache_read_tokens, 3);
        assert_eq!(usage.cache_write_tokens, 2);
    }

    #[test]
    fn codex_token_usage_updates_as_snapshot_not_accumulator() {
        let usage = Arc::new(std::sync::Mutex::new(TokenUsage::default()));

        replace_usage(
            &serde_json::json!({"tokenUsage": {"last": {"inputTokens": 10, "outputTokens": 4}}}),
            &usage,
        );
        replace_usage(
            &serde_json::json!({"tokenUsage": {"last": {"inputTokens": 12, "outputTokens": 5}}}),
            &usage,
        );

        let usage = usage.lock().unwrap().clone();
        assert_eq!(usage.input_tokens, 12);
        assert_eq!(usage.output_tokens, 5);
    }

    #[test]
    fn codex_agent_message_delta_extracts_text_shapes() {
        assert_eq!(
            extract_agent_message_delta(&serde_json::json!({
                "item": {"id": "item-1", "type": "agentMessage"},
                "delta": "hello"
            }))
            .as_deref(),
            Some("hello"),
        );

        assert_eq!(
            extract_agent_message_delta(&serde_json::json!({
                "item": {"id": "item-1", "type": "agentMessage"},
                "delta": {"content": [{"type": "text", "text": "hel"}, {"type": "text", "text": "lo"}]}
            }))
            .as_deref(),
            Some("hello"),
        );
    }
}
