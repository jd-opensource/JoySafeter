# Python Orchestrator ↔ Rust Orchestrator Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bring the Python `joysafeter_orchestrator` to full feature parity with the Rust `joysafeter_orchestrator_rs`, covering all differences in state machines, event handling, gRPC, data structures, config, and services.

**Architecture:** The Python orchestrator mirrors the Rust implementation 1:1 in module structure. The gaps fall into 7 categories: (1) missing config fields, (2) missing HarnessInput fields & builder logic, (3) sandbox lifecycle gaps, (4) gRPC/event handling gaps, (5) queue/coordinator/command gaps, (6) memory sync & file injection gaps, (7) dead code cleanup.

**Tech Stack:** Python 3.12, asyncio, gRPC (grpcio), SQLAlchemy, Redis, cryptography (AES-GCM)

---

## Category A: Configuration & Error Handling

### Task 1: Add unified `OrchestratorError` exception hierarchy

**Files:**
- Create: `backend/app/joysafeter_orchestrator/error.py`

**Step 1: Create the error module**

```python
"""Unified orchestrator error types — mirrors Rust OrchestratorError."""

class OrchestratorError(Exception):
    """Base error for all orchestrator operations."""
    pass

class DatabaseError(OrchestratorError):
    """Database query/connection errors."""
    pass

class GrpcError(OrchestratorError):
    """gRPC transport or protocol errors."""
    pass

class RedisError(OrchestratorError):
    """Redis connection or command errors."""
    pass

class DockerError(OrchestratorError):
    """Docker/container provider errors."""
    pass

class ConfigError(OrchestratorError):
    """Configuration loading or validation errors."""
    pass

class SandboxError(OrchestratorError):
    """Sandbox lifecycle errors."""
    pass

class TaskError(OrchestratorError):
    """Task lifecycle errors."""
    pass

class InternalError(OrchestratorError):
    """Catch-all for unexpected internal errors."""
    pass
```

**Step 2: Commit**

```bash
git add backend/app/joysafeter_orchestrator/error.py
git commit -m "feat(orchestrator): add unified OrchestratorError hierarchy (Rust parity)"
```

---

### Task 2: Add missing config fields to JoySafeterConfig

**Files:**
- Modify: `backend/app/joysafeter_shared/config/settings.py` (or wherever `JoySafeterConfig` lives)

The Rust `config.rs` defines many env vars that have no Python counterpart. Add them all:

**Step 1: Add the missing config fields**

Add these fields to the existing `JoySafeterConfig` (or equivalent settings class):

```python
# --- Scheduling ---
max_scheduling_tasks: int = int(os.getenv("JOYSAFETER_MAX_SCHEDULING_TASKS", "50"))
task_default_timeout: int = int(os.getenv("JOYSAFETER_TASK_DEFAULT_TIMEOUT", "7200"))
task_default_max_retries: int = int(os.getenv("JOYSAFETER_TASK_DEFAULT_MAX_RETRIES", "2"))
task_retry_base_ms: int = int(os.getenv("JOYSAFETER_TASK_RETRY_BASE_MS", "2000"))
task_retry_max_ms: int = int(os.getenv("JOYSAFETER_TASK_RETRY_MAX_MS", "30000"))

# --- Sandbox resource limits ---
sandbox_cpu: float | None = _opt_float(os.getenv("JOYSAFETER_SANDBOX_CPU"))
sandbox_memory_mb: int | None = _opt_int(os.getenv("JOYSAFETER_SANDBOX_MEMORY_MB"))
sandbox_disk_mb: int | None = _opt_int(os.getenv("JOYSAFETER_SANDBOX_DISK_MB"))

# --- Per-engine images ---
sandbox_pool_images: list[str] = _csv(os.getenv("JOYSAFETER_SANDBOX_POOL_IMAGES", ""))
image_claude: str = os.getenv("JOYSAFETER_IMAGE_CLAUDE", "joysafeter-claudecode:latest")
image_codex: str = os.getenv("JOYSAFETER_IMAGE_CODEX", "joysafeter-codex:latest")

# --- Event stream (Redis Streams) ---
event_batch_enabled: bool = _bool(os.getenv("JOYSAFETER_EVENT_BATCH_ENABLED", "true"))
event_stream_enabled: bool = _bool(os.getenv("JOYSAFETER_EVENT_STREAM_ENABLED", "false"))
event_stream_key: str = os.getenv("JOYSAFETER_EVENT_STREAM_KEY", "joysafeter:joysafeter:events")
event_stream_group: str = os.getenv("JOYSAFETER_EVENT_STREAM_GROUP", "joysafeter-workers")
event_stream_max_len: int = int(os.getenv("JOYSAFETER_EVENT_STREAM_MAX_LEN", "100000"))
event_stream_batch_size: int = int(os.getenv("JOYSAFETER_EVENT_STREAM_BATCH_SIZE", "100"))
event_stream_block_ms: int = int(os.getenv("JOYSAFETER_EVENT_STREAM_BLOCK_MS", "5000"))
event_stream_fallback_to_db: bool = _bool(os.getenv("JOYSAFETER_EVENT_STREAM_FALLBACK_TO_DB", "true"))
event_stream_pending_idle_ms: int = int(os.getenv("JOYSAFETER_EVENT_STREAM_PENDING_IDLE_MS", "60000"))

# --- gRPC ---
grpc_public_url: str | None = os.getenv("JOYSAFETER_GRPC_PUBLIC_URL")

# --- Envoy networking ---
envoy_enabled: bool = _bool(os.getenv("JOYSAFETER_ENVOY_ENABLED", "false"))
envoy_image: str = os.getenv("JOYSAFETER_ENVOY_IMAGE", "envoyproxy/envoy:v1.31-latest")
envoy_socket_volume: str = os.getenv("JOYSAFETER_ENVOY_SOCKET_VOLUME", "joysafeter_envoy_socks")
envoy_config_dir: str = os.getenv("JOYSAFETER_ENVOY_CONFIG_DIR", "/tmp/joysafeter_envoy")
envoy_network: str = os.getenv("JOYSAFETER_ENVOY_NETWORK", "joysafeter_net")
envoy_grpc_host: str = os.getenv("JOYSAFETER_ENVOY_GRPC_HOST", "host.docker.internal")
envoy_grpc_port: int = int(os.getenv("JOYSAFETER_ENVOY_GRPC_PORT", "9090"))
envoy_container_name: str = os.getenv("JOYSAFETER_ENVOY_CONTAINER_NAME", "joysafeter-envoy")

# --- Image builder ---
image_builder_enabled: bool = _bool(os.getenv("JOYSAFETER_IMAGE_BUILDER_ENABLED", "false"))
image_builder_base: str = os.getenv("JOYSAFETER_IMAGE_BUILDER_BASE", "joysafeter-claudecode:latest")

# --- Vault ---
vault_encryption_key: str | None = os.getenv("JOYSAFETER_VAULT_ENCRYPTION_KEY")

# --- Heartbeat ---
heartbeat_interval: int = int(os.getenv("JOYSAFETER_HEARTBEAT_INTERVAL", "15"))

# --- Daytona ---
daytona_api_url: str | None = os.getenv("JOYSAFETER_DAYTONA_API_URL")
daytona_api_key: str | None = os.getenv("JOYSAFETER_DAYTONA_API_KEY")
daytona_target: str | None = os.getenv("JOYSAFETER_DAYTONA_TARGET")
daytona_snapshot: str | None = os.getenv("JOYSAFETER_DAYTONA_SNAPSHOT")

# --- E2B ---
e2b_api_url: str | None = os.getenv("JOYSAFETER_E2B_API_URL")
e2b_api_key: str | None = os.getenv("JOYSAFETER_E2B_API_KEY")
e2b_template_id: str | None = os.getenv("JOYSAFETER_E2B_TEMPLATE_ID")
```

Also add `image_for_provider(engine_kind: str) -> str` method:

```python
def image_for_provider(self, engine_kind: str) -> str:
    if engine_kind == "codex":
        return self.image_codex
    return self.image_claude
```

**Step 2: Commit**

```bash
git commit -am "feat(config): add all missing Rust-parity config fields"
```

---

## Category B: HarnessInput & Builder Parity

### Task 3: Add missing fields to `HarnessInput` dataclass

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/runtime/adapter.py`

**Step 1: Add missing fields**

Add these fields to `HarnessInput`:

```python
@dataclass
class HarnessInput:
    # ... existing fields ...
    
    # NEW — Rust parity
    provider: str = "claude"                    # engine kind: "claude" | "codex" | "mock"
    setup_commands: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 100
    repos: list[dict] = field(default_factory=list)
```

**Step 2: Commit**

```bash
git commit -am "feat(adapter): add missing HarnessInput fields (Rust parity)"
```

---

### Task 4: Add `VaultCipher` with AES-GCM `enc:` prefix support

**Files:**
- Create: `backend/app/joysafeter_orchestrator/kernel/vault_cipher.py`

**Step 1: Implement VaultCipher**

```python
"""AES-256-GCM vault cipher — mirrors Rust VaultCipher."""
from __future__ import annotations

import base64
import binascii
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ENC_PREFIX = "enc:"
_NONCE_SIZE = 12  # 96-bit nonce for AES-GCM


class VaultCipher:
    """Encrypt/decrypt credential values with AES-256-GCM.
    
    Values prefixed with ``enc:`` are base64-encoded ciphertext
    (nonce ∥ ciphertext ∥ tag).  Values without the prefix are
    returned as-is (passthrough).
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("AES-256 key must be exactly 32 bytes")
        self._gcm = AESGCM(key)

    @classmethod
    def from_env(cls) -> VaultCipher | None:
        raw = os.getenv("JOYSAFETER_VAULT_ENCRYPTION_KEY")
        if not raw:
            return None
        # Try hex first, then base64
        try:
            key = binascii.unhexlify(raw)
        except (ValueError, binascii.Error):
            key = base64.b64decode(raw)
        return cls(key)

    # ------------------------------------------------------------------

    def decrypt_or_passthrough(self, value: str) -> str:
        if not value.startswith(_ENC_PREFIX):
            return value
        blob = base64.b64decode(value[len(_ENC_PREFIX):])
        nonce = blob[:_NONCE_SIZE]
        ciphertext = blob[_NONCE_SIZE:]
        plaintext = self._gcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode()

    def encrypt_or_passthrough(self, value: str) -> str:
        nonce = secrets.token_bytes(_NONCE_SIZE)
        ciphertext = self._gcm.encrypt(nonce, value.encode(), None)
        blob = nonce + ciphertext
        return _ENC_PREFIX + base64.b64encode(blob).decode()
```

**Step 2: Commit**

```bash
git add backend/app/joysafeter_orchestrator/kernel/vault_cipher.py
git commit -m "feat(vault): add AES-256-GCM VaultCipher with enc: prefix (Rust parity)"
```

---

### Task 5: Add OAuth token refresh to HarnessInputBuilder

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/harness_input_builder.py`

**Step 1: Add OAuth refresh logic**

Add a `_maybe_refresh_oauth` method that checks `credential_type == "oauth"`, reads `oauth_config.expires_at`, and if within 300s of expiry, POSTs to `token_url` with `client_id`/`client_secret`/`refresh_token`, writes back the new token + config to DB:

```python
import time
import httpx

async def _maybe_refresh_oauth(
    self,
    credential: dict,
    db_session,
) -> dict:
    """Refresh OAuth token if within 300s of expiry. Returns updated credential."""
    oauth_config = credential.get("oauth_config")
    if not oauth_config or credential.get("credential_type") != "oauth":
        return credential

    expires_at = oauth_config.get("expires_at", 0)
    if time.time() < expires_at - 300:
        return credential  # still fresh

    token_url = oauth_config["token_url"]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(token_url, data={
            "grant_type": "refresh_token",
            "refresh_token": oauth_config["refresh_token"],
            "client_id": oauth_config["client_id"],
            "client_secret": oauth_config["client_secret"],
        })
        resp.raise_for_status()
        token_data = resp.json()

    new_token = token_data["access_token"]
    new_expires_at = time.time() + token_data.get("expires_in", 3600)
    new_refresh = token_data.get("refresh_token", oauth_config["refresh_token"])

    # Update credential in-place and persist
    credential["token_value"] = new_token
    oauth_config["expires_at"] = new_expires_at
    oauth_config["refresh_token"] = new_refresh
    credential["oauth_config"] = oauth_config

    # Persist back to DB via credential service
    await self._credential_svc.update_credential_token(
        credential["id"], new_token, oauth_config, db_session
    )
    return credential
```

**Step 2: Wire into `resolve_vault_credentials`**

In the existing `resolve_vault_credentials` method, after loading each credential, call:
```python
credential = await self._maybe_refresh_oauth(credential, db_session)
```

**Step 3: Also wire VaultCipher decryption for `enc:` prefix**

```python
from joysafeter_orchestrator.kernel.vault_cipher import VaultCipher

# In resolve_vault_credentials, after loading token_value:
cipher = VaultCipher.from_env()
if cipher and credential.get("token_value"):
    credential["tok] = cipher.decrypt_or_passthrough(credential["token_value"])
```

**Step 4: Commit**

```bash
git commit -am "feat(builder): add OAuth token refresh + VaultCipher decryption (Rust parity)"
```

---

### Task 6: Add `setup_commands`, `allowed/disallowed_tools`, `max_turns` extraction to HarnessInputBuilder

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/harness_input_builder.py`

**Step 1: Add `_extract_setup_commands` helper**

```python
def _resolve_environment_setup_commands(self, environment: dict | None) -> list[str]:
    """Generate apt/pip/npm/cargo/gem/go install commands from environment config."""
    if not environment:
        return []
    config = environment.get("config", {})
    packages = config.get("packages", {})
    commands: list[str] = []
    
    apt = packages.get("apt", [])
    if apt:
        commands.append(f"apt-get update && apt-get install -y {' '.join(apt)}")
    pip = packages.get("pip", [])
    if pip:
        commands.append(f"pip install {' '.join(pip)}")
    npm = packages.get("npm", [])
    if npm:
        commands.append(f"npm install -g {' '.join(npm)}")
    cargo = packages.get("cargo", [])
    if cargo:
        commands.append(f"cargo install {' '.join(cargo)}")
    gem = packages.get("gem", [])
    if gem:
        commands.append(f"gem install {' '.join(gem)}")
    go = packages.get("go", [])
    if go:
        commands.extend(f"go install {pkg}" for pkg in go)
    
    return commands


def _extract_agent_setup_commands(self, agent: dict) -> list[str]:
    """Extract setup_commands from agent.metadata."""
    metadata = agent.get("metadata") or {}
    return list(metadata.get("setup_commands", []))
```

**Step 2: Add `_parse_tool_allow_lists` helper**

```python
def _parse_tool_allow_lists(self, agent: dict) -> tuple[list[str], list[str]]:
    """Parse agent_toolset_20260401 into allowed/disallowed tool lists."""
    tools = agent.get("tools") or []
    allowed: list[str] = []
    disallowed: list[str] = []
    for tool in tools:
        if tool.get("type") != "agent_toolset_20260401":
            continue
        tool_name = tool.get("name", "")
        if tool.get("enabled", True):
            allowed.append(tool_name)
        else:
            disallowed.append(tool_name)
    return allowed, disallowed
```

**Step 3: Add `_extract_max_turns` helper**

```python
def _extract_max_turns(self, agent: dict) -> int:
    """Extract max_turns from agent.metadata, default 100."""
    metadata = agent.get("metadata") or {}
    return int(metadata.get("max_turns", 100))
```

**Step 4: Wire into `build()` method**

In the `build()` method, after loading agent and environment, call all three:

```python
env_setup = self._resolve_environment_setup_commands(environment)
agent_setup = self._extract_agent_setup_commands(agent)
allowed_tools, disallowed_tools = self._parse_tool_allow_lists(agent)
max_turns = self._extract_max_turns(agent)

# Pass into HarnessInput:
harness_input = HarnessInput(
    # ... existing fields ...
    setup_commands=env_setup + agent_setup,
    allowed_tools=allowed_tools,
    disallowed_tools=disallowed_tools,
    max_turns=max_turns,
    provider=agent.get("engine_kind", "claude"),
)
```

**Step 5: Commit**

```bash
git commit -am "feat(builder): add setup_commands, tool allow lists, max_turns (Rust parity)"
```

---

## Category C: Sandbox Lifecycle Gaps

### Task 7: Add reverse orphan sweep to SandboxController

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/sandbox_controller.py`

Currently Python only does provider→DB orphan cleanup. Rust also does DB→provider: queries all non-destroyed DB records and checks `provider.status()` on each; if `NotFound`, marks them destroyed.

**Step 1: Add DB→provider reverse sweep**

```python
async def _sweep_db_orphans(self) -> None:
    """Destroy DB records pointing to containers that no longer exist in the provider."""
    async with self._db_session() as session:
        active_sandboxes = await self._sandbox_svc.list_active_sandboxes(session)
    
    for sandbox in active_sandboxes:
        if sandbox.status in ("destroyed", "stopped"):
            continue
        try:
            status = await self._provider.status(sandbox.external_id)
            if status == "not_found":
                logger.warning(
                    "DB orphan detected: sandbox %s (ext=%s) not found in provider, marking destroyed",
                    sandbox.id, sandbox.external_id,
                )
                async with self._db_session() as session:
                    await self._sandbox_record_svc.mark_destroyed(sandbox.id, session)
                # Also remove from bridge registry if present
                bridge = await self._bridge_registry.get(sandbox.external_id)
                if bridge:
                    self._bridge_registry.remove(sandbox.external_id)
        except Exception:
            logger.debug("Failed to check provider status for %s, skipping", sandbox.external_id)
```

**Step 2: Wire into `cleanup_orphaned_provider_sandboxes`**

At the end of the existing method, add:
```python
await self._sweep_db_orphans()
```

**Step 3: Commit**

```bash
git commit -am "feat(sandbox-ctrl): add reverse orphan sweep DB→provider (Rust parity)"
```

---

### Task 8: Add `SandboxStatus` enum and `SandboxCreateConfig` dataclass to provider

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/sandbox/provider.py`

**Step 1: Add SandboxStatus enum and SandboxCreateConfig**

```python
from enum import Enum
from dataclasses import dataclass, field
import uuid

class SandboxStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


@dataclass
class SandboxCreateConfig:
    sandbox_id: uuid.UUID
    image: str
    env: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    work_dir: str | None = None
    cpu_limit: float | None = None
    memory_limit_mb: int | None = None
    network: str | None = None
    workspace_path: str | None = None


@dataclass
class ProviderSandboxInfo:
    id: str
    name: str
    status: SandboxStatus
    image: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
```

**Step 2: Update `SandboxProvider` ABC to accept `SandboxCreateConfig`**

Update the `create` method signature (add alternative overload or update callers):

```python
class SandboxProvider(ABC):
    @abstractmethod
    async def create(self, config: SandboxCreateConfig) -> str:
        """Create a sandbox container, return external_id."""
        ...

    @abstractmethod
    async def status(self, external_id: str) -> SandboxStatus:
        """Return the status of a sandbox."""
        ...

    @abstractmethod
    async def list_active(self) -> list[ProviderSandboxInfo]:
        """List all active sandboxes from the provider."""
        ...

    @abstractmethod
    async def inject_files(self, external_id: str, files: list) -> None:
        """Inject files into a sandbox."""
        ...

    @abstractmethod
    async def exec(self, external_id: str, cmd: list[str], env: dict[str, str] | None = None) -> tuple[int, str, str]:
        """Execute a command, return (exit_code, stdout, stderr)."""
        ...
```

**Step 3: Update docker/daytona/e2b providers to use `SandboxCreateConfig`**

Update each provider's `create()` to accept and destructure a `SandboxCreateConfig`, using `config.cpu_limit`, `config.memory_limit_mb`, etc.

**Step 4: Commit**

```bash
git commit -am "feat(provider): add SandboxStatus, SandboxCreateConfig, ProviderSandboxInfo (Rust parity)"
```

---

### Task 9: Add `last_result_status` and `last_result_error` fields to SandboxBridge

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/sandbox_bridge.py`

**Step 1: Add missing fields**

Add to `SandboxBridge.__init__`:

```python
self.last_result_status: str | None = None
self.last_result_error: str | None = None
self.task_available: asyncio.Event = asyncio.Event()
self.sandbox_id: str = sandbox_db_id  # alias for compatibility with Rust
```

**Step 2: Set `last_result_status` and `last_result_error` in gRPC `_handle_result`**

In `server.py`'s `_handle_result` method, before processing the result:

```python
bridge.last_result_status = result.status
bridge.last_result_error = result.error if result.error else None
```

**Step 3: Commit**

```bash
git commit -am "feat(bridge): add last_result_status/error, task_available (Rust parity)"
```

---

## Category D: gRPC & Event Handling Gaps

### Task 10: Fix grace period probe schedule to match Rust

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/grpc/server.py`

Python currently probes at cumulative 5s, 15s, 30s then 90s (total 120s). Rust probes at absolute 3s, 5s, 10s, 15s then 120s total.

**Step 1: Fix the probe schedule**

Replace the existing `_grace_period_cleanup` probe loop:

```python
async def _grace_period_cleanup(self, sandbox_id: str, sandbox_db_id, original_bridge):
    """Probed grace period before cleanup — matches Rust schedule."""
    # Probe checkpoints at absolute 3s, 5s, 10s, 15s, then 120s total
    sleeps = [3, 2, 5, 5]  # cumulative: 3, 5, 10, 15
    for sleep_sec in sleeps:
        await asyncio.sleep(sleep_sec)
        current_bridge = await self._bridge_registry.get(sandbox_id)
        if current_bridge is not None and current_bridge is not original_bridge:
            logger.info("Sandbox %s reconnected during grace period", sandbox_id)
            return
    
    # Final sleep: 120 - 15 = 105s
    await asyncio.sleep(105)
    current_bridge = await self._bridge_registry.get(sandbox_id)
    if current_bridge is not None and current_bridge is not original_bridge:
        logger.info("Sandbox %s reconnected during final grace window", sandbox_id)
        return
    
    # No reconnection — proceed with cleanup
    await self._execute_sandbox_cleanup(sandbox_id, sandbox_db_id)
```

**Step 2: Commit**

```bash
git commit -am "fix(grpc): align grace period probe schedule with Rust (3s/5s/10s/15s/120s)"
```

---

### Task 11: Fix reconnect path to emit `session.status_idle` 

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/grpc/server.py`

Python `_handle_reconnect_active_task` does NOT emit `session.status_idle` when `task_done=True, got_idle=False`, but the main `_run_single_task` does.

**Step 1: Add the missing status emission**

Find the block in `_handle_reconnect_active_task` where `task_done and not got_idle` is handled (around lines 837-845), and add the same `session.status_idle` emission that `_run_single_task` has:

```python
if task_done and not got_idle:
    # Emit session.status_idle — matches main task loop and Rust behavior
    stop_reason = self._stop_reason_from_result(result_status, result_error)
    await self._emit_session_status(
        session_id=session_id,
        status="idle",
        stop_reason=stop_reason,
        task_id=task_id,
        sandbox_id=sandbox_db_id,
    )
```

**Step 2: Commit**

```bash
git commit -am "fix(grpc): emit session.status_idle on reconnect task completion (Rust parity)"
```

---

### Task 12: Fix cleanup Step 7 to query DB for pending tasks instead of in-memory list

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/grpc/server.py`

Python uses `len(failover_pending_tasks)` (in-memory list) to decide `sandbox_failed` vs `sandbox_disconnected`. Rust queries the DB for `status = 'pending'` tasks. They can diverge.

**Step 1: Replace in-memory check with DB query**

In `_execute_sandbox_cleanup` Step 7, replace:
```python
if len(failover_pending_tasks) > 0:
```
with:
```python
async with self._db_session() as session:
    pending_tasks = await self._task_svc.count_pending_tasks_for_session(
        chat_session_id, session
    )
if pending_tasks > 0:
```

**Step 2: Add `count_pending_tasks_for_session` to TaskService if not present**

```python
async def count_pending_tasks_for_session(
    self, session_id: uuid.UUID, db_session
) -> int:
    result = await db_session.execute(
        text("""
            SELECT COUNT(*) FROM joysafeter_tasks
            WHERE chat_session_id = :sid AND status = 'pending'
        """),
        {"sid": session_id},
    )
    return result.scalar() or 0
```

**Step 3: Commit**

```bash
git commit -am "fix(grpc): query DB for pending tasks in cleanup Step 7 (Rust parity)"
```

---

### Task 13: Auto-assign `event_id` as UUIDv7 in `EventEnvelope`

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/events/envelope.py`

Rust auto-assigns `Uuid::now_v7()` in `EventEnvelope::new()`. Python defaults to `None`.

**Step 1: Auto-generate event_id**

```python
import uuid
# uuid7 available via uuid_extensions or custom:
try:
    from uuid_extensions import uuid7
except ImportError:
    uuid7 = uuid.uuid4  # fallback

@dataclass
class JoySafeterEventEnvelope:
    session_id: uuid.UUID
    event_type: str
    payload: dict
    task_id: uuid.UUID | None = None
    sandbox_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = field(default_factory=lambda: uuid7())
    seq: int | None = None  # Change from int=0 to Optional[int]=None for Rust parity
    flush_immediately: bool = False
    is_status_change: bool = False
    stop_reason: dict | None = None
    task_broadcast_payload: dict | None = None
```

**Step 2: Commit**

```bash
git commit -am "feat(events): auto-assign UUIDv7 event_id, make seq Optional (Rust parity)"
```

---

### Task 14: Add `flush()` method to `EventBus`

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/events/bus.py`

Python event bus has no `flush()` method; the gRPC server calls `_event_buffer.flush()` directly.

**Step 1: Add flush to EventBus**

```python
class JoySafeterEventBus:
    # ... existing code ...
    
    async def flush(self) -> None:
        """Force flush all buffered events to DB."""
        await self._persister.flush()
```

**Step 2: Update gRPC server to use `event_bus.flush()` instead of `_event_buffer.flush()`**

Search for all `self._event_buffer.flush()` calls in `server.py` and replace with `self._event_bus.flush()`.

**Step 3: Commit**

```bash
git commit -am "feat(events): add flush() to EventBus, decouple from raw buffer (Rust parity)"
```

---

### Task 15: Remove dead code in `event_mapping.py`

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/events/event_mapping.py`

**Step 1: Remove dead `result` branch (line ~53)**

The `"result"` event_type branch can never be reached because `RunnerHarnessResult` is a top-level `RunnerMessage` payload.

**Step 2: Remove dead `memory_sync` branch (lines ~101-107)**

The `"memory_sync"` branch in `map_harness_event` can never be reached because `memory_sync` is handled as a top-level `RunnerMessage` payload in `server.py`.

**Step 3: Commit**

```bash
git commit -am "chore(events): remove dead result/memory_sync branches in event_mapping (Rust parity)"
```

---

## Category E: Queue / Coordinator / Command Listener

### Task 16: Add `cancel` command handler to CommandListener

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/command_listener.py`

Python only handles `"input"` and `"shutdown"` commands. Rust also handles `"cancel"`.

**Step 1: Add cancel handler**

```python
async def _dispatch(self, command: dict) -> None:
    cmd_type = command.get("type")
    if cmd_type == "input":
        await self._handle_input(command)
    elif cmd_type == "shutdown":
        await self._handle_shutdown(command)
    elif cmd_type == "cancel":
        await self._handle_cancel(command)
    else:
        logger.warning("Unknown command type: %s", cmd_type)


async def _handle_cancel(self, command: dict) -> None:
    sandbox_id = command.get("sandbox_id")
    reason = command.get("reason", "cancelled by remote instance")
    bridge = await self._bridge_registry.get(sandbox_id)
    if not bridge:
        logger.debug("Cancel command for unknown sandbox %s", sandbox_id)
        return
    
    # Send CancelTask proto to runner
    cancel_msg = OrchestratorMessage(cancel=CancelTask(reason=reason))
    await bridge.runner_tx.put(cancel_msg)
    
    # Signal cancellation
    bridge._cancel_event.set()
    logger.info("Forwarded cancel to sandbox %s: %s", sandbox_id, reason)
```

**Step 2: Commit**

```bash
git commit -am "feat(cmd-listener): add cancel command handler (Rust parity)"
```

---

### Task 17: Add `dispatch_cancel` and `dispatch_input` to RedisCoordinator

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/redis_coordinator.py`

**Step 1: Add the two dispatch methods**

```python
async def dispatch_cancel(self, sandbox_id: str, reason: str = "") -> None:
    """Publish a cancel command to all instances."""
    command = json.dumps({
        "type": "cancel",
        "sandbox_id": sandbox_id,
        "reason": reason,
    })
    # Publish to all instance command channels
    instances = await self.list_active_instances()
    for instance_id in instances:
        if instance_id == self._instance_id:
            continue
        channel = f"joysafeter:cmd:{instance_id}"
        await self._redis.publish(channel, command)


async def dispatch_input(self, sandbox_id: str, content: str) -> None:
    """Publish an input command to all instances."""
    command = json.dumps({
        "type": "input",
        "sandbox_id": sandbox_id,
        "content": content,
    })
    instances = await self.list_active_instances()
    for instance_id in instances:
        if instance_id == self._instance_id:
            continue
        channel = f"joysafeter:cmd:{instance_id}"
        await self._redis.publish(channel, command)
```

**Step 2: Commit**

```bash
git commit -am "feat(redis): add dispatch_cancel/dispatch_input methods (Rust parity)"
```

---

### Task 18: Fix RedisCoordinator lock key namespacing

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/redis_coordinator.py`

Python `try_acquire_lock(key)` uses the raw key directly. Rust `try_lock(lock_name)` prepends `joysafeter:lock:{lock_name}`.

**Step 1: Add namespace prefix**

```python
async def try_acquire_lock(self, lock_name: str, ttl_sec: int = 30) -> bool:
    key = f"joysafeter:lock:{lock_name}"
    result = await self._redis.set(key, self._instance_id, nx=True, ex=ttl_sec)
    return result is not None

async def release_lock(self, lock_name: str) -> bool:
    key = f"joysafeter:lock:{lock_name}"
    # Lua CAS: only delete if we own it
    script = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        return redis.call('DEL', KEYS[1])
    end
    return 0
    """
    result = await self._redis.eval(script, 1, key, self._instance_id)
    return bool(result)
```

**Step 2: Update all callers to pass `lock_name` (without prefix)**

Search for `try_acquire_lock` / `release_lock` callers and strip any `joysafeter:lock:` prefix they may already include.

**Step 3: Commit**

```bash
git commit -am "fix(redis): namespace lock keys with joysafeter:lock: prefix (Rust parity)"
```

---

### Task 19: Add `has_pending()` method to queue backend

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/queue.py`

**Step 1: Add has_pending**

```python
async def has_pending(self, sandbox_id: uuid.UUID) -> bool:
    """Check if a sandbox has pending wakeup work."""
    if self._redis:
        key = f"joysafeter:sandbox_wakeup:{sandbox_id}"
        result = await self._redis.get(key)
        return result is not None
    return False
```

**Step 2: Commit**

```bash
git commit -am "feat(queue): add has_pending() method (Rust parity)"
```

---

### Task 20: Add exponential backoff to CommandListener reconnect

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/command_listener.py`

Python uses fixed `sleep(5)` on failure, `sleep(1)` on stream end. Rust uses exponential backoff 1s→30s.

**Step 1: Implement exponential backoff**

```python
async def run(self) -> None:
    backoff = 1.0
    max_backoff = 30.0
    while not self._shutdown:
        try:
            await self._subscribe_and_listen()
            backoff = 1.0  # reset on clean exit
        except Exception as exc:
            logger.error("Command listener error: %s, retrying in %.0fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
```

**Step 2: Commit**

```bash
git commit -am "feat(cmd-listener): exponential backoff on reconnect (Rust parity)"
```

---

### Task 21: Add `publish_session_event` source wrapping to RedisCoordinator

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/redis_coordinator.py`

Rust wraps session events: `{"source_instance": ..., "event": ...}`. Python publishes raw payload.

**Step 1: Wrap session events**

```python
async def publish_session_event(self, session_id: uuid.UUID, payload: str) -> None:
    channel = f"joysafeter:session_events:{session_id}"
    wrapped = json.dumps({
        "source_instance": self._instance_id,
        "event": json.loads(payload),
    })
    await self._redis.publish(channel, wrapped)
```

**Step 2: Commit**

```bash
git commit -am "fix(redis): wrap session events with source_instance (Rust parity)"
```

---

## Category F: Memory Sync & File Injection

### Task 22: Align MemoryStoreSubscribers API with Rust

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/memory_sync.py`

**Step 1: Add `mount_path` to `MemorySessionEntry`**

```python
@dataclass
class MemorySessionEntry:
    session_id: uuid.UUID
    sandbox_db_id: uuid.UUID
    mount_name: str
    mount_path: str = ""  # NEW — filesystem mount path
```

**Step 2: Update `register()` to accept mount_path and deduplicate**

```python
def register(self, store_id: uuid.UUID, entry: MemorySessionEntry) -> None:
    entries = self._store_sessions.setdefault(store_id, [])
    # Deduplicate by (session_id, sandbox_db_id)
    for existing in entries:
        if existing.session_id == entry.session_id and existing.sandbox_db_id == entry.sandbox_db_id:
            return
    entries.append(entry)
```

**Step 3: Update `unregister_session` to also take sandbox_db_id**

```python
def unregister(self, session_id: uuid.UUID, sandbox_db_id: uuid.UUID) -> None:
    """Remove by both session AND sandbox — matches Rust."""
    for store_id, entries in self._store_sessions.items():
        self._store_sessions[store_id] = [
            e for e in entries
            if not (e.session_id == session_id and e.sandbox_db_id == sandbox_db_id)
        ]
```

Keep `unregister_session` as a convenience that removes all entries for a session.

**Step 4: Update `notify_peers` to exclude by sandbox_id and accept content directly**

```python
async def notify_peers(
    self,
    store_mount_name: str,
    relative_path: str,
    content: bytes,
    operation: str,
    sender_sandbox_id: uuid.UUID,
) -> None:
    """Notify peer sandboxes of a memory file change. Excludes sender."""
    for store_id, entries in self._store_sessions.items():
        for entry in entries:
            if entry.sandbox_db_id == sender_sandbox_id:
                continue
            if entry.mount_name != store_mount_name:
                continue
            bridge = await self._bridge_registry.get_by_db_id(entry.sandbox_db_id)
            if not bridge:
                continue
            msg = OrchestratorMessage(
                memory_update=MemoryFileUpdate(
                    store_mount_name=store_mount_name,
                    relative_path=relative_path,
                    content=content,
                    operation=operation,
                )
            )
            await bridge.runner_tx.put(msg)
```

**Step 5: Commit**

```bash
git commit -am "feat(memory-sync): align API with Rust (mount_path, dedup, exclude by sandbox) "
```

---

### Task 23: Add `InjectionStrategy` enum and typed file injection

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/sandbox/file_injection.py`

**Step 1: Add InjectionStrategy enum and FileToInject dataclass**

```python
from enum import Enum

class InjectionStrategy(str, Enum):
    PRESIGNED_URL = "presigned_url"
    GRPC_STREAM = "grpc_stream"
    HOST_MOUNT = "host_mount"
    PROVIDER_FALLBACK = "provider_fallback"


@dataclass
class FileToInject:
    filename: str
    mount_path: str
    content: bytes | None = None
    storage_key: str | None = None
    size_bytes: int = 0
    url: str | None = None
```

**Step 2: Refactor strategy selection to return `InjectionStrategy` enum values**

Replace the existing protocol-class-based dispatch with enum-based selection:

```python
def select_strategies(context: FileInjectionContext) -> list[InjectionStrategy]:
    strategies: list[InjectionStrategy] = []
    if context.workspace_path and not context.is_pool_sandbox:
        strategies.append(InjectionStrategy.HOST_MOUNT)
    if "grpc_file_transfer" in context.runner_capabilities:
        strategies.append(InjectionStrategy.GRPC_STREAM)
    strategies.append(InjectionStrategy.PRESIGNED_URL)
    strategies.append(InjectionStrategy.PROVIDER_FALLBACK)
    return strategies
```

**Step 3: Commit**

```bash
git commit -am "feat(file-injection): add InjectionStrategy enum, FileToInject (Rust parity)"
```

---

## Category G: Scheduler & Miscellaneous

### Task 24: Add `image_for_provider` routing to sandbox resolver

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/sandbox_resolver.py`

**Step 1: Use per-engine image selection**

When creating a new sandbox, use `config.image_for_provider(agent.engine_kind)` instead of the single default image:

```python
# In _create_new_sandbox or equivalent:
image = self._config.image_for_provider(agent.get("engine_kind", "claude"))
```

**Step 2: Commit**

```bash
git commit -am "feat(resolver): use per-engine image selection (Rust parity)"
```

---

### Task 25: Align RedisCoordinator heartbeat interval with config

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/redis_coordinator.py`

Python hardcodes `sleep(10)` and `expire(30)`. Rust uses `config.heartbeat_interval` (default 15) and `config.heartbeat_ttl` (default 30).

**Step 1: Use config values**

```python
async def _heartbeat_loop(self) -> None:
    interval = self._config.heartbeat_interval  # default 15
    ttl = interval * 2  # default 30
    while not self._shutdown:
        try:
            key = f"joysafeter:instances:{self._instance_id}"
            await self._redis.setex(key, ttl, self._instance_id)
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc)
        await asyncio.sleep(interval)
```

**Step 2: Commit**

```bash
git commit -am "fix(redis): use config heartbeat_interval instead of hardcoded 10s (Rust parity)"
```

---

### Task 26: Add `deregister_instance` method to RedisCoordinator

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/redis_coordinator.py`

**Step 1: Add named method**

```python
async def deregister_instance(self) -> None:
    """Explicitly remove this instance from the registry."""
    key = f"joysafeter:instances:{self._instance_id}"
    await self._redis.delete(key)
    logger.info("Deregistered instance %s", self._instance_id)
```

**Step 2: Wire into `stop()` method**

Replace inline key deletion with:
```python
async def stop(self) -> None:
    self._shutdown = True
    await self.deregister_instance()
```

**Step 3: Commit**

```bash
git commit -am "feat(redis): add deregister_instance method (Rust parity)"
```

---

### Task 27: Add `list_active_sandbox_owners` returning (sandbox_id, owner) tuples

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/redis_coordinator.py`

Python returns `list[UUID]` (sandbox IDs only). Rust returns `Vec<(Uuid, String)>` (sandbox_id + owner instance_id).

**Step 1: Update return type**

```python
async def list_active_sandbox_owners(self) -> list[tuple[uuid.UUID, str]]:
    """Return (sandbox_id, owner_instance_id) pairs for all owned sandboxes."""
    pattern = "joysafeter:sandbox_owner:*"
    result: list[tuple[uuid.UUID, str]] = []
    async for key in self._redis.scan_iter(match=pattern):
        owner = await self._redis.get(key)
        if owner:
            sandbox_id_str = key.decode().split(":")[-1]
            try:
                result.append((uuid.UUID(sandbox_id_str), owner.decode()))
            except ValueError:
                continue
    return result
```

**Step 2: Update callers to handle the new tuple format**

**Step 3: Commit**

```bash
git commit -am "feat(redis): return (sandbox_id, owner) tuples from list_active_sandbox_owners (Rust parity)"
```

---

### Task 28: Add `release_lock` returning `bool` (Lua CAS)

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/kernel/redis_coordinator.py`

This was partially covered in Task 18. Ensure `release_lock` returns `bool` (whether we owned the lock), matching Rust's `unlock()` semantics.

(Already covered in Task 18, skip if already done.)

---

### Task 29: Log `available_providers` from `RunnerReady` in gRPC server

**Files:**
- Modify: `backend/app/joysafeter_orchestrator/grpc/server.py`

**Step 1: Log the providers**

In the `RunnerReady` handler, add:
```python
if ready.available_providers:
    logger.info(
        "Runner %s connected with providers: %s",
        sandbox_id,
        ready.available_providers,
    )
```

**Step 2: Commit**

```bash
git commit -am "feat(grpc): log available_providers from RunnerReady (Rust parity)"
```

---

## Execution Order

Tasks are ordered by dependency:

1. **Task 1** — Error types (no deps)
2. **Task 2** — Config fields (no deps)
3. **Task 3** — HarnessInput fields (deps: Task 2 for config references)
4. **Task 4** — VaultCipher (no deps)
5. **Task 5** — OAuth refresh (deps: Task 4)
6. **Task 6** — setup_commands/tool lists/max_turns (deps: Task 3)
7. **Task 8** — SandboxStatus/CreateConfig (no deps)
8. **Task 7** — Reverse orphan sweep (deps: Task 8 for SandboxStatus)
9. **Task 9** — SandboxBridge fields (no deps)
10. **Task 13** — EventEnvelope auto-id (no deps)
11. **Task 14** — EventBus flush (no deps)
12. **Task 15** — Dead code cleanup (no deps)
13. **Task 10** — Grace period fix (deps: Task 9)
14. **Task 11** — Reconnect status_idle fix (no deps)
15. **Task 12** — Cleanup Step 7 DB query (no deps)
16. **Task 16** — Cancel command handler (no deps)
17. **Task 17** — dispatch_cancel/dispatch_input (no deps)
18. **Task 18** — Lock key namespacing (no deps)
19. **Task 19** — has_pending (no deps)
20. **Task 20** — CommandListener backoff (no deps)
21. **Task 21** — Session event wrapping (no deps)
22. **Task 22** — Memory sync alignment (no deps)
23. **Task 23** — File injection enum (no deps)
24. **Task 24** — Image routing (deps: Task 2)
25. **Task 25** — Heartbeat config (deps: Task 2)
26. **Task 26** — deregister_instance (no deps)
27. **Task 27** — Sandbox owners tuples (no deps)
28. **Task 29** — Log providers (no deps)

---

## Summary of All Differences Being Addressed

| # | Category | Difference | Task |
|---|----------|-----------|------|
| 1 | Error | No unified error type in Python | Task 1 |
| 2 | Config | 40+ missing env vars (scheduling, resources, Envoy, vault, etc.) | Task 2 |
| 3 | Config | No `image_for_provider()` method | Task 2, 24 |
| 4 | HarnessInput | Missing `provider`, `setup_commands`, `allowed_tools`, `disallowed_tools`, `max_turns`, `repos` | Task 3 |
| 5 | VaultCipher | No AES-GCM `enc:` prefix decryption | Task 4 |
| 6 | Builder | No OAuth token refresh | Task 5 |
| 7 | Builder | No environment-driven setup commands | Task 6 |
| 8 | Builder | No `agent_toolset_20260401` parsing | Task 6 |
| 9 | Builder | No `max_turns` extraction | Task 6 |
| 10 | Sandbox | No reverse DB→provider orphan sweep | Task 7 |
| 11 | Provider | No `SandboxStatus` enum, `SandboxCreateConfig`, `ProviderSandboxInfo` | Task 8 |
| 12 | Bridge | Missing `last_result_status/error`, `task_available` | Task 9 |
| 13 | gRPC | Grace period probes at wrong intervals | Task 10 |
| 14 | gRPC | Reconnect path missing `session.status_idle` | Task 11 |
| 15 | gRPC | Cleanup Step 7 uses in-memory list instead of DB | Task 12 |
| 16 | Events | `EventEnvelope.event_id` not auto-assigned | Task 13 |
| 17 | Events | `EventEnvelope.seq` is `int=0` instead of `Optional[int]=None` | Task 13 |
| 18 | Events | No `flush()` on EventBus | Task 14 |
| 19 | Events | Dead `result`/`memory_sync` branches in event_mapping | Task 15 |
| 20 | Commands | No `cancel` command in CommandListener | Task 16 |
| 21 | Redis | No `dispatch_cancel`/`dispatch_input` on RedisCoordinator | Task 17 |
| 22 | Redis | Lock keys not namespaced with `joysafeter:lock:` | Task 18 |
| 23 | Queue | No `has_pending()` method | Task 19 |
| 24 | Commands | Fixed sleep instead of exponential backoff | Task 20 |
| 25 | Redis | Session events not wrapped with `source_instance` | Task 21 |
| 26 | Memory | No `mount_path`, no dedup, unregister by session only | Task 22 |
| 27 | Memory | `notify_peers` excludes by session instead of sandbox | Task 22 |
| 28 | FileInj | No `InjectionStrategy` enum, no `FileToInject` dataclass | Task 23 |
| 29 | Resolver | No per-engine image routing | Task 24 |
| 30 | Redis | Heartbeat interval hardcoded instead of config-driven | Task 25 |
| 31 | Redis | No `deregister_instance` named method | Task 26 |
| 32 | Redis | `list_active_sandbox_owners` returns IDs only, not (id, owner) | Task 27 |
| 33 | gRPC | `available_providers` from RunnerReady silently ignored | Task 29 |
