# JoySafeter API

The JoySafeter HTTP API is served under the `/api/v1` prefix by the **API service**
(`JOYSAFETER_SERVICE_ROLE=api`). Interactive docs are available at
`http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`.

This page summarizes the router groups and the programmatic run flow (create an agent → open
a session → send a message → stream events). For complete request/response schemas, use the
live OpenAPI docs at `/docs`.

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
{ "success": true, "code": 200, "message": "OK", "data": { } }
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
| **LLM Catalog** | `/llm/catalog` | Engine capabilities, Protocol definitions, Provider bindings, Credential Profiles |
| **Credentials** | `/credentials` | Model connections, service credentials, MCP members, lifecycle, and connectivity tests |
| **Credential groups** | `/credential-groups` | MCP server credential groups and closed header-auth schemes |
| **Skills** | `/skills` | CRUD, `import-zip`, files, versions, security-scans, lifecycle transitions, admin `rescan-all` |
| **Skills AI authoring** | `/skills/ai-authoring` | **SSE** `/chat` (LLM authoring turn), `/save-draft` |
| **Sandboxes** | `/sandboxes` | list, get, stop |
| **Memory stores** | `/memory_stores` | store + memory CRUD, versions, redact; sandbox memory sync is relayed through the Rust runtime |
| **Files** | `/files` | upload, list, metadata, download, delete |
| **Organizations** | `/organizations` | org + member CRUD, transfer-ownership |
| **Quickstart** | `/quickstart` | **SSE** `/chat` — guided onboarding LLM proxy |
| **Health** | `/health` | readiness (Postgres + Redis), liveness |

An Agent stores `engine_kind + model_credential_id`. The referenced model Credential stores an
explicit `kind=model + provider + protocol + data` identity. MCP credentials belong to Credential Groups.

## LLM Catalog and model configurations

`GET /api/v1/llm/catalog` is the canonical public compatibility contract:

- Engines declare `supported_protocol_ids` and `preferred_protocol_ids`.
- Providers declare Protocol bindings and Credential Profiles.
- Credential Profiles declare accepted fields, required alternatives, `base_url_key`, and `model_key`.

Create a model Credential with `POST /api/v1/credentials`:

```json
{
  "kind": "model",
  "name": "openai-production",
  "provider": "openai",
  "protocol": "openai_responses",
  "data": {
    "OPENAI_API_KEY": "...",
    "OPENAI_MODEL": "gpt-5"
  },
  "is_default": true
}
```

Create a service Credential with `kind=service`, no `provider` or `protocol`, and arbitrary `data`.
The model identity fields are immutable after creation; `PATCH /credentials/{credential_id}` updates
the mutable credential fields only.

Useful Credential list filters:

| Query | Meaning |
|---|---|
| `kind=model` | Return only model configurations |
| `compatible_engine=codex` | Return only configurations whose Protocol is supported by Codex |
| `name=openai-production` | Exact project-scoped name lookup |
| `provider=openai&protocol=openai_responses` | Filter an explicit Provider/Protocol binding |

List responses expose `provider`, `protocol`, `model`, `compatible_engine_ids`, `is_default`, and
credential field names in `keys`; plaintext credential values are never returned. Defaults are
scoped by Protocol.

Agent creation requires an explicit `engine_kind`; the API does not infer or default an Engine.
Agent create/update and `POST /api/v1/quickstart/chat` validate Engine/Protocol compatibility on
the server. Quickstart chat requests use `engine_kind` (not `provider`) plus `model_credential_id`.

## ID formats

Managed-resource responses serialize IDs with a type prefix, such as `agent_<uuid>`, `agentver_<uuid>`,
`apikey_<uuid>`, `sess_<uuid>`,
`task_<uuid>`, `trig_<uuid>`, `env_<uuid>`, `cred_<uuid>`, `credgrp_<uuid>`, `skill_<uuid>`, `sbx_<uuid>`,
`memstore_<uuid>`, `mem_<uuid>`, `memver_<uuid>`, `sklfile_<uuid>`, `sklscan_<uuid>`, `sklver_<uuid>`,
`sklvfile_<uuid>`, `skluse_<uuid>`, `file_<uuid>`, `sesrsc_<uuid>`, `evt_<uuid>`, `vol_<uuid>`,
`stgrant_<uuid>`, and `staudit_<uuid>`. Typed Agent, Session, Task, Trigger, Environment,
Agent Version, API Key, Credential, Credential Group, Sandbox, Memory Store, Memory, Memory Version, Skill, Skill File,
Skill Security Scan, Skill Version, Skill Version File, Skill Usage, File, Session Resource, Event,
Storage Volume, Storage Grant, and Storage Mount Audit request fields, path parameters, and cursors require
their canonical prefixed form. Bare UUIDs are reserved for database, Redis, protobuf, and explicit
physical adapters documented in `ARCHITECTURE.md`; they are not public API alternatives. Environment
bindings use `environment_id` and require canonical `env_<uuid>` values; names and bare UUIDs are rejected.
Agent `model_credential_id`, Environment `environment_credential_ids` and
`egress_services[].credential_ref`, and Session `credential_group_ids` require canonical typed IDs.
Bare UUIDs and cross-entity prefixes are rejected. Persisted snapshots must use
`joysafeter.agent_execution_snapshot.v2`; runtime readers do not accept earlier aliases or schemas.
Sandbox diagnostics and task/session sandbox references return canonical `sbx_<uuid>` values. Runtime
commands, provider labels/names, Redis keys, and protobuf messages intentionally carry the bare sandbox
UUID and are not public client contracts.
Memory Store CRUD and memory/version routes likewise require canonical Memory IDs. Redis
`memory_update.store_id` and runner `MemoryStoreMount.store_id` intentionally carry the bare store UUID
and are converted back to `MemoryStoreId` inside the Rust command listener.
Skill routes require the matching canonical ID family rather than a generic UUID: root skills use
`skill_`, mutable files use `sklfile_`, scans use `sklscan_`, versions use `sklver_`, immutable version
files use `sklvfile_`, and usage rows use `skluse_`. Cross-family values are rejected even when the UUID
suffix is otherwise valid.
File routes use `file_<uuid>`, while mutable file/repository attachments under a Session use
`sesrsc_<uuid>`. Session memory-store attachments are also Session Resources and return their own
`sesrsc_<uuid>` ID with `type=session_memory_store`. Storage object keys and SQL UUID columns intentionally use the bare File UUID; clients
must retain the canonical prefixes in paths, request bodies, caches, and UI state.
Persisted Session event IDs use `evt_<uuid>` in REST history, SSE payloads, logs, caches, and UI state.
SQL UUID columns and Redis stream fields intentionally use the bare Event UUID; those physical forms
are not accepted by public API contracts.

---

## Programmatic run flow

There is no standalone "graph run" endpoint. The run unit is a **Task**; the conversation
unit is a **Session** with an append-only event log. For integrations that want live output,
prefer the session-first flow below.

### 1. Create a session

`POST /api/v1/sessions` (status `201`). Reference an agent by `agent`, `agent_id`, or
`agent_name`; optionally pass `title`, `environment_id`, `credential_group_ids`, memory-store `resources`,
uploaded `file_resources`, and git `repo_resources`.

```bash
curl -X POST https://your-domain/api/v1/sessions \
  -H "X-Api-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "apk-analyzer", "title": "APK analysis"}'
```

The response envelope's `data.id` is the session ID serialized as `sess_<uuid>`.

### 2. Send the first user message

`POST /api/v1/sessions/{session_id}/events` appends a `user.message`, creates a Task for that
turn, transitions the session to running, and enqueues the task. The API also emits a
`session.status_running` event whose payload contains the created `task_<uuid>` ID.

```bash
curl -X POST https://your-domain/api/v1/sessions/{session_id}/events \
  -H "X-Api-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "user.message", "content": "Analyze this APK: https://example.com/app.apk"}'
```

### 3. Stream live events

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

### 4. Continue the conversation

`POST /api/v1/sessions/{session_id}/events` sends a follow-up user message, which becomes a
new Task scheduled onto the same session's sandbox.

### 5. Low-level task creation

`POST /api/v1/tasks` (status `202`) remains available for direct task enqueue. Reference an
agent by `agent_id` or `agent_name`, provide a `prompt`, and optionally a `chat_session_id`
(a session is auto-created if omitted), canonical `environment_id`, and an `Idempotency-Key` header.

```bash
curl -X POST https://your-domain/api/v1/tasks \
  -H "X-Api-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 2d5e4c21-5b34-42f8-a970-0f6df6b1da6f" \
  -d '{"agent_name": "apk-analyzer", "prompt": "Analyze this APK: https://example.com/app.apk"}'
```

The response envelope's `data` carries only `id` (`task_<uuid>`) and `status`. To stream via
SSE after task-first creation, call `GET /api/v1/tasks/{task_id}` and use its
`chat_session_id` field with `/sessions/{session_id}/events/stream`.

### 6. Read history / cancel

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
  -d '{"name": "Production Key", "role": "developer"}'
```

`POST /api/v1/auth/api-keys` accepts `{name, role}` and returns canonical `id=apikey_<uuid>`, `project_id`, `name`,
`key_prefix`, `role`, and `raw_key`. The raw key is returned only once. List responses return
metadata only: `id`, `project_id`, `name`, `key_prefix`, `role`, `created_at`, and
`last_used_at`.
