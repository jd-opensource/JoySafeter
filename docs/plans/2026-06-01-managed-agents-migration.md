# Managed Agents (托管智能体) Migration Plan

> **Status (2026-07-03): Historical implementation plan.** The `/managed/**` product surface
> now exists in the current frontend (`frontend/app/managed`, `frontend/components/managed`,
> `frontend/hooks/managed`, `frontend/types/managed.ts`). Keep this document as migration
> history; use `frontend/README.md`, `docs/ARCHITECTURE.md`, and the live code for current
> development guidance.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate joysafeter-native's "托管智能体" section (Quickstart, Agents, Sessions, Environments, Vaults) into JoySafeter under `/managed/*` routes with a collapsible sidebar group.

**Architecture:** Port all joysafeter-native pages as Next.js App Router `'use client'` components under `app/managed/`. Reuse JoySafeter's `apiGet`/`apiPost` instead of JoySafeter's Bearer-token client. Shared components (DataTable, StatusBadge, etc.) go in `components/managed/shared/`. Session event viewer components go in `components/managed/session/`. The existing JoySafeter `/agents` page is preserved unchanged.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS v3, shadcn/ui, TanStack React Query v5, Zustand, i18next, lucide-react, date-fns, react-markdown + remark-gfm, js-yaml

**Source:** All code migrated from `/Users/wengaolei1/mydata/mycoding/sources/joysafeter-native/web/src/`

---

## Task 1: Foundation — Types, Utilities, and Hooks

**Files:**
- Create: `frontend/types/managed.ts`
- Create: `frontend/lib/managed/id.ts`
- Create: `frontend/lib/managed/filters.ts`
- Create: `frontend/lib/managed/sse.ts`
- Create: `frontend/hooks/managed/use-paginated-list.ts`

### Step 1: Create type definitions

Create `frontend/types/managed.ts` — copy all interfaces from `joysafeter-native/web/src/lib/types.ts` verbatim: `Agent`, `AgentSkillRef`, `ToolItemConfig`, `ToolDefaultConfig`, `AgentTool`, `McpServer`, `Session`, `SessionAgent`, `SessionStatus`, `SessionUsage`, `SessionStats`, `SessionEvent`, `EnvironmentNetworking`, `EnvironmentPackages`, `EnvironmentConfig`, `Environment`, `Vault`, `VaultCredential`, `MemoryStore`, `PaginatedResponse`, `FileRecord`, `SkillRecord`, `SkillVersionRecord`, `SkillFileRecord`, `MemberRecord`, `Secret`, `ApiKeyInfo`, `ProjectRecord`.

No changes needed — these are pure type definitions.

### Step 2: Create ID utility

Create `frontend/lib/managed/id.ts`:

```typescript
export function stripIdPrefix(id: string): string {
  return id.replace(/^(agent_|sess_|env_|vault_|vlt_|cred_|mst_|evt_|thread_)/, '')
}
```

### Step 3: Create filter utility

Create `frontend/lib/managed/filters.ts`:

```typescript
export function filterByCreatedTime(createdAt: string, filter: string): boolean {
  if (filter === 'all') return true
  const now = Date.now()
  const created = new Date(createdAt).getTime()
  const diffMs = now - created
  switch (filter) {
    case '1h': return diffMs <= 3_600_000
    case '24h': return diffMs <= 86_400_000
    case '7d': return diffMs <= 604_800_000
    case '30d': return diffMs <= 2_592_000_000
    case '90d': return diffMs <= 7_776_000_000
    default: return true
  }
}
```

### Step 4: Create SSE streaming hook

Create `frontend/lib/managed/sse.ts` — adapt from `joysafeter-native/web/src/lib/sse.ts`.

Key adaptation: Replace `getAuthHeaders()` (Bearer token) with `credentials: 'include'` (cookie-based). Replace `import.meta.env.VITE_API_BASE_URL` with JoySafeter's `API_BASE` from `@/lib/api-client`.

```typescript
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { SessionEvent } from '@/types/managed'
import { API_BASE } from '@/lib/api-client'
import { getCsrfToken } from '@/lib/auth/csrf'

export function useSessionStream(sessionId: string, enabled: boolean) {
  const [events, setEvents] = useState<SessionEvent[]>([])
  const [connected, setConnected] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const lastSeqRef = useRef<number>(0)

  useEffect(() => {
    if (!enabled || !sessionId) return
    let cancelled = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = async () => {
      if (cancelled) return
      const controller = new AbortController()
      abortRef.current = controller
      try {
        const afterSeq = lastSeqRef.current
        const path = `/sessions/${sessionId}/events/stream`
        const url = afterSeq > 0
          ? `${API_BASE}/${path}?after_seq=${afterSeq}`
          : `${API_BASE}/${path}`
        const headers: Record<string, string> = {}
        const csrfToken = getCsrfToken()
        if (csrfToken) headers['X-CSRF-Token'] = csrfToken
        const resp = await fetch(url, {
          signal: controller.signal,
          headers,
          credentials: 'include',
        })
        if (!resp.ok || !resp.body) { scheduleReconnect(); return }
        setConnected(true)
        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let batch: SessionEvent[] = []
        let flushTimer: ReturnType<typeof setTimeout> | null = null
        let lagged = false
        const flush = () => {
          if (batch.length > 0) {
            const toAdd = batch
            batch = []
            setEvents((prev) => [...prev, ...toAdd])
          }
          flushTimer = null
        }
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            const data = line.slice(5).trim()
            if (!data || data === '[DONE]') continue
            try {
              const parsed = JSON.parse(data)
              if (parsed.lagged) { lagged = true; continue }
              const event = parsed as SessionEvent
              if (event.seq && event.seq > lastSeqRef.current) lastSeqRef.current = event.seq
              batch.push(event)
            } catch { /* ignore */ }
          }
          if (batch.length > 0 && !flushTimer) flushTimer = setTimeout(flush, 50)
          if (lagged) { flush(); controller.abort(); break }
        }
        flush()
        setConnected(false)
        scheduleReconnect()
      } catch (e) {
        if ((e as Error).name !== 'AbortError') { setConnected(false); scheduleReconnect() }
      }
    }
    const scheduleReconnect = () => { if (!cancelled) reconnectTimer = setTimeout(connect, 500) }
    connect()
    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      abortRef.current?.abort()
      abortRef.current = null
      setConnected(false)
    }
  }, [sessionId, enabled])

  const clear = useCallback(() => { setEvents([]); lastSeqRef.current = 0 }, [])
  return { events, connected, clear }
}
```

### Step 5: Create paginated list hook

Create `frontend/hooks/managed/use-paginated-list.ts` — adapt from JoySafeter's `use-paginated-list.ts`.

Key adaptation: Replace `apiPage()` with inline implementation using JoySafeter's `apiGet`. The joysafeter `apiPage` builds URL params (`limit`, `after_id`, `include_archived`) and fetches via `apiFetch`. We replicate this using `apiGet`.

```typescript
'use client'

import { useState, useCallback, useEffect } from 'react'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { apiGet } from '@/lib/api-client'

interface PageResult<T> {
  data: T[]
  has_more: boolean
  first_id?: string
  last_id?: string
}

interface UsePaginatedListOptions {
  queryKey: string
  path: string
  limit?: number
  enabled?: boolean
  includeArchived?: boolean
}

async function fetchPage<T>(path: string, cursor?: string, limit = 20, includeArchived = false): Promise<PageResult<T>> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (cursor) params.set('after_id', cursor)
  if (includeArchived) params.set('include_archived', 'true')
  const sep = path.includes('?') ? '&' : '?'
  const url = `${path}${sep}${params.toString()}`
  const res = await apiGet<T[] | { data: T[]; has_more: boolean; first_id?: string; last_id?: string }>(url)
  if (Array.isArray(res)) return { data: res, has_more: false }
  return { data: res.data, has_more: res.has_more, first_id: res.first_id, last_id: res.last_id }
}

export function usePaginatedList<T extends { id?: string }>({
  queryKey,
  path,
  limit = 20,
  enabled = true,
  includeArchived = false,
}: UsePaginatedListOptions) {
  const queryClient = useQueryClient()
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [cursorStack, setCursorStack] = useState<string[]>([])
  const fullKey = [queryKey, cursor, includeArchived]

  useEffect(() => { setCursor(undefined); setCursorStack([]) }, [includeArchived])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: fullKey,
    queryFn: () => fetchPage<T>(path, cursor, limit, includeArchived),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
  const page = data || { data: [], has_more: false }

  useEffect(() => {
    if (page.has_more && page.last_id && enabled) {
      queryClient.prefetchQuery({
        queryKey: [queryKey, page.last_id, includeArchived],
        queryFn: () => fetchPage<T>(path, page.last_id, limit, includeArchived),
        staleTime: 30_000,
      })
    }
  }, [page.has_more, page.last_id, queryKey, path, limit, includeArchived, enabled, queryClient])

  const goNext = useCallback(() => {
    if (page.last_id) { setCursorStack((s) => [...s, cursor || '']); setCursor(page.last_id) }
  }, [page.last_id, cursor])
  const goPrev = useCallback(() => {
    const prev = cursorStack[cursorStack.length - 1]
    setCursorStack((s) => s.slice(0, -1))
    setCursor(prev || undefined)
  }, [cursorStack])
  const reset = useCallback(() => { setCursor(undefined); setCursorStack([]) }, [])

  return { data: page.data, isLoading, isFetching, hasNext: page.has_more, hasPrev: cursorStack.length > 0, goNext, goPrev, reset }
}
```

### Step 6: Commit

```bash
git add frontend/types/managed.ts frontend/lib/managed/ frontend/hooks/managed/
git commit -m "feat(managed): add types, utilities, SSE hook, and paginated list hook for managed agents"
```

---

## Task 2: Shared Components

**Files:**
- Create: `frontend/components/managed/shared/action-menu.tsx`
- Create: `frontend/components/managed/shared/data-table.tsx`
- Create: `frontend/components/managed/shared/filter-bar.tsx`
- Create: `frontend/components/managed/shared/status-badge.tsx`
- Create: `frontend/components/managed/shared/mono-id.tsx`
- Create: `frontend/components/managed/shared/relative-time.tsx`
- Create: `frontend/components/managed/shared/confirm-dialog.tsx`
- Create: `frontend/components/managed/shared/page-header.tsx`
- Create: `frontend/components/managed/shared/index.ts`

### Step 1: Port all shared components

Copy each component from `joysafeter-native/web/src/components/shared/` and `components/layout/PageHeader.tsx`. Adaptations for ALL files:

1. Add `'use client'` at top
2. Change `import { useTranslation } from "react-i18next"` → `import { useTranslation } from '@/lib/i18n'`
3. Change `@/components/ui/*` imports → same (JoySafeter has the same shadcn/ui components)
4. Change `@/lib/utils` → same (JoySafeter has `cn()`)
5. For `PageHeader.tsx`: change `<a href={crumb.to}>` → use `import Link from 'next/link'` and `<Link href={crumb.to}>`
6. For `RelativeTime`: install `date-fns` if not present (check `package.json`)
7. For `DataTable`: import `ActionMenu` from `./action-menu`

The components are simple enough that the Tailwind v4→v3 difference doesn't apply — they use utility classes (like `bg-muted`, `text-foreground`) that are the same in both versions.

### Step 2: Create barrel export

Create `frontend/components/managed/shared/index.ts`:

```typescript
export { ActionMenu, type MenuItem } from './action-menu'
export { DataTable, type Column } from './data-table'
export { FilterBar, type FilterDef } from './filter-bar'
export { StatusBadge } from './status-badge'
export { MonoId } from './mono-id'
export { RelativeTime } from './relative-time'
export { ConfirmDialog } from './confirm-dialog'
export { PageHeader } from './page-header'
```

### Step 3: Commit

```bash
git add frontend/components/managed/shared/
git commit -m "feat(managed): port shared components (DataTable, FilterBar, StatusBadge, etc.)"
```

---

## Task 3: Session Event Viewer Components

**Files:**
- Create: `frontend/components/managed/session/role-badge.tsx`
- Create: `frontend/components/managed/session/event-row.tsx`
- Create: `frontend/components/managed/session/event-list.tsx`
- Create: `frontend/components/managed/session/event-detail.tsx`
- Create: `frontend/components/managed/session/event-timeline.tsx`
- Create: `frontend/components/managed/session/event-filter.tsx`
- Create: `frontend/components/managed/session/index.ts`

### Step 1: Port all session event components

Copy each from `joysafeter-native/web/src/components/session/`. Adaptations:

1. Add `'use client'` at top
2. `import { useTranslation } from "react-i18next"` → `import { useTranslation } from '@/lib/i18n'`
3. `import type { SessionEvent } from "@/lib/types"` → `import type { SessionEvent } from '@/types/managed'`
4. `import { cn } from "@/lib/utils"` → same path (exists in JoySafeter)
5. `EventDetail.tsx`: uses `ReactMarkdown` and `remarkGfm` — both already in JoySafeter's dependencies

These components are display-only with no routing or API calls, so the migration is straightforward.

### Step 2: Create barrel export

```typescript
export { RoleBadge } from './role-badge'
export { EventRow } from './event-row'
export { EventList } from './event-list'
export { EventDetail } from './event-detail'
export { EventTimeline } from './event-timeline'
export { EventFilter } from './event-filter'
```

### Step 3: Commit

```bash
git add frontend/components/managed/session/
git commit -m "feat(managed): port session event viewer components (EventList, EventDetail, EventTimeline, etc.)"
```

---

## Task 4: Sidebar — Add Collapsible "托管智能体" Group

**Files:**
- Modify: `frontend/components/app-sidebar/app-sidebar.tsx`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/lib/i18n/locales/en.ts`

### Step 1: Add collapsible NavSection to sidebar

Modify `frontend/components/app-sidebar/app-sidebar.tsx`:

1. Import additional icons: `Zap`, `MessageSquare`, `Server`, `KeyRound`, `ChevronDown`
2. Add a new `MenuGroup` type variant that supports collapsible groups with a label
3. Add the managed agents group items:
   - quickstart: `/managed/quickstart`, icon `Zap`, labelKey `sidebar.managed.quickstart`
   - agents: `/managed/agents`, icon `Bot`, labelKey `sidebar.managed.agents`
   - sessions: `/managed/sessions`, icon `MessageSquare`, labelKey `sidebar.managed.sessions`
   - environments: `/managed/environments`, icon `Server`, labelKey `sidebar.managed.environments`
   - vaults: `/managed/vaults`, icon `KeyRound`, labelKey `sidebar.managed.vaults`
4. Add a collapsible section with header "托管智能体" between dashboard and the existing agents group
5. Use `useState(true)` for default-open collapse state
6. Active state: `pathname?.startsWith('/managed')`

The collapsible pattern: a clickable header with ChevronDown that toggles child items visibility, matching joysafeter-native's `NavSection`.

### Step 2: Add i18n keys

Add to `zh.ts` under `sidebar`:
```
managed: {
  title: '托管智能体',
  quickstart: '快速开始',
  agents: '智能体',
  sessions: '会话',
  environments: '环境',
  vaults: '凭证库',
}
```

Add corresponding English translations to `en.ts`.

### Step 3: Commit

```bash
git add frontend/components/app-sidebar/ frontend/lib/i18n/locales/
git commit -m "feat(managed): add collapsible managed agents group to sidebar"
```

---

## Task 5: Agents Pages

**Files:**
- Create: `frontend/app/managed/agents/page.tsx` (AgentList)
- Create: `frontend/app/managed/agents/[agentId]/page.tsx` (AgentDetail)
- Create: `frontend/app/managed/agents/[agentId]/edit/page.tsx` (AgentEdit)
- Create: `frontend/app/managed/agents/components/create-agent-dialog.tsx`

### Step 1: Port AgentList

Source: `joysafeter-native/web/src/pages/agents/AgentList.tsx`

Adaptations:
- `'use client'` at top
- `useNavigate()` → `import { useRouter } from 'next/navigation'` + `router.push()`
- `navigate('/agents/...')` → `router.push('/managed/agents/...')`
- `import { usePaginatedList } from "@/hooks/use-paginated-list"` → `from '@/hooks/managed/use-paginated-list'`
- `import { apiPost, apiFetch, apiDelete } from "@/lib/api"` → `from '@/lib/api-client'`
- All shared component imports → `from '@/components/managed/shared'`
- Type imports → `from '@/types/managed'`
- `import { stripIdPrefix } from "@/lib/id"` → `from '@/lib/managed/id'`
- `import { filterByCreatedTime } from "@/lib/filters"` → `from '@/lib/managed/filters'`
- `useTranslation` → `from '@/lib/i18n'`
- `CreateAgentDialog` → local component import

### Step 2: Port AgentDetail

Source: `joysafeter-native/web/src/pages/agents/AgentDetail.tsx`

Same adaptations as Step 1 plus:
- `const { id } = useParams()` → `export default function AgentDetailPage({ params }: { params: { agentId: string } })` — use Next.js page params
- All internal links to `/agents/`, `/sessions/`, `/environments/`, `/vaults/` → prefix with `/managed/`

### Step 3: Port AgentEdit

Source: `joysafeter-native/web/src/pages/agents/AgentEdit.tsx`

Same pattern of adaptations.

### Step 4: Port CreateAgentDialog

Source: `joysafeter-native/web/src/pages/agents/CreateAgentDialog.tsx`

Same adaptations. Internal navigation → `/managed/agents/{id}`.

### Step 5: Commit

```bash
git add frontend/app/managed/agents/
git commit -m "feat(managed): port agents pages (list, detail, edit, create dialog)"
```

---

## Task 6: Sessions Pages

**Files:**
- Create: `frontend/app/managed/sessions/page.tsx` (SessionList)
- Create: `frontend/app/managed/sessions/[sessionId]/page.tsx` (SessionDetail)
- Create: `frontend/app/managed/sessions/components/create-session-dialog.tsx`

### Step 1: Port SessionList

Source: `joysafeter-native/web/src/pages/sessions/SessionList.tsx`

Same adaptation pattern as Task 5. Navigation → `/managed/sessions/{id}`.

### Step 2: Port SessionDetail

Source: `joysafeter-native/web/src/pages/sessions/SessionDetail.tsx` (this is the largest single file ~1200 lines)

Key adaptations beyond the standard ones:
- `const { id } = useParams()` → Next.js page params `{ params: { sessionId: string } }`
- `import { useSessionStream } from "@/lib/sse"` → `from '@/lib/managed/sse'`
- Session event components → `from '@/components/managed/session'`
- Internal drawer navigation links (`/agents/`, `/environments/`, `/vaults/`) → `/managed/agents/`, `/managed/environments/`, `/managed/vaults/`
- Helper functions (`AgentDrawer`, `EnvDrawer`, `VaultDrawer`, `formatRelativeTime`) are defined inline — keep them inline

### Step 3: Port CreateSessionDialog

Source: `joysafeter-native/web/src/pages/sessions/CreateSessionDialog.tsx`

Key: internal links to manage agents/envs/vaults → `/managed/agents`, `/managed/environments`, `/managed/vaults`.

### Step 4: Commit

```bash
git add frontend/app/managed/sessions/
git commit -m "feat(managed): port sessions pages (list, detail, create dialog)"
```

---

## Task 7: Environments Pages

**Files:**
- Create: `frontend/app/managed/environments/page.tsx` (EnvironmentList)
- Create: `frontend/app/managed/environments/[envId]/page.tsx` (EnvironmentDetail)

### Step 1: Port EnvironmentList

Source: `joysafeter-native/web/src/pages/environments/EnvironmentList.tsx`

Standard adaptations. The create dialog is inline in this component (not a separate file). Navigation → `/managed/environments/{id}`.

### Step 2: Port EnvironmentDetail

Source: `joysafeter-native/web/src/pages/environments/EnvironmentDetail.tsx`

Adaptations:
- Page params: `{ params: { envId: string } }`
- `navigate("/environments")` → `router.push('/managed/environments')`
- `apiPost` for save → use JoySafeter's `apiPost`

### Step 3: Commit

```bash
git add frontend/app/managed/environments/
git commit -m "feat(managed): port environments pages (list, detail)"
```

---

## Task 8: Vaults Pages

**Files:**
- Create: `frontend/app/managed/vaults/page.tsx` (VaultList)
- Create: `frontend/app/managed/vaults/[vaultId]/page.tsx` (VaultDetail)
- Create: `frontend/app/managed/vaults/components/create-vault-dialog.tsx`
- Create: `frontend/app/managed/vaults/components/create-credential-dialog.tsx`

### Step 1: Port VaultList

Source: `joysafeter-native/web/src/pages/vaults/VaultList.tsx`

Standard adaptations. Navigation → `/managed/vaults/{id}`.

### Step 2: Port VaultDetail

Source: `joysafeter-native/web/src/pages/vaults/VaultDetail.tsx`

Adaptations:
- Page params: `{ params: { vaultId: string } }`
- Back navigation → `/managed/vaults`
- Breadcrumb link → `/managed/vaults`

### Step 3: Port CreateVaultDialog and CreateCredentialDialog

Source: `joysafeter-native/web/src/pages/vaults/CreateVaultDialog.tsx` and `CreateCredentialDialog.tsx`

Standard adaptations.

### Step 4: Commit

```bash
git add frontend/app/managed/vaults/
git commit -m "feat(managed): port vaults pages (list, detail, create dialogs)"
```

---

## Task 9: Quickstart Wizard

**Files:**
- Create: `frontend/app/managed/quickstart/page.tsx`
- Create: `frontend/hooks/managed/use-quickstart-chat.ts`

### Step 1: Port use-quickstart-chat hook

Source: `joysafeter-native/web/src/hooks/use-quickstart-chat.ts`

This is the most complex hook. Key adaptations:
- Replace `const BASE_URL = import.meta.env.VITE_API_BASE_URL || ""` with `import { API_BASE } from '@/lib/api-client'`
- Replace `getAuthHeaders()` (Bearer token) with cookie-based auth:
  ```typescript
  import { getCsrfToken } from '@/lib/auth/csrf'
  // In fetch calls:
  credentials: 'include',
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() || '' }
  ```
- Replace `localStorage.getItem(TOKEN_KEY)` token pattern with cookie-based approach
- `apiList` and `apiPost` → use JoySafeter's `apiGet` and `apiPost`

### Step 2: Port Quickstart page

Source: `joysafeter-native/web/src/pages/Quickstart.tsx` (~1237 lines)

Key adaptations beyond the standard ones:
- `useNavigate()` → `useRouter()` from next/navigation
- `navigate('/sessions/...')` → `router.push('/managed/sessions/...')`
- `import yaml from "js-yaml"` — needs `js-yaml` added to dependencies
- `import { useSessionStream } from "@/lib/sse"` → `from '@/lib/managed/sse'`
- Session event components → `from '@/components/managed/session'`
- `apiList` calls → use `apiGet` with the same paths
- `apiPost` calls → use JoySafeter's `apiPost`
- `stripIdPrefix` → `from '@/lib/managed/id'`
- `useQuery` → same (already in JoySafeter)
- The sub-components (Stepper, ApiCard, ChatBubble, StepCompleteCard, TemplateCard, etc.) are all defined inline — keep them inline

### Step 3: Install js-yaml if needed

```bash
cd frontend && bun add js-yaml && bun add -D @types/js-yaml
```

### Step 4: Commit

```bash
git add frontend/app/managed/quickstart/ frontend/hooks/managed/use-quickstart-chat.ts
git commit -m "feat(managed): port quickstart wizard with AI chat flow"
```

---

## Task 10: i18n Translations

**Files:**
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/lib/i18n/locales/en.ts`

### Step 1: Add all managed agent translations

Add a `managed` section to both locale files. Copy the relevant keys from `joysafeter-native/web/src/i18n/zh.json` and organize them under a `managed` namespace.

Keys to add (under `managed` in the translation object):
- All `quickstart.*` keys
- All `agents.*` keys (prefix with `managed.agents.*` to avoid collision with existing JoySafeter agents)
- All `sessions.*` keys
- All `environments.*` keys
- All `vaults.*` keys
- All `filters.*` keys
- All `table.*` keys
- All `common.*` keys that don't exist yet

In the ported components, update `t('agents.title')` → `t('managed.agents.title')` etc. throughout all ported files.

### Step 2: Commit

```bash
git add frontend/lib/i18n/locales/
git commit -m "feat(managed): add zh/en translations for managed agents section"
```

---

## Task 11: Route Layout and Dependencies Check

**Files:**
- Create: `frontend/app/managed/layout.tsx`
- Modify: `frontend/package.json` (if needed)

### Step 1: Create managed layout

Create `frontend/app/managed/layout.tsx`:

```tsx
export default function ManagedLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
```

This is a pass-through layout. The main app layout (with sidebar) already wraps everything.

### Step 2: Check dependencies

Verify these packages exist in `package.json`. If not, install:
- `date-fns` (for RelativeTime)
- `js-yaml` + `@types/js-yaml` (for Quickstart YAML preview)
- `react-markdown` + `remark-gfm` (for EventDetail transcript view — likely already present)

```bash
cd frontend && cat package.json | grep -E "date-fns|js-yaml|react-markdown|remark-gfm"
```

Install any missing ones.

### Step 3: Commit

```bash
git add frontend/app/managed/layout.tsx frontend/package.json frontend/bun.lock
git commit -m "feat(managed): add route layout and verify dependencies"
```

---

## Task 12: Smoke Test and Fix Build Errors

### Step 1: Run type check

```bash
cd frontend && bun run type-check
```

Fix any TypeScript errors. Common expected issues:
- Missing shadcn/ui component variants (e.g., `Badge` might not have `success` variant — adapt to use existing variants)
- `DropdownMenuItem` might not have `destructive` prop — check JoySafeter's dropdown-menu component
- Path alias resolution

### Step 2: Run dev server

```bash
cd frontend && bun dev
```

Navigate to `/managed/quickstart`, `/managed/agents`, `/managed/sessions`, `/managed/environments`, `/managed/vaults` and verify:
- Pages load without errors
- Sidebar shows collapsible group
- Active state highlights correctly

### Step 3: Fix any runtime issues and commit

```bash
git add -A
git commit -m "fix(managed): resolve build errors and type issues from migration"
```

---

## Summary of File Creation

| # | Files | Source |
|---|-------|--------|
| 1 | 5 files: types, utils, SSE, pagination hook | `lib/types.ts`, `lib/id.ts`, `lib/filters.ts`, `lib/sse.ts`, `hooks/use-paginated-list.ts` |
| 2 | 9 files: shared components | `components/shared/*`, `components/layout/PageHeader.tsx` |
| 3 | 7 files: session event components | `components/session/*` |
| 4 | 3 files modified: sidebar + i18n | `app-sidebar.tsx`, locale files |
| 5 | 4 files: agents pages | `pages/agents/*` |
| 6 | 3 files: sessions pages | `pages/sessions/*` |
| 7 | 2 files: environments pages | `pages/environments/*` |
| 8 | 4 files: vaults pages | `pages/vaults/*` |
| 9 | 2 files: quickstart | `pages/Quickstart.tsx`, `hooks/use-quickstart-chat.ts` |
| 10 | 2 files modified: translations | locale files |
| 11 | 2 files: layout + deps | layout, package.json |
| 12 | Fix pass | — |

**Total: ~42 new files + 5 modified files**

## Key Adaptation Checklist (apply to every ported file)

- [ ] `'use client'` directive at top
- [ ] `useNavigate()` → `useRouter()` from `next/navigation`
- [ ] `navigate(path)` → `router.push(path)`
- [ ] `useParams()` → Next.js page `params` prop
- [ ] `NavLink` → `Link` from `next/link`
- [ ] `useTranslation` from `react-i18next` → from `@/lib/i18n`
- [ ] Type imports → `@/types/managed`
- [ ] Shared component imports → `@/components/managed/shared`
- [ ] Session components → `@/components/managed/session`
- [ ] `stripIdPrefix` → `@/lib/managed/id`
- [ ] `filterByCreatedTime` → `@/lib/managed/filters`
- [ ] `useSessionStream` → `@/lib/managed/sse`
- [ ] `usePaginatedList` → `@/hooks/managed/use-paginated-list`
- [ ] `apiFetch/apiPost/apiDelete/apiList` → `apiGet/apiPost/apiDelete` from `@/lib/api-client`
- [ ] All internal routes prefixed with `/managed/`
- [ ] Auth: remove `getAuthHeaders()` / Bearer token → `credentials: 'include'` + CSRF
- [ ] `import.meta.env.VITE_*` → use `API_BASE` from `@/lib/api-client`
- [ ] i18n keys namespaced under `managed.*`
