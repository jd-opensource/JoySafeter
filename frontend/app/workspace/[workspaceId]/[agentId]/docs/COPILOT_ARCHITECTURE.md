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
- `onResult` - 最终结果
- `onError` - 错误处理

**优势**：
- ✅ 所有 WebSocket 逻辑集中管理
- ✅ 统一的错误处理策略
- ✅ 性能优化（useMemo）

---

### 3. **useCopilotActions** - 业务逻辑处理

**职责**：处理所有用户交互和业务逻辑

**位置**：`hooks/useCopilotActions.ts`

**功能**：
- `handleSend` - 发送消息
- `handleSendWithInput` - 使用指定输入发送
- `handleStop` - 停止生成
- `handleReset` - 重置对话
- `handleAIDecision` - AI 决策提示

**优势**：
- ✅ 业务逻辑与 UI 分离
- ✅ 易于单元测试
- ✅ 可复用的业务逻辑

---

### 4. **useCopilotEffects** - 副作用管理

**职责**：处理所有副作用（useEffect）

**位置**：`hooks/useCopilotEffects.ts`

**功能**：
- Session 恢复（断点续传）
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

## 🔄 图状态双写与权威

- **权威来源**：后端持久化后的图状态为权威。前端在 `onResult` 中先乐观执行 actions 以即时更新 UI，随后通过 `queryClient.invalidateQueries({ queryKey: graphKeys.state(graphId) })` 从服务端重新拉取图状态；该 invalidate 即视为以服务端为准的校正，无需额外二次 refetch。
- **应用逻辑契约**：前端 [actionProcessor](frontend/utils/copilot/actionProcessor.ts) 与后端 [action_applier](backend/app/core/copilot/action_applier.py) 需保持同一套规则（CREATE_NODE / CONNECT_NODES / DELETE_NODE / UPDATE_CONFIG / UPDATE_POSITION）。修改其一时请同步另一侧，长期可考虑由共享类型或后端生成前端 apply 逻辑。
- **Apply 契约测试**：用例数据见 `docs/schemas/copilot-apply-fixtures.json`；后端测试 `backend/tests/core/copilot/test_action_applier.py`、前端测试 `frontend/utils/copilot/__tests__/actionProcessor.contract.test.ts` 共用该用例，保证双端 apply 行为一致。

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
User Interaction
      │
      ▼
CopilotPanel (UI)
      │
      ▼
useCopilotActions (Business Logic)
      │
      ├─► API Call (copilotService)
      │       │
      │       ▼
      │   Backend Response
      │       │
      │       ▼
      └─► useCopilotState (State Update)
              │
              ▼
      WebSocket Connection
              │
              ▼
useCopilotWebSocketHandler (Event Handling)
              │
              ▼
      useCopilotState (State Update)
              │
              ▼
      CopilotPanel (UI Re-render)
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
  state,      // 从 useCopilotState 获取
  actions,    // 从 useCopilotState 获取
  refs,       // 从 useCopilotState 获取
  graphId,    // 从组件 props 获取
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
// CopilotPanel 组件现在非常简洁
export const CopilotPanel: React.FC = () => {
  // 1. 获取统一状态
  const { state, actions, refs } = useCopilotState(graphId)

  // 2. 获取 WebSocket 处理器
  const webSocketCallbacks = useCopilotWebSocketHandler({
    state, actions, refs, graphId
  })

  // 3. 获取业务逻辑处理器
  const {
    handleSend,
    handleStop,
    handleReset,
  } = useCopilotActions({
    state, actions, refs, graphId
  })

  // 4. 设置副作用
  useCopilotEffects({
    state, actions, refs, graphId, handleSendWithInput
  })

  // 5. 连接 WebSocket
  useCopilotWebSocket({
    sessionId: state.currentSessionId,
    callbacks: webSocketCallbacks,
  })

  // 6. 渲染 UI
  return <div>...</div>
}
```

## 🔍 对比：重构前后

### 重构前
- ❌ 684 行巨型组件
- ❌ 业务逻辑和 UI 混在一起
- ❌ 难以测试和维护
- ❌ 状态管理分散

### 重构后
- ✅ 约 100 行简洁组件
- ✅ 清晰的职责分离
- ✅ 易于测试和维护
- ✅ 统一的状态管理

## 🎓 最佳实践

1. **状态管理**：使用 `useCopilotState` 作为单一数据源
2. **业务逻辑**：所有业务逻辑放在 `useCopilotActions`
3. **副作用**：所有 useEffect 放在 `useCopilotEffects`
4. **WebSocket**：所有 WebSocket 逻辑放在 `useCopilotWebSocketHandler`
5. **工具函数**：共享的工具函数放在 `copilotUtils`

## 📚 相关文件

- `components/CopilotPanel.tsx` - 主组件（UI 层）
- `hooks/useCopilotState.ts` - 状态管理
- `hooks/useCopilotWebSocketHandler.ts` - WebSocket 处理
- `hooks/useCopilotActions.ts` - 业务逻辑
- `hooks/useCopilotEffects.ts` - 副作用管理
- `utils/copilotUtils.ts` - 工具函数

---

**架构设计者**：AI Assistant
**最后更新**：2026-01-19
**版本**：2.0.0
