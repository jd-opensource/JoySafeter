use async_trait::async_trait;
use joysafeter_types::harness::{
    HarnessAdapter, HarnessError, HarnessEvent, HarnessInput, HarnessResult, RunningHarness,
};
use joysafeter_types::token_usage::TokenUsage;
use serde::Deserialize;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
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
/// jsonrpc-id-as-string → user-approval oneshot. Used to route
/// codex's approval requests (execCommandApproval / applyPatchApproval)
/// out to the user (as agent.tool_use is_control_request) and resolve them
/// when the user posts a user.tool_confirmation back via send_input.
type PendingApprovals = Arc<Mutex<HashMap<String, oneshot::Sender<bool>>>>;

/// Prefix used by the orchestrator's "live input" channel for steering an
/// in-flight task — same string as in claude.rs. Kept duplicated to avoid
/// pulling a public type out of claude.rs for one constant.
const LIVE_INPUT_PREFIX: &str = "__joysafeter_input_v1__:";

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum CodexLiveInput {
    ToolConfirmation {
        tool_use_call_id: String,
        approved: bool,
        #[serde(default)]
        #[allow(dead_code)]
        deny_message: Option<String>,
    },
    // Other live-input variants (custom_tool_result / interrupt) are routed
    // through different mechanisms for codex; only tool_confirmation is
    // consumed here.
    #[serde(other)]
    Other,
}

struct TurnState {
    event_tx: mpsc::Sender<HarnessEvent>,
    turn_done_tx: Option<oneshot::Sender<bool>>,
    usage: Arc<std::sync::Mutex<TokenUsage>>,
    output: Arc<std::sync::Mutex<String>>,
    error: Arc<std::sync::Mutex<Option<String>>>,
    call_id_to_tool: Arc<std::sync::Mutex<HashMap<String, String>>>,
    agent_message_text_by_id: Arc<std::sync::Mutex<HashMap<String, String>>>,
    model: String,
    /// Tool names from `HarnessInput.allowed_tools` for this turn. Used by the
    /// reader loop to auto-accept ExecApprovalRequest events whose derived tool
    /// name matches the agent's allowlist — i.e. translate JoySafeter's
    /// `always_allow` to codex's approval protocol without going through the UI.
    allowed_tools: Vec<String>,
    /// Tool names the agent explicitly wants to ask the user about. Listed here
    /// so we can treat them as the only ones that always reach the user, even
    /// if we later refine the default behavior.
    ask_tools: Vec<String>,
    /// Multi-agent active-thread tracker.
    ///
    /// Codex's parent turn ends as soon as the parent model loop returns,
    /// independent of any sub-agents it spawned via `spawn_agent` — that's
    /// fire-and-forget at the wire-protocol level. The orchestrator can only
    /// declare RunnerIdle when *all* threads (parent + spawned children) are
    /// idle, so we mirror the aggregation codex itself does internally with
    /// `running_turn_count` in `thread_status.rs`. We hold a set of every
    /// thread id we've seen go busy, and `signal_turn_done_for` only fires
    /// the oneshot once the set is empty.
    ///
    /// Seeded with the main thread id at turn start. Children are added on
    /// `turn/started{threadId}`, `thread/status/changed{threadId, busy}`,
    /// and proactively on `collabAgentToolCall item/started`'s
    /// `receiverThreadIds` (in case the spawn event races the child's own
    /// `turn/started`). Removed on `turn/completed{threadId}` and on
    /// `thread/status/changed{threadId, idle}`.
    active_threads: HashSet<String>,
    /// The parent thread id for this turn. Used as the implicit target when
    /// a legacy (multi-agent-unaware) signal like `task_complete` or
    /// `turn_aborted` fires — those events don't carry a threadId, but they
    /// always describe the parent's loop.
    main_thread_id: String,
}

struct PersistentCodex {
    stdin: SharedStdin,
    next_id: Arc<AtomicI64>,
    pending: PendingMap,
    pending_approvals: PendingApprovals,
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

impl Default for CodexAdapter {
    fn default() -> Self {
        Self::new()
    }
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
            matches!(session.child.try_wait(), Ok(None))
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

        // Merge MCP servers from HarnessInput into ~/.codex/config.toml so the
        // codex CLI advertises them to the model. Codex CLI looks for
        // ``[mcp_servers.<name>]`` blocks in this file.
        if let Err(e) = merge_codex_mcp_servers(&input.mcp_configs).await {
            warn!(error = %e, "Failed to write codex MCP servers config");
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
        let pending_approvals: PendingApprovals = Arc::new(Mutex::new(HashMap::new()));
        let current_turn: Arc<Mutex<Option<TurnState>>> = Arc::new(Mutex::new(None));
        let notification_protocol: Arc<std::sync::Mutex<String>> =
            Arc::new(std::sync::Mutex::new("unknown".into()));
        let last_usage: Arc<std::sync::Mutex<TokenUsage>> =
            Arc::new(std::sync::Mutex::new(TokenUsage::default()));

        let reader_pending = pending.clone();
        let reader_pending_approvals = pending_approvals.clone();
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
                    // Classify the server→client request into an approval kind.
                    // Each kind serializes its decision differently (see
                    // ApprovalKind::result_json).
                    let approval_kind = ApprovalKind::from_method(method);

                    if let Some(approval_kind) = approval_kind {
                        // Route the approval request out to the user instead of
                        // auto-accepting. Steps:
                        //  1) Build a stable string id from the jsonrpc id.
                        //  2) Register a oneshot in pending_approvals.
                        //  3) Emit agent.tool_use with is_control_request=true so
                        //     the frontend banner picks it up (same shape claude
                        //     uses for its can_use_tool control_request).
                        //  4) Spawn a task that awaits the oneshot, then writes
                        //     a jsonrpc response back to codex's stdin with the
                        //     user's decision.
                        let req_id_value = msg.id.clone().unwrap_or(Value::Null);
                        let req_id_str = match &req_id_value {
                            Value::Number(n) => n.to_string(),
                            Value::String(s) => s.clone(),
                            other => other.to_string(),
                        };
                        let params = msg.params.clone().unwrap_or(Value::Null);
                        let tool_name = derive_approval_tool_name(method, &params);

                        // Fast path: if the current turn's allowed_tools list
                        // covers this approval, skip the UI roundtrip and reply
                        // accept directly. This is how JoySafeter's
                        // ``always_allow`` policy maps onto codex's approval
                        // protocol. ``ask_tools`` is checked separately so it
                        // explicitly takes priority over allow when both lists
                        // somehow contain the same tool (mirrors claude
                        // settings.json semantics).
                        let auto_accept: Option<bool> = {
                            let turn_guard = reader_current_turn.lock().await;
                            if let Some(turn) = turn_guard.as_ref() {
                                if approval_matches_tool(&turn.ask_tools, &tool_name) {
                                    None
                                } else if approval_matches_tool(&turn.allowed_tools, &tool_name) {
                                    Some(true)
                                } else {
                                    None
                                }
                            } else {
                                None
                            }
                        };

                        if auto_accept == Some(true) {
                            info!(
                                method = %method,
                                tool = %tool_name,
                                "Auto-approving codex tool call from allowed_tools"
                            );
                            let response = serde_json::json!({
                                "jsonrpc": "2.0",
                                "id": req_id_value,
                                "result": approval_kind.result_json(true)
                            });
                            let line = format!("{}\n", response);
                            let mut guard = reader_stdin.lock().await;
                            if let Some(ref mut stdin) = *guard {
                                let _ = stdin.write_all(line.as_bytes()).await;
                                let _ = stdin.flush().await;
                            }
                            continue;
                        }

                        let (tx, rx) = oneshot::channel::<bool>();
                        reader_pending_approvals
                            .lock()
                            .await
                            .insert(req_id_str.clone(), tx);

                        // Emit the approval-request event to the user. Best-effort:
                        // only if a turn is active and the event channel is alive.
                        {
                            let turn_guard = reader_current_turn.lock().await;
                            if let Some(turn) = turn_guard.as_ref() {
                                let _ = turn
                                    .event_tx
                                    .send(HarnessEvent::ToolUse {
                                        tool: tool_name.clone(),
                                        call_id: req_id_str.clone(),
                                        input: params.clone(),
                                        is_control_request: true,
                                    })
                                    .await;
                            } else {
                                warn!(
                                    method = %method,
                                    "Codex approval request arrived without an active turn; \
                                     event will not surface to user — denying"
                                );
                                // No way to surface to the user → deny so codex
                                // doesn't hang forever.
                                if let Some(tx) =
                                    reader_pending_approvals.lock().await.remove(&req_id_str)
                                {
                                    let _ = tx.send(false);
                                }
                            }
                        }

                        // Background waiter → jsonrpc response. The decision
                        // serialization is kind-specific (ApprovalKind::result_json):
                        //  - exec/patch v2 → {decision: "accept"|"decline"}
                        //  - exec/patch v1 → {decision: "approved"|"denied"}
                        //  - MCP elicitation → {action: "accept"|"decline", content: null}
                        // Sending the wrong shape makes codex misread the decision
                        // and report the tool as user-rejected even on approval.
                        let waiter_stdin = reader_stdin.clone();
                        let waiter_id = req_id_value;
                        let waiter_method = method.to_string();
                        tokio::spawn(async move {
                            let approved = rx.await.unwrap_or(false);
                            let response = serde_json::json!({
                                "jsonrpc": "2.0",
                                "id": waiter_id,
                                "result": approval_kind.result_json(approved)
                            });
                            let line = format!("{}\n", response);
                            let mut guard = waiter_stdin.lock().await;
                            if let Some(ref mut stdin) = *guard {
                                if let Err(e) = stdin.write_all(line.as_bytes()).await {
                                    warn!(error = %e, method = %waiter_method,
                                          "Failed to write approval response to codex stdin");
                                }
                                let _ = stdin.flush().await;
                            }
                        });
                    } else {
                        // Non-approval server→client request: keep historical
                        // behavior of acknowledging with an empty result.
                        let response = serde_json::json!({
                            "jsonrpc": "2.0",
                            "id": msg.id,
                            "result": {}
                        });
                        let line = format!("{}\n", response);
                        let mut guard = reader_stdin.lock().await;
                        if let Some(ref mut stdin) = *guard {
                            let _ = stdin.write_all(line.as_bytes()).await;
                            let _ = stdin.flush().await;
                        }
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
            pending_approvals,
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

        // Capture the pending-approvals handle so send_input on the returned
        // RunningHarness can resolve user.tool_confirmation by call_id.
        let pending_approvals_handle: PendingApprovals = session.pending_approvals.clone();

        let main_thread_id = session.thread_id.clone();
        let mut active_threads = HashSet::new();
        active_threads.insert(main_thread_id.clone());

        let turn_state = TurnState {
            event_tx: event_tx.clone(),
            turn_done_tx: None,
            usage: Arc::new(std::sync::Mutex::new(TokenUsage::default())),
            output: Arc::new(std::sync::Mutex::new(String::new())),
            error: Arc::new(std::sync::Mutex::new(None)),
            call_id_to_tool: Arc::new(std::sync::Mutex::new(HashMap::new())),
            agent_message_text_by_id: Arc::new(std::sync::Mutex::new(HashMap::new())),
            model: input.model.clone().unwrap_or_else(|| "codex".to_string()),
            allowed_tools: input.allowed_tools.clone(),
            ask_tools: input.ask_tools.clone(),
            active_threads,
            main_thread_id,
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
            let aborted = td_rx.await.unwrap_or(true);

            // Wait briefly for late notifications (tokenUsage, turn/completed)
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;

            let (final_output, turn_usage, final_error) = {
                let ct = current_turn_for_completion.lock().await;
                if let Some(ref turn) = *ct {
                    let o = turn.output.lock().unwrap().clone();
                    let u = turn.usage.lock().unwrap().clone();
                    let e = turn.error.lock().unwrap().clone();
                    (o, u, e)
                } else {
                    (String::new(), TokenUsage::default(), None)
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
            let (status, error) = crate::finish_turn(aborted, final_error);

            let _ = result_tx.send(HarnessResult {
                status,
                output: final_output,
                error,
                session_id: None,
                usage: final_usage,
                duration,
            });
        });

        Ok(RunningHarness {
            events: event_rx,
            result: result_rx,
            child: None,
            input: Some(Box::new(pending_approvals_handle)),
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

    /// Accept live-input messages and route `user.tool_confirmation` to the
    /// matching pending approval. Other live-input variants are not consumed
    /// here (custom_tool_result and interrupt don't apply to the codex
    /// app-server protocol the same way they do for claude). Plain non-live
    /// content is ignored — codex turns are driven by Op::UserTurn / Op::UserInput
    /// dispatched through start(), not through send_input.
    async fn send_input(
        &self,
        harness: &mut RunningHarness,
        content: String,
    ) -> Result<(), HarnessError> {
        let Some(any) = harness.input.as_ref() else {
            return Err(HarnessError::UnsupportedInput);
        };
        let Some(pending) = any.downcast_ref::<PendingApprovals>() else {
            return Err(HarnessError::UnsupportedInput);
        };

        let Some(raw) = content.strip_prefix(LIVE_INPUT_PREFIX) else {
            // Not a live-input frame — codex doesn't accept free-form steering
            // mid-turn through this channel.
            return Ok(());
        };
        let payload: CodexLiveInput = match serde_json::from_str(raw) {
            Ok(p) => p,
            Err(e) => return Err(HarnessError::ParseError(e.to_string())),
        };

        match payload {
            CodexLiveInput::ToolConfirmation {
                tool_use_call_id,
                approved,
                ..
            } => {
                if let Some(tx) = pending.lock().await.remove(&tool_use_call_id) {
                    let _ = tx.send(approved);
                }
                Ok(())
            }
            CodexLiveInput::Other => Ok(()),
        }
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

/// Classifies a codex server→client approval request and serializes decisions
/// in the shape that specific request expects.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ApprovalKind {
    /// v2 exec/patch — `{decision: "accept"|"decline"}`.
    ExecV2,
    /// v1 exec/patch — `{decision: "approved"|"denied"}`.
    ExecV1,
    /// MCP tool elicitation — `{action: "accept"|"decline", content: null}`.
    McpElicitation,
}

impl ApprovalKind {
    fn from_method(method: &str) -> Option<Self> {
        match method {
            "item/commandExecution/requestApproval" | "item/fileChange/requestApproval" => {
                Some(Self::ExecV2)
            }
            "execCommandApproval" | "applyPatchApproval" => Some(Self::ExecV1),
            "mcpServer/elicitation/request" => Some(Self::McpElicitation),
            _ => None,
        }
    }

    /// Build the JSON-RPC `result` payload for an approve/deny decision.
    fn result_json(self, approved: bool) -> Value {
        match self {
            Self::ExecV2 => {
                serde_json::json!({ "decision": if approved { "accept" } else { "decline" } })
            }
            Self::ExecV1 => {
                serde_json::json!({ "decision": if approved { "approved" } else { "denied" } })
            }
            Self::McpElicitation => {
                // codex parses {action:"accept", content:null} → Accept (its
                // fallback maps the empty-content Cancel back to Accept), and
                // {action:"decline"} → Decline.
                serde_json::json!({
                    "action": if approved { "accept" } else { "decline" },
                    "content": Value::Null
                })
            }
        }
    }
}

/// Return true if the agent's tool list authorizes the approval whose derived
/// name is ``tool_name``.
///
/// ``derive_approval_tool_name`` produces strings like ``"Bash"`` or
/// ``"Bash (git)"`` (exec) and ``"mcp__<server>__*"`` (MCP elicitation).
/// JoySafeter agents express permissions by short tool name (``Bash``, ``Write``,
/// …) and MCP rules as ``mcp__<server>__*`` / ``mcp__<server>__<tool>``. We match:
///  - exact (``rule == tool_name``),
///  - by leading word (``Bash (git)`` matches rule ``Bash``), or
///  - by MCP server prefix, so the derived ``mcp__server__*`` matches a more
///    specific rule ``mcp__server__tool`` (and vice-versa).
fn approval_matches_tool(rules: &[String], tool_name: &str) -> bool {
    if rules.is_empty() {
        return false;
    }
    let leading = tool_name.split_whitespace().next().unwrap_or(tool_name);

    // For MCP names, compare on the ``mcp__<server>__`` prefix so wildcard and
    // per-tool rules are interchangeable at the server granularity codex gives us.
    let mcp_server_prefix = |s: &str| -> Option<String> {
        let rest = s.strip_prefix("mcp__")?;
        let server = rest.split("__").next()?;
        if server.is_empty() {
            None
        } else {
            Some(format!("mcp__{server}__"))
        }
    };
    let tool_mcp_prefix = mcp_server_prefix(leading);

    rules.iter().any(|r| {
        if r == tool_name || r == leading {
            return true;
        }
        match (&tool_mcp_prefix, mcp_server_prefix(r)) {
            (Some(tp), Some(rp)) => tp == &rp,
            _ => false,
        }
    })
}

/// Pick a user-facing tool name for an approval request so the frontend banner
/// can show something meaningful. `params` typically carries the command being
/// approved (for exec) or the patch metadata (for fileChange).
fn derive_approval_tool_name(method: &str, params: &Value) -> String {
    match method {
        "item/commandExecution/requestApproval" | "execCommandApproval" => {
            // Try to surface the first token of the command if available.
            if let Some(cmd) = params.get("command").and_then(|c| c.as_array()) {
                if let Some(first) = cmd.first().and_then(|v| v.as_str()) {
                    return format!("Bash ({first})");
                }
            }
            if let Some(cmd_str) = params.get("command").and_then(|c| c.as_str()) {
                let first = cmd_str.split_whitespace().next().unwrap_or("Bash");
                return format!("Bash ({first})");
            }
            "Bash".to_string()
        }
        "item/fileChange/requestApproval" | "applyPatchApproval" => "ApplyPatch".to_string(),
        "mcpServer/elicitation/request" => {
            // codex sends camelCase `serverName`; tool name is NOT exposed in the
            // elicitation params, so we can only resolve to server granularity.
            let server = params
                .get("serverName")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if server.is_empty() {
                "mcp".to_string()
            } else {
                format!("mcp__{server}__*")
            }
        }
        _ => method.to_string(),
    }
}

#[allow(clippy::too_many_arguments)]
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
        record_turn_error(current_turn, error_msg.to_string()).await;
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

#[allow(clippy::too_many_arguments)]
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
            // Track this thread as active so signal_thread_done can't
            // declare the turn complete before it finishes. The first
            // turn/started we see for the parent thread is a no-op
            // (already seeded at start), but child threads spawned via
            // spawn_agent arrive here for the first time.
            if let Some(tid) = params.get("threadId").and_then(|v| v.as_str()) {
                note_thread_active(current_turn, tid).await;
            }
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
            if let Some(error_message) = codex_turn_error(turn) {
                let _ = event_tx
                    .send(HarnessEvent::Error {
                        message: error_message.clone(),
                    })
                    .await;
                record_turn_error(current_turn, error_message).await;
            }
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
            // Route the done signal to the specific thread that completed
            // — could be the parent or any spawned child. Only fires the
            // turn_done oneshot when every thread has reported done.
            let thread_id = params
                .get("threadId")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            match thread_id {
                Some(tid) => signal_thread_done(current_turn, &tid, aborted).await,
                None => signal_turn_done(current_turn, aborted).await,
            }
        }
        "thread/status/changed" => {
            let status_type = params
                .get("status")
                .and_then(|s| s.get("type"))
                .and_then(|t| t.as_str())
                .unwrap_or("");
            let thread_id = params
                .get("threadId")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            if status_type == "idle" {
                // Mirror what codex itself does in thread_status.rs:
                // running_turn_count drops when *any* thread goes idle, and
                // the whole conversation is only globally idle at count=0.
                match thread_id {
                    Some(tid) => signal_thread_done(current_turn, &tid, false).await,
                    None => signal_turn_done(current_turn, false).await,
                }
            } else if let Some(tid) = thread_id {
                // Any non-idle status (running / awaiting input / etc.)
                // means this thread is active — register it so a stale
                // empty set can't mistakenly fire the done signal.
                note_thread_active(current_turn, &tid).await;
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
            // Background sub-agent lifecycle (codex multi-agent v2). Mapped to
            // the same TaskNotification surface as Claude Code's Task tool so the
            // orchestrator/frontend bg_task rendering works for both engines.
            "collabAgentToolCall" => {
                // Pre-register every receiver thread as active. Without
                // this, a small race is possible: the child's own
                // `turn/started{threadId=X}` might still be in flight
                // when the parent's signal_thread_done fires for itself,
                // and the empty-set check would wrongly declare the turn
                // complete. By the time the child's turn/started arrives
                // we'd be too late. Note: insertions are idempotent.
                if let Some(receivers) = item.get("receiverThreadIds").and_then(|v| v.as_array()) {
                    for r in receivers {
                        if let Some(tid) = r.as_str() {
                            note_thread_active(current_turn, tid).await;
                        }
                    }
                }
                if let Some(ev) = collab_agent_to_task_event(item, /*completed=*/ false) {
                    let _ = event_tx.send(ev).await;
                }
            }
            "subAgentActivity" => {
                if let Some(ev) = sub_agent_activity_to_task_event(item) {
                    let _ = event_tx.send(ev).await;
                }
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
            // Background sub-agent completion (codex multi-agent v2).
            "collabAgentToolCall" => {
                if let Some(ev) = collab_agent_to_task_event(item, /*completed=*/ true) {
                    let _ = event_tx.send(ev).await;
                }
            }
            "subAgentActivity" => {
                if let Some(ev) = sub_agent_activity_to_task_event(item) {
                    let _ = event_tx.send(ev).await;
                }
            }
            _ => {}
        },
        _ => {}
    }
}

/// Truncate a string to at most `max` chars (char-boundary safe).
fn truncate_chars(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        s.chars().take(max).collect()
    }
}

/// Map a codex `collabAgentToolCall` item to a background-task notification.
///
/// `completed=false` for `item/started` (spawn → "started", others → "progress"),
/// `completed=true` for `item/completed` (status=failed → "failed" else "completed").
fn collab_agent_to_task_event(item: &Value, completed: bool) -> Option<HarnessEvent> {
    let tool = item.get("tool").and_then(|t| t.as_str()).unwrap_or("");
    // task_id: prefer the spawned receiver thread, fall back to sender thread.
    let task_id = item
        .get("receiverThreadIds")
        .and_then(|r| r.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_str())
        .or_else(|| item.get("senderThreadId").and_then(|s| s.as_str()))
        .unwrap_or("")
        .to_string();
    if task_id.is_empty() {
        return None;
    }
    let description = item
        .get("prompt")
        .and_then(|p| p.as_str())
        .filter(|p| !p.is_empty())
        .map(|p| truncate_chars(p, 80))
        .unwrap_or_else(|| tool.to_string());
    let tool_use_id = item
        .get("id")
        .and_then(|i| i.as_str())
        .map(|s| s.to_string());

    let (phase, status, summary) = if completed {
        let status_str = item
            .get("status")
            .and_then(|s| s.as_str())
            .unwrap_or("completed");
        let p = if status_str == "failed" {
            "failed"
        } else {
            "completed"
        };
        (
            p.to_string(),
            Some(p.to_string()),
            Some(format!("Sub-agent \"{description}\" {p}")),
        )
    } else {
        let p = if tool == "spawnAgent" {
            "started"
        } else {
            "progress"
        };
        (p.to_string(), None, None)
    };

    Some(HarnessEvent::TaskNotification {
        phase,
        task_id,
        tool_use_id,
        description: Some(description),
        status,
        summary,
        result: None,
        output_file: None,
        last_tool_name: None,
        total_tokens: None,
        tool_uses: None,
        duration_ms: None,
    })
}

/// Map a codex `subAgentActivity` item to a background-task notification.
fn sub_agent_activity_to_task_event(item: &Value) -> Option<HarnessEvent> {
    let task_id = item
        .get("agentThreadId")
        .and_then(|s| s.as_str())
        .unwrap_or("")
        .to_string();
    if task_id.is_empty() {
        return None;
    }
    let description = item
        .get("agentPath")
        .and_then(|p| p.as_str())
        .map(|s| s.to_string());
    let kind = item.get("kind").and_then(|k| k.as_str()).unwrap_or("");
    let (phase, status, summary) = match kind {
        "started" => ("started".to_string(), None, None),
        "interrupted" => (
            "stopped".to_string(),
            Some("stopped".to_string()),
            Some(format!(
                "Sub-agent {} stopped",
                description.as_deref().unwrap_or("")
            )),
        ),
        // "interacted" and any other activity → progress ping
        _ => ("progress".to_string(), None, None),
    };
    let tool_use_id = item
        .get("id")
        .and_then(|i| i.as_str())
        .map(|s| s.to_string());

    Some(HarnessEvent::TaskNotification {
        phase,
        task_id,
        tool_use_id,
        description,
        status,
        summary,
        result: None,
        output_file: None,
        last_tool_name: None,
        total_tokens: None,
        tool_uses: None,
        duration_ms: None,
    })
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
    let usage_obj = find_usage_object(data)?;

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

fn codex_turn_error(turn: &Value) -> Option<String> {
    let status = turn
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_ascii_lowercase();
    if !matches!(status.as_str(), "failed" | "error" | "errored") {
        return None;
    }

    turn.get("error")
        .and_then(crate::error_value_message)
        .or_else(|| {
            turn.get("message")
                .and_then(Value::as_str)
                .filter(|message| !message.trim().is_empty())
                .map(ToOwned::to_owned)
        })
        .or_else(|| Some(format!("codex turn {status}")))
}

async fn record_turn_error(current_turn: &Arc<Mutex<Option<TurnState>>>, error_message: String) {
    let guard = current_turn.lock().await;
    if let Some(turn) = guard.as_ref() {
        *turn.error.lock().unwrap() = Some(error_message);
    }
}

fn replace_usage(data: &Value, usage: &Arc<std::sync::Mutex<TokenUsage>>) -> Option<TokenUsage> {
    let parsed = usage_from_value(data)?;
    let mut u = usage.lock().unwrap();
    *u = parsed.clone();
    Some(parsed)
}

/// Mark `thread_id` as no longer running. If the active set is now empty
/// (parent + every spawned child have all reported done), fire the
/// turn_done oneshot so the runner can finalize the turn and emit
/// RunnerIdle. While the set still has anything in it we do nothing —
/// this is the multi-agent case where the parent finished but a sub-agent
/// it spawned via `spawn_agent` is still running.
async fn signal_thread_done(
    current_turn: &Arc<Mutex<Option<TurnState>>>,
    thread_id: &str,
    aborted: bool,
) {
    let mut guard = current_turn.lock().await;
    if let Some(ref mut turn) = *guard {
        turn.active_threads.remove(thread_id);
        if turn.active_threads.is_empty() {
            if let Some(tx) = turn.turn_done_tx.take() {
                let _ = tx.send(aborted);
            }
        }
    }
}

/// Mark `thread_id` as currently running. Idempotent: a second insert is
/// a no-op. Called on `turn/started`, on busy `thread/status/changed`, and
/// proactively for every receiver in `collabAgentToolCall item/started`
/// so the spawn handshake doesn't race the child's own `turn/started`.
async fn note_thread_active(current_turn: &Arc<Mutex<Option<TurnState>>>, thread_id: &str) {
    let mut guard = current_turn.lock().await;
    if let Some(ref mut turn) = *guard {
        turn.active_threads.insert(thread_id.to_string());
    }
}

/// Legacy entry point for callers that don't carry a thread id (the codex
/// 1.x `task_complete` / `turn_aborted` events from `handle_event_msg`,
/// and the `phase == "final_answer"` path in `handle_item_notification`).
/// Routes the signal to the parent thread — those events always describe
/// the parent's loop in practice.
async fn signal_turn_done(current_turn: &Arc<Mutex<Option<TurnState>>>, aborted: bool) {
    let main_id = {
        let guard = current_turn.lock().await;
        guard.as_ref().map(|t| t.main_thread_id.clone())
    };
    if let Some(id) = main_id {
        signal_thread_done(current_turn, &id, aborted).await;
    }
}

/// Merge MCP servers into ``~/.codex/config.toml``.
///
/// The codex CLI reads ``[mcp_servers.<name>]`` tables from this file to decide
/// which MCP servers to mount for the model. We append (or replace by name)
/// the entries described by ``HarnessInput.mcp_configs`` without touching the
/// rest of the file (so the entrypoint's [model_providers.*] etc. survive).
///
/// Currently we only handle URL servers — that's the only shape JoySafeter's
/// public schema accepts. URL servers translate to:
///
/// ```toml
/// [mcp_servers.echo-test]
/// url = "http://host.docker.internal:8765/"
/// ```
async fn merge_codex_mcp_servers(
    servers: &[joysafeter_types::agent::McpServerConfig],
) -> Result<(), String> {
    use joysafeter_types::agent::McpServerConfig;

    if servers.is_empty() {
        return Ok(());
    }

    let config_dir = match std::env::var("HOME") {
        Ok(h) => std::path::PathBuf::from(h).join(".codex"),
        Err(_) => std::path::PathBuf::from("/home/agent/.codex"),
    };
    tokio::fs::create_dir_all(&config_dir)
        .await
        .map_err(|e| format!("mkdir {}: {e}", config_dir.display()))?;

    let path = config_dir.join("config.toml");
    let existing = tokio::fs::read_to_string(&path).await.unwrap_or_default();

    // Strip any previous block this writer owned. We delimit our managed region
    // with sentinel comments so re-runs replace cleanly instead of stacking.
    const BEGIN: &str = "# >>> joysafeter mcp_servers >>>";
    const END: &str = "# <<< joysafeter mcp_servers <<<";
    let mut base = String::new();
    let mut in_block = false;
    for line in existing.lines() {
        if line.trim_start().starts_with(BEGIN) {
            in_block = true;
            continue;
        }
        if line.trim_start().starts_with(END) {
            in_block = false;
            continue;
        }
        if !in_block {
            base.push_str(line);
            base.push('\n');
        }
    }
    // Ensure a trailing newline before our block.
    if !base.is_empty() && !base.ends_with('\n') {
        base.push('\n');
    }

    let mut block = String::new();
    block.push_str(BEGIN);
    block.push('\n');
    for server in servers {
        match server {
            McpServerConfig::Url { name, url } => {
                if name.is_empty() || url.is_empty() {
                    continue;
                }
                // TOML keys with hyphens / non-bare-key chars must be quoted.
                block.push_str(&format!("[mcp_servers.\"{}\"]\n", toml_escape(name)));
                block.push_str(&format!("url = \"{}\"\n", toml_escape(url)));
                block.push('\n');
            }
        }
    }
    block.push_str(END);
    block.push('\n');

    let final_contents = format!("{base}\n{block}");
    tokio::fs::write(&path, final_contents)
        .await
        .map_err(|e| format!("write {}: {e}", path.display()))?;
    info!(
        path = %path.display(),
        count = servers.len(),
        "Wrote codex MCP servers config"
    );
    Ok(())
}

/// Minimal TOML basic-string escaper (handles backslash and double-quote).
fn toml_escape(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}

#[cfg(test)]
mod tests {
    use super::*;

    static TEST_HOME_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

    #[test]
    fn failed_turn_extracts_error_for_terminal_result() {
        let turn = serde_json::json!({
            "status": "failed",
            "error": {"message": "model unavailable"}
        });
        assert_eq!(
            codex_turn_error(&turn).as_deref(),
            Some("model unavailable")
        );
    }

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

    #[test]
    fn approval_matches_tool_handles_exact_and_leading_word() {
        let rules: Vec<String> = vec!["Bash".into(), "Write".into()];
        assert!(super::approval_matches_tool(&rules, "Bash"));
        assert!(super::approval_matches_tool(&rules, "Bash (git)"));
        assert!(super::approval_matches_tool(&rules, "Write"));
        assert!(!super::approval_matches_tool(&rules, "Read"));
        assert!(!super::approval_matches_tool(&rules, "ApplyPatch"));
        assert!(!super::approval_matches_tool(&[], "Bash"));
        // Exact-match still wins when a rule includes the parens form
        let exact: Vec<String> = vec!["Bash (git)".into()];
        assert!(super::approval_matches_tool(&exact, "Bash (git)"));
        // …but doesn't accidentally match a different leading word
        assert!(!super::approval_matches_tool(&exact, "Read"));
    }

    #[test]
    fn approval_matches_tool_handles_mcp_server_granularity() {
        // Wildcard rule (what _build_permission_rules emits for a server-level
        // mcp_toolset) matches the derived ``mcp__server__*`` name.
        let wildcard: Vec<String> = vec!["mcp__echo-test__*".into()];
        assert!(super::approval_matches_tool(&wildcard, "mcp__echo-test__*"));
        // Per-tool rule still matches at server granularity (codex only gives
        // us the server name in elicitation requests).
        let per_tool: Vec<String> = vec!["mcp__echo-test__echo".into()];
        assert!(super::approval_matches_tool(&per_tool, "mcp__echo-test__*"));
        // A different server must NOT match.
        assert!(!super::approval_matches_tool(&wildcard, "mcp__other__*"));
        // MCP rule must not match a plain builtin tool and vice-versa.
        assert!(!super::approval_matches_tool(&wildcard, "Bash"));
        assert!(!super::approval_matches_tool(
            &["Bash".into()],
            "mcp__echo-test__*"
        ));
    }

    #[test]
    fn approval_kind_serializes_per_protocol() {
        use super::ApprovalKind;
        assert_eq!(
            ApprovalKind::from_method("item/commandExecution/requestApproval"),
            Some(ApprovalKind::ExecV2)
        );
        assert_eq!(
            ApprovalKind::from_method("applyPatchApproval"),
            Some(ApprovalKind::ExecV1)
        );
        assert_eq!(
            ApprovalKind::from_method("mcpServer/elicitation/request"),
            Some(ApprovalKind::McpElicitation)
        );
        assert_eq!(ApprovalKind::from_method("notifications/foo"), None);

        assert_eq!(
            ApprovalKind::ExecV2.result_json(true),
            serde_json::json!({"decision": "accept"})
        );
        assert_eq!(
            ApprovalKind::ExecV1.result_json(false),
            serde_json::json!({"decision": "denied"})
        );
        assert_eq!(
            ApprovalKind::McpElicitation.result_json(true),
            serde_json::json!({"action": "accept", "content": serde_json::Value::Null})
        );
        assert_eq!(
            ApprovalKind::McpElicitation.result_json(false),
            serde_json::json!({"action": "decline", "content": serde_json::Value::Null})
        );
    }

    #[test]
    fn derive_approval_tool_name_for_elicitation() {
        let params = serde_json::json!({"serverName": "echo-test", "turnId": "t1"});
        assert_eq!(
            super::derive_approval_tool_name("mcpServer/elicitation/request", &params),
            "mcp__echo-test__*"
        );
    }

    #[tokio::test]
    async fn merge_codex_mcp_servers_writes_toml_block() {
        use joysafeter_types::agent::McpServerConfig;

        let _guard = TEST_HOME_LOCK.lock().await;
        let tmp = std::env::temp_dir().join(format!("codex_mcp_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::env::set_var("HOME", &tmp);

        let servers = vec![McpServerConfig::Url {
            name: "echo-test".to_string(),
            url: "http://host.docker.internal:8765/".to_string(),
        }];
        super::merge_codex_mcp_servers(&servers).await.unwrap();

        let path = tmp.join(".codex/config.toml");
        let body = std::fs::read_to_string(&path).unwrap();
        assert!(
            body.contains("[mcp_servers.\"echo-test\"]"),
            "block missing: {body}"
        );
        assert!(body.contains("url = \"http://host.docker.internal:8765/\""));
        assert!(body.contains("# >>> joysafeter mcp_servers >>>"));

        // Second call replaces (does not stack) the managed block.
        super::merge_codex_mcp_servers(&servers).await.unwrap();
        let body2 = std::fs::read_to_string(&path).unwrap();
        let count = body2.matches("# >>> joysafeter mcp_servers >>>").count();
        assert_eq!(count, 1, "managed block must replace, not stack: {body2}");

        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[tokio::test]
    async fn merge_codex_mcp_servers_preserves_existing_file_content() {
        use joysafeter_types::agent::McpServerConfig;

        let _guard = TEST_HOME_LOCK.lock().await;
        let tmp = std::env::temp_dir().join(format!("codex_mcp_preserve_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(tmp.join(".codex")).unwrap();
        let path = tmp.join(".codex/config.toml");
        std::fs::write(
            &path,
            "model = \"gpt-5\"\n\n[model_providers.codex]\nname = \"codex\"\n",
        )
        .unwrap();

        std::env::set_var("HOME", &tmp);
        let servers = vec![McpServerConfig::Url {
            name: "echo".to_string(),
            url: "http://x:1/".to_string(),
        }];
        super::merge_codex_mcp_servers(&servers).await.unwrap();

        let body = std::fs::read_to_string(&path).unwrap();
        assert!(body.contains("model = \"gpt-5\""));
        assert!(body.contains("[model_providers.codex]"));
        assert!(body.contains("[mcp_servers.\"echo\"]"));

        let _ = std::fs::remove_dir_all(&tmp);
    }
}
