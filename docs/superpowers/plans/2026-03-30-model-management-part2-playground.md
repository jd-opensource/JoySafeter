# 模型管理重构 Part 2：Playground 模型测试

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在模型管理详情面板中新增 Playground Tab，支持流式模型测试（SSE）、参数临时调节、性能指标展示（TTFT、token 用量、响应速度）。

**Architecture:** 后端将 test-output 端点改为 SSE 流式响应（复用项目中已有的 StreamingResponse 模式），前端用 fetch + ReadableStream 消费。性能指标在后端计算后通过 SSE metrics 事件推送。

**Tech Stack:** FastAPI StreamingResponse / SSE / React 19 / TypeScript / Tailwind

**Spec:** `docs/superpowers/specs/2026-03-30-model-management-refactor-design.md` Section 3

**前置依赖：** Part 1 计划完成（Master-Detail 布局 + detail-panel Tab 骨架已就位）

---

## File Structure

### 后端修改

| 操作 | 文件 | 职责 |
|------|------|------|
| Modify | `backend/app/api/v1/models.py` | 改造 test-output 为 SSE 端点 |
| Modify | `backend/app/services/model_service.py` | test_output 改为异步生成器 |

### 前端新增

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `frontend/app/settings/models/components/detail-panel/playground-tab/prompt-input.tsx` | 输入区（模型选择 + prompt + 参数面板） |
| Create | `frontend/app/settings/models/components/detail-panel/playground-tab/output-display.tsx` | 输出区（流式内容 + 性能指标卡片） |
| Create | `frontend/app/settings/models/components/detail-panel/playground-tab/test-history.tsx` | 测试历史列表 |
| Create | `frontend/app/settings/models/components/detail-panel/playground-tab/playground-tab.tsx` | Playground Tab 容器 |
| Modify | `frontend/hooks/queries/models.ts` | 新增 useTestModelStream hook |
| Modify | `frontend/types/models.ts` | 新增 ModelTestMetrics 等类型 |

### 测试

| 文件 | 覆盖 |
|------|------|
| `backend/tests/test_models_sse.py` | SSE 流式响应、metrics 事件、错误处理 |
| `frontend/app/settings/models/__tests__/playground-tab.test.tsx` | 模型选择、发送、流式渲染、性能指标 |

---

## Task 1: 后端 — test_output 改为异步生成器

**Files:**
- Modify: `backend/app/services/model_service.py`

- [ ] **Step 1: 新增 test_output_stream 方法**

在 `ModelService` 中新增异步生成器方法，保留原 `test_output` 不动（向后兼容）：

```python
import time
import json
from typing import AsyncGenerator

async def test_output_stream(
    self,
    user_id: str,
    model_name: str,
    input_text: str,
    model_parameters: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
    """
    流式测试模型输出，yield SSE 格式事件。
    事件类型：token, metrics, error, done
    """
    instance = await self.repo.get_by_name(model_name)
    if not instance:
        yield f"event: error\ndata: {json.dumps({'error': f'模型实例不存在: {model_name}'})}\n\n"
        return

    provider_name = instance.resolved_provider_name
    implementation_name = instance.resolved_implementation_name
    model_type = ModelType.CHAT

    credentials = await self.credential_service.get_current_credentials(
        provider_name=provider_name,
        model_type=model_type,
        model_name=model_name,
        user_id=user_id,
    )

    if not credentials:
        yield f"event: error\ndata: {json.dumps({'error': f'未找到有效凭据: {provider_name}/{model_name}'})}\n\n"
        return

    # 合并参数：实例参数 < 临时覆盖参数
    effective_params = {**(instance.model_parameters or {})}
    if model_parameters:
        effective_params.update(model_parameters)

    model = create_model_instance(
        implementation_name,
        model_name,
        model_type,
        credentials,
        effective_params,
    )

    start_time = time.monotonic()
    first_token_time = None
    output_tokens = 0
    full_output = ""

    try:
        async for chunk in model.astream(input_text):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if isinstance(token, list):
                token = "".join(str(t) for t in token)
            if not token:
                continue

            if first_token_time is None:
                first_token_time = time.monotonic()

            output_tokens += 1
            full_output += token
            yield f"event: token\ndata: {json.dumps({'token': token})}\n\n"

        total_time = time.monotonic() - start_time
        ttft = (first_token_time - start_time) if first_token_time else total_time

        # 估算 input tokens（简单按字符数 / 4 估算，精确值需要 tokenizer）
        input_tokens_est = max(1, len(input_text) // 4)

        metrics = {
            "ttft_ms": round(ttft * 1000, 1),
            "total_time_ms": round(total_time * 1000, 1),
            "input_tokens": input_tokens_est,
            "output_tokens": output_tokens,
            "tokens_per_second": round(output_tokens / total_time, 1) if total_time > 0 else 0,
        }
        yield f"event: metrics\ndata: {json.dumps(metrics)}\n\n"
        yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"

    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/model_service.py
git commit -m "feat: add test_output_stream async generator for SSE"
```

---

## Task 2: 后端 — SSE 端点

**Files:**
- Modify: `backend/app/api/v1/models.py`
- Test: `backend/tests/test_models_sse.py`

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_models_sse.py`：

```python
import pytest
from httpx import AsyncClient


class TestModelTestOutputSSE:
    """测试 SSE 流式 test-output 端点"""

    @pytest.mark.asyncio
    async def test_sse_content_type(self, client: AsyncClient, auth_headers):
        """响应 Content-Type 应为 text/event-stream"""
        response = await client.post(
            "/api/v1/models/test-output-stream",
            json={"model_name": "test-model", "input": "hello"},
            headers=auth_headers,
        )
        assert response.headers.get("content-type", "").startswith("text/event-stream")

    @pytest.mark.asyncio
    async def test_sse_with_model_parameters(self, client: AsyncClient, auth_headers):
        """请求体应接受可选的 model_parameters"""
        response = await client.post(
            "/api/v1/models/test-output-stream",
            json={
                "model_name": "test-model",
                "input": "hello",
                "model_parameters": {"temperature": 0.5},
            },
            headers=auth_headers,
        )
        # 即使模型不存在，也应返回 SSE 格式的 error 事件
        assert response.status_code == 200
```

- [ ] **Step 2: 新增 SSE 端点**

在 `backend/app/api/v1/models.py` 中新增：

```python
from fastapi.responses import StreamingResponse

class ModelTestStreamRequest(BaseModel):
    """流式测试模型输出请求"""
    model_name: str = Field(description="模型名称")
    input: str = Field(description="输入文本")
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="临时参数覆盖（不持久化）")


@router.post("/test-output-stream")
async def test_output_stream(
    payload: ModelTestStreamRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式测试模型输出（SSE）"""
    service = ModelService(db)

    async def event_generator():
        async for event in service.test_output_stream(
            user_id=current_user.id,
            model_name=payload.model_name,
            input_text=payload.input,
            model_parameters=payload.model_parameters,
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

保留原 `POST /test-output` 端点不动（向后兼容）。

- [ ] **Step 3: 运行测试**

Run: `cd backend && python -m pytest tests/test_models_sse.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/models.py backend/tests/test_models_sse.py
git commit -m "feat: add SSE test-output-stream endpoint"
```

---

## Task 3: 前端类型扩展

**Files:**
- Modify: `frontend/types/models.ts`

- [ ] **Step 1: 新增 Playground 相关类型**

```typescript
// ==================== Playground ====================

export interface ModelTestStreamRequest {
  model_name: string
  input: string
  model_parameters?: Record<string, unknown>
}

export interface ModelTestMetrics {
  ttft_ms: number
  total_time_ms: number
  input_tokens: number
  output_tokens: number
  tokens_per_second: number
}

export interface TestHistoryItem {
  id: string
  model_name: string
  input: string
  output: string
  metrics?: ModelTestMetrics
  timestamp: number
  status: 'success' | 'error'
  error?: string
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/types/models.ts
git commit -m "feat: add playground types for SSE streaming and metrics"
```

---

## Task 4: 前端 useTestModelStream hook

**Files:**
- Modify: `frontend/hooks/queries/models.ts`

- [ ] **Step 1: 新增 SSE 消费 hook**

在 `frontend/hooks/queries/models.ts` 中新增：

```typescript
import { useCallback, useRef, useState } from 'react'
import type { ModelTestMetrics, ModelTestStreamRequest } from '@/types/models'

interface StreamState {
  isStreaming: boolean
  output: string
  metrics: ModelTestMetrics | null
  error: string | null
  ttftShown: boolean
  ttftMs: number | null
}

export function useTestModelStream() {
  const [state, setState] = useState<StreamState>({
    isStreaming: false,
    output: '',
    metrics: null,
    error: null,
    ttftShown: false,
    ttftMs: null,
  })
  const abortRef = useRef<AbortController | null>(null)

  const startStream = useCallback(async (request: ModelTestStreamRequest) => {
    // 中断上一次流
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState({
      isStreaming: true,
      output: '',
      metrics: null,
      error: null,
      ttftShown: false,
      ttftMs: null,
    })

    try {
      const token = localStorage.getItem('token') || ''
      const response = await fetch('/api/v1/models/test-output-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(request),
        signal: controller.signal,
      })

      if (!response.ok || !response.body) {
        setState((s) => ({ ...s, isStreaming: false, error: `HTTP ${response.status}` }))
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let eventType = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7)
          } else if (line.startsWith('data: ') && eventType) {
            const data = JSON.parse(line.slice(6))
            if (eventType === 'token') {
              setState((s) => ({
                ...s,
                output: s.output + data.token,
                ttftShown: true,
                ttftMs: s.ttftMs,
              }))
            } else if (eventType === 'metrics') {
              setState((s) => ({
                ...s,
                metrics: data as ModelTestMetrics,
                ttftMs: data.ttft_ms,
              }))
            } else if (eventType === 'error') {
              setState((s) => ({ ...s, error: data.error }))
            }
            eventType = ''
          }
        }
      }

      setState((s) => ({ ...s, isStreaming: false }))
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setState((s) => ({
          ...s,
          isStreaming: false,
          error: (err as Error).message,
        }))
      }
    }
  }, [])

  const stopStream = useCallback(() => {
    abortRef.current?.abort()
    setState((s) => ({ ...s, isStreaming: false }))
  }, [])

  return { ...state, startStream, stopStream }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/hooks/queries/models.ts
git commit -m "feat: add useTestModelStream hook for SSE consumption"
```

---

## Task 5: 前端 Playground 组件 — prompt-input

**Files:**
- Create: `frontend/app/settings/models/components/detail-panel/playground-tab/prompt-input.tsx`

- [ ] **Step 1: 创建 prompt-input.tsx**

Props:
- `selectedProvider: string` — 当前 Provider
- `modelName: string` — 选中的模型
- `onModelChange: (name: string) => void`
- `parameters: Record<string, unknown>` — 当前参数
- `onParametersChange: (params: Record<string, unknown>) => void`
- `onSend: (input: string) => void`
- `onClear: () => void`
- `isStreaming: boolean`
- `configSchema: Record<string, any> | null`

包含：
- 模型选择器（下拉，使用 `useAvailableModels`，预选当前 Provider 下的模型）
- 参数调节折叠面板（根据 configSchema 动态渲染 slider/input）
- 多行 Prompt 输入框（Shift+Enter 换行，Enter 发送）
- 发送按钮（streaming 时变为停止按钮）+ 清空按钮

- [ ] **Step 2: Commit**

```bash
git add frontend/app/settings/models/components/detail-panel/playground-tab/prompt-input.tsx
git commit -m "feat: create playground prompt-input component"
```

---

## Task 6: 前端 Playground 组件 — output-display

**Files:**
- Create: `frontend/app/settings/models/components/detail-panel/playground-tab/output-display.tsx`

- [ ] **Step 1: 创建 output-display.tsx**

Props:
- `output: string`
- `metrics: ModelTestMetrics | null`
- `error: string | null`
- `isStreaming: boolean`

包含：
- 模型响应内容区（流式逐字显示，streaming 时底部有闪烁光标）
- 错误提示卡片（红色背景 + 重试按钮）
- 性能指标卡片组（横向排列 5 个指标卡片：TTFT、总时间、输入 tokens、输出 tokens、速度）
- 指标卡片在 metrics 为 null 时显示 skeleton loading

- [ ] **Step 2: Commit**

```bash
git add frontend/app/settings/models/components/detail-panel/playground-tab/output-display.tsx
git commit -m "feat: create playground output-display with metrics cards"
```

---

## Task 7: 前端 Playground 组件 — test-history + playground-tab

**Files:**
- Create: `frontend/app/settings/models/components/detail-panel/playground-tab/test-history.tsx`
- Create: `frontend/app/settings/models/components/detail-panel/playground-tab/playground-tab.tsx`

- [ ] **Step 1: 创建 test-history.tsx**

Props:
- `history: TestHistoryItem[]`
- `onSelect: (item: TestHistoryItem) => void`

简单的历史记录列表，每项显示：模型名、输入摘要（截断）、状态标签、时间戳。点击可回看。

- [ ] **Step 2: 创建 playground-tab.tsx**

Playground Tab 容器，管理所有状态：
- 使用 `useTestModelStream` hook
- 本地 state：selectedModel、parameters、history（TestHistoryItem[]）
- 上方渲染 `PromptInput`，下方渲染 `OutputDisplay`
- 底部可折叠的 `TestHistory`
- 发送时调用 `startStream`，完成后将结果追加到 history

- [ ] **Step 3: Commit**

```bash
git add frontend/app/settings/models/components/detail-panel/playground-tab/
git commit -m "feat: create playground-tab with test history"
```

---

## Task 8: 集成 Playground Tab 到 detail-panel

**Files:**
- Modify: `frontend/app/settings/models/components/detail-panel/detail-panel.tsx`

- [ ] **Step 1: 替换 Playground Tab 占位**

将 detail-panel.tsx 中 Playground Tab 的 "Coming Soon" 占位替换为 `<PlaygroundTab selectedProvider={selectedProvider} />`。

- [ ] **Step 2: Commit**

```bash
git add frontend/app/settings/models/components/detail-panel/detail-panel.tsx
git commit -m "feat: integrate playground tab into detail panel"
```

---

## Task 9: 前端测试

**Files:**
- Create: `frontend/app/settings/models/__tests__/playground-tab.test.tsx`

- [ ] **Step 1: 写测试**

测试：
- 模型选择器渲染可用模型列表
- 发送按钮触发 startStream
- 流式输出逐步渲染到 output-display
- 性能指标卡片在 metrics 到达后显示
- 错误状态显示错误卡片
- 停止按钮中断流

Mock `fetch` + `ReadableStream` 模拟 SSE 事件序列。

- [ ] **Step 2: 运行测试**

Run: `cd frontend && npx vitest run app/settings/models/__tests__/playground-tab.test.tsx --reporter=verbose`

- [ ] **Step 3: Commit**

```bash
git add frontend/app/settings/models/__tests__/playground-tab.test.tsx
git commit -m "test: add playground tab tests with SSE mock"
```

---

## Task 10: 集成验证

- [ ] **Step 1: 运行后端测试**

Run: `cd backend && python -m pytest tests/ -v --tb=short`

- [ ] **Step 2: 运行前端构建**

Run: `cd frontend && npx next build`

- [ ] **Step 3: 修复问题（如有）并 Commit**
