use async_trait::async_trait;
use joysafeter_types::harness::{
    HarnessAdapter, HarnessError, HarnessEvent, HarnessInput, RunningHarness,
};
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::sync::Mutex;
use tracing::info;

type SharedStdin = Arc<Mutex<Option<tokio::process::ChildStdin>>>;

pub struct PiAdapter {
    session: Arc<Mutex<Option<PersistentPi>>>,
}

struct PersistentPi {
    stdin: SharedStdin,
    #[allow(dead_code)]
    reader_handle: tokio::task::JoinHandle<()>,
    current_turn: Arc<Mutex<Option<TurnState>>>,
    child: tokio::process::Child,
}

struct TurnState {
    event_tx: tokio::sync::mpsc::Sender<HarnessEvent>,
    turn_done_tx: Option<tokio::sync::oneshot::Sender<bool>>,
    usage: Arc<std::sync::Mutex<joysafeter_types::token_usage::TokenUsage>>,
    output: Arc<std::sync::Mutex<String>>,
    call_id_to_tool: Arc<std::sync::Mutex<HashMap<String, String>>>,
}

impl Default for PiAdapter {
    fn default() -> Self {
        Self::new()
    }
}

impl PiAdapter {
    pub fn new() -> Self {
        Self {
            session: Arc::new(Mutex::new(None)),
        }
    }
}

#[async_trait]
impl HarnessAdapter for PiAdapter {
    async fn start(&self, input: HarnessInput, cwd: &Path) -> Result<RunningHarness, HarnessError> {
        use std::time::Instant;
        self.ensure_session(&input, cwd).await?;

        let start = Instant::now();
        let (event_tx, event_rx) = mpsc::channel(256);
        let (result_tx, result_rx) = oneshot::channel();

        let guard = self.session.lock().await;
        let session = guard
            .as_ref()
            .ok_or_else(|| HarnessError::StartFailed("session disappeared after ensure".into()))?;

        let (td_tx, td_rx) = oneshot::channel::<bool>();
        let usage = Arc::new(std::sync::Mutex::new(
            joysafeter_types::token_usage::TokenUsage::default(),
        ));
        let output = Arc::new(std::sync::Mutex::new(String::new()));
        {
            let mut ct = session.current_turn.lock().await;
            *ct = Some(TurnState {
                event_tx,
                turn_done_tx: Some(td_tx),
                usage: usage.clone(),
                output: output.clone(),
                call_id_to_tool: Arc::new(std::sync::Mutex::new(HashMap::new())),
            });
        }

        let stdin = session.stdin.clone();
        let prompt = input.prompt.clone();
        tokio::spawn(async move {
            let line = build_prompt_line(&prompt, &next_req_id());
            let mut g = stdin.lock().await;
            if let Some(ref mut stdin) = *g {
                let _ = stdin.write_all(line.as_bytes()).await;
                let _ = stdin.flush().await;
            }
        });

        let current_turn = session.current_turn.clone();
        let session_id = input.session_id.clone();
        let shared_stdin_for_harness = session.stdin.clone();
        drop(guard);

        tokio::spawn(async move {
            let aborted = td_rx.await.unwrap_or(true);
            let final_output = output.lock().unwrap().clone();
            let final_usage = usage.lock().unwrap().clone();
            {
                let mut ct = current_turn.lock().await;
                *ct = None;
            }
            let status = if aborted {
                joysafeter_types::harness::HarnessResultStatus::Aborted
            } else {
                joysafeter_types::harness::HarnessResultStatus::Completed
            };
            let _ = result_tx.send(joysafeter_types::harness::HarnessResult {
                status,
                output: final_output,
                error: None,
                session_id,
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
        Ok(())
    }
    fn provider(&self) -> &str {
        "pi"
    }
    async fn is_available(&self) -> bool {
        which::which("pi").is_ok()
    }
}

pub struct PiMapped {
    pub events: Vec<HarnessEvent>,
    pub turn_done: bool,
}

pub fn map_pi_event(
    event: &serde_json::Value,
    call_id_to_tool: &mut HashMap<String, String>,
) -> PiMapped {
    let mut events = Vec::new();
    let mut turn_done = false;
    let etype = event.get("type").and_then(|t| t.as_str()).unwrap_or("");

    match etype {
        "message_update" => {
            let ame = event.get("assistantMessageEvent");
            let ame_type = ame
                .and_then(|a| a.get("type"))
                .and_then(|t| t.as_str())
                .unwrap_or("");
            let delta = ame
                .and_then(|a| a.get("delta"))
                .and_then(|d| d.as_str())
                .unwrap_or("");
            match ame_type {
                "text_delta" if !delta.is_empty() => {
                    events.push(HarnessEvent::Text { content: delta.to_string() });
                }
                "thinking_delta" if !delta.is_empty() => {
                    events.push(HarnessEvent::Thinking { content: delta.to_string() });
                }
                _ => {}
            }
        }
        "tool_execution_start" => {
            let tool = event.get("toolName").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let call_id = event.get("toolCallId").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let input = event.get("args").cloned().unwrap_or(serde_json::Value::Null);
            call_id_to_tool.insert(call_id.clone(), tool.clone());
            events.push(HarnessEvent::ToolUse { tool, call_id, input, is_control_request: false });
        }
        "tool_execution_end" => {
            let call_id = event.get("toolCallId").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let tool = event
                .get("toolName")
                .and_then(|t| t.as_str())
                .map(|s| s.to_string())
                .or_else(|| call_id_to_tool.get(&call_id).cloned())
                .unwrap_or_default();
            let result = event.get("result");
            let output = match result {
                Some(serde_json::Value::String(s)) => s.clone(),
                Some(v) => v.to_string(),
                None => String::new(),
            };
            if event.get("isError").and_then(|b| b.as_bool()).unwrap_or(false) {
                events.push(HarnessEvent::Error { message: output.clone() });
            }
            events.push(HarnessEvent::ToolResult { tool, call_id, output });
        }
        "message_end" => {
            if let Some(message) = event.get("message") {
                let model = message.get("model").and_then(|m| m.as_str()).unwrap_or("unknown").to_string();
                if let Some(usage) = message.get("usage") {
                    let g = |k: &str| usage.get(k).and_then(|v| v.as_u64()).unwrap_or(0);
                    events.push(HarnessEvent::ModelRequestEnd {
                        model,
                        input_tokens: g("input"),
                        output_tokens: g("output"),
                        cache_read_tokens: g("cacheRead"),
                        cache_write_tokens: g("cacheWrite"),
                    });
                }
            }
        }
        "agent_settled" => {
            turn_done = true;
        }
        "error" => {
            let msg = event.get("message").and_then(|m| m.as_str()).unwrap_or("pi error").to_string();
            events.push(HarnessEvent::Error { message: msg });
        }
        _ => {}
    }

    PiMapped { events, turn_done }
}

/// 解析并分发单行 pi stdout。返回 true 表示该行是 agent_settled(turn 完成)。
/// 响应行(type=="response")跳过。
pub(crate) async fn dispatch_pi_line(
    line: &str,
    event_tx: &mpsc::Sender<HarnessEvent>,
    call_id_to_tool: &mut HashMap<String, String>,
) -> bool {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return false;
    }
    let value: serde_json::Value = match serde_json::from_str(trimmed) {
        Ok(v) => v,
        Err(_) => return false,
    };
    if value.get("type").and_then(|t| t.as_str()) == Some("response") {
        return false;
    }
    let mapped = map_pi_event(&value, call_id_to_tool);
    for ev in mapped.events {
        let _ = event_tx.send(ev).await;
    }
    mapped.turn_done
}

async fn persistent_pi_reader(
    stdout: tokio::process::ChildStdout,
    current_turn: Arc<Mutex<Option<TurnState>>>,
) {
    let reader = BufReader::new(stdout);
    let mut lines = reader.lines();
    let mut call_id_to_tool: HashMap<String, String> = HashMap::new();

    while let Ok(Some(line)) = lines.next_line().await {
        let refs = {
            let guard = current_turn.lock().await;
            guard
                .as_ref()
                .map(|t| (t.event_tx.clone(), t.usage.clone(), t.output.clone()))
        };
        let Some((event_tx, usage, output)) = refs else {
            continue;
        };

        if let Ok(v) = serde_json::from_str::<serde_json::Value>(line.trim()) {
            accumulate_usage_and_output(&v, &usage, &output);
        }

        let turn_done = dispatch_pi_line(&line, &event_tx, &mut call_id_to_tool).await;
        if turn_done {
            let mut guard = current_turn.lock().await;
            if let Some(ref mut t) = *guard {
                if let Some(tx) = t.turn_done_tx.take() {
                    let _ = tx.send(false);
                }
            }
        }
    }

    info!("pi stdout reader exiting (process closed stdout)");
    let mut guard = current_turn.lock().await;
    if let Some(ref mut t) = *guard {
        if let Some(tx) = t.turn_done_tx.take() {
            let _ = tx.send(true);
        }
    }
}

/// 旁路:把 message_end.usage 累加进 TokenUsage(含 by_model),把 text_delta 追加进 output。
fn accumulate_usage_and_output(
    v: &serde_json::Value,
    usage: &Arc<std::sync::Mutex<joysafeter_types::token_usage::TokenUsage>>,
    output: &Arc<std::sync::Mutex<String>>,
) {
    use joysafeter_types::token_usage::ModelUsage;
    match v.get("type").and_then(|t| t.as_str()) {
        Some("message_update") => {
            if let Some(ame) = v.get("assistantMessageEvent") {
                if ame.get("type").and_then(|t| t.as_str()) == Some("text_delta") {
                    if let Some(d) = ame.get("delta").and_then(|d| d.as_str()) {
                        output.lock().unwrap().push_str(d);
                    }
                }
            }
        }
        Some("message_end") => {
            if let Some(u) = v.get("message").and_then(|m| m.get("usage")) {
                let g = |k: &str| u.get(k).and_then(|x| x.as_u64()).unwrap_or(0);
                let model = v
                    .get("message")
                    .and_then(|m| m.get("model"))
                    .and_then(|m| m.as_str())
                    .unwrap_or("unknown")
                    .to_string();
                let mut acc = usage.lock().unwrap();
                acc.input_tokens += g("input");
                acc.output_tokens += g("output");
                acc.cache_read_tokens += g("cacheRead");
                acc.cache_write_tokens += g("cacheWrite");
                let e = acc.by_model.entry(model).or_insert_with(ModelUsage::default);
                e.input_tokens += g("input");
                e.output_tokens += g("output");
                e.cache_read_tokens += g("cacheRead");
                e.cache_write_tokens += g("cacheWrite");
            }
        }
        _ => {}
    }
}

pub(crate) fn build_prompt_line(message: &str, id: &str) -> String {
    let v = serde_json::json!({ "type": "prompt", "message": message, "id": id });
    format!("{}\n", v)
}

fn next_req_id() -> String {
    let n = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    format!("req_{n}")
}

impl PiAdapter {
    async fn ensure_session(&self, input: &HarnessInput, cwd: &Path) -> Result<(), HarnessError> {
        let mut guard = self.session.lock().await;

        let alive = if let Some(ref mut s) = *guard {
            matches!(s.child.try_wait(), Ok(None))
        } else {
            false
        };
        if alive {
            return Ok(());
        }
        if let Some(ref mut old) = guard.take() {
            let _ = old.child.start_kill();
            let _ = old.child.wait().await;
        }

        let mut args = vec!["--mode".to_string(), "rpc".to_string()];
        if let Some(model) = &input.model {
            args.extend(["--model".to_string(), model.clone()]);
        }

        let mut cmd = Command::new("pi");
        cmd.args(&args)
            .current_dir(cwd)
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
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| HarnessError::StartFailed("failed to open stdout".into()))?;

        let current_turn: Arc<Mutex<Option<TurnState>>> = Arc::new(Mutex::new(None));
        let reader_current_turn = current_turn.clone();
        let reader_handle = tokio::spawn(async move {
            persistent_pi_reader(stdout, reader_current_turn).await;
        });

        info!("Started persistent pi process");
        *guard = Some(PersistentPi {
            stdin: Arc::new(Mutex::new(Some(stdin))),
            reader_handle,
            current_turn,
            child,
        });
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use joysafeter_types::harness::HarnessEvent;

    fn map(v: serde_json::Value) -> PiMapped {
        let mut m = HashMap::new();
        map_pi_event(&v, &mut m)
    }

    #[test]
    fn text_delta_maps_to_text() {
        let m = map(serde_json::json!({
            "type": "message_update",
            "assistantMessageEvent": { "type": "text_delta", "delta": "hello" }
        }));
        assert!(matches!(&m.events[0], HarnessEvent::Text { content } if content == "hello"));
    }

    #[test]
    fn thinking_delta_maps_to_thinking() {
        let m = map(serde_json::json!({
            "type": "message_update",
            "assistantMessageEvent": { "type": "thinking_delta", "delta": "hmm" }
        }));
        assert!(matches!(&m.events[0], HarnessEvent::Thinking { content } if content == "hmm"));
    }

    #[test]
    fn tool_execution_start_maps_to_tool_use() {
        let m = map(serde_json::json!({
            "type": "tool_execution_start",
            "toolCallId": "call_1", "toolName": "bash",
            "args": { "command": "ls" }
        }));
        match &m.events[0] {
            HarnessEvent::ToolUse { tool, call_id, is_control_request, .. } => {
                assert_eq!(tool, "bash");
                assert_eq!(call_id, "call_1");
                assert!(!is_control_request);
            }
            other => panic!("expected ToolUse, got {other:?}"),
        }
    }

    #[test]
    fn tool_execution_end_maps_to_tool_result() {
        let mut cmap = HashMap::new();
        map_pi_event(&serde_json::json!({
            "type": "tool_execution_start",
            "toolCallId": "call_1", "toolName": "bash", "args": {}
        }), &mut cmap);
        let m = map_pi_event(&serde_json::json!({
            "type": "tool_execution_end",
            "toolCallId": "call_1", "toolName": "bash",
            "result": "file.txt", "isError": false
        }), &mut cmap);
        match &m.events[0] {
            HarnessEvent::ToolResult { tool, call_id, output } => {
                assert_eq!(tool, "bash");
                assert_eq!(call_id, "call_1");
                assert!(output.contains("file.txt"));
            }
            other => panic!("expected ToolResult, got {other:?}"),
        }
    }

    #[test]
    fn message_end_usage_maps_to_model_request_end() {
        let m = map(serde_json::json!({
            "type": "message_end",
            "message": {
                "model": "deepseek/deepseek-chat",
                "usage": { "input": 10, "output": 5, "cacheRead": 2, "cacheWrite": 1 }
            }
        }));
        let mre = m.events.iter().find(|e| matches!(e, HarnessEvent::ModelRequestEnd { .. }))
            .expect("expected ModelRequestEnd");
        match mre {
            HarnessEvent::ModelRequestEnd { model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens } => {
                assert_eq!(model, "deepseek/deepseek-chat");
                assert_eq!(*input_tokens, 10);
                assert_eq!(*output_tokens, 5);
                assert_eq!(*cache_read_tokens, 2);
                assert_eq!(*cache_write_tokens, 1);
            }
            _ => unreachable!(),
        }
    }

    #[test]
    fn agent_settled_sets_turn_done() {
        let m = map(serde_json::json!({ "type": "agent_settled" }));
        assert!(m.turn_done);
    }

    #[test]
    fn unknown_event_is_ignored() {
        let m = map(serde_json::json!({ "type": "queue_update", "foo": 1 }));
        assert!(m.events.is_empty());
        assert!(!m.turn_done);
    }

    #[tokio::test]
    async fn adapter_reports_pi_provider() {
        let adapter = super::PiAdapter::new();
        assert_eq!(adapter.provider(), "pi");
    }

    #[tokio::test]
    async fn dispatch_line_forwards_events_to_channel() {
        let (tx, mut rx) = tokio::sync::mpsc::channel::<HarnessEvent>(16);
        let mut cmap = HashMap::new();
        let line = r#"{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"hi"}}"#;
        super::dispatch_pi_line(line, &tx, &mut cmap).await;
        match rx.recv().await {
            Some(HarnessEvent::Text { content }) => assert_eq!(content, "hi"),
            other => panic!("expected Text, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn dispatch_line_reports_turn_done_on_settled() {
        let (tx, _rx) = tokio::sync::mpsc::channel::<HarnessEvent>(16);
        let mut cmap = HashMap::new();
        let done = super::dispatch_pi_line(r#"{"type":"agent_settled"}"#, &tx, &mut cmap).await;
        assert!(done);
    }

    #[test]
    fn build_prompt_line_is_valid_jsonl() {
        let line = super::build_prompt_line("hello world", "req_1");
        let v: serde_json::Value = serde_json::from_str(line.trim_end()).unwrap();
        assert_eq!(v["type"], "prompt");
        assert_eq!(v["message"], "hello world");
        assert_eq!(v["id"], "req_1");
        assert!(line.ends_with('\n'));
    }

    #[tokio::test]
    async fn dispatch_line_ignores_response_lines() {
        let (tx, mut rx) = tokio::sync::mpsc::channel::<HarnessEvent>(16);
        let mut cmap = HashMap::new();
        let done = super::dispatch_pi_line(
            r#"{"type":"response","command":"prompt","success":true,"id":"req_1"}"#,
            &tx,
            &mut cmap,
        )
        .await;
        assert!(!done);
        assert!(rx.try_recv().is_err());
    }
}
