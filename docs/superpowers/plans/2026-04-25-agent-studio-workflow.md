# Agent Studio Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Visual Agent frontend into a single Agent Studio workflow where users move from Brief to Canvas, Test Lab, Release, and Usage without confusing Copilot, draft testing, published chat, and business runs.

**Architecture:** This is a frontend-first refactor that reuses existing Agent, AgentVersion, AgentRelease, Copilot, and execution APIs. `/agents/:agentId` becomes the type-aware Agent workspace; Visual Agents render an Agent Studio shell with stage navigation. Graph Builder internals are incrementally reorganized so Canvas owns node adding and the right panel owns Copilot or Inspector.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS, Radix UI, React Query, Zustand, React Flow, Vitest, Bun

**Spec:** `docs/superpowers/specs/2026-04-25-agent-studio-workflow-design.md`

---

## Scope

This plan implements the Visual Agent Studio frontend flow. It does not add new backend tables or replace the AgentVersion/AgentRelease model.

The first implementation should support:

- Visual Agents default into Studio instead of the generic Overview tab.
- Studio has stable stage navigation: `Brief`, `Canvas`, `Test Lab`, `Release`, `Usage`.
- Empty Visual Agents start at `Brief`; existing Visual Agents start at `Canvas`.
- Canvas keeps React Flow as the main workspace.
- Copilot and Components stop competing as right-side tabs.
- Node adding is available from toolbar palette and canvas context menu.
- Draft test execution is presented as Test Lab, while published chat remains Usage.
- Release and Usage reuse existing release, chat, task, and execution hooks.

## File Structure

### New Files

| File | Responsibility |
| --- | --- |
| `frontend/components/agents/studio/agent-studio-shell.tsx` | Top-level Visual Agent Studio layout, stage routing, stage state |
| `frontend/components/agents/studio/studio-top-bar.tsx` | Agent name, draft/published status, next action |
| `frontend/components/agents/studio/studio-stage-nav.tsx` | Left rail stage navigation |
| `frontend/components/agents/studio/studio-brief-stage.tsx` | Structured first-run brief form that sends prompt to Copilot via `copilotInput` |
| `frontend/components/agents/studio/studio-canvas-stage.tsx` | Canvas stage wrapper around refactored `AgentBuilder` |
| `frontend/components/agents/studio/studio-test-lab-stage.tsx` | Draft test surface reusing builder execution panel |
| `frontend/components/agents/studio/studio-release-stage.tsx` | Version/release history and publish/activate actions |
| `frontend/components/agents/studio/studio-usage-stage.tsx` | Published usage entry points: Chat, Task, API, recent business runs |
| `frontend/components/agents/studio/studio-types.ts` | Shared Studio stage types and helpers |
| `frontend/components/agents/studio/__tests__/studio-stage-selection.test.ts` | Unit tests for stage selection helpers |
| `frontend/components/editors/graph-builder/components/StudioRightPanel.tsx` | Right panel controller: Copilot, node inspector, edge inspector |
| `frontend/components/editors/graph-builder/components/AddNodePalette.tsx` | Searchable node palette that reuses `nodeRegistry` |
| `frontend/components/editors/graph-builder/components/CanvasContextMenu.tsx` | Canvas right-click Add Node menu |
| `frontend/components/editors/graph-builder/components/__tests__/add-node-palette.test.tsx` | Palette filtering/selection tests |

### Modified Files

| File | Change |
| --- | --- |
| `frontend/app/agents/[agentId]/page.tsx` | Route Visual Agents to Studio; keep prompt/code/generic fallback behavior |
| `frontend/components/agents/agent-overview-tab.tsx` | Update quick action copy from Builder to Studio if still used for non-Visual Agents |
| `frontend/components/agents/agent-builder-tab.tsx` | Either remove as primary route or make it a thin wrapper around Canvas stage |
| `frontend/components/editors/graph-builder/AgentBuilder.tsx` | Accept Studio props, remove hard dependency on `BuilderSidebarTabs`, expose canvas/test/right-panel composition |
| `frontend/components/editors/graph-builder/components/BuilderCanvas.tsx` | Add context menu position handling, remove floating properties panels when right panel owns Inspector |
| `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx` | Add `+ Add` button/palette trigger; rename run action to Run Draft when in Studio |
| `frontend/components/editors/graph-builder/components/ComponentsSidebar.tsx` | Reuse as palette content or keep only as legacy advanced drag source |
| `frontend/components/editors/graph-builder/components/BuilderSidebarTabs.tsx` | Deprecate; replace usage with `StudioRightPanel` |
| `frontend/components/editors/graph-builder/components/PropertiesPanel.tsx` | Add embedded mode so it can render inside the right panel without absolute positioning |
| `frontend/components/editors/graph-builder/components/EdgePropertiesPanel.tsx` | Add embedded mode so it can render inside the right panel without absolute positioning |
| `frontend/lib/i18n/locales/en.ts` | Add Agent Studio terminology |
| `frontend/lib/i18n/locales/zh.ts` | Add Agent Studio terminology |

### Existing APIs Reused

| API/Hook | Usage |
| --- | --- |
| `useAgent`, `useVersionGraphState`, `useVersion` | Determine Visual Agent type, draft state, empty graph state |
| `useVersions`, `useReleases`, `usePublishRelease`, `useActivateRelease` | Release stage |
| `useAgentRuns` | Usage recent business runs |
| `ChatPanel` | Usage stage published Agent chat |
| `CopilotPanel` and `copilotInput` query param | Brief handoff to existing Copilot pipeline |
| `useExecutionStore.startExecution` | Test Lab draft-style run UI in first frontend iteration |

## Task 1: Stage Model and Studio Shell

**Files:**
- Create: `frontend/components/agents/studio/studio-types.ts`
- Create: `frontend/components/agents/studio/__tests__/studio-stage-selection.test.ts`
- Create: `frontend/components/agents/studio/studio-stage-nav.tsx`
- Create: `frontend/components/agents/studio/studio-top-bar.tsx`
- Create: `frontend/components/agents/studio/agent-studio-shell.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] **Step 1: Create failing unit tests for stage helpers**

Create `frontend/components/agents/studio/__tests__/studio-stage-selection.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import {
  AGENT_STUDIO_STAGES,
  getDefaultStudioStage,
  isStudioStage,
  normalizeStudioStage,
} from '../studio-types'

describe('Agent Studio stage helpers', () => {
  it('defines the Visual Agent stage order', () => {
    expect(AGENT_STUDIO_STAGES.map((stage) => stage.id)).toEqual([
      'brief',
      'canvas',
      'test-lab',
      'release',
      'usage',
    ])
  })

  it('uses brief as the default for an empty graph', () => {
    expect(getDefaultStudioStage({ nodesCount: 0, hasActiveRelease: false })).toBe('brief')
  })

  it('uses canvas as the default when graph nodes already exist', () => {
    expect(getDefaultStudioStage({ nodesCount: 2, hasActiveRelease: false })).toBe('canvas')
  })

  it('normalizes unknown stage values to the computed default', () => {
    expect(normalizeStudioStage('unknown', { nodesCount: 1, hasActiveRelease: true })).toBe('canvas')
  })

  it('recognizes only known stage ids', () => {
    expect(isStudioStage('release')).toBe(true)
    expect(isStudioStage('versions')).toBe(false)
  })
})
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
cd frontend && bun run test -- components/agents/studio/__tests__/studio-stage-selection.test.ts
```

Expected: fails because `studio-types.ts` does not exist.

- [ ] **Step 3: Implement `studio-types.ts`**

Create `frontend/components/agents/studio/studio-types.ts`:

```typescript
import {
  FileText,
  GitBranch,
  LayoutDashboard,
  LucideIcon,
  PlayCircle,
  Rocket,
} from 'lucide-react'

export type AgentStudioStage = 'brief' | 'canvas' | 'test-lab' | 'release' | 'usage'

export interface AgentStudioStageConfig {
  id: AgentStudioStage
  labelKey: string
  descriptionKey: string
  icon: LucideIcon
}

export const AGENT_STUDIO_STAGES: readonly AgentStudioStageConfig[] = [
  {
    id: 'brief',
    labelKey: 'agents.studio.stages.brief',
    descriptionKey: 'agents.studio.stageDescriptions.brief',
    icon: FileText,
  },
  {
    id: 'canvas',
    labelKey: 'agents.studio.stages.canvas',
    descriptionKey: 'agents.studio.stageDescriptions.canvas',
    icon: GitBranch,
  },
  {
    id: 'test-lab',
    labelKey: 'agents.studio.stages.testLab',
    descriptionKey: 'agents.studio.stageDescriptions.testLab',
    icon: PlayCircle,
  },
  {
    id: 'release',
    labelKey: 'agents.studio.stages.release',
    descriptionKey: 'agents.studio.stageDescriptions.release',
    icon: Rocket,
  },
  {
    id: 'usage',
    labelKey: 'agents.studio.stages.usage',
    descriptionKey: 'agents.studio.stageDescriptions.usage',
    icon: LayoutDashboard,
  },
]

const STAGE_IDS = new Set<AgentStudioStage>(AGENT_STUDIO_STAGES.map((stage) => stage.id))

export function isStudioStage(value: string | null | undefined): value is AgentStudioStage {
  return Boolean(value && STAGE_IDS.has(value as AgentStudioStage))
}

export function getDefaultStudioStage({
  nodesCount,
}: {
  nodesCount: number
  hasActiveRelease: boolean
}): AgentStudioStage {
  return nodesCount === 0 ? 'brief' : 'canvas'
}

export function normalizeStudioStage(
  value: string | null | undefined,
  context: { nodesCount: number; hasActiveRelease: boolean },
): AgentStudioStage {
  return isStudioStage(value) ? value : getDefaultStudioStage(context)
}
```

- [ ] **Step 4: Re-run the focused test and verify it passes**

Run:

```bash
cd frontend && bun run test -- components/agents/studio/__tests__/studio-stage-selection.test.ts
```

Expected: pass.

- [ ] **Step 5: Create `studio-stage-nav.tsx`**

Create `frontend/components/agents/studio/studio-stage-nav.tsx`:

```tsx
'use client'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

import { AGENT_STUDIO_STAGES, type AgentStudioStage } from './studio-types'

interface StudioStageNavProps {
  activeStage: AgentStudioStage
  onStageChange: (stage: AgentStudioStage) => void
}

export function StudioStageNav({ activeStage, onStageChange }: StudioStageNavProps) {
  const { t } = useTranslation()

  return (
    <nav className="flex h-full w-52 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-2)] px-3 py-4">
      <div className="mb-4 px-2">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
          {t('agents.studio.title', { defaultValue: 'Agent Studio' })}
        </p>
      </div>

      <div className="space-y-1">
        {AGENT_STUDIO_STAGES.map((stage) => {
          const Icon = stage.icon
          const active = stage.id === activeStage
          return (
            <button
              key={stage.id}
              type="button"
              onClick={() => onStageChange(stage.id)}
              className={cn(
                'flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors',
                active
                  ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm'
                  : 'text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]',
              )}
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="min-w-0">
                <span className="block text-sm font-semibold">
                  {t(stage.labelKey)}
                </span>
                <span className="mt-0.5 block text-xs leading-snug text-[var(--text-muted)]">
                  {t(stage.descriptionKey)}
                </span>
              </span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
```

- [ ] **Step 6: Create `studio-top-bar.tsx`**

Create `frontend/components/agents/studio/studio-top-bar.tsx`:

```tsx
'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import type { Agent } from '@/types/agent'

import type { AgentStudioStage } from './studio-types'

interface StudioTopBarProps {
  agent: Agent
  activeStage: AgentStudioStage
  nodesCount: number
  hasPendingChanges?: boolean
  onPrimaryAction: () => void
}

export function StudioTopBar({
  agent,
  activeStage,
  nodesCount,
  hasPendingChanges = false,
  onPrimaryAction,
}: StudioTopBarProps) {
  const { t } = useTranslation()
  const hasRelease = Boolean(agent.active_release_id)

  const actionLabel =
    activeStage === 'brief'
      ? t('agents.studio.actions.generateDraft', { defaultValue: 'Generate Draft' })
      : activeStage === 'canvas'
        ? t('agents.studio.actions.runDraft', { defaultValue: 'Run Draft' })
        : activeStage === 'test-lab'
          ? t('agents.studio.actions.publish', { defaultValue: 'Publish' })
          : activeStage === 'release'
            ? t('agents.studio.actions.openUsage', { defaultValue: 'Open Usage' })
            : t('agents.studio.actions.createTask', { defaultValue: 'Create Task' })

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4">
      <div className="flex min-w-0 items-center gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold text-[var(--text-primary)]">
            {agent.name}
          </h1>
          <p className="truncate text-xs text-[var(--text-muted)]">
            {t('agents.studio.visualAgent', { defaultValue: 'Visual Agent' })}
          </p>
        </div>
        <Badge variant="outline">
          {nodesCount === 0
            ? t('agents.studio.status.emptyDraft', { defaultValue: 'Empty draft' })
            : hasPendingChanges
              ? t('agents.studio.status.unsavedDraft', { defaultValue: 'Draft changed' })
              : t('agents.studio.status.savedDraft', { defaultValue: 'Draft saved' })}
        </Badge>
        <Badge variant={hasRelease ? 'default' : 'outline'}>
          {hasRelease
            ? t('agents.studio.status.published', { defaultValue: 'Published' })
            : t('agents.studio.status.notPublished', { defaultValue: 'Not published' })}
        </Badge>
      </div>

      <Button size="sm" onClick={onPrimaryAction}>
        {actionLabel}
      </Button>
    </header>
  )
}
```

- [ ] **Step 7: Create initial Studio shell with stage overview content**

Create `frontend/components/agents/studio/agent-studio-shell.tsx`:

```tsx
'use client'

import { useCallback, useMemo, useState } from 'react'

import { useTranslation } from '@/lib/i18n'
import type { Agent } from '@/types/agent'

import { StudioStageNav } from './studio-stage-nav'
import { StudioTopBar } from './studio-top-bar'
import {
  getDefaultStudioStage,
  normalizeStudioStage,
  type AgentStudioStage,
} from './studio-types'

interface AgentStudioShellProps {
  agent: Agent
  initialStage?: string | null
  nodesCount: number
  hasPendingChanges?: boolean
}

export function AgentStudioShell({
  agent,
  initialStage,
  nodesCount,
  hasPendingChanges,
}: AgentStudioShellProps) {
  const { t } = useTranslation()
  const defaultStage = useMemo(
    () => getDefaultStudioStage({ nodesCount, hasActiveRelease: Boolean(agent.active_release_id) }),
    [agent.active_release_id, nodesCount],
  )
  const [activeStage, setActiveStage] = useState<AgentStudioStage>(
    normalizeStudioStage(initialStage, {
      nodesCount,
      hasActiveRelease: Boolean(agent.active_release_id),
    }),
  )

  const handlePrimaryAction = useCallback(() => {
    if (activeStage === 'brief') setActiveStage('canvas')
    else if (activeStage === 'canvas') setActiveStage('test-lab')
    else if (activeStage === 'test-lab') setActiveStage('release')
    else if (activeStage === 'release') setActiveStage('usage')
  }, [activeStage])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--bg)] text-[var(--text-primary)]">
      <StudioTopBar
        agent={agent}
        activeStage={activeStage}
        nodesCount={nodesCount}
        hasPendingChanges={hasPendingChanges}
        onPrimaryAction={handlePrimaryAction}
      />
      <div className="flex min-h-0 flex-1">
        <StudioStageNav activeStage={activeStage} onStageChange={setActiveStage} />
        <main className="min-w-0 flex-1 overflow-hidden">
          <div className="flex h-full items-center justify-center p-8 text-center">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
                {t('agents.studio.title', { defaultValue: 'Agent Studio' })}
              </p>
              <h2 className="mt-2 text-2xl font-semibold">{activeStage}</h2>
              <p className="mt-2 text-sm text-[var(--text-muted)]">
                {t('agents.studio.stageOverview', {
                  defaultValue: `Current stage: ${activeStage}. Default stage: ${defaultStage}`,
                })}
              </p>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
```

- [ ] **Step 8: Add i18n keys**

Add these keys under the existing `agents.detail` adjacent namespace in both `frontend/lib/i18n/locales/en.ts` and `frontend/lib/i18n/locales/zh.ts`. If the file is a nested object, add the `studio` object under `agents`.

English values:

```typescript
studio: {
  title: 'Agent Studio',
  visualAgent: 'Visual Agent',
  stageOverview: 'Current stage: {{activeStage}}. Default stage: {{defaultStage}}',
  stages: {
    brief: 'Brief',
    canvas: 'Canvas',
    testLab: 'Test Lab',
    release: 'Release',
    usage: 'Usage',
  },
  stageDescriptions: {
    brief: 'Define the goal',
    canvas: 'Build the workflow',
    testLab: 'Run the draft',
    release: 'Publish safely',
    usage: 'Use in business',
  },
  actions: {
    generateDraft: 'Generate Draft',
    runDraft: 'Run Draft',
    publish: 'Publish',
    openUsage: 'Open Usage',
    createTask: 'Create Task',
  },
  status: {
    emptyDraft: 'Empty draft',
    unsavedDraft: 'Draft changed',
    savedDraft: 'Draft saved',
    published: 'Published',
    notPublished: 'Not published',
  },
}
```

Chinese values:

```typescript
studio: {
  title: 'Agent Studio',
  visualAgent: 'Visual Agent',
  stageOverview: '当前阶段：{{activeStage}}。默认阶段：{{defaultStage}}',
  stages: {
    brief: '需求',
    canvas: '编排',
    testLab: '测试',
    release: '发布',
    usage: '使用',
  },
  stageDescriptions: {
    brief: '定义目标',
    canvas: '构建流程',
    testLab: '运行草稿',
    release: '安全发布',
    usage: '接入业务',
  },
  actions: {
    generateDraft: '生成草稿',
    runDraft: '运行草稿',
    publish: '发布',
    openUsage: '打开使用',
    createTask: '创建任务',
  },
  status: {
    emptyDraft: '空草稿',
    unsavedDraft: '草稿已变更',
    savedDraft: '草稿已保存',
    published: '已发布',
    notPublished: '未发布',
  },
}
```

- [ ] **Step 9: Run focused test and type-check**

Run:

```bash
cd frontend && bun run test -- components/agents/studio/__tests__/studio-stage-selection.test.ts
cd frontend && bun run type-check
```

Expected: test passes and type-check passes.

- [ ] **Step 10: Commit**

```bash
git add frontend/components/agents/studio frontend/lib/i18n/locales
git commit -m "feat: add Agent Studio shell and stage model"
```

## Task 2: Route Visual Agents Into Studio

**Files:**
- Modify: `frontend/app/agents/[agentId]/page.tsx`
- Modify: `frontend/components/agents/agent-overview-tab.tsx`
- Modify: `frontend/components/agents/agent-builder-tab.tsx`
- Test: `frontend/components/agents/studio/__tests__/studio-stage-selection.test.ts`

- [ ] **Step 1: Extend stage helper tests for URL stage values**

Append this test to `frontend/components/agents/studio/__tests__/studio-stage-selection.test.ts`:

```typescript
it('accepts test-lab from URL stage values', () => {
  expect(normalizeStudioStage('test-lab', { nodesCount: 0, hasActiveRelease: false })).toBe(
    'test-lab',
  )
})
```

- [ ] **Step 2: Run focused test**

Run:

```bash
cd frontend && bun run test -- components/agents/studio/__tests__/studio-stage-selection.test.ts
```

Expected: pass.

- [ ] **Step 3: Update `AgentDetailPage` to route graph Agents to Studio**

Modify `frontend/app/agents/[agentId]/page.tsx` so graph/visual Agents render `AgentStudioShell` by default.

Use this complete component shape:

```tsx
'use client'

import { Loader2 } from 'lucide-react'
import { useParams, useSearchParams, useRouter } from 'next/navigation'

import { AgentBuilderTab } from '@/components/agents/agent-builder-tab'
import { AgentOverviewTab } from '@/components/agents/agent-overview-tab'
import { AgentSettingsTab } from '@/components/agents/agent-settings-tab'
import { AgentStudioShell } from '@/components/agents/studio/agent-studio-shell'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { useVersionGraphState } from '@/hooks/queries/agentVersions'
import { useAgent } from '@/hooks/queries/agents'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

export default function AgentDetailPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const router = useRouter()
  const agentId = params.agentId as string
  const tab = searchParams.get('tab')
  const stage = searchParams.get('stage')
  const threadId = searchParams.get('thread') || undefined
  const { workspaceId } = useCurrentWorkspace()

  const { data: agent, isLoading: isAgentLoading } = useAgent(agentId, workspaceId)
  const draftVersionId = agent?.current_draft_version_id || undefined
  const { data: graphStateData, isLoading: isGraphLoading } = useVersionGraphState(
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
        onThreadChange={(id) => router.push(`/agents/${agentId}?tab=chat&thread=${id}`)}
      />
    )
  }

  if (tab === 'settings') {
    return <AgentSettingsTab agentId={agentId} />
  }

  if (tab === 'builder') {
    return <AgentBuilderTab agentId={agentId} />
  }

  if (isAgentLoading || (agent && draftVersionId && isGraphLoading)) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
      </div>
    )
  }

  if (!agent) {
    return <AgentOverviewTab agentId={agentId} />
  }

  const isVisualAgent = graphStateData?.definitionKind === 'graph'

  if (isVisualAgent) {
    return (
      <AgentStudioShell
        agent={agent}
        initialStage={stage}
        nodesCount={graphStateData?.nodes?.length ?? 0}
      />
    )
  }

  return <AgentOverviewTab agentId={agentId} />
}
```

- [ ] **Step 4: Update Overview quick action copy**

In `frontend/components/agents/agent-overview-tab.tsx`, change quick action text:

```typescript
{t('agents.detail.openBuilder', { defaultValue: 'Open Studio' })}
{t('agents.detail.openBuilderDesc', { defaultValue: 'Build, test, publish, and use this Agent' })}
```

Change the href from:

```tsx
href={`/agents/${agentId}?tab=builder`}
```

to:

```tsx
href={`/agents/${agentId}?stage=canvas`}
```

- [ ] **Step 5: Keep `AgentBuilderTab` as a compatibility wrapper**

Leave `frontend/components/agents/agent-builder-tab.tsx` in place. Add a top comment:

```typescript
// Compatibility wrapper for legacy ?tab=builder links. Visual Agents now use AgentStudioShell by default.
```

- [ ] **Step 6: Run type-check**

Run:

```bash
cd frontend && bun run type-check
```

Expected: pass.

- [ ] **Step 7: Manual verification**

Run:

```bash
cd frontend && bun run dev
```

Expected:

- `/agents/:agentId` for a graph draft opens Agent Studio.
- `/agents/:agentId?stage=test-lab` selects the Test Lab stage overview.
- `/agents/:agentId?tab=chat` still opens published Agent Chat.
- `/agents/:agentId?tab=settings` still opens Settings.
- `/agents/:agentId?tab=builder` still opens the legacy builder wrapper.

- [ ] **Step 8: Commit**

```bash
git add 'frontend/app/agents/[agentId]/page.tsx' frontend/components/agents frontend/components/agents/studio
git commit -m "feat: route Visual Agents into Agent Studio"
```

## Task 3: Implement Brief and Canvas Stage Wrappers

**Files:**
- Create: `frontend/components/agents/studio/studio-brief-stage.tsx`
- Create: `frontend/components/agents/studio/studio-canvas-stage.tsx`
- Modify: `frontend/components/agents/studio/agent-studio-shell.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] **Step 1: Create Brief stage component**

Create `frontend/components/agents/studio/studio-brief-stage.tsx`:

```tsx
'use client'

import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import type { Agent } from '@/types/agent'

interface StudioBriefStageProps {
  agent: Agent
  onGenerate: (prompt: string) => void
  onSkipToCanvas: () => void
}

export function StudioBriefStage({ agent, onGenerate, onSkipToCanvas }: StudioBriefStageProps) {
  const { t } = useTranslation()
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

  return (
    <div className="h-full overflow-y-auto bg-[var(--surface-1)]">
      <div className="mx-auto max-w-4xl px-8 py-8">
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
            <Textarea value={goal} onChange={(event) => setGoal(event.target.value)} rows={3} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>{t('agents.studio.brief.input', { defaultValue: 'Input' })}</Label>
              <Input value={input} onChange={(event) => setInput(event.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>{t('agents.studio.brief.output', { defaultValue: 'Output' })}</Label>
              <Input value={output} onChange={(event) => setOutput(event.target.value)} />
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.tools', { defaultValue: 'Tools / Skills' })}</Label>
            <Input value={tools} onChange={(event) => setTools(event.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.constraints', { defaultValue: 'Safety / approval rules' })}</Label>
            <Textarea
              value={constraints}
              onChange={(event) => setConstraints(event.target.value)}
              rows={2}
            />
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.scenario', { defaultValue: 'Business scenario' })}</Label>
            <Input value={scenario} onChange={(event) => setScenario(event.target.value)} />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onSkipToCanvas}>
              {t('agents.studio.brief.skip', { defaultValue: 'Build manually' })}
            </Button>
            <Button onClick={() => onGenerate(prompt)} disabled={!goal.trim()}>
              {t('agents.studio.brief.generate', { defaultValue: 'Generate with Copilot' })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create Canvas stage wrapper**

Create `frontend/components/agents/studio/studio-canvas-stage.tsx`:

```tsx
'use client'

import AgentBuilder from '@/components/editors/graph-builder/AgentBuilder'

interface StudioCanvasStageProps {
  agentId: string
  workspaceId: string
  versionId?: string
  onOpenTestLab: () => void
  onOpenRelease: () => void
}

export function StudioCanvasStage({
  agentId,
  workspaceId,
  versionId,
  onOpenTestLab,
  onOpenRelease,
}: StudioCanvasStageProps) {
  return (
    <AgentBuilder
      workspaceId={workspaceId}
      agentId={agentId}
      versionId={versionId}
      studioMode
      onOpenTestLab={onOpenTestLab}
      onOpenRelease={onOpenRelease}
    />
  )
}
```

- [ ] **Step 3: Update `AgentBuilder` props for Studio mode**

In `frontend/components/editors/graph-builder/AgentBuilder.tsx`, extend `AgentBuilderContentProps`:

```typescript
interface AgentBuilderContentProps {
  workspaceIdProp?: string
  agentIdProp?: string
  versionIdProp?: string
  studioMode?: boolean
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
}
```

Pass these through from the exported `AgentBuilder` component:

```typescript
interface AgentBuilderProps {
  workspaceId?: string
  agentId?: string
  versionId?: string
  studioMode?: boolean
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
}
```

Update the exported component call:

```tsx
const AgentBuilder = ({
  workspaceId,
  agentId: agentIdProp,
  versionId,
  studioMode = false,
  onOpenTestLab,
  onOpenRelease,
}: AgentBuilderProps = {}) => (
  <ReactFlowProvider>
    <AgentBuilderContent
      workspaceIdProp={workspaceId}
      agentIdProp={agentIdProp}
      versionIdProp={versionId}
      studioMode={studioMode}
      onOpenTestLab={onOpenTestLab}
      onOpenRelease={onOpenRelease}
    />
  </ReactFlowProvider>
)
```

Do not change layout behavior yet in this task.

- [ ] **Step 4: Wire Brief and Canvas into shell**

Modify `frontend/components/agents/studio/agent-studio-shell.tsx`:

Add imports:

```typescript
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import { useRouter } from 'next/navigation'
import { StudioBriefStage } from './studio-brief-stage'
import { StudioCanvasStage } from './studio-canvas-stage'
```

Inside the component:

```typescript
const router = useRouter()
const { workspaceId } = useCurrentWorkspace()
```

Add:

```typescript
const handleGenerateFromBrief = useCallback(
  (prompt: string) => {
    setActiveStage('canvas')
    const encoded = encodeURIComponent(prompt)
    router.replace(`/agents/${agent.id}?stage=canvas&copilotInput=${encoded}`, { scroll: false })
  },
  [agent.id, router],
)
```

Replace the initial stage overview `<main>` content with:

```tsx
<main className="min-w-0 flex-1 overflow-hidden">
  {activeStage === 'brief' && (
    <StudioBriefStage
      agent={agent}
      onGenerate={handleGenerateFromBrief}
      onSkipToCanvas={() => setActiveStage('canvas')}
    />
  )}
  {activeStage === 'canvas' && (
    <StudioCanvasStage
      agentId={agent.id}
      workspaceId={workspaceId}
      versionId={agent.current_draft_version_id || undefined}
      onOpenTestLab={() => setActiveStage('test-lab')}
      onOpenRelease={() => setActiveStage('release')}
    />
  )}
  {activeStage !== 'brief' && activeStage !== 'canvas' && (
    <div className="flex h-full items-center justify-center p-8 text-center">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
          {t('agents.studio.title', { defaultValue: 'Agent Studio' })}
        </p>
        <h2 className="mt-2 text-2xl font-semibold">{activeStage}</h2>
      </div>
    </div>
  )}
</main>
```

- [ ] **Step 5: Add Brief i18n keys**

Add under `agents.studio.brief` in `en.ts`:

```typescript
brief: {
  kicker: 'First build step',
  title: 'Describe the Agent you want to build',
  subtitle: 'Copilot will turn this brief into an editable visual workflow. You can still skip and build manually on the canvas.',
  goal: 'Goal',
  input: 'Input',
  output: 'Output',
  tools: 'Tools / Skills',
  constraints: 'Safety / approval rules',
  scenario: 'Business scenario',
  skip: 'Build manually',
  generate: 'Generate with Copilot',
}
```

Add matching `zh.ts` keys:

```typescript
brief: {
  kicker: '第一步',
  title: '描述你想打造的 Agent',
  subtitle: 'Copilot 会把需求转换成可编辑的可视化流程。你也可以跳过并直接在画布上手动构建。',
  goal: '目标',
  input: '输入',
  output: '输出',
  tools: '工具 / Skills',
  constraints: '安全 / 审批规则',
  scenario: '业务场景',
  skip: '手动构建',
  generate: '用 Copilot 生成',
}
```

- [ ] **Step 6: Run type-check**

Run:

```bash
cd frontend && bun run type-check
```

Expected: pass.

- [ ] **Step 7: Manual verification**

Run:

```bash
cd frontend && bun run dev
```

Expected:

- Empty graph Visual Agent opens Brief.
- `Build manually` switches to Canvas.
- `Generate with Copilot` switches to Canvas and adds `copilotInput` to the URL.
- Existing Copilot auto-send behavior consumes `copilotInput`.

- [ ] **Step 8: Commit**

```bash
git add frontend/components/agents/studio frontend/components/editors/graph-builder/AgentBuilder.tsx frontend/lib/i18n/locales
git commit -m "feat: add Brief and Canvas stages to Agent Studio"
```

## Task 4: Replace Builder Right Tabs With Copilot/Inspector Controller

**Files:**
- Create: `frontend/components/editors/graph-builder/components/StudioRightPanel.tsx`
- Modify: `frontend/components/editors/graph-builder/components/PropertiesPanel.tsx`
- Modify: `frontend/components/editors/graph-builder/components/EdgePropertiesPanel.tsx`
- Modify: `frontend/components/editors/graph-builder/AgentBuilder.tsx`
- Modify: `frontend/components/editors/graph-builder/components/BuilderSidebarTabs.tsx`

- [ ] **Step 1: Add embedded mode to `PropertiesPanel`**

In `frontend/components/editors/graph-builder/components/PropertiesPanel.tsx`, extend props:

```typescript
interface PropertiesPanelProps {
  node: Node
  nodes: Node[]
  edges: Edge[]
  onUpdate: (id: string, data: { label: string; config?: Record<string, unknown> }) => void
  onClose: () => void
  embedded?: boolean
}
```

Update function signature:

```typescript
export default function PropertiesPanel({
  node,
  nodes,
  edges,
  onUpdate,
  onClose,
  embedded = false,
}: PropertiesPanelProps) {
```

Replace the root `className` string with conditional layout:

```tsx
<div
  className={cn(
    'flex flex-col overflow-hidden bg-[var(--surface-1)]',
    embedded
      ? 'h-full'
      : 'absolute bottom-[60px] right-[336px] top-[56px] z-50 w-[400px] rounded-2xl border border-[var(--border)] shadow-2xl duration-300 animate-in fade-in slide-in-from-right-10',
  )}
>
```

- [ ] **Step 2: Add embedded mode to `EdgePropertiesPanel`**

In `frontend/components/editors/graph-builder/components/EdgePropertiesPanel.tsx`, extend props:

```typescript
embedded?: boolean
```

Update function signature with `embedded = false`.

Change the outer wrapper from fragment to:

```tsx
return (
  <>
    <div
      className={
        embedded
          ? 'flex h-full flex-col overflow-hidden bg-[var(--surface-1)]'
          : 'absolute right-4 top-16 z-50 w-72 rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] shadow-xl'
      }
    >
```

Keep the delete confirmation dialog unchanged.

- [ ] **Step 3: Create `StudioRightPanel.tsx`**

Create `frontend/components/editors/graph-builder/components/StudioRightPanel.tsx`:

```tsx
'use client'

import { Settings2, Sparkles } from 'lucide-react'

import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'

import { useBuilderStore } from '../stores/builderStore'
import { CopilotPanel } from './CopilotPanel'
import { EdgePropertiesPanel } from './EdgePropertiesPanel'
import PropertiesPanel from './PropertiesPanel'

export function StudioRightPanel() {
  const { t } = useTranslation()
  const { toast } = useToast()
  const userPermissions = useUserPermissionsContext()
  const {
    nodes,
    edges,
    selectedNodeId,
    selectedEdgeId,
    updateNodeConfig,
    updateNodeLabel,
    updateEdge,
    onEdgesChange,
    selectNode,
    selectEdge,
    takeSnapshot,
  } = useBuilderStore()

  const selectedNode = nodes.find((node) => node.id === selectedNodeId)
  const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId)

  const denyEdit = () =>
    toast({
      title: t('workspace.noPermission'),
      description: t('workspace.cannotEditNode'),
      variant: 'destructive',
    })

  if (selectedNode) {
    return (
      <section className="flex h-full min-h-0 flex-col bg-[var(--surface-1)]">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3">
          <Settings2 size={15} />
          <span className="text-sm font-semibold">
            {t('agents.studio.rightPanel.inspector', { defaultValue: 'Inspector' })}
          </span>
        </div>
        <PropertiesPanel
          embedded
          node={selectedNode}
          nodes={nodes}
          edges={edges}
          onUpdate={(id, data) => {
            if (!userPermissions.canEdit) {
              denyEdit()
              return
            }
            takeSnapshot()
            const nodeData = selectedNode.data as { label?: string }
            if (data.label !== nodeData.label) updateNodeLabel(id, data.label)
            if (data.config) updateNodeConfig(id, data.config)
          }}
          onClose={() => selectNode(null)}
        />
      </section>
    )
  }

  if (selectedEdge) {
    return (
      <section className="flex h-full min-h-0 flex-col bg-[var(--surface-1)]">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3">
          <Settings2 size={15} />
          <span className="text-sm font-semibold">
            {t('agents.studio.rightPanel.edgeInspector', { defaultValue: 'Edge Inspector' })}
          </span>
        </div>
        <EdgePropertiesPanel
          embedded
          edge={selectedEdge}
          nodes={nodes}
          edges={edges}
          onUpdate={(id, data) => {
            if (!userPermissions.canEdit) {
              denyEdit()
              return
            }
            takeSnapshot()
            updateEdge(id, data)
          }}
          onDelete={(id) => {
            if (!userPermissions.canEdit) {
              denyEdit()
              return
            }
            takeSnapshot()
            onEdgesChange([{ type: 'remove', id }])
            selectEdge(null)
          }}
          onClose={() => selectEdge(null)}
        />
      </section>
    )
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--surface-2)]">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3">
        <Sparkles size={15} />
        <span className="text-sm font-semibold">
          {t('agents.studio.rightPanel.copilot', { defaultValue: 'Copilot Builder' })}
        </span>
      </div>
      <div className="min-h-0 flex-1">
        <CopilotPanel />
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Remove floating panels from `BuilderCanvas` when Studio owns them**

Extend `BuilderCanvas` props:

```typescript
interface BuilderCanvasProps {
  inspectorMode?: 'floating' | 'external'
}

export function BuilderCanvas({ inspectorMode = 'floating' }: BuilderCanvasProps) {
```

Wrap the existing `PropertiesPanel` and `EdgePropertiesPanel` render blocks:

```tsx
{inspectorMode === 'floating' && selectedNode && (...)}
{inspectorMode === 'floating' && selectedEdgeId && (...)}
```

- [ ] **Step 5: Use `StudioRightPanel` in Studio mode**

In `frontend/components/editors/graph-builder/AgentBuilder.tsx`, import:

```typescript
import { StudioRightPanel } from './components/StudioRightPanel'
```

Change `BuilderCanvas` render:

```tsx
<BuilderCanvas key={agentId || 'empty'} inspectorMode={studioMode ? 'external' : 'floating'} />
```

Change sidebar content:

```tsx
{studioMode ? <StudioRightPanel /> : <BuilderSidebarTabs />}
```

- [ ] **Step 6: Mark `BuilderSidebarTabs` as legacy**

At the top of `frontend/components/editors/graph-builder/components/BuilderSidebarTabs.tsx`, add:

```typescript
// Legacy non-Studio sidebar. Studio mode uses StudioRightPanel so Copilot and Components are no longer equal tabs.
```

- [ ] **Step 7: Add right panel i18n keys**

Add in both locale files:

```typescript
rightPanel: {
  copilot: 'Copilot Builder',
  inspector: 'Inspector',
  edgeInspector: 'Edge Inspector',
}
```

Chinese:

```typescript
rightPanel: {
  copilot: 'Copilot 构建助手',
  inspector: '属性面板',
  edgeInspector: '连线属性',
}
```

- [ ] **Step 8: Run type-check**

Run:

```bash
cd frontend && bun run type-check
```

Expected: pass.

- [ ] **Step 9: Manual verification**

Run:

```bash
cd frontend && bun run dev
```

Expected:

- Studio Canvas right panel defaults to Copilot.
- Selecting a node shows Inspector in the right panel.
- Selecting an edge shows Edge Inspector in the right panel.
- Legacy `?tab=builder` still shows old tabbed sidebar if `studioMode` is false.

- [ ] **Step 10: Commit**

```bash
git add frontend/components/editors/graph-builder frontend/lib/i18n/locales
git commit -m "refactor: replace builder right tabs with Studio right panel"
```

## Task 5: Add Node Palette and Canvas Context Menu

**Files:**
- Create: `frontend/components/editors/graph-builder/components/AddNodePalette.tsx`
- Create: `frontend/components/editors/graph-builder/components/CanvasContextMenu.tsx`
- Create: `frontend/components/editors/graph-builder/components/__tests__/add-node-palette.test.tsx`
- Modify: `frontend/components/editors/graph-builder/components/BuilderCanvas.tsx`
- Modify: `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx`
- Modify: `frontend/components/editors/graph-builder/AgentBuilder.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] **Step 1: Create failing palette test**

Create `frontend/components/editors/graph-builder/components/__tests__/add-node-palette.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AddNodePalette } from '../AddNodePalette'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key,
  }),
}))

vi.mock('../../services/nodeRegistry', () => ({
  nodeRegistry: {
    getGrouped: () => ({
      Core: [
        {
          type: 'agent',
          label: 'Agent',
          subLabel: 'LLM Process',
          icon: () => <span data-testid="agent-icon" />,
          style: { color: '', bg: '' },
        },
        {
          type: 'code_agent',
          label: 'Code Agent',
          subLabel: 'Python',
          icon: () => <span data-testid="code-icon" />,
          style: { color: '', bg: '' },
        },
      ],
    }),
  },
}))

describe('AddNodePalette', () => {
  it('filters nodes by query and selects the requested node', () => {
    const onSelect = vi.fn()
    render(<AddNodePalette onSelect={onSelect} />)

    fireEvent.change(screen.getByPlaceholderText('Search nodes...'), {
      target: { value: 'code' },
    })

    expect(screen.queryByText('Agent')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Code Agent'))

    expect(onSelect).toHaveBeenCalledWith({
      type: 'code_agent',
      label: 'Code Agent',
    })
  })
})
```

- [ ] **Step 2: Run focused test and verify it fails**

Run:

```bash
cd frontend && bun run test -- components/editors/graph-builder/components/__tests__/add-node-palette.test.tsx
```

Expected: fails because `AddNodePalette` does not exist.

- [ ] **Step 3: Implement `AddNodePalette.tsx`**

Create `frontend/components/editors/graph-builder/components/AddNodePalette.tsx`:

```tsx
'use client'

import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { nodeRegistry } from '../services/nodeRegistry'

interface AddNodePaletteProps {
  onSelect: (node: { type: string; label: string }) => void
  className?: string
}

export function AddNodePalette({ onSelect, className }: AddNodePaletteProps) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const groupedTools = nodeRegistry.getGrouped()

  const filteredGroups = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return Object.entries(groupedTools)
      .map(([category, items]) => ({
        category,
        items: items.filter((item) => {
          if (!normalizedQuery) return true
          return [item.label, item.subLabel, item.type]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(normalizedQuery))
        }),
      }))
      .filter((group) => group.items.length > 0)
  }, [groupedTools, query])

  return (
    <div className={cn('flex max-h-[520px] w-80 flex-col overflow-hidden', className)}>
      <div className="border-b border-[var(--border)] p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-[var(--text-muted)]" />
          <Input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('agents.studio.addNode.search', { defaultValue: 'Search nodes...' })}
            className="pl-8"
          />
        </div>
      </div>
      <div className="custom-scrollbar flex-1 overflow-y-auto p-2">
        {filteredGroups.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-[var(--text-muted)]">
            {t('agents.studio.addNode.empty', { defaultValue: 'No nodes found' })}
          </p>
        ) : (
          filteredGroups.map((group) => (
            <div key={group.category} className="mb-3">
              <p className="px-2 py-1 text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                {group.category}
              </p>
              <div className="space-y-1">
                {group.items.map((item) => {
                  const Icon = item.icon
                  return (
                    <button
                      key={item.type}
                      type="button"
                      onClick={() => onSelect({ type: item.type, label: item.label })}
                      className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left hover:bg-[var(--surface-3)]"
                    >
                      <span className={cn('rounded-lg p-1.5', item.style.bg, item.style.color)}>
                        <Icon size={16} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-[var(--text-primary)]">
                          {item.label}
                        </span>
                        {item.subLabel && (
                          <span className="block truncate text-xs text-[var(--text-muted)]">
                            {item.subLabel}
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Implement `CanvasContextMenu.tsx`**

Create `frontend/components/editors/graph-builder/components/CanvasContextMenu.tsx`:

```tsx
'use client'

import { AddNodePalette } from './AddNodePalette'

interface CanvasContextMenuProps {
  open: boolean
  x: number
  y: number
  onClose: () => void
  onAddNode: (node: { type: string; label: string }) => void
}

export function CanvasContextMenu({ open, x, y, onClose, onAddNode }: CanvasContextMenuProps) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-[80]" onClick={onClose} onContextMenu={(event) => event.preventDefault()}>
      <div
        className="absolute rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] shadow-2xl"
        style={{ left: x, top: y }}
        onClick={(event) => event.stopPropagation()}
      >
        <AddNodePalette
          onSelect={(node) => {
            onAddNode(node)
            onClose()
          }}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Re-run palette test**

Run:

```bash
cd frontend && bun run test -- components/editors/graph-builder/components/__tests__/add-node-palette.test.tsx
```

Expected: pass.

- [ ] **Step 6: Add toolbar `+ Add` palette**

In `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx`, import:

```typescript
import { Plus } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { AddNodePalette } from './AddNodePalette'
```

Extend props:

```typescript
onAddNode?: (node: { type: string; label: string }) => void
```

Add `onAddNode` to the destructured props.

Add this button in the right action group before Run/Publish:

```tsx
{onAddNode && (
  <Popover>
    <PopoverTrigger asChild>
      <Button size="sm" variant="outline" className="h-7 gap-1.5 px-2.5">
        <Plus size={13} />
        <span>{t('agents.studio.addNode.button', { defaultValue: 'Add' })}</span>
      </Button>
    </PopoverTrigger>
    <PopoverContent align="end" className="w-auto p-0">
      <AddNodePalette onSelect={onAddNode} />
    </PopoverContent>
  </Popover>
)}
```

- [ ] **Step 7: Add context menu behavior to `BuilderCanvas`**

In `frontend/components/editors/graph-builder/components/BuilderCanvas.tsx`, add state:

```typescript
const [contextMenu, setContextMenu] = useState<{
  open: boolean
  screenX: number
  screenY: number
  flowPosition: { x: number; y: number }
}>({ open: false, screenX: 0, screenY: 0, flowPosition: { x: 0, y: 0 } })
```

Import:

```typescript
import { CanvasContextMenu } from './CanvasContextMenu'
```

Add helper:

```typescript
const getFlowPositionFromEvent = useCallback((clientX: number, clientY: number) => {
  const bounds = reactFlowWrapper.current?.getBoundingClientRect()
  const instance = useBuilderStore.getState().rfInstance
  if (!bounds || !instance) return { x: 0, y: 0 }
  return instance.screenToFlowPosition({
    x: clientX - bounds.left,
    y: clientY - bounds.top,
  })
}, [])
```

Add to the root wrapper:

```tsx
onContextMenu={(event) => {
  event.preventDefault()
  if (!userPermissions.canEdit) return
  setContextMenu({
    open: true,
    screenX: event.clientX,
    screenY: event.clientY,
    flowPosition: getFlowPositionFromEvent(event.clientX, event.clientY),
  })
}}
```

Render before closing root div:

```tsx
<CanvasContextMenu
  open={contextMenu.open}
  x={contextMenu.screenX}
  y={contextMenu.screenY}
  onClose={() => setContextMenu((current) => ({ ...current, open: false }))}
  onAddNode={(node) => addNode(node.type, contextMenu.flowPosition, node.label)}
/>
```

- [ ] **Step 8: Wire toolbar add node in `AgentBuilder`**

In `frontend/components/editors/graph-builder/AgentBuilder.tsx`, extract `addNode` and `rfInstance` from store if not already available:

```typescript
addNode,
```

Define:

```typescript
const handleToolbarAddNode = (node: { type: string; label: string }) => {
  const viewport = useBuilderStore.getState().rfInstance?.getViewport()
  const position = {
    x: viewport ? -viewport.x / viewport.zoom + 120 : 120,
    y: viewport ? -viewport.y / viewport.zoom + 120 : 120,
  }
  addNode(node.type, position, node.label)
}
```

Pass to `BuilderToolbar` only in Studio mode:

```tsx
onAddNode={studioMode ? handleToolbarAddNode : undefined}
```

- [ ] **Step 9: Add add-node i18n keys**

Add under `agents.studio.addNode`:

English:

```typescript
addNode: {
  button: 'Add',
  search: 'Search nodes...',
  empty: 'No nodes found',
}
```

Chinese:

```typescript
addNode: {
  button: '添加',
  search: '搜索节点...',
  empty: '未找到节点',
}
```

- [ ] **Step 10: Run tests and type-check**

Run:

```bash
cd frontend && bun run test -- components/editors/graph-builder/components/__tests__/add-node-palette.test.tsx
cd frontend && bun run type-check
```

Expected: test and type-check pass.

- [ ] **Step 11: Manual verification**

Run:

```bash
cd frontend && bun run dev
```

Expected:

- Studio Canvas toolbar shows `Add`.
- Clicking `Add` opens a searchable palette.
- Selecting a node adds it near the visible canvas area.
- Right-clicking canvas opens the palette at cursor.
- Selecting a node from right-click palette adds it at the clicked flow position.
- Drag-and-drop from legacy Components still works in non-Studio builder.

- [ ] **Step 12: Commit**

```bash
git add frontend/components/editors/graph-builder frontend/lib/i18n/locales
git commit -m "feat: add canvas-native node palette"
```

## Task 6: Implement Test Lab Stage

**Files:**
- Create: `frontend/components/agents/studio/studio-test-lab-stage.tsx`
- Modify: `frontend/components/agents/studio/agent-studio-shell.tsx`
- Modify: `frontend/components/editors/graph-builder/AgentBuilder.tsx`
- Modify: `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] **Step 1: Rename Studio run copy to Run Draft**

In `frontend/components/editors/graph-builder/components/BuilderToolbar.tsx`, change run button text to use Studio copy when `studioMode` is true.

Extend props:

```typescript
studioMode?: boolean
```

Use:

```typescript
const runLabel = studioMode
  ? t('agents.studio.testLab.runDraft', { defaultValue: 'Run Draft' })
  : t('workspace.run', { defaultValue: 'Run' })
```

Replace visible run text with `runLabel`. If the current run button is icon-only, update tooltip content to `runLabel`.

- [ ] **Step 2: Pass `studioMode` into `BuilderToolbar`**

In `AgentBuilder.tsx`, pass:

```tsx
studioMode={studioMode}
```

- [ ] **Step 3: Create `studio-test-lab-stage.tsx`**

Create `frontend/components/agents/studio/studio-test-lab-stage.tsx`:

```tsx
'use client'

import { useState } from 'react'

import { ExecutionPanelNew as ExecutionPanel } from '@/components/execution/ExecutionPanelNew'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import { useExecutionStore } from '@/components/editors/graph-builder/stores/execution/executionStore'

interface StudioTestLabStageProps {
  onOpenCanvas: () => void
  onOpenRelease: () => void
}

export function StudioTestLabStage({ onOpenCanvas, onOpenRelease }: StudioTestLabStageProps) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')
  const { isExecuting, startExecution, stopExecution, togglePanel } = useExecutionStore()

  const runDraft = async () => {
    if (!input.trim()) return
    togglePanel(true)
    await startExecution(input)
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
                defaultValue:
                  'Run draft behavior before publishing. These tests do not affect the active release.',
              })}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onOpenCanvas}>
              {t('agents.studio.testLab.backToCanvas', { defaultValue: 'Back to Canvas' })}
            </Button>
            <Button variant="outline" onClick={onOpenRelease}>
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
            onChange={(event) => setInput(event.target.value)}
            rows={8}
            className="mt-2"
            placeholder={t('agents.studio.testLab.inputPlaceholder', {
              defaultValue: 'Enter a sample request for this draft...',
            })}
          />
          <Button className="mt-3 w-full" onClick={runDraft} disabled={!input.trim() || isExecuting}>
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

- [ ] **Step 4: Add embedded mode to `ExecutionPanelNew`**

In `frontend/components/execution/ExecutionPanelNew.tsx`, change `ExecutionPanelContent` to accept `embedded`:

```typescript
interface ExecutionPanelContentProps {
  embedded?: boolean
}

function ExecutionPanelContent({ embedded = false }: ExecutionPanelContentProps) {
```

Replace the root `className` in `ExecutionPanelContent` with:

```tsx
className={cn(
  'z-40 flex shrink-0 flex-col border-t border-[var(--border)] bg-[var(--surface-elevated)] font-sans shadow-[0_-4px_20px_rgba(0,0,0,0.05)] duration-300 animate-in slide-in-from-bottom-10',
  embedded ? 'h-full w-full' : 'h-[320px] w-[calc(100%-320px)]',
)}
```

Change the exported component:

```typescript
interface ExecutionPanelNewProps {
  embedded?: boolean
}

export function ExecutionPanelNew({ embedded = false }: ExecutionPanelNewProps) {
  const { steps, isExecuting, treeRoots, treeNodeMap } = useExecutionStore()

  return (
    <ExecutionSelectionProvider>
      <ExecutionSelectionConsumerWrapper
        embedded={embedded}
        steps={steps}
        isExecuting={isExecuting}
        treeRoots={treeRoots}
        treeNodeMap={treeNodeMap}
      />
    </ExecutionSelectionProvider>
  )
}
```

Update `ExecutionSelectionConsumerWrapper` props:

```typescript
function ExecutionSelectionConsumerWrapper({
  embedded = false,
  steps,
  isExecuting,
  treeRoots,
  treeNodeMap,
}: {
  embedded?: boolean
  steps: any[]
  isExecuting: boolean
  treeRoots: any[]
  treeNodeMap: Map<string, any>
}) {
```

Pass it through:

```tsx
<ExecutionPanelContent embedded={embedded} />
```

The default `embedded = false` keeps current bottom-dock behavior unchanged.

- [ ] **Step 5: Wire Test Lab stage into shell**

In `agent-studio-shell.tsx`, import `StudioTestLabStage` and render:

```tsx
{activeStage === 'test-lab' && (
  <StudioTestLabStage
    onOpenCanvas={() => setActiveStage('canvas')}
    onOpenRelease={() => setActiveStage('release')}
  />
)}
```

Remove `test-lab` from the initial stage overview condition.

- [ ] **Step 6: Add Test Lab i18n keys**

Add under `agents.studio.testLab`:

English:

```typescript
testLab: {
  kicker: 'Draft validation',
  title: 'Test the current draft',
  subtitle: 'Run draft behavior before publishing. These tests do not affect the active release.',
  inputLabel: 'Test input',
  inputPlaceholder: 'Enter a sample request for this draft...',
  runDraft: 'Run Draft',
  running: 'Running...',
  stop: 'Stop',
  backToCanvas: 'Back to Canvas',
  openRelease: 'Open Release',
}
```

Chinese:

```typescript
testLab: {
  kicker: '草稿验证',
  title: '测试当前草稿',
  subtitle: '发布前先运行草稿行为。这些测试不会影响当前已发布版本。',
  inputLabel: '测试输入',
  inputPlaceholder: '输入一个用于测试草稿的请求...',
  runDraft: '运行草稿',
  running: '运行中...',
  stop: '停止',
  backToCanvas: '回到编排',
  openRelease: '打开发布',
}
```

- [ ] **Step 7: Run type-check**

Run:

```bash
cd frontend && bun run type-check
```

Expected: pass.

- [ ] **Step 8: Manual verification**

Run:

```bash
cd frontend && bun run dev
```

Expected:

- `stage=test-lab` opens Test Lab.
- Test input can start a run.
- Execution events render in embedded panel.
- Stop button cancels current run.
- Copy says Run Draft, not Chat.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/agents/studio frontend/components/editors/graph-builder frontend/components/execution frontend/lib/i18n/locales
git commit -m "feat: add Agent Studio Test Lab stage"
```

## Task 7: Implement Release and Usage Stages

**Files:**
- Create: `frontend/components/agents/studio/studio-release-stage.tsx`
- Create: `frontend/components/agents/studio/studio-usage-stage.tsx`
- Modify: `frontend/components/agents/studio/agent-studio-shell.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] **Step 1: Create Release stage**

Create `frontend/components/agents/studio/studio-release-stage.tsx`:

```tsx
'use client'

import { Loader2, Rocket } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useReleases, useActivateRelease } from '@/hooks/queries/agentReleases'
import { useVersions } from '@/hooks/queries/agentVersions'
import { useTranslation } from '@/lib/i18n'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import type { Agent } from '@/types/agent'

interface StudioReleaseStageProps {
  agent: Agent
  onOpenUsage: () => void
}

export function StudioReleaseStage({ agent, onOpenUsage }: StudioReleaseStageProps) {
  const { t } = useTranslation()
  const { workspaceId } = useCurrentWorkspace()
  const { data: versions = [], isLoading: versionsLoading } = useVersions(agent.id, workspaceId)
  const { data: releases = [], isLoading: releasesLoading } = useReleases(agent.id, workspaceId)
  const activateRelease = useActivateRelease()

  const loading = versionsLoading || releasesLoading

  return (
    <div className="h-full overflow-y-auto bg-[var(--surface-1)] px-8 py-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
            {t('agents.studio.release.kicker', { defaultValue: 'Publish for use' })}
          </p>
          <h2 className="mt-1 text-2xl font-semibold">
            {t('agents.studio.release.title', { defaultValue: 'Release this Agent' })}
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-[var(--text-secondary)]">
            {t('agents.studio.release.subtitle', {
              defaultValue:
                'Freeze a draft as a version, publish it, and choose which release business scenarios use.',
            })}
          </p>
        </div>
        <Button onClick={onOpenUsage} disabled={!agent.active_release_id}>
          {t('agents.studio.release.openUsage', { defaultValue: 'Open Usage' })}
        </Button>
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--brand-500)]" />
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card className="p-5">
            <h3 className="mb-4 font-semibold">
              {t('agents.studio.release.versions', { defaultValue: 'Versions' })}
            </h3>
            <div className="space-y-2">
              {versions.map((version) => (
                <div
                  key={version.id}
                  className="flex items-center justify-between rounded-lg border border-[var(--border)] p-3"
                >
                  <div>
                    <p className="font-medium">v{version.version_number}</p>
                    <p className="text-xs text-[var(--text-muted)]">{version.definition_kind}</p>
                  </div>
                  <Badge variant="outline">{version.status}</Badge>
                </div>
              ))}
              {versions.length === 0 && (
                <p className="text-sm text-[var(--text-muted)]">
                  {t('agents.studio.release.noVersions', { defaultValue: 'No versions yet' })}
                </p>
              )}
            </div>
          </Card>

          <Card className="p-5">
            <h3 className="mb-4 font-semibold">
              {t('agents.studio.release.releases', { defaultValue: 'Published Releases' })}
            </h3>
            <div className="space-y-2">
              {releases.map((release) => {
                const active = release.id === agent.active_release_id
                return (
                  <div
                    key={release.id}
                    className="flex items-center justify-between rounded-lg border border-[var(--border)] p-3"
                  >
                    <div className="flex items-center gap-3">
                      <Rocket className="h-4 w-4 text-[var(--text-muted)]" />
                      <div>
                        <p className="font-medium">{release.runtime_kind}</p>
                        <p className="text-xs text-[var(--text-muted)]">{release.status}</p>
                      </div>
                    </div>
                    {active ? (
                      <Badge>{t('agents.studio.release.active', { defaultValue: 'Active' })}</Badge>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          activateRelease.mutate({
                            agentId: agent.id,
                            releaseId: release.id,
                            workspaceId,
                          })
                        }
                      >
                        {t('agents.studio.release.activate', { defaultValue: 'Activate' })}
                      </Button>
                    )}
                  </div>
                )
              })}
              {releases.length === 0 && (
                <p className="text-sm text-[var(--text-muted)]">
                  {t('agents.studio.release.noReleases', { defaultValue: 'No releases yet' })}
                </p>
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create Usage stage**

Create `frontend/components/agents/studio/studio-usage-stage.tsx`:

```tsx
'use client'

import { Code2, MessageSquare, PlusCircle, Workflow } from 'lucide-react'
import Link from 'next/link'

import { ChatPanel } from '@/components/chat/ChatPanel'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAgentRuns } from '@/hooks/queries/agentRuns'
import { useTranslation } from '@/lib/i18n'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import type { Agent } from '@/types/agent'

interface StudioUsageStageProps {
  agent: Agent
}

export function StudioUsageStage({ agent }: StudioUsageStageProps) {
  const { t } = useTranslation()
  const { workspaceId } = useCurrentWorkspace()
  const { data: runs = [] } = useAgentRuns(
    { workspace_id: workspaceId },
    { enabled: Boolean(workspaceId && agent.active_release_id) },
  )

  const recentRuns = runs.slice(0, 5)

  if (!agent.active_release_id) {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--surface-1)] p-8 text-center">
        <div className="max-w-md">
          <h2 className="text-2xl font-semibold">
            {t('agents.studio.usage.notPublishedTitle', { defaultValue: 'Publish before using' })}
          </h2>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            {t('agents.studio.usage.notPublishedDesc', {
              defaultValue: 'Usage runs against the active release. Publish a tested version first.',
            })}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr] bg-[var(--surface-1)]">
      <aside className="overflow-y-auto border-r border-[var(--border)] p-5">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
          {t('agents.studio.usage.kicker', { defaultValue: 'Business usage' })}
        </p>
        <h2 className="mt-1 text-xl font-semibold">
          {t('agents.studio.usage.title', { defaultValue: 'Use the published Agent' })}
        </h2>
        <div className="mt-5 space-y-3">
          <Button asChild className="w-full justify-start">
            <Link href={`/tasks?agent=${agent.id}`}>
              <PlusCircle className="mr-2 h-4 w-4" />
              {t('agents.studio.usage.createTask', { defaultValue: 'Create Task' })}
            </Link>
          </Button>
          <Button variant="outline" className="w-full justify-start">
            <Code2 className="mr-2 h-4 w-4" />
            {t('agents.studio.usage.copyApi', { defaultValue: 'Copy API endpoint' })}
          </Button>
          <Button variant="outline" className="w-full justify-start">
            <Workflow className="mr-2 h-4 w-4" />
            {t('agents.studio.usage.bindScenario', { defaultValue: 'Bind scenario' })}
          </Button>
        </div>

        <Card className="mt-6 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <MessageSquare className="h-4 w-4" />
            {t('agents.studio.usage.recentRuns', { defaultValue: 'Recent business runs' })}
          </h3>
          <div className="space-y-2">
            {recentRuns.map((run) => (
              <Link
                key={run.id}
                href={`/executions/${run.current_execution_id ?? run.id}`}
                className="block rounded-lg border border-[var(--border)] p-2 text-sm hover:bg-[var(--surface-2)]"
              >
                <span className="block truncate font-medium">{run.goal || run.id}</span>
                <span className="text-xs text-[var(--text-muted)]">{run.status}</span>
              </Link>
            ))}
            {recentRuns.length === 0 && (
              <p className="text-sm text-[var(--text-muted)]">
                {t('agents.studio.usage.noRuns', { defaultValue: 'No business runs yet' })}
              </p>
            )}
          </div>
        </Card>
      </aside>

      <section className="min-h-0">
        <ChatPanel agentId={agent.id} workspaceId={workspaceId} />
      </section>
    </div>
  )
}
```

- [ ] **Step 3: Wire Release and Usage into shell**

In `agent-studio-shell.tsx`, import:

```typescript
import { StudioReleaseStage } from './studio-release-stage'
import { StudioUsageStage } from './studio-usage-stage'
```

Render:

```tsx
{activeStage === 'release' && (
  <StudioReleaseStage agent={agent} onOpenUsage={() => setActiveStage('usage')} />
)}
{activeStage === 'usage' && <StudioUsageStage agent={agent} />}
```

Remove `release` and `usage` from the initial stage overview condition.

- [ ] **Step 4: Add Release/Usage i18n keys**

Add under `agents.studio.release` and `agents.studio.usage`.

English:

```typescript
release: {
  kicker: 'Publish for use',
  title: 'Release this Agent',
  subtitle: 'Freeze a draft as a version, publish it, and choose which release business scenarios use.',
  openUsage: 'Open Usage',
  versions: 'Versions',
  releases: 'Published Releases',
  noVersions: 'No versions yet',
  noReleases: 'No releases yet',
  active: 'Active',
  activate: 'Activate',
},
usage: {
  kicker: 'Business usage',
  title: 'Use the published Agent',
  notPublishedTitle: 'Publish before using',
  notPublishedDesc: 'Usage runs against the active release. Publish a tested version first.',
  createTask: 'Create Task',
  copyApi: 'Copy API endpoint',
  bindScenario: 'Bind scenario',
  recentRuns: 'Recent business runs',
  noRuns: 'No business runs yet',
}
```

Chinese:

```typescript
release: {
  kicker: '发布使用',
  title: '发布这个 Agent',
  subtitle: '将草稿冻结为版本，发布后选择业务场景使用的 Release。',
  openUsage: '打开使用',
  versions: '版本',
  releases: '已发布 Release',
  noVersions: '暂无版本',
  noReleases: '暂无发布',
  active: '当前使用',
  activate: '激活',
},
usage: {
  kicker: '业务使用',
  title: '使用已发布 Agent',
  notPublishedTitle: '发布后才能使用',
  notPublishedDesc: '使用入口运行的是 active release。请先发布一个测试过的版本。',
  createTask: '创建任务',
  copyApi: '复制 API Endpoint',
  bindScenario: '绑定业务场景',
  recentRuns: '最近业务执行',
  noRuns: '暂无业务执行',
}
```

- [ ] **Step 5: Run type-check**

Run:

```bash
cd frontend && bun run type-check
```

Expected: pass.

- [ ] **Step 6: Manual verification**

Run:

```bash
cd frontend && bun run dev
```

Expected:

- Release stage shows versions and releases.
- Activation button calls existing release mutation.
- Usage stage blocks if no active release.
- Usage stage shows ChatPanel only when active release exists.
- Task link points to `/tasks?agent=:id`.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/agents/studio frontend/lib/i18n/locales
git commit -m "feat: add Agent Studio release and usage stages"
```

## Task 8: Final Route Cleanup, Legacy Guardrails, and CI

**Files:**
- Modify: `frontend/app/agents/[agentId]/page.tsx`
- Modify: `frontend/components/agents/agent-overview-tab.tsx`
- Modify: `frontend/components/editors/graph-builder/components/BuilderSidebarTabs.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: `docs/superpowers/specs/2026-04-25-agent-studio-workflow-design.md` only if implementation reveals a spec correction

- [ ] **Step 1: Audit remaining builder/version/release route links**

Run:

```bash
rg -n "tab=builder|/versions|/releases|/runs|BuilderSidebarTabs|Open Builder|deploymentHistory" frontend/app frontend/components frontend/hooks frontend/services
```

Expected: remaining matches are either compatibility paths or intentionally internal UI labels.

- [ ] **Step 2: Update stale copy and links**

For user-facing links:

- Replace `?tab=builder` with `?stage=canvas`.
- Replace `Open Builder` with `Open Studio`.
- Keep `?tab=builder` only as backward-compatible route handling in `page.tsx`.
- Keep `BuilderSidebarTabs` only for non-Studio compatibility.

- [ ] **Step 3: Verify no Components tab appears in Studio**

Manual dev check:

```bash
cd frontend && bun run dev
```

Expected:

- Studio right panel has Copilot or Inspector.
- Components are available through `+ Add` and right-click palette.
- No `Copilot / Components` tabs are visible in Studio.

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd frontend && bun run test -- components/agents/studio/__tests__/studio-stage-selection.test.ts components/editors/graph-builder/components/__tests__/add-node-palette.test.tsx
```

Expected: pass.

- [ ] **Step 5: Run full frontend CI**

Run:

```bash
sh scripts/run-frontend-ci.sh
```

Expected: lint, typegen, type-check, tests, and build pass.

- [ ] **Step 6: Commit final cleanup**

```bash
git add frontend docs/superpowers/specs/2026-04-25-agent-studio-workflow-design.md
git commit -m "refactor: finalize Agent Studio workflow integration"
```

## Acceptance Checklist

- [ ] `/agents/:agentId` opens Agent Studio for graph/Visual Agents.
- [ ] Empty Visual Agents default to Brief.
- [ ] Non-empty Visual Agents default to Canvas.
- [ ] Brief can hand structured intent to existing Copilot via `copilotInput`.
- [ ] Canvas right panel defaults to Copilot when nothing is selected.
- [ ] Canvas right panel shows Inspector when node or edge is selected.
- [ ] `+ Add` opens node palette.
- [ ] Right-click on canvas opens node palette at cursor.
- [ ] Test Lab says Run Draft and does not use Chat terminology.
- [ ] Release stage shows versions and releases.
- [ ] Usage stage only uses active release and includes published Agent Chat.
- [ ] Legacy `?tab=chat`, `?tab=settings`, and `?tab=builder` remain functional.
- [ ] Full frontend CI passes.

## Risks and Follow-Ups

- Test Lab currently reuses `executionStore.startExecution`, and that code path reads `agent.active_release_id`. The implementation must either change the execution adapter to accept draft version runs in a dedicated follow-up plan, or label the first implementation as "validation run using current active release" in code comments and product copy. Do not claim backend draft isolation until a draft execution API exists.
- Release stage lists existing versions and releases. If current publish flow does not create/freeze a version from the draft, leave the publish action routed to the existing `deploymentAdapter.deploy(agentId, versionId, workspaceId)` flow used by `BuilderToolbar`; do not invent a new release API in this frontend plan.
- Usage stage contains API endpoint and business scenario actions. In this plan, implement them as disabled buttons with explanatory tooltips unless concrete endpoints already exist in `frontend/services`. The enabled first-pass usage actions are `Create Task`, `ChatPanel`, and recent business runs.
- The `AgentBuilder` component is large. Avoid broad rewrites; each task should preserve existing loading, autosave, import/export, Copilot, and execution behavior.
