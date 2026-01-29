# SSE 数据协议重构 - 方案分析与前端适配指南

## 方案评估

### ✅ 方案优势

1. **标准化信封结构**
   - 所有事件遵循统一格式，便于解析和维护
   - 元数据（node_name, run_id, timestamp）统一管理
   - 易于扩展新的事件类型

2. **基于 run_id 的分组机制**
   - 前端可以使用 `run_id` 将同一调用的多个片段聚合
   - 解决 React 渲染时的 key 问题
   - 支持并发流式输出的正确显示

3. **明确的节点标识**
   - `node_name` 直接来自 LangGraph 的 `langgraph_node`
   - 比解析 `checkpoint_ns` 更准确可靠
   - 前端可以显示"当前是哪个 Agent 在工作"

4. **增量与全量分离**
   - `content` 使用 `delta`（增量），减少数据传输
   - `tool_start/end` 使用全量数据，保证完整性
   - 避免 `on_chain_end` 重复发送内容

5. **时间戳支持**
   - 每个事件都有 `timestamp`，便于前端做性能分析
   - 可以显示"这个 token 是什么时候收到的"

### ⚠️ 需要注意的点

1. **向后兼容性**
   - 前端需要适配新的数据结构
   - 建议保留旧版本支持一段时间，逐步迁移

2. **数据嵌套**
   - 从扁平结构改为嵌套结构（`data.delta`）
   - 前端代码需要相应调整

3. **错误处理**
   - 需要处理 `run_id` 为空的情况
   - 需要处理 `data` 字段缺失的情况

## 前端适配方案

### 步骤 1: 更新类型定义

**文件**: `frontend/services/chatBackend.ts`

```typescript
// 新的标准化事件结构
export interface StreamEventEnvelope {
  type: 'content' | 'tool_start' | 'tool_end' | 'status' | 'error' | 'done' | 'thread_id';
  node_name: string;
  run_id: string;
  timestamp: number;
  thread_id: string;
  data: any; // 根据 type 不同而不同
}

// Content 事件的 data 结构
export interface ContentEventData {
  delta: string; // 增量文本
}

// Tool Start 事件的 data 结构
export interface ToolStartEventData {
  tool_name: string;
  tool_input: any;
}

// Tool End 事件的 data 结构
export interface ToolEndEventData {
  tool_name: string;
  tool_output: any;
}

// Error 事件的 data 结构
export interface ErrorEventData {
  message: string;
}

// 兼容旧格式的联合类型（过渡期使用）
export type ChatStreamEvent =
  | StreamEventEnvelope // 新格式
  | { type: 'content'; content: string; thread_id: string } // 旧格式（向后兼容）
  | { type: 'tool_start'; tool_name: string; tool_input: any; thread_id: string }
  | { type: 'tool_end'; tool_name: string; tool_output: any; thread_id: string }
  | { type: 'done'; thread_id: string }
  | { stopped: true; thread_id: string }
  | { type: 'error'; error: string; thread_id: string };
```

### 步骤 2: 创建事件适配器

**文件**: `frontend/services/chatBackend.ts` (新增函数)

```typescript
/**
 * 标准化事件适配器
 * 将新旧格式统一转换为标准格式
 */
export function normalizeStreamEvent(evt: any): StreamEventEnvelope | null {
  // 如果已经是新格式（有 data 字段和 run_id）
  if (evt.data !== undefined && evt.run_id !== undefined) {
    return evt as StreamEventEnvelope;
  }

  // 兼容旧格式，转换为新格式
  if (evt.type === 'content' && evt.content !== undefined) {
    return {
      type: 'content',
      node_name: evt.node_name || 'unknown',
      run_id: evt.run_id || '',
      timestamp: evt.timestamp || Date.now(),
      thread_id: evt.thread_id || '',
      data: {
        delta: evt.content,
      },
    };
  }

  if (evt.type === 'tool_start') {
    return {
      type: 'tool_start',
      node_name: evt.node_name || 'unknown',
      run_id: evt.run_id || '',
      timestamp: evt.timestamp || Date.now(),
      thread_id: evt.thread_id || '',
      data: {
        tool_name: evt.tool_name,
        tool_input: evt.tool_input,
      },
    };
  }

  if (evt.type === 'tool_end') {
    return {
      type: 'tool_end',
      node_name: evt.node_name || 'unknown',
      run_id: evt.run_id || '',
      timestamp: evt.timestamp || Date.now(),
      thread_id: evt.thread_id || '',
      data: {
        tool_name: evt.tool_name,
        tool_output: evt.tool_output,
      },
    };
  }

  if (evt.type === 'error') {
    return {
      type: 'error',
      node_name: evt.node_name || 'system',
      run_id: evt.run_id || '',
      timestamp: evt.timestamp || Date.now(),
      thread_id: evt.thread_id || '',
      data: {
        message: evt.error || 'Unknown error',
      },
    };
  }

  // 处理 stopped 和 done 事件
  if (evt.stopped) {
    return {
      type: 'error',
      node_name: 'system',
      run_id: '',
      timestamp: Date.now(),
      thread_id: evt.thread_id || '',
      data: { message: 'Stream stopped' },
    };
  }

  if (evt.done || evt.type === 'done') {
    return {
      type: 'done',
      node_name: 'system',
      run_id: '',
      timestamp: Date.now(),
      thread_id: evt.thread_id || '',
      data: {},
    };
  }

  return null;
}
```

### 步骤 3: 更新 useBackendChatStream Hook

**文件**: `frontend/app/chat/hooks/useBackendChatStream.ts`

```typescript
import { normalizeStreamEvent, type StreamEventEnvelope } from '../services/chatBackend'

// 在 sendMessage 函数中更新事件处理
onEvent: (evt) => {
  // 标准化事件
  const normalized = normalizeStreamEvent(evt)
  if (!normalized) return

  const { type, thread_id, run_id, node_name, timestamp, data } = normalized

  // 更新 thread_id
  if (thread_id) {
    latestThreadId = thread_id
    currentThreadIdRef.current = thread_id
  }

  // 处理 thread_id 事件
  if (type === 'thread_id') {
    return
  }

  // 处理停止事件
  if (type === 'error' && data.message === 'Stream stopped') {
    setMessages((prev) =>
      prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m))
    )
    return
  }

  // 处理内容事件（使用 run_id 分组）
  if (type === 'content') {
    const delta = (data as ContentEventData).delta
    if (!delta) return

    // 使用 run_id 作为 key，如果不存在则使用 aiMsgId
    const contentKey = run_id || aiMsgId

    setMessages((prev) =>
      prev.map((m) => {
        if (m.id === aiMsgId) {
          // 可以在这里根据 run_id 创建多个消息块
          // 或者简单地追加到当前消息
          return {
            ...m,
            content: m.content + delta,
            // 可选：保存 node_name 和 timestamp 用于显示
            metadata: {
              ...m.metadata,
              lastNode: node_name,
              lastUpdate: timestamp,
            },
          }
        }
        return m
      })
    )
    return
  }

  // 处理工具开始事件
  if (type === 'tool_start') {
    const { tool_name, tool_input } = data as ToolStartEventData
    const toolId = generateId()
    lastRunningToolIdByName[tool_name] = toolId

    const tool: ToolCall = {
      id: toolId,
      name: tool_name,
      args: tool_input,
      status: 'running',
      startTime: timestamp || now(),
    }

    setMessages((prev) =>
      prev.map((m) =>
        m.id === aiMsgId
          ? { ...m, tool_calls: [...(m.tool_calls || []), tool] }
          : m
      )
    )
    return
  }

  // 处理工具结束事件
  if (type === 'tool_end') {
    const { tool_name, tool_output } = data as ToolEndEventData
    const toolId = lastRunningToolIdByName[tool_name]

    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== aiMsgId) return m
        const tools = (m.tool_calls || []).map((t) => {
          if (toolId && t.id === toolId) {
            return {
              ...t,
              status: 'completed' as const,
              endTime: timestamp || now(),
              result: tool_output,
            }
          }
          return t
        })
        return { ...m, tool_calls: tools }
      })
    )
    return
  }

  // 处理错误事件
  if (type === 'error') {
    const errorMsg = (data as ErrorEventData).message
    setMessages((prev) =>
      prev.map((m) =>
        m.id === aiMsgId
          ? { ...m, content: (m.content || '') + `\n\n*Error: ${errorMsg}*` }
          : m
      )
    )
    return
  }

  // 处理完成事件
  if (type === 'done') {
    setMessages((prev) =>
      prev.map((m) => (m.id === aiMsgId ? { ...m, isStreaming: false } : m))
    )
    return
  }
}
```

### 步骤 4: 更新 eventAdapter

**文件**: `frontend/app/workspace/[workspaceId]/[agentId]/services/eventAdapter.ts`

```typescript
import { normalizeStreamEvent, type StreamEventEnvelope } from '@/services/chatBackend'

export function mapChatEventToExecutionStep(
  evt: ChatStreamEvent,
  ctx: EventAdapterContext
): AdapterResult {
  // 标准化事件
  const normalized = normalizeStreamEvent(evt)
  if (!normalized) return { type: 'noop' }

  const { type, data, node_name, run_id, timestamp } = normalized
  const { currentThoughtId, toolStepMap, genId, getSteps } = ctx

  // 处理停止事件
  if (type === 'error' && (data as any).message === 'Stream stopped') {
    return { type: 'stopped' }
  }

  // 处理内容事件
  if (type === 'content') {
    const delta = (data as any).delta
    if (!delta) return { type: 'noop' }

    // 使用 node_name 和 run_id 创建更精确的步骤
    if (!currentThoughtId) {
      const thoughtId = genId('thought')
      return {
        type: 'add_step',
        step: {
          id: thoughtId,
          nodeId: node_name || 'agent',
          nodeLabel: node_name || 'Agent',
          stepType: 'agent_thought',
          title: `Reasoning (${node_name})`,
          status: 'running',
          startTime: timestamp || Date.now(),
          content: delta,
        },
      }
    }

    return {
      type: 'append_content',
      stepId: currentThoughtId,
      content: delta,
    }
  }

  // 处理工具开始事件
  if (type === 'tool_start') {
    const { tool_name, tool_input } = data as any

    const toolId = genId('tool')
    toolStepMap.set(tool_name, toolId)

    return {
      type: 'add_step',
      step: {
        id: toolId,
        nodeId: node_name || 'tool',
        nodeLabel: tool_name,
        stepType: 'tool_execution',
        title: tool_name,
        status: 'running',
        startTime: timestamp || Date.now(),
        data: { request: tool_input },
      },
    }
  }

  // 处理工具结束事件
  if (type === 'tool_end') {
    const { tool_name, tool_output } = data as any

    const toolId = toolStepMap.get(tool_name)
    if (!toolId) return { type: 'noop' }

    const existingStep = getSteps().find((s) => s.id === toolId)
    toolStepMap.delete(tool_name)

    return {
      type: 'update_step',
      stepId: toolId,
      updates: {
        status: 'success',
        endTime: timestamp || Date.now(),
        data: {
          request: existingStep?.data?.request,
          response: tool_output,
        },
      },
    }
  }

  // 处理错误事件
  if (type === 'error') {
    const errorMsg = (data as any).message || 'Unknown error'

    return {
      type: 'add_step',
      step: {
        id: genId('error'),
        nodeId: node_name || 'system',
        nodeLabel: 'Error',
        stepType: 'system_log',
        title: 'Error',
        status: 'error',
        startTime: timestamp || Date.now(),
        content: errorMsg,
      },
    }
  }

  // 处理完成事件
  if (type === 'done') {
    return { type: 'done' }
  }

  return { type: 'noop' }
}
```

### 步骤 5: 利用 run_id 进行高级聚合（可选）

如果需要支持多个并发流式输出，可以这样处理：

```typescript
// 在 useBackendChatStream 中
const runIdToMessageMap = useRef<Map<string, string>>(new Map())

// 处理 content 事件时
if (type === 'content') {
  const delta = (data as ContentEventData).delta
  if (!delta) return

  if (run_id) {
    // 如果 run_id 存在，检查是否需要创建新的消息块
    if (!runIdToMessageMap.current.has(run_id)) {
      // 创建新的消息块
      const newMsgId = generateId()
      runIdToMessageMap.current.set(run_id, newMsgId)

      setMessages((prev) => [
        ...prev,
        {
          id: newMsgId,
          role: 'assistant',
          content: delta,
          timestamp: timestamp || now(),
          isStreaming: true,
          tool_calls: [],
          metadata: { run_id, node_name },
        },
      ])
    } else {
      // 追加到现有消息
      const msgId = runIdToMessageMap.current.get(run_id)!
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? { ...m, content: m.content + delta }
            : m
        )
      )
    }
  } else {
    // 回退到旧逻辑（使用 aiMsgId）
    setMessages((prev) =>
      prev.map((m) =>
        m.id === aiMsgId ? { ...m, content: m.content + delta } : m
      )
    )
  }
}
```

## 迁移建议

### 阶段 1: 兼容模式（推荐）
1. 更新类型定义，支持新旧两种格式
2. 创建 `normalizeStreamEvent` 适配器
3. 逐步更新事件处理逻辑

### 阶段 2: 完全迁移
1. 移除旧格式支持
2. 全面使用新格式
3. 利用 `run_id` 和 `node_name` 增强 UI

### 阶段 3: 增强功能
1. 使用 `node_name` 显示当前执行的节点
2. 使用 `timestamp` 做性能分析
3. 使用 `run_id` 支持并发流式输出

## 测试清单

- [ ] 验证 content 事件的 delta 正确拼接
- [ ] 验证 tool_start/end 事件正确显示
- [ ] 验证 run_id 正确分组
- [ ] 验证 node_name 正确显示
- [ ] 验证错误处理
- [ ] 验证向后兼容性（如果有旧版本后端）

## 总结

这个方案是**合适的**，主要优势：
1. ✅ 标准化结构，易于维护
2. ✅ run_id 支持更好的分组
3. ✅ node_name 提供更清晰的上下文
4. ✅ 增量/全量分离，性能更好

前端适配需要：
1. 更新类型定义
2. 创建适配器函数（兼容新旧格式）
3. 更新事件处理逻辑
4. 可选：利用新字段增强 UI

建议采用**渐进式迁移**，先支持兼容模式，再逐步完全迁移。
