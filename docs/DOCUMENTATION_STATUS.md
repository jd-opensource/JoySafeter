# Documentation Status

Last code-based review: 2026-07-09.

This file tracks the documentation state after the v2 code refactor. The source of truth is the
current repository, not older design notes.

## Reviewed And Updated

| Document | Current status |
| --- | --- |
| `README.md` / `README_CN.md` | Updated quick start to use `deploy.sh doctor` / `deploy.sh local`, current Rust orchestrator deployment, local-development split, runtime collaboration table, primary data flow, and removed stale single-process/service-role wording. |
| `INSTALL.md` / `INSTALL_CN.md` | Replaced removed `python-orchestrator` and all-in-one Python startup instructions with `deploy.sh doctor/local`, Rust `orchestrator-rs`, prebuilt-image usage, environment checks, and troubleshooting notes. |
| `DEVELOPMENT.md` | Updated local development commands to run Python API, Rust `orchestrator-rs`, and Python worker as separate processes; refreshed Bun-based frontend workflow and current frontend env variables. |
| `backend/README.md` / `backend/env.example` | Updated service role names, explicit entrypoints, worker responsibilities, current backend layout, current backend runtime knobs, and the unified Docker deployment entrypoint. |
| `backend/config/README_OAUTH_LOCAL.md` | Removed the stale bundled mock-server command and documented the current external/self-hosted mock OAuth flow. |
| `backend/config/oauth_providers.example.yaml` | Updated the example post-login redirect from the removed `/chat` surface to `/managed/quickstart`. |
| `frontend/README.md` / `frontend/env.example` | Updated App Router structure to the current `/managed/**` product surface and current frontend runtime/server config. |
| `deploy/README.md` | Updated to the single existing Compose file, `doctor/local` workflow, Docker daemon CPU auto-detection, multi-arch image defaults, service collaboration topology, deployment data flow, deployment-mode selection, SkillSpector auto-prepare behavior, migrations, cloud Redis/Postgres notes, command/option matrix, and troubleshooting FAQ. |
| `deploy/.env.example` | Updated local deployment defaults for multi-arch official images, Docker platform guidance, and `.deps/SkillSpector` as the default SkillSpector source. |
| `deploy/deploy.sh` | Added `doctor` and `local` commands that prepare env files, detect Docker daemon CPU architecture, set safe multi-arch image defaults, locate Docker socket, prepare SkillSpector, preflight compose/ports, run db migrations, and then start the local stack. Image lifecycle commands now include backend, frontend, Rust orchestrator, and SkillSpector as core deployment images. |
| `deploy/docker-compose.yml` / deployment Dockerfiles | Updated build args and service image defaults to Docker Official Images multi-arch mirrors, removed stale single-arch defaults, aligned SkillSpector source path with `.deps/SkillSpector`, and removed stale Python-orchestrator health/port exposure from the backend image contract. |
| `docs/api/openapi.md` | Updated response envelope, mounted router list, API key request/response details, session-first run flow, task-first response shape, and task ID path semantics from current routers/schemas. |
| `docs/README.md` | Added a docs-level entry point linking status, architecture, tutorials, API notes, hardening, plans, and assets. |
| `docs/tutorials/*.md` | Updated v2 tutorial navigation to current sidebar labels/routes, clarified new skill naming guidance and SkillSpector runtime-gate semantics, and aligned the Agent example model with the current default Anthropic secret model. |
| `docs/ARCHITECTURE.md` / `docs/ARCHITECTURE_CN.md` / `docs/*.mmd` | Updated deployment command snippets for the supported Rust orchestrator stack, added collaboration contracts and failure-ownership routing, replaced brittle line-number anchors with stable module references, and corrected SkillSpector failure-mode wording. |
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
- The legacy all-in-one Python startup path and Python orchestrator profile are not present in the current codebase.
- API routes are mounted under `/api/v1`; notifications use `/ws/notifications`.
- Programmatic live runs should use the session-first flow: `POST /sessions`, `POST /sessions/{id}/events`
  with `user.message`, then `GET /sessions/{id}/events/stream`. Direct `POST /tasks` returns only
  `id` and `status`; task detail/stream/cancel paths currently take a bare UUID.
- Worker currently runs the Redis Stream event consumer and batch persistence path.
- Frontend's main product surface is under `/managed/**`; root redirects authenticated users to `/managed/quickstart`.
- Docker Compose has one active file: `deploy/docker-compose.yml`. Local Redis is behind the `local-redis` profile.
- The supported quick-start is `cd deploy && ./deploy.sh doctor && ./deploy.sh local`; the orchestrator is Rust via the `rust-orchestrator` profile.
- Local deployment defaults use Docker Official Images multi-arch mirrors (`public.ecr.aws/docker/library/`) to avoid single-arch image resolution under arm64 Docker daemons.
- SkillSpector local source defaults to `.deps/SkillSpector`; `deploy.sh doctor/local` prepares it when missing.
- Collaboration ownership is explicit: API owns product HTTP/SSE/auth, Rust orchestrator owns scheduling/sandbox/gRPC, runner owns in-sandbox execution, worker owns durable event persistence, PostgreSQL owns truth, and Redis owns wakeups/streams/pubsub/commands.
- Core deployment image lifecycle covers backend, frontend, Rust orchestrator, and SkillSpector. Agent runtime images are single-architecture builds and require an explicit `--arch`; invalid multi-arch runtime push combinations fail before any image build/push starts.

## Verification Notes

- `git diff --check` passes.
- Stale deployment-command scans no longer find runnable references to `python-orchestrator`,
  the removed Python orchestrator ASGI entrypoint, or the removed all-in-one Python startup path
  outside historical migration notes.
- Relative Markdown link audit checked 30 Markdown files after excluding dependency,
  virtualenv, and `skills/**` directories.
- Ruby YAML parsing succeeds for `deploy/docker-compose.yml`,
  `backend/config/oauth_providers.yaml`, and `backend/config/oauth_providers.example.yaml`.
  `./deploy.sh doctor` resolves the local platform, prepares local env files and SkillSpector,
  validates compose config, and does not start containers. `docker-compose --profile local-redis
  --profile rust-orchestrator --profile init config` resolves the supported local service set with
  multi-arch official image defaults.
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
- Deployment architecture notes were checked against `deploy/deploy.sh`,
  `deploy/docker-compose.yml`, `deploy/.env.example`, and `deploy/docker/*.Dockerfile`.
- `deploy/.env.example` variable reachability was checked against `deploy/**`,
  `backend/app/**`, `backend/joysafeter_skillspector/**`, and `frontend/**`; no completely
  unused env keys were found in that scope.
- Old-platform scans still intentionally match docs that explain removed v1 concepts
  (`CHANGELOG.md`, `docs/ARCHITECTURE*.md`, and selected tutorials). `skills/**` is outside the
  scan scope for this pass.
