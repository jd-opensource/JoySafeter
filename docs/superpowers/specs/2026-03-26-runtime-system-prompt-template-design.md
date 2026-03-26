# Runtime System Prompt Template Design

## Goal

Replace the current one-off `{thread_id}` substitution with a general runtime template system for graph node system prompts.

The new system should support many dynamic variables, keep the existing `{var_name}` prompt style, and avoid introducing a second template DSL such as LangSmith-specific formats, Jinja, or Mustache.

## Status

Proposed on 2026-03-26.

## Context

The current implementation has two problems:

- Runtime substitution is effectively hardcoded around `thread_id`
- Prompt rendering logic is fragmented across builder and executor code paths

That is sufficient for the current Skill Creator prompt, but it does not scale to other runtime values such as `user_id`, `graph_id`, `workspace_id`, `graph_name`, or graph-defined custom context variables.

The user confirmed these requirements:

- Prompt syntax remains `{var_name}`
- `graph.variables.context` variables must be supported
- `graph.variables.context` may override built-in runtime fields
- Missing variables must remain unchanged in the rendered prompt

## Scope

**In scope:**

- General runtime template rendering for node system prompts
- A unified runtime prompt context assembled during graph build
- Support for built-in runtime variables and graph-defined custom context variables
- Consistent behavior across standard graph execution and DeepAgents execution
- Tests covering merge order, missing variables, and builder/executor consistency

**Out of scope:**

- Rendering user messages or tool inputs as templates
- Supporting LangSmith Playground prompt template features
- Jinja, Mustache, or expression-based template syntax
- Nested paths such as `{user.id}`
- Conditional logic, loops, filters, or function calls in prompts

## Template Semantics

### Supported syntax

Only simple placeholders are supported:

```text
{thread_id}
{workspace_id}
{target_repo}
```

Supported variable names are identifier-like keys. The initial implementation should allow letters, digits, and underscores, with the first character restricted to a letter or underscore.

### Unsupported syntax

These are intentionally not supported:

```text
{user.id}
{vars["name"]}
{a + b}
{{mustache}}
{% if condition %}
```

If unsupported forms appear in a prompt, they are treated as literal text unless they incidentally match the simple placeholder pattern.

### Missing variables

If a placeholder has no runtime value, it stays unchanged:

```text
"Hello {missing_value}" -> "Hello {missing_value}"
```

This avoids surprising failures at runtime and preserves backward compatibility for prompts that include placeholders not available in a given execution context.

## Runtime Prompt Context

System prompt rendering should use a single merged context object, referred to here as `runtime_prompt_context`.

### Built-in fields

The initial built-in fields are:

- `thread_id`
- `user_id`
- `graph_id`
- `workspace_id`
- `graph_name`

Additional built-in fields may be added later without changing prompt syntax.

### Graph-defined custom fields

If `graph.variables.context` exists, its key-value pairs are merged into `runtime_prompt_context`.

Example:

```json
{
  "variables": {
    "context": {
      "target_repo": "acme/backend",
      "customer_name": "Acme Corp"
    }
  }
}
```

These become available as:

- `{target_repo}`
- `{customer_name}`

### Merge order

Merge order is explicit:

1. Start with built-in runtime fields
2. Merge `graph.variables.context`

This means graph-defined custom fields can override built-in fields.

Example:

```json
{
  "context": {
    "thread_id": "demo-thread"
  }
}
```

If present, `{thread_id}` renders to `demo-thread`, not the actual conversation thread id.

This behavior is intentional because the user explicitly requested graph variables to have final precedence.

## Architecture

### Single rendering entry point

Introduce one shared rendering function:

```python
render_runtime_template(text: str | None, context: Mapping[str, Any]) -> str | None
```

Responsibilities:

- Replace only simple `{var_name}` placeholders
- Convert non-string values to strings
- Leave unknown placeholders unchanged
- Return `None` unchanged

This function should be pure and reusable.

### Builder-owned context assembly

`BaseGraphBuilder` should assemble `runtime_prompt_context` once from graph metadata and runtime state.

This context should be stored on the builder and reused by all prompt rendering calls during that build.

Recommended helper structure:

```python
_build_runtime_prompt_context() -> dict[str, Any]
_render_runtime_template(text: str | None) -> str | None
```

### Single system prompt resolution path

All node executors must obtain system prompts through the builder-backed rendering path when a builder is available.

There must not be a second code path that reads raw `systemPrompt` directly from node config and bypasses rendering.

This is required so that:

- standard agent nodes
- DeepAgents root nodes
- DeepAgents worker nodes

all see the same rendered system prompt for the same graph and runtime context.

## Data Sources

### Runtime execution sources

The runtime prompt context should be assembled from values already available during graph construction:

- request/runtime values from websocket execution, including `thread_id` and `user_id`
- graph model values, including `graph.id`, `graph.name`, and `graph.workspace_id`
- `graph.variables.context`

No new persistence layer is required for this design.

### Null handling

If a built-in field is absent, omit it from the context rather than forcing `"None"` into prompts.

That keeps missing placeholders stable and consistent with the chosen rule of leaving unresolved placeholders unchanged.

## Caching and Correctness

Compiled graph caching must not cause prompts to render with stale runtime values.

Today graph compilation may be cached by `(graph_id, updated_at)`. Runtime-rendered prompts depend on execution-specific context, especially `thread_id`.

Therefore, one of these must be true:

- runtime prompt rendering happens after cache lookup on a builder instance that still has current runtime context
- or the compile cache key includes all runtime values that affect prompt rendering

The preferred approach is to keep template rendering runtime-aware and avoid broadening the compile cache key unless necessary.

Any implementation that allows cached compiled graphs to reuse old rendered prompt values is incorrect.

## Testing

Add focused tests for:

- rendering built-in variables in system prompts
- rendering custom `graph.variables.context` variables
- custom variables overriding built-in values
- missing variables remaining unchanged
- standard agent executor using the same rendered prompt as builder
- DeepAgents config path using the same rendered prompt as builder
- repeated executions of the same graph with different runtime contexts not leaking values across runs

## Migration and Compatibility

This design is backward compatible with existing prompts that already use `{thread_id}`.

No frontend prompt schema migration is required because the placeholder syntax does not change.

The only behavioral expansion is that more runtime variables become available, and graph-defined context variables can now participate in system prompt rendering.

## Open Questions

There are no open product questions blocking implementation.

Future enhancements that are intentionally deferred:

- support for nested path lookup such as `{customer.name}`
- support for rendering other prompt-bearing config fields beyond system prompt
- validation or linting for unresolved placeholders in the graph editor
