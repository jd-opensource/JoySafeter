# Graph Builder 全面重构设计

> 日期: 2026-04-26
> 状态: 待审核
> 修订: v2 — 修复 spec review 反馈
> 原则: 从目标架构出发，用户交互友好，能力自洽

## 问题

### 布局问题
1. 右侧面板 `absolute` 定位遮挡画布 320px，画布没有让出空间
2. 工具栏被塞在 320px 右面板顶部，按钮挤在一起
3. 状态栏信息分散（保存状态、缩放控件在不同位置）

### 功能杂糅
4. `studioMode` 分叉导致两套 UI 并存（StudioRightPanel vs BuilderSidebarTabs）
5. 右面板把 Copilot 聊天和节点属性编辑挤在一起
6. 工具栏的测试/发布按钮跟 AgentBuildShell stepper 功能重复
7. RunInputModal + ExecutionPanel 在 studioMode 下是死代码

### 代码质量
8. AgentBuilder.tsx 657 行，职责过多
9. builderStore.ts 760 行，未按职责拆分
10. executionStore.ts 838 行（本次不拆，跟构建页面解耦后不影响）
11. BuilderToolbar.tsx 374 行，包含过多逻辑

## 目标布局

```
┌──────────────────────────────────────────────────────────────┐
│  [+ 添加节点]  [导入] [导出]              [▶ 测试] [🚀 发布] │  ← GraphToolbar（全宽）
├──────────────────────────────────────────────────────────────┤
│                                          ┌──────────────┐   │
│                                          │ NodeInspector │   │
│              React Flow 画布              │ （选中节点时） │   │
│              （flex-1 自动收缩）           │              │   │
│                                          └──────────────┘   │
│                                                              │
│         ┌──────────────────────────────────┐                 │
│         │ 💬 Ask Copilot...                │                 │  ← CopilotOverlay（浮动）
│         └──────────────────────────────────┘                 │
├──────────────────────────────────────────────────────────────┤
│  ● 自动保存 09:31 · 未发布               [fit] [−] 100% [+] │  ← GraphStatusBar
└──────────────────────────────────────────────────────────────┘
```

## 架构

### 组件拆分

AgentBuilder 拆成布局容器 + 独立子组件：

```
GraphBuilderShell              ← 新文件，纯布局容器
├── GraphToolbar               ← 重写，从右面板移到顶部全宽
├── <div className="flex">     ← 主体区域
│   ├── BuilderCanvas          ← 已有，flex-1
│   └── NodeInspector          ← 新文件，选中节点时 shrink-0 滑出
├── CopilotOverlay             ← 新文件，底部浮动 AI 助手
└── GraphStatusBar             ← 新文件，统一底部状态栏
```

### GraphBuilderShell

```typescript
// 纯布局，不管业务逻辑
interface GraphBuilderShellProps {
  agentId: string
  versionId?: string
  workspaceId: string
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
}

function GraphBuilderShell(props: GraphBuilderShellProps) {
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId)
  const [copilotExpanded, setCopilotExpanded] = useState(false)

  return (
    <div className="flex h-full flex-col">
      <GraphToolbar
        onOpenTestLab={props.onOpenTestLab}
        onOpenRelease={props.onOpenRelease}
      />
      <div className="relative min-h-0 flex-1 flex">
        <div className="min-w-0 flex-1">
          <BuilderCanvas />
        </div>
        {selectedNodeId && (
          <aside className="w-[360px] shrink-0 border-l overflow-y-auto animate-in slide-in-from-right">
            <NodeInspector
              nodeId={selectedNodeId}
              onClose={() => useGraphStore.getState().selectNode(null)}
            />
          </aside>
        )}
        <CopilotOverlay
          agentId={props.agentId}
          expanded={copilotExpanded}
          onToggle={() => setCopilotExpanded((v) => !v)}
        />
      </div>
      <GraphStatusBar />
    </div>
  )
}
```

### GraphToolbar

从右面板 header 移到顶部全宽。删除 studioMode 分叉。

```typescript
interface GraphToolbarProps {
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
}

function GraphToolbar({ onOpenTestLab, onOpenRelease }: GraphToolbarProps) {
  return (
    <div className="flex items-center justify-between border-b px-3 py-1.5">
      {/* 左：编辑操作 */}
      <div className="flex items-center gap-1">
        <AddNodeButton />
        <ImportExportMenu />
      </div>
      {/* 右：生命周期快捷入口 */}
      <div className="flex items-center gap-1.5">
        {onOpenTestLab && (
          <Button variant="outline" size="sm" onClick={onOpenTestLab}>
            <Beaker className="mr-1.5 h-3.5 w-3.5" /> Test
          </Button>
        )}
        {onOpenRelease && (
          <Button size="sm" onClick={onOpenRelease}>
            <Rocket className="mr-1.5 h-3.5 w-3.5" /> Release
          </Button>
        )}
      </div>
    </div>
  )
}
```

删除的功能：
- Deploy 按钮 → 发布走 stepper 的 Release 阶段
- Run/Stop 按钮 → 测试走 stepper 的 Test Lab 阶段
- ExecutionPanel toggle → 执行面板在 TestLabStage 里
- studioMode 条件分支

### InspectorPanel（原 NodeInspector）

选中节点或边时右侧滑出，360px 宽，flex shrink-0（画布自动收缩让出空间）。

```typescript
interface InspectorPanelProps {
  onClose: () => void
}

function InspectorPanel({ onClose }: InspectorPanelProps) {
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId)
  const selectedEdgeId = useGraphStore((s) => s.selectedEdgeId)

  // 节点优先于边
  if (selectedNodeId) {
    return (
      <InspectorShell title={nodeLabel} onClose={onClose}>
        <NodePropertyForm nodeId={selectedNodeId} />
      </InspectorShell>
    )
  }

  if (selectedEdgeId) {
    return (
      <InspectorShell title="Edge" onClose={onClose}>
        <EdgePropertyForm edgeId={selectedEdgeId} />
      </InspectorShell>
    )
  }

  return null
}

// InspectorShell — 通用外壳：header + scrollable body
function InspectorShell({ title, onClose, children }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <span className="text-sm font-medium">{title}</span>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {children}
      </div>
    </div>
  )
}
```

> NodePropertyForm 复用现有 PropertiesPanel 的表单逻辑。EdgePropertyForm 复用现有 EdgePropertiesPanel 的逻辑。只换外壳。

GraphBuilderShell 中的条件改为：

```typescript
{(selectedNodeId || selectedEdgeId) && (
  <aside className="w-[360px] shrink-0 border-l animate-in slide-in-from-right">
    <InspectorPanel onClose={() => useGraphStore.getState().clearSelection()} />
  </aside>
)}
```

### CopilotOverlay

底部浮动层，两种状态：

**收起（默认）：** 居中浮动输入框，贴近底部状态栏上方

```typescript
// 收起状态
<div className="absolute bottom-2 left-1/2 z-30 w-full max-w-xl -translate-x-1/2">
  <button className="flex w-full items-center gap-2 rounded-xl border bg-[var(--surface-2)] px-4 py-2.5 text-sm shadow-lg backdrop-blur"
    onClick={onToggle}>
    <Sparkles className="h-4 w-4" />
    Ask Copilot to build or modify your graph...
  </button>
</div>
```

**展开：** 聊天面板，高度 40vh，带消息历史和输入框

```typescript
// 展开状态
<div className="absolute bottom-2 left-1/2 z-30 flex h-[40vh] w-full max-w-2xl -translate-x-1/2 flex-col rounded-xl border bg-[var(--surface-1)] shadow-2xl">
  <header> Copilot + 收起按钮 </header>
  <div className="flex-1 overflow-y-auto"> 消息列表 </div>
  <footer> 输入框 + 发送按钮 </footer>
</div>
```

> Copilot 的聊天逻辑从 StudioRightPanel 迁移过来，只换 UI 外壳。

### CopilotOverlay 聊天逻辑迁移

当前 StudioRightPanel 内部使用 `useCopilotChat()` hook 管理消息历史和发送。迁移方式：

- `useCopilotChat()` hook 保持不变，CopilotOverlay 直接调用
- 消息列表渲染逻辑从 StudioRightPanel 复制到 CopilotOverlay 的展开状态
- Copilot 的 "apply to graph" 操作（添加节点、修改边）通过 `useGraphStore` 执行，跟当前一致
- 不需要改后端 API

### GraphStatusBar

统一底部状态栏：

```typescript
function GraphStatusBar() {
  const { saveStatus, lastSavedAt } = useSaveStore()

  return (
    <div className="flex items-center justify-between border-t px-3 py-1 text-[10px] text-[var(--text-muted)]">
      <div className="flex items-center gap-2">
        <SaveStatusIndicator status={saveStatus} lastSavedAt={lastSavedAt} />
        <span>·</span>
        <PublishStatusIndicator />
      </div>
      <ZoomControls />
    </div>
  )
}
```

## studioMode 清理

所有 Agent 现在走 AgentBuildShell → VisualBuilderSurface，`studioMode` 永远 `true`。

| 删除 | 理由 |
|---|---|
| `studioMode` prop | 永远 true |
| `BuilderSidebarTabs` 组件 | 非 studio 路径的右面板 |
| `RunInputModal` | 非 studio 路径的测试入口 |
| `ExecutionPanel` 在 AgentBuilder 内的渲染 | 执行面板在 TestLabStage |
| `onRunClick` / `showExecutionPanel` 状态 | 不再需要 |

## builderStore 拆分

当前 `builderStore.ts`（760 行）拆成 3 个 store：

| Store | 文件 | 职责 | 预估行数 |
|---|---|---|---|
| `useGraphStore` | `stores/graphStore.ts` | 节点、边、视口、选中节点/边、React Flow 操作、agentId/versionId/workspaceId | ~350 |
| `useSaveStore` | `stores/saveStore.ts` | 自动保存状态、保存时间、脏标记、SaveManager | ~200 |
| `useBuilderUIStore` | `stores/builderUIStore.ts` | UI 状态（copilot 展开、面板可见性） | ~80 |

`executionStore.ts`（838 行）本次不拆 — 它只在 TestLabStage 使用，跟 GraphBuilder 解耦后不影响构建页面。

### SaveManager 跨 store 依赖

SaveManager 需要读取 `graphStore` 的 nodes/edges/viewport 和 identity 字段来执行保存。解决方式：SaveManager 在 `saveStore` 中创建，通过回调注入读取 `graphStore` 的能力。

```typescript
// stores/saveStore.ts
import { useGraphStore } from './graphStore'

export const useSaveStore = create<SaveState>((set, get) => {
  const manager = new SaveManager({
    getGraphSnapshot: () => {
      const gs = useGraphStore.getState()
      return { agentId: gs.agentId, versionId: gs.versionId, workspaceId: gs.workspaceId,
               graphId: gs.graphId, graphName: gs.graphName,
               nodes: gs.nodes, edges: gs.edges, viewport: gs.viewport }
    },
    onSaveSuccess: (hash) => set({ lastSavedStateHash: hash, lastAutoSaveTime: Date.now() }),
    onSaveError: (err) => set((s) => ({ saveRetryCount: s.saveRetryCount + 1, lastSaveError: err })),
  })
  return { manager, startAutoSave: () => manager.start(), stopAutoSave: () => manager.stop() }
})
```

### 迁移策略

为避免一次性修改 20+ 文件，分两步：

1. 创建新 store 文件。在 `builderStore.ts` 保留兼容层：`export const useBuilderStore = useGraphStore`
2. 逐文件替换 `useBuilderStore` 为对应新 store，完成后删除兼容层

## 文件结构

### 新建
- `graph-builder/GraphBuilderShell.tsx` — 布局容器
- `graph-builder/components/GraphToolbar.tsx` — 重写工具栏
- `graph-builder/components/InspectorPanel.tsx` — 节点/边属性面板（通用）
- `graph-builder/components/CopilotOverlay.tsx` — 浮动 Copilot
- `graph-builder/components/GraphStatusBar.tsx` — 底部状态栏
- `graph-builder/components/AddNodeButton.tsx` — 从 BuilderToolbar 抽出
- `graph-builder/components/ImportExportMenu.tsx` — 从 BuilderToolbar 抽出
- `graph-builder/components/ZoomControls.tsx` — 缩放控件
- `graph-builder/stores/graphStore.ts` — 图状态
- `graph-builder/stores/saveStore.ts` — 保存状态
- `graph-builder/stores/builderUIStore.ts` — UI 状态

### 重写
- `graph-builder/AgentBuilder.tsx` — 精简为 ReactFlowProvider + 初始化逻辑 + GraphBuilderShell
- `surfaces/visual/visual-builder-surface.tsx` — 适配新 props

> **ReactFlowProvider 位置：** `AgentBuilder.tsx` 保留为入口组件，负责 `ReactFlowProvider` 包裹和初始化逻辑（版本解冻、graphState 加载、agentId/versionId 同步）。`GraphBuilderShell` 在 Provider 内部，可以使用 `useReactFlow()` hook。这跟当前的 AgentBuilder（外壳）→ AgentBuilderContent（内容）模式一致，只是 Content 改名为 GraphBuilderShell 并只做布局。

```typescript
// AgentBuilder.tsx — 精简后 ~80 行
export default function AgentBuilder(props: GraphBuilderShellProps) {
  return (
    <ReactFlowProvider>
      <GraphBuilderInit {...props} />
    </ReactFlowProvider>
  )
}

// GraphBuilderInit — 初始化逻辑（版本解冻、数据加载、store 同步）
function GraphBuilderInit(props: GraphBuilderShellProps) {
  // useEffect: sync agentId/versionId/workspaceId to graphStore
  // useEffect: auto-unfreeze frozen versions
  // useEffect: auto-save lifecycle (start/stop)
  // useEffect: cleanup on unmount

  if (isInitializing) return <LoadingOverlay />

  return <GraphBuilderShell {...props} />
}
```

### 删除
- `graph-builder/components/BuilderToolbar.tsx` — 被 GraphToolbar 取代
- `graph-builder/BuilderSidebarTabs.tsx` — studioMode=false 路径
- `graph-builder/studio/StudioRightPanel.tsx` — Copilot 迁移到 CopilotOverlay
- `graph-builder/stores/builderStore.ts` — 拆成 3 个 store

## 重构范围

本次实现：
- 布局重写（GraphBuilderShell + 全宽工具栏 + flex 右面板）
- studioMode 清理
- builderStore 拆分
- NodeInspector 独立
- CopilotOverlay 浮动化
- GraphStatusBar 统一
- GraphToolbar 精简

不在范围：
- executionStore 拆分
- 节点类型系统重构
- BuilderCanvas 内部重构
- 后端 API 变更
