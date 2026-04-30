# Agent Kind Refactor: EngineKind + RuntimeKind

## Problem

The current agent "kind" system uses three confusing, overlapping concepts:

- `DefinitionKindLiteral = Literal["graph", "code", "sandbox_cli"]` — what engine built the agent
- `RuntimeKindLiteral = Literal["graph", "code", "sandbox"]` — where the agent runs
- `executor_kind` (on Execution) — the actual CLI tool (`claude_code`, `codex`, `openclaw`)

Problems:
1. `"sandbox_cli"` mixes runtime (sandbox) and definition (cli) concepts
2. `definition_kind → runtime_kind` mapping is identity for graph/code, confusing why two concepts exist
3. `executor_kind` is a hidden third layer that carries the real engine identity for CLI agents
4. `CLIEngine` + `RuntimeProviderRegistry` adds unnecessary dispatch indirection

## Design: Two Orthogonal Axes

### Axis 1: EngineKind — what kernel builds the agent

```python
EngineKind = Literal[
    "langgraph_visual",   # LangGraph visual builder
    "langgraph_code",     # LangGraph code
    "claude_code",        # Claude Code CLI
    "codex",              # Codex CLI
    "openclaw",           # OpenClaw CLI
]
ENGINE_KINDS: set[str] = {"langgraph_visual", "langgraph_code", "claude_code", "codex", "openclaw"}

InternalEngineKind = Literal["build_copilot"]
INTERNAL_ENGINE_KINDS: set[str] = {"build_copilot"}

AllEngineKind = Union[EngineKind, InternalEngineKind]
ALL_ENGINE_KINDS: set[str] = ENGINE_KINDS | INTERNAL_ENGINE_KINDS
```

### Axis 2: RuntimeKind — where the agent runs

```python
RuntimeKind = Literal["sandbox", "server"]
RUNTIME_KINDS: set[str] = {"sandbox", "server"}
```

### Mapping

```python
ENGINE_RUNTIME_MAP: dict[str, str] = {
    "langgraph_visual": "server",
    "langgraph_code":   "server",
    "claude_code":      "sandbox",
    "codex":            "sandbox",
    "openclaw":         "sandbox",
}

CLI_ENGINE_KINDS: set[str] = {"claude_code", "codex", "openclaw"}
```

## Concept Elimination

| Old | New |
|---|---|
| `DefinitionKindLiteral` | `EngineKind` |
| `RuntimeKindLiteral` | `RuntimeKind` |
| `DEFINITION_KINDS` | `ENGINE_KINDS` |
| `CLI_DEFINITION_KINDS` | `CLI_ENGINE_KINDS` |
| `DEFINITION_RUNTIME_KIND` | `ENGINE_RUNTIME_MAP` |
| `"graph"` (definition) | `"langgraph_visual"` |
| `"code"` (definition) | `"langgraph_code"` |
| `"sandbox_cli"` | eliminated |
| `"graph"` / `"code"` (runtime) | `"server"` |
| `executor_kind` (column) | `engine_kind` |

## Engine Registry

Each engine kind maps to its own `ExecutionEngine` implementation. No intermediate dispatch layer.

```python
engine_registry.register("langgraph_visual", LangGraphVisualEngine())
engine_registry.register("langgraph_code",   LangGraphCodeEngine())
engine_registry.register("claude_code",      ClaudeCodeEngine())
engine_registry.register("codex",            CodexEngine())
engine_registry.register("openclaw",         OpenClawEngine())
engine_registry.register("build_copilot",    CopilotEngine())
```

### Eliminated layers

- `CLIEngine` — deleted. Each CLI tool is a first-class engine.
- `RuntimeProviderRegistry` + `ClaudeCodeProvider` / `CodexProvider` / `OpenClawProvider` — promoted to engines.
- `core/agent/cli_backends/registry.py` — deleted.

### Engine renames

| Old | New |
|---|---|
| `GraphEngine` | `LangGraphVisualEngine` |
| `CodeEngine` | `LangGraphCodeEngine` |
| `CLIEngine` | eliminated |
| `ClaudeCodeProvider` | `ClaudeCodeEngine` (implements `ExecutionEngine`) |
| `CodexProvider` | `CodexEngine` (implements `ExecutionEngine`) |
| `OpenClawProvider` | `OpenClawEngine` (implements `ExecutionEngine`) |

## Database Migration

```sql
-- 1. AgentVersion: rename column + remap values
ALTER TABLE agent_versions RENAME COLUMN definition_kind TO engine_kind;
UPDATE agent_versions SET engine_kind = 'langgraph_visual' WHERE engine_kind = 'graph';
UPDATE agent_versions SET engine_kind = 'langgraph_code'   WHERE engine_kind = 'code';
UPDATE agent_versions av SET engine_kind = (
    SELECT COALESCE(
        (SELECT rv.runtime_binding->>'runtime_type'
         FROM agent_releases rv
         WHERE rv.agent_version_id = av.id
         LIMIT 1),
        'claude_code'
    )
) WHERE av.engine_kind = 'sandbox_cli';

-- 2. AgentRelease: remap runtime_kind values
UPDATE agent_releases SET runtime_kind = 'server' WHERE runtime_kind IN ('graph', 'code');

-- 3. Execution: rename column (values already correct)
ALTER TABLE executions RENAME COLUMN executor_kind TO engine_kind;
```

## Frontend Types

```typescript
export const ENGINE_KINDS = [
  'langgraph_visual', 'langgraph_code',
  'claude_code', 'codex', 'openclaw'
] as const
export type EngineKind = (typeof ENGINE_KINDS)[number]

export const RUNTIME_KINDS = ['sandbox', 'server'] as const
export type RuntimeKind = (typeof RUNTIME_KINDS)[number]
```

## Affected Files

| Module | Change |
|---|---|
| `core/contracts/agent.py` | Rewrite types, constants, utility functions |
| `models/agent.py` | `definition_kind` → `engine_kind`, remove `normalize_*` |
| `models/agent_run.py` | `executor_kind` → `engine_kind` |
| `schemas/agent.py` | `DefinitionKindLiteral` → `EngineKind` |
| `schemas/agent_version.py` | same |
| `schemas/agent_release.py` | `RuntimeKindLiteral` → `RuntimeKind` |
| `services/agent_publish_service.py` | Use `ENGINE_RUNTIME_MAP` |
| `services/execution_orchestrator.py` | Route by `engine_kind` directly |
| `core/engine/__init__.py` | Register by `engine_kind` |
| `core/engine/protocol.py` | Align with new enums |
| `core/agent/cli_backends/` | Delete `registry.py`, promote providers to engines |
| `frontend/types/agent.ts` | New types |
| `frontend/` components | Update all references |
| Alembic | New migration script |
