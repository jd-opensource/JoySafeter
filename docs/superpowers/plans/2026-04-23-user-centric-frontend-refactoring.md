# User-Centric Frontend Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the frontend presentation architecture from user's perspective — simplify six concepts to three, add Dashboard, restructure Agent detail, embed execution results in Tasks, unify i18n.

**Architecture:** Top-down refactoring: navigation layer first (Dashboard + sidebar), then page-level restructuring (Agent detail 3-tab, Task embedded execution), then cross-cutting concerns (i18n, redirects, empty states). Each layer produces a usable state.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS, Radix UI, React Query, Zustand, i18next

**Spec:** `docs/superpowers/specs/2026-04-23-user-centric-frontend-refactoring-design.md`

---

## File Structure

### New Files
- `frontend/app/dashboard/page.tsx` — Dashboard landing page
- `frontend/app/dashboard/loading.tsx` — Dashboard loading state
- `frontend/components/dashboard/needs-attention.tsx` — Attention items aggregation
- `frontend/components/dashboard/recent-tasks.tsx` — Recent tasks with execution status
- `frontend/components/dashboard/active-agents.tsx` — Active agent cards
- `frontend/components/dashboard/empty-state.tsx` — New user onboarding
- `frontend/components/agents/agent-overview-tab.tsx` — Simplified overview
- `frontend/components/agents/agent-chat-tab.tsx` — Chat tab (absorbed threads)
- `frontend/components/agents/agent-settings-tab.tsx` — Settings tab (absorbed build/versions/releases)
- `frontend/components/tasks/task-execution-panel.tsx` — Embedded execution view
- `frontend/components/tasks/task-execution-history.tsx` — Execution history list

### Modified Files
- `frontend/middleware.ts` — Add `/dashboard` to ALLOWED_REDIRECT_PATHS, add legacy route redirects
- `frontend/next.config.ts` — Add static route redirects
- `frontend/app/page.tsx` — Redirect to `/dashboard` instead of `/agents`
- `frontend/components/app-sidebar/app-sidebar.tsx` — Restructure menu groups
- `frontend/app/agents/[agentId]/layout.tsx` — Change tabs to Overview/Chat/Settings
- `frontend/app/agents/[agentId]/page.tsx` — Simplified overview with two action buttons + recent activity
- `frontend/components/agents/agent-form-dialog.tsx` — Simplify to name+description only
- `frontend/components/tasks/task-detail-panel.tsx` — Add execution tab as default
- `frontend/lib/i18n/locales/en.ts` — Namespace renames, new keys
- `frontend/lib/i18n/locales/zh.ts` — Namespace renames, new keys

### Removed Routes (replaced by redirects)
- `frontend/app/agents/[agentId]/threads/` → `?tab=chat`
- `frontend/app/agents/[agentId]/build/` → `?tab=settings`
- `frontend/app/agents/[agentId]/versions/` → `?tab=settings`
- `frontend/app/agents/[agentId]/releases/` → `?tab=settings`
- `frontend/app/agents/[agentId]/runs/` → overview
- `frontend/app/agents/[agentId]/edit/` → `?tab=settings`
- `frontend/app/agents/[agentId]/tasks/` → `/tasks?agent=[id]`
- `frontend/app/runs/` → `/dashboard`
- `frontend/app/memory/` → `/settings`

---

## Task 1: Sidebar Navigation Restructure

**Files:**
- Modify: `frontend/components/app-sidebar/app-sidebar.tsx:33-52`
- Modify: `frontend/lib/i18n/locales/en.ts:20-42`
- Modify: `frontend/lib/i18n/locales/zh.ts:20-43`

- [ ] **Step 1: Update i18n sidebar keys in en.ts**

Change the sidebar section to match new navigation structure:
- `sidebar.dashboard` value from `'AgentSpark'` to `'Dashboard'`
- `sidebar.myAgents` to `sidebar.agents` with value `'Agents'`
- `sidebar.taskCenter` to `sidebar.tasks` with value `'Tasks'`
- Remove `sidebar.memory` key
- Keep `sidebar.skillsHub`, `sidebar.toolsAndMcp`, `sidebar.settings`

- [ ] **Step 2: Update i18n sidebar keys in zh.ts**

Mirror the en.ts changes:
- `sidebar.dashboard`: `'Dashboard'`
- `sidebar.agents`: `'Agents'`
- `sidebar.tasks`: `'Tasks'`
- Remove `sidebar.memory`

- [ ] **Step 3: Restructure menuGroups in app-sidebar.tsx**

Replace the `menuGroups` constant (lines 33-52) with new structure:

```typescript
const menuGroups: MenuGroup[] = [
  {
    items: [
      { label: 'sidebar.dashboard', icon: LayoutDashboard, href: '/dashboard' },
    ],
  },
  {
    items: [
      { label: 'sidebar.agents', icon: Bot, href: '/agents' },
      { label: 'sidebar.tasks', icon: ListChecks, href: '/tasks' },
    ],
  },
  {
    items: [
      { label: 'sidebar.skillsHub', icon: Sparkles, href: '/skills' },
      { label: 'sidebar.toolsAndMcp', icon: Wrench, href: '/tools' },
    ],
  },
  {
    items: [
      { label: 'sidebar.settings', icon: Settings, href: '/settings' },
    ],
  },
];
```

Add `LayoutDashboard` to the lucide-react imports.

- [ ] **Step 4: Update all components referencing old sidebar i18n keys**

Search for `sidebar.myAgents`, `sidebar.taskCenter`, `sidebar.memory` across the codebase and update references.

- [ ] **Step 5: Verify sidebar renders correctly**

Run dev server — sidebar should show Dashboard / Agents / Tasks / Skills / Tools / Settings.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/app-sidebar/ frontend/lib/i18n/locales/
git commit -m "refactor: restructure sidebar navigation — Dashboard + Agents + Tasks"
```

---

## Task 2: Dashboard Page — Scaffold & Empty State

**Files:**
- Create: `frontend/app/dashboard/page.tsx`
- Create: `frontend/app/dashboard/loading.tsx`
- Create: `frontend/components/dashboard/empty-state.tsx`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/middleware.ts:16-29`

- [ ] **Step 1: Add `/dashboard` to ALLOWED_REDIRECT_PATHS**

In `frontend/middleware.ts`, add `'/dashboard'` to the `ALLOWED_REDIRECT_PATHS` array (line 16-29).

- [ ] **Step 2: Create Dashboard loading state**

Create `frontend/app/dashboard/loading.tsx` with a centered spinner.

- [ ] **Step 3: Create Dashboard empty state component**

Create `frontend/components/dashboard/empty-state.tsx` — onboarding view for new users with:
- Welcome title and subtitle
- Single CTA "Create Agent" button → navigates to `/agents`
- Three-step flow icons: Create Agent → Assign Task → View Results

- [ ] **Step 4: Create Dashboard page**

Create `frontend/app/dashboard/page.tsx`:
- Fetch agents via `useAgents()` hook
- If no agents → render `<DashboardEmptyState />`
- If has agents → render page title placeholder (data sections added in Task 3)

- [ ] **Step 5: Update root redirect**

In `frontend/app/page.tsx`, change authenticated redirect from `/agents` to `/dashboard`.

- [ ] **Step 6: Add dashboard i18n keys**

Add `dashboard` namespace to both `en.ts` and `zh.ts`:
- `dashboard.title`: `'Dashboard'` / `'Dashboard'`
- `dashboard.onboarding.title`: `'Welcome to JoySafeter'` / `'欢迎使用 JoySafeter'`
- `dashboard.onboarding.subtitle`: `'Create your first Agent...'` / `'创建你的第一个 Agent...'`
- `dashboard.onboarding.createAgent`: `'Create Agent'` / `'创建 Agent'`
- `dashboard.onboarding.step1-3`: Create Agent / Assign Task / View Results

- [ ] **Step 7: Verify Dashboard renders**

Dev server: `/dashboard` shows empty state. Root `/` redirects to `/dashboard`.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/dashboard/ frontend/components/dashboard/ frontend/app/page.tsx frontend/middleware.ts frontend/lib/i18n/locales/
git commit -m "feat: add Dashboard page with empty state onboarding"
```

---

## Task 3: Dashboard Data Sections

**Files:**
- Create: `frontend/components/dashboard/needs-attention.tsx`
- Create: `frontend/components/dashboard/recent-tasks.tsx`
- Create: `frontend/components/dashboard/active-agents.tsx`
- Modify: `frontend/app/dashboard/page.tsx`

- [ ] **Step 1: Create NeedsAttention component**

Create `frontend/components/dashboard/needs-attention.tsx`:
- Fetch tasks with status `in_review` (awaiting approval) and runs with status `failed`
- Display as a card with categorized counts: "Awaiting Approval x3", "Failed x1"
- Each item clickable → navigates to the relevant task detail
- Empty state: show a subtle "All clear" message

- [ ] **Step 2: Create RecentTasks component**

Create `frontend/components/dashboard/recent-tasks.tsx`:
- Fetch last 10 tasks ordered by latest execution time
- Each row: task title, assigned agent name, execution status badge (Running/Completed/Failed/Pending), relative time
- Click row → navigate to `/tasks` with task selected
- Use existing status badge styles from `types/agent-run.ts:37-45`

- [ ] **Step 3: Create ActiveAgents component**

Create `frontend/components/dashboard/active-agents.tsx`:
- Fetch all agents, filter to those with active runs or recent tasks
- Display as horizontal card row: agent avatar + name + active task count
- Idle agents greyed out with "idle" label
- Click card → navigate to `/agents/[id]`

- [ ] **Step 4: Wire components into Dashboard page**

Update `frontend/app/dashboard/page.tsx`:
- Two-column layout top: NeedsAttention (left), RecentTasks (right)
- Full-width bottom: ActiveAgents
- Add welcome greeting: `t('dashboard.welcome', { name: user.name })`

- [ ] **Step 5: Add remaining dashboard i18n keys**

Add to both `en.ts` and `zh.ts`:
- `dashboard.welcome`: `'Welcome back, {{name}}'` / `'欢迎回来, {{name}}'`
- `dashboard.needsAttention`: `'Needs Attention'` / `'需要关注'`
- `dashboard.recentTasks`: `'Recent Tasks'` / `'最近任务'`
- `dashboard.activeAgents`: `'Active Agents'` / `'活跃 Agents'`
- `dashboard.allClear`: `'All clear'` / `'一切正常'`
- `dashboard.idle`: `'idle'` / `'空闲'`
- `dashboard.viewAll`: `'View all'` / `'查看全部'`

- [ ] **Step 6: Verify Dashboard with data**

Dev server: Dashboard shows all three sections with real data. Empty sections show appropriate fallbacks.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/dashboard/ frontend/app/dashboard/ frontend/lib/i18n/locales/
git commit -m "feat: add Dashboard data sections — attention, recent tasks, active agents"
```

---

## Task 4: Agent Detail Page — Three-Tab Restructure

**Files:**
- Modify: `frontend/app/agents/[agentId]/layout.tsx:14-18`
- Modify: `frontend/app/agents/[agentId]/page.tsx`
- Create: `frontend/components/agents/agent-overview-tab.tsx`
- Create: `frontend/components/agents/agent-chat-tab.tsx`
- Create: `frontend/components/agents/agent-settings-tab.tsx`

- [ ] **Step 1: Update layout tab navigation**

In `frontend/app/agents/[agentId]/layout.tsx`, replace `NAV_ITEMS` (lines 14-18):

```typescript
const NAV_ITEMS = [
  { label: 'agents.detail.tabs.overview', href: '' },
  { label: 'agents.detail.tabs.chat', href: '?tab=chat' },
  { label: 'agents.detail.tabs.settings', href: '?tab=settings' },
];
```

Update tab navigation logic to use `searchParams` (`tab` query param) instead of path-based routing. Replace `usePathname()` active-tab detection with `useSearchParams()` from `next/navigation`. Active tab determined by `searchParams.get('tab')` — default is overview. Remove the `labelEn` field from `NAV_ITEMS` type if present.

- [ ] **Step 2: Create AgentOverviewTab component**

Create `frontend/components/agents/agent-overview-tab.tsx`:
- Agent description display
- Two action buttons: "Assign Task" (primary, opens task create dialog) and "Chat" (secondary, switches to chat tab)
- "Recent Activity" section: merged list of recent task executions and chat sessions, sorted by time
- Fetch recent runs via `useAgentRuns(agentId)` and threads via `useThreads(agentId)`
- Each activity item: icon (task/chat), title, status badge, relative time

- [ ] **Step 3: Create AgentChatTab component**

Create `frontend/components/agents/agent-chat-tab.tsx`:
- Absorb content from current `frontend/app/agents/[agentId]/threads/page.tsx` and `frontend/app/agents/[agentId]/threads/[threadId]/page.tsx`
- Left panel: thread list (reuse `ThreadList` component)
- Right panel: conversation view (reuse `ConversationView` component)
- "New Chat" button to create thread
- Handle `thread` query param for deep linking: `?tab=chat&thread=[tid]`

- [ ] **Step 4: Create AgentSettingsTab component**

Create `frontend/components/agents/agent-settings-tab.tsx`:
- Section 1: Basic info editing (name, description, avatar) — absorb from current edit page
- Section 2: Definition method (prompt/graph) — absorb from current build page
- Section 3: Version management — collapsible, absorb from versions page
- Section 4: Release management — collapsible, absorb from releases page
- Each section uses `Collapsible` from Radix UI, sections 3-4 collapsed by default

- [ ] **Step 5: Update Agent detail page to render tabs**

Rewrite `frontend/app/agents/[agentId]/page.tsx`:
- Read `searchParams.tab` to determine active tab
- Render `AgentOverviewTab` (default), `AgentChatTab`, or `AgentSettingsTab`
- Pass `agentId` as prop to each tab component

- [ ] **Step 6: Add agent detail i18n keys**

Add to both locale files:
- `agents.detail.tabs.overview`: `'Overview'` / `'概览'`
- `agents.detail.tabs.chat`: `'Chat'` / `'对话'`
- `agents.detail.tabs.settings`: `'Settings'` / `'设置'`
- `agents.detail.assignTask`: `'Assign Task'` / `'派任务'`
- `agents.detail.startChat`: `'Chat'` / `'开始对话'`
- `agents.detail.recentActivity`: `'Recent Activity'` / `'最近活动'`

- [ ] **Step 7: Verify all three tabs work**

Dev server: Agent detail page shows three tabs. Overview shows actions + activity. Chat shows thread list + conversation. Settings shows collapsible sections.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/agents/[agentId]/ frontend/components/agents/ frontend/lib/i18n/locales/
git commit -m "refactor: Agent detail page — three-tab structure (Overview/Chat/Settings)"
```

---

## Task 5: Task Detail — Embedded Execution Results

**Files:**
- Create: `frontend/components/tasks/task-execution-panel.tsx`
- Create: `frontend/components/tasks/task-execution-history.tsx`
- Modify: `frontend/components/tasks/task-detail-panel.tsx`

- [ ] **Step 1: Create TaskExecutionPanel component**

Create `frontend/components/tasks/task-execution-panel.tsx`:
- Accepts `taskId` and `latestRunId` props
- Fetches execution events for the latest run via existing `useExecutionEvents` hook
- Renders live streaming execution events:
  - `tool_use` → tool icon + tool name
  - `thinking` → thought bubble icon + text
  - `text` → text content
  - `artifact` → document icon + artifact name
  - `approval_request` → inline approve/reject buttons
- Auto-scrolls to bottom as new events arrive
- Shows "Running..." indicator when execution is active
- Shows final result section when execution completes

- [ ] **Step 2: Create TaskExecutionHistory component**

Create `frontend/components/tasks/task-execution-history.tsx`:
- Accepts `taskId` prop
- Fetches all runs for this task via `useAgentRuns({ taskId })`
- Renders numbered list: `#N status timestamp [Retry/View]`
- "Retry" button on failed runs → calls `createAgentRun` mutation
- "View" button on completed runs → switches execution panel to that run
- Collapsed by default, expandable

- [ ] **Step 3: Add execution tab to TaskDetailPanel**

Modify `frontend/components/tasks/task-detail-panel.tsx`:
- Add three sub-tabs at top: "Execution" (default), "Description", "Activity"
- "Execution" tab renders `TaskExecutionPanel` + `TaskExecutionHistory`
- "Description" tab renders existing task description content
- "Activity" tab renders existing activity/comments content
- Default to "Execution" tab when task has a latest run, otherwise "Description"

- [ ] **Step 4: Update task card status display**

In task card components, show the latest execution status badge (Running/Completed/Failed) alongside the task status, using the mapped status labels from the spec.

- [ ] **Step 5: Add task execution i18n keys**

Add to both locale files:
- `tasks.detail.tabs.execution`: `'Execution'` / `'执行过程'`
- `tasks.detail.tabs.description`: `'Description'` / `'描述'`
- `tasks.detail.tabs.activity`: `'Activity'` / `'活动记录'`
- `tasks.detail.executionHistory`: `'Execution History'` / `'历史执行'`
- `tasks.detail.retry`: `'Retry'` / `'重试'`
- `tasks.detail.viewResult`: `'View'` / `'查看结果'`
- `tasks.detail.running`: `'Running...'` / `'执行中...'`
- `tasks.detail.result`: `'Result'` / `'执行结果'`
- `tasks.detail.executionN`: `'Execution #{{n}}'` / `'第 {{n}} 次执行'`

- [ ] **Step 6: Verify task execution embedding**

Dev server: Open a task with runs → "Execution" tab shows live events. History section shows past runs. Retry button works on failed runs.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/tasks/ frontend/lib/i18n/locales/
git commit -m "feat: embed execution results in Task detail panel"
```

---

## Task 6: i18n Namespace Rename & Terminology Unification

**Files:**
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: all files referencing `runs.*` or `threads.*` i18n keys

- [ ] **Step 1: Rename `runs.*` namespace to `execution.*`**

In both `en.ts` and `zh.ts`:
- Rename the top-level `runs` key to `execution`
- Move the existing `runs.chat.*` sub-keys (lines 94-101 in en.ts) to `copilot.*` namespace to avoid collision
- Update all user-facing labels: replace "Run" with "Execution", "运行" with "执行"

- [ ] **Step 2: Rename `threads.*` namespace to `chat.*`**

In both locale files:
- Rename the top-level `threads` key to `chat`
- Verify no collision with the moved copilot keys

- [ ] **Step 3: Update all component references**

Search and replace across all `.tsx` files:
- `t('runs.` → `t('execution.`
- `t('threads.` → `t('chat.`
- Any direct references to the old `chat.*` copilot keys → `t('copilot.`

- [ ] **Step 4: Unify status labels**

Ensure all status displays use the standardized labels from the spec:
- pending → Pending / 待执行
- running → Running / 执行中
- succeeded → Completed / 已完成
- failed → Failed / 失败
- cancelled → Cancelled / 已取消
- approval_wait → Awaiting Approval / 等待审批

- [ ] **Step 5: Verify no broken i18n keys**

Run dev server, navigate through all pages. Check browser console for missing translation warnings. Fix any remaining references.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/i18n/locales/ frontend/components/ frontend/app/
git commit -m "refactor: unify i18n — runs→execution, threads→chat, standardize status labels"
```

---

## Task 7: Agent Creation Simplification

**Files:**
- Modify: `frontend/components/agents/agent-form-dialog.tsx:37-84`

- [ ] **Step 1: Simplify agent creation dialog**

In `frontend/components/agents/agent-form-dialog.tsx`:
- Remove the `definitionKind` selection from the creation form (lines 37-42)
- Keep only: name (required), description (optional), avatar (optional)
- Default `definition_kind` to `'prompt'` in the submit handler
- Remove `DEFINITION_KIND_OPTIONS` constant

- [ ] **Step 2: Update i18n keys if needed**

Remove or update any i18n keys related to definition kind selection in the creation dialog. Keep the labels for the Settings tab where definition kind will be editable.

- [ ] **Step 3: Verify simplified creation flow**

Dev server: Click "Create Agent" → dialog shows only name + description. Agent created with prompt definition by default.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/agents/agent-form-dialog.tsx frontend/lib/i18n/locales/
git commit -m "simplify: Agent creation — name + description only, default to prompt"
```

---

## Task 8: Route Redirects & Cleanup

**Files:**
- Modify: `frontend/next.config.ts`
- Modify: `frontend/middleware.ts`

- [ ] **Step 1: Add static redirects in next.config.ts**

Add redirects to `frontend/next.config.ts` for simple path-to-path mappings:

```typescript
async redirects() {
  return [
    { source: '/runs', destination: '/dashboard', permanent: true },
    { source: '/memory', destination: '/settings', permanent: true },
  ];
},
```

- [ ] **Step 2: Add dynamic redirects in middleware.ts**

Add redirect logic in `frontend/middleware.ts` for routes with dynamic parameters:

```typescript
// Legacy route redirects
const agentSubRouteRedirects: Record<string, string> = {
  '/threads': '?tab=chat',
  '/build': '?tab=settings',
  '/versions': '?tab=settings',
  '/releases': '?tab=settings',
  '/runs': '',
  '/edit': '?tab=settings',
  '/tasks': '', // will redirect to /tasks?agent=[id]
};
```

Match `/agents/[id]/threads/[tid]` → redirect to `/agents/[id]?tab=chat&thread=[tid]`.
Match `/agents/[id]/(threads|build|versions|releases|runs|edit)` → redirect to appropriate new route.
Match `/agents/[id]/tasks` → redirect to `/tasks?agent=[id]`.

- [ ] **Step 3: Remove old route directories**

Delete the old route directories so Next.js App Router doesn't resolve them before middleware redirects fire:

```bash
rm -rf frontend/app/agents/\[agentId\]/threads
rm -rf frontend/app/agents/\[agentId\]/build
rm -rf frontend/app/agents/\[agentId\]/versions
rm -rf frontend/app/agents/\[agentId\]/releases
rm -rf frontend/app/agents/\[agentId\]/runs
rm -rf frontend/app/agents/\[agentId\]/edit
rm -rf frontend/app/agents/\[agentId\]/tasks
rm -rf frontend/app/runs
rm -rf frontend/app/memory
```

These directories' functionality has been absorbed into the new tab components (Task 4) or redirected. Verify no imports reference these deleted files.

- [ ] **Step 4: Verify all legacy routes redirect correctly**

Test each old route in browser:
- `/runs` → `/dashboard`
- `/memory` → `/settings`
- `/agents/123/threads` → `/agents/123?tab=chat`
- `/agents/123/threads/456` → `/agents/123?tab=chat&thread=456`
- `/agents/123/build` → `/agents/123?tab=settings`
- `/agents/123/runs` → `/agents/123`

- [ ] **Step 5: Commit**

```bash
git add frontend/next.config.ts frontend/middleware.ts
git commit -m "feat: add legacy route redirects and remove old route directories"
```

---

## Task 9: Empty States for Agent & Task Lists

**Files:**
- Modify: `frontend/app/agents/page.tsx`
- Modify: `frontend/app/tasks/page.tsx`

- [ ] **Step 1: Update Agent list empty state**

In `frontend/app/agents/page.tsx`, update the empty state to show:
- "No Agents yet" heading
- "Create an Agent to handle repetitive work for you" subtitle
- "Create Agent" CTA button

- [ ] **Step 2: Update Task list empty state**

In `frontend/app/tasks/page.tsx`, update the empty state to show:
- "No Tasks yet" heading
- "Pick an Agent and assign it a task" subtitle
- "View Agents →" link button navigating to `/agents`

- [ ] **Step 3: Add empty state i18n keys**

Add to both locale files:
- `agents.emptyState.title` / `agents.emptyState.subtitle` / `agents.emptyState.cta`
- `tasks.emptyState.title` / `tasks.emptyState.subtitle` / `tasks.emptyState.cta`

- [ ] **Step 4: Verify empty states**

Dev server: With no agents, `/agents` shows proper empty state. With no tasks, `/tasks` shows proper empty state with link to agents.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/agents/page.tsx frontend/app/tasks/page.tsx frontend/lib/i18n/locales/
git commit -m "feat: add user-friendly empty states for Agent and Task lists"
```

---

## Task 10: Final Integration & Verification

**Files:**
- All modified files from Tasks 1-9

- [ ] **Step 1: Full navigation flow test**

Test the complete user journey:
1. `/` → redirects to `/dashboard`
2. Dashboard empty state → "Create Agent" → agent creation dialog (name + description only)
3. Agent created → agent overview with "Assign Task" + "Chat" buttons
4. "Assign Task" → task creation → task detail with execution tab
5. "Chat" → chat tab with thread list
6. Settings tab → collapsible version/release sections
7. Sidebar navigation: Dashboard / Agents / Tasks / Skills / Tools / Settings

- [ ] **Step 2: Legacy route redirect test**

Verify all old routes redirect correctly (list from Task 8 Step 3).

- [ ] **Step 3: i18n verification**

Switch between English and Chinese. Verify:
- No missing translation warnings in console
- All status labels use standardized terms
- "Run" and "Thread" do not appear in any user-facing text

- [ ] **Step 4: Build verification**

Run: `cd frontend && npx next build`
Expected: Build succeeds with no errors.

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: integration fixes for user-centric frontend refactoring"
```
