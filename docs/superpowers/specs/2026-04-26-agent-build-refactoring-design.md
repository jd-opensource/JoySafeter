# Agent 全体重构设计

> 日期: 2026-04-26
> 状态: 待审核

## 问题

当前前端 Agent 系统存在以下问题：

1. **缺乏主线** — `page.tsx` 按 `definitionKind === 'graph'` 分叉，graph 走 `AgentStudioShell`，其他走 Overview/Legacy，没有统一入口
2. **功能杂糅** — `AgentBuilder.tsx` 内部判断 `definitionKind === 'code'` 渲染 `CodeEditorPage`，code builder 硬塞进 visual builder
3. **两套类型并存** — `types/agent.ts`（新）和 `types/agents.ts`（旧）定义冲突
4. **布局浪费空间** — 左侧 260px 阶段导航在构建阶段压缩了画布空间，用户 80% 时间在构建
5. **测试被锁死** — Test Lab 绑定在 graph draft execution 上，不能边构建边测试

## 目标架构

### 核心模型

5 个固定阶段，所有 Agent 类型共享同一生命周期：

| 阶段 | 引擎适配 | 说明 |
|---|---|---|
| 目标 (Brief) | 需要适配 | 通用外壳 + 引擎特定字段 |
| 构建 (Build) | 完全个性化 | 跟引擎深度绑定 |
| 测试 (Test Lab) | 需要适配 | 通用外壳 + 引擎特定执行/展示 |
| 发布 (Release) | 完全通用 | 冻结版本 → 创建 Release |
| 使用 (Usage) | 完全通用 | 接入业务场景 |

### 架构模式：Builder Surface Provider

每种引擎实现 `BuilderSurface` 接口，通过 React Context 注入 AgentBuildShell。

```typescript
interface BuilderSurface {
  kind: BuilderSurfaceKind  // 'visual' | 'cli' | 'code' | 'prompt'
  BriefStage:   React.ComponentType<StageProps>
  BuildStage:   React.ComponentType<StageProps>
  TestLabStage: React.ComponentType<StageProps>
}

interface StageProps {
  agent: Agent
  version: AgentVersion
  workspaceId: string
  navigateToStage: (stageId: string) => void
}
```

Context 注入：

```typescript
const BuilderSurfaceContext = React.createContext<BuilderSurface | null>(null)

function useBuilderSurface(): BuilderSurface {
  const ctx = useContext(BuilderSurfaceContext)
  if (!ctx) throw new Error('useBuilderSurface must be used within BuilderSurfaceProvider')
  return ctx
}
```

入口组装：

```typescript
// app/agents/[agentId]/page.tsx
function AgentPage({ agent, version }) {
  const surface = resolveBuilderSurface(version.definition_kind)
  return (
    <BuilderSurfaceContext.Provider value={surface}>
      <AgentBuildShell agent={agent} version={version} />
    </BuilderSurfaceContext.Provider>
  )
}
```

所有 Agent 统一走 AgentBuildShell，不再按 definitionKind 分叉路由。

## 页面布局

### 从左侧导航改为顶部 Stepper

行业调研（Dify、Coze、n8n、AWS Step Functions、Retool Workflows、OpenAI GPT Builder）发现：

- 没有主流产品用左侧边栏做生命周期阶段导航
- 左侧边栏都留给构建工具（节点面板、资源列表）
- 生命周期阶段普遍用顶部 tab/stepper 或按钮
- 测试面板几乎都是"随时可用"的滑出 panel

### 新布局

```
┌─────────────────────────────────────────────────────────┐
│  [Agent名称]   ① 目标  ② 构建  ③ 测试  ④ 发布  ⑤ 使用  │  ← 顶部 stepper
├─────────────────────────────────────────────────────────┤
│                                                         │
│              全宽工作区（按阶段切换内容）                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

各阶段布局：

| 阶段 | 布局 |
|---|---|
| 目标 | 居中卡片，max-width 720px |
| 构建 | 全宽，三栏（可选左面板 + 画布/编辑器 + 右面板） |
| 测试 | 左右分栏（输入 / 结果） |
| 发布 | 居中卡片，max-width 960px |
| 使用 | 居中卡片，max-width 960px |

### Stepper 交互

- 水平排列 5 个阶段，带序号 + 图标 + 标签
- 当前阶段高亮，点击任意阶段可跳转（非线性限制）
- 构建阶段时 stepper 可收缩为 mini 模式（只显示图标），最大化画布空间

### 构建阶段的测试快捷入口

- 构建工具栏保留 "▶ Run Draft" 按钮
- 点击后右侧滑出 Test Panel（overlay），不离开构建阶段
- 也可以点 stepper 的"测试"进入完整测试页面

## AgentBuildShell 重写

```typescript
function AgentBuildShell({ agent, version }) {
  const surface = useBuilderSurface()
  const [activeStageId, setActiveStageId] = useState(() =>
    resolveDefaultStage(agent, version)
  )

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center border-b px-4 py-2">
        <AgentIdentity agent={agent} />
        <BuildStepper
          stages={BUILD_STAGES}
          activeStage={activeStageId}
          onNavigate={setActiveStageId}
        />
        <StatusBadges agent={agent} />
      </header>
      <main className="min-h-0 flex-1">
        <StageRenderer
          stageId={activeStageId}
          surface={surface}
          agent={agent}
          version={version}
          navigateToStage={setActiveStageId}
        />
      </main>
    </div>
  )
}
```

### StageRenderer

```typescript
function StageRenderer({ stageId, surface, ...stageProps }) {
  switch (stageId) {
    case 'brief':    return <surface.BriefStage {...stageProps} />
    case 'build':    return <surface.BuildStage {...stageProps} />
    case 'test-lab': return <surface.TestLabStage {...stageProps} />
    case 'release':  return <AgentReleaseStage {...stageProps} />
    case 'usage':    return <AgentUsageStage {...stageProps} />
  }
}
```

## 进入 Agent 的默认阶段路由

| Agent 状态 | 默认阶段 | 理由 |
|---|---|---|
| 无 draft version 或 draft 内容为空 | 目标 | 新 Agent，从头开始 |
| 有 draft 内容（节点 > 0 / 代码非空 / prompt 非空） | 构建 | 继续上次的工作 |
| 有 active_release 且无未保存修改 | 使用 | Agent 已上线 |
| URL 带 `?stage=xxx` | 指定阶段 | 显式指定优先 |

优先级：`URL ?stage=` > 自动判断。

## 文件结构

```
frontend/components/agents/
  agent-build/                              # 通用层
    agent-build-shell.tsx                   # 重写：顶部 stepper + 全宽工作区
    agent-build-types.ts                    # 5 阶段定义 + BuilderSurface 接口 + StageProps
    builder-surface-context.tsx             # Context + useBuilderSurface() hook
    builder-surface-registry.ts             # resolveBuilderSurface(definitionKind)
    agent-release-stage.tsx                 # 通用 Release（已有）
    agent-usage-stage.tsx                   # 通用 Usage（已有）
    agent-release-adapter.ts               # Release 适配器（已有）

  surfaces/                                 # 引擎适配层
    visual/
      index.ts                              # 导出 visualSurface: BuilderSurface
      visual-brief-stage.tsx                # ← studio/studio-brief-stage.tsx
      visual-builder-surface.tsx            # ← studio/visual-builder-surface.tsx + studio-canvas-stage.tsx
      visual-test-lab-stage.tsx             # ← studio/studio-test-lab-stage.tsx
    cli/
      index.ts                              # placeholder
    code/
      index.ts                              # placeholder
    prompt/
      index.ts                              # placeholder

  studio/                                   # 整体删除
```

## 迁移映射

| 旧文件 | 去向 |
|---|---|
| `studio/agent-studio-shell.tsx` | 删除 — 职责被 `agent-build-shell.tsx` + Context 取代 |
| `studio/studio-types.ts` | 合并到 `agent-build-types.ts` |
| `studio/studio-brief-stage.tsx` | `surfaces/visual/visual-brief-stage.tsx` |
| `studio/studio-canvas-stage.tsx` + `studio/visual-builder-surface.tsx` | `surfaces/visual/visual-builder-surface.tsx`（合并） |
| `studio/studio-test-lab-stage.tsx` | `surfaces/visual/visual-test-lab-stage.tsx` |
| `studio/studio-right-panel.tsx` | 留在 `editors/graph-builder/` 内部 |

## 类型系统清理

合并 `types/agents.ts` 到 `types/agent.ts`，删除 `types/agents.ts`。

```typescript
// types/agent.ts — 唯一的 Agent 类型定义
export type DefinitionKind = 'prompt' | 'graph' | 'code'       // 删除 'hybrid'
export type RuntimeKind = 'graph' | 'sandbox' | 'code' | 'copilot' | 'hosted' | 'external'
export type BuilderSurfaceKind = 'visual' | 'cli' | 'code' | 'prompt'
```

DefinitionKind → BuilderSurfaceKind 映射：
- `graph` → `visual`
- `code` → `code`
- `prompt` → `prompt`
- `cli` — 预留，暂无对应 DefinitionKind

## 重构范围

本次只实现：
- 架构搭建（AgentBuildShell 重写 + BuilderSurface Provider + 顶部 Stepper）
- Visual Builder Surface 完整可用
- CLI / Code / Prompt Surface 留 placeholder
- 类型系统统一
- studio/ 目录退役

## 不在范围内

- CLI Builder Surface 实现
- Code Builder Surface 实现
- Prompt Builder Surface 实现
- 后端 API 变更
