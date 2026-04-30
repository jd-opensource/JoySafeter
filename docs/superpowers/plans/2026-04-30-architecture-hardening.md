# Architecture Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the new Agent/Version/Release/Run/Execution architecture so contracts, boundaries, runtime capabilities, frontend surfaces, docs, and tests are aligned for future extension.

**Architecture:** Add canonical contract modules, move execution orchestration into the service layer, expose engine capability metadata, and clean the product boundary between AgentVersion and visual graph implementation details. Keep the visual builder stable by changing product-facing seams first rather than renaming every ReactFlow-internal graph concept.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Pydantic, pytest, Next.js, React, TypeScript, Vitest, Zustand, TanStack Query.

---

## File Map

### Backend Contracts

- Create `backend/app/core/contracts/__init__.py`
  - Re-export canonical contract values and helpers.
- Create `backend/app/core/contracts/agent.py`
  - Own `DEFINITION_KINDS`, `RUNTIME_KINDS`, `CLI_DEFINITION_KINDS`, and `DEFINITION_RUNTIME_KIND`.
- Create `backend/app/core/contracts/execution.py`
  - Own `RUN_STATUSES`, `EXECUTION_STATUSES`, `RELEASE_STATUSES`, `TRIGGER_SOURCES`, and active/terminal subsets.
- Modify `backend/app/core/agent_kinds.py`
  - Convert it into a compatibility import facade over `app.core.contracts.agent`.
- Modify `backend/app/schemas/agent.py`
  - Import `DefinitionKindLiteral` and `RuntimeKindLiteral` from canonical contracts.
- Modify `backend/app/schemas/agent_release.py`
  - Import `RuntimeKindLiteral` and `ReleaseStatusLiteral` from canonical contracts.
- Modify `backend/app/schemas/agent_run.py`
  - Import `TriggerSourceLiteral` from canonical contracts.

### Backend Orchestration Boundary

- Move `backend/app/core/engine/orchestrator.py` to `backend/app/services/execution_orchestrator.py`
  - Keep class/function behavior unchanged first.
- Modify `backend/app/services/dispatch_service.py`
  - Import `ExecutionOrchestrator` from `app.services.execution_orchestrator`.
- Modify `backend/app/api/v1/executions.py`
  - Import service-layer orchestrator in debug endpoint.
- Modify `backend/app/core/agent/coordinator_tools.py`
  - Import service-layer orchestrator for `publish_run_status_change`.

### Backend Engine Capabilities

- Modify `backend/app/core/engine/protocol.py`
  - Add `EngineCapabilities`.
  - Add `capabilities` to `ExecutionEngine` protocol.
- Modify `backend/app/core/engine/cli_engine.py`
  - Declare CLI capabilities.
- Modify `backend/app/core/engine/graph_engine.py`
  - Declare Graph capabilities.
- Modify `backend/app/core/engine/code_engine.py`
  - Declare Code capabilities.
- Modify `backend/app/core/engine/copilot_engine.py`
  - Declare Copilot capabilities.
- Modify `backend/app/services/execution_orchestrator.py`
  - Check `supports_message_injection` before `engine.send_message`.

### Event Sequencing Documentation

- Modify `backend/app/core/events/subscribers/persistence.py`
  - Add explicit single-process sequence cache warning and follow-up pointer in comments.

### Frontend Contracts and Visual Definition Boundary

- Modify `frontend/types/agent.ts`
  - Export arrays for supported definition/runtime kinds.
- Modify `frontend/types/agent-run.ts`
  - Add missing trigger sources and exported trigger-source array.
- Modify `frontend/types/agent-release.ts`
  - Export release statuses.
- Create `frontend/components/editors/graph-builder/services/visualDefinitionAdapter.ts`
  - Own AgentVersion definition-payload load/save for visual graph definitions.
- Modify `frontend/components/editors/graph-builder/services/graphDataAdapter.ts`
  - Re-export `visualDefinitionAdapter` as `graphDataAdapter` for compatibility.
- Modify `frontend/components/editors/graph-builder/utils/saveManager.ts`
  - Import `visualDefinitionAdapter`.
- Modify `frontend/components/editors/graph-builder/AgentBuilder.tsx`
  - Import `visualDefinitionAdapter`.
  - Keep ReactFlow-internal graph naming stable.
- Modify frontend tests under `frontend/components/editors/graph-builder/services/__tests__/` and `frontend/components/editors/graph-builder/utils/__tests__/`.

### Builder Surfaces

- Modify `frontend/components/agents/agent-build/builder-surface-registry.ts`
  - Export supported definition-kind list or assert exhaustive mapping.
- Modify `frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts`
  - Verify every supported definition kind maps to a surface.

### Documentation

- Modify `docs/ARCHITECTURE.md`
- Modify `docs/ARCHITECTURE_CN.md`
- Modify `docs/architecture-diagram.mmd`

### Tests

- Create `backend/tests/test_core/test_architecture_contracts.py`
- Create `backend/tests/test_services/test_execution_orchestrator_boundary.py`
- Create `frontend/types/__tests__/architecture-contracts.test.ts`
- Update existing frontend adapter and surface tests.

---

## Task 1: Add Backend Canonical Contract Modules

**Files:**
- Create: `backend/app/core/contracts/__init__.py`
- Create: `backend/app/core/contracts/agent.py`
- Create: `backend/app/core/contracts/execution.py`
- Modify: `backend/app/core/agent_kinds.py`
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/app/schemas/agent_release.py`
- Modify: `backend/app/schemas/agent_run.py`
- Test: `backend/tests/test_core/test_architecture_contracts.py`

- [ ] **Step 1: Write failing backend contract tests**

Create `backend/tests/test_core/test_architecture_contracts.py` with:

```python
from __future__ import annotations

from typing import get_args

from app.core.contracts.agent import (
    CLI_DEFINITION_KINDS,
    DEFINITION_KINDS,
    DEFINITION_RUNTIME_KIND,
    RUNTIME_KINDS,
    DefinitionKindLiteral,
    RuntimeKindLiteral,
    infer_runtime_kind,
    is_cli_definition_kind,
)
from app.core.contracts.execution import (
    EXECUTION_STATUSES,
    RELEASE_STATUSES,
    RUN_STATUSES,
    TRIGGER_SOURCES,
    ExecutionStatusLiteral,
    ReleaseStatusLiteral,
    RunStatusLiteral,
    TriggerSourceLiteral,
)
from app.models.agent import AgentRelease
from app.models.agent_run import AgentRun
from app.models.execution import Execution


def test_agent_contract_literals_match_runtime_sets() -> None:
    assert set(get_args(DefinitionKindLiteral)) == DEFINITION_KINDS
    assert set(get_args(RuntimeKindLiteral)) == RUNTIME_KINDS
    assert CLI_DEFINITION_KINDS == {"claude_code", "codex", "openclaw"}
    assert DEFINITION_RUNTIME_KIND == {
        "graph": "graph",
        "code": "code",
        "claude_code": "sandbox",
        "codex": "sandbox",
        "openclaw": "sandbox",
    }


def test_infer_runtime_kind_maps_every_definition_kind() -> None:
    assert {kind: infer_runtime_kind(kind) for kind in DEFINITION_KINDS} == DEFINITION_RUNTIME_KIND
    assert is_cli_definition_kind("claude_code") is True
    assert is_cli_definition_kind("graph") is False


def test_execution_contract_literals_match_runtime_sets() -> None:
    assert set(get_args(RunStatusLiteral)) == RUN_STATUSES
    assert set(get_args(ExecutionStatusLiteral)) == EXECUTION_STATUSES
    assert set(get_args(ReleaseStatusLiteral)) == RELEASE_STATUSES
    assert set(get_args(TriggerSourceLiteral)) == TRIGGER_SOURCES
    assert {"draft_test", "draft_copilot", "debug", "copilot"}.issubset(TRIGGER_SOURCES)


def _enum_values(model, column_name: str) -> set[str]:
    column = model.__table__.columns[column_name]
    return set(column.type.enums)


def test_model_status_enums_match_contracts() -> None:
    assert _enum_values(AgentRun, "status") == RUN_STATUSES
    assert _enum_values(Execution, "status") == EXECUTION_STATUSES
    assert _enum_values(AgentRelease, "status") == RELEASE_STATUSES
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_architecture_contracts.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.contracts'`.

- [ ] **Step 3: Create canonical agent contracts**

Create `backend/app/core/contracts/agent.py`:

```python
"""Canonical Agent definition/runtime kind contract values."""

from __future__ import annotations

from typing import Literal

from app.common.app_errors import InvalidRequestError

DefinitionKindLiteral = Literal["graph", "code", "claude_code", "codex", "openclaw"]
RuntimeKindLiteral = Literal["graph", "code", "sandbox"]

DEFINITION_KINDS: set[str] = {"graph", "code", "claude_code", "codex", "openclaw"}
CLI_DEFINITION_KINDS: set[str] = {"claude_code", "codex", "openclaw"}
RUNTIME_KINDS: set[str] = {"graph", "code", "sandbox"}
DEFINITION_RUNTIME_KIND: dict[str, str] = {
    "graph": "graph",
    "code": "code",
    "claude_code": "sandbox",
    "codex": "sandbox",
    "openclaw": "sandbox",
}


def infer_runtime_kind(definition_kind: str) -> str:
    runtime_kind = DEFINITION_RUNTIME_KIND.get(definition_kind)
    if not runtime_kind:
        raise InvalidRequestError(
            f"Unsupported definition_kind={definition_kind}",
            code="AGENT_DEFINITION_KIND_UNSUPPORTED",
            data={"definition_kind": definition_kind},
        )
    return runtime_kind


def is_cli_definition_kind(definition_kind: str) -> bool:
    return definition_kind in CLI_DEFINITION_KINDS


def normalize_definition_kind(definition_kind: str | None) -> str | None:
    return definition_kind if definition_kind in DEFINITION_KINDS else None


def normalize_runtime_kind(runtime_kind: str | None) -> str | None:
    return runtime_kind if runtime_kind in RUNTIME_KINDS else None
```

- [ ] **Step 4: Create canonical execution contracts**

Create `backend/app/core/contracts/execution.py`:

```python
"""Canonical execution contract values."""

from __future__ import annotations

from typing import Literal

RunStatusLiteral = Literal["pending", "running", "succeeded", "failed", "cancelled"]
ExecutionStatusLiteral = Literal[
    "pending",
    "dispatched",
    "running",
    "approval_wait",
    "succeeded",
    "failed",
    "cancelled",
]
ReleaseStatusLiteral = Literal["ready", "active", "superseded", "failed", "retired"]
TriggerSourceLiteral = Literal[
    "task",
    "chat",
    "api",
    "scheduler",
    "draft_test",
    "draft_copilot",
    "debug",
    "copilot",
]

RUN_STATUSES: set[str] = {"pending", "running", "succeeded", "failed", "cancelled"}
ACTIVE_RUN_STATUSES: set[str] = {"pending", "running"}
TERMINAL_RUN_STATUSES: set[str] = {"succeeded", "failed", "cancelled"}

EXECUTION_STATUSES: set[str] = {
    "pending",
    "dispatched",
    "running",
    "approval_wait",
    "succeeded",
    "failed",
    "cancelled",
}
ACTIVE_EXECUTION_STATUSES: set[str] = {"pending", "dispatched", "running", "approval_wait"}
TERMINAL_EXECUTION_STATUSES: set[str] = {"succeeded", "failed", "cancelled"}

RELEASE_STATUSES: set[str] = {"ready", "active", "superseded", "failed", "retired"}
TRIGGER_SOURCES: set[str] = {
    "task",
    "chat",
    "api",
    "scheduler",
    "draft_test",
    "draft_copilot",
    "debug",
    "copilot",
}
```

- [ ] **Step 5: Create contract package re-exports**

Create `backend/app/core/contracts/__init__.py`:

```python
"""Canonical cross-layer contract values."""

from app.core.contracts.agent import (
    CLI_DEFINITION_KINDS,
    DEFINITION_KINDS,
    DEFINITION_RUNTIME_KIND,
    RUNTIME_KINDS,
    DefinitionKindLiteral,
    RuntimeKindLiteral,
    infer_runtime_kind,
    is_cli_definition_kind,
    normalize_definition_kind,
    normalize_runtime_kind,
)
from app.core.contracts.execution import (
    ACTIVE_EXECUTION_STATUSES,
    ACTIVE_RUN_STATUSES,
    EXECUTION_STATUSES,
    RELEASE_STATUSES,
    RUN_STATUSES,
    TERMINAL_EXECUTION_STATUSES,
    TERMINAL_RUN_STATUSES,
    TRIGGER_SOURCES,
    ExecutionStatusLiteral,
    ReleaseStatusLiteral,
    RunStatusLiteral,
    TriggerSourceLiteral,
)

__all__ = [
    "ACTIVE_EXECUTION_STATUSES",
    "ACTIVE_RUN_STATUSES",
    "CLI_DEFINITION_KINDS",
    "DEFINITION_KINDS",
    "DEFINITION_RUNTIME_KIND",
    "EXECUTION_STATUSES",
    "ExecutionStatusLiteral",
    "DefinitionKindLiteral",
    "RELEASE_STATUSES",
    "RUNTIME_KINDS",
    "RUN_STATUSES",
    "ReleaseStatusLiteral",
    "RuntimeKindLiteral",
    "RunStatusLiteral",
    "TERMINAL_EXECUTION_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "TRIGGER_SOURCES",
    "TriggerSourceLiteral",
    "infer_runtime_kind",
    "is_cli_definition_kind",
    "normalize_definition_kind",
    "normalize_runtime_kind",
]
```

- [ ] **Step 6: Turn `agent_kinds.py` into a compatibility facade**

Replace `backend/app/core/agent_kinds.py` with:

```python
"""Compatibility imports for canonical Agent kind contract values."""

from app.core.contracts.agent import (
    CLI_DEFINITION_KINDS,
    DEFINITION_KINDS as SUPPORTED_DEFINITION_KINDS,
    DEFINITION_RUNTIME_KIND,
    RUNTIME_KINDS as SUPPORTED_RUNTIME_KINDS,
    DefinitionKindLiteral,
    RuntimeKindLiteral,
    infer_runtime_kind,
    is_cli_definition_kind,
    normalize_definition_kind,
    normalize_runtime_kind,
)

__all__ = [
    "CLI_DEFINITION_KINDS",
    "DEFINITION_RUNTIME_KIND",
    "DefinitionKindLiteral",
    "RuntimeKindLiteral",
    "SUPPORTED_DEFINITION_KINDS",
    "SUPPORTED_RUNTIME_KINDS",
    "infer_runtime_kind",
    "is_cli_definition_kind",
    "normalize_definition_kind",
    "normalize_runtime_kind",
]
```

- [ ] **Step 7: Update schemas to import canonical literals**

In `backend/app/schemas/agent.py`, replace:

```python
from app.core.agent_kinds import DefinitionKindLiteral, RuntimeKindLiteral
```

with:

```python
from app.core.contracts.agent import DefinitionKindLiteral, RuntimeKindLiteral
```

In `backend/app/schemas/agent_release.py`, replace:

```python
from typing import Literal, Optional
from app.core.agent_kinds import RuntimeKindLiteral

ReleaseStatusLiteral = Literal["ready", "active", "superseded", "failed", "retired"]
```

with:

```python
from typing import Optional
from pydantic import BaseModel

from app.core.contracts.agent import RuntimeKindLiteral
from app.core.contracts.execution import ReleaseStatusLiteral
```

In `backend/app/schemas/agent_run.py`, replace:

```python
from typing import Literal, Optional
TriggerSourceLiteral = Literal[
    "task",
    "chat",
    "api",
    "scheduler",
    "comment",
    "mention",
    "draft_copilot",
    "draft_test",
]
```

with:

```python
from typing import Optional
from pydantic import BaseModel

from app.core.contracts.execution import TriggerSourceLiteral
```

- [ ] **Step 8: Run backend contract tests**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_architecture_contracts.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit backend contract alignment**

```bash
git add backend/app/core/contracts backend/app/core/agent_kinds.py backend/app/schemas/agent.py backend/app/schemas/agent_release.py backend/app/schemas/agent_run.py backend/tests/test_core/test_architecture_contracts.py
git commit -m "refactor: centralize architecture contract values"
```

---

## Task 2: Move Execution Orchestrator to the Service Layer

**Files:**
- Move: `backend/app/core/engine/orchestrator.py` -> `backend/app/services/execution_orchestrator.py`
- Modify: `backend/app/services/dispatch_service.py`
- Modify: `backend/app/api/v1/executions.py`
- Modify: `backend/app/core/agent/coordinator_tools.py`
- Test: `backend/tests/test_services/test_execution_orchestrator_boundary.py`

- [ ] **Step 1: Write failing service-boundary tests**

Create `backend/tests/test_services/test_execution_orchestrator_boundary.py`:

```python
from __future__ import annotations

import importlib


def test_dispatch_service_uses_service_layer_orchestrator() -> None:
    module = importlib.import_module("app.services.dispatch_service")
    assert module.ExecutionOrchestrator.__module__ == "app.services.execution_orchestrator"


def test_core_engine_orchestrator_module_removed() -> None:
    try:
        importlib.import_module("app.core.engine.orchestrator")
        assert False, "app.core.engine.orchestrator should not remain importable"
    except ModuleNotFoundError:
        pass


def test_engine_package_does_not_export_product_orchestration() -> None:
    engine_module = importlib.import_module("app.core.engine")
    assert not hasattr(engine_module, "ExecutionOrchestrator")
```

- [ ] **Step 2: Run boundary tests to verify failure**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_services/test_execution_orchestrator_boundary.py -q
```

Expected: FAIL because `app.services.execution_orchestrator` does not exist and `app.core.engine.orchestrator` is still importable.

- [ ] **Step 3: Move the orchestrator file**

Run:

```bash
mv backend/app/core/engine/orchestrator.py backend/app/services/execution_orchestrator.py
```

Then edit the module docstring at the top of `backend/app/services/execution_orchestrator.py` to:

```python
"""
Execution Orchestrator — service-layer entry point for execution dispatch.

Layer 2: sits between API/triggers (Layer 1) and engines (Layer 3).
Creates AgentRun + Execution, resolves the engine, builds context, and starts execution.
"""
```

- [ ] **Step 4: Update service and API imports**

In `backend/app/services/dispatch_service.py`, replace:

```python
from app.core.engine.orchestrator import ExecutionOrchestrator
```

with:

```python
from app.services.execution_orchestrator import ExecutionOrchestrator
```

In `backend/app/api/v1/executions.py`, replace:

```python
from app.core.engine.orchestrator import ExecutionOrchestrator
```

with:

```python
from app.services.execution_orchestrator import ExecutionOrchestrator
```

In `backend/app/core/agent/coordinator_tools.py`, replace:

```python
from app.core.engine.orchestrator import ExecutionOrchestrator
```

with:

```python
from app.services.execution_orchestrator import ExecutionOrchestrator
```

- [ ] **Step 5: Search for stale orchestrator imports**

Run:

```bash
rg -n "app\\.core\\.engine\\.orchestrator|core/engine/orchestrator|ExecutionOrchestrator" backend/app backend/tests
```

Expected: all `ExecutionOrchestrator` imports point to `app.services.execution_orchestrator`; no result contains `app.core.engine.orchestrator`.

- [ ] **Step 6: Run boundary tests**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_services/test_execution_orchestrator_boundary.py -q
```

Expected: PASS.

- [ ] **Step 7: Run existing structured-error test that imports EngineRegistry**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_http_error_contract.py::test_engine_registry_raises_structured_error_for_missing_runtime -q
```

Expected: PASS.

- [ ] **Step 8: Commit orchestrator boundary move**

```bash
git add backend/app/services/execution_orchestrator.py backend/app/services/dispatch_service.py backend/app/api/v1/executions.py backend/app/core/agent/coordinator_tools.py backend/tests/test_services/test_execution_orchestrator_boundary.py
git add -u backend/app/core/engine/orchestrator.py
git commit -m "refactor: move execution orchestrator to service layer"
```

---

## Task 3: Add Engine Capability Metadata and Structured Unsupported Operation Errors

**Files:**
- Modify: `backend/app/core/engine/protocol.py`
- Modify: `backend/app/core/engine/cli_engine.py`
- Modify: `backend/app/core/engine/graph_engine.py`
- Modify: `backend/app/core/engine/code_engine.py`
- Modify: `backend/app/core/engine/copilot_engine.py`
- Modify: `backend/app/services/execution_orchestrator.py`
- Test: `backend/tests/test_core/test_architecture_contracts.py`
- Test: `backend/tests/test_core/test_http_error_contract.py`

- [ ] **Step 1: Add failing tests for engine capabilities**

Append to `backend/tests/test_core/test_architecture_contracts.py`:

```python
from app.core.engine import engine_registry
from app.core.engine.protocol import EngineCapabilities


def test_registered_engines_declare_capabilities() -> None:
    for runtime_kind in ["sandbox", "graph", "code", "copilot"]:
        engine = engine_registry.get(runtime_kind)
        assert isinstance(engine.capabilities, EngineCapabilities)


def test_graph_engine_declares_no_message_injection() -> None:
    graph_engine = engine_registry.get("graph")
    assert graph_engine.capabilities.supports_message_injection is False
```

Append to `backend/tests/test_core/test_http_error_contract.py`:

```python
def test_execution_operation_unsupported_error_payload() -> None:
    from app.common.app_errors import InvalidRequestError

    error = InvalidRequestError(
        "Execution engine does not support message injection",
        code="EXECUTION_OPERATION_UNSUPPORTED",
        data={
            "operation": "send_message",
            "engine_kind": "graph",
            "execution_id": "exec-1",
        },
    )

    assert error.to_payload() == {
        "code": "EXECUTION_OPERATION_UNSUPPORTED",
        "message": "Execution engine does not support message injection",
        "data": {
            "operation": "send_message",
            "engine_kind": "graph",
            "execution_id": "exec-1",
        },
    }
```

- [ ] **Step 2: Run capability tests to verify failure**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_architecture_contracts.py::test_registered_engines_declare_capabilities backend/tests/test_core/test_architecture_contracts.py::test_graph_engine_declares_no_message_injection -q
```

Expected: FAIL because `EngineCapabilities` or `engine.capabilities` does not exist.

- [ ] **Step 3: Add `EngineCapabilities` to protocol**

In `backend/app/core/engine/protocol.py`, add after imports:

```python
@dataclass(frozen=True)
class EngineCapabilities:
    """Feature flags exposed by execution engines to API/service callers."""

    supports_cancel: bool = False
    supports_message_injection: bool = False
    supports_debug_observation: bool = False
    supports_artifacts: bool = False
    supports_approval: bool = False
```

Add this attribute to `class ExecutionEngine(Protocol)`:

```python
    capabilities: EngineCapabilities
```

Update `__all__` exports in `backend/app/core/engine/__init__.py` by importing and exporting `EngineCapabilities`:

```python
from app.core.engine.protocol import EngineCapabilities, ExecutionContext, ExecutionEngine
```

and add `"EngineCapabilities"` to `__all__`.

- [ ] **Step 4: Add capabilities to concrete engines**

In `backend/app/core/engine/cli_engine.py`, import `EngineCapabilities` and set inside `CLIEngine`:

```python
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=True,
        supports_debug_observation=False,
        supports_artifacts=True,
        supports_approval=True,
    )
```

In `backend/app/core/engine/graph_engine.py`, import `EngineCapabilities` and set inside `GraphEngine`:

```python
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=False,
        supports_debug_observation=True,
        supports_artifacts=True,
        supports_approval=True,
    )
```

In `backend/app/core/engine/code_engine.py`, import `EngineCapabilities` and set inside `CodeEngine`:

```python
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=False,
        supports_debug_observation=True,
        supports_artifacts=False,
        supports_approval=False,
    )
```

In `backend/app/core/engine/copilot_engine.py`, import `EngineCapabilities` and set inside `CopilotEngine`:

```python
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=False,
        supports_debug_observation=False,
        supports_artifacts=False,
        supports_approval=False,
    )
```

If any engine class currently lacks a class body location near `engine_kind`, place `capabilities` immediately below `engine_kind`.

- [ ] **Step 5: Preflight message injection in orchestrator**

In `backend/app/services/execution_orchestrator.py`, inside `send_message()` just before:

```python
        await engine.send_message(execution_id, message)
```

insert:

```python
        if not engine.capabilities.supports_message_injection:
            raise InvalidRequestError(
                "Execution engine does not support message injection",
                code="EXECUTION_OPERATION_UNSUPPORTED",
                data={
                    "operation": "send_message",
                    "engine_kind": getattr(engine, "engine_kind", execution.executor_kind),
                    "execution_id": str(execution_id),
                },
            )
```

- [ ] **Step 6: Run capability and structured-error tests**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_architecture_contracts.py backend/tests/test_core/test_http_error_contract.py::test_execution_operation_unsupported_error_payload -q
```

Expected: PASS.

- [ ] **Step 7: Commit engine capability metadata**

```bash
git add backend/app/core/engine backend/app/services/execution_orchestrator.py backend/tests/test_core/test_architecture_contracts.py backend/tests/test_core/test_http_error_contract.py
git commit -m "feat: expose execution engine capabilities"
```

---

## Task 4: Document Event Sequence Cache Risk

**Files:**
- Modify: `backend/app/core/events/subscribers/persistence.py`
- Test: `backend/tests/test_core/test_architecture_contracts.py`

- [ ] **Step 1: Add a test that protects the warning text**

Append to `backend/tests/test_core/test_architecture_contracts.py`:

```python
from pathlib import Path


def test_persistence_subscriber_documents_single_process_sequence_cache() -> None:
    source = Path("backend/app/core/events/subscribers/persistence.py").read_text()
    assert "single-process sequence cache" in source
    assert "distributed event sequencing" in source
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_architecture_contracts.py::test_persistence_subscriber_documents_single_process_sequence_cache -q
```

Expected: FAIL because the exact warning text is not present.

- [ ] **Step 3: Add explicit event sequencing warning**

In `backend/app/core/events/subscribers/persistence.py`, replace the current `_seq_cache` comment:

```python
        # In-memory seq counter per execution — avoids MAX() query on every event.
        # Seeded lazily on first event for each execution_id.
```

with:

```python
        # single-process sequence cache:
        # This in-memory counter avoids a MAX() query on every event and is safe
        # only when one backend process owns event writes for an execution. Multi-
        # worker or multi-instance deployments need distributed event sequencing
        # before this cache can be treated as globally safe.
```

- [ ] **Step 4: Run event sequencing documentation test**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_architecture_contracts.py::test_persistence_subscriber_documents_single_process_sequence_cache -q
```

Expected: PASS.

- [ ] **Step 5: Commit event sequencing documentation**

```bash
git add backend/app/core/events/subscribers/persistence.py backend/tests/test_core/test_architecture_contracts.py
git commit -m "docs: document execution event sequencing constraint"
```

---

## Task 5: Align Frontend Contract Types

**Files:**
- Modify: `frontend/types/agent.ts`
- Modify: `frontend/types/agent-run.ts`
- Modify: `frontend/types/agent-release.ts`
- Create: `frontend/types/__tests__/architecture-contracts.test.ts`

- [ ] **Step 1: Write failing frontend contract tests**

Create `frontend/types/__tests__/architecture-contracts.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import { BUILDER_DEFINITION_KINDS, RUNTIME_KINDS } from '@/types/agent'
import {
  ACTIVE_EXECUTION_STATUSES,
  ACTIVE_RUN_STATUSES,
  EXECUTION_STATUSES,
  RUN_STATUSES,
  TERMINAL_EXECUTION_STATUSES,
  TERMINAL_RUN_STATUSES,
  TRIGGER_SOURCES,
} from '@/types/agent-run'
import { RELEASE_STATUSES } from '@/types/agent-release'

describe('architecture contract constants', () => {
  it('matches backend definition and runtime kinds', () => {
    expect([...BUILDER_DEFINITION_KINDS].sort()).toEqual([
      'claude_code',
      'code',
      'codex',
      'graph',
      'openclaw',
    ])
    expect([...RUNTIME_KINDS].sort()).toEqual(['code', 'graph', 'sandbox'])
  })

  it('matches backend run and execution statuses', () => {
    expect([...RUN_STATUSES].sort()).toEqual([
      'cancelled',
      'failed',
      'pending',
      'running',
      'succeeded',
    ])
    expect([...ACTIVE_RUN_STATUSES].sort()).toEqual(['pending', 'running'])
    expect([...TERMINAL_RUN_STATUSES].sort()).toEqual(['cancelled', 'failed', 'succeeded'])
    expect([...EXECUTION_STATUSES].sort()).toEqual([
      'approval_wait',
      'cancelled',
      'dispatched',
      'failed',
      'pending',
      'running',
      'succeeded',
    ])
    expect([...ACTIVE_EXECUTION_STATUSES].sort()).toEqual([
      'approval_wait',
      'dispatched',
      'pending',
      'running',
    ])
    expect([...TERMINAL_EXECUTION_STATUSES].sort()).toEqual(['cancelled', 'failed', 'succeeded'])
  })

  it('matches backend release statuses and trigger sources', () => {
    expect([...RELEASE_STATUSES].sort()).toEqual([
      'active',
      'failed',
      'ready',
      'retired',
      'superseded',
    ])
    expect([...TRIGGER_SOURCES].sort()).toEqual([
      'api',
      'chat',
      'copilot',
      'debug',
      'draft_copilot',
      'draft_test',
      'scheduler',
      'task',
    ])
  })
})
```

- [ ] **Step 2: Run frontend contract tests to verify failure**

Run:

```bash
cd frontend && bun test types/__tests__/architecture-contracts.test.ts
```

Expected: FAIL because `RUNTIME_KINDS`, `RUN_STATUSES`, `EXECUTION_STATUSES`, `TRIGGER_SOURCES`, or `RELEASE_STATUSES` are not exported yet.

- [ ] **Step 3: Export agent kind constants**

In `frontend/types/agent.ts`, ensure the top section is:

```typescript
export type DefinitionKind = 'graph' | 'code' | 'claude_code' | 'codex' | 'openclaw'
export type RuntimeKind = 'graph' | 'code' | 'sandbox'

export const BUILDER_DEFINITION_KINDS: readonly DefinitionKind[] = [
  'graph',
  'code',
  'claude_code',
  'codex',
  'openclaw',
] as const

export const RUNTIME_KINDS: readonly RuntimeKind[] = [
  'graph',
  'code',
  'sandbox',
] as const
```

Keep existing exports below this section unchanged unless they duplicate these declarations.

- [ ] **Step 4: Export run, execution, and trigger constants**

In `frontend/types/agent-run.ts`, update `trigger_source` and `CreateAgentRunRequest.trigger_source` to use:

```typescript
export type TriggerSource =
  | 'task'
  | 'chat'
  | 'api'
  | 'scheduler'
  | 'draft_test'
  | 'draft_copilot'
  | 'debug'
  | 'copilot'

export const TRIGGER_SOURCES: readonly TriggerSource[] = [
  'task',
  'chat',
  'api',
  'scheduler',
  'draft_test',
  'draft_copilot',
  'debug',
  'copilot',
] as const
```

Add this constant immediately after `AgentRunStatus`:

```typescript
export const RUN_STATUSES: readonly AgentRunStatus[] = [
  'pending',
  'running',
  'succeeded',
  'failed',
  'cancelled',
] as const
```

Add this constant immediately after `ExecutionStatus`:

```typescript
export const EXECUTION_STATUSES: readonly ExecutionStatus[] = [
  'pending',
  'dispatched',
  'running',
  'approval_wait',
  'succeeded',
  'failed',
  'cancelled',
] as const
```

Then change:

```typescript
  trigger_source: 'task' | 'chat' | 'api' | 'scheduler' | 'comment' | 'mention' | 'copilot'
```

to:

```typescript
  trigger_source: TriggerSource
```

and change `CreateAgentRunRequest.trigger_source` the same way.

- [ ] **Step 5: Export release status constants**

In `frontend/types/agent-release.ts`, add near the top:

```typescript
export const RELEASE_STATUSES = [
  'ready',
  'active',
  'superseded',
  'failed',
  'retired',
] as const
```

If `ReleaseStatus` currently aliases `AgentRelease['status']`, replace it with:

```typescript
export type ReleaseStatus = (typeof RELEASE_STATUSES)[number]
```

Ensure `AgentRelease.status` uses `ReleaseStatus`.

- [ ] **Step 6: Run frontend contract tests**

Run:

```bash
cd frontend && bun test types/__tests__/architecture-contracts.test.ts
```

Expected: PASS.

- [ ] **Step 7: Run related frontend tests**

Run:

```bash
cd frontend && bun test components/agents/agent-build/__tests__/builder-surface-registry.test.ts lib/agents/agent-list-filters.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit frontend contract alignment**

```bash
git add frontend/types/agent.ts frontend/types/agent-run.ts frontend/types/agent-release.ts frontend/types/__tests__/architecture-contracts.test.ts
git commit -m "refactor: align frontend architecture contracts"
```

---

## Task 6: Introduce Visual Definition Adapter Boundary

**Files:**
- Create: `frontend/components/editors/graph-builder/services/visualDefinitionAdapter.ts`
- Modify: `frontend/components/editors/graph-builder/services/graphDataAdapter.ts`
- Modify: `frontend/components/editors/graph-builder/utils/saveManager.ts`
- Modify: `frontend/components/editors/graph-builder/AgentBuilder.tsx`
- Modify: `frontend/components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts`
- Create: `frontend/components/editors/graph-builder/services/__tests__/visualDefinitionAdapter.test.ts`
- Modify: `frontend/components/editors/graph-builder/utils/__tests__/saveManager.test.ts`

- [ ] **Step 1: Write visual adapter tests**

Create `frontend/components/editors/graph-builder/services/__tests__/visualDefinitionAdapter.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { visualDefinitionAdapter } from '../visualDefinitionAdapter'
import { agentVersionService } from '@/services/agentVersionService'

vi.mock('@/services/agentVersionService', () => ({
  agentVersionService: {
    get: vi.fn(),
    update: vi.fn(),
    create: vi.fn(),
  },
}))

vi.mock('@/lib/api-client', () => ({
  API_BASE: '/api/v1',
}))

describe('visualDefinitionAdapter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads visual definition state from AgentVersion.definition_payload', async () => {
    vi.mocked(agentVersionService.get).mockResolvedValue({
      id: 'v1',
      agent_id: 'a1',
      version_number: 1,
      status: 'draft',
      source_kind: 'manual',
      definition_kind: 'graph',
      definition_payload: {
        nodes: [{ id: 'n1' }],
        edges: [],
        viewport: { x: 1, y: 2, zoom: 0.5 },
        graphStateFields: [{ name: 'target', type: 'string' }],
        fallbackNodeId: 'n1',
      },
      capability_manifest: {},
      changelog: null,
      created_by: 'u1',
      created_at: '2026-04-30T00:00:00Z',
    } as any)

    const state = await visualDefinitionAdapter.load('a1', 'v1', 'w1')

    expect(agentVersionService.get).toHaveBeenCalledWith('a1', 'v1', 'w1')
    expect(state.agentId).toBe('a1')
    expect(state.versionId).toBe('v1')
    expect(state.workspaceId).toBe('w1')
    expect(state.nodes).toEqual([{ id: 'n1' }])
    expect(state.fallbackNodeId).toBe('n1')
  })

  it('saves visual definition state to AgentVersion.definition_payload', async () => {
    vi.mocked(agentVersionService.update).mockResolvedValue({ id: 'v2' } as any)

    const result = await visualDefinitionAdapter.save('a1', 'v1', 'w1', {
      nodes: [{ id: 'n1' }] as any,
      edges: [],
      fallbackNodeId: 'n1',
    })

    expect(agentVersionService.update).toHaveBeenCalledWith('a1', 'v1', 'w1', {
      definition_payload: {
        nodes: [{ id: 'n1' }],
        edges: [],
        fallbackNodeId: 'n1',
      },
    })
    expect(result).toEqual({ versionId: 'v2' })
  })
})
```

- [ ] **Step 2: Run visual adapter tests to verify failure**

Run:

```bash
cd frontend && bun test components/editors/graph-builder/services/__tests__/visualDefinitionAdapter.test.ts
```

Expected: FAIL because `visualDefinitionAdapter.ts` does not exist.

- [ ] **Step 3: Create visual definition adapter**

Create `frontend/components/editors/graph-builder/services/visualDefinitionAdapter.ts`:

```typescript
import { API_BASE } from '@/lib/api-client'
import { agentVersionService } from '@/services/agentVersionService'

import type { GraphState } from '../utils/saveManager'

function toVisualDefinitionState(
  payload: Record<string, unknown>,
  agentId: string,
  versionId: string,
  workspaceId: string,
): GraphState {
  return {
    graphId: agentId,
    graphName: (payload.graphName as string) ?? null,
    nodes: (payload.nodes as any[]) ?? [],
    edges: (payload.edges as any[]) ?? [],
    viewport: (payload.viewport as { x: number; y: number; zoom: number }) ?? { x: 0, y: 0, zoom: 1 },
    graphStateFields: (payload.graphStateFields as any[]) ?? [],
    fallbackNodeId: (payload.fallbackNodeId as string) ?? null,
    agentId,
    versionId,
    workspaceId,
  }
}

export const visualDefinitionAdapter = {
  async load(agentId: string, versionId: string, workspaceId: string): Promise<GraphState> {
    const version = await agentVersionService.get(agentId, versionId, workspaceId)
    return toVisualDefinitionState(version.definition_payload, agentId, versionId, workspaceId)
  },

  async save(
    agentId: string,
    versionId: string,
    workspaceId: string,
    graphState: Partial<GraphState>,
  ): Promise<{ versionId: string }> {
    const updated = await agentVersionService.update(agentId, versionId, workspaceId, {
      definition_payload: graphState,
    })
    return { versionId: updated.id }
  },

  sendBeaconSave(
    agentId: string,
    versionId: string,
    workspaceId: string,
    graphState: { nodes: unknown[]; edges: unknown[]; viewport?: unknown },
  ): void {
    const url = `${API_BASE}/agents/${agentId}/versions/${versionId}?workspace_id=${workspaceId}`
    const body = JSON.stringify({ definition_payload: graphState })
    fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {})
  },

  async createDraft(agentId: string, workspaceId: string, basePayload?: Record<string, unknown>): Promise<string> {
    const version = await agentVersionService.create(agentId, workspaceId, {
      definition_kind: 'graph',
      definition_payload: basePayload || {},
    })
    return version.id
  },
}
```

- [ ] **Step 4: Convert old graph adapter to compatibility re-export**

Replace `frontend/components/editors/graph-builder/services/graphDataAdapter.ts` with:

```typescript
import { visualDefinitionAdapter } from './visualDefinitionAdapter'

export const graphDataAdapter = visualDefinitionAdapter
```

- [ ] **Step 5: Update product-facing imports to use visual adapter**

In `frontend/components/editors/graph-builder/utils/saveManager.ts`, replace:

```typescript
import { graphDataAdapter } from '../services/graphDataAdapter'
```

with:

```typescript
import { visualDefinitionAdapter } from '../services/visualDefinitionAdapter'
```

and replace:

```typescript
      const result = await graphDataAdapter.save(state.agentId, state.versionId, state.workspaceId, {
```

with:

```typescript
      const result = await visualDefinitionAdapter.save(state.agentId, state.versionId, state.workspaceId, {
```

In `frontend/components/editors/graph-builder/AgentBuilder.tsx`, replace:

```typescript
import { graphDataAdapter } from './services/graphDataAdapter'
```

with:

```typescript
import { visualDefinitionAdapter } from './services/visualDefinitionAdapter'
```

and replace:

```typescript
          graphDataAdapter.sendBeaconSave(graphId, versionId, workspaceId, {
```

with:

```typescript
          visualDefinitionAdapter.sendBeaconSave(graphId, versionId, workspaceId, {
```

- [ ] **Step 6: Update save manager test mock**

In `frontend/components/editors/graph-builder/utils/__tests__/saveManager.test.ts`, replace the mock:

```typescript
vi.mock('../../services/graphDataAdapter', () => ({
  graphDataAdapter: { save: (...args: any[]) => mockGraphDataAdapterSave(...args) },
}))
```

with:

```typescript
vi.mock('../../services/visualDefinitionAdapter', () => ({
  visualDefinitionAdapter: { save: (...args: any[]) => mockGraphDataAdapterSave(...args) },
}))
```

Keep existing test names unless a test name explicitly says it imports `graphDataAdapter`.

- [ ] **Step 7: Run adapter and save-manager tests**

Run:

```bash
cd frontend && bun test components/editors/graph-builder/services/__tests__/visualDefinitionAdapter.test.ts components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts components/editors/graph-builder/utils/__tests__/saveManager.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit visual definition adapter boundary**

```bash
git add frontend/components/editors/graph-builder/services/visualDefinitionAdapter.ts frontend/components/editors/graph-builder/services/graphDataAdapter.ts frontend/components/editors/graph-builder/utils/saveManager.ts frontend/components/editors/graph-builder/AgentBuilder.tsx frontend/components/editors/graph-builder/services/__tests__/visualDefinitionAdapter.test.ts frontend/components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts frontend/components/editors/graph-builder/utils/__tests__/saveManager.test.ts
git commit -m "refactor: introduce visual definition adapter"
```

---

## Task 7: Make Builder Surface Registry Exhaustive

**Files:**
- Modify: `frontend/components/agents/agent-build/builder-surface-registry.ts`
- Modify: `frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts`

- [ ] **Step 1: Update failing exhaustive surface test**

Replace `frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts` with:

```typescript
import { describe, it, expect } from 'vitest'

import { BUILDER_DEFINITION_KINDS } from '@/types/agent'

import { resolveBuilderSurface } from '../builder-surface-registry'

describe('resolveBuilderSurface', () => {
  it('maps every supported definition kind to a complete surface', () => {
    for (const definitionKind of BUILDER_DEFINITION_KINDS) {
      const surface = resolveBuilderSurface(definitionKind)
      expect(surface.BriefStage, definitionKind).toBeDefined()
      expect(surface.BuildStage, definitionKind).toBeDefined()
      expect(surface.TestLabStage, definitionKind).toBeDefined()
    }
  })

  it('returns visual surface for graph', () => {
    const surface = resolveBuilderSurface('graph')
    expect(surface.BriefStage).toBeDefined()
    expect(surface.BuildStage).toBeDefined()
    expect(surface.TestLabStage).toBeDefined()
  })

  it('returns explicit placeholder surface for code', () => {
    const surface = resolveBuilderSurface('code')
    expect(surface.BriefStage).toBeDefined()
    expect(surface.BuildStage).toBeDefined()
    expect(surface.TestLabStage).toBeDefined()
  })

  it('returns the shared sandbox builder surface for CLI-backed definition kinds', () => {
    const claudeCode = resolveBuilderSurface('claude_code')
    expect(resolveBuilderSurface('codex')).toBe(claudeCode)
    expect(resolveBuilderSurface('openclaw')).toBe(claudeCode)
  })

  it('defaults to visual for null/undefined', () => {
    expect(resolveBuilderSurface(null)).toBe(resolveBuilderSurface('graph'))
    expect(resolveBuilderSurface(undefined)).toBe(resolveBuilderSurface('graph'))
  })
})
```

- [ ] **Step 2: Run registry test**

Run:

```bash
cd frontend && bun test components/agents/agent-build/__tests__/builder-surface-registry.test.ts
```

Expected: PASS if Task 5 already exported `BUILDER_DEFINITION_KINDS`; FAIL otherwise.

- [ ] **Step 3: Make registry type exhaustive**

In `frontend/components/agents/agent-build/builder-surface-registry.ts`, replace:

```typescript
const DEFINITION_TO_SURFACE: Record<string, BuilderSurfaceKind> = {
```

with:

```typescript
import type { DefinitionKind } from '@/types/agent'

const DEFINITION_TO_SURFACE: Record<DefinitionKind, BuilderSurfaceKind> = {
```

If the file already has imports at the top, place the new type import with the other imports.

- [ ] **Step 4: Run registry test again**

Run:

```bash
cd frontend && bun test components/agents/agent-build/__tests__/builder-surface-registry.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit exhaustive surface registry**

```bash
git add frontend/components/agents/agent-build/builder-surface-registry.ts frontend/components/agents/agent-build/__tests__/builder-surface-registry.test.ts
git commit -m "test: enforce builder surface mapping"
```

---

## Task 8: Refresh Architecture Documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE_CN.md`
- Modify: `docs/architecture-diagram.mmd`

- [ ] **Step 1: Replace stale architecture terms in English doc**

In `docs/ARCHITECTURE.md`, update the top architecture diagram and data-flow sections so they use these current terms:

```markdown
REST["REST APIs<br/>Auth/Agents/Versions/Releases/Tasks/Threads"]
WS["WebSocket<br/>Executions/Notifications/OpenClaw"]
ExecWS["Execution WebSocket<br/>/ws/executions"]
DispatchSvc["DispatchService"]
Orchestrator["ExecutionOrchestrator<br/>service layer"]
EngineRegistry["EngineRegistry<br/>runtime_kind -> engine"]
```

Replace stale bullets:

```markdown
- **WebSocket (`/ws/runs`)**: Real-time run observation — event replay and status updates for active agent runs
- **SSE Stream**: Real-time execution status, streaming output, node execution events
```

with:

```markdown
- **WebSocket (`/ws/executions`)**: Execution snapshot, replay, live events, and observation frames.
- **Execution events**: All engines emit through `ExecutionContext.emit()` into `execution_events`; WebSocket subscribers receive persisted and live events from the same source.
```

Replace stale `GraphService` workflow references with:

```markdown
AgentVersion.definition_payload stores visual graph, code, or CLI-backed definitions. Execution starts through `DispatchService -> ExecutionOrchestrator -> EngineRegistry -> ExecutionEngine`.
```

- [ ] **Step 2: Replace stale architecture terms in Chinese doc**

In `docs/ARCHITECTURE_CN.md`, make the equivalent replacements:

```markdown
REST["REST APIs<br/>Auth/Agents/Versions/Releases/Tasks/Threads"]
WS["WebSocket<br/>Executions/Notifications/OpenClaw"]
ExecWS["执行 WebSocket<br/>/ws/executions"]
DispatchSvc["DispatchService"]
Orchestrator["ExecutionOrchestrator<br/>服务层编排"]
EngineRegistry["EngineRegistry<br/>runtime_kind -> engine"]
```

Replace stale bullets with:

```markdown
- **WebSocket (`/ws/executions`)**：执行快照、事件回放、实时事件和 observation 帧。
- **执行事件**：所有引擎通过 `ExecutionContext.emit()` 写入 `execution_events`；WebSocket 订阅者从同一来源接收历史和实时事件。
```

Add this sentence near the graph definition section:

```markdown
Graph 现在只是 `AgentVersion.definition_kind = "graph"` 的一种 definition payload，不再是顶层产品模型。
```

- [ ] **Step 3: Update Mermaid architecture diagram**

In `docs/architecture-diagram.mmd`, replace old nodes:

```text
RUN_WS["RunWsClient\n/ws/runs"]
REST["/v1  REST Endpoints\nChat · Runs · Graphs · Skills\nModels · Tools · Workspaces"]
GRAPH_SVC["GraphService\nTemplate · Deploy\n& Lookup"]
RUN_SVC["RunService\nEvent Sourcing\nRun · Event · Snapshot"]
```

with:

```text
EXEC_WS["ExecutionWsClient\n/ws/executions"]
REST["/v1 REST Endpoints\nAgents · Versions · Releases\nTasks · Threads · Runs · Executions"]
DISPATCH_SVC["DispatchService\nAPI-facing execution entry"]
ORCH_SVC["ExecutionOrchestrator\nRun · Execution · Engine dispatch"]
ENGINE_REG["EngineRegistry\nruntime_kind -> engine"]
```

Ensure diagram edges route execution flow through `DISPATCH_SVC -> ORCH_SVC -> ENGINE_REG`.

- [ ] **Step 4: Verify stale terms are removed from product architecture docs**

Run:

```bash
rg -n "GraphService|/ws/runs|SSE Stream|Graphs/Chat|RunWsClient" docs/ARCHITECTURE.md docs/ARCHITECTURE_CN.md docs/architecture-diagram.mmd
```

Expected: no matches.

- [ ] **Step 5: Commit architecture docs refresh**

```bash
git add docs/ARCHITECTURE.md docs/ARCHITECTURE_CN.md docs/architecture-diagram.mmd
git commit -m "docs: refresh architecture for agent execution model"
```

---

## Task 9: Run Focused Verification

**Files:**
- No code changes unless verification reveals a failure from prior tasks.

- [ ] **Step 1: Run backend architecture tests**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev pytest backend/tests/test_core/test_architecture_contracts.py backend/tests/test_services/test_execution_orchestrator_boundary.py backend/tests/test_core/test_http_error_contract.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend architecture tests**

Run:

```bash
cd frontend && bun test types/__tests__/architecture-contracts.test.ts components/agents/agent-build/__tests__/builder-surface-registry.test.ts components/editors/graph-builder/services/__tests__/visualDefinitionAdapter.test.ts components/editors/graph-builder/services/__tests__/graphDataAdapter.test.ts components/editors/graph-builder/utils/__tests__/saveManager.test.ts
```

Expected: PASS.

- [ ] **Step 3: Run backend type/import smoke check**

Run:

```bash
SECRET_KEY=test-secret uv run --project backend --dev python - <<'PY'
from app.services.dispatch_service import DispatchService
from app.services.execution_orchestrator import ExecutionOrchestrator
from app.core.engine import engine_registry

assert DispatchService is not None
assert ExecutionOrchestrator is not None
assert set(engine_registry.list_kinds()) >= {"sandbox", "graph", "code", "copilot"}
print("architecture import smoke ok")
PY
```

Expected output:

```text
architecture import smoke ok
```

- [ ] **Step 4: Run frontend type check**

Run:

```bash
cd frontend && bun run type-check
```

Expected: PASS.

- [ ] **Step 5: Run final stale-term checks**

Run:

```bash
rg -n "app\\.core\\.engine\\.orchestrator|GraphService|/ws/runs|SSE Stream|RunWsClient" backend/app docs/ARCHITECTURE.md docs/ARCHITECTURE_CN.md docs/architecture-diagram.mmd
```

Expected: no matches.

- [ ] **Step 6: Commit any verification fixes**

If Step 1-5 required fixes, commit them:

```bash
git add backend frontend docs
git commit -m "fix: stabilize architecture hardening verification"
```

If no fixes were required, do not create an empty commit.

---

## Self-Review Checklist

### Spec Coverage

- Backend layering: Task 2.
- Canonical contracts: Tasks 1 and 5.
- Engine capabilities: Task 3.
- Frontend visual boundary: Task 6.
- Builder surface registry: Task 7.
- Event sequencing risk: Task 4.
- Documentation refresh: Task 8.
- Focused verification: Task 9.

### Implementation Notes

- Keep commits task-sized.
- Do not rename ReactFlow-internal graph vocabulary unless the name crosses the Agent/Version product boundary.
- Do not add compatibility endpoints for deleted graph APIs.
- Prefer structured app errors over raw exceptions for capability gaps.
- If a verification command fails because dependencies are missing, run the existing project install command instead of editing source around missing dependencies.
