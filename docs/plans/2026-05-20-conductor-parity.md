# Conductor 1:1 Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bring the JoySafeter Python conductor to full 1:1 feature parity with the agentd Rust conductor, excluding conductor-kernel, conductor-runner, and conductor-runtime.

**Architecture:** The agentd conductor is a Rust monolith split into 6 crates. JoySafeter already has a Python translation covering ~70% of the functionality. This plan addresses the remaining ~30% across 4 layers: models/schemas, services/store, API routes, and sandbox/config. Each task is scoped to a single coherent unit of work.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (async), Pydantic v2, asyncio, aioredis, aiodocker, gRPC (grpcio), Alembic

---

## Layer 1: Models & Schemas (conductor-types parity)

### Task 1: Add missing ORM columns — agents table

**Files:**
- Modify: `backend/app/conductor/models/agent.py`
- Create: `backend/alembic/versions/20260520_000001_add_agents_commands_columns.py`

**Step 1: Add ORM columns**

In `models/agent.py`, add two JSONB columns to `ConductorAgent`:

```python
agents = Column(JSONB, nullable=False, server_default="[]")
commands = Column(JSONB, nullable=False, server_default="[]")
```

**Step 2: Create migration**

```python
def upgrade() -> None:
    op.add_column("conductor_agents", sa.Column("agents", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.add_column("conductor_agents", sa.Column("commands", postgresql.JSONB(), nullable=False, server_default="[]"))

def downgrade() -> None:
    op.drop_column("conductor_agents", "commands")
    op.drop_column("conductor_agents", "agents")
```

**Step 3: Commit**
```bash
git add backend/app/conductor/models/agent.py backend/alembic/versions/20260520_000001_*.py
git commit -m "feat(conductor): add agents and commands columns to conductor_agents"
```

---

### Task 2: Add missing ORM columns — sessions table (stats)

**Files:**
- Modify: `backend/app/conductor/models/session.py`
- Create: `backend/alembic/versions/20260520_000002_add_session_stats.py`

**Step 1: Add ORM columns for SessionStats**

In `models/session.py`, add to `ConductorSession`:

```python
active_seconds = Column(Float, nullable=True)
duration_seconds = Column(Float, nullable=True)
```

**Step 2: Create migration**

```python
def upgrade() -> None:
    op.add_column("conductor_sessions", sa.Column("active_seconds", sa.Float(), nullable=True))
    op.add_column("conductor_sessions", sa.Column("duration_seconds", sa.Float(), nullable=True))

def downgrade() -> None:
    op.drop_column("conductor_sessions", "duration_seconds")
    op.drop_column("conductor_sessions", "active_seconds")
```

**Step 3: Commit**

---

### Task 3: Add typed enums and helper functions to schemas

**Files:**
- Modify: `backend/app/conductor/schemas/agent.py`
- Modify: `backend/app/conductor/schemas/session.py`
- Modify: `backend/app/conductor/schemas/sandbox.py`
- Modify: `backend/app/conductor/schemas/memory.py`
- Modify: `backend/app/conductor/schemas/vault.py`

**Step 1: Add `PermissionPolicy` as proper discriminated union**

In `schemas/agent.py`:

```python
class PermissionPolicy(BaseModel):
    type: Literal["always_allow", "always_ask"] = "always_allow"

    def to_mode_str(self) -> str:
        if self.type == "always_allow":
            return "bypassPermissions"
        return "default"
```

**Step 2: Add `extract_permission_mode()` helper**

```python
def extract_permission_mode(tools: list[dict]) -> str:
    for tool in tools:
        tool_type = tool.get("type", "")
        if tool_type in ("agent_toolset_20260401", "mcp_toolset"):
            dc = tool.get("default_config", {})
            pp = dc.get("permission_policy", {})
            if pp.get("type") == "always_ask":
                return "default"
    return "bypassPermissions"
```

**Step 3: Add `InjectConfig` schema**

```python
class InjectConfig(BaseModel):
    name: str
    target: str
    tar_gz_b64: str
```

**Step 4: Add `ContentBlock` enum**

In `schemas/session.py`:

```python
class ContentBlock(BaseModel):
    type: Literal["text", "image", "document"]
    text: Optional[str] = None
    source: Optional[dict[str, Any]] = None

    @classmethod
    def text_block(cls, text: str) -> "ContentBlock":
        return cls(type="text", text=text)
```

**Step 5: Add `SessionAgent.from_agent()` constructor**

```python
class SessionAgent(BaseModel):
    # ... existing fields ...

    @classmethod
    def from_agent(cls, agent) -> "SessionAgent":
        return cls(
            id=agent.id,
            version=agent.version,
            name=agent.name,
            description=agent.description,
            model=agent.model,
            system=agent.system_prompt,
            tools=agent.tools or [],
            skills=agent.skills or [],
            mcp_servers=agent.mcp_configs or [],
            multiagent=agent.multiagent,
        )
```

**Step 6: Add sandbox typed schemas**

In `schemas/sandbox.py`:

```python
class SandboxStatus(str, Enum):
    CREATING = "creating"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    IDLE = "idle"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    DESTROYED = "destroyed"
    POOLED = "pooled"

class SandboxProvisionStatus(BaseModel):
    stage: str = ""
    progress: int = 0
    message: str = ""
    complete: bool = False
    error: bool = False
    error_message: Optional[str] = None

class MemoryMount(BaseModel):
    store_id: uuid.UUID
    mount_name: str
    host_path: str
    access: str = "read_write"

class SandboxConfig(BaseModel):
    image: str
    env: dict[str, str] = {}
    cpu: Optional[float] = None
    memory_mb: Optional[int] = None
    disk_mb: Optional[int] = None
    timeout: int = 7200
    workspace_host_path: Optional[str] = None
    networking: Optional[dict] = None
    memory_mounts: list[MemoryMount] = []
```

**Step 7: Add `MemoryOperation`, `MemoryAccess` enums and `MemoryPrefix` to memory schemas**

In `schemas/memory.py`:

```python
class MemoryOperation(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"

class MemoryAccess(str, Enum):
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"

class MemoryPrefix(BaseModel):
    type: str = "memory_prefix"
    path: str
```

**Step 8: Add `CredentialType` enum, `OAuthConfig.is_expired_or_near_expiry()`, `VaultCredential.auth_header_value()`**

In `schemas/vault.py`:

```python
class CredentialType(str, Enum):
    STATIC_BEARER = "static_bearer"
    MCP_OAUTH = "mcp_oauth"

# In OAuthConfigSchema:
def is_expired_or_near_expiry(self, buffer_seconds: int = 300) -> bool:
    if not self.expires_at:
        return True
    from datetime import datetime, timezone
    return self.expires_at < datetime.now(timezone.utc) + timedelta(seconds=buffer_seconds)
```

**Step 9: Add `Packages.install_commands()` and `Networking` helpers**

In `schemas/environment.py`:

```python
class Packages(BaseModel):
    apt: list[str] = []
    pip: list[str] = []
    npm: list[str] = []
    cargo: list[str] = []
    gem: list[str] = []
    go: list[str] = []

    def is_empty(self) -> bool:
        return not any([self.apt, self.pip, self.npm, self.cargo, self.gem, self.go])

    def install_commands(self) -> list[str]:
        cmds = []
        if self.apt:
            cmds.append(f"apt-get update && apt-get install -y {' '.join(self.apt)}")
        if self.pip:
            cmds.append(f"pip install {' '.join(self.pip)}")
        if self.npm:
            cmds.append(f"npm install -g {' '.join(self.npm)}")
        if self.cargo:
            cmds.append(f"cargo install {' '.join(self.cargo)}")
        if self.gem:
            cmds.append(f"gem install {' '.join(self.gem)}")
        if self.go:
            cmds.append(f"go install {' '.join(self.go)}")
        return cmds

class Networking(BaseModel):
    type: str = "unrestricted"
    allowed_hosts: list[str] = []
    allow_mcp_servers: bool = True
    allow_package_managers: bool = True

    def is_default(self) -> bool:
        return self.type == "unrestricted"

    @staticmethod
    def normalize_allowed_host(host: str) -> str:
        host = host.lower().strip()
        for prefix in ("https://", "http://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
        return host.rstrip("/")
```

**Step 10: Add domain error types**

Create: `backend/app/conductor/errors.py`

```python
class ConductorError(Exception):
    pass

class NotFoundError(ConductorError):
    pass

class AlreadyExistsError(ConductorError):
    pass

class InvalidInputError(ConductorError):
    pass

class ConflictError(ConductorError):
    pass
```

**Step 11: Commit**

---

### Task 4: Add `parse_*_id()` utility functions

**Files:**
- Create: `backend/app/conductor/schemas/id_utils.py`

```python
import uuid

def parse_prefixed_id(value: str, prefix: str) -> uuid.UUID:
    if value.startswith(prefix):
        value = value[len(prefix):]
    return uuid.UUID(value)

def parse_agent_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "agent_")

def parse_session_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "sess_")

def parse_task_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "task_")

def parse_environment_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "env_")

def parse_memory_store_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "memstore_")

def parse_memory_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "mem_")

def parse_memory_version_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "memver_")

def parse_vault_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "vault_")

def parse_credential_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "cred_")

def serialize_prefixed_id(value: uuid.UUID, prefix: str) -> str:
    return f"{prefix}{value}"
```

**Commit.**

---

## Layer 2: Services/Store (conductor-store parity)

### Task 5: Add missing agent service methods

**Files:**
- Modify: `backend/app/conductor/services/agent_service.py`

Add these methods:

1. `hard_delete_agent(agent_id)` — cascade-delete sessions (events, tasks, memory stores), then delete versions, then agent
2. `archive_sessions_for_agent(agent_id)` — bulk set `archived_at`, set `status='terminated'`, return list of session UUIDs
3. `get_agent_version_snapshot(agent_id, version)` — single version lookup
4. `list_active_tasks_for_agent(agent_id)` — filter `status IN ('pending','scheduling','running')`

**Commit.**

---

### Task 6: Add missing task service methods

**Files:**
- Modify: `backend/app/conductor/services/task_service.py`

Add these methods:

1. `append_task_output(task_id, chunk)` — `UPDATE SET output = output || $chunk`
2. `update_task_chat_session(task_id, session_id)` — reassign task session
3. `reset_sandbox_tasks_to_pending(sandbox_id)` — bulk reset scheduling→pending
4. `list_running_tasks()` — filter by status='running'
5. `list_pending_tasks()` — filter by status='pending'
6. Fix `claim_task_for_scheduling` to set `started_at = func.now()` per Rust behavior

**Commit.**

---

### Task 7: Add missing secret & environment service methods

**Files:**
- Modify: `backend/app/conductor/services/secret_service.py`
- Modify: `backend/app/conductor/services/environment_service.py`

For secrets:
1. `hard_delete_secret(secret_id)` — physical DELETE
2. `secret_is_referenced(name)` — check if any agent references this secret
3. Purge soft-deleted rows on `create_secret` before inserting

For environments:
1. `environment_is_referenced_by_sessions(env_name, env_id)` — check sessions
2. `get_environment_by_ref(ref_str)` — parse `env_<uuid>` format, fallback to name lookup
3. Purge soft-deleted rows on `create_environment` before inserting

**Commit.**

---

### Task 8: Add missing session service methods

**Files:**
- Modify: `backend/app/conductor/services/session_service.py`

Add:
1. `batch_insert_session_events(events)` — batch insert with per-session seq computation
2. `list_session_events_filtered(session_id, after_seq, limit, event_types)` — type filter
3. `list_all_memories_for_session(session_id)` — join session_memory_stores → memory_stores → memories
4. State machine guard in `update_session_status` (running only from idle/rescheduling, etc.)
5. Archive session: guard against running status (return 409)
6. `accumulate_usage`: ensure per-model breakdown (`by_model`) is tracked

**Commit.**

---

### Task 9: Add missing sandbox service methods

**Files:**
- Modify: `backend/app/conductor/services/sandbox_service.py`

Add all GC-related methods:
1. `update_status(sandbox_id, status)` — unconditional update (no CAS)
2. `update_status_and_config(sandbox_id, status, config)` — also sets `last_used_at`
3. `list_idle_expired(timeout_seconds)` — idle sandboxes past TTL
4. `list_pool_stale(max_age_seconds)` — stale pooled sandboxes
5. `count_pool_by_provider_image(provider, image)` — pool sizing query
6. `list_all_pooled()` — all pooled sandboxes
7. `list_provisioning()` — all provisioning sandboxes
8. `complete_task(sandbox_id, task_id, status)` — sandbox post-task cleanup
9. `list_stopping(timeout_seconds)` — stuck stopping sandboxes
10. `list_stopped_expired(max_age_seconds)` — stopped past TTL
11. Fix `find_by_session` to filter proper status set matching Rust: `('idle','provisioning','stopped','stopping','error')`

**Commit.**

---

### Task 10: Add missing vault & memory service methods

**Files:**
- Modify: `backend/app/conductor/services/vault_service.py`
- Modify: `backend/app/conductor/services/memory_service.py`
- Modify: `backend/app/conductor/services/vault_cipher.py`

For vault:
1. `archive_vault` should cascade soft-delete credentials
2. `delete_vault` should hard-delete credentials, then vault
3. Add `update_credential_token(cred_id, new_token, new_expires_at)` standalone method
4. Purge soft-deleted rows on `create_vault` before inserting

For memory:
1. `is_live_version(store_id, version_id)` — check `memories.current_version_id`
2. Fix `redact_memory_version` to also null `content_sha256`, `content_size_bytes`, `path`
3. `list_memories` — add `path_prefix` filter and `order_by`/`order` params
4. `list_memory_versions` — add `memory_id`, `session_id`, `operation` filters
5. `upsert_memory_from_agent` — skip update if SHA256 matches

For vault_cipher:
1. Add `decrypt_or_passthrough(stored)` — passthrough non-encrypted values
2. Align encryption format: add `enc:` prefix to ciphertext for Rust compatibility

**Commit.**

---

### Task 11: Fix Redis key naming for Rust compatibility

**Files:**
- Modify: `backend/app/conductor/kernel/redis_coordinator.py`
- Modify: `backend/app/conductor/kernel/queue.py`

Change Redis key names to match Rust:
- `conductor:queue:global` → `conductor:global_queue`
- `conductor:queue:sandbox:{id}` → `conductor:sandbox_queue:{id}`

Also align LPUSH/BRPOP → RPUSH/BLPOP to match Rust's FIFO direction.

Fix `register_instance` to accept and store `grpc_addr` and `http_addr` parameters.

Add `is_healthy()` method to RedisCoordinator.

**Commit.**

---

## Layer 3: API Routes (conductor-api parity)

### Task 12: Fix agent API routes

**Files:**
- Modify: `backend/app/conductor/api/agents.py`
- Modify: `backend/app/conductor/api/router.py`

1. Add `GET /agents/{agent_id}/tasks` dedicated endpoint
2. Add `GET /agents/{agent_id}/sessions` dedicated endpoint
3. Add `?include_archived` query param to `GET /agents`
4. Add MCP server cross-validation (tool mcp_server_name must reference declared mcp_server)
5. Add no-op detection on update (compare serialized JSON minus version/updated_at)
6. Add optimistic concurrency check on update (version CAS → 409 on mismatch)
7. `DELETE /agents/{id}` — add sandbox teardown: gRPC CancelTask, shutdown bridges, provider.stop(), provider.teardown_networking(), then hard_delete_agent
8. `POST /agents/{id}/archive` — add `cancel_active_tasks_for_agent` with bridge shutdown and SSE events

**Commit.**

---

### Task 13: Fix session API routes — create & delete

**Files:**
- Modify: `backend/app/conductor/api/sessions.py`

1. `POST /sessions` — support `agent` as `{type, id, version}` object for pinned agent versions
2. `POST /sessions` — enforce `environment_id` as required with `env_` prefix parsing
3. `POST /sessions` — limit memory_store resources to 8 max
4. `POST /sessions` — compute `mount_name` by slugifying store name
5. `DELETE /sessions/{id}` — block if running (409), emit `session.deleted` event, teardown sandbox (stop, destroy, teardown_networking), hard_delete_session

**Commit.**

---

### Task 14: Fix session events dispatch — the critical endpoint

**Files:**
- Modify: `backend/app/conductor/api/sessions.py`

This is the most complex endpoint. Implement Rust's full dispatch pipeline:

1. Validate session is not archived, terminated, or rescheduling
2. Reject `user.message` if session is already running
3. Validate `user.message` content is array of `{type:"text", text:string}` blocks
4. For `user.message`: create task, mark session running (insert `session.status_running` event, broadcast SSE), push to scheduler
5. For `user.custom_tool_result`: resolve `tool_use_call_id` via event store, try direct bridge injection with `__conductor_input_v1__:` prefix, fallback to `enqueue_session_task_with_retry(max_retries=3)`
6. For `user.tool_confirmation`: resolve `control_request_id` from bridge's pending map, fallback to `resolve_tool_use_call_id`
7. For `user.interrupt`: encode interrupt live-input with `source_event_id`
8. After all events: `replay_pending_control_inputs_for_session` to replay unprocessed control events
9. Return `{"events": [...]}` wrapper (not bare array)

**Commit.**

---

### Task 15: Fix task API routes

**Files:**
- Modify: `backend/app/conductor/api/tasks.py`

1. `POST /tasks` — support `environment_ref`, auto-create ChatSession if needed
2. `POST /tasks/{id}/cancel` — send gRPC CancelTask to bridge, update session to idle, emit SSE event
3. WebSocket stream — add Redis pub/sub cross-instance fallback (`_stream_via_redis` is Python-only and already present; verify it works)

**Commit.**

---

### Task 16: Fix secret & environment API routes

**Files:**
- Modify: `backend/app/conductor/api/secrets.py`
- Modify: `backend/app/conductor/api/environments.py`

For secrets:
1. `GET /secrets` — return redacted list `{id, name, keys: [...], created_at, updated_at}` (no values)
2. `DELETE /secrets/{id}` — check `secret_is_referenced()`, block with 409 unless `?force=true`

For environments:
1. `POST /environments` — validate packages build synchronously (fail request on error)
2. `POST /environments/{id}` — block update if archived (409)
3. `DELETE /environments/{id}` — check `environment_is_referenced_by_sessions()`, block with 409
4. `POST /environments/{id}/archive` — return 409 if already archived (not idempotent)
5. Add `?include_archived` query param to `GET /environments`

**Commit.**

---

### Task 17: Fix memory store API routes

**Files:**
- Modify: `backend/app/conductor/api/memory_stores.py`

1. `POST /memory_stores` — metadata validation (max 16 keys, keys 1-64 chars, values max 512 chars, all string values)
2. `POST /memory_stores/{id}` (update) — partial metadata patching (null values remove keys)
3. `POST /memory_stores/{id}/memories` — Unicode NFC path normalization, path validation (starts with `/`, max 1024 bytes, no `.`/`..` segments, no `//`, no control chars), path conflict check (409), content max 100KB, SHA-256 computation, `?view=full` support
4. `GET /memory_stores/{id}/memories` — add `?path_prefix`, `?depth` (hierarchical view with `MemoryPrefix` rollup), `?order_by`, `?order`, `?view=full`
5. `POST /memories/{id}` (update) — add `?path` for move, precondition as `{type, content_sha256}` object
6. `DELETE /memories/{id}` — add `?expected_content_sha256` query param
7. `GET /memory_versions` — add `?memory_id`, `?session_id`, `?operation`, `?view=full` filters
8. `POST /memory_versions/{id}/redact` — block if live version (409)
9. SSE event stream — add `?types[]` query param filter for event types
10. Return response bodies on DELETE operations (not 204)

**Commit.**

---

### Task 18: Fix vault API routes

**Files:**
- Modify: `backend/app/conductor/api/vaults.py`

1. Token redaction: `token_value` → first 6 chars + `***`, redact `oauth_config.client_secret` and `oauth_config.refresh_token`
2. Return `{"deleted": true}` on DELETE (not 204)
3. Ensure `vault_` and `cred_` ID prefixes in responses
4. Vault update: only accept `description` and `metadata` (not `name`)

**Commit.**

---

## Layer 4: Sandbox & Config (conductor-sandbox parity)

### Task 19: Fix Docker provider socket path for Envoy compatibility

**Files:**
- Modify: `backend/app/conductor/sandbox/docker_provider.py`
- Modify: `backend/app/conductor/sandbox/envoy_manager.py`

1. Change socket mount from flat `/tmp/conductor-sockets/grpc.sock` to per-sandbox `/sockets/<sandbox_id>/grpc.sock`
2. Change container label from `conductor.managed=true` to `conductor=true`
3. Add start-failure rollback (destroy container if start fails)
4. Use standardized provisioning stage names: `"runtime_booting"`, `"container_starting"`, `"provider_failed"`, `"provider_pending"`
5. Pass `cpu`/`memory_mb` from SandboxConfig to container HostConfig

**Commit.**

---

### Task 20: Fix sandbox resolver — pool provisioning & memory preloading

**Files:**
- Modify: `backend/app/conductor/kernel/sandbox_resolver.py`

1. Fix pool sandbox provisioning: `_manage_pool_inner()` must call `provider.create()` + `provider.start()`, not just create a DB record
2. Add memory preloading at provision time: call `list_all_memories_for_session()`, write files to `<workspace>/.memory/<mount_name>/`, create `MemoryMount` entries
3. Add pool claim liveness check: after `claim_from_pool()`, check `provider.status()`, handle Stopped (restart) and broken (destroy+create new)
4. Add multi-image map support: `image_for_provider(engine_kind)` with `CONDUCTOR_IMAGE_CLAUDE` / `CONDUCTOR_IMAGE_CODEX` env vars

**Commit.**

---

### Task 21: Fix configuration — expose hardcoded values and add hot-reload

**Files:**
- Modify: `backend/app/conductor/config.py`
- Modify: `backend/app/conductor/lifespan.py`
- Modify: `backend/app/conductor/kernel/runtime_config.py`

1. Add to `ConductorConfig`:
   - `image_claude: str` / `image_codex: str` (multi-image map)
   - `event_batch_enabled: bool = True`
   - `event_batch_max_size: int = 50`
   - `event_batch_max_delay_ms: int = 50`
   - `grpc_public_url: Optional[str] = None`

2. Wire config values into `lifespan.py` instead of hardcoded values

3. Add SIGHUP handler in lifespan for runtime_config hot-reload:
```python
import signal
def _setup_sighup_handler(runtime_config, config):
    def handler(signum, frame):
        new_cfg = ConductorConfig()
        runtime_config.update(
            idle_timeout_sec=new_cfg.sandbox_idle_timeout,
            stopped_max_age_sec=new_cfg.sandbox_stopped_ttl,
            ...
        )
    signal.signal(signal.SIGHUP, handler)
```

**Commit.**

---

### Task 22: Fix gRPC server — populate missing StartTask fields

**Files:**
- Modify: `backend/app/conductor/grpc/server.py`

1. Populate `StartTask.max_turns` from agent config or default
2. Populate `StartTask.work_dir` from session's `last_work_dir`
3. Populate `StartTask.repos` from agent config (if applicable)
4. Populate `SetupSandbox.setup_commands` from agent/environment config
5. Parse `TokenUsage.by_model` (repeated `ModelUsageEntry`) in `_handle_result` instead of dropping it
6. Handle `RunnerReady.active_task_id` for reconnection to in-flight tasks

**Commit.**

---

### Task 23: Fix Daytona & E2B provider resource values from config

**Files:**
- Modify: `backend/app/conductor/sandbox/daytona_provider.py`
- Modify: `backend/app/conductor/sandbox/e2b_provider.py`

1. Daytona: derive `disk` from `config.disk_mb / 1024` instead of hardcoded 20GB
2. Daytona: derive `memory` from `config.memory_mb / 1024` instead of hardcoded 4GB
3. E2B: derive timeout from `config.timeout` instead of hardcoded 7200
4. E2B: include `creating` state in `list_active`

**Commit.**

---

### Task 24: Add health check and vault provider to gRPC state

**Files:**
- Modify: `backend/app/conductor/lifespan.py`
- Modify: `backend/app/conductor/api/health.py`

1. Pass vault_provider to gRPC server state
2. Add `PgStore.health_check()` equivalent — `SELECT 1` probe on the DB
3. Add `RedisCoordinator.is_healthy()` — check pool status

**Commit.**

---

## Layer 5: Integration & Alignment

### Task 25: Align VaultCipher format for Rust cross-compatibility

**Files:**
- Modify: `backend/app/conductor/services/vault_cipher.py`

1. Support hex key encoding (64-char hex → 32 bytes) alongside existing base64
2. Add `enc:` prefix to encrypted output for Rust compatibility
3. Add `decrypt_or_passthrough()` — if value starts with `enc:`, decrypt; otherwise return as-is
4. Keep backward compatibility: detect old format (no `enc:` prefix) and decrypt with legacy logic

**Commit.**

---

### Task 26: Fix SSE session event stream payload flattening

**Files:**
- Modify: `backend/app/conductor/schemas/session.py`
- Modify: `backend/app/conductor/api/sessions.py`

Rust's `SessionEvent` custom `Serialize` flattens `payload` fields into top-level. Implement the same:

```python
class SessionEventResponse(BaseModel):
    # ... existing fields ...

    def flatten_payload(self) -> dict:
        base = {
            "id": f"evt_{self.id}",
            "type": self.event_type,
            "session_id": f"sess_{self.session_id}",
            "seq": self.seq,
            "created_at": self.created_at.isoformat(),
        }
        if self.processed_at:
            base["processed_at"] = self.processed_at.isoformat()
        if isinstance(self.payload, dict):
            base.update(self.payload)
        return base
```

Use this in SSE stream and event listing responses.

**Commit.**

---

### Task 27: End-to-end verification

**Files:**
- Create: `scripts/e2e/test_conductor_api.py`

Write a minimal e2e test script that:
1. Creates a secret
2. Creates an environment
3. Creates an agent referencing the secret and environment
4. Creates a session with memory stores
5. Sends a `user.message` event
6. Lists events and verifies SSE stream
7. Cancels the task
8. Archives and deletes resources
9. Verifies health endpoints

Run: `python scripts/e2e/test_conductor_api.py`

**Commit.**

---

## Execution Order

Tasks 1-4 (models/schemas) must be done first — they are leaf dependencies.
Tasks 5-11 (services) depend on tasks 1-4.
Tasks 12-18 (API routes) depend on tasks 5-11.
Tasks 19-24 (sandbox/config) can be done in parallel with tasks 12-18.
Tasks 25-26 (alignment) depend on all above.
Task 27 (e2e) is the final verification.

Recommended batching for parallel execution:
- **Batch 1:** Tasks 1-4 (models/schemas) — 4 parallel agents
- **Batch 2:** Tasks 5-11 (services) — 7 parallel agents
- **Batch 3:** Tasks 12-18 (API) + Tasks 19-24 (sandbox/config) — 13 parallel agents
- **Batch 4:** Tasks 25-27 (alignment + verification)
