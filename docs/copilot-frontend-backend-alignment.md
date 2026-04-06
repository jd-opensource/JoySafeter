# Copilot 前后端架构对照

本文档梳理 Copilot 前后端在通信、事件、API、类型上的架构对齐关系。

> **架构说明**：Copilot 已迁移至 Run Center 模型。前端通过共享 `/ws/chat` WebSocket 发送 `extension: { kind: "copilot" }` 消息，后端通过 `execute_copilot_turn` 消费 `CopilotService._get_copilot_stream()`，事件持久化到 `agent_run_events` 表，状态投影存储于 `agent_run_snapshots`。

---

## 1. 通信架构

### 1.1 消息发送流程

```
前端 CopilotPanel
  → useCopilotActions.handleSendWithInput()
    → runService.createRun({ agent_name: "copilot", graph_id, message })   // REST: 创建 run
    → getChatWsClient().sendChat({
        requestId,
        input: { message, model },
        graphId,
        extension: { kind: "copilot", runId, graphContext, conversationHistory, mode }
      })                                                                     // WS: chat.start 帧
```

### 1.2 后端处理链路

```
/ws/chat → ChatWsHandler
  → chat_protocol.parse_client_frame()  → ParsedCopilotExtension
  → chat_commands.build_command_from_parsed_frame()  → CopilotTurnCommand
  → chat_turn_executor.execute_copilot_turn()
    → CopilotService._get_copilot_stream()
    → _emit_event() per event  →  WS 推送 + _mirror_run_stream_event() 持久化
  → _finalize_task()  →  更新 run status (completed/failed)
```

### 1.3 页面刷新恢复（Live Event Replay）

```
前端 useCopilotEffects
  → 检测 state.currentRunId
  → runService.getRunSnapshot(runId)  // REST: 获取快照
  → 若 status 为 running/queued:
    → getRunWsClient().subscribe(runId, afterSeq, { onEvent, onStatus })  // /ws/runs 订阅
    → runEventToChatEvent() 适配器将 RunEventFrame → ChatStreamEvent
    → handleCopilotEvent() 驱动 UI 更新
```

---

## 2. 流式事件契约（WebSocket）

### 2.1 事件类型与字段

| 事件类型 | 后端 `_get_copilot_stream` 发出 | 前端 `handleCopilotEvent` 处理 | 持久化事件类型 |
|----------|-------------------------------|-------------------------------|--------------|
| `status` | `{ type, stage?, message }` | `onStatus(stage, message)` → 更新 stage 指示器 | `status` |
| `content` | `{ type, content }` | `onContent(content)` → 追加流式内容 | `content_delta` |
| `thought_step` | `{ type, step: { index, content } }` | `onThoughtStep(step)` → 追加思考步骤 | `thought_step` |
| `tool_call` | `{ type, tool, input }` | `onToolCall(tool, input)` → 显示工具调用 | `tool_call` |
| `tool_result` | `{ type, action: { type, payload, reasoning? } }` | `onToolResult(action)` → 显示工具结果 | `tool_result` |
| `result` | `{ type, message, actions[] }` | `onResult({ message, actions })` → 最终结果和图操作 | `result` |
| `error` | `{ type, message, code? }` | `onError(message)` → 显示错误 | `error` |
| `done` | `{ type }` | `onDone()` → 清理状态 | `done` |

### 2.2 事件持久化映射 (`_mirror_run_stream_event`)

后端 `ChatWsHandler._mirror_run_stream_event` 将 WS 事件翻译为持久化 payload：

- **`content`** → 存储为 `content_delta`，payload: `{ message_id, delta }`（`delta` 取自 `data.delta` 或 `data.content`）
- **`status`** → 区分是否有 `stage`：有则 `{ stage, message }`，无则 `{ message, status }`
- **`thought_step / tool_call / tool_result / result`** → 直接透传 `data` 作为 payload
- **`error`** → `{ message, code }`
- **`done`** → `{}`

前端 `/ws/runs` 回放时通过 `runEventToChatEvent()` 反向映射 `content_delta` → `content`。

### 2.3 Copilot Reducer（投影状态）

`backend/app/services/run_reducers/copilot.py` 维护 run 投影：

```python
{
    "version": 1,
    "run_type": "copilot_turn",
    "status": "queued | running | completed | failed",
    "stage": "thinking | processing | analyzing | ...",
    "content": "",           # 累积的流式内容
    "thought_steps": [],     # 思考步骤列表
    "tool_calls": [],        # 工具调用列表 { tool, input }
    "tool_results": [],      # 工具结果/图操作列表
    "result_message": None,  # 最终结果消息
    "result_actions": [],    # 最终图操作列表
    "error": None,
    "graph_id": None,
    "mode": None,            # "standard" | "deepagents"
}
```

---

## 3. REST API 契约

### 3.1 创建 Run

```
POST /api/v1/runs
Body: { agent_name: "copilot", graph_id: "<uuid>", message: "<user prompt>" }
Response: { run_id: "<uuid>", status: "queued", ... }
```

### 3.2 获取历史

```
GET /api/v1/graphs/{graph_id}/copilot/history
Response: { data: { graph_id, messages: [ { role, content, created_at, actions?, thought_steps?, tool_calls? } ] } }
```

历史从 `agent_runs` + `agent_run_snapshots` 表组装，按时间正序返回 user/assistant 消息对。

### 3.3 清除历史

```
DELETE /api/v1/graphs/{graph_id}/copilot/history
Response: { success: true }
```

硬删除该 graph 下所有 `agent_name="copilot"` 的 runs 及关联的 events/snapshots（级联删除）。

---

## 4. 取消机制（handleStop）

```
前端 useCopilotActions.handleStop()
  → getChatWsClient().stopByRequestId(activeRequestId)   // 发送 chat.stop 帧
  → 后端 ChatWsHandler 取消 asyncio task
  → execute_copilot_turn 的 CancelledError 分支发出 done 事件
  → _finalize_task 根据 StreamState.stopped 标记 run 为 completed
```

前端通过 `useRef<string>(activeRequestIdRef)` 跟踪当前请求 ID，在 `handleSendWithInput` 开始时设置，`finally` 块中清除。

---

## 5. GraphAction 与 Apply 逻辑

- **类型**：后端 `GraphActionType` + `GraphAction`，前端 `GraphActionType` | `GraphAction`；payload 结构一致
- **Apply**：后端 `action_applier.apply_actions_to_graph_state`，前端 `ActionProcessor.processActions`
- **节点默认配置**：后端 `NODE_DEFAULT_CONFIGS` / `NODE_LABELS` 与前端 `nodeRegistry` 需人工同步

---

## 6. Stage 与 UI 状态

- **后端**：`status` 事件的 `stage` 为字符串（如 `thinking`, `processing`, `analyzing`, `planning`, `validating`）
- **前端**：`StageType = 'thinking' | 'processing' | 'generating' | 'analyzing' | 'planning' | 'validating'`
- 若后端新增未在 `StageType` 中的 stage，前端会以 string 传入，当前已有的 stage 均在 `StageType` 内

---

## 7. 关键文件索引

### 后端
| 文件 | 职责 |
|------|------|
| `app/websocket/chat_protocol.py` | `ParsedCopilotExtension` 解析 |
| `app/websocket/chat_commands.py` | `CopilotTurnCommand` 派发 |
| `app/websocket/chat_turn_executor.py` | `execute_copilot_turn` 执行 |
| `app/websocket/chat_ws_handler.py` | `_mirror_run_stream_event` 事件持久化 |
| `app/services/run_reducers/copilot.py` | Copilot reducer 投影 |
| `app/services/copilot_service.py` | `_get_copilot_stream` 流式生成、`execute_copilot_turn` 入口 |
| `app/api/v1/graphs.py` | 历史 API（从 `agent_runs` 读取） |

### 前端
| 文件 | 职责 |
|------|------|
| `lib/ws/chat/types.ts` | `CopilotExtension` 类型定义 |
| `lib/ws/chat/chatWsClient.ts` | `serializeExtension` copilot 分支 |
| `hooks/copilot/useCopilotSession.ts` | `currentRunId` + localStorage 持久化 |
| `app/workspace/.../hooks/useCopilotState.ts` | 统一状态管理 |
| `app/workspace/.../hooks/useCopilotActions.ts` | `runService.createRun` + `sendChat` |
| `app/workspace/.../hooks/useCopilotWebSocketHandler.ts` | `handleCopilotEvent` 事件桥接 |
| `app/workspace/.../hooks/useCopilotEffects.ts` | Run snapshot 恢复 + `/ws/runs` 订阅 |

### 测试
| 文件 | 覆盖范围 |
|------|---------|
| `tests/test_services/test_copilot_run_reducer.py` | Reducer 单元测试 |
| `tests/test_api/test_chat_protocol_copilot_extension.py` | 协议解析测试 |
| `tests/test_api/test_chat_commands_copilot.py` | 命令派发测试 |
| `tests/test_api/test_copilot_event_mirroring.py` | 事件镜像 + reducer 集成测试 |
| `tests/test_api/test_copilot_history_from_runs.py` | 历史 API 单元测试 |
