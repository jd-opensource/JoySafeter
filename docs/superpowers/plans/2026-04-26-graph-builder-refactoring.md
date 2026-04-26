# Graph Builder 全面重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全面重构 Graph Builder 页面 — 布局重写（工具栏顶部全宽、flex 右面板、浮动 Copilot、统一状态栏）、studioMode 清理、builderStore 拆分、组件分解。

**Spec:** `docs/superpowers/specs/2026-04-26-graph-builder-refactoring-design.md`

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS, Zustand, React Query, React Flow, Vitest + Testing Library

---

## 文件结构总览

### 新建文件
- `graph-builder/GraphBuilderShell.tsx` — 纯布局容器（~80 行）
- `graph-builder/components/GraphToolbar.tsx` — 全宽工具栏（~120 行）
- `graph-builder/components/InspectorPanel.tsx` — 节点/边属性面板（~80 行）
- `graph-builder/components/CopilotOverlay.tsx` — 底部浮动 Copilot（~150 行）
- `graph-builder/components/GraphStatusBar.tsx` — 统一底部状态栏（~60 行）
- `graph-builder/components/AddNodeButton.tsx` — 从 BuilderToolbar 抽出（~100 行）
- `graph-builder/components/ImportExportMenu.tsx` — 从 BuilderToolbar 抽出（~60 行）
- `graph-builder/components/ZoomControls.tsx` — 缩放控件（~40 行）
- `graph-builder/stores/graphStore.ts` — 图状态 store（~350 行）
- `graph-builder/stores/saveStore.ts` — 保存状态 store（~200 行）
- `graph-builder/stores/builderUIStore.ts` — UI 状态 store（~80 行）

### 重写文件
- `graph-builder/AgentBuilder.tsx` — 精简为 ReactFlowProvider + 初始化 + GraphBuilderShell（~120 行）
- `surfaces/visual/visual-builder-surface.tsx` — 删除 studioMode prop

### 删除文件
- `graph-builder/components/BuilderToolbar.tsx` — 被 GraphToolbar + AddNodeButton + ImportExportMenu 取代
- `graph-builder/components/BuilderSidebarTabs.tsx` — studioMode=false 路径
- `graph-builder/components/StudioRightPanel.tsx` — Copilot 迁移到 CopilotOverlay，属性迁移到 InspectorPanel
- `graph-builder/stores/builderStore.ts` — 拆成 3 个 store（最后删除兼容层）

### 重写文件（已有）
- `graph-builder/components/GraphStatusBar.tsx` — 已有 149 行，重写为使用 saveStore + 统一布局

---

## Task 1: graphStore — 从 builderStore 拆出图状态

**Files:**
- Create: `frontend/components/editors/graph-builder/stores/graphStore.ts`
- Test: `frontend/components/editors/graph-builder/stores/__tests__/graphStore.test.ts`

**目标：** 将 builderStore 中的图相关状态（nodes, edges, viewport, selectedNodeId, selectedEdgeId, identity fields, ReactFlow handlers, undo/redo）拆到独立 store。

**依赖：** 无

- [ ] **Step 1: 读取当前 builderStore.ts**

读取 `frontend/components/editors/graph-builder/stores/builderStore.ts`，理解完整的 state shape 和所有 action methods。

- [ ] **Step 2: 写测试**

```typescript
// frontend/components/editors/graph-builder/stores/__tests__/graphStore.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useGraphStore } from '../graphStore'

describe('graphStore', () => {
  beforeEach(() => {
    useGraphStore.setState(useGraphStore.getInitialState())
  })

  it('initializes with empty nodes and edges', () => {
    const state = useGraphStore.getState()
    expect(state.nodes).toEqual([])
    expect(state.edges).toEqual([])
  })

  it('tracks selectedNodeId', () => {
    useGraphStore.getState().selectNode('node-1')
    expect(useGraphStore.getState().selectedNodeId).toBe('node-1')
  })

  it('tracks selectedEdgeId', () => {
    useGraphStore.getState().selectEdge('edge-1')
    expect(useGraphStore.getState().selectedEdgeId).toBe('edge-1')
  })

  it('clearSelection clears both node and edge', () => {
    useGraphStore.getState().selectNode('node-1')
    useGraphStore.getState().selectEdge('edge-1')
    useGraphStore.getState().clearSelection()
    expect(useGraphStore.getState().selectedNodeId).toBeNull()
    expect(useGraphStore.getState().selectedEdgeId).toBeNull()
  })

  it('stores identity fields', () => {
    useGraphStore.setState({ agentId: 'a-1', versionId: 'v-1', workspaceId: 'ws-1' })
    const s = useGraphStore.getState()
    expect(s.agentId).toBe('a-1')
    expect(s.versionId).toBe('v-1')
    expect(s.workspaceId).toBe('ws-1')
  })
})
```

- [ ] **Step 3: 实现 graphStore.ts**

从 `builderStore.ts` 复制以下字段和方法到新 store：

**State fields:**
- `nodes`, `edges`, `rfInstance`, `selectedNodeId`, `selectedEdgeId`
- `past`, `future` (undo/redo history)
- `agentId`, `versionId`, `workspaceId`, `graphId`, `graphName`
- `graphStateFields`, `fallbackNodeId`
- `isInitializing`

**Action methods:**
- `onNodesChange`, `onEdgesChange`, `onConnect`
- `addNode`, `updateNodeData`, `removeNode`
- `selectNode`, `selectEdge`, `clearSelection` (new — clears both)
- `undo`, `redo`, `pushHistory`
- `setWorkspaceId`
- `setNodes`, `setEdges` (direct setters)

**不包含：** SaveManager, lastAutoSaveTime, saveRetryCount, lastSaveError, hasPendingChanges, isSaving, deployedAt, isExecuting, activeExecutionNodeId, executionLogs

- [ ] **Step 4: 运行测试**

Run: `cd frontend && npx vitest run components/editors/graph-builder/stores/__tests__/graphStore.test.ts`

- [ ] **Step 5: 在 builderStore.ts 添加兼容层**

在 `builderStore.ts` 底部添加：
```typescript
// 兼容层 — 逐步迁移后删除
export { useGraphStore as useBuilderStore } from './graphStore'
```

暂时不删除 builderStore 的原始代码 — 等所有消费者迁移完再删。

- [ ] **Step 6: 提交**

```bash
git add frontend/components/editors/graph-builder/stores/graphStore.ts \
       frontend/components/editors/graph-builder/stores/__tests__/graphStore.test.ts
git commit -m "feat: create graphStore — split graph state from builderStore"
```

---

## Task 2: saveStore — 从 builderStore 拆出保存状态

**Files:**
- Create: `frontend/components/editors/graph-builder/stores/saveStore.ts`
- Test: `frontend/components/editors/graph-builder/stores/__tests__/saveStore.test.ts`

**目标：** 将保存相关状态（SaveManager, lastAutoSaveTime, saveRetryCount, hasPendingChanges 等）拆到独立 store。SaveManager 通过回调注入读取 graphStore。

**依赖：** Task 1（graphStore）

- [ ] **Step 1: 写测试**

```typescript
// frontend/components/editors/graph-builder/stores/__tests__/saveStore.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useSaveStore } from '../saveStore'

describe('saveStore', () => {
  beforeEach(() => {
    useSaveStore.setState(useSaveStore.getInitialState())
  })

  it('initializes with idle save status', () => {
    const s = useSaveStore.getState()
    expect(s.isSaving).toBe(false)
    expect(s.lastAutoSaveTime).toBeNull()
    expect(s.saveRetryCount).toBe(0)
  })

  it('tracks save errors', () => {
    useSaveStore.setState({ lastSaveError: 'network error', saveRetryCount: 1 })
    expect(useSaveStore.getState().lastSaveError).toBe('network error')
  })
})
```

- [ ] **Step 2: 实现 saveStore.ts**

**State fields (from builderStore):**
- `isSaving`, `lastAutoSaveTime`, `deployedAt`
- `lastSavedStateHash`, `hasPendingChanges`
- `saveRetryCount`, `lastSaveError`

**SaveManager integration:**
```typescript
import { useGraphStore } from './graphStore'

const manager = new SaveManager({
  getGraphSnapshot: () => {
    const gs = useGraphStore.getState()
    return {
      agentId: gs.agentId, versionId: gs.versionId, workspaceId: gs.workspaceId,
      graphId: gs.graphId, graphName: gs.graphName,
      nodes: gs.nodes, edges: gs.edges,
      viewport: gs.rfInstance?.getViewport(),
      graphStateFields: gs.graphStateFields, fallbackNodeId: gs.fallbackNodeId,
    }
  },
  onSaveStart: () => set({ isSaving: true }),
  onSaveSuccess: (hash) => set({
    isSaving: false, lastSavedStateHash: hash,
    lastAutoSaveTime: Date.now(), saveRetryCount: 0, lastSaveError: null,
  }),
  onSaveError: (err) => set((s) => ({
    isSaving: false, saveRetryCount: s.saveRetryCount + 1, lastSaveError: err,
  })),
})
```

**Action methods:**
- `startAutoSave()`, `stopAutoSave()`, `saveNow(reason)`
- `autoSave()` — called by online event handler

- [ ] **Step 3: 运行测试**

Run: `cd frontend && npx vitest run components/editors/graph-builder/stores/__tests__/saveStore.test.ts`

- [ ] **Step 4: 提交**

```bash
git add frontend/components/editors/graph-builder/stores/saveStore.ts \
       frontend/components/editors/graph-builder/stores/__tests__/saveStore.test.ts
git commit -m "feat: create saveStore — split save state from builderStore"
```

---

## Task 3: builderUIStore — UI 状态

**Files:**
- Create: `frontend/components/editors/graph-builder/stores/builderUIStore.ts`

**目标：** 轻量 UI 状态 store，管理 copilot 展开状态等。

**依赖：** 无

- [ ] **Step 1: 实现 builderUIStore.ts**

```typescript
// frontend/components/editors/graph-builder/stores/builderUIStore.ts
import { create } from 'zustand'

interface BuilderUIState {
  copilotExpanded: boolean
  toggleCopilot: () => void
  setCopilotExpanded: (expanded: boolean) => void
}

export const useBuilderUIStore = create<BuilderUIState>((set) => ({
  copilotExpanded: false,
  toggleCopilot: () => set((s) => ({ copilotExpanded: !s.copilotExpanded })),
  setCopilotExpanded: (expanded) => set({ copilotExpanded: expanded }),
}))
```

- [ ] **Step 2: 提交**

```bash
git add frontend/components/editors/graph-builder/stores/builderUIStore.ts
git commit -m "feat: create builderUIStore for UI state"
```

---

## Task 4: GraphToolbar — 全宽工具栏 + 子组件抽取

**Files:**
- Create: `frontend/components/editors/graph-builder/components/GraphToolbar.tsx`
- Create: `frontend/components/editors/graph-builder/components/AddNodeButton.tsx`
- Create: `frontend/components/editors/graph-builder/components/ImportExportMenu.tsx`
- Test: `frontend/components/editors/graph-builder/components/__tests__/GraphToolbar.test.tsx`

**目标：** 从 BuilderToolbar（374 行）抽取核心功能，重写为全宽顶部工具栏。删除 studioMode 分叉、Deploy 按钮、Run/Stop 按钮、ExecutionPanel toggle。

**依赖：** 无（不依赖 store 拆分）

**参考旧文件：** `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx`

- [ ] **Step 1: 写测试**

```tsx
// frontend/components/editors/graph-builder/components/__tests__/GraphToolbar.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (_: string, o?: { defaultValue?: string }) => o?.defaultValue ?? _ }),
}))
vi.mock('@/providers/workspace-permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canEdit: true, canAdmin: true }),
}))

import { GraphToolbar } from '../GraphToolbar'

describe('GraphToolbar', () => {
  it('renders Test and Release buttons', () => {
    const onTest = vi.fn()
    const onRelease = vi.fn()
    render(<GraphToolbar onOpenTestLab={onTest} onOpenRelease={onRelease} />)
    expect(screen.getByRole('button', { name: /test/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /release/i })).toBeInTheDocument()
  })

  it('calls onOpenTestLab when Test clicked', () => {
    const onTest = vi.fn()
    render(<GraphToolbar onOpenTestLab={onTest} onOpenRelease={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /test/i }))
    expect(onTest).toHaveBeenCalled()
  })

  it('does not render Test button when callback not provided', () => {
    render(<GraphToolbar />)
    expect(screen.queryByRole('button', { name: /test/i })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 实现 AddNodeButton.tsx**

从 BuilderToolbar 中抽取 "添加节点" Popover + 节点面板逻辑。读取旧文件中 `handleAddNode` 和节点类型列表，保持功能一致。

```tsx
// frontend/components/editors/graph-builder/components/AddNodeButton.tsx
'use client'
// 从 BuilderToolbar 抽取 Popover + nodeRegistry 节点面板
// Props: onAddNode: (node: { type: string; label: string }) => void
```

- [ ] **Step 3: 实现 ImportExportMenu.tsx**

从 BuilderToolbar 中抽取导入/导出下拉菜单。

```tsx
// frontend/components/editors/graph-builder/components/ImportExportMenu.tsx
'use client'
// 从 BuilderToolbar 抽取 DropdownMenu: Import JSON, Export JSON
// Props: onImport, onExport
```

- [ ] **Step 4: 实现 GraphToolbar.tsx**

```tsx
// frontend/components/editors/graph-builder/components/GraphToolbar.tsx
'use client'

import { Beaker, Rocket } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'
import { useGraphStore } from '../stores/graphStore'
import { AddNodeButton } from './AddNodeButton'
import { ImportExportMenu } from './ImportExportMenu'

interface GraphToolbarProps {
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
}

export function GraphToolbar({ onOpenTestLab, onOpenRelease }: GraphToolbarProps) {
  const { t } = useTranslation()
  const { canEdit } = useUserPermissionsContext()
  const addNode = useGraphStore((s) => s.addNode)

  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-1.5">
      <div className="flex items-center gap-1">
        {canEdit && <AddNodeButton onAddNode={addNode} />}
        <ImportExportMenu />
      </div>
      <div className="flex items-center gap-1.5">
        {onOpenTestLab && (
          <Button variant="outline" size="sm" onClick={onOpenTestLab} className="gap-1.5 text-xs">
            <Beaker className="h-3.5 w-3.5" />
            {t('agents.build.test', { defaultValue: 'Test' })}
          </Button>
        )}
        {onOpenRelease && (
          <Button size="sm" onClick={onOpenRelease} className="gap-1.5 text-xs">
            <Rocket className="h-3.5 w-3.5" />
            {t('agents.build.release', { defaultValue: 'Release' })}
          </Button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: 运行测试**

Run: `cd frontend && npx vitest run components/editors/graph-builder/components/__tests__/GraphToolbar.test.tsx`

- [ ] **Step 6: 提交**

```bash
git add frontend/components/editors/graph-builder/components/GraphToolbar.tsx \
       frontend/components/editors/graph-builder/components/AddNodeButton.tsx \
       frontend/components/editors/graph-builder/components/ImportExportMenu.tsx \
       frontend/components/editors/graph-builder/components/__tests__/GraphToolbar.test.tsx
git commit -m "feat: add GraphToolbar with AddNodeButton and ImportExportMenu"
```

---

## Task 5: InspectorPanel — 节点/边属性面板

**Files:**
- Create: `frontend/components/editors/graph-builder/components/InspectorPanel.tsx`
- Test: `frontend/components/editors/graph-builder/components/__tests__/InspectorPanel.test.tsx`

**目标：** 独立的右侧属性面板，选中节点或边时显示对应的属性编辑表单。复用现有 PropertiesPanel 和 EdgePropertiesPanel 的表单逻辑。

**依赖：** Task 1（graphStore — selectedNodeId, selectedEdgeId）

**参考旧文件：**
- `frontend/components/editors/graph-builder/components/PropertiesPanel.tsx`（408 行）
- `frontend/components/editors/graph-builder/studio/StudioRightPanel.tsx`（切换逻辑）

- [ ] **Step 1: 写测试**

```tsx
// frontend/components/editors/graph-builder/components/__tests__/InspectorPanel.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (_: string, o?: { defaultValue?: string }) => o?.defaultValue ?? _ }),
}))

// Mock graphStore to return a selected node
const mockNode = { id: 'n-1', type: 'llm', data: { label: 'LLM Node' }, position: { x: 0, y: 0 } }
vi.mock('../../stores/graphStore', () => ({
  useGraphStore: (selector: any) => {
    const state = {
      selectedNodeId: 'n-1',
      selectedEdgeId: null,
      nodes: [mockNode],
      edges: [],
    }
    return selector(state)
  },
}))

// Mock PropertiesPanel to avoid deep dependency tree
vi.mock('../PropertiesPanel', () => ({
  PropertiesPanel: () => <div data-testid="properties-panel">Properties</div>,
}))

import { InspectorPanel } from '../InspectorPanel'

describe('InspectorPanel', () => {
  it('renders node properties when node is selected', () => {
    render(<InspectorPanel onClose={vi.fn()} />)
    expect(screen.getByText('LLM Node')).toBeInTheDocument()
    expect(screen.getByTestId('properties-panel')).toBeInTheDocument()
  })

  it('calls onClose when close button clicked', () => {
    const onClose = vi.fn()
    render(<InspectorPanel onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 实现 InspectorPanel.tsx**

```tsx
// frontend/components/editors/graph-builder/components/InspectorPanel.tsx
'use client'

import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { useGraphStore } from '../stores/graphStore'
import { PropertiesPanel } from './PropertiesPanel'

interface InspectorPanelProps {
  onClose: () => void
}

export function InspectorPanel({ onClose }: InspectorPanelProps) {
  const { t } = useTranslation()
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId)
  const selectedEdgeId = useGraphStore((s) => s.selectedEdgeId)
  const node = useGraphStore((s) => s.nodes.find((n) => n.id === s.selectedNodeId))
  const edge = useGraphStore((s) => s.edges.find((e) => e.id === s.selectedEdgeId))

  const title = node?.data?.label || (edge ? t('graph.edge', { defaultValue: 'Edge' }) : '')

  return (
    <div className="flex h-full flex-col bg-[var(--surface-1)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <span className="text-sm font-medium text-[var(--text-primary)]">{title}</span>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {selectedNodeId && <PropertiesPanel />}
        {/* Edge properties: 如果有 EdgePropertiesPanel 组件则渲染，否则显示基本信息 */}
      </div>
    </div>
  )
}
```

> **注意：** PropertiesPanel 内部已经从 builderStore 读取 selectedNodeId 并渲染对应表单。InspectorPanel 只是提供外壳（header + close button + scroll container）。迁移到 graphStore 后 PropertiesPanel 的 import 需要更新。

- [ ] **Step 3: 运行测试**

Run: `cd frontend && npx vitest run components/editors/graph-builder/components/__tests__/InspectorPanel.test.tsx`

- [ ] **Step 4: 提交**

```bash
git add frontend/components/editors/graph-builder/components/InspectorPanel.tsx \
       frontend/components/editors/graph-builder/components/__tests__/InspectorPanel.test.tsx
git commit -m "feat: add InspectorPanel for node/edge property editing"
```

---

## Task 6: GraphStatusBar — 重写已有底部状态栏

**Files:**
- Rewrite: `frontend/components/editors/graph-builder/components/GraphStatusBar.tsx` (已有 149 行，重写为使用 saveStore)
- Create: `frontend/components/editors/graph-builder/components/ZoomControls.tsx`

**目标：** 重写已有 GraphStatusBar，改为从 saveStore 读取状态（而非 builderStore），并抽出 ZoomControls 为独立组件。保留已有功能：保存错误显示、重试计数、手动保存按钮、在线/离线状态。

**依赖：** Task 2（saveStore）

- [ ] **Step 1: 实现 ZoomControls.tsx**

```tsx
// frontend/components/editors/graph-builder/components/ZoomControls.tsx
'use client'

import { Maximize, Minus, Plus } from 'lucide-react'
import { useReactFlow } from 'reactflow'
import { Button } from '@/components/ui/button'

export function ZoomControls() {
  const { fitView, zoomIn, zoomOut } = useReactFlow()

  return (
    <div className="flex items-center gap-0.5">
      <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => fitView({ duration: 300 })}>
        <Maximize className="h-3 w-3" />
      </Button>
      <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => zoomOut({ duration: 200 })}>
        <Minus className="h-3 w-3" />
      </Button>
      <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => zoomIn({ duration: 200 })}>
        <Plus className="h-3 w-3" />
      </Button>
    </div>
  )
}
```

- [ ] **Step 2: 实现 GraphStatusBar.tsx**

```tsx
// frontend/components/editors/graph-builder/components/GraphStatusBar.tsx
'use client'

import { useTranslation } from '@/lib/i18n'
import { useSaveStore } from '../stores/saveStore'
import { ZoomControls } from './ZoomControls'

export function GraphStatusBar() {
  const { t } = useTranslation()
  const isSaving = useSaveStore((s) => s.isSaving)
  const lastAutoSaveTime = useSaveStore((s) => s.lastAutoSaveTime)
  const deployedAt = useSaveStore((s) => s.deployedAt)

  const saveText = isSaving
    ? t('graph.saving', { defaultValue: 'Saving...' })
    : lastAutoSaveTime
      ? `${t('graph.autoSaved', { defaultValue: 'Auto-saved' })} ${new Date(lastAutoSaveTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
      : t('graph.notSaved', { defaultValue: 'Not saved' })

  const publishText = deployedAt
    ? t('graph.published', { defaultValue: 'Published' })
    : t('graph.notPublished', { defaultValue: 'Not published' })

  return (
    <div className="flex items-center justify-between border-t border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-1">
      <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
        <span className="flex items-center gap-1">
          <span className={`h-1.5 w-1.5 rounded-full ${isSaving ? 'bg-yellow-400' : 'bg-green-400'}`} />
          {saveText}
        </span>
        <span>·</span>
        <span>{publishText}</span>
      </div>
      <ZoomControls />
    </div>
  )
}
```

- [ ] **Step 3: 提交**

```bash
git add frontend/components/editors/graph-builder/components/GraphStatusBar.tsx \
       frontend/components/editors/graph-builder/components/ZoomControls.tsx
git commit -m "feat: add GraphStatusBar and ZoomControls"
```

---

## Task 7: CopilotOverlay — 底部浮动 AI 助手

**Files:**
- Create: `frontend/components/editors/graph-builder/components/CopilotOverlay.tsx`
- Test: `frontend/components/editors/graph-builder/components/__tests__/CopilotOverlay.test.tsx`

**目标：** 底部浮动 Copilot，收起/展开两态。聊天逻辑从 StudioRightPanel 迁移。

**依赖：** Task 3（builderUIStore — copilotExpanded）

**参考旧文件：** `frontend/components/editors/graph-builder/studio/StudioRightPanel.tsx`

- [ ] **Step 1: 写测试**

```tsx
// frontend/components/editors/graph-builder/components/__tests__/CopilotOverlay.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (_: string, o?: { defaultValue?: string }) => o?.defaultValue ?? _ }),
}))

import { CopilotOverlay } from '../CopilotOverlay'

describe('CopilotOverlay', () => {
  it('renders collapsed input bar by default', () => {
    render(<CopilotOverlay agentId="a-1" expanded={false} onToggle={vi.fn()} />)
    expect(screen.getByText(/ask copilot/i)).toBeInTheDocument()
  })

  it('calls onToggle when collapsed bar clicked', () => {
    const onToggle = vi.fn()
    render(<CopilotOverlay agentId="a-1" expanded={false} onToggle={onToggle} />)
    fireEvent.click(screen.getByText(/ask copilot/i))
    expect(onToggle).toHaveBeenCalled()
  })

  it('renders expanded chat panel', () => {
    render(<CopilotOverlay agentId="a-1" expanded={true} onToggle={vi.fn()} />)
    expect(screen.getByText('Copilot')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/type a message/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 实现 CopilotOverlay.tsx**

读取 StudioRightPanel 中的 Copilot 聊天逻辑（useCopilotChat hook 或内联逻辑），迁移到新组件。UI 改为浮动层。

```tsx
// frontend/components/editors/graph-builder/components/CopilotOverlay.tsx
'use client'

import { useState } from 'react'
import { ChevronDown, Send, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'

interface CopilotOverlayProps {
  agentId: string
  expanded: boolean
  onToggle: () => void
}

export function CopilotOverlay({ agentId, expanded, onToggle }: CopilotOverlayProps) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')

  if (!expanded) {
    return (
      <div className="absolute bottom-2 left-1/2 z-30 w-full max-w-xl -translate-x-1/2 px-4">
        <button
          className="flex w-full items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-2)]/90 px-4 py-2.5 text-sm text-[var(--text-muted)] shadow-lg backdrop-blur transition-colors hover:bg-[var(--surface-2)]"
          onClick={onToggle}
        >
          <Sparkles className="h-4 w-4 shrink-0 text-[var(--skill-brand-600)]" />
          {t('graph.copilot.placeholder', { defaultValue: 'Ask Copilot to build or modify your graph...' })}
        </button>
      </div>
    )
  }

  return (
    <div className="absolute bottom-2 left-1/2 z-30 flex h-[40vh] w-full max-w-2xl -translate-x-1/2 flex-col rounded-xl border border-[var(--border)] bg-[var(--surface-1)] shadow-2xl">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          <Sparkles className="h-3.5 w-3.5 text-[var(--skill-brand-600)]" />
          Copilot
        </span>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onToggle}>
          <ChevronDown className="h-4 w-4" />
        </Button>
      </div>

      {/* Message list — 从 StudioRightPanel 迁移聊天消息渲染逻辑 */}
      <div className="flex-1 overflow-y-auto p-4">
        <p className="text-center text-xs text-[var(--text-muted)]">
          {t('graph.copilot.empty', { defaultValue: 'Ask Copilot to add nodes, connect edges, or modify your graph.' })}
        </p>
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border)] p-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t('graph.copilot.inputPlaceholder', { defaultValue: 'Type a message...' })}
            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--skill-brand-600)]"
            onKeyDown={(e) => { if (e.key === 'Enter' && input.trim()) { /* send */ setInput('') } }}
          />
          <Button size="sm" disabled={!input.trim()} className="shrink-0">
            <Send className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}
```

> **注意：** 聊天消息发送/接收的完整逻辑需要从 StudioRightPanel 迁移。这里先搭好 UI 骨架，消息列表渲染和 API 调用在实现时从旧代码复制。

- [ ] **Step 3: 运行测试**

Run: `cd frontend && npx vitest run components/editors/graph-builder/components/__tests__/CopilotOverlay.test.tsx`

- [ ] **Step 4: 提交**

```bash
git add frontend/components/editors/graph-builder/components/CopilotOverlay.tsx \
       frontend/components/editors/graph-builder/components/__tests__/CopilotOverlay.test.tsx
git commit -m "feat: add CopilotOverlay floating AI assistant"
```

---

## Task 8: GraphBuilderShell — 布局容器

**Files:**
- Create: `frontend/components/editors/graph-builder/GraphBuilderShell.tsx`
- Test: `frontend/components/editors/graph-builder/__tests__/GraphBuilderShell.test.tsx`

**目标：** 纯布局容器，组装 GraphToolbar + BuilderCanvas + InspectorPanel + CopilotOverlay + GraphStatusBar。

**依赖：** Task 1, 3, 4, 5, 6, 7

- [ ] **Step 1: 写测试**

```tsx
// frontend/components/editors/graph-builder/__tests__/GraphBuilderShell.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (_: string, o?: { defaultValue?: string }) => o?.defaultValue ?? _ }),
}))
vi.mock('@/providers/workspace-permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canEdit: true, canAdmin: true }),
}))
vi.mock('../stores/graphStore', () => ({
  useGraphStore: (sel: any) => sel({ selectedNodeId: null, selectedEdgeId: null, nodes: [], edges: [], addNode: vi.fn() }),
}))
vi.mock('../stores/saveStore', () => ({
  useSaveStore: (sel: any) => sel({ isSaving: false, lastAutoSaveTime: null, deployedAt: null }),
}))
vi.mock('../stores/builderUIStore', () => ({
  useBuilderUIStore: (sel: any) => sel({ copilotExpanded: false, toggleCopilot: vi.fn() }),
}))
vi.mock('../components/BuilderCanvas', () => ({
  default: () => <div data-testid="canvas">Canvas</div>,
}))
vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({ fitView: vi.fn(), zoomIn: vi.fn(), zoomOut: vi.fn() }),
}))

import { GraphBuilderShell } from '../GraphBuilderShell'

describe('GraphBuilderShell', () => {
  const baseProps = { agentId: 'a-1', workspaceId: 'ws-1', onOpenTestLab: vi.fn(), onOpenRelease: vi.fn() }

  it('renders toolbar, canvas, status bar', () => {
    render(<GraphBuilderShell {...baseProps} />)
    expect(screen.getByTestId('canvas')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /test/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /release/i })).toBeInTheDocument()
  })

  it('renders copilot collapsed bar', () => {
    render(<GraphBuilderShell {...baseProps} />)
    expect(screen.getByText(/ask copilot/i)).toBeInTheDocument()
  })

  it('does not render inspector when nothing selected', () => {
    render(<GraphBuilderShell {...baseProps} />)
    expect(screen.queryByRole('button', { name: /close/i })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 实现 GraphBuilderShell.tsx**

```tsx
// frontend/components/editors/graph-builder/GraphBuilderShell.tsx
'use client'

import { useGraphStore } from './stores/graphStore'
import { useBuilderUIStore } from './stores/builderUIStore'
import BuilderCanvas from './components/BuilderCanvas'
import { GraphToolbar } from './components/GraphToolbar'
import { InspectorPanel } from './components/InspectorPanel'
import { CopilotOverlay } from './components/CopilotOverlay'
import { GraphStatusBar } from './components/GraphStatusBar'

interface GraphBuilderShellProps {
  agentId: string
  versionId?: string
  workspaceId: string
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
}

export function GraphBuilderShell({
  agentId,
  onOpenTestLab,
  onOpenRelease,
}: GraphBuilderShellProps) {
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId)
  const selectedEdgeId = useGraphStore((s) => s.selectedEdgeId)
  const hasSelection = Boolean(selectedNodeId || selectedEdgeId)

  const copilotExpanded = useBuilderUIStore((s) => s.copilotExpanded)
  const toggleCopilot = useBuilderUIStore((s) => s.toggleCopilot)

  return (
    <div className="flex h-full flex-col">
      <GraphToolbar onOpenTestLab={onOpenTestLab} onOpenRelease={onOpenRelease} />

      <div className="relative flex min-h-0 flex-1">
        {/* Canvas — auto-shrinks when inspector is open */}
        <div className="min-w-0 flex-1">
          <BuilderCanvas />
        </div>

        {/* Inspector — slides in from right when node/edge selected */}
        {hasSelection && (
          <aside className="w-[360px] shrink-0 border-l border-[var(--border)] overflow-y-auto">
            <InspectorPanel onClose={() => useGraphStore.getState().clearSelection()} />
          </aside>
        )}

        {/* Copilot — floating overlay above status bar */}
        <CopilotOverlay agentId={agentId} expanded={copilotExpanded} onToggle={toggleCopilot} />
      </div>

      <GraphStatusBar />
    </div>
  )
}
```

- [ ] **Step 3: 运行测试**

Run: `cd frontend && npx vitest run components/editors/graph-builder/__tests__/GraphBuilderShell.test.tsx`

- [ ] **Step 4: 提交**

```bash
git add frontend/components/editors/graph-builder/GraphBuilderShell.tsx \
       frontend/components/editors/graph-builder/__tests__/GraphBuilderShell.test.tsx
git commit -m "feat: add GraphBuilderShell layout container"
```

---

## Task 9: AgentBuilder 精简 — ReactFlowProvider + 初始化

**Files:**
- Rewrite: `frontend/components/editors/graph-builder/AgentBuilder.tsx`

**目标：** 将 657 行的 AgentBuilder 精简为 ~120 行：ReactFlowProvider 包裹 + 初始化逻辑（版本解冻、数据加载、store 同步）+ GraphBuilderShell。删除 studioMode 分叉、RunInputModal、ExecutionPanel 渲染、右面板 absolute 布局。

**依赖：** Task 1-8（所有新组件和 store 就位）

**参考旧文件：** 当前 `AgentBuilder.tsx`（657 行）

- [ ] **Step 1: 读取当前 AgentBuilder.tsx**

完整读取，理解所有 useEffect 和初始化逻辑。需要保留的逻辑：
- ReactFlowProvider 包裹
- useEffect: sync agentId/versionId/workspaceId to graphStore
- useEffect: auto-unfreeze frozen versions
- useEffect: auto-save lifecycle (start/stop)
- useEffect: handle online event (reconnect save)
- useEffect: handle beforeunload (beacon save)
- useEffect: load graph when agentId changes (graphStateData → store)
- useEffect: cleanup execution state on unmount
- AlertDialogs for import/new graph confirmation

需要删除的逻辑：
- `studioMode` prop 和所有条件分支
- `isRunModalOpen`, `runInput` state
- `showExecutionPanel` 相关逻辑
- 右面板 `<aside className="absolute inset-y-0 right-0">` 布局
- `<BuilderToolbar>` 渲染（移到 GraphToolbar）
- `<StudioRightPanel>` / `<BuilderSidebarTabs>` 渲染
- `<RunInputModal>` / `<ExecutionPanel>` 渲染

- [ ] **Step 2: 重写 AgentBuilder.tsx**

```tsx
// frontend/components/editors/graph-builder/AgentBuilder.tsx
'use client'

import { ReactFlowProvider } from 'reactflow'
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'

import { useVersionGraphState } from '@/hooks/queries/agentVersions'
import { useAgent } from '@/hooks/queries/agents'
import { useFreezeVersion, useUnfreezeVersion } from '@/hooks/queries/agentVersions'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

import { GraphBuilderShell } from './GraphBuilderShell'
import { useGraphStore } from './stores/graphStore'
import { useSaveStore } from './stores/saveStore'

interface AgentBuilderProps {
  agentId: string
  versionId?: string
  workspaceId: string
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
}

export default function AgentBuilder(props: AgentBuilderProps) {
  return (
    <ReactFlowProvider>
      <AgentBuilderInit {...props} />
    </ReactFlowProvider>
  )
}

function AgentBuilderInit({
  agentId,
  versionId,
  workspaceId,
  onOpenTestLab,
  onOpenRelease,
}: AgentBuilderProps) {
  // --- Data fetching ---
  const { data: agentData } = useAgent(agentId, workspaceId)
  const { data: graphStateData, isLoading: isGraphLoading } = useVersionGraphState(
    agentId, versionId, workspaceId,
    { enabled: Boolean(agentId && versionId && workspaceId) },
  )
  const unfreezeVersion = useUnfreezeVersion()

  // --- Sync identity to graphStore ---
  useEffect(() => {
    useGraphStore.setState({ agentId, versionId: versionId ?? null, workspaceId })
  }, [agentId, versionId, workspaceId])

  // --- Auto-unfreeze frozen versions ---
  useEffect(() => {
    if (graphStateData?.versionStatus === 'frozen' && versionId) {
      unfreezeVersion.mutate({ agentId, versionId, workspaceId })
    }
  }, [graphStateData?.versionStatus])

  // --- Load graph data into store ---
  useEffect(() => {
    if (!graphStateData || !agentData) return
    // 从旧 AgentBuilder 的 useEffect (line 238) 复制图数据加载逻辑
    // 设置 nodes, edges, graphName, graphStateFields, fallbackNodeId, isInitializing=false
    useGraphStore.setState({
      graphId: agentId,
      graphName: agentData.name,
      nodes: graphStateData.nodes ?? [],
      edges: graphStateData.edges ?? [],
      graphStateFields: graphStateData.stateFields ?? [],
      fallbackNodeId: graphStateData.fallbackNodeId ?? null,
      isInitializing: false,
    })
  }, [agentId, agentData, graphStateData])

  // --- Auto-save lifecycle ---
  useEffect(() => {
    const { graphId, graphName, isInitializing } = useGraphStore.getState()
    if (graphId && graphName && !isInitializing) {
      useSaveStore.getState().startAutoSave()
    }
    return () => useSaveStore.getState().stopAutoSave()
  }, [agentId, graphStateData])

  // --- Beacon save on beforeunload ---
  useEffect(() => {
    const handler = () => {
      // 从旧 AgentBuilder 复制 beacon save 逻辑
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  // --- Loading state ---
  const isInitializing = useGraphStore((s) => s.isInitializing)
  if (isGraphLoading || isInitializing) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
      </div>
    )
  }

  return (
    <GraphBuilderShell
      agentId={agentId}
      versionId={versionId}
      workspaceId={workspaceId}
      onOpenTestLab={onOpenTestLab}
      onOpenRelease={onOpenRelease}
    />
  )
}
```

> **注意：** 图数据加载的具体逻辑（viewport 恢复、节点位置计算等）需要从旧 AgentBuilder 的 line 238-340 完整复制。上面的代码是骨架，实现时需要补全细节。

- [ ] **Step 3: 更新 visual-builder-surface.tsx**

删除 `studioMode` prop：

```tsx
// frontend/components/agents/surfaces/visual/visual-builder-surface.tsx
'use client'

import AgentBuilder from '@/components/editors/graph-builder/AgentBuilder'
import type { StageProps } from '@/components/agents/agent-build/agent-build-types'

export function VisualBuilderSurface({ agent, version, workspaceId, navigateToStage }: StageProps) {
  return (
    <AgentBuilder
      agentId={agent.id}
      workspaceId={workspaceId}
      versionId={version?.id}
      onOpenTestLab={() => navigateToStage('test-lab')}
      onOpenRelease={() => navigateToStage('release')}
    />
  )
}
```

- [ ] **Step 4: TypeScript 编译检查**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: 可能有 store import 路径错误，逐个修复。

- [ ] **Step 5: 提交**

```bash
git add frontend/components/editors/graph-builder/AgentBuilder.tsx \
       frontend/components/agents/surfaces/visual/visual-builder-surface.tsx
git commit -m "refactor: slim AgentBuilder to init + GraphBuilderShell, remove studioMode"
```

---

## Task 10: 清理 — 删除旧文件 + 迁移 store 消费者

**Files:**
- Delete: `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx`
- Delete: `frontend/components/editors/graph-builder/BuilderSidebarTabs.tsx`
- Delete: `frontend/components/editors/graph-builder/studio/StudioRightPanel.tsx`
- Modify: 所有 `useBuilderStore` 消费者 → 迁移到 `useGraphStore` / `useSaveStore`

**目标：** 删除被取代的旧文件，将所有 `useBuilderStore` import 迁移到新 store。

**依赖：** Task 9（AgentBuilder 不再引用旧文件）

- [ ] **Step 1: 检查残留 import**

```bash
grep -r "BuilderToolbar\|BuilderSidebarTabs\|StudioRightPanel" frontend/ --include="*.ts" --include="*.tsx" -l
```

Expected: 只有旧文件自身。如果 AgentBuilder 还引用，说明 Task 9 没改干净。

- [ ] **Step 2: 删除旧文件**

```bash
rm frontend/components/editors/graph-builder/components/BuilderToolbar.tsx
rm frontend/components/editors/graph-builder/components/BuilderSidebarTabs.tsx
rm frontend/components/editors/graph-builder/components/StudioRightPanel.tsx
```

- [ ] **Step 3: 迁移 useBuilderStore 消费者**

```bash
grep -r "useBuilderStore" frontend/ --include="*.ts" --include="*.tsx" -l
```

对每个文件：
- 如果读取 nodes/edges/selectedNodeId/selectedEdgeId → 改为 `useGraphStore`
- 如果读取 isSaving/lastAutoSaveTime → 改为 `useSaveStore`
- 如果读取 UI 状态 → 改为 `useBuilderUIStore`

> **关键文件列表（从探索结果）：**
> - `BuilderCanvas.tsx` → useGraphStore
> - `BuilderNode.tsx` → useGraphStore
> - `PropertiesPanel.tsx` → useGraphStore
> - `InterruptPanel.tsx` → useGraphStore + useSaveStore
> - `ModelIOCard.tsx` → useGraphStore
> - `ToolCallCard.tsx` → useGraphStore
> - `DeploymentHistoryPanel.tsx` → useSaveStore
> - `studio-test-lab-stage.tsx` → useGraphStore (已在 surfaces/visual/)
> - `hooks/useDeploymentHistory.ts` → useSaveStore

- [ ] **Step 4: 删除 builderStore.ts 兼容层**

当所有消费者迁移完后，删除 `builderStore.ts` 或将其改为纯 re-export：

```bash
rm frontend/components/editors/graph-builder/stores/builderStore.ts
```

- [ ] **Step 5: TypeScript 全量编译**

Run: `cd frontend && npx tsc --noEmit --pretty`
Expected: 无错误

- [ ] **Step 6: 全量测试**

Run: `cd frontend && npx vitest run`
Expected: ALL PASS

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "refactor: delete old files, migrate all useBuilderStore consumers to new stores"
```

---

## Task 11: 全局验证 — TypeScript + 测试 + 视觉检查

**Files:** 无新文件，纯验证

- [ ] **Step 1: TypeScript 全量编译**

Run: `cd frontend && npx tsc --noEmit --pretty`
Expected: 无错误

- [ ] **Step 2: 全量测试**

Run: `cd frontend && npx vitest run`
Expected: ALL PASS

- [ ] **Step 3: 检查 i18n key 覆盖**

新增的 i18n key：
- `graph.saving`, `graph.autoSaved`, `graph.notSaved`
- `graph.published`, `graph.notPublished`
- `graph.copilot.placeholder`, `graph.copilot.empty`, `graph.copilot.inputPlaceholder`
- `graph.edge`
- `agents.build.test`, `agents.build.release`

检查 en.ts 和 zh.ts，添加缺失的 key。

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "chore: add i18n keys and verify full compilation for graph builder refactoring"
```
