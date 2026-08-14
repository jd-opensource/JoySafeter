# pi 引擎接入 JoySafeter 沙箱 — 设计文档

- 日期: 2026-08-05
- 分支: joysafeter-v2
- 状态: 已通过 brainstorming 评审,待写实现计划

## 目标

把外部项目 **pi**(`@earendil-works/pi-coding-agent`,TypeScript/Node coding-agent harness,多供应商)接入为 JoySafeter 沙箱的**第四个引擎**(现有:`claude` / `codex` / `native`),与现有引擎**全功能对齐**:多轮会话、steering 实时插话、MCP、skills、完整 token 计费。

## 范围与关键决策

| 维度 | 决策 |
|---|---|
| 范围 | 全功能对齐 claude/codex(多轮 / steering / skills / token 计费)。**MCP 例外见下** |
| 权限模型 | **全放行,靠容器兜底**。pi 无内置权限系统,以默认全权限运行,隔离交给 JoySafeter 沙箱(Docker + cap-drop + no-new-privs + Envoy)。`HarnessInput.allowed_tools/ask_tools` 本方案不落地为逐工具 ask 流(与 codex 的 `danger-full-access` 姿态一致) |
| LLM 供应商 | **pi 内置全部支持,pass-through**。provider/model 由 `HarnessInput.model` 透传成 pi 的 `--model <provider>/<pattern>` |
| 出网/凭证 | **复用现有 Envoy 重注入机制**,不新造。每个供应商在 `llm_provider_registry()` 一行 `LlmProviderSpec` + Envoy 放行域名 |
| 驱动面 | **`pi --mode rpc`(JSONL 行协议)**,常驻子进程 |
| 实现模板 | 骨架抄 `native.rs`(最薄),事件解析参考 `claude.rs`;不抄 `codex.rs`(其复杂度是 codex 特有的 JSON-RPC/审批/多 agent) |

> **MCP 差异(2026-08-06 修正,刻意不对齐):** pi 0.83.0 **本身刻意不支持 MCP**(README:496 "No MCP";docs/usage.md:301 "intentionally does not include built-in MCP"),无任何 MCP 配置文件/CLI flag/settings 字段。因此 codex 那种"把 `[mcp_servers.*]` 合并进配置文件"的做法在 pi 上不存在。pi 的工具扩展等价物是 **Skills**(CLI 工具 + README),已通过 `.pi/` 布局接入。故 `HarnessInput.mcp_configs` 对 pi 引擎**有意不落地**(pi.rs `ensure_session` 有注释说明,防误判为 bug)。若将来确需 pi 消费 MCP server,只能另写一个 MCP-bridge pi 扩展(独立工程),不在本方案范围。

## 背景:JoySafeter 引擎抽象(已验证)

"引擎" = `sandbox-runner/crates/joysafeter-runtime/` 里实现 `HarnessAdapter` trait(`joysafeter-types/src/harness.rs:159`)的 Rust 运行时适配器。职责:spawn agent CLI,把其原生输出流翻译成规范化的 `HarnessEvent`。

```rust
#[async_trait]
pub trait HarnessAdapter: Send + Sync {
    async fn start(&self, input: HarnessInput, cwd: &Path) -> Result<RunningHarness, HarnessError>;
    async fn cancel(&self, harness: &mut RunningHarness) -> Result<(), HarnessError>;
    async fn send_input(&self, _harness: &mut RunningHarness, _content: String) -> Result<(), HarnessError>;
    fn provider(&self) -> &str;
    async fn is_available(&self) -> bool;
}
```

- 注册: `joysafeter-runtime/src/lib.rs:15` `AdapterRegistry::discover()`,按 `is_available()` 探测后按 provider 名分发。
- 每个引擎独立 Docker 镜像(`deploy/docker/*.Dockerfile`):统一 base + 编译进 `joysafeter-runner` 二进制 + npm 装对应 CLI + 各自 entrypoint。
- provider→镜像映射: `settings.py:803 image_for_provider` + `config.rs:377 image_for_provider` + `JOYSAFETER_IMAGE_*` 环境变量。

**不改动**:`SandboxProvider` 执行面(Docker/K8s/E2B/Daytona)、runner↔orchestrator gRPC(`proto/joysafeter.proto`)、Envoy 出网机制本身。这确认接入是扩展点,不是 fork。

## pi 侧事实(已直接验证)

- pi 是 Node monorepo,Node ≥ 22.19,npm 可全局安装(`@earendil-works/pi-coding-agent`)。
- `pi --mode rpc` 走 **JSONL 行协议**(`packages/coding-agent/src/modes/rpc/`,非 CBOR)。`rpc-client.ts` 暴露:`prompt`(发起一轮)、steering 消息(中途插话/中断,对应 `send_input`)、`new_session`/`switch_session`、会话状态/统计、事件流(`JsonAgentSessionEvent`)。
- 每个 provider 从**环境变量**读 key(`envApiKeyAuth(..., ["DEEPSEEK_API_KEY"])` 等),base_url 为可覆盖默认值 → 与 JoySafeter 的 env 剥离 + Envoy 重注入天然兼容。
- 协议标注 experimental、无兼容保证 → **必须 pin 死 pi 版本**(如同现有 `CLAUDE_CODE_VERSION` / `CODEX_VERSION`)。

## 架构:PiAdapter

新文件 `sandbox-runner/crates/joysafeter-runtime/src/pi.rs`,实现 `HarnessAdapter`,以常驻 `pi --mode rpc` 子进程驱动。

### 组件与数据流

```
orchestrator --gRPC--> joysafeter-runner --trait--> PiAdapter
                                                        |
                                       spawn: pi --mode rpc (stdin/stdout JSONL)
                                                        |
        HarnessInput --(prompt/steering via stdin JSONL)--> pi
        pi --(JsonAgentSessionEvent via stdout JSONL)--> PiAdapter
        PiAdapter --(HarnessEvent via mpsc)--> runner --> orchestrator
```

- **会话生命周期**:首个 `start` 拉起常驻 pi 进程 + `new_session`;后续轮次复用同进程(参照 `codex.rs` 的 `ensure_session`/持久会话,但用 JSONL 而非 JSON-RPC)。会话存活性用 `child.try_wait()` 探测。
- **`start`**:向 pi stdin 写 `{"type":"prompt","message":<prompt>}`;system_prompt 通过 pi 的 system-prompt 机制注入(append/replace 模式对应 `HarnessInput.system_prompt_mode`)。返回 `RunningHarness`(mpsc 事件流 + oneshot 结果 + child 句柄)。
- **`send_input`**:写 pi 的 steering 消息,实现实时插话。
- **`cancel`**:写 pi 的 interrupt,中止当前轮。
- **`is_available`**:`which pi` 或 `pi --version` 成功即可用(参照 `native.rs` 的 `which::which`)。
- **`provider`**:返回 `"pi"`。

### 事件映射表(pi → HarnessEvent)

pi `JsonAgentSessionEvent`(会话级)+ `message_update.assistantMessageEvent`(增量级,见 `packages/agent/src/proxy.ts`)→ `HarnessEvent`:

| pi 事件 | HarnessEvent |
|---|---|
| `message_update` → `text_delta` | `Text { content: delta }` |
| `message_update` → `thinking_delta` | `Thinking { content: delta }` |
| `message_update` → `toolcall_start { id, toolName }` + `toolcall_delta` (聚合入参) | `ToolUse { tool, call_id, input }` |
| `tool_execution_end`(工具执行结果) | `ToolResult { tool, call_id, output }` |
| `message_update` → `error` / 错误事件 | `Error { message }` |
| `message_end` 上的 `usage: Usage` | `ModelRequestEnd { input_tokens: usage.input, output_tokens: usage.output, cache_read_tokens: usage.cacheRead, cache_write_tokens: usage.cacheWrite }` |
| `message_start`(带 model) | `ModelRequestStart { model }` |
| 子 agent 生命周期(若启用)| `TaskNotification { phase, task_id, ... }` |
| `turn_end` / `agent_end` | 触发 `HarnessResult`(status/output/usage/duration)经 oneshot 返回 |

- `Usage` 字段已核实:`{ input, output, cacheRead, cacheWrite }`(`packages/ai/src/types.ts:364`)——四项与 `ModelRequestEnd` 精确对应,token 计费完整。
- **待实现期确认**:`toolcall_delta` 入参聚合的确切时机、子 agent 事件在 pi rpc 下的具体形态(pi 是否在 rpc 模式发子 agent 事件)。这两点在实现时以真实 JSONL 输出为准,不臆测。

## 多供应商与出网(复用 Envoy 重注入)

- provider/model 选择:`HarnessInput.model` 透传为 pi `--model <provider>/<pattern>`(或 `--provider <name> --model <pattern>`)。
- 凭证:JoySafeter 把该 provider 的 key env(如 `DEEPSEEK_API_KEY`)注入容器;现有出网层剥离 key、Envoy 在边界重注入。
- `llm_provider_registry()`(`llm_providers.rs`)已覆盖 Anthropic / OpenAI / Gemini / Azure 四类。**pi 对接这四类无需改出网表**——最小可用的 pi 引擎(跑 Anthropic/OpenAI/Gemini/Azure 任一)零出网改动即可上线。
- pi 用到表外的 provider(如 DeepSeek / Qwen / Kimi / MiniMax / Zai 等)时,**每个补一行 `LlmProviderSpec`**(detection_keys / base_url_var / default_host / header_name / is_bearer)+ Envoy 放行域名。数据驱动,按需增量扩展,不必上线即注册全部。

## 改动清单

| # | 位置 | 改动 |
|---|---|---|
| 1 | `joysafeter-runtime/src/pi.rs`(新) | `PiAdapter` 实现 `HarnessAdapter` + 事件映射 |
| 2 | `joysafeter-runtime/src/lib.rs` | `discover()` 注册 pi;mock 分支加 `"pi"` |
| 3 | `joysafeter_orchestrator_rs/src/kernel/engine_adapter.rs` | 加 `EngineSpec{ engine_kind:"pi", injects_conversation_history:true, model_secret_keys }`。pi 多供应商、模型经 `--model` 透传,`model_secret_keys` 取空表或按默认 provider 填(实现期依透传方案定) |
| 4 | `deploy/docker/pi.Dockerfile` + `deploy/docker/pi-entrypoint.sh`(新) | base + `joysafeter-runner` + `npm i -g @earendil-works/pi-coding-agent`(pin 版本);entrypoint 写 pi 配置 + 复用 token 剥离逻辑 |
| 5 | `.github/workflows/docker-build.yml` + `release.yml` | 构建矩阵加 `joysafeter-pi` |
| 6 | `settings.py:image_for_provider` + `config.rs:image_for_provider` + `JOYSAFETER_IMAGE_PI` + `SANDBOX_POOL_IMAGES` + `deploy.sh` + `deploy/k8s/orchestrator-complete.yaml` | provider→镜像映射 |
| 7 | `joysafeter_orchestrator_rs/src/kernel/llm_providers.rs` | 按需为 pi provider 补 `LlmProviderSpec` |
| 8 | `runner.rs:571 skill_base_dir` + MCP 写配置逻辑 | 加 `"pi"` 分支(pi 用 `.pi/` 放 skills/extensions) |
| 9 | backend API / 前端引擎选择列表(`quickstart.py` 等) | 暴露 pi 为可选引擎 |

## 测试策略

- **单元**:事件映射函数(pi JSONL → HarnessEvent)对每类事件的用例;usage 映射;错误/中断路径。
- **mock 适配器**:`lib.rs` mock 分支加 pi,使不装 pi CLI 的环境也能跑测试。
- **`is_available` 探测**:pi 缺失时优雅不注册(参照 native)。
- **集成**:构建 `joysafeter-pi` 镜像,起沙箱跑一个真实任务(单轮 + 一次 steering + cancel),校验事件流与 token 计费。
- **后端**:`cd backend && uv run pytest`(遵循 CLAUDE.md — 必须在 backend/ 下跑)。

## 风险与缓解

1. **pi 协议 experimental、无兼容保证** → Dockerfile pin 死 pi 版本;事件映射对未知事件类型宽容跳过。
2. **`allowed_tools/ask_tools` 不落地** → 与已选"全放行"决策一致;若未来需要 ask 流,再以 pi 扩展(`permission-gate` 风格)实现,不影响本方案结构。
3. **子 agent / toolcall 入参聚合的确切形态** → 实现期以真实 JSONL 输出验证,不臆测。
4. **每引擎需独立镜像**(`config.rs:381-385`:runner 只注册 CLI 存在的 adapter)→ pi 必须有自己的镜像,不得回退到其他引擎镜像。
