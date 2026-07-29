use async_trait::async_trait;
use axum::body::{Body, Bytes};
use axum::extract::{OriginalUri, State};
use axum::http::{HeaderMap, Method, Response};
use axum::routing::any;
use axum::Router;
use joysafeter_types::harness::{
    HarnessAdapter, HarnessError, HarnessEvent, HarnessInput, HarnessResult, HarnessResultStatus,
    RunningHarness,
};
use joysafeter_types::token_usage::{ModelUsage, TokenUsage};
use serde::Deserialize;
use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::net::SocketAddr;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpListener;
use tokio::process::Command;
use tokio::sync::{mpsc, oneshot, Mutex};
use tracing::{info, warn};

type SharedStdin = Arc<Mutex<Option<tokio::process::ChildStdin>>>;
const LIVE_INPUT_PREFIX: &str = "__joysafeter_input_v1__:";
const BASIC_CLAUDE_TOOLS: &str = "Bash,Read,Edit,Write";

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

struct PersistentClaude {
    stdin: SharedStdin,
    #[allow(dead_code)]
    reader_handle: tokio::task::JoinHandle<()>,
    compat_proxy_handle: Option<tokio::task::JoinHandle<()>>,
    current_turn: Arc<Mutex<Option<TurnState>>>,
    child: tokio::process::Child,
    config_fingerprint: u64,
    last_session_id: Arc<std::sync::Mutex<Option<String>>>,
}

#[derive(Clone)]
struct AnthropicCompatProxyState {
    client: reqwest::Client,
    upstream_base_url: String,
}

fn merged_command_env(input: &HarnessInput) -> HashMap<String, String> {
    let mut env = input.env.clone();
    for (k, v) in &input.secrets {
        env.insert(k.clone(), v.clone());
    }
    env
}

fn anthropic_base_url(input: &HarnessInput) -> Option<String> {
    input
        .secrets
        .get("ANTHROPIC_BASE_URL")
        .or_else(|| input.env.get("ANTHROPIC_BASE_URL"))
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

fn anthropic_compat_mode_enabled(input: &HarnessInput) -> bool {
    let explicit = input
        .secrets
        .get("ANTHROPIC_CLAUDE_CODE_COMPAT")
        .or_else(|| input.env.get("ANTHROPIC_CLAUDE_CODE_COMPAT"))
        .map(|v| v.trim().to_ascii_lowercase());
    if let Some(value) = explicit {
        return !matches!(value.as_str(), "0" | "false" | "no" | "off" | "disabled");
    }

    anthropic_base_url(input)
        .map(|url| {
            let url = url.to_ascii_lowercase();
            url.contains("ai-api.jdcloud.com/anthropic") || url.contains("jdcloud.com/anthropic")
        })
        .unwrap_or(false)
}

fn truncate_for_diagnostics(value: &str, max_chars: usize) -> String {
    let mut out = String::new();
    for (idx, ch) in value.chars().enumerate() {
        if idx >= max_chars {
            out.push_str("...");
            return out;
        }
        out.push(ch);
    }
    out
}

fn format_anthropic_compat_error_body(status: u16, body: &[u8]) -> String {
    let upstream_body = String::from_utf8_lossy(body).trim().to_string();
    let upstream_body = if upstream_body.is_empty() {
        "<empty response body>".to_string()
    } else {
        truncate_for_diagnostics(&upstream_body, 4000)
    };
    let message = format!(
        "API Error: {status} 模型服务调用失败\n\nHTTP {status}\n\nUpstream response:\n{upstream_body}"
    );
    serde_json::json!({
        "type": "error",
        "error": {
            "type": "model_service_error",
            "message": message,
            "status_code": status,
            "upstream_body": upstream_body,
        }
    })
    .to_string()
}

fn sanitize_anthropic_compat_request_body(body: Bytes) -> Bytes {
    let Ok(mut value) = serde_json::from_slice::<serde_json::Value>(&body) else {
        return body;
    };
    let Some(object) = value.as_object_mut() else {
        return body;
    };
    if object.remove("context_management").is_none() {
        return body;
    }
    serde_json::to_vec(&value).map(Bytes::from).unwrap_or(body)
}

fn build_claude_args(
    input: &HarnessInput,
    resume_session_id: Option<&String>,
    system_prompt: Option<&String>,
    compat_mode: bool,
) -> Vec<String> {
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

    if compat_mode {
        args.extend([
            "--bare".to_string(),
            "--tools".to_string(),
            BASIC_CLAUDE_TOOLS.to_string(),
        ]);
    }
    if let Some(model) = &input.model {
        args.extend(["--model".to_string(), model.clone()]);
    }
    if let Some(session_id) = resume_session_id {
        args.extend(["--resume".to_string(), session_id.clone()]);
    }
    if let Some(system_prompt) = system_prompt {
        args.extend(["--append-system-prompt".to_string(), system_prompt.clone()]);
    }
    args
}

async fn start_anthropic_compat_proxy(
    upstream_base_url: String,
) -> Result<(String, tokio::task::JoinHandle<()>), HarnessError> {
    let state = AnthropicCompatProxyState {
        client: reqwest::Client::new(),
        upstream_base_url: upstream_base_url.trim_end_matches('/').to_string(),
    };
    let app = Router::new()
        .fallback(any(anthropic_compat_proxy_handler))
        .with_state(state);
    let listener = TcpListener::bind(("127.0.0.1", 0)).await?;
    let addr: SocketAddr = listener.local_addr()?;
    let proxy_base_url = format!("http://{addr}/anthropic");
    let handle = tokio::spawn(async move {
        if let Err(error) = axum::serve(listener, app).await {
            warn!(error = %error, "Anthropic compatibility proxy stopped");
        }
    });
    Ok((proxy_base_url, handle))
}

async fn anthropic_compat_proxy_handler(
    State(state): State<AnthropicCompatProxyState>,
    method: Method,
    OriginalUri(uri): OriginalUri,
    headers: HeaderMap,
    body: Bytes,
) -> Response<Body> {
    let path_and_query = uri
        .path_and_query()
        .map(|pq| pq.as_str())
        .unwrap_or("/");
    let upstream_path = path_and_query
        .strip_prefix("/anthropic")
        .filter(|path| !path.is_empty())
        .unwrap_or("/");
    let upstream_url = format!("{}{}", state.upstream_base_url, upstream_path);

    let mut request = state.client.request(method.clone(), upstream_url);
    for (name, value) in headers.iter() {
        let header_name = name.as_str();
        if header_name.eq_ignore_ascii_case("host")
            || header_name.eq_ignore_ascii_case("content-length")
            || header_name.eq_ignore_ascii_case("anthropic-beta")
        {
            continue;
        }
        request = request.header(name, value);
    }
    if method != Method::HEAD {
        request = request.body(sanitize_anthropic_compat_request_body(body));
    }

    match request.send().await {
        Ok(upstream) => {
            let status = upstream.status();
            let headers = upstream.headers().clone();
            match upstream.bytes().await {
                Ok(bytes) => {
                    let mut builder = Response::builder().status(status);
                    for (name, value) in headers.iter() {
                        let header_name = name.as_str();
                        if header_name.eq_ignore_ascii_case("content-length")
                            || header_name.eq_ignore_ascii_case("transfer-encoding")
                        {
                            continue;
                        }
                        builder = builder.header(name, value);
                    }
                    if !status.is_success() {
                        let detail = format_anthropic_compat_error_body(status.as_u16(), &bytes);
                        warn!(
                            status = status.as_u16(),
                            upstream_body = %truncate_for_diagnostics(&String::from_utf8_lossy(&bytes), 2000),
                            "Anthropic compatibility proxy upstream request failed"
                        );
                        builder = builder.header("content-type", "application/json");
                        return builder
                            .body(Body::from(detail))
                            .unwrap_or_else(|_| Response::new(Body::from("proxy response build failed")));
                    }
                    builder
                        .body(Body::from(bytes))
                        .unwrap_or_else(|_| Response::new(Body::from("proxy response build failed")))
                }
                Err(error) => Response::builder()
                    .status(502)
                    .body(Body::from(format!("proxy upstream read failed: {error}")))
                    .unwrap_or_else(|_| Response::new(Body::from("proxy upstream read failed"))),
            }
        }
        Err(error) => Response::builder()
            .status(502)
            .body(Body::from(format!("proxy upstream request failed: {error}")))
            .unwrap_or_else(|_| Response::new(Body::from("proxy upstream request failed"))),
    }
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
            if let Some(handle) = old.compat_proxy_handle.take() {
                handle.abort();
            }
            let _ = old.child.start_kill();
            let _ = old.child.wait().await;
        }

        // Determine session_id for --resume: prefer input.session_id (from orchestrator DB),
        // fall back to last_session_id from previous turn (for crash recovery within same adapter).
        let resume_session_id = input.session_id.clone();
        let compat_mode = anthropic_compat_mode_enabled(input);
        let args = build_claude_args(
            input,
            resume_session_id.as_ref(),
            input.system_prompt.as_ref(),
            compat_mode,
        );
        let mut command_env = merged_command_env(input);
        let mut compat_proxy_handle = None;
        if compat_mode {
            if let Some(base_url) = anthropic_base_url(input) {
                let (proxy_base_url, proxy_handle) = start_anthropic_compat_proxy(base_url).await?;
                command_env.insert("ANTHROPIC_BASE_URL".to_string(), proxy_base_url);
                compat_proxy_handle = Some(proxy_handle);
                info!("Started Anthropic compatibility proxy for Claude Code");
            }
        }

        let mut cmd = Command::new("claude");
        cmd.args(&args)
            .current_dir(cwd)
            .env("HOME", cwd.to_string_lossy().to_string())
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        for (k, v) in &command_env {
            cmd.env(k, v);
        }

        let mut child = match cmd.spawn() {
            Ok(child) => child,
            Err(error) => {
                if let Some(handle) = compat_proxy_handle {
                    handle.abort();
                }
                return Err(HarnessError::StartFailed(error.to_string()));
            }
        };

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
            persistent_claude_reader(stdout, reader_current_turn, reader_last_session_id).await;
        });

        info!("Started persistent claude process");

        *guard = Some(PersistentClaude {
            stdin: shared_stdin,
            reader_handle,
            compat_proxy_handle,
            current_turn,
            child,
            config_fingerprint: fp,
            last_session_id,
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
                if let Some(handle) = s.compat_proxy_handle.take() {
                    handle.abort();
                }
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
    last_session_id: Arc<std::sync::Mutex<Option<String>>>,
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
                    *session_id.lock().unwrap() = Some(sid.clone());
                    *last_session_id.lock().unwrap() = Some(sid.clone());
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
                    if let Some(task_id) = msg.task_id.clone() {
                        let (total_tokens, tool_uses, duration_ms) = match msg.usage {
                            Some(u) => (u.total_tokens, u.tool_uses, u.duration_ms),
                            None => (None, None, None),
                        };
                        let _ = event_tx
                            .send(HarnessEvent::TaskNotification {
                                phase: phase.to_string(),
                                task_id,
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
                                entry.cache_read_tokens =
                                    pull(Some(mu), "cachedInputTokens")
                                        .max(pull(Some(mu), "cache_read_input_tokens"));
                                entry.cache_write_tokens =
                                    pull(Some(mu), "uncachedInputTokens")
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
        let fp1 = ClaudeAdapter::compute_fingerprint(&input);
        let fp2 = ClaudeAdapter::compute_fingerprint(&input);
        assert_eq!(fp1, fp2);
    }

    #[test]
    fn compute_fingerprint_ignores_prompt_and_session_id() {
        let input1 = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
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
            ClaudeAdapter::compute_fingerprint(&input1),
            ClaudeAdapter::compute_fingerprint(&input2)
        );
    }

    #[test]
    fn compute_fingerprint_differs_on_model_change() {
        let input1 = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
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
            ClaudeAdapter::compute_fingerprint(&input1),
            ClaudeAdapter::compute_fingerprint(&input2)
        );
    }

    #[test]
    fn jd_anthropic_base_url_uses_compat_cli_args() {
        let input = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
            session_id: None,
            model: None,
            max_turns: None,
            timeout: Duration::from_secs(60),
            env: HashMap::new(),
            secrets: HashMap::from([(
                "ANTHROPIC_BASE_URL".into(),
                "http://ai-api.jdcloud.com/anthropic".into(),
            )]),
            mcp_configs: vec![],
            permission_mode: "bypassPermissions".into(),
            allowed_tools: vec![],
            ask_tools: vec![],
        };

        let args = build_claude_args(&input, None, None, true);

        assert!(args.contains(&"--bare".to_string()));
        assert!(args.contains(&"--tools".to_string()));
        assert!(args.contains(&"Bash,Read,Edit,Write".to_string()));
    }

    #[test]
    fn compat_cli_args_can_be_disabled() {
        let input = HarnessInput {
            prompt: "hello".into(),
            system_prompt: None,
            session_id: None,
            model: None,
            max_turns: None,
            timeout: Duration::from_secs(60),
            env: HashMap::new(),
            secrets: HashMap::from([
                (
                    "ANTHROPIC_BASE_URL".into(),
                    "http://ai-api.jdcloud.com/anthropic".into(),
                ),
                ("ANTHROPIC_CLAUDE_CODE_COMPAT".into(), "false".into()),
            ]),
            mcp_configs: vec![],
            permission_mode: "bypassPermissions".into(),
            allowed_tools: vec![],
            ask_tools: vec![],
        };

        assert!(!anthropic_compat_mode_enabled(&input));
    }

    #[test]
    fn compat_proxy_error_body_includes_upstream_detail() {
        let body = br#"{"error":{"message":"invalid model: claude-4","type":"invalid_request_error"}}"#;

        let formatted = format_anthropic_compat_error_body(400, body);

        assert!(formatted.contains("HTTP 400"));
        assert!(formatted.contains("模型服务调用失败"));
        assert!(formatted.contains("invalid model: claude-4"));
        assert!(formatted.contains("invalid_request_error"));
    }

    #[test]
    fn compat_proxy_request_body_removes_unsupported_context_management() {
        let body = Bytes::from_static(
            br#"{"model":"claude","messages":[],"context_management":{"context_id":"ctx_123"}}"#,
        );

        let sanitized = sanitize_anthropic_compat_request_body(body);
        let value: serde_json::Value = serde_json::from_slice(&sanitized).unwrap();

        assert_eq!(value["model"], "claude");
        assert_eq!(value["messages"], serde_json::json!([]));
        assert!(value.get("context_management").is_none());
    }
}
