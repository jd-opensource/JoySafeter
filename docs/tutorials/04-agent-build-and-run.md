# 教程 04：构建并运行一个 Agent

> **适合人群**：想端到端跑通“定义 Agent → 开会话 → 实时看执行”的用户。
> **前置**：已配置一条模型凭据（[教程 01](./01-model-provider-setup.md)）。

---

## 0. 心智模型

- **Agent**：一份定义——引擎 `engine_kind`、`model`、`system`，以及能力
  （`skills` / `tools` / `mcp_servers`）。
- **Session（会话）**：一段对话（`joysafeter_sessions`），创建时快照当时的 Agent 定义。
- **Task（任务）**：会话里的每条用户消息变成一个 Task（`joysafeter_tasks`），被调度到沙箱执行。
- **事件流**：harness 的一切输出（文本 / 思考 / 工具调用 / 工具结果 / 模型请求 / 子任务）以事件形式
  经 **SSE** 实时回到浏览器，并追加落库 `joysafeter_session_events`（带单调 `seq`）。

一次消息的完整链路见 [架构文档 §2](../ARCHITECTURE_CN.md#2-核心闭环从消息到实时事件)。

---

## 1. 创建 Agent

进入 **托管智能体 → 智能体**（`/managed/agents`）并点击 **新建**，或打开已有 Agent 的**编辑器**，配置：

| 配置 | 说明 |
|------|------|
| **引擎（engine_kind）** | `claude`（Claude Code CLI）/ `codex`（Codex app-server）/ `native`（自研 `ccb`）。决定沙箱镜像与运行时 harness。 |
| **模型（model）** | 引擎支持的模型名；密钥由该 Agent 关联的 Secret 注入（见教程 01）。 |
| **系统提示词（system）** | Agent 的角色与行为约束。 |
| **技能（skills）** | 勾选已 `approved` 的技能（见教程 03），可选特定版本。 |
| **工具 + 策略（tools）** | 勾选内置工具，并对高危工具设 `always_ask`（运行时人工确认）。 |
| **MCP 服务器（mcp_servers）** | URL 型外部工具服务（见教程 02），凭据放 Vaults。 |
| **权限模式（permission_mode）** | 如 `bypassPermissions` / `default`，影响工具放行策略。 |

保存后，Agent 会**版本化**（`joysafeter_agent_versions` 记录快照）。

对应 API（简化）：
```bash
curl -X POST http://localhost:8000/api/v1/agents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <platform-token>" \
  -d '{
    "name": "recon-helper",
    "engine_kind": "claude",
    "model": { "id": "Claude-Opus-4.6" },
    "system": "你是一名授权范围内的安全侦察助手。",
    "skills": [ { "type": "skill_id", "skill_id": "<id>", "version": "1.0.0" } ],
    "tools": [ ],
    "mcp_servers": [ ]
  }'
```

---

## 2. 开一个 Session 并发消息

1. 打开 Agent，点 **新建会话**。创建时后端会解析 Agent、按需挂载文件 / repo / 记忆资源，并**准备沙箱**
   （复用会话已有沙箱 → 从预热池认领 → 新建其一）。
2. 在会话里发第一条消息。它变成一个 `pending` 的 Task 入队（Redis list `joysafeter:global_queue`）。
3. orchestrator 调度器认领任务（DB 权威 + `FOR UPDATE SKIP LOCKED`），把 `SetupSandbox`（技能 / MCP /
   工具 / 文件 / env）与 `StartTask`（prompt / provider / model）经 gRPC `AgentBridge` 下发给沙箱 runner。

对应 API：`POST /api/v1/sessions` 建会话，`POST /api/v1/sessions/{id}/events`（`user.message`）发消息。

---

## 3. 实时观察执行（SSE）

前端通过 **SSE** 订阅会话事件流：`GET /api/v1/sessions/{id}/events/stream?after_seq=N`
（先按 `after_seq` 回放已持久化事件，再转实时）。你会看到这些事件类型：

| 事件 | 含义 |
|------|------|
| `session.status_running` / `session.status_idle` | 会话运行 / 空闲状态切换 |
| `agent.thinking` | 模型思考过程 |
| `agent.message` | 助手文本输出 |
| `agent.tool_use` / `agent.mcp_tool_use` / `agent.custom_tool_use` | 工具调用（内置 / MCP / 自定义） |
| `span.model_request_start` / `span.model_request_end` | 模型请求起止（含 input/output/cache token 计量） |
| `agent.bg_task_started` / `_progress` / `_finished` | 后台子 Agent 生命周期 |
| `user.tool_confirmation` / `user.interrupt` | 人工确认 / 中断握手 |

> 断线重连时，前端用最后的 `seq` 作为 `?after_seq` 回放，不丢事件。

---

## 4. 干预与停止

- **人工确认**：若某工具设了 `always_ask`，它会以 `is_control_request` 的工具调用挂起，前端弹确认；
  你同意后，orchestrator 用 gRPC `SendInput` 放行（或用 `CancelTask` 拒绝）。
- **追加输入 / 中断**：会话运行中可继续发消息或中断；控制指令经 Redis 中继到拥有该沙箱的实例，再经
  gRPC 注入 runner。
- **停止**：`POST /api/v1/sessions/{id}/stop` 取消活动任务；沙箱空闲后由清扫循环回收。

---

## 5. 挂载资源（可选）

会话可挂载：
- **文件**：`POST /api/v1/files` 上传后加为会话资源，投递进沙箱工作目录。
- **Git 仓库**：加 `github_repository` 资源，runner 在沙箱内 clone（凭据不写日志）。
- **记忆库（Memory Store）**：Agent 可读写的 KV 存储，带版本历史，双向同步。

---

## 下一步

- [教程 01](./01-model-provider-setup.md) / [02](./02-mcp-service-setup.md) / [03](./03-skills-usage.md)：分别深化模型 / MCP / 技能配置
- [系统架构](../ARCHITECTURE_CN.md)：理解三服务、事件模型与沙箱隔离的完整设计
