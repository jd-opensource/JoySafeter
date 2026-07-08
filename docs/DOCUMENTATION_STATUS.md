# Documentation Status

Last code-based review: 2026-07-03.

This file tracks the documentation state after the v2 code refactor. The source of truth is the
current repository, not older design notes.

## Reviewed And Updated

| Document | Current status |
| --- | --- |
| `README.md` / `README_CN.md` | Updated quick start to reflect the `local-redis` profile and current three-service deployment. |
| `INSTALL.md` / `INSTALL_CN.md` | Updated Docker Compose commands, Redis profile behavior, and frontend setup to use the checked-in Bun lockfile only. |
| `DEVELOPMENT.md` | Updated local development commands, Bun-based frontend workflow, and current frontend env variables. |
| `backend/README.md` / `backend/env.example` | Updated service role names, explicit entrypoints, worker responsibilities, current backend layout, and current backend runtime knobs. |
| `backend/config/README_OAUTH_LOCAL.md` | Removed the stale bundled mock-server command and documented the current external/self-hosted mock OAuth flow. |
| `backend/config/oauth_providers.example.yaml` | Updated the example post-login redirect from the removed `/chat` surface to `/managed/quickstart`. |
| `frontend/README.md` / `frontend/env.example` | Updated App Router structure to the current `/managed/**` product surface and current frontend runtime/server config. |
| `deploy/README.md` | Updated to the single existing Compose file, removed stale remote-compose instructions, documented cloud Redis vs local Redis, and clarified SkillSpector draft-save vs runtime-gate behavior. |
| `deploy/.env.example` | Updated the Redis default to match the local compose quickstart while keeping cloud Redis examples, and clarified SkillSpector failure behavior for draft writes vs runtime packing. |
| `deploy/docker-compose.yml` | Updated top-level usage comments to show the supported Rust orchestrator local stack and removed the stale Python orchestrator service. |
| `docs/api/openapi.md` | Updated response envelope, mounted router list, API key request/response details, session-first run flow, task-first response shape, and task ID path semantics from current routers/schemas. |
| `docs/README.md` | Added a docs-level entry point linking status, architecture, tutorials, API notes, hardening, plans, and assets. |
| `docs/tutorials/*.md` | Updated v2 tutorial navigation to current sidebar labels/routes, clarified new skill naming guidance and SkillSpector runtime-gate semantics, and aligned the Agent example model with the current default Anthropic secret model. |
| `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE_CN.md` / `docs/*.mmd` | Updated compose command snippets for the supported Rust orchestrator stack, replaced brittle line-number anchors with stable module references, and corrected SkillSpector failure-mode wording. |
| `docs/user-journey-quickstart.drawio` | Updated stale `/chat`, `/settings/models`, `/tools`, `/workspace`, `/runs`, and `/ws/executions` labels to the current managed routes and SSE session stream. |
| `docs/assets/README.md` | Updated committed asset inventory and screenshot TODOs for the current `/managed/**` UI. |
| `docs/plans/*.md` | Added status banners marking historical implementation plans and the missing Rust orchestrator source directory where relevant. |
| `docs/production-hardening-plan.md` | Added current implementation status: task lease/fencing/idempotency/dead-letter pieces landed; outbox, durable membership, provider chain, tenant quotas, and full failure matrix remain open. |
| Governance docs (`CONTRIBUTING.md`, `SECURITY.md`, `.pre-commit-setup.md`, `.github/*`) | Updated current dependency expectations, Bun commands, pre-commit checks, supported version line, and issue-template version example. |

## Reviewed, No Code-Dependent Changes Needed

| Document | Status |
| --- | --- |
| `CHANGELOG.md` | Historical release log. Older Run Center, Copilot, and DeepAgents entries are retained as dated history rather than rewritten as current product docs. |
| `CODE_OF_CONDUCT.md` | Community policy text; no v2 architecture or command references to update. |
| `PENETRATION_TESTING_DISCLAIMER_CN.md` | Legal/safety disclaimer; no v2 architecture or command references to update. |
| `THIRD_PARTY_LICENSES.md` | License notice; no v2 architecture or command references to update. |
| `.github/ISSUE_TEMPLATE/feature_request.md` / `.github/PULL_REQUEST_TEMPLATE.md` | Generic GitHub templates; no stale v1 route, command, or service references found. |

## Skipped By Request

| Area | Status |
| --- | --- |
| `skills/**` | Excluded from this documentation pass by user request. No files under `skills/` are changed or claimed as reviewed here. |

## Current Code Facts Used For This Pass

- Backend Python service roles are `api` and `worker`; Rust owns orchestration.
- Explicit Python ASGI entrypoints are `app.joysafeter_api.main:app` and `app.joysafeter_worker.main:app`.
- API routes are mounted under `/api/v1`; notifications use `/ws/notifications`.
- Programmatic live runs should use the session-first flow: `POST /sessions`, `POST /sessions/{id}/events`
  with `user.message`, then `GET /sessions/{id}/events/stream`. Direct `POST /tasks` returns only
  `id` and `status`; task detail/stream/cancel paths currently take a bare UUID.
- Worker currently runs the Redis Stream event consumer and batch persistence path.
- Frontend's main product surface is under `/managed/**`; root redirects authenticated users to `/managed/quickstart`.
- Docker Compose has one active file: `deploy/docker-compose.yml`. Local Redis is behind the `local-redis` profile.
- The supported quick-start orchestrator is Rust via the `rust-orchestrator` profile.

## Verification Notes

- `git diff --check` passes.
- Relative Markdown link audit checked 34 Markdown files after excluding dependency,
  virtualenv, and `skills/**` directories.
- Ruby YAML parsing succeeds for `deploy/docker-compose.yml`,
  `backend/config/oauth_providers.yaml`, and `backend/config/oauth_providers.example.yaml`.
  `docker-compose --env-file .env.example --profile local-redis --profile rust-orchestrator
  config --services` resolves the supported local service set. Full `docker-compose config --quiet`
  requires local `backend/.env` and `frontend/.env` files; those are intentionally created by the
  documented setup commands and were not generated during this audit.
- API run-flow notes were checked against `joysafeter_api/api/v1/router.py`,
  `sessions.py`, `tasks.py`, `id_helpers.py`, and `joysafeter_task.py`. In particular,
  `POST /tasks` returns only `id` and `status`, while `POST /sessions/{id}/events` creates
  the task for a `user.message` and records the task UUID in a `session.status_running` event.
- API router groups were rechecked against `joysafeter_api/api/v1/router.py` and route
  decorators. `audit.py` remains an internal helper used by other routers and is not mounted.
  Session create fields were checked against `CreateSessionRequest`, including memory-store
  `resources`, uploaded `file_resources`, and git `repo_resources`.
- The mounted route table was also generated by importing `joysafeter_api.app.create_api_app`
  with a no-op lifespan under `SECRET_KEY=test-secret`; it confirms `/api/v1/*`,
  `WS /api/v1/tasks/{task_id}/stream`, and `/ws/notifications`, including current
  `/memory_stores`, `/quickstart/chat`, and `/skills/ai-authoring/chat` endpoints and no mounted
  audit/model/MCP/tool routers.
- `backend/env.example` was checked against `joysafeter_shared/config/settings.py`; stale
  `API_V1_PREFIX`, `SMTP_FROM`, and `SMTP_TLS` examples were removed, and current task lease,
  Redis stream dead-letter/high-water, native image, SkillSpector async threshold, and skill
  import limit knobs were documented.
- Frontend runtime/server env was checked against `frontend/lib/core/config/env.ts`,
  `frontend/services/email/mailer.ts`, and `deploy/docker-compose.yml`; local and Compose
  examples now include the frontend server auth/email variables as well as `NEXT_PUBLIC_*`.
- Old-platform scans still intentionally match docs that explain removed v1 concepts
  (`CHANGELOG.md`, `docs/ARCHITECTURE*.md`, and selected tutorials). `skills/**` is outside the
  scan scope for this pass.
