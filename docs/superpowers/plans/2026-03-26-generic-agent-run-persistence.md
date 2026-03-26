# Generic Agent Run Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the run persistence system so all long-running Agent tasks use the same model, with an agent registry pattern and Run Center filtering by agent name, status, and title search.

**Architecture:** Add `agent_name` column to `agent_runs`, introduce an `AgentRegistry` that maps agent names to reducers, generalize `RunService` and API endpoints to use the registry, and upgrade the Run Center UI with server-side filtering.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), Next.js/React/TypeScript (frontend), PostgreSQL, Redis, Alembic migrations, pytest (asyncio_mode=auto), vitest

## File Map

### Backend — new files
- `backend/app/services/agent_registry.py` — `AgentDefinition` dataclass + `AgentRegistry` singleton
- `backend/alembic/versions/20260326_000000_add_agent_name_column.py` — adds `agent_name` column + indexes
- `backend/tests/test_services/test_agent_registry.py` — registry unit tests
- `backend/tests/test_services/test_run_reducers.py` — reducer unit tests
- `backend/tests/test_api/test_runs_api.py` — runs API unit tests

### Backend — modified files
- `backend/app/models/agent_run.py` — add `agent_name` column + index
- `backend/app/repositories/agent_run.py` — add `agent_name` + `search` filters; add `find_latest_active_run` generic method
- `backend/app/services/run_service.py` — use registry for reducer dispatch; add generic `create_run` + `find_latest_active_run`; keep old methods as aliases
- `backend/app/services/run_reducers/__init__.py` — export registry after registration
- `backend/app/services/run_reducers/skill_creator.py` — add `make_initial_projection` + register with `AgentRegistry`
- `backend/app/schemas/runs.py` — add `agent_name` + `agent_display_name` to `RunSummary`; add `CreateRunRequest`; add `AgentDefinitionResponse` + `AgentListResponse`
- `backend/app/api/v1/runs.py` — add `POST /v1/runs`, `GET /v1/runs/agents`, `GET /v1/runs/active`; add `agent_name` + `search` query params to `GET /v1/runs`; keep old endpoints as aliases

### Frontend — modified files
- `frontend/services/runService.ts` — add `agent_name`/`agent_display_name` to `RunSummary`; add `AgentDefinition` type; add `createRun`, `listAgents`, `findActiveRun`; keep old methods as aliases
- `frontend/hooks/queries/runs.ts` — add `useAgents` hook; update `useRuns` to accept `agentName` + `search` filters; update `runKeys`
- `frontend/lib/utils/runHelpers.ts` — update `buildRunHref` to use `agent_name`
- `frontend/app/runs/page.tsx` — add agent filter chips, title search input, sync filters to URL params; move filtering server-side

---
