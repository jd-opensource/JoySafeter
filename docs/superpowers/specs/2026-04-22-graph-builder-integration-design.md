# Graph Builder 集成架构设计

Date: 2026-04-22
Status: Design

## 问题

Graph Builder（84 个文件）从 `/workspace/[wid]/[aid]/` 复制到了 `/components/editors/graph-builder/`，但内部仍然依赖已删除的旧模型。创建 stub 文件只能让编译通过，功能是断的。

需要 3 个适配层让 Graph Builder 真正接入新领域模型。

## 适配层设计

### 适配层 1：数据层 — Graph ←→ AgentVersion

Graph Builder 内部用 `builderStore`（Zustand）管理画布状态：nodes、edges、variables。

旧流程：
```
builderStore.loadGraph() → GraphService.getGraph(graphId) → graphs 表
builderStore.saveGraph() → GraphService.updateGraph(graphId, {nodes, edges}) → graphs 表
```

新流程：
```
builderStore.loadGraph() → agentVersionService.getVersion(versionId) → version.definition_payload
builderStore.saveGraph() → agentVersionService.updateVersion(versionId, {definition_payload}) → agent_versions 表
```

实现方式：在 graph-builder 内部创建 `services/graphDataAdapter.ts`：
```typescript
// 适配器：将 AgentVersion API 包装成 Graph Builder 期望的接口
export const graphDataAdapter = {
  async loadGraph(agentId: string, versionId: string, workspaceId: string) {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    return {
      nodes: version.definition_payload.nodes || [],
      edges: version.definition_payload.edges || [],
      variables: version.definition_payload.variables || {},
    }
  },
  async saveGraph(agentId: string, versionId: string, workspaceId: string, data: GraphData) {
    await agentVersionService.update(agentId, versionId, workspaceId, {
      definition_payload: {
        nodes: data.nodes,
        edges: data.edges,
        variables: data.variables,
      }
    })
  }
}
```

### 适配层 2：发布层 — Deployment ←→ AgentRelease

Graph Builder 有 DeploymentPanel 和 DeploymentVersionsList 组件。

旧流程：
```
DeploymentPanel → graphDeploymentService.deploy(graphId) → graph_deployment_version 表
DeploymentVersionsList → graphDeploymentService.list(graphId) → 版本列表
```

新流程：
```
DeploymentPanel → 先 freeze version → 再 publish release
  agentVersionService.freeze(agentId, versionId)
  agentReleaseService.publish(agentId, {agent_version_id, runtime_kind: "graph"})

DeploymentVersionsList → agentReleaseService.list(agentId) → release 列表
```

实现方式：在 graph-builder 内部创建 `services/deploymentAdapter.ts`：
```typescript
export const deploymentAdapter = {
  async deploy(agentId: string, versionId: string, workspaceId: string) {
    // 1. Freeze the version
    await agentVersionService.freeze(agentId, versionId, workspaceId)
    // 2. Publish as release
    return await agentReleaseService.publish(agentId, workspaceId, {
      agent_version_id: versionId,
      runtime_kind: 'graph',
    })
  },
  async listVersions(agentId: string, workspaceId: string) {
    return await agentReleaseService.list(agentId, workspaceId)
  },
  async activate(agentId: string, releaseId: string, workspaceId: string) {
    return await agentReleaseService.activate(agentId, releaseId, workspaceId)
  }
}
```

### 适配层 3：执行层 — Run ←→ ExecutionOrchestrator

Graph Builder 有 RunInputModal 和 execution 面板。

旧流程：
```
RunInputModal → WebSocket /ws/chat → chat_ws_handler → LangGraph 执行 → 事件流
```

新流程：
```
RunInputModal → POST /v1/runs {release_id, prompt, trigger_source: "chat"}
  → ExecutionOrchestrator.dispatch_direct()
  → GraphEngine.start()
  → 事件通过 /ws/executions/{execution_id} 推送
```

实现方式：在 graph-builder 内部创建 `services/executionAdapter.ts`：
```typescript
export const executionAdapter = {
  async run(agentId: string, workspaceId: string, prompt: string) {
    // Get active release
    const agent = await agentService.get(agentId, workspaceId)
    if (!agent.active_release_id) throw new Error('No active release')
    
    // Create run via API
    const run = await agentRunService.create({
      release_id: agent.active_release_id,
      trigger_source: 'chat',
      goal: prompt,
    })
    return run
  },
  
  subscribeToEvents(executionId: string, onEvent: (event: ExecutionEvent) => void) {
    // Connect to /ws/executions/{executionId}
    const ws = new WebSocket(`${WS_BASE}/ws/executions/${executionId}`)
    ws.onmessage = (e) => onEvent(JSON.parse(e.data))
    return () => ws.close()
  }
}
```

### 共享 UI 组件提取

从已删除的 `app/chat/` 中需要的组件，应该作为独立共享组件重建（不是 stub）：

```
components/shared/
├── artifact-panel.tsx      — 显示执行产出物（文件、报告等）
├── code-viewer.tsx         — 代码高亮显示
├── tool-call-display.tsx   — 工具调用展示
└── copy-button.tsx         — 复制到剪贴板按钮

types/
├── chat.ts                 — Message, ToolCall 等共享类型
```

这些不是 stub，是真正的 UI 组件，从旧 chat 代码中提取核心逻辑。

## 实施顺序

### Step 1: 创建 3 个适配器 + 共享 UI 组件
- `components/editors/graph-builder/services/graphDataAdapter.ts`
- `components/editors/graph-builder/services/deploymentAdapter.ts`
- `components/editors/graph-builder/services/executionAdapter.ts`
- `components/shared/artifact-panel.tsx`
- `components/shared/code-viewer.tsx`
- `components/shared/tool-call-display.tsx`
- `hooks/useCopyToClipboard.ts`
- `types/chat.ts`

### Step 2: 重写 Graph Builder 内部引用
- `builderStore` 的 load/save 改用 graphDataAdapter
- `DeploymentVersionsList` 改用 deploymentAdapter
- `DeploymentPreview` 改用 deploymentAdapter
- `RunInputModal` 改用 executionAdapter
- 所有 `@/app/chat/` 引用改为 `@/components/shared/`
- 所有 `@/stores/deploymentStore` 引用改为 deploymentAdapter
- 所有 `@/app/workspace/[wid]/[aid]/` 引用改为相对路径

### Step 3: 修复剩余 import 路径
- workspace 页面的旧引用
- skills creator 的旧引用
- copilot 的旧引用

### Step 4: 验证 build 通过
