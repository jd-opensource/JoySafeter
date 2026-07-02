# JoySafeter API

The JoySafeter HTTP API is served under the `/api/v1` prefix by the **API service**
(`JOYSAFETER_SERVICE_ROLE=api`). Interactive docs are available at
`http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`.

This page summarizes the router groups and the programmatic run flow (create an agent → open
a session → send a message → stream events). For request/response schemas, use the live
OpenAPI docs at `/docs`.

---

## Authentication

Requests authenticate in priority order:

1. **API Key** — `X-Api-Key: <key>` header. Keys are managed under `/api/v1/auth/api-keys`
   (or from the workspace settings UI).
2. **JWT** — `Authorization: Bearer <token>` or an auth cookie, re-verified against the DB.
3. **Cookie/session** — auto-provisions a default org + project on first login.

WebSocket connections authenticate with a short-lived token from `GET /api/v1/auth/ws-token`.
Every project-scoped route is filtered by the caller's active project for multi-tenant isolation.

---

## Response envelope

All JSON responses are wrapped in a canonical envelope:

```json
{ "success": true, "code": "OK", "message": "", "data": { } }
```

On error, `success` is `false` and `data` carries an `ErrorDescriptor`
(`{code, message, data, source, retryable, user_action}`).

> **Streaming paths are exempt.** SSE endpoints (paths ending in `/stream`, and the
> `text/event-stream` responses) and WebSocket endpoints bypass the envelope and emit raw
> event frames.

---

## Router groups

All paths are under `/api/v1`.

| Group | Prefix | Highlights |
|-------|--------|------------|
| **Auth** | `/auth` | sign-up/in, logout, refresh, password reset, email verify, `ws-token`, `switch-context`, projects, `api-keys`, members |
| **OAuth / SSO** | `/auth/oauth` | provider list, authorize, callback, account link/unlink |
| **Agents** | `/agents` | CRUD, archive, versions, `/tasks`, `/sessions` |
| **Tasks** | `/tasks` | create + enqueue, list, get, cancel, **WS** `/tasks/{id}/stream` |
| **Sessions** | `/sessions` | CRUD, archive, stop, `POST /events` (send message), `GET /events` (history), **SSE** `/events/stream`, resources (files/repos) |
| **Environments** | `/environments` | Sandbox image/config CRUD |
| **Secrets** | `/secrets` | Provider API keys (model credentials) + default selection, AES-256-GCM encrypted |
| **Vaults** | `/vaults` | MCP-server credentials + OAuth config |
| **Skills** | `/skills` | CRUD, `import-zip`, files, versions, security-scans, lifecycle transitions |
| **Skills AI authoring** | `/skills/ai-authoring` | **SSE** `/chat` (LLM authoring turn), `/save-draft` |
| **Sandboxes** | `/sandboxes` | list, get, stop |
| **Memory stores** | `/memory_stores` | store + memory CRUD, versions, redact, **SSE** `/events/stream` |
| **Files** | `/files` | upload, list, metadata, download, delete |
| **Organizations** | `/organizations` | org + member CRUD, transfer-ownership |
| **Quickstart** | `/quickstart` | **SSE** `/chat` — guided onboarding LLM proxy |
| **Health** | `/health` | readiness (Postgres + Redis), liveness |

> There are **no** `models`, `model-credentials`, `model-providers`, `mcp`, `tools`,
> `copilot`, `graphs`, or `openapi/graph/*` routers. Model configuration lives in the agent's
> `model` JSONB field plus a `secret_ref` into **Secrets**; MCP credentials live in **Vaults**.

---

## Programmatic run flow

There is no standalone "graph run" endpoint. The run unit is a **Task**; the conversation
unit is a **Session** with an append-only event log. To drive a run over the API:

### 1. Create a task

`POST /api/v1/tasks` (status `202`). Reference an agent by `agent_id` or `agent_name`, provide
a `prompt`, and optionally a `chat_session_id` (a session is auto-created if omitted) and an
`environment_ref`.

```bash
curl -X POST https://your-domain/api/v1/tasks \
  -H "X-Api-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "apk-analyzer", "prompt": "Analyze this APK: https://example.com/app.apk"}'
```

The response envelope's `data` carries the created `task_id` and `chat_session_id`.

### 2. Stream live events

Subscribe to the session's Server-Sent Events stream. Pass `?after_seq=<n>` to replay
persisted events from the database before switching to the live feed:

```bash
curl -N https://your-domain/api/v1/sessions/{session_id}/events/stream \
  -H "X-Api-Key: YOUR_API_KEY"
```

Each frame is a JoySafeter event envelope with a monotonically increasing `seq`
(text, thinking, tool_use, tool_result, model_request_*, task_notification, status, ...).

Alternatively, per-task output is available over WebSocket at
`WS /api/v1/tasks/{task_id}/stream`.

### 3. Continue the conversation

`POST /api/v1/sessions/{session_id}/events` sends a follow-up user message, which becomes a
new Task scheduled onto the same session's sandbox.

### 4. Read history / cancel

- `GET /api/v1/sessions/{session_id}/events` — persisted event history.
- `GET /api/v1/tasks/{task_id}` — task status.
- `POST /api/v1/tasks/{task_id}/cancel` — cancel a running task.

**Task status** follows the FSM
`pending → scheduling → running → {completed, failed, aborted, timeout, cancelled}`
(with retry back to `pending`).

---

## Error responses

Errors use the standard envelope with `success: false`:

```json
{
  "success": false,
  "code": "NOT_FOUND",
  "message": "Agent not found",
  "data": { "source": "api", "retryable": false }
}
```

| HTTP status | Meaning |
|-------------|---------|
| 401 | API key / token missing, invalid, or expired |
| 403 | Insufficient permissions (resource not in the active project) |
| 404 | Resource not found |
| 400 / 422 | Invalid request parameters |
| 503 | Scheduler not running (orchestrator unavailable) |
| 500 | Internal server error |

---

## API Key management

Create API keys from the workspace settings UI, or via the auth API:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/auth/api-keys` | List API keys |
| POST | `/api/v1/auth/api-keys` | Create an API key |
| DELETE | `/api/v1/auth/api-keys/{key_id}` | Delete an API key |

```bash
curl -X POST https://your-domain/api/v1/auth/api-keys \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Production Key"}'
```

> **TODO (verify against `auth.py`):** the exact create/list request and response fields for
> `api-keys` (e.g. key `type`/`scope`, whether the raw key is returned only once) were not
> re-derived here — confirm against the live `/docs` schema before publishing externally.
