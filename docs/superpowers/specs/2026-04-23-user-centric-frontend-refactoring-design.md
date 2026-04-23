# User-Centric Frontend Refactoring Design

## Context

JoySafeter is a multi-agent platform. The current frontend exposes six concepts (Agent, Task, Thread, Run, Version, Release) across scattered navigation paths. New users face high cognitive load, unclear concept relationships, and redundant navigation. This refactoring redesigns the frontend presentation architecture from the user's perspective.

## Target Users

Both technical users (developers) and business users (product managers, operators), served through progressive disclosure — simple mode by default, advanced features accessible on demand.

## Core Flow

Task-driven: Create Agent → Assign Task → View Results.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Core flow | Task-first | Users primarily assign work and check results |
| Concept model | Three-layer (Agent, Task, Chat) | Reduce six concepts to three user-facing ones |
| Navigation | Dashboard + dual entry (Agents, Tasks) | Global overview + clear separation of concerns |
| Agent detail | Three tabs (Overview, Chat, Settings) | Reduce information density, progressive disclosure |
| Task ↔ Run | Task embeds execution results | Users see results without navigating away |
| Implementation | Top-down (nav → pages → components) | Each layer is usable when complete |

---

## 1. Information Architecture & Concept Model

### Three-Layer User-Facing Concepts

| Layer | Concept | User Understanding | Internal Model |
|-------|---------|-------------------|----------------|
| Core | Agent | "AI that does work for me" | Agent |
| Core | Task | "Work I want it to do" | Task + Run + Execution |
| Auxiliary | Chat | "Talk to AI for debugging" | Thread |
| Hidden | Version/Release | Config management in advanced settings | Version + Release |

### Principles

- Users only need to understand: **Create Agent → Assign Task → View Results**
- Run/Execution invisible to users, merged into Task's "execution history"
- Thread (chat) demoted to Agent auxiliary feature, absent from main navigation
- Version/Release moved into Agent settings, for advanced users only

### Sidebar Navigation

```
Dashboard
─────────────
Agents
Tasks
─────────────
Skills
Tools
─────────────
Settings
```

- Memory removed from sidebar entirely. `/memory` route removed, redirects to `/settings`. Memory-related features deferred to future iteration — not merged into Settings now.
- Dashboard becomes default landing page, replacing current blank redirect
- Navigation items reduced from 6 to 5 with clearer grouping

---

## 2. Dashboard

New landing page replacing the current empty redirect to `/agents`.

### Layout

```
┌─────────────────────────────────────────────┐
│  Welcome back, {username}                    │
├──────────────────┬──────────────────────────┤
│  Needs Attention  │  Recent Tasks            │
│  ┌────────────┐  │  ┌──────────────────────┐│
│  │ Approval x3 │  │  │ Task A  ● Running    ││
│  │ Failed x1   │  │  │ Task B  ✓ Completed  ││
│  │ Stuck x2    │  │  │ Task C  ✗ Failed     ││
│  └────────────┘  │  │ Task D  ○ Pending    ││
│                  │  └──────────────────────┘│
├──────────────────┴──────────────────────────┤
│  Active Agents                               │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ Agent A  │ │ Agent B  │ │ Agent C  │       │
│  │ 3 tasks  │ │ 1 task   │ │ idle     │       │
│  └─────────┘ └─────────┘ └─────────┘       │
└─────────────────────────────────────────────┘
```

### Three Sections

1. **Needs Attention** — Aggregates items requiring user intervention: pending approvals, failed executions, timed-out tasks. First thing users should see.
2. **Recent Tasks** — Last 10 tasks with execution status labels. Click to enter Task detail. Replaces scattered Run lists.
3. **Active Agents** — Agent cards with active task counts. Idle agents greyed out.

### Design Points

- Dashboard is an "action hub" — every section is clickable
- Empty state for new users shows onboarding: "Create your first Agent"
- No Run/Execution concepts exposed; task status uses user-friendly language (Running/Completed/Failed)

---

## 3. Agent Detail Page

### New Three-Tab Structure

```
[ Overview ]  [ Chat ]  [ Settings ]
```

### Overview Tab

```
┌─────────────────────────────────────────────┐
│  Agent Name                                  │
│  Description text...                         │
│                                              │
│  ┌──────────────┐  ┌──────────────┐         │
│  │  📋 Assign    │  │  💬 Chat      │         │
│  │     Task      │  │              │         │
│  └──────────────┘  └──────────────┘         │
├─────────────────────────────────────────────┤
│  Recent Activity                             │
│  ┌─────────────────────────────────────────┐│
│  │ Task "Data Report"  ● Running  2m ago   ││
│  │ Task "Weekly Sum"   ✓ Done    1h ago    ││
│  │ Chat "Debug prompt" ○ 3 msgs  yesterday ││
│  └─────────────────────────────────────────┘│
└─────────────────────────────────────────────┘
```

- Two action buttons: Assign Task (primary), Chat (secondary) — reflects task-driven priority
- "Recent Activity" merges Task executions and chat records in reverse chronological order
- No Draft/Release information shown

### Chat Tab

- Thread list + conversation interface
- Current `/agents/[agentId]/threads` content absorbed here
- Users see "Chat", not "Thread"

### Settings Tab

- Agent basic info editing (name, description, avatar)
- Definition method (prompt / visual orchestration) — current Build tab content
- Version management — collapsible section
- Release management — collapsible section
- Advanced users expand as needed; regular users ignore

### Route Changes

| Current Route | New Route | Notes |
|--------------|-----------|-------|
| `/agents/[id]` | `/agents/[id]` | Overview tab (unchanged) |
| `/agents/[id]/threads` | `/agents/[id]?tab=chat` | Absorbed into Chat tab |
| `/agents/[id]/threads/[tid]` | `/agents/[id]?tab=chat&thread=[tid]` | Chat detail |
| `/agents/[id]/build` | `/agents/[id]?tab=settings` | Absorbed into Settings |
| `/agents/[id]/versions` | `/agents/[id]?tab=settings` | Absorbed into Settings |
| `/agents/[id]/releases` | `/agents/[id]?tab=settings` | Absorbed into Settings |
| `/agents/[id]/runs` | Removed | Embedded in Overview and Task |
| `/agents/[id]/runs/[rid]` | Removed | Embedded in Task detail |
| `/agents/[id]/edit` | `/agents/[id]?tab=settings` | Absorbed into Settings |
| `/agents/[id]/tasks` | Removed | Use global `/tasks?agent=[id]` with agent filter |

---

## 4. Task with Embedded Execution Results

### Task Detail Panel

```
┌─────────────────────────────────────────────┐
│  Task: Generate Weekly Report                │
│  Agent: Data Analyst    Priority: High       │
│  Status: ● Running                           │
├─────────────────────────────────────────────┤
│  [ Execution ]  [ Description ]  [ Activity ]│
├─────────────────────────────────────────────┤
│  Execution (live)                            │
│  ┌─────────────────────────────────────────┐│
│  │ 14:03  🔧 Tool: query_database          ││
│  │ 14:03  💭 Analyzing last week's data... ││
│  │ 14:04  🔧 Tool: generate_chart          ││
│  │ 14:05  📄 Output: weekly_report.md      ││
│  │ ● Running...                             ││
│  └─────────────────────────────────────────┘│
├─────────────────────────────────────────────┤
│  Result                                      │
│  ┌─────────────────────────────────────────┐│
│  │ (Agent's final output displayed here)    ││
│  └─────────────────────────────────────────┘│
├─────────────────────────────────────────────┤
│  Execution History (3 total)                 │
│  #3 ● Running   14:03                       │
│  #2 ✗ Failed    Yesterday 09:30  [Retry]    │
│  #1 ✓ Completed 2 days ago 16:20 [View]     │
└─────────────────────────────────────────────┘
```

### Design Points

- Default tab is "Execution", not "Description" — users care about results after assigning
- Live streaming of execution events, reusing existing ExecutionEvent data (text, tool_use, thinking, artifact) with user-friendly presentation
- "Execution History" collapsed at bottom, shows all Run records as "Execution #N"
- Failed executions offer "Retry" button, triggering a new Run
- Approval requests rendered inline with action buttons, no navigation away

### Task Board/List Changes

- Task cards show latest execution status label (Running/Completed/Failed)
- Click opens right-side detail panel (existing interaction preserved) with new layout
- Remove links to standalone Run pages from task cards

### Concept Mapping

| User Sees | Internal Model |
|-----------|---------------|
| Execution process | ExecutionEvent stream |
| Result | Run's final output |
| Execution #N | AgentRun record |
| Retry | Create new AgentRun |
| Awaiting Approval | approval_request ExecutionEvent |

---

## 5. i18n & Terminology

### Terminology Standard

| Concept | English | 中文 | Deprecated Terms |
|---------|---------|------|-----------------|
| Agent | Agent | Agent（不翻译） | 助手、智能体、自治体 |
| Task | Task | 任务 | 工单、事项 |
| Execution | Execution | 执行 | Run、运行、运行记录 |
| Chat | Chat | 对话 | Thread、会话、线程 |
| Version | Version | 版本 | Draft、草稿 |
| Release | Release | 发布 | 上线、激活 |
| Dashboard | Dashboard | Dashboard（不翻译） | 首页、主页 |
| Skill | Skill | 技能 | — |
| Tool | Tool | 工具 | — |

### Principles

- Agent and Dashboard stay in English — universally understood by target users
- "Run" removed from all user-facing UI, replaced with "Execution" / "执行"
- "Thread" removed from all user-facing UI, replaced with "Chat" / "对话"
- Chinese locale prefers Chinese, but technical concepts (Agent, Dashboard, Skill) stay English

### i18n File Changes

- `sidebar.*` — navigation item names updated; add new key `sidebar.dashboard`
- New `dashboard.*` — Dashboard page copy
- `runs.*` → `execution.*` — namespace rename
- `threads.*` → `chat.*` — rename; the existing `chat.*` keys (used by copilot feature) should be moved to `copilot.*` namespace to avoid collision
- `agents.detail.*` — Agent detail tab names and content
- `tasks.detail.*` — new execution-related copy

### Status Labels

| Internal Status | 中文 | English |
|----------------|------|---------|
| pending | 待执行 | Pending |
| running | 执行中 | Running |
| succeeded | 已完成 | Completed |
| failed | 失败 | Failed |
| cancelled | 已取消 | Cancelled |
| approval_wait | 等待审批 | Awaiting Approval |

---

## 6. Onboarding & Empty States

### Dashboard Empty State (First Login)

```
┌─────────────────────────────────────────────┐
│                                              │
│         Welcome to JoySafeter                │
│                                              │
│    Create your first Agent to start          │
│    automating workflows                      │
│                                              │
│         [ Create Agent ]                     │
│                                              │
│    ┌──────┐  ┌──────┐  ┌──────┐             │
│    │ 1    │  │ 2    │  │ 3    │             │
│    │Create │  │Assign │  │View  │             │
│    │Agent  │  │Task   │  │Result│             │
│    └──────┘  └──────┘  └──────┘             │
│                                              │
└─────────────────────────────────────────────┘
```

- Three-step flow diagram for immediate understanding of core loop
- Single CTA button, no decision paralysis

### Agent List Empty State

```
No Agents yet
Create an Agent to handle repetitive work for you
[ Create Agent ]
```

### Task List Empty State

```
No Tasks yet
Pick an Agent and assign it a task
[ View Agents → ]
```

### Agent Creation Simplification

- Creation dialog: only name + description, default to "prompt" definition
- Definition method selection moved to Agent Settings tab
- After creation, redirect to Agent overview with prompt: "Try assigning your first task"

### Guided Flow

```
First login → Dashboard empty state → Click "Create Agent"
→ Simplified dialog (name + description) → Agent overview
→ Overview prompts "Assign a task" → Task creation dialog
→ Task executing → User sees live execution
```

Core flow completed in under 4 clicks.

---

## 7. Route Structure

### Final Routes

| Route | Page | Notes |
|-------|------|-------|
| `/` | Redirect | → `/dashboard` (auth) or `/signin` |
| `/dashboard` | Dashboard | New landing page |
| `/agents` | Agent list | Preserved |
| `/agents/[id]` | Agent overview | Simplified overview tab |
| `/agents/[id]?tab=chat` | Agent chat | Absorbed from threads |
| `/agents/[id]?tab=chat&thread=[tid]` | Chat detail | Absorbed from thread detail |
| `/agents/[id]?tab=settings` | Agent settings | Merged build/versions/releases/edit |
| `/tasks` | Task center | Board/list + embedded execution |
| `/skills` | Skills marketplace | Preserved |
| `/tools` | Tool integration | Preserved |
| `/settings` | Global settings | Preserved |

### Removed Routes (with redirects)

| Removed Route | Redirect To |
|--------------|-------------|
| `/agents/[id]/threads` | `/agents/[id]?tab=chat` |
| `/agents/[id]/threads/[tid]` | `/agents/[id]?tab=chat&thread=[tid]` |
| `/agents/[id]/build` | `/agents/[id]?tab=settings` |
| `/agents/[id]/versions` | `/agents/[id]?tab=settings` |
| `/agents/[id]/releases` | `/agents/[id]?tab=settings` |
| `/agents/[id]/runs` | `/agents/[id]` |
| `/agents/[id]/runs/[rid]` | `/agents/[id]` |
| `/agents/[id]/edit` | `/agents/[id]?tab=settings` |
| `/agents/[id]/tasks` | `/tasks?agent=[id]` |
| `/runs` | `/dashboard` |
| `/memory` | `/settings` |

### Compatibility

- Old routes handled via Next.js `next.config.js` `redirects` config (build-time, static) for simple path-to-path mappings. For dynamic routes with parameters (e.g., `[agentId]`, `[threadId]`), use Next.js middleware redirect logic added to the existing `frontend/middleware.ts`.
- `/dashboard` must be added to `ALLOWED_REDIRECT_PATHS` in `frontend/middleware.ts` to support auth callback redirects.
- API layer unchanged — frontend routing and presentation only
