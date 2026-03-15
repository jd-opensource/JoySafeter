# Copilot 前后端逻辑对照与不对应项

本文档梳理前后端 Copilot 在事件、API、类型、行为上的一致性与不对应之处，便于逐项修复或约定。

---

## 1. 流式事件 (WebSocket / SSE)

### 1.1 事件类型与字段

| 事件类型 | 后端 (action_types.py / 实际发送) | 前端 (use-copilot-websocket.ts) | 对齐情况 |
|----------|-----------------------------------|----------------------------------|----------|
| status | type, stage, message | stage, message → onStatus(stage, message) | 一致 |
| content | type, content | content → onContent | 一致 |
| thought_step | type, step: {index, content} | step → onThoughtStep | 一致 |
| tool_call | type, tool, input | tool, input → onToolCall | 一致 |
| tool_result | type, action: {type, payload, reasoning?} | action → onToolResult | 一致 |
| result | type, message, actions[], batch? | message, actions → onResult | 见 1.2 |
| done | type | 触发 cleanup，不回调 | 一致 |
| error | type, message, code | message, code → onError，按 code 分支 | 见 1.3 |

### 1.2 result 事件：空 message 或空 actions

- **后端**：`CopilotResultEvent` 中 `message: str` 必填，`actions` 默认 `[]`，可发 `message=""` 且 `actions=[...]`。
- **前端**：`if (data.message && data.actions)` 才调用 `onResult`。在 JS 中 `"" && data.actions` 为 `""`（falsy），会跳过 onResult。
- **不对应**：当后端发送 `result` 且 `message=""`、`actions` 非空时，前端不会执行 onResult，导致不落盘、不执行 actions。
- **建议**：前端改为按事件类型处理，例如 `if (data.type === 'result')` 则调用 `onResult({ message: data.message ?? '', actions: data.actions ?? [] })`，不依赖 `data.message && data.actions`。

### 1.3 error 事件与错误码

- **后端发送的 code**：`CREDENTIAL_ERROR`、`AGENT_ERROR`、`REDIS_UNAVAILABLE`、`UNKNOWN_ERROR`（见 copilot_service.py）。
- **前端处理**：对 `CREDENTIAL_ERROR`、`AGENT_ERROR`、`REDIS_UNAVAILABLE`、`CANCELLED` 有专属文案；其余走 `systemError: ${error}`。后端未发 `CANCELLED`，前端保留可接受。
- **不对应**：`UNKNOWN_ERROR` 未在前端做专门文案，会落入通用错误；若需统一体验可加一条。非必须。
- **一致**：错误码字段名、关键码处理一致。

---

## 2. API 契约

### 2.1 创建任务 POST graphs/copilot/actions/create

- **后端**：`CopilotRequest`: prompt, graph_context, graph_id?, conversation_history?, mode?。返回 session_id, status, created_at。
- **前端**：传 prompt, graph_context, graph_id, conversation_history，可选 mode。期望 session_id, status, created_at。
- **一致**：字段与路径一致。conversation_history 见 2.3。

### 2.2 获取会话 GET graphs/copilot/sessions/:id

- **后端**：从 Redis 取 status, content, error。仅当 `status == "generating"` 时返回 content；否则返回 status + content: null，**未在响应中带出 error**。
- **前端**：useCopilotEffects 在 `sessionData?.status === 'failed'` 时用 `sessionData.error || '...'` 展示。
- **不对应**：status 为 failed 时后端未返回 `error`，前端拿不到具体错误信息。
- **建议**：后端在返回会话时若 `session_data.get("status") == "failed"`，在响应中增加 `error: session_data.get("error")`。

### 2.3 对话历史格式 (conversation_history / history API)

- **后端**：`CopilotRequest.conversation_history` 类型为 `List[Dict[str, str]]`，实际只使用 `role`、`content`（见 message_builder.py）。get_history 返回的 messages 含 role('user'|'assistant'), content, actions, thought_steps, tool_calls。
- **前端**：convertConversationHistory 发送 `{ role: 'user'|'assistant', content, actions? }`；历史加载时把 assistant 映射为 model，并读 thought_steps。
- **不对应**：类型标注上后端写的是 Dict[str, str]，实际可含 actions（list），类型与实现不一致。
- **建议**：后端将 conversation_history 类型改为更宽松（如 List[Dict[str, Any]]）或在文档中明确“仅使用 role、content，其余忽略”，避免误导。

### 2.4 历史消息 role 命名

- **后端**：持久化与 API 使用 `user` | `assistant`。
- **前端**：UI 与 state 使用 `user` | `model`；发 API 时转为 `assistant`；加载历史时把 `assistant` 转为 `model`。
- **一致**：转换逻辑明确，无行为不对应。

---

## 3. GraphAction 与 Apply 逻辑

- **类型**：后端 GraphActionType + GraphAction，前端 GraphActionType | GraphAction；payload 结构一致（id, type, label, position, config, source, target 等）。
- **Apply**：后端 action_applier.apply_actions_to_graph_state，前端 ActionProcessor.processActions；契约测试与 fixtures 已覆盖，行为对齐。
- **节点默认配置**：后端 NODE_DEFAULT_CONFIGS / NODE_LABELS 与前端 nodeRegistry 需人工同步，已写在 docs/schemas/README.md。

---

## 4. Stage 与 UI 状态

- **后端**：status 事件的 stage 为任意字符串（如 thinking, processing, analyzing, planning, validating）。
- **前端**：StageType = 'thinking' | 'processing' | 'generating' | 'analyzing' | 'planning' | 'validating'；setCurrentStage 时把 stage 转为 StageType。
- **潜在不对应**：若后端新增未在 StageType 中的 stage，前端会以 string 传入，可能影响类型或展示。当前 DeepAgents 与 standard 使用的 stage 均在 StageType 内，可接受。

---

## 5. 汇总：已完成的修复（高质量架构约束下）

| 优先级 | 项 | 位置 | 已做修改 |
|--------|-----|------|----------|
| 高 | result 事件在 message 为空时未触发 onResult | 前端 [use-copilot-websocket.ts](frontend/hooks/use-copilot-websocket.ts) | 按 type === 'result' 统一调用 onResult，message/actions 用 ?? 兜底，满足契约 |
| 高 | 会话失败时无 error 字段 | 后端 [graphs.py get_copilot_session](backend/app/api/v1/graphs.py) | status 为 failed 时响应中增加 error: session_data.get("error") |
| 中 | conversation_history 类型标注与实现不符 | 后端 [action_types.py CopilotRequest](backend/app/core/copilot/action_types.py) | 改为 List[Dict[str, Any]]，description 注明仅使用 role/content |
| 低 | UNKNOWN_ERROR 无专属前端文案 | 前端 use-copilot-websocket.ts | 错误码统一走 messageByCode 映射，新增 UNKNOWN_ERROR 文案 |

**架构原则**：流式事件以 backend 契约为准，前端按事件 type 分支、不依赖可选字段的真值；错误码与 session 响应与后端约定一致，便于扩展新 code 与字段。

---

## 6. 已对齐或无需改动

- 流式事件类型与字段（除 result 条件、error 的 code 覆盖）。
- 创建任务请求/响应、WebSocket 路径与心跳。
- 历史 API 的 messages 结构与 role 映射。
- GraphAction 与 apply 双端逻辑（含契约测试）。
- 错误码 CREDENTIAL_ERROR、AGENT_ERROR、REDIS_UNAVAILABLE 的前端处理与后端发送一致。
