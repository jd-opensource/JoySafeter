# Agent Kind Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `DefinitionKindLiteral`/`RuntimeKindLiteral`/`executor_kind` with two clean orthogonal axes: `EngineKind` (what kernel) and `RuntimeKind` (where it runs). Each CLI tool becomes its own first-class engine.

**Architecture:** Contracts layer defines `EngineKind` (5 user-facing values + 1 internal) and `RuntimeKind` (sandbox/server). The engine registry maps `engine_kind` → `ExecutionEngine` 1:1. The `CLIEngine` + `RuntimeProviderRegistry` intermediate dispatch layer is eliminated — each CLI provider is promoted to a full `ExecutionEngine` implementation.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Pydantic v2, Alembic, TypeScript, Vitest

---

## File Structure

### Backend — New/Renamed files

| Action | Path | Responsibility |
|---|---|---|
| Rewrite | `backend/app/core/contracts/agent.py` | New `EngineKind`, `RuntimeKind`, `ENGINE_RUNTIME_MAP` |
| Rewrite | `backend/app/core/contracts/__init__.py` | Updated re-exports |
| Rename | `backend/app/core/engine/graph_engine.py` → keep file, rename class to `LangGraphVisualEngine` | Visual graph engine |
| Rename | `backend/app/core/engine/code_engine.py` → keep file, rename class to `LangGraphCodeEngine` | Code graph engine |
| Create | `backend/app/core/engine/claude_code_engine.py` | Claude Code engine (promoted from provider) |
| Create | `backend/app/core/engine/codex_engine.py` | Codex engine (promoted from provider) |
| Create | `backend/app/core/engine/openclaw_engine.py` | OpenClaw engine (promoted from provider) |
| Delete | `backend/app/core/engine/cli_engine.py` | Replaced by 3 individual engines |
| Rewrite | `backend/app/core/engine/__init__.py` | 6 engine registrations |
| Modify | `backend/app/core/engine/registry.py` | `runtime_kind` → `engine_kind` in naming |
| Modify | `backend/app/core/engine/protocol.py` | Update docstring |
| Modify | `backend/app/models/agent.py` | `definition_kind` → `engine_kind`, remove `normalize_*` |
| Modify | `backend/app/models/execution.py` | `executor_kind` → `engine_kind` |
| Modify | `backend/app/schemas/agent.py` | `DefinitionKindLiteral` → `EngineKind`, `RuntimeKindLiteral` → `RuntimeKind` |
| Modify | `backend/app/schemas/agent_version.py` | Same |
| Modify | `backend/app/schemas/agent_release.py` | `RuntimeKindLiteral` → `RuntimeKind` |
| Modify | `backend/app/services/agent_publish_service.py` | Use `ENGINE_RUNTIME_MAP`, remove `is_cli_definition_kind` |
| Modify | `backend/app/services/execution_orchestrator.py` | Route by `engine_kind` directly, simplify overrides |
| Create | `backend/alembic/versions/xxxx_refactor_agent_kinds.py` | Column rename + value migration |

### Frontend — Modified files

| Action | Path | Responsibility |
|---|---|---|
| Rewrite | `frontend/types/agent.ts` | New `ENGINE_KINDS`, `EngineKind`, `RUNTIME_KINDS`, `RuntimeKind` |
| Modify | `frontend/types/agent-run.ts` | `executor_kind` → `engine_kind` |
| Rewrite | `frontend/types/__tests__/architecture-contracts.test.ts` | Updated assertions |
| Modify | `frontend/components/agents/agent-card.tsx` | Use new `EngineKind` labels |
| Modify | `frontend/components/agents/agent-settings-tab.tsx` | Same |
| Modify | `frontend/components/agents/agent-form-dialog.tsx` | `DefinitionKind` → `EngineKind` |
| Modify | `frontend/components/agents/version-form-dialog.tsx` | Same |
| Modify | `frontend/components/agents/agent-build/builder-surface-registry.ts` | `DefinitionKind` → `EngineKind` |
| Modify | `frontend/lib/agents/agent-list-filters.ts` | `DefinitionKind` → `EngineKind` |
| Modify | `frontend/lib/agents/agent-list-filters.test.ts` | Updated test data |
| Modify | `frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts` | Updated assertions |

---

### Task 1: Rewrite contracts layer (`core/contracts/agent.py` + `__init__.py`)

**Files:**
- Modify: `backend/app/core/contracts/agent.py`
- Modify: `backend/app/core/contracts/__init__.py`

- [ ] **Step 1: Rewrite `agent.py` with new types**

Replace the entire file content:

```python
"""Canonical Agent engine/runtime kind contract values."""

from __future__ import annotations

from typing import Literal, Union

from app.common.app_errors import InvalidRequestError

EngineKind = Literal[
    "langgraph_visual",
    "langgraph_code",
    "claude_code",
    "codex",
    "openclaw",
]
ENGINE_KINDS: set[str] = {"langgraph_visual", "langgraph_code", "claude_code", "codex", "openclaw"}

InternalEngineKind = Literal["build_copilot"]
INTERNAL_ENGINE_KINDS: set[str] = {"build_copilot"}

AllEngineKind = Union[EngineKind, InternalEngineKind]
ALL_ENGINE_KINDS: set[str] = ENGINE_KINDS | INTERNAL_ENGINE_KINDS

RuntimeKind = Literal["sandbox", "server"]
RUNTIME_KINDS: set[str] = {"sandbox", "server"}

ENGINE_RUNTIME_MAP: dict[str, str] = {
    "langgraph_visual": "server",
    "langgraph_code": "server",
    "claude_code": "sandbox",
    "codex": "sandbox",
    "openclaw": "sandbox",
}

CLI_ENGINE_KINDS: set[str] = {"claude_code", "codex", "openclaw"}


def infer_runtime_kind(engine_kind: str) -> str:
    runtime_kind = ENGINE_RUNTIME_MAP.get(engine_kind)
    if not runtime_kind:
        raise InvalidRequestError(
            f"Unsupported engine_kind={engine_kind}",
            code="AGENT_ENGINE_KIND_UNSUPPORTED",
            data={"engine_kind": engine_kind},
        )
    return runtime_kind


def is_cli_engine_kind(engine_kind: str) -> bool:
    return engine_kind in CLI_ENGINE_KINDS


def normalize_engine_kind(engine_kind: str | None) -> str | None:
    return engine_kind if engine_kind in ENGINE_KINDS else None


def normalize_runtime_kind(runtime_kind: str | None) -> str | None:
    return runtime_kind if runtime_kind in RUNTIME_KINDS else None
```

- [ ] **Step 2: Update `__init__.py` re-exports**

Replace the agent imports block in `__init__.py`:

```python
from app.core.contracts.agent import (
    ALL_ENGINE_KINDS,
    CLI_ENGINE_KINDS,
    ENGINE_KINDS,
    ENGINE_RUNTIME_MAP,
    INTERNAL_ENGINE_KINDS,
    RUNTIME_KINDS,
    AllEngineKind,
    EngineKind,
    InternalEngineKind,
    RuntimeKind,
    infer_runtime_kind,
    is_cli_engine_kind,
    normalize_engine_kind,
    normalize_runtime_kind,
)
```

Update `__all__` to match — remove all old names (`DEFINITION_KINDS`, `CLI_DEFINITION_KINDS`, `DEFINITION_RUNTIME_KIND`, `DefinitionKindLiteral`, `RuntimeKindLiteral`, `is_cli_definition_kind`, `normalize_definition_kind`), add all new names.

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/contracts/agent.py backend/app/core/contracts/__init__.py
git commit -m "refactor: replace DefinitionKindLiteral/RuntimeKindLiteral with EngineKind/RuntimeKind in contracts"
```

---

### Task 2: Rename engine classes and update registry

**Files:**
- Modify: `backend/app/core/engine/graph_engine.py`
- Modify: `backend/app/core/engine/code_engine.py`
- Modify: `backend/app/core/engine/registry.py`
- Modify: `backend/app/core/engine/protocol.py`
- Modify: `backend/app/core/engine/__init__.py`

- [ ] **Step 1: Rename GraphEngine → LangGraphVisualEngine**

In `backend/app/core/engine/graph_engine.py`:
- Rename class `GraphEngine` → `LangGraphVisualEngine`
- Change `engine_kind = "graph"` → `engine_kind = "langgraph_visual"`
- Change the `definition_kind` validation: `if definition_kind != "graph":` → `if definition_kind != "langgraph_visual":`
- Update error code: `GRAPH_DEFINITION_KIND_UNSUPPORTED` → `LANGGRAPH_VISUAL_ENGINE_KIND_MISMATCH`
- Update all log prefixes `[GraphEngine]` → `[LangGraphVisualEngine]`

- [ ] **Step 2: Rename CodeEngine → LangGraphCodeEngine**

In `backend/app/core/engine/code_engine.py`:
- Rename class `CodeEngine` → `LangGraphCodeEngine`
- Change `engine_kind = "code"` → `engine_kind = "langgraph_code"`
- Change validation: `if definition_kind != "code":` → `if definition_kind != "langgraph_code":`
- Update error code: `CODE_DEFINITION_KIND_UNSUPPORTED` → `LANGGRAPH_CODE_ENGINE_KIND_MISMATCH`
- Update all log prefixes `[CodeEngine]` → `[LangGraphCodeEngine]`

- [ ] **Step 3: Update registry.py naming**

In `backend/app/core/engine/registry.py`:
- Rename parameter `runtime_kind` → `engine_kind` in all methods (`register`, `has`, `get`, `list_kinds`)
- Update docstring and error messages: `"runtime_kind"` → `"engine_kind"`, `"available_runtime_kinds"` → `"available_engine_kinds"`
- Update error code: `EXECUTION_ENGINE_NOT_REGISTERED` stays the same (still correct)

```python
class EngineRegistry:
    """Singleton registry: engine_kind → ExecutionEngine."""

    def __init__(self) -> None:
        self._engines: dict[str, ExecutionEngine] = {}

    def register(self, engine_kind: str, engine: ExecutionEngine) -> None:
        self._engines[engine_kind] = engine

    def has(self, engine_kind: str) -> bool:
        return engine_kind in self._engines

    def get(self, engine_kind: str) -> ExecutionEngine:
        engine = self._engines.get(engine_kind)
        if not engine:
            available = ", ".join(self._engines.keys()) or "(none)"
            raise NotFoundError(
                "Execution engine is not registered",
                code="EXECUTION_ENGINE_NOT_REGISTERED",
                data={"engine_kind": engine_kind, "available_engine_kinds": available},
            )
        return engine

    def list_kinds(self) -> list[str]:
        return list(self._engines.keys())
```

- [ ] **Step 4: Update protocol.py docstring**

In `backend/app/core/engine/protocol.py`:
- Update the `ExecutionEngine` docstring to list the new engine names:

```python
@runtime_checkable
class ExecutionEngine(Protocol):
    """
    Stable interface for all execution engines.

    User-facing engines:
      - LangGraphVisualEngine  (engine_kind: langgraph_visual)
      - LangGraphCodeEngine    (engine_kind: langgraph_code)
      - ClaudeCodeEngine       (engine_kind: claude_code)
      - CodexEngine            (engine_kind: codex)
      - OpenClawEngine         (engine_kind: openclaw)

    Internal platform engines:
      - CopilotEngine          (engine_kind: build_copilot)
    """
```

- Change `definition_kind` parameter name in `start()` to `engine_kind`:

```python
    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        engine_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
```

- Update the docstring for the parameter: `engine_kind: "langgraph_visual" | "langgraph_code" | "claude_code" | "codex" | "openclaw"`

- [ ] **Step 5: Update all engine start() signatures**

In each engine file (`graph_engine.py`, `code_engine.py`, `copilot_engine.py`), rename the `definition_kind` parameter to `engine_kind` in the `start()` method signature and update any internal references to it.

For `graph_engine.py`:
```python
    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        engine_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        execution_id = context.execution_id
        if engine_kind != "langgraph_visual":
            error = InvalidRequestError(
                f"LangGraphVisualEngine cannot handle engine_kind={engine_kind}",
                ...
```

For `code_engine.py`:
```python
        if engine_kind != "langgraph_code":
            error = InvalidRequestError(
                f"LangGraphCodeEngine cannot handle engine_kind={engine_kind}",
                ...
```

For `copilot_engine.py`: rename parameter `definition_kind` → `engine_kind` (no validation needed — copilot doesn't check it).

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/engine/
git commit -m "refactor: rename engine classes and update registry to use engine_kind"
```

---

### Task 3: Create individual CLI engine implementations

**Files:**
- Create: `backend/app/core/engine/claude_code_engine.py`
- Create: `backend/app/core/engine/codex_engine.py`
- Create: `backend/app/core/engine/openclaw_engine.py`
- Delete: `backend/app/core/engine/cli_engine.py`

Each CLI engine follows the same pattern — they delegate to `ExecutionRunner` (which uses `RuntimeProviderRegistry` internally to get the right provider). The key difference from the old `CLIEngine` is that each engine sets its own `engine_kind` and the `runtime_type` is hardcoded rather than read from `release_runtime_binding`.

- [ ] **Step 1: Create `claude_code_engine.py`**

```python
"""Claude Code Execution Engine.

engine_kind: "claude_code"
Docker + Claude Code CLI agent runtime.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from app.core.engine.protocol import EngineCapabilities, ExecutionContext
from app.core.events.event_types import ExecutionEventType


class ClaudeCodeEngine:
    """Claude Code CLI execution engine."""

    engine_kind = "claude_code"
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=True,
        supports_debug_observation=False,
        supports_artifacts=True,
        supports_approval=True,
    )

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        engine_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        from app.core.database import AsyncSessionLocal

        execution_id = context.execution_id
        logger.info(f"[ClaudeCodeEngine] Starting execution {execution_id}")

        await context.update_status("running")
        await context.emit(
            ExecutionEventType.EXECUTION_STARTED,
            {"engine": "claude_code"},
        )

        async with AsyncSessionLocal() as db:
            from app.services.runner_factory import create_execution_runner

            runner = create_execution_runner(db)
            await runner.run(
                execution_id=execution_id,
                prompt=prompt,
                credentials=context.credentials or None,
                collector=context.collector,
            )

    async def cancel(self, execution_id: uuid.UUID) -> None:
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.cancel()
            logger.info(f"[ClaudeCodeEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.inject_message(message)
```

- [ ] **Step 2: Create `codex_engine.py`**

Same as `claude_code_engine.py` but with:
- Class name: `CodexEngine`
- `engine_kind = "codex"`
- Log prefix: `[CodexEngine]`
- Emit payload: `{"engine": "codex"}`

```python
"""Codex Execution Engine.

engine_kind: "codex"
Docker + Codex CLI agent runtime.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from app.core.engine.protocol import EngineCapabilities, ExecutionContext
from app.core.events.event_types import ExecutionEventType


class CodexEngine:
    """Codex CLI execution engine."""

    engine_kind = "codex"
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=True,
        supports_debug_observation=False,
        supports_artifacts=True,
        supports_approval=True,
    )

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        engine_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        from app.core.database import AsyncSessionLocal

        execution_id = context.execution_id
        logger.info(f"[CodexEngine] Starting execution {execution_id}")

        await context.update_status("running")
        await context.emit(
            ExecutionEventType.EXECUTION_STARTED,
            {"engine": "codex"},
        )

        async with AsyncSessionLocal() as db:
            from app.services.runner_factory import create_execution_runner

            runner = create_execution_runner(db)
            await runner.run(
                execution_id=execution_id,
                prompt=prompt,
                credentials=context.credentials or None,
                collector=context.collector,
            )

    async def cancel(self, execution_id: uuid.UUID) -> None:
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.cancel()
            logger.info(f"[CodexEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.inject_message(message)
```

- [ ] **Step 3: Create `openclaw_engine.py`**

Same pattern:
- Class name: `OpenClawEngine`
- `engine_kind = "openclaw"`
- Log prefix: `[OpenClawEngine]`
- Emit payload: `{"engine": "openclaw"}`

```python
"""OpenClaw Execution Engine.

engine_kind: "openclaw"
Docker + OpenClaw CLI agent runtime.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from app.core.engine.protocol import EngineCapabilities, ExecutionContext
from app.core.events.event_types import ExecutionEventType


class OpenClawEngine:
    """OpenClaw CLI execution engine."""

    engine_kind = "openclaw"
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=True,
        supports_debug_observation=False,
        supports_artifacts=True,
        supports_approval=True,
    )

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        engine_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        from app.core.database import AsyncSessionLocal

        execution_id = context.execution_id
        logger.info(f"[OpenClawEngine] Starting execution {execution_id}")

        await context.update_status("running")
        await context.emit(
            ExecutionEventType.EXECUTION_STARTED,
            {"engine": "openclaw"},
        )

        async with AsyncSessionLocal() as db:
            from app.services.runner_factory import create_execution_runner

            runner = create_execution_runner(db)
            await runner.run(
                execution_id=execution_id,
                prompt=prompt,
                credentials=context.credentials or None,
                collector=context.collector,
            )

    async def cancel(self, execution_id: uuid.UUID) -> None:
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.cancel()
            logger.info(f"[OpenClawEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.inject_message(message)
```

- [ ] **Step 4: Delete `cli_engine.py`**

```bash
git rm backend/app/core/engine/cli_engine.py
```

- [ ] **Step 5: Update `__init__.py` with new registrations**

Replace the entire file:

```python
"""
Engine package — unified execution engine abstraction.

Registers all built-in engines at import time.
"""

from app.core.engine.claude_code_engine import ClaudeCodeEngine
from app.core.engine.codex_engine import CodexEngine
from app.core.engine.code_engine import LangGraphCodeEngine
from app.core.engine.copilot_engine import CopilotEngine
from app.core.engine.graph_engine import LangGraphVisualEngine
from app.core.engine.openclaw_engine import OpenClawEngine
from app.core.engine.protocol import EngineCapabilities, ExecutionContext, ExecutionEngine
from app.core.engine.registry import engine_registry

engine_registry.register("langgraph_visual", LangGraphVisualEngine())
engine_registry.register("langgraph_code", LangGraphCodeEngine())
engine_registry.register("claude_code", ClaudeCodeEngine())
engine_registry.register("codex", CodexEngine())
engine_registry.register("openclaw", OpenClawEngine())
engine_registry.register("build_copilot", CopilotEngine())

__all__ = [
    "ExecutionContext",
    "ExecutionEngine",
    "EngineCapabilities",
    "engine_registry",
    "ClaudeCodeEngine",
    "CodexEngine",
    "CopilotEngine",
    "LangGraphCodeEngine",
    "LangGraphVisualEngine",
    "OpenClawEngine",
]
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/engine/
git commit -m "refactor: promote CLI providers to first-class engines, delete CLIEngine"
```

---

### Task 4: Update models (`agent.py`, `execution.py`)

**Files:**
- Modify: `backend/app/models/agent.py`
- Modify: `backend/app/models/execution.py`

- [ ] **Step 1: Update `agent.py`**

Change import:
```python
# Old
from app.core.contracts.agent import normalize_definition_kind, normalize_runtime_kind
# New
from app.core.contracts.agent import normalize_engine_kind, normalize_runtime_kind
```

Rename `Agent.definition_kind` property to `Agent.engine_kind`:
```python
    @property
    def engine_kind(self) -> Optional[str]:
        if not self.current_draft_version:
            return None
        return normalize_engine_kind(self.current_draft_version.engine_kind)
```

Rename `AgentVersion.definition_kind` column to `engine_kind`:
```python
    engine_kind: Mapped[str] = mapped_column(String(20), nullable=False)
```

Note: The SQLAlchemy `mapped_column` name defaults to the attribute name. The actual DB column rename happens in the migration (Task 7). For now the Python attribute name drives the column expectation. This means the app code and the migration must be deployed together.

- [ ] **Step 2: Update `execution.py`**

Rename `Execution.executor_kind` to `Execution.engine_kind`:
```python
    engine_kind: Mapped[str] = mapped_column(String(20), nullable=False)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/agent.py backend/app/models/execution.py
git commit -m "refactor: rename definition_kind→engine_kind and executor_kind→engine_kind in models"
```

---

### Task 5: Update schemas

**Files:**
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/app/schemas/agent_version.py`
- Modify: `backend/app/schemas/agent_release.py`

- [ ] **Step 1: Update `schemas/agent.py`**

Change import:
```python
# Old
from app.core.contracts.agent import DefinitionKindLiteral, RuntimeKindLiteral
# New
from app.core.contracts.agent import EngineKind, RuntimeKind
```

Update `CreateAgentRequest`:
```python
    engine_kind: EngineKind = "langgraph_visual"
```

Update `AgentSummary` and `AgentResponse`:
```python
    engine_kind: Optional[EngineKind] = None
    runtime_kind: Optional[RuntimeKind] = None
```

Remove `definition_kind` from both — the field is now `engine_kind`.

- [ ] **Step 2: Update `schemas/agent_version.py`**

Change import:
```python
# Old
from app.schemas.agent import DefinitionKindLiteral
# New
from app.core.contracts.agent import EngineKind
```

Update `CreateAgentVersionRequest`:
```python
    engine_kind: EngineKind = "langgraph_visual"
```

Update response schemas — rename `definition_kind: str` → `engine_kind: str`.

- [ ] **Step 3: Update `schemas/agent_release.py`**

Change import:
```python
# Old
from app.core.contracts.agent import RuntimeKindLiteral
# New
from app.core.contracts.agent import RuntimeKind
```

Update `CreateAgentReleaseRequest`:
```python
    runtime_kind: RuntimeKind
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/agent.py backend/app/schemas/agent_version.py backend/app/schemas/agent_release.py
git commit -m "refactor: update schemas to use EngineKind/RuntimeKind"
```

---

### Task 6: Update services

**Files:**
- Modify: `backend/app/services/agent_publish_service.py`
- Modify: `backend/app/services/execution_orchestrator.py`
- Modify: `backend/app/core/agent/cli_backends/execution_runner.py`

- [ ] **Step 1: Update `agent_publish_service.py`**

Change import:
```python
# Old
from app.core.contracts.agent import infer_runtime_kind, is_cli_definition_kind
# New
from app.core.contracts.agent import ENGINE_RUNTIME_MAP, infer_runtime_kind
```

Update `publish()`:
```python
        runtime_kind = infer_runtime_kind(version.engine_kind)
        release_data = CreateAgentReleaseRequest(
            agent_version_id=version.id,
            runtime_kind=runtime_kind,
            runtime_binding={},
        )
```

The `runtime_binding` no longer needs `runtime_type` — the engine registry routes directly by `engine_kind` now.

Remove `_infer_runtime_kind` static method (just use `infer_runtime_kind` directly).

- [ ] **Step 2: Update `execution_orchestrator.py`**

Change import:
```python
# Old
from app.core.contracts.agent import infer_runtime_kind, is_cli_definition_kind
# New
from app.core.contracts.agent import infer_runtime_kind
```

**Update `_resolve_engine`** — simplify to always use `engine_kind`:
```python
    def _resolve_engine(self, execution: Execution, release: AgentRelease):
        return engine_registry.get(execution.engine_kind)
```

**Update `_resolve_draft_engine_kind`** — now just returns `engine_kind` directly:
```python
    def _resolve_draft_engine_kind(self, version: AgentVersion) -> str:
        return version.engine_kind
```

**Update `_build_draft_runtime_binding`** — always empty now:
```python
    def _build_draft_runtime_binding(self, version: AgentVersion) -> dict:
        return {}
```

**Update `_create_and_fire`** — change `executor_kind` to `engine_kind`:
```python
        execution = Execution(
            run_id=run.id,
            attempt_index=1,
            engine_kind=executor_kind_override or version.engine_kind,
            status="pending",
        )
```

The current `_create_and_fire` reads `release` and then `version` from `release.agent_version_id` (line 549). The `executor_kind` assignment currently reads:

```python
executor_kind=executor_kind_override or release.runtime_binding.get("runtime_type", "claude_code"),
```

Since `runtime_binding` no longer has `runtime_type`, and we route by `engine_kind`, change to:

```python
            engine_kind=executor_kind_override or version.engine_kind,
```

**Update `_create_and_fire_draft`** — similar change:
```python
            engine_kind=executor_kind_override or version.engine_kind,
```

**Update `retry_run`** — change executor_kind assignment:
```python
        execution = Execution(
            run_id=run_id,
            attempt_index=max_attempt + 1,
            engine_kind=version.engine_kind,
            status="pending",
        )
```

**Update `_fire_engine`** — simplify engine resolution:
```python
        engine = engine_registry.get(engine_kind_override or execution.engine_kind)
```

Remove the `resolved_runtime_kind` logic. The engine is now always resolved from `engine_kind`.

Pass `engine_kind` instead of `definition_kind` to `engine.start()`:
```python
        await engine.start(
            ctx,
            release_runtime_binding=runtime_binding,
            engine_kind=_def_kind,
            definition_payload=_def_payload,
            prompt=prompt,
        )
```

**Update `send_message`** — change `execution.executor_kind` reference:
```python
                    "engine_kind": engine.engine_kind,
```

**Update `dispatch_copilot_draft`** — rename override params:
```python
        return await self._create_and_fire_draft(
            ...
            engine_kind_override="build_copilot",
            definition_kind_override="build_copilot",
            definition_payload_override=copilot_payload,
            executor_kind_override="build_copilot",
        )
```

These override parameter names stay the same for now (they're internal kwargs), but the `definition_kind_override` is now passed as `engine_kind` to `engine.start()`.

**Update `_validate_draft_overrides`** — no changes needed, just validates they're all-or-nothing.

- [ ] **Step 3: Update `execution_runner.py`**

Change line 87 and 96 to use `engine_kind`:
```python
        logger.info(
            f"[exec:{execution_id}] Starting execution "
            f"(release={release.id if release else 'draft'}, "
            f"engine={execution.engine_kind})"
        )
```

Line 166:
```python
                    "engine_kind": execution.engine_kind,
```

Line 172 — the runner still uses `runtime_registry.get(execution.engine_kind)` to get the right provider. This is the key integration point: `execution.engine_kind` is now `"claude_code"` / `"codex"` / `"openclaw"` which matches the `provider_type` of each `RuntimeProvider`. So this line works as-is after the rename:
```python
            provider = runtime_registry.get(execution.engine_kind)
```

Line 196:
```python
            await self._drain_to_events(execution_id, collector=collector, executor_kind=execution.engine_kind)
```

Also rename the `executor_kind` parameter in `_drain_to_events` to `engine_kind`:
```python
        executor_kind: str = "cli",  # → engine_kind: str = "cli",
```

And update the caller in line 280:
```python
            root_span = collector.start_agent(name=f"cli:{engine_kind}")
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent_publish_service.py backend/app/services/execution_orchestrator.py backend/app/core/agent/cli_backends/execution_runner.py
git commit -m "refactor: update services to route by engine_kind directly"
```

---

### Task 7: Create Alembic migration

**Files:**
- Create: `backend/alembic/versions/xxxx_refactor_agent_kinds.py`

- [ ] **Step 1: Generate migration revision ID**

```bash
cd backend && python -c "import uuid; print(uuid.uuid4().hex[:12])"
```

Use the output as the revision ID.

- [ ] **Step 2: Write migration file**

Create `backend/alembic/versions/<rev_id>_refactor_agent_kinds.py`:

```python
"""refactor_agent_kinds

Revision ID: <rev_id>
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-30

Renames definition_kind→engine_kind, executor_kind→engine_kind.
Remaps values: graph→langgraph_visual, code→langgraph_code,
sandbox_cli→(split by runtime_binding), graph/code runtime→server.
"""
from alembic import op
import sqlalchemy as sa

revision = '<rev_id>'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade():
    # 1. agent_versions: rename column + remap values
    op.alter_column('agent_versions', 'definition_kind', new_column_name='engine_kind')
    op.execute("UPDATE agent_versions SET engine_kind = 'langgraph_visual' WHERE engine_kind = 'graph'")
    op.execute("UPDATE agent_versions SET engine_kind = 'langgraph_code' WHERE engine_kind = 'code'")
    # sandbox_cli → split by runtime_binding from linked releases
    op.execute("""
        UPDATE agent_versions av
        SET engine_kind = COALESCE(
            (SELECT ar.runtime_binding->>'runtime_type'
             FROM agent_releases ar
             WHERE ar.agent_version_id = av.id
             LIMIT 1),
            'claude_code'
        )
        WHERE av.engine_kind = 'sandbox_cli'
    """)

    # 2. agent_releases: remap runtime_kind values
    op.execute("UPDATE agent_releases SET runtime_kind = 'server' WHERE runtime_kind IN ('graph', 'code')")

    # 3. executions: rename column (values already correct: claude_code, codex, openclaw, build_copilot)
    op.alter_column('executions', 'executor_kind', new_column_name='engine_kind')


def downgrade():
    # 3. executions: restore column name
    op.alter_column('executions', 'engine_kind', new_column_name='executor_kind')

    # 2. agent_releases: restore runtime_kind values (best-effort)
    # Cannot distinguish graph vs code from runtime_kind alone, default to graph
    op.execute("UPDATE agent_releases SET runtime_kind = 'graph' WHERE runtime_kind = 'server'")

    # 1. agent_versions: restore column name + remap values
    op.execute("UPDATE agent_versions SET engine_kind = 'graph' WHERE engine_kind = 'langgraph_visual'")
    op.execute("UPDATE agent_versions SET engine_kind = 'code' WHERE engine_kind = 'langgraph_code'")
    op.execute("""
        UPDATE agent_versions SET engine_kind = 'sandbox_cli'
        WHERE engine_kind IN ('claude_code', 'codex', 'openclaw')
    """)
    op.alter_column('agent_versions', 'engine_kind', new_column_name='definition_kind')
```

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat: add migration to rename agent kind columns and remap values"
```

---

### Task 8: Update frontend types

**Files:**
- Modify: `frontend/types/agent.ts`
- Modify: `frontend/types/agent-run.ts`
- Modify: `frontend/types/__tests__/architecture-contracts.test.ts`

- [ ] **Step 1: Rewrite `frontend/types/agent.ts`**

```typescript
export const ENGINE_KINDS = [
  'langgraph_visual',
  'langgraph_code',
  'claude_code',
  'codex',
  'openclaw',
] as const

export type EngineKind = (typeof ENGINE_KINDS)[number]

export const RUNTIME_KINDS = ['sandbox', 'server'] as const

export type RuntimeKind = (typeof RUNTIME_KINDS)[number]

export function hasBuilderSupport(kind?: string): boolean {
  return ENGINE_KINDS.includes(kind as EngineKind)
}

export interface Agent {
  id: string
  workspace_id: string
  name: string
  slug: string
  description: string | null
  avatar: string | null
  status: 'draft' | 'active' | 'archived'
  has_custom_env: boolean
  current_draft_version_id: string | null
  active_release_id: string | null
  engine_kind: EngineKind | null
  runtime_kind: RuntimeKind | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface CreateAgentRequest {
  name: string
  description?: string
  avatar?: string
  engine_kind: EngineKind
  definition_payload?: Record<string, unknown>
  capability_manifest?: Record<string, unknown>
}

export interface UpdateAgentRequest {
  name?: string
  description?: string
  avatar?: string
  status?: 'draft' | 'active' | 'archived'
}

export interface AgentVersion {
  id: string
  agent_id: string
  version_number: number
  status: 'draft' | 'frozen'
  source_kind: string
  engine_kind: EngineKind
  definition_payload: Record<string, unknown>
  capability_manifest: Record<string, unknown>
  changelog: string | null
  created_by: string
  created_at: string
}

export interface CreateAgentVersionRequest {
  source_kind?: string
  engine_kind: EngineKind
  definition_payload?: Record<string, unknown>
  capability_manifest?: Record<string, unknown>
  changelog?: string
}

export interface UpdateAgentVersionRequest {
  definition_payload?: Record<string, unknown>
  capability_manifest?: Record<string, unknown>
  changelog?: string
}
```

- [ ] **Step 2: Update `frontend/types/agent-run.ts`**

Change `Execution.executor_kind` → `Execution.engine_kind`:
```typescript
export interface Execution {
  id: string
  run_id: string
  parent_execution_id: string | null
  attempt_index: number
  engine_kind: string
  ...
}
```

- [ ] **Step 3: Rewrite contract test**

In `frontend/types/__tests__/architecture-contracts.test.ts`:

Update imports:
```typescript
import {
  ENGINE_KINDS,
  RUNTIME_KINDS,
} from '../agent'
```

Update assertions:
```typescript
  it('exports engine kinds', () => {
    expect([...ENGINE_KINDS].sort()).toEqual([
      'claude_code',
      'codex',
      'langgraph_code',
      'langgraph_visual',
      'openclaw',
    ])
  })

  it('exports runtime kinds', () => {
    expect([...RUNTIME_KINDS].sort()).toEqual(['sandbox', 'server'])
  })
```

Update the type derivation check:
```typescript
    expectTypeDerivedFromConstant(source, 'EngineKind', 'ENGINE_KINDS')
    expectTypeDerivedFromConstant(source, 'RuntimeKind', 'RUNTIME_KINDS')
```

- [ ] **Step 4: Commit**

```bash
git add frontend/types/
git commit -m "refactor: update frontend types to EngineKind/RuntimeKind"
```

---

### Task 9: Update frontend components

**Files:**
- Modify: `frontend/components/agents/agent-card.tsx`
- Modify: `frontend/components/agents/agent-settings-tab.tsx`
- Modify: `frontend/components/agents/agent-form-dialog.tsx`
- Modify: `frontend/components/agents/version-form-dialog.tsx`
- Modify: `frontend/components/agents/agent-build/builder-surface-registry.ts`
- Modify: `frontend/lib/agents/agent-list-filters.ts`
- Modify: `frontend/lib/agents/agent-list-filters.test.ts`
- Modify: `frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts`
- Modify: `frontend/components/agents/agent-overview-tab.tsx`
- Modify: `frontend/components/editors/graph-builder/services/visualDefinitionAdapter.ts`

- [ ] **Step 1: Update `agent-card.tsx`**

Change `DEFINITION_LABEL_KEYS`:
```typescript
const DEFINITION_LABEL_KEYS: Record<string, { labelKey: string; defaultLabel: string }> = {
  langgraph_visual: { labelKey: 'agents.graph.shortLabel', defaultLabel: 'Graph' },
  langgraph_code: { labelKey: 'agents.code.shortLabel', defaultLabel: 'Code' },
  claude_code: { labelKey: 'agents.claudeCode.shortLabel', defaultLabel: 'Claude Code' },
  codex: { labelKey: 'agents.codex.shortLabel', defaultLabel: 'Codex' },
  openclaw: { labelKey: 'agents.openclaw.shortLabel', defaultLabel: 'OpenClaw' },
}
```

Change `agent.definition_kind` → `agent.engine_kind`:
```typescript
  const definitionLabel = agent.engine_kind ? DEFINITION_LABEL_KEYS[agent.engine_kind] : null
```

- [ ] **Step 2: Update `agent-settings-tab.tsx`**

Change `DEFINITION_KIND_LABELS`:
```typescript
  const DEFINITION_KIND_LABELS: Record<string, string> = {
    langgraph_visual: t('agents.graph.label'),
    langgraph_code: t('agents.code.label'),
    claude_code: t('agents.claudeCode.label'),
    codex: t('agents.codex.label'),
    openclaw: t('agents.openclaw.label'),
  }
```

Change `draftVersion.definition_kind` → `draftVersion.engine_kind`.

- [ ] **Step 3: Update `agent-form-dialog.tsx`**

Change import: `DefinitionKind` → `EngineKind`.

Update `BuildMethodOption`:
```typescript
interface BuildMethodOption {
  value: EngineKind
  ...
}
```

Update `BUILD_METHOD_OPTIONS`:
```typescript
const BUILD_METHOD_OPTIONS: BuildMethodOption[] = [
  { value: 'langgraph_visual', labelKey: 'agents.graph.label', descriptionKey: 'agents.graph.description', icon: GitBranch },
  { value: 'langgraph_code', labelKey: 'agents.code.label', descriptionKey: 'agents.code.description', icon: Code2 },
  { value: 'claude_code', labelKey: 'agents.claudeCode.label', descriptionKey: 'agents.claudeCode.description', icon: Terminal },
  { value: 'codex', labelKey: 'agents.codex.label', descriptionKey: 'agents.codex.description', icon: Bot },
  { value: 'openclaw', labelKey: 'agents.openclaw.label', descriptionKey: 'agents.openclaw.description', icon: Cog },
]
```

Change state: `useState<DefinitionKind>('graph')` → `useState<EngineKind>('langgraph_visual')`.

Change submit: `definition_kind: definitionKind` → `engine_kind: engineKind`.

Reset: `setDefinitionKind('graph')` → `setEngineKind('langgraph_visual')`.

- [ ] **Step 4: Update `version-form-dialog.tsx`**

Change import: `DefinitionKind` → `EngineKind`.

Change state and submit to use `engine_kind` and `EngineKind`.

Default: `'graph'` → `'langgraph_visual'`.

- [ ] **Step 5: Update `builder-surface-registry.ts`**

```typescript
import { ENGINE_KINDS } from '@/types/agent'
import type { EngineKind } from '@/types/agent'

const DEFINITION_TO_SURFACE: Record<EngineKind, BuilderSurfaceKind> = {
  langgraph_visual: 'visual',
  langgraph_code: 'code',
  claude_code: 'cli',
  codex: 'cli',
  openclaw: 'cli',
}

function isEngineKind(engineKind: string | null | undefined): engineKind is EngineKind {
  return ENGINE_KINDS.includes(engineKind as EngineKind)
}
```

Update `resolveBuilderSurface` to use `isEngineKind`.

- [ ] **Step 6: Update `agent-list-filters.ts`**

Change imports and types: `DefinitionKind` → `EngineKind`, `AgentListDefinitionFilter` → `AgentListEngineFilter`.

Change filter field: `agent.definition_kind` → `agent.engine_kind`.

- [ ] **Step 7: Update `agent-list-filters.test.ts`**

Change mock data: `definition_kind: 'graph'` → `engine_kind: 'langgraph_visual'`, etc.

Change `runtime_kind: 'graph'` → `runtime_kind: 'server'`.

- [ ] **Step 8: Update `agent-overview-tab.tsx`**

Change: `draftVersion?.definition_kind` → `draftVersion?.engine_kind`.

- [ ] **Step 9: Update `visualDefinitionAdapter.ts`**

Change: `definition_kind: 'graph'` → `engine_kind: 'langgraph_visual'` in defaults and the `DefinitionKind` type references.

Change: `version.definition_kind` → `version.engine_kind`.

- [ ] **Step 10: Update remaining test files**

- `builder-surface-registry.test.ts`: update imports from `BUILDER_DEFINITION_KINDS` → `ENGINE_KINDS`
- `visualDefinitionAdapter.test.ts`: change `definition_kind: 'graph'` → `engine_kind: 'langgraph_visual'`, `definition_kind: 'code'` → `engine_kind: 'langgraph_code'`
- `visual-test-lab-stage.test.tsx`: change `definition_kind: 'graph'` → `engine_kind: 'langgraph_visual'`
- `agent-build-stages.test.tsx`: change `definition_kind: 'graph'` → `engine_kind: 'langgraph_visual'`

- [ ] **Step 11: Commit**

```bash
git add frontend/
git commit -m "refactor: update all frontend components to use EngineKind/RuntimeKind"
```

---

### Task 10: Update existing migration and verify

**Files:**
- Modify: `backend/alembic/versions/1a2b3c4d5e6f_unify_agent_run_metadata.py`

- [ ] **Step 1: Update old migration**

The old migration at line 67 consolidates `claude_code`/`codex`/`openclaw` → `sandbox_cli`. Since our new migration reverses this, update the old migration to NOT do the consolidation (since the new migration will handle the full rename):

Actually — the old migration has `down_revision = None` and is not wired into the chain yet. The new migration's `down_revision` should point to whatever the actual latest migration is, not `1a2b3c4d5e6f`. Check the alembic head:

```bash
cd backend && alembic heads
```

If the old migration (`1a2b3c4d5e6f`) is the current head, update line 67 to consolidate directly to per-tool values instead:

```python
# Line 67 — keep definition_kind at per-tool granularity (new migration will handle column rename)
# Remove this line entirely since the new migration handles the full remap
```

Actually, it's simpler: since `1a2b3c4d5e6f` consolidates to `sandbox_cli` and our new migration splits `sandbox_cli` back out using `runtime_binding`, the two migrations compose correctly. Leave the old migration as-is.

- [ ] **Step 2: Run full test suite to verify**

```bash
cd backend && python -m pytest --tb=short -q
```

```bash
cd frontend && npx vitest run --reporter=verbose
```

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "refactor: agent kind refactor complete — EngineKind + RuntimeKind"
```
