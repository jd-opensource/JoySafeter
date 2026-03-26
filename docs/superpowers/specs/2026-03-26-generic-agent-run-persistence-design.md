# Generic Agent Run Persistence Design

## Goal

Generalize the run persistence system so that **all** long-running Agent tasks — not just Skill Creator — use the same `run_id + snapshot + replay` model. Add an agent registry pattern for pluggable agent types and upgrade the Run Center UI with agent name filtering, status filtering, and title search.

## Status

Proposed on 2026-03-26. Builds on the Phase 1 Skill Creator implementation (2026-03-25).

## Context

Phase 1 delivered Skill Creator run persistence:

- `agent_runs`, `agent_run_events`, `agent_run_snapshots` tables
- `WS /ws/runs` subscription endpoint
- Run Center UI at `/runs`
- Reducer-based snapshot system

Everything is currently hardcoded to `run_type = "skill_creator"`. This design generalizes the system so Chat, Copilot, Workspace Execution, and any future agent can register and participate.

## Scope

**In scope:**

- New `agent_name` column on `agent_runs`
- Agent registry pattern with pluggable reducers
- Generic create-run API
- Run Center UI with agent filter, status filter, and title search
- Fix schema drift (missing `runtime_owner_id`, `last_heartbeat_at` columns and index)
- Backward compatibility for all existing Skill Creator code paths

**Out of scope:**

- Actually wiring Chat, Copilot, or Workspace Execution to emit run events (they can be added incrementally by registering a reducer)
- Moving execution to external workers
- Event compaction or archival

## Data Model Changes

### New column on `agent_runs`

```sql
agent_name  VARCHAR(100)  NOT NULL  DEFAULT 'skill_creator'
```

- `run_type` stays as-is — describes the kind of run ("generation", "turn", "execution")
- `agent_name` identifies which agent produced the run ("skill_creator", "chat", "copilot", "workspace")
- Default `'skill_creator'` for backward compatibility with existing rows

### New indexes

```sql
CREATE INDEX agent_runs_user_agent_idx ON agent_runs (user_id, agent_name, created_at DESC);
CREATE INDEX agent_runs_user_runtype_idx ON agent_runs (user_id, run_type, created_at DESC);
```

### Schema drift fix

The ORM model defines `runtime_owner_id`, `last_heartbeat_at`, and `agent_runs_owner_status_idx` but the existing migration does not create them. This migration adds:

```sql
ALTER TABLE agent_runs ADD COLUMN runtime_owner_id VARCHAR(255);
ALTER TABLE agent_runs ADD COLUMN last_heartbeat_at TIMESTAMPTZ;
CREATE INDEX agent_runs_owner_status_idx ON agent_runs (runtime_owner_id, status);
```

## Agent Registry

A simple Python registry — no metaclass magic, just a dict.

### AgentDefinition

```python
@dataclass
class AgentDefinition:
    name: str                    # e.g. "skill_creator"
    display_name: str            # e.g. "Skill Creator" (for UI)
    default_run_type: str        # e.g. "generation"
    reducer: Callable            # (projection, event_type, payload, status) -> projection
    initial_projection: Callable # () -> dict (empty projection template)
```

### AgentRegistry

```python
class AgentRegistry:
    _agents: dict[str, AgentDefinition] = {}

    @classmethod
    def register(cls, definition: AgentDefinition): ...

    @classmethod
    def get(cls, agent_name: str) -> AgentDefinition | None: ...

    @classmethod
    def list_all(cls) -> list[AgentDefinition]: ...
```

### Registration

Each reducer module self-registers at import time:

```python
# backend/app/services/run_reducers/skill_creator.py (add at bottom)
AgentRegistry.register(AgentDefinition(
    name="skill_creator",
    display_name="Skill Creator",
    default_run_type="generation",
    reducer=apply_skill_creator_event,
    initial_projection=make_initial_projection,
))
```

Future agents follow the same pattern — one file, one register call.

### RunService integration

- `create_run(agent_name, ...)` calls `definition.initial_projection()` to seed the snapshot, then appends a `run_initialized` event through the reducer (same pattern as current `create_skill_creator_run`)
- `append_event` replaces `if run.run_type == "skill_creator"` with `AgentRegistry.get(run.agent_name).reducer`
- `create_skill_creator_run(...)` stays as a thin wrapper calling `create_run("skill_creator", ...)`
- `find_latest_active_run(agent_name, user_id, ...)` generalizes the current skill-creator-specific method

### Response schema

`RunSummary` (both Pydantic and frontend type) adds `agent_name: str` and `agent_display_name: str` fields. The API populates `agent_display_name` from the registry.

### Frontend href routing

Per-agent "Open" button routing stays in the frontend (`runHelpers.ts`) as a simple map on `agent_name`. The backend registry does not need to know about frontend routes.

## API Changes

### New generic create-run endpoint

```
POST /api/v1/runs
{
  "agent_name": "skill_creator",
  "message": "Build a skill that ...",
  "graph_id": "uuid",
  "thread_id": null,
  "config": {}
}
```

Backend validates `agent_name` against `AgentRegistry`.

### Existing endpoint preserved as alias

```
POST /api/v1/runs/skill-creator  →  delegates to POST /api/v1/runs with agent_name="skill_creator"
```

### Enhanced list endpoint

```
GET /api/v1/runs?agent_name=skill_creator&status=running&run_type=generation&search=weather&limit=50
```

New query params:

- `agent_name` — filter by agent (exact match)
- `search` — case-insensitive substring match on `title`

### Agent metadata endpoint

```
GET /api/v1/runs/agents
```

Returns:

```json
{
  "data": [
    { "name": "skill_creator", "display_name": "Skill Creator" }
  ]
}
```

Frontend uses this to populate agent filter dropdown dynamically.

### Generalized active run lookup

```
GET /api/v1/runs/active?agent_name=skill_creator&graph_id=...&thread_id=...
```

Replaces `GET /api/v1/runs/active/skill-creator`. Old endpoint stays as alias.

## Run Center UI

### Filter bar

```
┌─────────────────────────────────────────────────────────┐
│  Run Center                                             │
├─────────────────────────────────────────────────────────┤
│  [🔍 Search by title...          ]                      │
│                                                         │
│  Agent:  [All ▾] [Skill Creator] [Chat] [Copilot] ...  │
│  Status: [All] [Active] [Finished]                      │
├─────────────────────────────────────────────────────────┤
│  ● Running  │ Skill Creator │ Build weather skill │ 3m  │
│  ● Running  │ Chat          │ Debug auth flow     │ 1m  │
│  ○ Done     │ Skill Creator │ CSV parser skill    │ 12m │
│  ✕ Failed   │ Copilot       │ Refactor utils      │ 25m │
└─────────────────────────────────────────────────────────┘
```

### Implementation details

- Agent filter chips populated from `GET /api/v1/runs/agents` — fully dynamic
- All filters sent server-side as query params to `GET /api/v1/runs`
- URL search params sync with filters: `/runs?agent_name=chat&status=running`
- `useRuns` hook updated to accept all filter params, polls every 15s
- Each `RunRow` shows `agent_name` as a colored badge using `display_name`
- "Open" button logic: registry can provide a `buildRunHref(run)` per agent, or fallback to `/runs/{runId}`

### No changes to

- Run Detail page (`/runs/[runId]`) — already agent-agnostic
- WS subscription logic — already generic by `run_id`

## Frontend Service & Hook Changes

### runService.ts

```ts
// New generic methods
createRun(params: { agent_name: string; message: string; graph_id?: string; thread_id?: string; config?: Record<string, any> })
listRuns(params?: { agentName?: string; status?: string; runType?: string; search?: string; limit?: number })
findActiveRun(agentName: string, graphId?: string, threadId?: string)
getAgents(): Promise<AgentDefinition[]>

// Old methods stay as aliases
createSkillCreatorRun(...)  →  calls createRun({ agent_name: "skill_creator", ... })
findActiveSkillCreatorRun(...)  →  calls findActiveRun("skill_creator", ...)
```

### queries/runs.ts

```ts
// New hooks
useAgents()           // GET /v1/runs/agents, cached (staleTime: Infinity)
useRuns(filters)      // updated to pass agent_name, search, status, runType

// Existing hooks stay, delegate internally
useActiveSkillCreatorRun()  →  calls findActiveRun("skill_creator", ...)
```

### Skill Creator hook

Minimal changes — calls `createSkillCreatorRun` (now an alias). Reducer logic unchanged.

## Migration & Backward Compatibility

### Alembic migration

Single migration:

1. Add `agent_name VARCHAR(100) NOT NULL DEFAULT 'skill_creator'` to `agent_runs`
2. Backfill existing rows: `UPDATE agent_runs SET agent_name = 'skill_creator'`
3. Add `runtime_owner_id VARCHAR(255)` and `last_heartbeat_at TIMESTAMPTZ` (schema drift fix)
4. Create indexes: `agent_runs_user_agent_idx`, `agent_runs_user_runtype_idx`, `agent_runs_owner_status_idx`

### Backward compatibility

- All existing `skill_creator` runs get `agent_name='skill_creator'` via default
- Old `POST /v1/runs/skill-creator` stays, delegates to generic
- Old `GET /v1/runs/active/skill-creator` stays, delegates to generic
- Frontend aliases keep Skill Creator page working without changes
- Run Center works immediately — "Skill Creator" shows as only agent until others register

## Implementation Sequence

| Step | What | Files |
|------|------|-------|
| 1 | Migration + model update | `backend/app/models/agent_run.py`, new alembic migration |
| 2 | Agent registry + register skill_creator | New `backend/app/services/agent_registry.py`, modify `backend/app/services/run_reducers/skill_creator.py` |
| 3 | Generalize RunService | `backend/app/services/run_service.py`, `backend/app/repositories/agent_run.py` |
| 4 | Generalize API endpoints | `backend/app/api/v1/runs.py`, `backend/app/schemas/runs.py` |
| 5 | Frontend service & hooks | `frontend/services/runService.ts`, `frontend/hooks/queries/runs.ts` |
| 6 | Run Center UI upgrade | `frontend/app/runs/page.tsx` |
| 7 | Tests | Backend unit + frontend unit |

## File Checklist

### Backend new

- `backend/app/services/agent_registry.py`
- `backend/alembic/versions/<new>_add_agent_name_and_fix_drift.py`

### Backend modify

- `backend/app/models/agent_run.py` — add `agent_name` column
- `backend/app/repositories/agent_run.py` — generalize queries
- `backend/app/services/run_service.py` — use registry for reducer dispatch, add generic methods
- `backend/app/services/run_reducers/skill_creator.py` — add registration call
- `backend/app/api/v1/runs.py` — add generic endpoints, agents endpoint, search param
- `backend/app/schemas/runs.py` — add new request/response schemas

### Frontend modify

- `frontend/services/runService.ts` — add generic methods, keep aliases
- `frontend/hooks/queries/runs.ts` — add useAgents, update useRuns filters
- `frontend/app/runs/page.tsx` — agent filter, status filter, title search

## Rollback Strategy

Safe — `agent_name` column with default means old code ignores it. Revert frontend to old filter UI. No data loss.

## Testing Plan

### Backend unit

- Agent registry: register, get, list
- Reducer dispatch via registry matches direct call
- Repository: filter by `agent_name`, filter by `search` on title
- Migration: backfill correctness

### Backend integration

- Create run via generic endpoint with `agent_name`
- List runs filtered by `agent_name` returns only matching
- List runs with `search` returns title matches
- Old skill-creator alias endpoints still work
- `GET /v1/runs/agents` returns registered agents

### Frontend unit

- `useAgents` populates filter chips
- Filter state syncs with URL params
- `useRuns` passes all filters to API
- Skill Creator flow unchanged (alias path)

### E2E

1. Open Run Center
2. Start a Skill Creator run
3. Filter by "Skill Creator" — run visible
4. Filter by "Chat" — run hidden
5. Search by title substring — run visible/hidden correctly
6. Combine agent + status filter — correct results

## Success Criteria

This phase is successful if:

- Any agent can register by adding one reducer file + one register call
- Run Center shows all runs and can filter by agent name, status, and title search
- Existing Skill Creator flow has zero functional regression
- API supports generic run creation with `agent_name` validation
- Schema drift is resolved
