# EverOS Sidecar Integration Design

## Status

Approved for implementation planning.

## Goal

Integrate EverOS into JoySafeter from source, while running it as a dedicated
backend service container that Claude Code, Codex, and Native execution
sandboxes can call.

The target shape is:

```text
backend/app/everos/          # vendored EverOS source inside JoySafeter backend
        |
        v
compose service: everos      # long-running backend service container
        |
        v
http://everos:8003           # internal service URL
        |
        v
Claude/Codex/Native sandbox  # calls EverOS service over the Docker network
```

## Decisions

### Source Location

EverOS source will live under `backend/app/everos/`.

This makes EverOS part of the JoySafeter backend source tree rather than an
opaque external package. The import path must be adapted from `everos.*` to
`app.everos.*`, including regular imports and string-based dynamic imports.

### Runtime Shape

EverOS will run as its own long-running service container named `everos`, not
inside the existing `api`, `orchestrator`, or `worker` processes.

Although the source is inside `backend/app`, EverOS owns its own runtime
lifespan: SQLite, LanceDB, cascade watcher, and OME scheduler. Keeping it in a
separate service container prevents those threads, locks, and shutdown rules
from interfering with JoySafeter task orchestration.

### Port And URL

EverOS will listen on port `8003`.

Internal URL:

```text
http://everos:8003
```

Execution sandboxes receive:

```text
EVEROS_BASE_URL=http://everos:8003
```

Optional host mapping may expose `127.0.0.1:8003` for local debugging.

### Persistence

EverOS will use a dedicated container data directory:

```text
/data/everos
```

Docker Compose will mount a persistent volume:

```text
everos-data:/data/everos
```

EverOS keeps its native Markdown-first storage model:

- Markdown files are the source of truth.
- SQLite stores runtime state, buffers, cascade queue, and OME state.
- LanceDB stores rebuildable retrieval indexes.

These files are owned by the EverOS service container, not by ordinary
Claude/Codex/Native execution sandboxes.

## Service Configuration

The EverOS service should be launched from the JoySafeter backend image with a
service role and app module such as:

```env
JOYSAFETER_SERVICE_ROLE=everos
BACKEND_APP_MODULE=app.everos.entrypoints.api.app:create_app
BACKEND_PORT=8003
EVEROS_ROOT=/data/everos
```

The EverOS service must receive the LLM, embedding, and optional rerank
configuration expected by EverOS. JoySafeter deployment examples should expose
these through `.env.example` rather than hardcoding provider values.

## Docker Compose Changes

Add an `everos` service to `deploy/docker-compose.yml`.

Expected traits:

- Builds from the JoySafeter backend image.
- Runs one worker.
- Exposes container port `8003`.
- Joins `joysafeter-network`.
- Mounts `everos-data:/data/everos`.
- Has a healthcheck against `http://localhost:8003/health`.
- Starts before services that depend on EverOS memory integration.

The existing `api`, `orchestrator`, and `worker` service roles remain
separate.

## Sandbox Access

For unrestricted Docker sandboxes, `DockerSandboxProvider` already places
sandboxes on the configured Docker network when `JOYSAFETER_ENVOY_NETWORK` or
equivalent network settings are used. Those sandboxes can call
`http://everos:8003`.

For limited networking mode, EverOS must be explicitly allowed. The integration
should either:

- add `everos` / `everos:8003` to the generated allowed-host policy, or
- route access through the existing Envoy mechanism.

The initial implementation may only support unrestricted networking, but it
must make the limited-network gap explicit and fail predictably.

## Relationship To Existing Memory Store

The existing Memory Store remains unchanged.

Current Memory Store:

```text
Agent writes /mnt/memory
  -> Rust FUSE
  -> gRPC MemoryFileSync
  -> PostgreSQL joysafeter_memories
```

EverOS adds a separate cognitive memory service:

```text
Conversation/task events or Agent tool calls
  -> EverOS HTTP API
  -> Markdown + SQLite + LanceDB
```

No existing `/mnt/memory` behavior should be removed or replaced in the first
integration phases.

## Integration Phases

### Phase 1: Service Boot And Health

Deliverables:

- Copy EverOS source into `backend/app/everos/`.
- Adapt imports to `app.everos.*`.
- Add EverOS dependencies to backend packaging.
- Add EverOS service configuration to Docker Compose.
- Add `everos-data` volume.
- Start the service on port `8003`.
- Verify `GET /health` succeeds from inside the compose network.

Phase 1 does not require automatic memory extraction yet.

### Phase 2: Execution Sandbox Access

Deliverables:

- Inject `EVEROS_BASE_URL=http://everos:8003` into Claude Code, Codex, and
  Native sandboxes.
- Append a small system-prompt note that the EverOS memory service is available.
- Verify a sandbox can call `GET $EVEROS_BASE_URL/health`.
- Document behavior for limited networking mode.

### Phase 3: Platform-Managed Memory

Deliverables:

- Add a JoySafeter client for EverOS HTTP calls.
- Add a subscriber or orchestrator integration that converts task/session
  events into EverOS `/api/v1/memory/add` requests.
- Call `/api/v1/memory/flush` at task/session completion.
- Search EverOS before a new task and inject relevant memories into the system
  prompt.
- Keep failures non-fatal to the primary task execution path.

### Phase 4: Agent-Managed Memory Tools

Deliverables:

- Add a wrapper or MCP tool so agents can search or write EverOS memory without
  manually constructing HTTP requests.
- Make the tool available to Claude Code, Codex, and Native runtimes.
- Verify the tool works from an execution sandbox.

## Error Handling

EverOS should be treated as an optional cognitive memory dependency during
early rollout.

- If EverOS is unavailable, normal task execution should continue.
- Health and startup errors should be visible in logs.
- Memory injection should degrade to no-op when search fails.
- Memory write failures should not fail the task unless a future configuration
  explicitly makes EverOS required.

## Security And Isolation

EverOS HTTP API must stay on the internal Docker network by default.

Do not expose it publicly unless an authentication and authorization layer is
added. EverOS memory calls carry user, project, session, and agent context, so
any future public exposure must enforce tenant isolation at the API boundary.

For the initial internal service:

- `app_id` should be fixed to `joysafeter`.
- `project_id` should use the JoySafeter project UUID.
- user memory should use JoySafeter user id.
- agent memory should use an agent/user scoped id to avoid cross-user leakage.

## Verification Plan

Phase 1 verification:

- Docker compose starts `everos`.
- `curl http://everos:8003/health` succeeds from another compose service.
- `/data/everos/.index` is created in the `everos-data` volume.

Phase 2 verification:

- A Claude Code sandbox can print `$EVEROS_BASE_URL`.
- A Claude Code sandbox can call `/health`.
- Repeat for Codex and Native runtime images.

Phase 3 verification:

- A completed conversation produces EverOS episode Markdown under
  `/data/everos/joysafeter/<project_id>/users/<user_id>/episodes/`.
- A later task with a related prompt gets a non-empty EverOS search result.
- If EverOS is stopped, task execution still succeeds without memory injection.

Phase 4 verification:

- The agent sees the EverOS memory tool.
- The agent can call the tool from inside the sandbox.
- The tool returns results consistent with direct EverOS `/search` calls.
