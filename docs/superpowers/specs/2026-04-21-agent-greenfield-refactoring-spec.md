# Agent Greenfield Refactoring Spec

Date: 2026-04-21
Status: Approved

## Overview

Rebuild the JoySafeter agent system from the approved greenfield domain model. Replace legacy tables, APIs, and frontend pages in 5 domain-ordered phases with no compatibility layer and no data migration.

## Decisions

| Decision | Choice |
|----------|--------|
| Migration strategy | Domain-batched Big Bang, no adapter layer |
| Graph system | Fully absorbed into AgentVersion (definition_kind: graph) |
| Mission system | Retained as product layer (Kanban UI), execution path switches to AgentRun → Execution |
| Legacy tables | Delete and rebuild, no data migration |
| Preserved systems | Auth/Workspace, Skills/MCP/Models, runtime infrastructure, frontend base components |
| API versioning | Replace v1 routes in-place |

## Design Deviations from Approved Domain Model

The approved domain model (2026-04-20) defines `AgentRuntime` as a separate entity and `AgentDraft` backed by the existing `graphs` table. This spec makes two intentional simplifications for the greenfield rewrite:

1. **AgentRuntime absorbed into AgentRelease**: Runtime configuration is stored as `agent_releases.runtime_binding` JSONB rather than a separate table. Rationale: runtime config is tightly coupled to a release (same runtime kind, same env vars, same concurrency limits). A separate table adds join complexity with no independent lifecycle benefit.

2. **AgentDraft replaced by AgentVersion with status: draft**: Instead of reusing the existing `graphs` table, the draft is a `agent_versions` row with `status = 'draft'`. Rationale: since we are deleting all legacy tables with no data migration, there is no reuse benefit. A unified version table is simpler.

## Deployment Strategy

All 5 phases ship as a **single deployment on a feature branch**. The system will be rebuilt entirely before going live. There is no incremental rollout — the old agent system and the new agent system never coexist in production. Development proceeds phase-by-phase for code organization, but the merge to main happens once all phases are complete and tested.

This means:
- No downtime management needed per phase
- No in-flight execution handling during transition
- The feature branch accumulates all changes before a single cutover

## Phase Plan

### Phase 1: Agent Core (agents + agent_versions)
- New tables: `agents`, `agent_versions`
- Delete table: `agent_profiles`
- New API: `/agents`, `/agents/{id}/versions`
- Frontend: rewrite agents pages (list, create, edit, version history)
- Graph definition_payload stored as definition_kind: graph in version

### Phase 2: AgentRelease + Publish Flow
- New table: `agent_releases`
- Delete table: `graph_deployment_version`
- New API: `/agents/{id}/releases`
- Frontend: release management UI (freeze, build, publish, activate)
- Connect runtime: release becomes execution entry point

### Phase 3: Thread + Message (Conversation System)
- New tables: `threads`, `messages`
- New API: `/threads`, `/messages`
- Frontend: agent conversation UI (replaces/integrates existing chat)
- WebSocket adapted to thread model

### Phase 4: AgentRun + Execution (Execution Chain)
- New table: `agent_runs`, rebuild `executions`
- Delete tables: legacy `agent_runs`, legacy `executions`, legacy `execution_events`, legacy `execution_snapshots`, legacy `agent_run_events`, legacy `agent_run_snapshots`
- Mission backend switches to AgentRun → Execution
- New API: `/runs`, `/executions`
- Frontend: Mission board wired to new chain, execution detail page rewritten

### Phase 5: Cleanup + Supporting Objects
- New tables: `artifacts`, `execution_events` (new schema)
- Delete tables: `graphs`, `graph_nodes`, `graph_edges`, `graph_node_secrets`, `graph_executions`
- Clean up residual frontend components and services
- Final API route cleanup

## Database Write Model

**Important: user.id type compatibility.** The existing `user` table uses `VARCHAR(255)` primary key, not UUID. All `FK → user(id)` columns in new tables must use `VARCHAR(255)` to match. The spec writes `FK → user(id)` — the implementer must use the correct type.

**Migration ordering for circular FKs:** `agents` references `agent_versions` and `agent_releases`, which reference back to `agents`. Create tables in this order: (1) `agents` without the two FK constraints, (2) `agent_versions`, (3) `agent_releases`, (4) ALTER TABLE `agents` ADD CONSTRAINT for `current_draft_version_id` and `active_release_id`.

### agents (replaces agent_profiles)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| workspace_id | UUID NOT NULL | FK → workspaces(id) |
| name | VARCHAR(255) NOT NULL | |
| slug | VARCHAR(255) NOT NULL | UNIQUE(workspace_id, slug) |
| description | TEXT | |
| avatar | VARCHAR(500) | |
| status | VARCHAR(20) NOT NULL | DEFAULT 'draft' — draft, active, archived |
| current_draft_version_id | UUID | FK → agent_versions(id), added via ALTER TABLE |
| active_release_id | UUID | FK → agent_releases(id), added via ALTER TABLE |
| created_by | VARCHAR(255) NOT NULL | FK → user(id) |
| created_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |
| updated_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |

Field migration from agent_profiles:
- name → agents.name
- description → agents.description
- avatar → agents.avatar
- runtime_type → agent_versions.definition_kind + agent_releases.runtime_kind
- instructions → agent_versions.definition_payload
- skill_ids → agent_versions.capability_manifest
- custom_env → agent_releases.runtime_binding
- runtime_config → agent_releases.runtime_binding
- status (idle/working/blocked) → derived from Run/Execution state
- max_concurrent_tasks → agent_releases.runtime_binding

### agent_versions (new)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| agent_id | UUID NOT NULL | FK → agents(id) ON DELETE CASCADE |
| version_number | INTEGER NOT NULL | UNIQUE(agent_id, version_number) |
| status | VARCHAR(20) NOT NULL | DEFAULT 'draft' — draft, frozen |
| source_kind | VARCHAR(20) NOT NULL | DEFAULT 'manual' — manual, template, clone, import, generated |
| definition_kind | VARCHAR(20) NOT NULL | prompt, graph, code, hybrid |
| definition_payload | JSONB NOT NULL | DEFAULT '{}' |
| capability_manifest | JSONB NOT NULL | DEFAULT '{}' |
| changelog | TEXT | |
| created_by | VARCHAR(255) NOT NULL | FK → user(id) |
| created_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |

Graph absorption: when definition_kind = 'graph', definition_payload stores:
```json
{
  "nodes": [],
  "edges": [],
  "variables": {}
}
```

When definition_kind = 'prompt', definition_payload stores:
```json
{
  "instructions": "...",
  "system_prompt": "..."
}
```

capability_manifest stores:
```json
{
  "skill_ids": [],
  "mcp_server_ids": [],
  "allowed_tools": []
}
```

### agent_releases (replaces graph_deployment_version)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| agent_version_id | UUID NOT NULL | FK → agent_versions(id) |
| release_number | INTEGER NOT NULL | UNIQUE(agent_version_id, release_number) |
| status | VARCHAR(20) NOT NULL | DEFAULT 'building' — building, ready, failed, retired |
| runtime_kind | VARCHAR(20) NOT NULL | graph, sandbox, hosted, external |
| builder_kind | VARCHAR(20) | How the release was built: langchain_compile, docker_build, none (for prompt-only). Nullable for releases that need no build step. |
| executable_ref | JSONB | |
| runtime_binding | JSONB NOT NULL | DEFAULT '{}' |
| published_by | VARCHAR(255) | FK → user(id) |
| published_at | TIMESTAMPTZ | |
| retired_at | TIMESTAMPTZ | |

runtime_binding stores:
```json
{
  "runtime_type": "claude_code",
  "custom_env": {},
  "runtime_config": {},
  "max_concurrent_tasks": 3
}
```

### threads (new)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| agent_id | UUID NOT NULL | FK → agents(id) |
| workspace_id | UUID NOT NULL | FK → workspaces(id) |
| title | VARCHAR(500) | |
| status | VARCHAR(20) NOT NULL | DEFAULT 'active' — active, archived. No hard delete; PATCH status to archived. |
| created_by | VARCHAR(255) NOT NULL | FK → user(id) |
| created_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |
| updated_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |

### agent_runs (replaces legacy agent_runs + mission execution link)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| release_id | UUID NOT NULL | FK → agent_releases(id) |
| workspace_id | UUID NOT NULL | denormalized from agent for query efficiency |
| thread_id | UUID | FK → threads(id) |
| mission_id | UUID | FK → missions(id) — product layer link |
| trigger_source | VARCHAR(20) NOT NULL | mission, chat, api, scheduler |
| goal | TEXT | |
| input_payload | JSONB | |
| status | VARCHAR(20) NOT NULL | DEFAULT 'queued' — queued, running, waiting, succeeded, failed, cancelled |
| current_execution_id | UUID | FK → executions(id) |
| result_summary | TEXT | |
| started_at | TIMESTAMPTZ | |
| ended_at | TIMESTAMPTZ | |
| created_by | VARCHAR(255) | FK → user(id), nullable for system/scheduler triggers |
| created_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |

### executions (rebuilt)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| run_id | UUID NOT NULL | FK → agent_runs(id) |
| parent_execution_id | UUID | FK → executions(id) |
| attempt_index | INTEGER NOT NULL | DEFAULT 1, UNIQUE(run_id, attempt_index). Counts retries of the same run. |
| executor_kind | VARCHAR(20) NOT NULL | claude_code, codex, openclaw, langgraph |
| runtime_session_ref | VARCHAR(500) | |
| status | VARCHAR(20) NOT NULL | DEFAULT 'pending' — pending, running, suspended, succeeded, failed, cancelled |
| error_code | VARCHAR(100) | |
| error_message | TEXT | |
| metrics | JSONB | |
| started_at | TIMESTAMPTZ | |
| ended_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |

`parent_execution_id` is for hierarchical decomposition (e.g., a graph node spawning child executions). `attempt_index` is for retries of the top-level run. They are orthogonal: child executions inherit the parent's `attempt_index` scope but have their own `parent_execution_id` chain.

### messages (new)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| thread_id | UUID NOT NULL | FK → threads(id) |
| run_id | UUID | FK → agent_runs(id) |
| execution_id | UUID | FK → executions(id) |
| role | VARCHAR(20) NOT NULL | user, assistant, system, tool |
| content | JSONB NOT NULL | |
| created_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |

### artifacts (new)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| execution_id | UUID NOT NULL | FK → executions(id) |
| kind | VARCHAR(50) NOT NULL | |
| uri | TEXT NOT NULL | |
| metadata | JSONB | |
| created_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |

### execution_events (rebuilt)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID PK | gen_random_uuid() |
| execution_id | UUID NOT NULL | FK → executions(id) |
| sequence_no | INTEGER NOT NULL | UNIQUE(execution_id, sequence_no) |
| event_type | VARCHAR(50) NOT NULL | |
| payload | JSONB NOT NULL | DEFAULT '{}' |
| created_at | TIMESTAMPTZ NOT NULL | DEFAULT now() |

### Tables preserved unchanged

missions, mission_comments, skills, skill_files, skill_versions, skill_collaborators, mcp_servers, model_provider, model_credential, model_instance, user, session, workspaces, workspace_member, workspace_folder, platform_tokens, memories, oauth_account, security_audit_log, model_usage_log, user_sandbox, openclaw_instance, organization, member

### Tables deleted

agent_profiles, graphs, graph_nodes, graph_edges, graph_node_secrets, graph_deployment_version, graph_executions, conversations, legacy agent_runs, agent_run_events, agent_run_snapshots, legacy executions, legacy execution_events, legacy execution_snapshots

### Missions table modification

Remove `current_execution_id` column from `missions`. The execution link is now derived through `agent_runs.mission_id`.

## API Resource Model

### New/replaced routes

```
# Agent Core
GET    /api/v1/agents
POST   /api/v1/agents
GET    /api/v1/agents/{agentId}
PATCH  /api/v1/agents/{agentId}
DELETE /api/v1/agents/{agentId}

# AgentVersion
GET    /api/v1/agents/{agentId}/versions
POST   /api/v1/agents/{agentId}/versions
GET    /api/v1/agents/{agentId}/versions/{versionId}
PATCH  /api/v1/agents/{agentId}/versions/{versionId}
POST   /api/v1/agents/{agentId}/versions/{versionId}/freeze

# AgentRelease
GET    /api/v1/agents/{agentId}/releases
POST   /api/v1/agents/{agentId}/releases
GET    /api/v1/agents/{agentId}/releases/{releaseId}
POST   /api/v1/agents/{agentId}/releases/{releaseId}/activate
POST   /api/v1/agents/{agentId}/releases/{releaseId}/retire

# Thread
GET    /api/v1/threads
POST   /api/v1/threads
GET    /api/v1/threads/{threadId}
PATCH  /api/v1/threads/{threadId}

# Message
GET    /api/v1/threads/{threadId}/messages
POST   /api/v1/threads/{threadId}/messages

# AgentRun
GET    /api/v1/runs
POST   /api/v1/runs
GET    /api/v1/runs/{runId}
POST   /api/v1/runs/{runId}/cancel
POST   /api/v1/runs/{runId}/retry

# Execution
GET    /api/v1/executions
GET    /api/v1/executions/{executionId}
GET    /api/v1/executions/{executionId}/events
GET    /api/v1/executions/{executionId}/artifacts
POST   /api/v1/executions/{executionId}/approve
POST   /api/v1/executions/{executionId}/message

# Mission (preserved, simplified execution link)
GET    /api/v1/missions
POST   /api/v1/missions
PATCH  /api/v1/missions/{id}
POST   /api/v1/missions/{id}/dispatch    → creates AgentRun + Execution
GET    /api/v1/missions/{id}/runs        → new: view associated runs
```

### Deleted routes

```
/api/v1/agent-profiles/*       → replaced by /agents/*
/api/v1/graphs/*               → replaced by /agents/*/versions
/api/v1/graph-code/*           → replaced by /agents/*/versions
/api/v1/runs/* (legacy)        → replaced by new /runs/*
/api/v1/conversations/*        → replaced by /threads/*
```

### WebSocket endpoints

```
/ws/executions    → preserved, adapted to new execution model
/ws/chat          → refactored to /ws/threads/{threadId}
/ws/runs          → deleted (legacy LangGraph, merged into /ws/executions)
```

### Response expansion

GET /runs/{id} example:
```json
{
  "id": "...",
  "status": "running",
  "goal": "...",
  "agent": { "id": "...", "name": "...", "slug": "..." },
  "version": { "id": "...", "version_number": 3, "definition_kind": "prompt" },
  "release": { "id": "...", "release_number": 1, "runtime_kind": "sandbox" },
  "thread": { "id": "...", "title": "..." },
  "current_execution": { "id": "...", "status": "running", "attempt_index": 1 }
}
```

### Preserved routes

/auth/*, /users/*, /workspaces/*, /workspace-folders/*, /skills/*, /skill-versions/*, /mcp/*, /tools/*, /model-providers/*, /model-credentials/*, /models/*, /tokens/*, /memory/*, /traces/*, /sandboxes/*, /organizations/*, /version

## Backend Service Architecture

### Directory structure

```
backend/app/
├── models/
│   ├── agent.py              # Agent, AgentVersion, AgentRelease
│   ├── thread.py             # Thread, Message
│   ├── agent_run.py          # AgentRun
│   ├── execution.py          # Execution, ExecutionEvent, Artifact
│   ├── mission.py            # Mission (preserved, simplified)
│   └── ...                   # remainder unchanged
├── schemas/
│   ├── agent.py
│   ├── agent_version.py
│   ├── agent_release.py
│   ├── thread.py
│   ├── agent_run.py
│   ├── execution.py
│   └── ...
├── services/
│   ├── agent_service.py
│   ├── agent_version_service.py
│   ├── agent_release_service.py
│   ├── thread_service.py
│   ├── agent_run_service.py
│   ├── execution_lifecycle_service.py  # renamed, refactored to new model
│   ├── execution_runner.py             # preserved, interface adapted
│   └── mission_service.py              # preserved, dispatch delegates to AgentRunService
├── api/v1/
│   ├── agents.py              # /agents + /versions + /releases
│   ├── threads.py             # /threads + /messages
│   ├── agent_runs.py          # /runs
│   ├── executions.py          # /executions (rewritten)
│   ├── missions.py            # preserved, dispatch creates AgentRun
│   └── ...
```

### Key service interactions

Mission dispatch (refactored):
```
POST /missions/{id}/dispatch
  → MissionService.dispatch()
    → find agent's active_release
    → AgentRunService.create_run(release_id, trigger='mission', mission_id=id)
      → ExecutionLifecycleService.start_execution(run_id)
        → ExecutionRunner.run()
```

Direct run trigger (new):
```
POST /runs
  → AgentRunService.create_run(release_id, trigger='api/chat', thread_id=...)
    → ExecutionLifecycleService.start_execution(run_id)
```

Retry flow:
```
POST /runs/{id}/retry
  → AgentRunService.retry_run(run_id)
    → new Execution(attempt_index + 1)
    → ExecutionLifecycleService.start_execution(run_id, execution_id)
```

### Runtime bridge

ExecutionRunner, ContainerPool, RuntimeRegistry (ClaudeCodeProvider etc.) are preserved. Only the input interface changes:

- Old: `ExecutionRunner.run(execution: LegacyExecution, prompt, credentials)`
- New: `ExecutionRunner.run(execution: NewExecution, release: AgentRelease, prompt, credentials)`

Runtime config sourced from `release.runtime_binding` instead of `agent_profile`.

### Scheduler adaptation

mission_dispatcher_loop and execution_reaper_loop preserved, but:
- dispatcher triggers via AgentRunService.create_run()
- reaper checks new executions table heartbeat

## Frontend Architecture

### Route structure (App Router)

```
app/
├── agents/
│   ├── page.tsx                     # Agent list
│   ├── new/page.tsx                 # Create Agent
│   └── [agentId]/
│       ├── page.tsx                 # Agent detail (overview, active release)
│       ├── edit/page.tsx            # Edit draft version
│       ├── versions/page.tsx        # Version history
│       ├── releases/page.tsx        # Release history
│       ├── threads/
│       │   ├── page.tsx             # Thread list
│       │   └── [threadId]/page.tsx  # Conversation UI
│       └── runs/page.tsx            # Agent run history
├── missions/                        # preserved, wired to new API
│   ├── page.tsx                     # Kanban board (DnD preserved)
│   └── [missionId]/page.tsx         # Mission detail (associated runs)
├── runs/                            # new global Run view
│   ├── page.tsx                     # Global Run list
│   └── [runId]/page.tsx             # Run detail + Execution stream
├── executions/
│   └── [executionId]/page.tsx       # Execution detail (events, artifacts)
```

Deleted routes: app/chat/ (absorbed into agents/[agentId]/threads/), app/runs/ (legacy, replaced)

### Services layer

```
services/
├── agentService.ts          # replaces agentProfileService.ts
├── agentVersionService.ts   # new
├── agentReleaseService.ts   # new
├── threadService.ts         # new, replaces parts of chatBackend.ts
├── agentRunService.ts       # new
├── executionService.ts      # rewritten
├── missionService.ts        # preserved, simplified
└── ...                      # remainder unchanged
```

### React Query hooks

```
hooks/queries/
├── agents.ts                # useAgents, useAgent, useCreateAgent, useUpdateAgent
├── agentVersions.ts         # useVersions, useCreateVersion, useFreezeVersion
├── agentReleases.ts         # useReleases, usePublishRelease, useActivateRelease
├── threads.ts               # useThreads, useThread, useMessages, useSendMessage
├── agentRuns.ts             # useRuns, useCreateRun, useCancelRun, useRetryRun
├── executions.ts            # useExecution, useExecutionEvents (rewritten)
├── missions.ts              # preserved, dispatch mutation calls new API
```

### WebSocket hooks

```
hooks/
├── use-execution-stream.ts  # preserved, adapted to new execution model
├── use-thread-stream.ts     # new, replaces legacy chat WebSocket
```

### Key components

Agent detail page:
- AgentHeader — name, slug, status, quick actions
- AgentOverview — active release info, recent runs summary
- VersionEditor — draft version editor, switches by definition_kind:
  - PromptEditor for definition_kind: prompt
  - GraphEditor for definition_kind: graph (reuses ReactFlow canvas)
  - CodeEditor for definition_kind: code (reuses CodeMirror)
- VersionHistory — version list + diff view
- ReleaseManager — publish, activate, retire actions

Mission board (preserved + adapted):
- MissionBoard — DnD Kanban preserved
- MissionCard — agent info from new Agent model
- MissionDetailPanel — dispatch via AgentRun
- RunStream — new component replacing embedded execution stream

### Store changes

- Delete: deploymentStore.ts (release management via React Query)
- Preserve: auth/, sidebar/, settings/
- New domains all use React Query server state, no new Zustand stores

## Acceptance Criteria

1. Every user-facing entry path starts from an Agent
2. Every runnable target resolves through an AgentRelease
3. Every task is represented by an AgentRun
4. Every retry or branch is a distinct Execution
5. Frontend never needs runtime or graph identifiers to determine which agent is in scope
6. Database write model remains normalized across the primary chain
7. API convenience expansions do not change write-model ownership
8. LangGraph/Canvas is just definition_kind: graph within AgentVersion, not a separate top-level object
9. Mission Kanban board remains functional with execution chain wired through AgentRun → Execution
10. All legacy tables deleted, no compatibility layer
