# pi 引擎接入 JoySafeter 沙箱 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 pi(`@earendil-works/pi-coding-agent`)接入为 JoySafeter 沙箱第四个引擎(`pi`),与 claude/codex/native 全功能对齐(多轮 / steering / 工具事件 / token 计费)。

**Architecture:** 新增 Rust 运行时适配器 `PiAdapter` 实现 `HarnessAdapter`,以常驻 `pi --mode rpc`(JSONL 行协议)子进程驱动;把 pi 的 `JsonAgentSessionEvent` 翻译成规范化 `HarnessEvent`。打包为独立 Docker 镜像 `joysafeter-pi`(统一 base + `joysafeter-runner` + npm 装 pi)。凭证走现有 Envoy 重注入。

**Tech Stack:** Rust(tokio、async-trait、serde_json)、TypeScript/Node ≥22.19(pi)、Docker、GitHub Actions、Python(FastAPI settings)。

## Global Constraints

- pi 镜像 Node 运行时 **≥ 22.19.0**(pi `engines.node`)。
- **pin 死 pi 版本**:Dockerfile 用 `ARG PI_VERSION=<x.y.z>`,不用 `latest`(pi 协议标注 experimental、无兼容保证)。
- 引擎标识字符串处处为 **`"pi"`**。
- Rust 测试:`cd sandbox-runner && cargo test -p joysafeter-runtime`。
- 后端测试:`cd backend && uv run pytest`(必须在 `backend/` 下跑,见仓库 CLAUDE.md)。
- pi **必须有自己的镜像**,`image_for_provider` 不得回退到其他引擎镜像(否则容器内 runner 未注册 pi adapter → "No adapter for provider: pi",见 `config.rs:381-385`)。
- 权限模型 = **全放行靠容器兜底**;`HarnessInput.allowed_tools/ask_tools` 不落地为 ask 流。
- 出网 = **复用现有 Envoy 重注入**(`llm_providers.rs`),不新造机制。
- pi rpc 协议(源码事实,已核对):
  - client→pi(stdin JSONL):`{"type":"prompt","message":<str>,"id":"req_N"}`、`{"type":"steer","message":<str>,"id":..}`、`{"type":"abort","id":..}`、`{"type":"new_session","id":..}`、`{"type":"set_model","provider":..,"modelId":..,"id":..}`。
  - pi→client(stdout JSONL):响应行 `{"type":"response","command":..,"success":bool,"id":..}`;其余为事件 `JsonAgentSessionEvent`。
  - 事件字段(源码 `core/agent-session.ts` / `agent/src/proxy.ts` / `ai/src/types.ts`):
    - `{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":<str>}}`(及 `thinking_delta`)
    - `{"type":"tool_execution_start","toolCallId":<str>,"toolName":<str>,"args":<obj>}`
    - `{"type":"tool_execution_end","toolCallId":<str>,"toolName":<str>,"result":<any>,"isError":<bool>}`
    - `{"type":"message_end","message":{"model":<str>,"usage":{"input":n,"output":n,"cacheRead":n,"cacheWrite":n}}}`
    - `{"type":"agent_settled"}` = 一轮完成/空闲信号。

---

### Task 1: pi 事件映射纯函数

把单条 pi 事件翻译成 `HarnessEvent`。纯函数、无子进程,可独立单测。这是适配器核心,先做以解锁 reader loop。

**Files:**
- Create: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs`
- Test: 同文件 `#[cfg(test)] mod tests`

**Interfaces:**
- Produces:
  - `struct PiMapped { pub events: Vec<HarnessEvent>, pub turn_done: bool }`
  - `fn map_pi_event(event: &serde_json::Value, call_id_to_tool: &mut std::collections::HashMap<String, String>) -> PiMapped`

- [ ] **Step 1: 写失败测试**

在新文件 `pi.rs` 顶部放最小骨架 + 测试:

```rust
use joysafeter_types::harness::HarnessEvent;
use std::collections::HashMap;

pub struct PiMapped {
    pub events: Vec<HarnessEvent>,
    pub turn_done: bool,
}

pub fn map_pi_event(
    _event: &serde_json::Value,
    _call_id_to_tool: &mut HashMap<String, String>,
) -> PiMapped {
    PiMapped { events: vec![], turn_done: false }
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
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi::tests`
Expected: FAIL(断言不通过,events 为空)

- [ ] **Step 3: 实现 `map_pi_event`**

替换 Step 1 的桩实现:

```rust
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
```

在文件顶部补齐 imports:`use joysafeter_types::harness::{HarnessEvent};`(已在 Step 1)。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi::tests`
Expected: PASS(7 个测试全绿)

- [ ] **Step 5: 提交**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "feat(runtime): add pi event mapping pure function"
```

---

### Task 2: PiAdapter 骨架 + 注册

补上 `HarnessAdapter` 骨架(struct / new / provider / is_available),注册进 `AdapterRegistry::discover()` + mock 分支。此刻 `start` 先返回未实现错误,后续任务填充。

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs`
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/lib.rs`

**Interfaces:**
- Consumes: `map_pi_event`(Task 1)
- Produces: `pub struct PiAdapter`(impl `HarnessAdapter`,`provider()=="pi"`,`is_available()` via `which::which("pi")`)

- [ ] **Step 1: 写失败测试(provider 名 + 可用性探测)**

在 `pi.rs` 的 tests 模块追加:

```rust
    #[tokio::test]
    async fn adapter_reports_pi_provider() {
        let adapter = super::PiAdapter::new();
        assert_eq!(adapter.provider(), "pi");
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi::tests::adapter_reports_pi_provider`
Expected: FAIL(`PiAdapter` 未定义)

- [ ] **Step 3: 实现骨架**

在 `pi.rs` 顶部 imports 之后加入(参照 `native.rs` 的持久会话结构,`start` 暂返回未实现):

```rust
use async_trait::async_trait;
use joysafeter_types::harness::{
    HarnessAdapter, HarnessError, HarnessInput, RunningHarness,
};
use std::path::Path;
use std::sync::Arc;
use tokio::sync::Mutex;

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
    fn default() -> Self { Self::new() }
}

impl PiAdapter {
    pub fn new() -> Self {
        Self { session: Arc::new(Mutex::new(None)) }
    }
}

#[async_trait]
impl HarnessAdapter for PiAdapter {
    async fn start(&self, _input: HarnessInput, _cwd: &Path) -> Result<RunningHarness, HarnessError> {
        Err(HarnessError::StartFailed("pi start not yet implemented".into()))
    }
    async fn cancel(&self, _harness: &mut RunningHarness) -> Result<(), HarnessError> { Ok(()) }
    fn provider(&self) -> &str { "pi" }
    async fn is_available(&self) -> bool { which::which("pi").is_ok() }
}
```

- [ ] **Step 4: 注册进 discover() + mock 分支**

Modify `lib.rs`:第 4 行后加 `pub mod pi;`;在 mock 分支(约第 22-34 行)追加:

```rust
            adapters.insert("pi".to_string(), Arc::new(mock::MockAdapter::new("pi")));
```

在真实分支(约第 46-49 行 codex 之后)追加:

```rust
            let pi_adapter = pi::PiAdapter::new();
            if pi_adapter.is_available().await {
                adapters.insert("pi".to_string(), Arc::new(pi_adapter));
            }
```

- [ ] **Step 5: 跑测试确认通过 + 编译**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi::tests && cargo build -p joysafeter-runtime`
Expected: PASS + 编译通过

- [ ] **Step 6: 提交**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs sandbox-runner/crates/joysafeter-runtime/src/lib.rs
git commit -m "feat(runtime): add PiAdapter skeleton and register it"
```

---

### Task 3: 常驻会话 spawn + stdout reader loop

拉起 `pi --mode rpc`,建立持久 reader,把每行事件经 `map_pi_event` 转发到当前 turn 的事件通道;`agent_settled` 触发 turn 完成。

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs`

**Interfaces:**
- Consumes: `map_pi_event`、`PersistentPi`、`TurnState`(Task 1/2)
- Produces: `impl PiAdapter { async fn ensure_session(&self, input: &HarnessInput, cwd: &Path) -> Result<(), HarnessError> }`;`async fn persistent_pi_reader(stdout, current_turn)`

- [ ] **Step 1: 写失败测试(reader 把一行 message_update 转成 Text 事件)**

reader 依赖真实子进程,难纯单测;改为测试"reader 的核心分发逻辑"提取出的辅助:reader 每行调用 `map_pi_event` 并把 events 送入 channel。写一个针对该行为的测试:

```rust
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

    #[tokio::test]
    async fn dispatch_line_ignores_response_lines() {
        let (tx, mut rx) = tokio::sync::mpsc::channel::<HarnessEvent>(16);
        let mut cmap = HashMap::new();
        let done = super::dispatch_pi_line(
            r#"{"type":"response","command":"prompt","success":true,"id":"req_1"}"#,
            &tx, &mut cmap,
        ).await;
        assert!(!done);
        assert!(rx.try_recv().is_err());
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi::tests::dispatch`
Expected: FAIL(`dispatch_pi_line` 未定义)

- [ ] **Step 3: 实现 `dispatch_pi_line` + reader + ensure_session**

在 `pi.rs` 追加(补 imports:`use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader}; use tokio::process::Command; use tokio::sync::{mpsc, oneshot}; use tracing::{info, warn};`):

```rust
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
        // 抓取当前 turn 的通道 + usage/output 累加器
        let refs = {
            let guard = current_turn.lock().await;
            guard.as_ref().map(|t| (t.event_tx.clone(), t.usage.clone(), t.output.clone()))
        };
        let Some((event_tx, usage, output)) = refs else { continue };

        // 先解析出事件用于旁路累加(token / output 文本),再分发
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

    // stdout 关闭 = 进程退出,通知当前 turn 中止
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
                let model = v.get("message").and_then(|m| m.get("model"))
                    .and_then(|m| m.as_str()).unwrap_or("unknown").to_string();
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
            // pi 接受 "<provider>/<pattern>" 或裸 pattern
            args.extend(["--model".to_string(), model.clone()]);
        }

        let mut cmd = Command::new("pi");
        cmd.args(&args)
            .current_dir(cwd)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());
        for (k, v) in &input.env { cmd.env(k, v); }
        for (k, v) in &input.secrets { cmd.env(k, v); }

        let mut child = cmd.spawn().map_err(|e| HarnessError::StartFailed(e.to_string()))?;
        let stdin = child.stdin.take()
            .ok_or_else(|| HarnessError::StartFailed("failed to open stdin".into()))?;
        let stdout = child.stdout.take()
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi::tests::dispatch`
Expected: PASS(3 个 dispatch 测试)

- [ ] **Step 5: 提交**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "feat(runtime): pi session spawn and stdout reader loop"
```

---

### Task 4: `start` — 发 prompt、装配 turn、agent_settled 完成

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs`

**Interfaces:**
- Consumes: `ensure_session`、`PersistentPi`、`TurnState`
- Produces: 完整 `HarnessAdapter::start`(替换 Task 2 的桩)

- [ ] **Step 1: 写失败测试(用 mock 会打通,这里测 prompt 消息构造函数)**

`start` 需真实 pi 子进程,做端到端到 Task 15。此处对可纯测的"prompt 行构造"上锁:

```rust
    #[test]
    fn build_prompt_line_is_valid_jsonl() {
        let line = super::build_prompt_line("hello world", "req_1");
        let v: serde_json::Value = serde_json::from_str(line.trim_end()).unwrap();
        assert_eq!(v["type"], "prompt");
        assert_eq!(v["message"], "hello world");
        assert_eq!(v["id"], "req_1");
        assert!(line.ends_with('\n'));
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi::tests::build_prompt_line`
Expected: FAIL(未定义)

- [ ] **Step 3: 实现 `build_prompt_line` + 完整 `start`**

追加辅助并替换 `start`:

```rust
pub(crate) fn build_prompt_line(message: &str, id: &str) -> String {
    let v = serde_json::json!({ "type": "prompt", "message": message, "id": id });
    format!("{}\n", v)
}

fn next_req_id() -> String {
    let n = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis()).unwrap_or(0);
    format!("req_{n}")
}
```

把 `start` 桩替换为(结构照 `native.rs::start`):

```rust
    async fn start(&self, input: HarnessInput, cwd: &Path) -> Result<RunningHarness, HarnessError> {
        use std::time::Instant;
        self.ensure_session(&input, cwd).await?;

        let start = Instant::now();
        let (event_tx, event_rx) = mpsc::channel(256);
        let (result_tx, result_rx) = oneshot::channel();

        let guard = self.session.lock().await;
        let session = guard.as_ref()
            .ok_or_else(|| HarnessError::StartFailed("session disappeared after ensure".into()))?;

        let (td_tx, td_rx) = oneshot::channel::<bool>();
        let usage = Arc::new(std::sync::Mutex::new(joysafeter_types::token_usage::TokenUsage::default()));
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

        // 写 prompt 到 stdin
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
            { let mut ct = current_turn.lock().await; *ct = None; }
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
```

- [ ] **Step 4: 跑测试 + 编译**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi:: && cargo build -p joysafeter-runtime`
Expected: PASS + 编译通过

- [ ] **Step 5: 提交**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "feat(runtime): implement PiAdapter start (prompt + turn assembly)"
```

---

### Task 5: `send_input`(steer)+ `cancel`(abort)

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/pi.rs`

**Interfaces:**
- Consumes: `SharedStdin`(存于 `RunningHarness.input`)
- Produces: `build_steer_line`、`build_abort_line`;完整 `send_input` / `cancel`

- [ ] **Step 1: 写失败测试**

```rust
    #[test]
    fn build_steer_line_is_valid() {
        let line = super::build_steer_line("wait, stop", "req_2");
        let v: serde_json::Value = serde_json::from_str(line.trim_end()).unwrap();
        assert_eq!(v["type"], "steer");
        assert_eq!(v["message"], "wait, stop");
    }

    #[test]
    fn build_abort_line_is_valid() {
        let line = super::build_abort_line("req_3");
        let v: serde_json::Value = serde_json::from_str(line.trim_end()).unwrap();
        assert_eq!(v["type"], "abort");
        assert_eq!(v["id"], "req_3");
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi::tests::build_steer_line pi::tests::build_abort_line`
Expected: FAIL(未定义)

- [ ] **Step 3: 实现**

```rust
pub(crate) fn build_steer_line(message: &str, id: &str) -> String {
    format!("{}\n", serde_json::json!({ "type": "steer", "message": message, "id": id }))
}
pub(crate) fn build_abort_line(id: &str) -> String {
    format!("{}\n", serde_json::json!({ "type": "abort", "id": id }))
}
```

`send_input`(从 `RunningHarness.input` downcast 出 `SharedStdin`,照 `native.rs::send_input`):

```rust
    async fn send_input(
        &self,
        harness: &mut RunningHarness,
        content: String,
    ) -> Result<(), HarnessError> {
        let Some(any) = harness.input.as_ref() else { return Err(HarnessError::UnsupportedInput) };
        let Some(shared_stdin) = any.downcast_ref::<SharedStdin>() else {
            return Err(HarnessError::UnsupportedInput)
        };
        let mut g = shared_stdin.lock().await;
        let Some(stdin) = g.as_mut() else {
            return Err(HarnessError::StartFailed("stdin closed".into()))
        };
        stdin.write_all(build_steer_line(&content, &next_req_id()).as_bytes()).await?;
        stdin.flush().await?;
        Ok(())
    }
```

`cancel`(向 pi 发 abort + 把当前 turn 标记为 aborted):

```rust
    async fn cancel(&self, _harness: &mut RunningHarness) -> Result<(), HarnessError> {
        let guard = self.session.lock().await;
        if let Some(ref session) = *guard {
            {
                let mut g = session.stdin.lock().await;
                if let Some(ref mut stdin) = *g {
                    let _ = stdin.write_all(build_abort_line(&next_req_id()).as_bytes()).await;
                    let _ = stdin.flush().await;
                }
            }
            let mut ct = session.current_turn.lock().await;
            if let Some(ref mut t) = *ct {
                if let Some(tx) = t.turn_done_tx.take() { let _ = tx.send(true); }
            }
        }
        Ok(())
    }
```

删除 Task 2 里 `cancel` 的空桩(用此实现替换)。

- [ ] **Step 4: 跑测试 + 编译**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime pi:: && cargo build -p joysafeter-runtime`
Expected: PASS + 编译通过

- [ ] **Step 5: 提交**

```bash
git add sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "feat(runtime): PiAdapter send_input (steer) and cancel (abort)"
```

---

### Task 6: pi 镜像 Dockerfile + entrypoint

**Files:**
- Create: `deploy/docker/pi.Dockerfile`
- Create: `deploy/docker/pi-entrypoint.sh`

**Interfaces:**
- Produces: 镜像 `joysafeter-pi`,内含 `joysafeter-runner` + 全局 `pi`,`ENTRYPOINT ["pi-entrypoint.sh"]`

- [ ] **Step 1: 写 `pi.Dockerfile`**(照 `codex.Dockerfile`,把 npm 包换成 pi,pin 版本)

```dockerfile
ARG BASE_IMAGE_REGISTRY="public.ecr.aws/docker/library/"
ARG RUST_VERSION="1.97.1-bookworm"
ARG NODE_VERSION="22.23.1-bookworm-slim"
ARG PYTHON_VERSION="3.12-slim-bookworm"

FROM ${BASE_IMAGE_REGISTRY}rust:${RUST_VERSION} AS runner-build
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config protobuf-compiler && rm -rf /var/lib/apt/lists/*
WORKDIR /build/sandbox-runner
COPY sandbox-runner/Cargo.toml sandbox-runner/Cargo.lock ./
COPY sandbox-runner/crates ./crates
COPY proto /build/proto
RUN --mount=type=cache,id=joysafeter-cargo-registry,sharing=locked,target=/usr/local/cargo/registry \
    --mount=type=cache,id=joysafeter-runner-target-${TARGETARCH},sharing=locked,target=/build/sandbox-runner/target \
    cargo build --locked --release -p joysafeter-runner \
    && cp target/release/joysafeter-runner /tmp/joysafeter-runner

FROM ${BASE_IMAGE_REGISTRY}node:${NODE_VERSION} AS node-runtime
FROM ${BASE_IMAGE_REGISTRY}python:${PYTHON_VERSION} AS runtime
ARG DEBIAN_FRONTEND=noninteractive
ARG PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
ARG NPM_REGISTRY="https://registry.npmjs.org"
ARG UV_VERSION="0.11.29"
ARG YARN_VERSION="1.22.22"
ARG PNPM_VERSION="10.15.0"

COPY --from=node-runtime /usr/local/ /usr/local/
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git curl wget jq tar zip unzip \
    openssh-client tmux screen make cmake ripgrep tree htop vim nano \
    socat sqlite3 postgresql-client redis-tools \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --root-user-action=ignore --no-cache-dir --index-url "${PIP_INDEX_URL}" "uv==${UV_VERSION}"

# pin pi version — protocol is experimental, no compat guarantees
ARG PI_VERSION="0.83.0"
RUN rm -f /usr/local/bin/yarn /usr/local/bin/yarnpkg /usr/local/bin/pnpm /usr/local/bin/pnpx \
    && npm install -g \
        "yarn@${YARN_VERSION}" \
        "pnpm@${PNPM_VERSION}" \
        "@earendil-works/pi-coding-agent@${PI_VERSION}" \
        --registry="${NPM_REGISTRY}" --no-audit --no-fund

RUN useradd -m -s /bin/bash agent \
    && mkdir -p /workspace /mnt/memory \
    && chown -R agent:agent /workspace /mnt/memory

ARG GIT_COMMIT_SHA="unknown"
LABEL org.opencontainers.image.revision="${GIT_COMMIT_SHA}"
ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

COPY --from=runner-build /tmp/joysafeter-runner /usr/local/bin/joysafeter-runner
COPY deploy/docker/pi-entrypoint.sh /usr/local/bin/pi-entrypoint.sh
RUN chmod +x /usr/local/bin/joysafeter-runner /usr/local/bin/pi-entrypoint.sh

WORKDIR /workspace
USER agent
ENTRYPOINT ["pi-entrypoint.sh"]
```

> **注**:`PI_VERSION` 默认值实现期以 npm 上 `@earendil-works/pi-coding-agent` 最新稳定版为准(锁死具体号,勿用 latest)。

- [ ] **Step 2: 写 `pi-entrypoint.sh`**(复用 `runner-entrypoint.sh` 的 token 剥离逻辑;pi 无需额外 config 文件,provider/model 经 env + `--model` 传入)

```sh
#!/bin/sh
# Scrub JOYSAFETER_RUNNER_TOKEN from the container env (same as runner-entrypoint.sh):
# save to a tmpfs file the runner can read, unset the env var, then exec the runner.
TOKEN_FILE="/tmp/.runner-token"
if [ -n "${JOYSAFETER_RUNNER_TOKEN:-}" ]; then
    printf '%s' "$JOYSAFETER_RUNNER_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    export JOYSAFETER_RUNNER_TOKEN_FILE="$TOKEN_FILE"
    unset JOYSAFETER_RUNNER_TOKEN
fi
exec joysafeter-runner "$@"
```

- [ ] **Step 3: 本地构建镜像验证(真实构建,不靠眼看)**

Run:
```bash
cd /Users/yuzhenjiang1/Downloads/workspace/JoySafeter && \
docker build -f deploy/docker/pi.Dockerfile -t joysafeter-pi:dev . 2>&1 | tail -20 && \
docker run --rm --entrypoint pi joysafeter-pi:dev --version
```
Expected: 构建成功;`pi --version` 打印版本号

- [ ] **Step 4: 提交**

```bash
git add deploy/docker/pi.Dockerfile deploy/docker/pi-entrypoint.sh
git commit -m "feat(docker): add joysafeter-pi engine image"
```

---

### Task 7: CI 构建矩阵加 joysafeter-pi

**Files:**
- Modify: `.github/workflows/docker-build.yml`(codex 块之后)
- Modify: `.github/workflows/release.yml`(codex 块之后)

**Interfaces:** 无(纯 CI 配置)

- [ ] **Step 1: 两个 workflow 各加一条矩阵项**

在两个文件的 `- name: joysafeter-codex` 块之后各追加:

```yaml
          - name: joysafeter-pi
            context: .
            dockerfile: ./deploy/docker/pi.Dockerfile
            skillspector: false
            build_contexts: ''
```

- [ ] **Step 2: 校验 YAML 语法**

Run: `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in ['.github/workflows/docker-build.yml','.github/workflows/release.yml']]; print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/docker-build.yml .github/workflows/release.yml
git commit -m "ci: build joysafeter-pi image in matrix"
```

---

### Task 8: orchestrator config.rs — image_pi 字段 + 映射

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/config.rs`

**Interfaces:**
- Consumes: 无
- Produces: `Config.image_pi: String`;`image_for_provider("pi")` 返回 `image_pi`

- [ ] **Step 1: 写失败测试**

在 `config.rs` 测试模块加(参照现有 image 测试):

```rust
    #[test]
    fn image_for_provider_pi_uses_image_pi() {
        let mut cfg = Config::default_for_test(); // 若无此辅助,构造方式照现有测试
        cfg.image_pi = "joysafeter-pi:latest".to_string();
        assert_eq!(cfg.image_for_provider("pi"), "joysafeter-pi:latest");
    }
```

> 若现有测试用别的方式构造 `Config`,照其模式;关键断言是 `image_for_provider("pi") == image_pi`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test image_for_provider_pi`
Expected: FAIL(`image_pi` 字段不存在)

- [ ] **Step 3: 实现**

- 在 struct 字段区(约 62-64 行,`image_native` 后)加:`pub image_pi: String,`
- 在构造区(约 224-226 行,`image_native` 后)加:`image_pi: env_str("JOYSAFETER_IMAGE_PI", ""),`
- 在 `image_for_provider`(约 378 行 match)`native` 臂后、`_` 前加:

```rust
            // pi 同 native:需要自己的镜像,不得回退到其他引擎镜像。
            "pi" if !self.image_pi.is_empty() => self.image_pi.clone(),
```

- [ ] **Step 4: 跑测试 + 编译**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test image_for_provider_pi && cargo build`
Expected: PASS + 编译通过

- [ ] **Step 5: 提交**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/config.rs
git commit -m "feat(orchestrator): map pi provider to image_pi"
```

---

### Task 9: Python settings.py — image_pi 字段 + 映射

**Files:**
- Modify: `backend/app/joysafeter_shared/config/settings.py`

**Interfaces:**
- Produces: `image_pi: str`;`image_for_provider("pi")` 返回 `image_pi`

- [ ] **Step 1: 写失败测试**

`backend/tests/` 下新增/追加(照现有 settings 测试范式):

```python
def test_image_for_provider_pi():
    from app.joysafeter_shared.config.settings import Settings
    s = Settings(image_pi="joysafeter-pi:latest")
    assert s.image_for_provider("pi") == "joysafeter-pi:latest"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest -k image_for_provider_pi -q`
Expected: FAIL(`image_pi` 未定义 / 返回 sandbox_image)

- [ ] **Step 3: 实现**

- 字段区(约 662-664 行,`image_native` 后)加:`image_pi: str = ""`
- `image_for_provider`(约 803 行)在 `native` 分支后、`return self.sandbox_image` 前加:

```python
        if engine_kind == "pi" and self.image_pi:
            return self.image_pi
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest -k image_for_provider_pi -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/joysafeter_shared/config/settings.py backend/tests/
git commit -m "feat(config): map pi provider to image_pi (python)"
```

---

### Task 10: engine_registry 增加 pi EngineSpec

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/engine_adapter.rs`

**Interfaces:**
- Produces: `engine_spec("pi")` 返回非 None

- [ ] **Step 1: 写失败测试**

```rust
    #[test]
    fn pi_engine_is_registered() {
        assert!(super::engine_spec("pi").is_some());
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test pi_engine_is_registered`
Expected: FAIL

- [ ] **Step 3: 实现**(在 REGISTRY 数组 native 项后加)

```rust
        EngineSpec {
            engine_kind: "pi",
            injects_conversation_history: true,
            // pi 多供应商,模型经 HarnessInput.model → `--model` 透传;
            // PI_MODEL 承载模型名,MODEL 兜底。
            model_secret_keys: &["PI_MODEL", "MODEL"],
        },
```

- [ ] **Step 4: 跑测试 + 编译**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test pi_engine_is_registered && cargo build`
Expected: PASS + 编译通过

- [ ] **Step 5: 提交**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/kernel/engine_adapter.rs
git commit -m "feat(orchestrator): register pi in engine registry"
```

---

### Task 11: env 样例 + deploy.sh + k8s manifest

**Files:**
- Modify: `deploy/.env.example`、`backend/.env.example`(若存在对应键)
- Modify: `deploy/deploy.sh`
- Modify: `deploy/k8s/orchestrator-complete.yaml`

**Interfaces:** 无(部署配置)

- [ ] **Step 1: env 样例加 pi 镜像 + 预热池**

在 `deploy/.env.example` 的 `JOYSAFETER_IMAGE_*` 附近加:`JOYSAFETER_IMAGE_PI=joysafeter-pi:latest`;把 `JOYSAFETER_SANDBOX_POOL_IMAGES` 追加 `"joysafeter-pi:latest"`。`backend/.env.example` 同样加 `JOYSAFETER_IMAGE_PI`。

- [ ] **Step 2: deploy.sh 加 PI_IMAGE**

在 `deploy.sh` 约 30-32 行(`NATIVE_IMAGE` 后)加:`PI_IMAGE="${PI_IMAGE:-joysafeter-pi}"`;在帮助文本(约 171-173 行)加对应说明行。grep 检查 deploy.sh 中构建/推送镜像的循环是否枚举了引擎镜像列表,若是则把 `pi` 加入该列表。

Run(定位需要改的枚举点): `grep -n "CLAUDECODE_IMAGE\|CODEX_IMAGE\|NATIVE_IMAGE" deploy/deploy.sh`
按输出把 pi 补齐到同样的位置。

- [ ] **Step 3: k8s manifest 加 pi 镜像环境变量**

在 `deploy/k8s/orchestrator-complete.yaml` 约 187-193 行(`JOYSAFETER_IMAGE_*` env 块)加:

```yaml
        - name: JOYSAFETER_IMAGE_PI
          value: "aisec-repo.jd.com/joysafeter/joysafeter-pi:latest"
```

- [ ] **Step 4: 校验**

Run: `python -c "import yaml; list(yaml.safe_load_all(open('deploy/k8s/orchestrator-complete.yaml'))); print('yaml ok')" && bash -n deploy/deploy.sh && echo 'sh ok'`
Expected: `yaml ok` + `sh ok`

- [ ] **Step 5: 提交**

```bash
git add deploy/.env.example backend/.env.example deploy/deploy.sh deploy/k8s/orchestrator-complete.yaml
git commit -m "chore(deploy): wire joysafeter-pi image through env/deploy/k8s"
```

---

### Task 12: skill/MCP 布局分支 — pi 用 .pi/

**Files:**
- Modify: `sandbox-runner/crates/joysafeter-runner/src/runner.rs`

**Interfaces:**
- Consumes: 现有 `skill_base_dir(work_dir, provider, target)`、MCP 写配置逻辑
- Produces: pi 的 skill 目录 = `<work_dir>/.pi/<target>`

- [ ] **Step 1: 写失败测试**(若 `skill_base_dir` 无测试,新增)

```rust
    #[test]
    fn skill_base_dir_pi_uses_dot_pi() {
        let base = skill_base_dir(std::path::Path::new("/w"), "pi", "skills");
        assert_eq!(base, std::path::Path::new("/w/.pi/skills"));
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd sandbox-runner && cargo test -p joysafeter-runner skill_base_dir_pi`
Expected: FAIL(pi 落到默认 `.claude`)

- [ ] **Step 3: 实现**

`skill_base_dir`(约 571 行 match)在 `"codex"` 臂后加:

```rust
        "pi" => work_dir.join(".pi").join(target),
```

MCP 写配置(约 756 行 `if !matches!(provider, "claude" | "claude_code")` 跳过 `.claude/settings.json` 的逻辑)对 pi 已默认跳过(pi 不读 `.claude/settings.json`),无需改动;pi 的 MCP 配置形态在 Task 15 集成阶段以真实运行验证后按需补充(pi 经 `.pi/` 扩展加载,非本任务范围)。

- [ ] **Step 4: 跑测试 + 编译**

Run: `cd sandbox-runner && cargo test -p joysafeter-runner skill_base_dir_pi && cargo build -p joysafeter-runner`
Expected: PASS + 编译通过

- [ ] **Step 5: 提交**

```bash
git add sandbox-runner/crates/joysafeter-runner/src/runner.rs
git commit -m "feat(runner): pi uses .pi/ for skill layout"
```

---

### Task 13: 出网凭证 — 复用 Envoy 重注入(按需扩 provider)

现有 `llm_provider_registry()` 已覆盖 Anthropic/OpenAI/Gemini/Azure。**pi 对接这四类零改动即可跑通。** 本任务提供扩展模式并加一个 China provider 的 worked example(DeepSeek),其余 provider 照抄一行。

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/llm_providers.rs`

**Interfaces:**
- Produces: `llm_provider_registry()` 含 DeepSeek 条目;检测键 `DEEPSEEK_API_KEY`

- [ ] **Step 1: 写失败测试**

```rust
    #[test]
    fn deepseek_provider_registered() {
        let found = super::llm_provider_registry()
            .iter()
            .any(|s| s.detection_keys.contains(&"DEEPSEEK_API_KEY"));
        assert!(found);
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test deepseek_provider_registered`
Expected: FAIL

- [ ] **Step 3: 实现**(在 REGISTRY 数组末尾、Azure 项后加;pi 的 deepseek base_url=api.deepseek.com,Bearer)

```rust
        // 6. DEEPSEEK_API_KEY — OpenAI-compatible, Bearer authorization.
        LlmProviderSpec {
            detection_keys: &["DEEPSEEK_API_KEY"],
            base_url_var: "DEEPSEEK_BASE_URL",
            default_host: Some("api.deepseek.com"),
            header_name: "authorization",
            is_bearer: true,
            extra_keys_to_remove: &["DEEPSEEK_API_KEY"],
            placeholder: None,
        },
```

> 追加其他 pi provider(Qwen/Kimi/MiniMax/Zai…)时照此一行模式:填 detection_keys / base_url_var / default_host / header_name / is_bearer,并在 Envoy 放行该 default_host。

- [ ] **Step 4: 跑测试 + 编译**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test deepseek_provider_registered && cargo build`
Expected: PASS + 编译通过

- [ ] **Step 5: 提交**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/kernel/llm_providers.rs
git commit -m "feat(orchestrator): add deepseek to LLM egress registry (pi provider example)"
```

---

### Task 14: 后端 API / 前端引擎选择暴露 pi

**Files:**
- Modify: 引擎选择相关(先定位):`backend/app/joysafeter_api/api/v1/quickstart.py` 及前端引擎列表

**Interfaces:**
- Produces: 用户可在创建 agent 时选择 `pi` 引擎(`engine_kind="pi"`)

- [ ] **Step 1: 定位所有"引擎枚举"出现点**

Run: `grep -rn "claudecode\|\"codex\"\|engine_kind\|ENGINE" backend/app/joysafeter_api frontend/src --include=*.py --include=*.ts --include=*.tsx | grep -iv test | head -40`
把返回中"列出可选引擎"的位置(校验白名单、下拉选项、文案)一一记录。

- [ ] **Step 2: 写失败测试**(后端引擎白名单校验若存在)

针对 agent 创建接口的引擎校验:断言 `engine_kind="pi"` 被接受。测试文件照现有 agents API 测试范式。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest -k "engine and pi" -q`
Expected: FAIL(pi 不在白名单)

- [ ] **Step 4: 实现**

把 Step 1 定位到的每个引擎枚举/白名单/前端选项加入 `pi`(后端 Python 校验列表 + 前端引擎选择组件)。前端展示名可用 "Pi"。

- [ ] **Step 5: 跑测试确认通过 + 前端类型检查**

Run: `cd backend && uv run pytest -k "engine and pi" -q`(PASS);前端若有 `npm run typecheck` 则跑一遍。

- [ ] **Step 6: 提交**

```bash
git add backend/app/joysafeter_api frontend/src
git commit -m "feat(api): expose pi as a selectable engine"
```

---

### Task 15: 实盘 fixture 抓取 + 端到端集成验证

用真实运行验证映射与全链路(不靠眼看)。这是最终证据。

**Files:**
- Create: `sandbox-runner/crates/joysafeter-runtime/tests/fixtures/pi_rpc_stream.jsonl`(抓取产物)
- Create: `sandbox-runner/crates/joysafeter-runtime/tests/pi_fixture_test.rs`

**Interfaces:**
- Consumes: `map_pi_event`、`dispatch_pi_line`

- [ ] **Step 1: 抓取真实 pi rpc 事件流**

在 pi 镜像内起 rpc、灌一个 prompt、抓 stdout(需一个可用 provider key,例如 DeepSeek):

```bash
docker run --rm -i -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" joysafeter-pi:dev \
  sh -c 'printf "%s\n" "{\"type\":\"prompt\",\"message\":\"say hi then list files\",\"id\":\"req_1\"}"; sleep 20' \
  | pi --mode rpc --model deepseek/deepseek-chat \
  > /tmp/pi_rpc_stream.jsonl 2>/dev/null || true
head -50 /tmp/pi_rpc_stream.jsonl
```

> 实现期按容器内实际调用方式调整(entrypoint 是 runner,抓取时用 `--entrypoint pi` 直接跑 rpc)。**LOOK at the output**:确认里面出现 `message_update`/`tool_execution_start`/`tool_execution_end`/`message_end`/`agent_settled`,且字段名与 Task 1 断言一致。若某字段名不同(如 `result` 是对象数组而非字符串),回到 Task 1 修正映射并补测试。把抓到的流去敏后存为 fixture 文件。

- [ ] **Step 2: 写 fixture 回放测试**

`tests/pi_fixture_test.rs`:逐行喂 fixture 给 `dispatch_pi_line`,断言至少产生一个 `Text`、一个 `ToolUse`、一个 `ToolResult`、一个 `ModelRequestEnd`,且最终出现 `turn_done`。

```rust
use joysafeter_runtime::pi::{dispatch_pi_line, /* 若未 pub 则改为 pub(crate) 并加 pub re-export */};
// 见下方 note:测试需要访问 dispatch_pi_line 与 HarnessEvent
```

> **Note:** 若 `dispatch_pi_line` 为 `pub(crate)`,在 `pi.rs` 顶部为集成测试加 `#[cfg(test)]` 不可见 → 改为在 `lib.rs` 暴露一个 `#[doc(hidden)] pub use pi::dispatch_pi_line;` 或把回放测试放进 `pi.rs` 的 `#[cfg(test)] mod tests`(推荐后者,读 fixture 用 `include_str!`)。

推荐实现(放进 `pi.rs` tests 模块):

```rust
    #[tokio::test]
    async fn replays_real_pi_stream_fixture() {
        let fixture = include_str!("../tests/fixtures/pi_rpc_stream.jsonl");
        let (tx, mut rx) = tokio::sync::mpsc::channel::<HarnessEvent>(1024);
        let mut cmap = HashMap::new();
        let mut done = false;
        for line in fixture.lines() {
            if dispatch_pi_line(line, &tx, &mut cmap).await { done = true; }
        }
        drop(tx);
        let mut kinds = std::collections::HashSet::new();
        while let Some(ev) = rx.recv().await {
            kinds.insert(std::mem::discriminant(&ev));
            let _ = ev;
        }
        assert!(done, "expected agent_settled in fixture");
        // 至少见过 Text / ToolUse / ToolResult / ModelRequestEnd
        assert!(kinds.len() >= 3, "expected several event kinds, saw {}", kinds.len());
    }
```

- [ ] **Step 3: 跑回放测试**

Run: `cd sandbox-runner && cargo test -p joysafeter-runtime replays_real_pi_stream_fixture`
Expected: PASS

- [ ] **Step 4: 全链路手测(起沙箱跑一轮 + steer + cancel)**

用现有本地部署(`deploy/deploy.sh local`)配置 `JOYSAFETER_IMAGE_PI=joysafeter-pi:dev`,创建 `engine_kind="pi"` 的 agent,发一条消息:验证前端收到流式文本、工具事件、token 用量;测一次 steer 中途插话、一次 cancel。**LOOK**:确认事件与 token 真实非空。记录结果。

- [ ] **Step 5: 跑完整后端 + runtime 测试套件**

Run:
```bash
cd sandbox-runner && cargo test -p joysafeter-runtime && cd - && \
cd backend && uv run pytest -q
```
Expected: 全绿(区分真实失败与环境 ERROR,如镜像拉取失败)

- [ ] **Step 6: 提交**

```bash
git add sandbox-runner/crates/joysafeter-runtime/tests/ sandbox-runner/crates/joysafeter-runtime/src/pi.rs
git commit -m "test(runtime): pi rpc stream fixture replay + integration verification"
```

---

## Self-Review

**Spec coverage(逐条对照 spec):**
- PiAdapter / HarnessAdapter → Task 1-5 ✓
- 驱动面 `pi --mode rpc` JSONL → Task 3-5 ✓
- 事件映射表(含 usage 四项)→ Task 1 + Task 15 fixture 验证 ✓
- 镜像 pi.Dockerfile + entrypoint + pin 版本 → Task 6 ✓
- CI 矩阵 → Task 7 ✓
- provider→镜像(Rust + Python)→ Task 8/9 ✓
- engine_registry EngineSpec → Task 10 ✓
- env/deploy/k8s → Task 11 ✓
- skill `.pi/` 布局 → Task 12 ✓
- 出网复用 Envoy(+ worked example)→ Task 13 ✓
- 后端/前端引擎暴露 → Task 14 ✓
- 权限=全放行:不新增 ask 流代码,`allowed_tools/ask_tools` 不落地 → 全程未引入,符合 ✓
- 测试策略(单元 + mock + is_available + 集成 + backend pytest)→ Task 1-5/2/15 ✓

**Placeholder scan:** 无 TBD/TODO;两处"实现期确认"(Task 6 PI_VERSION 具体号、Task 15 字段名核对)是**必须的实盘验证步骤**而非占位——已给出确认方法与失败时的回改路径。

**Type consistency:** `map_pi_event` / `dispatch_pi_line` / `build_prompt_line` / `build_steer_line` / `build_abort_line` / `PersistentPi` / `TurnState` / `PiAdapter` 跨任务命名一致;`HarnessEvent` 变体、`HarnessResult` 字段、`RunningHarness` 结构均与 `harness.rs` 一致;`TokenUsage` 字段(input_tokens/output_tokens/cache_read_tokens/cache_write_tokens/by_model)与 native.rs 用法一致。

**风险提示(继承 spec):** pi 协议 experimental → 已 pin 版本 + 未知事件宽容跳过;Task 15 的 fixture 回放是防协议漂移的回归护栏。
