# Agent 全体重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Agent 系统重构为统一的 AgentBuildShell + Builder Surface Provider 架构，顶部 Stepper 导航，Visual Builder 完整可用，其余 Surface 留 placeholder。

**Architecture:** AgentBuildShell 管理 5 阶段生命周期（目标/构建/测试/发布/使用），通过 React Context 注入 BuilderSurface 接口实现引擎适配。layout.tsx 精简为 Agent 身份 + Chat/Settings 入口，Shell 的 Stepper 成为主导航。

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS, Zustand, React Query, React Flow, Vitest + Testing Library

**Spec:** `docs/superpowers/specs/2026-04-26-agent-build-refactoring-design.md`

---

## 文件结构总览

### 新建文件
- `frontend/components/agents/agent-build/agent-build-types.ts` — 重写：BuildStageId, StageProps, BuilderSurface, BUILD_STAGES, resolveDefaultStage
- `frontend/components/agents/agent-build/builder-surface-context.tsx` — Context + useBuilderSurface hook
- `frontend/components/agents/agent-build/builder-surface-registry.ts` — 重写：resolveBuilderSurface 返回 BuilderSurface 对象
- `frontend/components/agents/agent-build/build-stepper.tsx` — 顶部 Stepper 组件
- `frontend/components/agents/agent-build/stage-renderer.tsx` — StageRenderer 路由组件
- `frontend/components/agents/surfaces/visual/index.ts` — visualSurface 导出
- `frontend/components/agents/surfaces/visual/visual-brief-stage.tsx` — Visual Brief（从 studio 迁移重写）
- `frontend/components/agents/surfaces/visual/visual-builder-surface.tsx` — Visual Build（从 studio 合并重写）
- `frontend/components/agents/surfaces/visual/visual-test-lab-stage.tsx` — Visual Test Lab（从 studio 迁移重写）
- `frontend/components/agents/surfaces/cli/index.ts` — placeholder
- `frontend/components/agents/surfaces/code/index.ts` — placeholder
- `frontend/components/agents/surfaces/prompt/index.ts` — placeholder

### 重写文件
- `frontend/components/agents/agent-build/agent-build-shell.tsx` — 重写为顶部 Stepper + 全宽工作区
- `frontend/components/agents/agent-build/agent-release-stage.tsx` — props 重写为 StageProps
- `frontend/components/agents/agent-build/agent-usage-stage.tsx` — props 重写为 StageProps
- `frontend/app/agents/[agentId]/page.tsx` — 统一入口，不再分叉路由
- `frontend/app/agents/[agentId]/layout.tsx` — 精简：删除 overview/builder tab

### 删除文件
- `frontend/components/agents/studio/agent-studio-shell.tsx`
- `frontend/components/agents/studio/studio-types.ts`
- `frontend/components/agents/studio/studio-brief-stage.tsx`
- `frontend/components/agents/studio/studio-canvas-stage.tsx`
- `frontend/components/agents/studio/visual-builder-surface.tsx`
- `frontend/components/agents/studio/studio-test-lab-stage.tsx`
- `frontend/components/agents/studio/__tests__/agent-studio-shell.test.tsx`
- `frontend/components/agents/studio/__tests__/studio-stage-selection.test.ts`
- `frontend/components/agents/studio/__tests__/studio-test-lab-stage.test.tsx`
- `frontend/types/agents.ts`

---

## Task 1: 类型基础层 — agent-build-types.ts 重写

**Files:**
- Rewrite: `frontend/components/agents/agent-build/agent-build-types.ts`
- Test: `frontend/components/agents/agent-build/__tests__/agent-build-types.test.ts`

**目标：** 定义整个重构的类型基础 — BuildStageId、StageProps、BuilderSurface 接口、BUILD_STAGES 常量、resolveDefaultStage 函数。

- [ ] **Step 1: 写测试**

```typescript
// frontend/components/agents/agent-build/__tests__/agent-build-types.test.ts
import { describe, it, expect } from 'vitest'
import {
  BUILD_STAGES,
  resolveDefaultStage,
  isBuildStageId,
} from '../agent-build-types'

describe('BUILD_STAGES', () => {
  it('defines exactly 5 stages in order', () => {
    expect(BUILD_STAGES.map((s) => s.id)).toEqual([
      'brief', 'build', 'test-lab', 'release', 'usage',
    ])
  })

  it('each stage has icon, labelKey, descriptionKey', () => {
    for (const stage of BUILD_STAGES) {
      expect(stage.icon).toBeDefined()
      expect(stage.labelKey).toMatch(/^agents\.build\.stages\./)
      expect(stage.descriptionKey).toMatch(/^agents\.build\.stageDescriptions\./)
    }
  })
})

describe('isBuildStageId', () => {
  it('returns true for valid stage ids', () => {
    expect(isBuildStageId('brief')).toBe(true)
    expect(isBuildStageId('build')).toBe(true)
    expect(isBuildStageId('test-lab')).toBe(true)
    expect(isBuildStageId('release')).toBe(true)
    expect(isBuildStageId('usage')).toBe(true)
  })

  it('returns false for invalid values', () => {
    expect(isBuildStageId('canvas')).toBe(false)
    expect(isBuildStageId(null)).toBe(false)
    expect(isBuildStageId(undefined)).toBe(false)
  })
})

describe('resolveDefaultStage', () => {
  const baseAgent = { active_release_id: null } as any

  it('returns brief when no version', () => {
    expect(resolveDefaultStage(baseAgent, null)).toBe('brief')
  })

  it('returns brief when version has empty payload', () => {
    const version = { definition_payload: { nodes: [] } } as any
    expect(resolveDefaultStage(baseAgent, version)).toBe('brief')
  })

  it('returns build when version has nodes', () => {
    const version = { definition_payload: { nodes: [{}] } } as any
    expect(resolveDefaultStage(baseAgent, version)).toBe('build')
  })

  it('returns usage when agent has active release', () => {
    const agent = { active_release_id: 'rel-1' } as any
    const version = { definition_payload: { nodes: [{}] } } as any
    expect(resolveDefaultStage(agent, version)).toBe('usage')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/agent-build-types.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现 agent-build-types.ts**

```typescript
// frontend/components/agents/agent-build/agent-build-types.ts
import { Beaker, BriefcaseBusiness, FileText, Hammer, Rocket, type LucideIcon } from 'lucide-react'
import type { Agent, AgentVersion } from '@/types/agent'

export type BuildStageId = 'brief' | 'build' | 'test-lab' | 'release' | 'usage'

export interface StageProps {
  agent: Agent
  version: AgentVersion | null
  workspaceId: string
  navigateToStage: (stageId: BuildStageId) => void
}

export interface BuilderSurface {
  BriefStage: React.ComponentType<StageProps>
  BuildStage: React.ComponentType<StageProps>
  TestLabStage: React.ComponentType<StageProps>
}

export interface BuildStageConfig {
  id: BuildStageId
  labelKey: string
  descriptionKey: string
  icon: LucideIcon
}

export const BUILD_STAGES: readonly BuildStageConfig[] = [
  { id: 'brief',    labelKey: 'agents.build.stages.brief',   descriptionKey: 'agents.build.stageDescriptions.brief',   icon: FileText },
  { id: 'build',    labelKey: 'agents.build.stages.build',   descriptionKey: 'agents.build.stageDescriptions.build',   icon: Hammer },
  { id: 'test-lab', labelKey: 'agents.build.stages.testLab', descriptionKey: 'agents.build.stageDescriptions.testLab', icon: Beaker },
  { id: 'release',  labelKey: 'agents.build.stages.release', descriptionKey: 'agents.build.stageDescriptions.release', icon: Rocket },
  { id: 'usage',    labelKey: 'agents.build.stages.usage',   descriptionKey: 'agents.build.stageDescriptions.usage',   icon: BriefcaseBusiness },
] as const

const BUILD_STAGE_IDS = new Set<BuildStageId>(BUILD_STAGES.map((s) => s.id))

export function isBuildStageId(value: string | null | undefined): value is BuildStageId {
  return Boolean(value && BUILD_STAGE_IDS.has(value as BuildStageId))
}

function hasVersionContent(version: AgentVersion): boolean {
  const payload = version.definition_payload
  if (!payload) return false
  const nodes = payload.nodes as unknown[] | undefined
  if (Array.isArray(nodes) && nodes.length > 0) return true
  const code = payload.code_content as string | undefined
  if (code && code.trim().length > 0) return true
  const prompt = payload.prompt as string | undefined
  if (prompt && prompt.trim().length > 0) return true
  return false
}

export function resolveDefaultStage(agent: Agent, version: AgentVersion | null): BuildStageId {
  if (agent.active_release_id) return 'usage'
  if (!version) return 'brief'
  return hasVersionContent(version) ? 'build' : 'brief'
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/agent-build-types.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/components/agents/agent-build/agent-build-types.ts frontend/components/agents/agent-build/__tests__/agent-build-types.test.ts
git commit -m "feat: rewrite agent-build-types with BuildStageId, StageProps, BuilderSurface"
```

---

## Task 2: Context + Registry — BuilderSurface 注入机制

**Files:**
- Create: `frontend/components/agents/agent-build/builder-surface-context.tsx`
- Rewrite: `frontend/components/agents/agent-build/builder-surface-registry.ts`
- Test: `frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts`

**目标：** 创建 BuilderSurfaceContext 和 useBuilderSurface hook，重写 registry 使其返回 BuilderSurface 对象而非字符串。

**依赖：** Task 1（BuilderSurface 接口）

- [ ] **Step 1: 写 registry 测试**

```typescript
// frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts
import { describe, it, expect } from 'vitest'
import { resolveBuilderSurface } from '../builder-surface-registry'

describe('resolveBuilderSurface', () => {
  it('returns visual surface for graph', () => {
    const surface = resolveBuilderSurface('graph')
    expect(surface.BriefStage).toBeDefined()
    expect(surface.BuildStage).toBeDefined()
    expect(surface.TestLabStage).toBeDefined()
  })

  it('returns visual surface for hybrid', () => {
    const surface = resolveBuilderSurface('hybrid')
    expect(surface).toBe(resolveBuilderSurface('graph'))
  })

  it('returns placeholder surface for code', () => {
    const surface = resolveBuilderSurface('code')
    expect(surface.BriefStage).toBeDefined()
  })

  it('returns placeholder surface for prompt', () => {
    const surface = resolveBuilderSurface('prompt')
    expect(surface.BriefStage).toBeDefined()
  })

  it('defaults to visual for null/undefined', () => {
    expect(resolveBuilderSurface(null)).toBe(resolveBuilderSurface('graph'))
    expect(resolveBuilderSurface(undefined)).toBe(resolveBuilderSurface('graph'))
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/builder-surface-registry.test.ts`
Expected: FAIL

- [ ] **Step 3: 创建 placeholder surfaces**

先创建 placeholder，让 registry 有东西可以引用。

```typescript
// frontend/components/agents/surfaces/cli/index.ts
import type { BuilderSurface, StageProps } from '@/components/agents/agent-build/agent-build-types'

function PlaceholderStage({ navigateToStage }: StageProps) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
      CLI Builder — coming soon
    </div>
  )
}

export const cliSurface: BuilderSurface = {
  BriefStage: PlaceholderStage,
  BuildStage: PlaceholderStage,
  TestLabStage: PlaceholderStage,
}
```

```typescript
// frontend/components/agents/surfaces/code/index.ts
import type { BuilderSurface, StageProps } from '@/components/agents/agent-build/agent-build-types'

function PlaceholderStage({ navigateToStage }: StageProps) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
      Code Builder — coming soon
    </div>
  )
}

export const codeSurface: BuilderSurface = {
  BriefStage: PlaceholderStage,
  BuildStage: PlaceholderStage,
  TestLabStage: PlaceholderStage,
}
```

```typescript
// frontend/components/agents/surfaces/prompt/index.ts
import type { BuilderSurface, StageProps } from '@/components/agents/agent-build/agent-build-types'

function PlaceholderStage({ navigateToStage }: StageProps) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
      Prompt Builder — coming soon
    </div>
  )
}

export const promptSurface: BuilderSurface = {
  BriefStage: PlaceholderStage,
  BuildStage: PlaceholderStage,
  TestLabStage: PlaceholderStage,
}
```

- [ ] **Step 4: 创建 Visual Surface 临时 stub**

Visual Surface 的真实实现在 Task 6-8，这里先用 stub 让 registry 编译通过。

```typescript
// frontend/components/agents/surfaces/visual/index.ts
import type { BuilderSurface, StageProps } from '@/components/agents/agent-build/agent-build-types'

function StubStage(_props: StageProps) {
  return <div>Visual stub — will be replaced</div>
}

export const visualSurface: BuilderSurface = {
  BriefStage: StubStage,
  BuildStage: StubStage,
  TestLabStage: StubStage,
}
```

- [ ] **Step 5: 实现 builder-surface-context.tsx**

```typescript
// frontend/components/agents/agent-build/builder-surface-context.tsx
'use client'

import { createContext, useContext } from 'react'
import type { BuilderSurface } from './agent-build-types'

export const BuilderSurfaceContext = createContext<BuilderSurface | null>(null)

export function useBuilderSurface(): BuilderSurface {
  const ctx = useContext(BuilderSurfaceContext)
  if (!ctx) {
    throw new Error('useBuilderSurface must be used within a BuilderSurfaceContext.Provider')
  }
  return ctx
}
```

- [ ] **Step 6: 重写 builder-surface-registry.ts**

```typescript
// frontend/components/agents/agent-build/builder-surface-registry.ts
import type { BuilderSurface } from './agent-build-types'
import { visualSurface } from '@/components/agents/surfaces/visual'
import { cliSurface } from '@/components/agents/surfaces/cli'
import { codeSurface } from '@/components/agents/surfaces/code'
import { promptSurface } from '@/components/agents/surfaces/prompt'

export type BuilderSurfaceKind = 'visual' | 'cli' | 'code' | 'prompt'

const SURFACE_MAP: Record<BuilderSurfaceKind, BuilderSurface> = {
  visual: visualSurface,
  cli:    cliSurface,
  code:   codeSurface,
  prompt: promptSurface,
}

const DEFINITION_TO_SURFACE: Record<string, BuilderSurfaceKind> = {
  graph:  'visual',
  hybrid: 'visual',
  code:   'code',
  prompt: 'prompt',
  cli:    'cli',
}

export function resolveBuilderSurface(definitionKind: string | null | undefined): BuilderSurface {
  const surfaceKind = DEFINITION_TO_SURFACE[definitionKind ?? ''] ?? 'visual'
  return SURFACE_MAP[surfaceKind]
}
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/builder-surface-registry.test.ts`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add frontend/components/agents/agent-build/builder-surface-context.tsx \
       frontend/components/agents/agent-build/builder-surface-registry.ts \
       frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts \
       frontend/components/agents/surfaces/
git commit -m "feat: add BuilderSurface context, registry, and placeholder surfaces"
```

---

## Task 3: BuildStepper — 顶部阶段导航组件

**Files:**
- Create: `frontend/components/agents/agent-build/build-stepper.tsx`
- Test: `frontend/components/agents/agent-build/__tests__/build-stepper.test.tsx`

**目标：** 水平 Stepper 组件，5 个阶段带序号 + 图标 + 标签 + 连接线，当前阶段高亮，点击跳转。

**依赖：** Task 1（BUILD_STAGES, BuildStageId）

- [ ] **Step 1: 写测试**

```typescript
// frontend/components/agents/agent-build/__tests__/build-stepper.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { BuildStepper } from '../build-stepper'
import { BUILD_STAGES } from '../agent-build-types'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
  }),
}))

describe('BuildStepper', () => {
  const onNavigate = vi.fn()

  it('renders all 5 stages', () => {
    render(<BuildStepper stages={BUILD_STAGES} activeStage="brief" onNavigate={onNavigate} />)
    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(5)
  })

  it('marks active stage with aria-current', () => {
    render(<BuildStepper stages={BUILD_STAGES} activeStage="build" onNavigate={onNavigate} />)
    const activeButton = screen.getByRole('button', { current: 'step' })
    expect(activeButton).toBeInTheDocument()
  })

  it('calls onNavigate when clicking a stage', () => {
    render(<BuildStepper stages={BUILD_STAGES} activeStage="brief" onNavigate={onNavigate} />)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[2]) // test-lab
    expect(onNavigate).toHaveBeenCalledWith('test-lab')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/build-stepper.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 build-stepper.tsx**

```tsx
// frontend/components/agents/agent-build/build-stepper.tsx
'use client'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import type { BuildStageConfig, BuildStageId } from './agent-build-types'

interface BuildStepperProps {
  stages: readonly BuildStageConfig[]
  activeStage: BuildStageId
  onNavigate: (stageId: BuildStageId) => void
}

export function BuildStepper({ stages, activeStage, onNavigate }: BuildStepperProps) {
  const { t } = useTranslation()

  return (
    <nav aria-label="Build stages" className="flex items-center gap-1">
      {stages.map((stage, index) => {
        const Icon = stage.icon
        const isActive = stage.id === activeStage
        const isLast = index === stages.length - 1

        return (
          <div key={stage.id} className="flex items-center">
            <button
              type="button"
              aria-current={isActive ? 'step' : undefined}
              className={cn(
                'flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                'hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--skill-brand-600)]',
                isActive
                  ? 'bg-[var(--skill-brand-50)] text-[var(--skill-brand-700)]'
                  : 'text-[var(--text-muted)]',
              )}
              onClick={() => onNavigate(stage.id)}
            >
              <span
                className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[10px] font-bold',
                  isActive
                    ? 'bg-[var(--skill-brand-600)] text-white'
                    : 'bg-[var(--surface-2)] text-[var(--text-muted)]',
                )}
              >
                {index + 1}
              </span>
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="hidden whitespace-nowrap sm:inline">{t(stage.labelKey)}</span>
            </button>
            {!isLast && (
              <div className="mx-1 h-px w-4 bg-[var(--border)]" />
            )}
          </div>
        )
      })}
    </nav>
  )
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/build-stepper.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/components/agents/agent-build/build-stepper.tsx \
       frontend/components/agents/agent-build/__tests__/build-stepper.test.tsx
git commit -m "feat: add BuildStepper horizontal stage navigation component"
```

---

## Task 4: StageRenderer + AgentBuildShell 重写

**Files:**
- Create: `frontend/components/agents/agent-build/stage-renderer.tsx`
- Rewrite: `frontend/components/agents/agent-build/agent-build-shell.tsx`
- Test: `frontend/components/agents/agent-build/__tests__/agent-build-shell.test.tsx` (重写)

**目标：** StageRenderer 根据 stageId 路由到 surface 组件或通用组件。AgentBuildShell 重写为顶部 Stepper + 全宽工作区，通过 useBuilderSurface 消费 Context。

**依赖：** Task 1-3

- [ ] **Step 1: 实现 stage-renderer.tsx**

```tsx
// frontend/components/agents/agent-build/stage-renderer.tsx
'use client'

import type { BuildStageId, BuilderSurface, StageProps } from './agent-build-types'
import { AgentReleaseStage } from './agent-release-stage'
import { AgentUsageStage } from './agent-usage-stage'

interface StageRendererProps {
  stageId: BuildStageId
  surface: BuilderSurface
  stageProps: StageProps
}

export function StageRenderer({ stageId, surface, stageProps }: StageRendererProps) {
  switch (stageId) {
    case 'brief':
      return <surface.BriefStage {...stageProps} />
    case 'build':
      return <surface.BuildStage {...stageProps} />
    case 'test-lab':
      return <surface.TestLabStage {...stageProps} />
    case 'release':
      return <AgentReleaseStage {...stageProps} />
    case 'usage':
      return <AgentUsageStage {...stageProps} />
  }
}
```

> **注意：** 这里 AgentReleaseStage 和 AgentUsageStage 的 props 签名还没改成 StageProps，会有 TS 报错。Task 5 会修复。先写 shell 整体结构。

- [ ] **Step 2: 重写 agent-build-shell.tsx**

```tsx
// frontend/components/agents/agent-build/agent-build-shell.tsx
'use client'

import { useCallback, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/i18n'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import type { Agent, AgentVersion } from '@/types/agent'

import { BUILD_STAGES, isBuildStageId, resolveDefaultStage, type BuildStageId } from './agent-build-types'
import { BuildStepper } from './build-stepper'
import { useBuilderSurface } from './builder-surface-context'
import { StageRenderer } from './stage-renderer'

interface AgentBuildShellProps {
  agent: Agent
  version: AgentVersion | null
}

export function AgentBuildShell({ agent, version }: AgentBuildShellProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const surface = useBuilderSurface()
  const { workspaceId } = useCurrentWorkspace()

  const [activeStageId, setActiveStageId] = useState<BuildStageId>(() => {
    const urlStage = searchParams.get('stage')
    if (urlStage && isBuildStageId(urlStage)) return urlStage
    return resolveDefaultStage(agent, version)
  })

  const navigateToStage = useCallback(
    (stageId: BuildStageId) => {
      setActiveStageId(stageId)
      const params = new URLSearchParams(searchParams.toString())
      params.set('stage', stageId)
      router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
    },
    [agent.id, router, searchParams],
  )

  const stageProps = {
    agent,
    version,
    workspaceId,
    navigateToStage,
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-2">
        <BuildStepper
          stages={BUILD_STAGES}
          activeStage={activeStageId}
          onNavigate={navigateToStage}
        />
        <div className="flex items-center gap-2">
          <Badge variant={agent.active_release_id ? 'default' : 'outline'}>
            {agent.active_release_id
              ? t('agents.build.status.published', { defaultValue: 'Published' })
              : t('agents.build.status.notPublished', { defaultValue: 'Not Published' })}
          </Badge>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">
        <StageRenderer stageId={activeStageId} surface={surface} stageProps={stageProps} />
      </main>
    </div>
  )
}
```

- [ ] **Step 3: 重写 shell 测试**

```tsx
// frontend/components/agents/agent-build/__tests__/agent-build-shell.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const replaceMock = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))
vi.mock('@/providers/workspace-provider', () => ({
  useCurrentWorkspace: () => ({ workspaceId: 'ws-1' }),
}))

const mockBriefStage = vi.fn(() => <div data-testid="brief-stage">Brief</div>)
const mockBuildStage = vi.fn(() => <div data-testid="build-stage">Build</div>)
const mockTestLabStage = vi.fn(() => <div data-testid="test-lab-stage">TestLab</div>)

vi.mock('./builder-surface-context', () => ({
  useBuilderSurface: () => ({
    BriefStage: mockBriefStage,
    BuildStage: mockBuildStage,
    TestLabStage: mockTestLabStage,
  }),
}))

vi.mock('./agent-release-stage', () => ({
  AgentReleaseStage: () => <div data-testid="release-stage">Release</div>,
}))
vi.mock('./agent-usage-stage', () => ({
  AgentUsageStage: () => <div data-testid="usage-stage">Usage</div>,
}))

import { AgentBuildShell } from '../agent-build-shell'

const baseAgent = {
  id: 'agent-1',
  name: 'Test Agent',
  active_release_id: null,
  status: 'draft',
} as any

describe('AgentBuildShell', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders stepper with 5 stages', () => {
    render(<AgentBuildShell agent={baseAgent} version={null} />)
    const buttons = screen.getAllByRole('button')
    expect(buttons.length).toBeGreaterThanOrEqual(5)
  })

  it('defaults to brief stage when no version', () => {
    render(<AgentBuildShell agent={baseAgent} version={null} />)
    expect(screen.getByTestId('brief-stage')).toBeInTheDocument()
  })

  it('defaults to usage stage when agent has active release', () => {
    const agent = { ...baseAgent, active_release_id: 'rel-1' }
    render(<AgentBuildShell agent={agent} version={null} />)
    expect(screen.getByTestId('usage-stage')).toBeInTheDocument()
  })

  it('navigates to a different stage on click', async () => {
    const user = userEvent.setup()
    render(<AgentBuildShell agent={baseAgent} version={null} />)
    const buttons = screen.getAllByRole('button')
    await user.click(buttons[3]) // release (index 3)
    expect(screen.getByTestId('release-stage')).toBeInTheDocument()
  })
})
```

- [ ] **Step 4: 运行测试**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/agent-build-shell.test.tsx`
Expected: PASS（可能有 TS 警告因为 Release/Usage props 还没改，但测试用 mock 所以能过）

- [ ] **Step 5: 提交**

```bash
git add frontend/components/agents/agent-build/stage-renderer.tsx \
       frontend/components/agents/agent-build/agent-build-shell.tsx \
       frontend/components/agents/agent-build/__tests__/agent-build-shell.test.tsx
git commit -m "feat: rewrite AgentBuildShell with top stepper and StageRenderer"
```

---

## Task 5: 通用阶段 props 重写 — Release + Usage

**Files:**
- Rewrite: `frontend/components/agents/agent-build/agent-release-stage.tsx`
- Rewrite: `frontend/components/agents/agent-build/agent-usage-stage.tsx`
- Test: `frontend/components/agents/agent-build/__tests__/agent-build-stages.test.tsx` (重写)

**目标：** 将 AgentReleaseStage 和 AgentUsageStage 的 props 签名从旧的自定义 props 重写为统一的 StageProps。内部派生 runtimeKind、canPublishDraft 等值。

**依赖：** Task 1（StageProps）

- [ ] **Step 1: 重写 agent-release-stage.tsx**

关键变化：
- props 从 `{ agent, canPublishDraft, versionId, workspaceId, runtimeKind }` 改为 `StageProps`
- `runtimeKind` 内部从 `version?.definition_kind` 派生：`graph → 'graph'`, `code → 'sandbox'`, 其余 → `'graph'`
- `canPublishDraft` 内部从 `version?.definition_payload` 判断
- `versionId` 从 `version?.id` 取

```tsx
// frontend/components/agents/agent-build/agent-release-stage.tsx
// 只改 props 接口和组件签名，内部逻辑不变

// 旧：
// interface AgentReleaseStageProps {
//   agent: Agent
//   canPublishDraft?: boolean
//   versionId?: string
//   workspaceId: string
//   runtimeKind: RuntimeKind
// }

// 新：
import type { StageProps } from './agent-build-types'
import type { RuntimeKind } from '@/types/agent-release'

function deriveRuntimeKind(definitionKind: string | undefined): RuntimeKind {
  switch (definitionKind) {
    case 'graph': return 'graph'
    case 'hybrid': return 'graph'
    case 'code': return 'sandbox'
    default: return 'graph'
  }
}

function hasPublishableContent(version: AgentVersion | null): boolean {
  if (!version?.definition_payload) return false
  const payload = version.definition_payload
  const nodes = payload.nodes as unknown[] | undefined
  if (Array.isArray(nodes) && nodes.length > 0) return true
  const code = payload.code_content as string | undefined
  if (code && code.trim().length > 0) return true
  const prompt = payload.prompt as string | undefined
  if (prompt && prompt.trim().length > 0) return true
  return false
}

export function AgentReleaseStage({ agent, version, workspaceId }: StageProps) {
  const versionId = version?.id
  const runtimeKind = deriveRuntimeKind(version?.definition_kind)
  const canPublishDraft = hasPublishableContent(version)
  // ... 其余内部逻辑保持不变，只是从 props 解构改为从上面的变量读取
}
```

- [ ] **Step 2: 重写 agent-usage-stage.tsx**

变化更小 — 旧 props 是 `{ agent, workspaceId }`，新 props 是 `StageProps`，只需改签名。

```tsx
// frontend/components/agents/agent-build/agent-usage-stage.tsx
import type { StageProps } from './agent-build-types'

export function AgentUsageStage({ agent, workspaceId }: StageProps) {
  // 内部逻辑完全不变
}
```

- [ ] **Step 3: 重写测试**

```tsx
// frontend/components/agents/agent-build/__tests__/agent-build-stages.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))
vi.mock('@/providers/workspace-permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canAdmin: true }),
}))
vi.mock('@/hooks/queries/agentReleases', () => ({
  releaseKeys: { all: () => ['releases'] },
  useReleases: () => ({ data: [], isLoading: false }),
  useActivateRelease: () => ({ mutate: vi.fn(), isPending: false }),
  useRetireRelease: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('@/hooks/queries/agents', () => ({
  agentKeys: { detail: () => ['agent'] },
}))
vi.mock('@/hooks/queries/agentVersions', () => ({
  versionKeys: { all: () => ['versions'] },
}))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

import { AgentReleaseStage } from '../agent-release-stage'
import { AgentUsageStage } from '../agent-usage-stage'

const baseStageProps = {
  agent: { id: 'a-1', name: 'Test', active_release_id: null } as any,
  version: { id: 'v-1', definition_kind: 'graph', definition_payload: { nodes: [{}] } } as any,
  workspaceId: 'ws-1',
  navigateToStage: vi.fn(),
}

describe('AgentReleaseStage', () => {
  it('renders with StageProps', () => {
    render(<AgentReleaseStage {...baseStageProps} />)
    expect(screen.getByText('Publish and manage releases')).toBeInTheDocument()
  })

  it('enables publish when version has content', () => {
    render(<AgentReleaseStage {...baseStageProps} />)
    const publishBtn = screen.getByRole('button', { name: /publish draft/i })
    expect(publishBtn).not.toBeDisabled()
  })

  it('disables publish when version is null', () => {
    render(<AgentReleaseStage {...baseStageProps} version={null} />)
    const publishBtn = screen.getByRole('button', { name: /publish draft/i })
    expect(publishBtn).toBeDisabled()
  })
})

describe('AgentUsageStage', () => {
  it('renders with StageProps', () => {
    render(<AgentUsageStage {...baseStageProps} />)
    expect(screen.getByText('Use this Agent in business scenarios')).toBeInTheDocument()
  })
})
```

- [ ] **Step 4: 运行测试**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/agent-build-stages.test.tsx`
Expected: PASS

- [ ] **Step 5: 运行全部 agent-build 测试确认无回归**

Run: `cd frontend && npx vitest run components/agents/agent-build/`
Expected: ALL PASS

- [ ] **Step 6: 提交**

```bash
git add frontend/components/agents/agent-build/agent-release-stage.tsx \
       frontend/components/agents/agent-build/agent-usage-stage.tsx \
       frontend/components/agents/agent-build/__tests__/agent-build-stages.test.tsx
git commit -m "refactor: rewrite Release and Usage stage props to unified StageProps"
```

---

## Task 6: Visual Brief Stage — 从 studio 迁移重写

**Files:**
- Create: `frontend/components/agents/surfaces/visual/visual-brief-stage.tsx`
- Test: `frontend/components/agents/surfaces/visual/__tests__/visual-brief-stage.test.tsx`

**目标：** 将 `studio/studio-brief-stage.tsx` 迁移到 `surfaces/visual/`，props 改为 StageProps。内部逻辑复用（表单字段、prompt 生成），但导航改为 `navigateToStage('build')`，copilot prompt 通过 URL 参数传递。

**依赖：** Task 1（StageProps）

**参考旧文件：** `frontend/components/agents/studio/studio-brief-stage.tsx`（104 行）

- [ ] **Step 1: 写测试**

```tsx
// frontend/components/agents/surfaces/visual/__tests__/visual-brief-stage.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

const replaceMock = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))

import { VisualBriefStage } from '../visual-brief-stage'

const baseProps = {
  agent: { id: 'a-1', name: 'My Agent', description: 'test goal' } as any,
  version: null,
  workspaceId: 'ws-1',
  navigateToStage: vi.fn(),
}

describe('VisualBriefStage', () => {
  it('renders the brief form with goal pre-filled from agent description', () => {
    render(<VisualBriefStage {...baseProps} />)
    const goalTextarea = screen.getByDisplayValue('test goal')
    expect(goalTextarea).toBeInTheDocument()
  })

  it('has Generate and Build manually buttons', () => {
    render(<VisualBriefStage {...baseProps} />)
    expect(screen.getByRole('button', { name: /generate/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /build manually/i })).toBeInTheDocument()
  })

  it('navigates to build stage on skip', () => {
    render(<VisualBriefStage {...baseProps} />)
    fireEvent.click(screen.getByRole('button', { name: /build manually/i }))
    expect(baseProps.navigateToStage).toHaveBeenCalledWith('build')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run components/agents/surfaces/visual/__tests__/visual-brief-stage.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 visual-brief-stage.tsx**

从 `studio-brief-stage.tsx` 复制核心逻辑，改 props 签名和导航方式：

```tsx
// frontend/components/agents/surfaces/visual/visual-brief-stage.tsx
'use client'

import { useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import type { StageProps } from '@/components/agents/agent-build/agent-build-types'

export function VisualBriefStage({ agent, navigateToStage }: StageProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()

  const [goal, setGoal] = useState(agent.description || '')
  const [input, setInput] = useState('')
  const [output, setOutput] = useState('')
  const [tools, setTools] = useState('')
  const [constraints, setConstraints] = useState('')
  const [scenario, setScenario] = useState('')

  const prompt = useMemo(
    () =>
      [
        `Build a Visual Agent named "${agent.name}".`,
        `Goal: ${goal || 'Not specified'}`,
        `Input: ${input || 'Not specified'}`,
        `Output: ${output || 'Not specified'}`,
        `Tools or Skills: ${tools || 'Not specified'}`,
        `Safety and human confirmation rules: ${constraints || 'Not specified'}`,
        `Business usage scenario: ${scenario || 'Not specified'}`,
        'Create an initial graph, add reasonable nodes and edges, and explain missing configuration.',
      ].join('\n'),
    [agent.name, constraints, goal, input, output, scenario, tools],
  )

  const handleGenerate = () => {
    const params = new URLSearchParams(searchParams.toString())
    params.set('stage', 'build')
    params.set('copilotInput', prompt)
    router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
  }

  return (
    <div className="h-full overflow-y-auto bg-[var(--surface-1)]">
      <div className="mx-auto max-w-3xl px-8 py-8">
        <div className="mb-8">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
            {t('agents.studio.brief.kicker', { defaultValue: 'First build step' })}
          </p>
          <h2 className="mt-2 text-3xl font-semibold text-[var(--text-primary)]">
            {t('agents.studio.brief.title', { defaultValue: 'Describe the Agent you want to build' })}
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
            {t('agents.studio.brief.subtitle', {
              defaultValue:
                'Copilot will turn this brief into an editable visual workflow. You can still skip and build manually on the canvas.',
            })}
          </p>
        </div>

        <div className="grid gap-5 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-5 shadow-sm">
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.goal', { defaultValue: 'Goal' })}</Label>
            <Textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={3} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>{t('agents.studio.brief.input', { defaultValue: 'Input' })}</Label>
              <Input value={input} onChange={(e) => setInput(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>{t('agents.studio.brief.output', { defaultValue: 'Output' })}</Label>
              <Input value={output} onChange={(e) => setOutput(e.target.value)} />
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.tools', { defaultValue: 'Tools / Skills' })}</Label>
            <Input value={tools} onChange={(e) => setTools(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.constraints', { defaultValue: 'Safety / approval rules' })}</Label>
            <Textarea value={constraints} onChange={(e) => setConstraints(e.target.value)} rows={2} />
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.scenario', { defaultValue: 'Business scenario' })}</Label>
            <Input value={scenario} onChange={(e) => setScenario(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => navigateToStage('build')}>
              {t('agents.studio.brief.skip', { defaultValue: 'Build manually' })}
            </Button>
            <Button onClick={handleGenerate} disabled={!goal.trim()}>
              {t('agents.studio.brief.generate', { defaultValue: 'Generate with Copilot' })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run components/agents/surfaces/visual/__tests__/visual-brief-stage.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/components/agents/surfaces/visual/visual-brief-stage.tsx \
       frontend/components/agents/surfaces/visual/__tests__/visual-brief-stage.test.tsx
git commit -m "feat: add VisualBriefStage with StageProps interface"
```

---

## Task 7: Visual Builder Surface — 从 studio 合并重写

**Files:**
- Rewrite: `frontend/components/agents/surfaces/visual/visual-builder-surface.tsx`

**目标：** 合并 `studio/studio-canvas-stage.tsx` + `studio/visual-builder-surface.tsx` 为一个组件，props 改为 StageProps。内部渲染 AgentBuilder（studioMode=true），从 StageProps 派生 agentId/workspaceId/versionId。

**依赖：** Task 1（StageProps）

**参考旧文件：**
- `studio/studio-canvas-stage.tsx`（30 行）— 传递 props 给 VisualBuilderSurface
- `studio/visual-builder-surface.tsx`（31 行）— 渲染 AgentBuilder

- [ ] **Step 1: 实现 visual-builder-surface.tsx**

```tsx
// frontend/components/agents/surfaces/visual/visual-builder-surface.tsx
'use client'

import { AgentBuilder } from '@/components/editors/graph-builder/AgentBuilder'
import type { StageProps } from '@/components/agents/agent-build/agent-build-types'

export function VisualBuilderSurface({ agent, version, workspaceId, navigateToStage }: StageProps) {
  return (
    <AgentBuilder
      agentId={agent.id}
      workspaceId={workspaceId}
      versionId={version?.id}
      studioMode
      onOpenTestLab={() => navigateToStage('test-lab')}
      onOpenRelease={() => navigateToStage('release')}
    />
  )
}
```

> **注意：** AgentBuilder 的 props 接口不变（它接收 agentId/workspaceId/versionId 字符串），我们只是在 Surface 层做适配。AgentBuilder 内部的 `definitionKind === 'code'` 分支在本次重构中不需要处理 — code agent 会走 codeSurface（placeholder），不会进入 VisualBuilderSurface。

- [ ] **Step 2: 提交**

```bash
git add frontend/components/agents/surfaces/visual/visual-builder-surface.tsx
git commit -m "feat: add VisualBuilderSurface wrapping AgentBuilder with StageProps"
```

---

## Task 8: Visual Test Lab Stage — 从 studio 迁移重写

**Files:**
- Rewrite: `frontend/components/agents/surfaces/visual/visual-test-lab-stage.tsx`
- Test: `frontend/components/agents/surfaces/visual/__tests__/visual-test-lab-stage.test.tsx`

**目标：** 将 `studio/studio-test-lab-stage.tsx` 迁移到 `surfaces/visual/`，props 改为 StageProps。内部逻辑复用（useExecutionStore、draft execution），导航改为 navigateToStage。

**依赖：** Task 1（StageProps）

**参考旧文件：** `frontend/components/agents/studio/studio-test-lab-stage.tsx`（118 行）

- [ ] **Step 1: 写测试**

```tsx
// frontend/components/agents/surfaces/visual/__tests__/visual-test-lab-stage.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))
vi.mock('@/components/editors/graph-builder/stores/builderStore', () => ({
  useBuilderStore: { setState: vi.fn() },
}))
vi.mock('@/components/editors/graph-builder/stores/execution/executionStore', () => ({
  useExecutionStore: () => ({
    isExecuting: false,
    setCurrentGraphId: vi.fn(),
    startDraftExecution: vi.fn(),
    stopExecution: vi.fn(),
  }),
}))
vi.mock('@/components/execution/ExecutionPanelNew', () => ({
  ExecutionPanelNew: () => <div data-testid="execution-panel">Execution</div>,
}))

import { VisualTestLabStage } from '../visual-test-lab-stage'

const baseProps = {
  agent: { id: 'a-1', name: 'Test' } as any,
  version: { id: 'v-1', definition_kind: 'graph' } as any,
  workspaceId: 'ws-1',
  navigateToStage: vi.fn(),
}

describe('VisualTestLabStage', () => {
  it('renders test input and run button', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByPlaceholderText(/enter a sample request/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /run draft/i })).toBeInTheDocument()
  })

  it('renders execution panel', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByTestId('execution-panel')).toBeInTheDocument()
  })

  it('has navigation buttons using navigateToStage', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByRole('button', { name: /back to build/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open release/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run components/agents/surfaces/visual/__tests__/visual-test-lab-stage.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 visual-test-lab-stage.tsx**

```tsx
// frontend/components/agents/surfaces/visual/visual-test-lab-stage.tsx
'use client'

import { useEffect, useState } from 'react'

import { useBuilderStore } from '@/components/editors/graph-builder/stores/builderStore'
import { useExecutionStore } from '@/components/editors/graph-builder/stores/execution/executionStore'
import { ExecutionPanelNew as ExecutionPanel } from '@/components/execution/ExecutionPanelNew'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import type { StageProps } from '@/components/agents/agent-build/agent-build-types'

export function VisualTestLabStage({ agent, version, workspaceId, navigateToStage }: StageProps) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')
  const agentId = agent.id
  const versionId = version?.id

  const { isExecuting, setCurrentGraphId, startDraftExecution, stopExecution } =
    useExecutionStore()

  useEffect(() => {
    useBuilderStore.setState({
      agentId,
      graphId: agentId,
      versionId: versionId ?? null,
      workspaceId,
    })
    setCurrentGraphId(agentId)
  }, [agentId, setCurrentGraphId, versionId, workspaceId])

  const runDraft = async () => {
    const trimmedInput = input.trim()
    if (!trimmedInput || !versionId) return
    await startDraftExecution({
      agentId,
      versionId,
      workspaceId,
      input: trimmedInput,
    })
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--surface-1)]">
      <div className="shrink-0 border-b border-[var(--border)] px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
              {t('agents.studio.testLab.kicker', { defaultValue: 'Draft validation' })}
            </p>
            <h2 className="mt-1 text-xl font-semibold">
              {t('agents.studio.testLab.title', { defaultValue: 'Test the current draft' })}
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('agents.studio.testLab.subtitle', {
                defaultValue: 'Run draft behavior before publishing. These tests do not affect the active release.',
              })}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => navigateToStage('build')}>
              {t('agents.studio.testLab.backToCanvas', { defaultValue: 'Back to Build' })}
            </Button>
            <Button variant="outline" onClick={() => navigateToStage('release')}>
              {t('agents.studio.testLab.openRelease', { defaultValue: 'Open Release' })}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[360px_1fr]">
        <aside className="border-r border-[var(--border)] p-4">
          <label className="text-sm font-medium">
            {t('agents.studio.testLab.inputLabel', { defaultValue: 'Test input' })}
          </label>
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={8}
            className="mt-2"
            placeholder={t('agents.studio.testLab.inputPlaceholder', {
              defaultValue: 'Enter a sample request for this draft...',
            })}
          />
          <Button
            className="mt-3 w-full"
            onClick={runDraft}
            disabled={!input.trim() || !versionId || isExecuting}
          >
            {isExecuting
              ? t('agents.studio.testLab.running', { defaultValue: 'Running...' })
              : t('agents.studio.testLab.runDraft', { defaultValue: 'Run Draft' })}
          </Button>
          {isExecuting && (
            <Button className="mt-2 w-full" variant="outline" onClick={() => stopExecution()}>
              {t('agents.studio.testLab.stop', { defaultValue: 'Stop' })}
            </Button>
          )}
        </aside>
        <section className="min-h-0 overflow-hidden">
          <ExecutionPanel embedded />
        </section>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npx vitest run components/agents/surfaces/visual/__tests__/visual-test-lab-stage.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/components/agents/surfaces/visual/visual-test-lab-stage.tsx \
       frontend/components/agents/surfaces/visual/__tests__/visual-test-lab-stage.test.tsx
git commit -m "feat: add VisualTestLabStage with StageProps interface"
```

---

## Task 9: Visual Surface 组装 — 替换 stub

**Files:**
- Rewrite: `frontend/components/agents/surfaces/visual/index.ts`

**目标：** 将 Task 2 中的 stub 替换为 Task 6-8 中实现的真实组件。

**依赖：** Task 6, 7, 8

- [ ] **Step 1: 重写 visual/index.ts**

```typescript
// frontend/components/agents/surfaces/visual/index.ts
import type { BuilderSurface } from '@/components/agents/agent-build/agent-build-types'

import { VisualBriefStage } from './visual-brief-stage'
import { VisualBuilderSurface } from './visual-builder-surface'
import { VisualTestLabStage } from './visual-test-lab-stage'

export const visualSurface: BuilderSurface = {
  BriefStage: VisualBriefStage,
  BuildStage: VisualBuilderSurface,
  TestLabStage: VisualTestLabStage,
}
```

- [ ] **Step 2: 运行 registry 测试确认仍通过**

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/builder-surface-registry.test.ts`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add frontend/components/agents/surfaces/visual/index.ts
git commit -m "feat: wire real Visual Surface components into visualSurface export"
```

---

## Task 10: 路由入口重写 — page.tsx 统一

**Files:**
- Rewrite: `frontend/app/agents/[agentId]/page.tsx`

**目标：** 删除 definitionKind 分叉路由，所有 Agent 统一走 BuilderSurfaceContext.Provider + AgentBuildShell。保留 `?tab=chat` 和 `?tab=settings` 分支（由 layout 处理）。

**依赖：** Task 1-4, 9

**参考旧文件：** `frontend/app/agents/[agentId]/page.tsx`（78 行）

- [ ] **Step 1: 重写 page.tsx**

```tsx
// frontend/app/agents/[agentId]/page.tsx
'use client'

import { Loader2 } from 'lucide-react'
import { useParams, useSearchParams } from 'next/navigation'

import { AgentBuildShell } from '@/components/agents/agent-build/agent-build-shell'
import { BuilderSurfaceContext } from '@/components/agents/agent-build/builder-surface-context'
import { resolveBuilderSurface } from '@/components/agents/agent-build/builder-surface-registry'
import { AgentSettingsTab } from '@/components/agents/agent-settings-tab'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { useAgent } from '@/hooks/queries/agents'
import { useVersion } from '@/hooks/queries/agentVersions'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

export default function AgentDetailPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const agentId = params.agentId as string
  const tab = searchParams.get('tab')
  const threadId = searchParams.get('thread') || undefined
  const { workspaceId } = useCurrentWorkspace()

  const { data: agent, isLoading: isAgentLoading } = useAgent(agentId, workspaceId)
  const draftVersionId = agent?.current_draft_version_id || undefined
  const { data: version, isLoading: isVersionLoading } = useVersion(
    agentId,
    draftVersionId,
    workspaceId,
    { enabled: Boolean(agent && draftVersionId && workspaceId) },
  )

  if (tab === 'chat') {
    return (
      <ChatPanel
        agentId={agentId}
        workspaceId={workspaceId}
        threadId={threadId}
        onThreadChange={(id) => {
          const url = `/agents/${agentId}?tab=chat&thread=${id}`
          window.history.replaceState(null, '', url)
        }}
      />
    )
  }

  if (tab === 'settings') {
    return <AgentSettingsTab agentId={agentId} />
  }

  if (isAgentLoading || (draftVersionId && isVersionLoading)) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
        Agent not found
      </div>
    )
  }

  const surface = resolveBuilderSurface(version?.definition_kind)

  return (
    <BuilderSurfaceContext.Provider value={surface}>
      <AgentBuildShell agent={agent} version={version ?? null} />
    </BuilderSurfaceContext.Provider>
  )
}
```

> **关键变化：** 不再有 `if (isVisualAgent) → AgentStudioShell` 分支。所有 Agent 统一走 `AgentBuildShell`，由 `resolveBuilderSurface` 决定构建内容。删除了 `AgentOverviewTab`、`AgentBuilderTab`、`AgentStudioShell` 的 import。

- [ ] **Step 2: 确认 TypeScript 编译通过**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: 无与 page.tsx 相关的错误（可能有其他文件的错误，暂时忽略）

- [ ] **Step 3: 提交**

```bash
git add frontend/app/agents/[agentId]/page.tsx
git commit -m "refactor: unify agent page entry — all agents go through AgentBuildShell"
```

---

## Task 11: layout.tsx 精简 — 删除 overview/builder tab

**Files:**
- Rewrite: `frontend/app/agents/[agentId]/layout.tsx`

**目标：** 删除 overview 和 builder tab，只保留 Chat 和 Settings 作为辅助入口。Agent 名称 + 返回按钮 + 状态保留在 header。

**依赖：** Task 10

**参考旧文件：** `frontend/app/agents/[agentId]/layout.tsx`（131 行）

- [ ] **Step 1: 重写 layout.tsx**

```tsx
// frontend/app/agents/[agentId]/layout.tsx
'use client'

import { ArrowLeft, Bot, Loader2, MessageSquare, Settings } from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'

import { AgentStatusIndicator } from '@/components/agents/agent-status'
import { Button } from '@/components/ui/button'
import { useAgent } from '@/hooks/queries/agents'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

export default function AgentDetailLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const params = useParams()
  const searchParams = useSearchParams()
  const agentId = params.agentId as string
  const { workspaceId } = useCurrentWorkspace()
  const { data: agent, isLoading } = useAgent(agentId, workspaceId)
  const currentTab = searchParams.get('tab')

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {t('common.loading')}
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-sm text-[var(--text-muted)]">Agent not found</p>
        <Button variant="outline" size="sm" asChild>
          <Link href="/agents">Back to Agents</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-elevated)] px-4 py-2">
        {/* Left: Identity */}
        <div className="flex items-center gap-3 min-w-0">
          <Button variant="ghost" size="sm" asChild className="-ml-2 h-8 w-8 p-0 text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <Link href="/agents">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <Bot className="h-4 w-4 shrink-0 text-[var(--skill-brand-600)]" />
          <h1 className="truncate text-sm font-semibold text-[var(--text-primary)]">
            {agent.name}
          </h1>
          <AgentStatusIndicator status={agent.status} className="shrink-0 scale-75 origin-left" />
        </div>

        {/* Right: Chat + Settings */}
        <div className="flex items-center gap-1">
          <Button
            variant={currentTab === 'chat' ? 'secondary' : 'ghost'}
            size="sm"
            asChild
            className="h-7 px-2 text-xs"
          >
            <Link href={`/agents/${agentId}?tab=chat`}>
              <MessageSquare className="mr-1.5 h-3 w-3" />
              {t('agents.detail.tabs.chat', { defaultValue: 'Chat' })}
            </Link>
          </Button>
          <Button
            variant={currentTab === 'settings' ? 'secondary' : 'ghost'}
            size="sm"
            asChild
            className="h-7 px-2 text-xs"
          >
            <Link href={`/agents/${agentId}?tab=settings`}>
              <Settings className="mr-1.5 h-3 w-3" />
              {t('agents.detail.tabs.settings', { defaultValue: 'Settings' })}
            </Link>
          </Button>
        </div>
      </div>

      <div className={cn('flex-1', currentTab ? 'overflow-y-auto' : 'overflow-hidden')}>
        {children}
      </div>
    </div>
  )
}
```

> **关键变化：** 删除了 overview/builder tab 导航栏，只保留 Chat 和 Settings 按钮。不再有 `tabKeys` 数组和 `hasBuilder` 判断。

- [ ] **Step 2: 提交**

```bash
git add frontend/app/agents/[agentId]/layout.tsx
git commit -m "refactor: simplify agent layout — remove overview/builder tabs, keep chat/settings"
```

---

## Task 12: 清理 — 删除 studio 目录 + 死代码

**Files:**
- Delete: `frontend/components/agents/studio/` (entire directory)
- Delete: `frontend/types/agents.ts`
- Modify: 清理残留 import

**目标：** 删除所有已迁移/废弃的文件，清理残留 import。

**依赖：** Task 6-11（所有新代码已就位）

- [ ] **Step 1: 检查是否还有文件 import studio 目录**

Run: `grep -r "from.*agents/studio" frontend/ --include="*.ts" --include="*.tsx" -l`
Expected: 应该只剩 page.tsx（已在 Task 10 中清理）。如果还有其他文件，需要逐个修复。

- [ ] **Step 2: 检查是否还有文件 import types/agents**

Run: `grep -r "from.*types/agents" frontend/ --include="*.ts" --include="*.tsx" -l`
Expected: 无结果（已确认无 import）

- [ ] **Step 3: 删除 studio 目录**

```bash
rm -rf frontend/components/agents/studio/
```

- [ ] **Step 4: 删除 types/agents.ts**

```bash
rm frontend/types/agents.ts
```

- [ ] **Step 5: 删除旧的 agent-build 测试中不再需要的文件**

检查 `frontend/components/agents/agent-build/__tests__/agent-build-boundaries.test.ts` 是否仍然有效（它检查 agent-build 不 import graph-builder）。如果仍然有效则保留。

Run: `cd frontend && npx vitest run components/agents/agent-build/__tests__/agent-build-boundaries.test.ts`

- [ ] **Step 6: 运行全部测试确认无回归**

Run: `cd frontend && npx vitest run`
Expected: ALL PASS（studio 测试已删除，新测试已就位）

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "refactor: remove studio directory and dead types/agents.ts"
```

---

## Task 13: 全局验证 — TypeScript + 测试 + i18n

**Files:** 无新文件，纯验证

**目标：** 确认整个重构后系统自洽：TypeScript 编译通过、所有测试通过、i18n key 无缺失。

- [ ] **Step 1: TypeScript 全量编译**

Run: `cd frontend && npx tsc --noEmit --pretty`
Expected: 无错误。如果有错误，逐个修复。

- [ ] **Step 2: 全量测试**

Run: `cd frontend && npx vitest run`
Expected: ALL PASS

- [ ] **Step 3: 检查 i18n key 覆盖**

新增的 i18n key（如果有）：
- `agents.build.stages.brief` / `build` / `testLab` / `release` / `usage`
- `agents.build.stageDescriptions.brief` / `build` / `testLab` / `release` / `usage`

检查 en.ts 和 zh.ts 是否已有这些 key。如果缺失，添加到对应的 locale 文件。

Run: `grep -c "agents.build.stages" frontend/lib/i18n/locales/en.ts`

- [ ] **Step 4: 添加缺失的 i18n key（如需要）**

```typescript
// 在 en.ts 的 agents.build 下添加：
stages: {
  brief: 'Goal',
  build: 'Build',
  testLab: 'Test',
  release: 'Release',
  usage: 'Usage',
},
stageDescriptions: {
  brief: 'Define what this Agent should do',
  build: 'Build the Agent logic',
  testLab: 'Test the current draft',
  release: 'Publish and manage releases',
  usage: 'Connect to business scenarios',
},
```

```typescript
// 在 zh.ts 的 agents.build 下添加：
stages: {
  brief: '目标',
  build: '构建',
  testLab: '测试',
  release: '发布',
  usage: '使用',
},
stageDescriptions: {
  brief: '定义 Agent 的目标和行为',
  build: '构建 Agent 逻辑',
  testLab: '测试当前草稿',
  release: '发布和管理版本',
  usage: '接入业务场景',
},
```

- [ ] **Step 5: 再次全量编译 + 测试**

Run: `cd frontend && npx tsc --noEmit --pretty && npx vitest run`
Expected: ALL PASS

- [ ] **Step 6: 最终提交**

```bash
git add -A
git commit -m "chore: add i18n keys for build stages and verify full compilation"
```
