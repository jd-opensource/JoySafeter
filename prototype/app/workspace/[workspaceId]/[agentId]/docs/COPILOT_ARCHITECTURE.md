# Copilot 架构设计文档

## 📋 概述

本文档描述了 AgentBuilder Copilot 前端组件的清晰、完整的架构设计。该架构采用**关注点分离**和**单一职责原则**，将复杂的业务逻辑拆分为多个专门的 hooks，使代码更易维护、测试和扩展。

## 🏗️ 架构层次

```
┌─────────────────────────────────────────────────────────┐
│                  CopilotPanel (UI Layer)                │
│  - 纯 UI 组件，只负责渲染和组合                          │
│  - 从 hooks 获取状态和操作                               │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ State Layer  │  │  Logic Layer │  │ Effects Layer│
│              │  │              │  │              │
│useCopilotState│ │useCopilotActions│ │useCopilotEffects│
└──────────────┘  └──────────────┘  └──────────────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  WebSocket Layer      │
              │                       │
              │useCopilotWebSocketHandler│
              └───────────────────────┘
```

## 📦 核心模块

### 1. **useCopilotState** - 统一状态管理

**职责**：统一管理所有 Copilot 相关的状态

**位置**：`hooks/useCopilotState.ts`

**功能**：
- 整合多个子 hooks（messages, streaming, actions, session）
- 提供统一的状态接口
- 管理本地 UI 状态（input, loading, expandedItems）
- 提供统一的 actions 接口
- 管理所有 refs（生命周期跟踪、DOM 引用）

**状态域**：
```typescript
interface CopilotState {
  // Message state
  messages, loadingHistory

  // Streaming state
  streamingContent, currentStage, currentToolCall, toolResults

  // Action execution state
  executingActions

  // Session state
  currentSessionId

  // Local UI state
  input, loading, expandedItems, copiedStreaming
}
```

**优势**：
- ✅ 单一数据源（Single Source of Truth）
- ✅ 状态集中管理，易于调试
- ✅ 类型安全的状态接口

---

### 2. **useCopilotWebSocketHandler** - WebSocket 事件处理

**职责**：处理所有 WebSocket 事件

**位置**：`hooks/useCopilotWebSocketHandler.ts`

**功能**：
- 封装所有 WebSocket 回调函数
- 统一的挂载状态检查
- 错误处理和用户友好的错误消息
- 使用 `useMemo` 优化性能

**事件处理**：
- `onConnect` - 连接建立
- `onStatus` - 状态更新
- `onContent` - 内容流式传输
- `onThoughtStep` - 思考步骤
- `onToolCall` - 工具调用
- `onToolResult` - 工具结果
- `onResult` - 最终结果（仅乐观渲染，不清理 session）
- `onDone` - 后端持久化完成后：invalidate 缓存 + 清理 session/loading
- `onError` - 错误处理

**优势**：
- ✅ 所有 WebSocket 逻辑集中管理
- ✅ 统一的错误处理策略
- ✅ 性能优化（useMemo + stateRef 减少依赖）

---

### 3. **useCopilotActions** - 业务逻辑处理

**职责**：处理所有用户交互和业务逻辑

**位置**：`hooks/useCopilotActions.ts`

**功能**：
- `handleSend` - 发送消息
- `handleSendWithInput` - 使用指定输入发送（携带当前 `copilotMode` 调用 `createCopilotTask`）
- `handleStop` - 停止生成
- `handleReset` - 重置对话
- `handleAIDecision` - AI 决策提示

**模式**：`useCopilotActions` 接收 `copilotMode`（`'standard'` | `'deepagents'`），提交任务时传给后端 `mode` 参数。

**优势**：
- ✅ 业务逻辑与 UI 分离
- ✅ 易于单元测试
- ✅ 可复用的业务逻辑

---

### 4. **useCopilotEffects** - 副作用管理

**职责**：处理所有副作用（useEffect）

**位置**：`hooks/useCopilotEffects.ts`

**功能**：
- **Session 恢复**：根据 `getSession` 结果分支处理
  - `sessionData == null` 或 `status == null`：清理 localStorage/session，避免死循环
  - `generating` 且存在缓存的 `result`：先应用 `executeActions` + `finalizeCurrentMessage`，再由 WebSocket 重连继续
  - `generating` 无 result：恢复 content/thinking UI，WebSocket 重连
  - `completed`：清理 session，图数据由 AgentBuilder 的 `refetchOnMount: 'always'` 从 DB 加载
  - `failed`：toast 提示并清理 session
- 自动滚动优化
- 页面标题更新
- 离开页面警告
- URL 参数处理

**优势**：
- ✅ 副作用集中管理
- ✅ 易于理解和维护
- ✅ 性能优化（内容签名检测）

---

### 5. **copilotUtils** - 工具函数

**职责**：提供共享的工具函数

**位置**：`utils/copilotUtils.ts`

**功能**：
- `formatActionContent` - 格式化动作内容
- `hasCurrentMessage` - 检查当前消息
- `getStageConfig` - 获取阶段配置

**优势**：
- ✅ 可复用的工具函数
- ✅ 易于测试
- ✅ 纯函数，无副作用

---

## 🔄 图状态架构（后端唯一写入 + 前端乐观渲染）

### 原则

- **后端是图状态的唯一写入方**：仅由 `_persist_graph_from_actions` 在生成完成后写 DB；前端不再在 `applyAIChanges` 中调用 `immediateSave()`，避免双写竞争。
- **前端只做乐观渲染**：`onResult` 中执行 `executeActions` → `applyAIChanges`，仅更新 builderStore 的 nodes/edges，不触发保存。
- **顺序消息队列**：`use-copilot-websocket` 内消息入队并顺序处理，保证 async 的 `onResult` 完全执行后再处理 `onDone`，避免乱序。
- **Result 可恢复**：后端在产出 `result` 后写入 Redis（`set_copilot_result`），会话恢复或刷新时可通过 `getSession` 的 `result` 字段应用未持久化的结果。
- **done 语义**：后端在 `_persist_graph_from_actions` 完成后才发布 `done`。前端 `onDone` 中做：`invalidateQueries`（graph state + copilot history）、清理 session/loading，便于下次进入或刷新从 DB 拉取最新数据。

### 事件流简述

1. 用户提交 → `createCopilotTask`（带 `mode`）→ 获得 `session_id`，建立 WebSocket。
2. 后端流式推送：status / content / thought_step / tool_call / tool_result → **result**（后端同时缓存 result 到 Redis）→ 前端 `onResult` 乐观渲染。
3. 后端持久化图 → 设置 status=completed → 推送 **done** → 前端 `onDone` invalidate + 清理。
4. WebSocket 连接时：若会话已 completed，先发缓存的 result + done 再关闭；若 failed 则发 error 再关闭；若 generating 且已有 result 则先发 result 再订阅 Pub/Sub。

### 应用逻辑契约

- 前端 [actionProcessor](frontend/utils/copilot/actionProcessor.ts) 与后端 [action_applier](backend/app/core/copilot/action_applier.py) 需保持同一套规则（CREATE_NODE / CONNECT_NODES / DELETE_NODE / UPDATE_CONFIG / UPDATE_POSITION），含节点 ID 去重等幂。
- 用例数据：`docs/schemas/copilot-apply-fixtures.json`；后端测试 `backend/tests/core/copilot/test_action_applier.py`、前端测试 `frontend/utils/copilot/__tests__/actionProcessor.contract.test.ts` 共用该用例，保证双端 apply 行为一致。

## 类型契约

- **权威定义**：Copilot 流式事件与 GraphAction 的权威定义在后端 `backend/app/core/copilot/action_types.py`（含 `CopilotStatusEvent`、`CopilotContentEvent`、`CopilotResultEvent`、`CopilotErrorEvent` 等及 `GraphAction`）。
- **导出 Schema**：通过脚本 `backend/scripts/export_copilot_schema.py` 导出 JSON Schema 至 `docs/schemas/copilot-contract.json`，供前端与工具识别事件形态。重新生成：`python backend/scripts/export_copilot_schema.py`。
- **前端类型来源**：前端 `frontend/types/copilot.ts` 与 `frontend/hooks/use-copilot-websocket.ts` 中的 `CopilotWebSocketEvent` 与契约人工对齐，文件顶注释指向上述 schema；新增/修改事件字段时需同步 schema 与前端类型。

| 事件 type     | 主要字段 |
|---------------|----------|
| status        | stage, message |
| content       | content |
| thought_step  | step: { index, content } |
| tool_call     | tool, input |
| tool_result   | action: { type, payload, reasoning? } |
| result        | message, actions, batch? |
| done          | （无额外字段） |
| error         | message, code |

**新增或修改 GraphAction 类型时**：需 (1) 改 backend `action_types.py` 的 `GraphActionType` 与 payload 模型（若有）、(2) 运行 `export_copilot_schema.py` 更新 schema、(3) 更新前端 `types/copilot.ts` 与 apply 逻辑（ActionProcessor + action_applier）、(4) 补充或更新 `docs/schemas/copilot-apply-fixtures.json` 用例并跑双端测试。

## 🔄 数据流

```
User Interaction (含模式选择 copilotMode)
      │
      ▼
CopilotPanel (UI) ── copilotMode state ──► CopilotInput 下拉框（单Agent / DeepAgents）
      │
      ▼
useCopilotActions (Business Logic, 携带 copilotMode)
      │
      ├─► createCopilotTask({ ..., mode: copilotMode })
      │       │
      │       ▼
      │   Backend 返回 session_id
      │       │
      │       ▼
      └─► setSession(sessionId) → useCopilotWebSocket 连接
              │
              ▼
      use-copilot-websocket：消息入队，顺序执行 handleMessage（await onResult / onDone）
              │
              ▼
useCopilotWebSocketHandler
  · onResult → 乐观渲染（executeActions → applyAIChanges），不写 DB、不清理 session
  · onDone   → invalidateQueries + clearSession / setLoading(false)
              │
              ▼
      useCopilotState (State Update) → CopilotPanel (UI Re-render)
```

## 🎯 设计原则

### 1. **单一职责原则**
每个 hook 只负责一个特定的功能域：
- `useCopilotState` - 状态管理
- `useCopilotWebSocketHandler` - WebSocket 处理
- `useCopilotActions` - 业务逻辑
- `useCopilotEffects` - 副作用

### 2. **关注点分离**
- UI 层：只负责渲染
- 业务层：处理业务逻辑
- 状态层：管理状态
- 副作用层：处理副作用

### 3. **依赖注入**
所有 hooks 通过参数接收依赖，而不是直接导入：
```typescript
useCopilotActions({
  state,       // 从 useCopilotState 获取
  actions,     // 从 useCopilotState 获取
  refs,        // 从 useCopilotState 获取
  graphId,     // 从路由/组件获取
  copilotMode, // 从 CopilotPanel 的 useState 获取，用于提交任务时传 mode
})
```

### 4. **类型安全**
所有接口都有完整的 TypeScript 类型定义：
- `CopilotState` - 状态类型
- `CopilotActions` - 操作类型
- `CopilotRefs` - 引用类型

## 🚀 优势总结

### 代码质量
- ✅ **可维护性**：职责清晰，易于理解和修改
- ✅ **可测试性**：每个 hook 可以独立测试
- ✅ **可扩展性**：新功能可以轻松添加到相应的 hook
- ✅ **类型安全**：完整的 TypeScript 类型定义

### 性能优化
- ✅ **useMemo**：WebSocket callbacks 使用 useMemo 优化
- ✅ **useCallback**：所有事件处理函数使用 useCallback
- ✅ **内容签名**：自动滚动使用内容签名避免不必要的滚动
- ✅ **依赖优化**：所有 hooks 的依赖项都经过优化

### 错误处理
- ✅ **挂载检查**：所有异步操作都有挂载状态检查
- ✅ **资源清理**：所有 timeout 和资源都有清理机制
- ✅ **错误边界**：使用 CopilotErrorBoundary 捕获错误
- ✅ **用户友好**：所有错误都有用户友好的消息

## 📝 使用示例

```typescript
// CopilotPanel 组件
export const CopilotPanel: React.FC = () => {
  const [copilotMode, setCopilotMode] = useState<CopilotMode>('deepagents')

  const { state, actions, refs } = useCopilotState(graphId)

  const webSocketCallbacks = useCopilotWebSocketHandler({
    state, actions, refs, graphId
  })

  const { handleSend, handleSendWithInput, handleStop, handleReset, handleAIDecision } =
    useCopilotActions({
      state, actions, refs, graphId,
      copilotMode,  // 提交时传给 createCopilotTask 的 mode
    })

  useCopilotEffects({
    state, actions, refs, graphId, handleSendWithInput
  })

  useCopilotWebSocket({
    sessionId: state.currentSessionId,
    callbacks: webSocketCallbacks,
    autoReconnect: true,
  })

  return (
    <>
      <CopilotChat ... />
      <CopilotInput
        ...
        copilotMode={copilotMode}
        onModeChange={setCopilotMode}
      />
    </>
  )
}
```

## 🖥️ UI：模式选择

- **位置**：`components/copilot/CopilotInput.tsx` 顶部工具栏一行。
- **交互**：二选一下拉框（单Agent 模式 / DeepAgents 模式），位于「AI 自动完善」右侧，Reset 按钮位于该行最右侧。
- **状态**：`CopilotPanel` 内 `useState<CopilotMode>('deepagents')`，通过 `copilotMode` / `onModeChange` 传入 `CopilotInput` 与 `useCopilotActions`。
- **文案**：i18n 键 `workspace.copilotModeSingleAgent`、`workspace.copilotModeDeepAgents`。


## 🎓 最佳实践

1. **状态管理**：使用 `useCopilotState` 作为单一数据源
2. **业务逻辑**：所有业务逻辑放在 `useCopilotActions`
3. **副作用**：所有 useEffect 放在 `useCopilotEffects`
4. **WebSocket**：所有 WebSocket 逻辑放在 `useCopilotWebSocketHandler`
5. **工具函数**：共享的工具函数放在 `copilotUtils`

## 📚 相关文件

**前端（本 workspace）**
- `components/CopilotPanel.tsx` - 主组件（UI 层，含 copilotMode state）
- `components/copilot/CopilotInput.tsx` - 输入区与模式下拉框
- `hooks/useCopilotState.ts` - 状态管理
- `hooks/useCopilotWebSocketHandler.ts` - WebSocket 事件回调（onResult 乐观渲染 / onDone 清理）
- `hooks/useCopilotActions.ts` - 业务逻辑（含 copilotMode 传参）
- `hooks/useCopilotEffects.ts` - 副作用与 session 恢复
- `utils/copilotUtils.ts` - 工具函数

**前端（全局）**
- `hooks/use-copilot-websocket.ts` - WebSocket 连接与消息队列（顺序处理 async 回调）
- `utils/copilot/actionProcessor.ts` - GraphAction 应用逻辑
- `services/copilotService.ts` - createCopilotTask / getSession（含 result 字段）
- `types/copilot.ts` - GraphAction / CopilotResponse 等类型

**后端**
- `app/services/copilot_service.py` - 生成流、Redis 发布、result 缓存、_persist_graph_from_actions
- `app/websocket/copilot_handler.py` - 连接时检查会话状态，completed/failed 立即回送
- `app/core/redis.py` - set_copilot_result / get_copilot_result / get_copilot_session
- `app/core/copilot/action_applier.py` - apply_actions_to_graph_state

---

**架构设计者**：AI Assistant
**最后更新**：2026-03-15
**版本**：3.0.0
