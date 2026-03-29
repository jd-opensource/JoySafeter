# DSL Code Editor — Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Scope:** Replace standard canvas graph editing with a Python DSL code editor. DeepAgents canvas mode is preserved unchanged.

---

## 1. Problem Statement

The current canvas-based graph builder has accumulated significant complexity:

- Three representation layers (ReactFlow nodes/edges → DB JSONB → GraphSchema → LangGraph) with lossy conversions at each boundary
- Frontend `dataMigration.ts` patching field name inconsistencies (`routeKey` → `route_key`, `output_map` → `output_mapping`, etc.)
- State schema management split across four UI surfaces with no single source of truth
- `stateReads`/`stateWrites` on node.data never populated by `addNode`, causing schema export to always emit empty arrays

The DSL approach eliminates the first two layers. Code is the source of truth. The backend parses it into `GraphSchema` and executes via the existing `GraphCompiler`.

---

## 2. Goals

- Users define graphs in Python code that closely mirrors LangGraph native syntax
- Real-time canvas preview reflects code structure (read-only)
- Run button compiles and executes via existing backend pipeline
- Old canvas graphs are migrated to code via existing `code_generator.py`
- DeepAgents canvas mode is fully preserved

## 3. Non-Goals

- Arbitrary Python execution (no sandbox/kernel — code is parsed, not run directly)
- Supporting dynamic node generation (e.g. nodes created in loops at parse time)
- Modifying the DeepAgents builder or canvas
- Jupyter-style cell execution

---

## 4. Architecture Overview

```
Frontend Monaco Editor (Python)
        │
        │ debounce 500ms
        ▼
POST /v1/graphs/{id}/code/parse
        │
        ▼
DSLParser  ──── Python ast module (static analysis)
        │        extracts: state / nodes / edges / inline_code
        ▼
GraphSchema (existing Pydantic model)
        │
        ├──► returned to frontend → read-only canvas preview
        │
        └──► on Run: GraphCompiler.compile_from_schema() → LangGraph → execute
```

**Key principle:** `DSLParser` is the only new core module. Everything downstream is reused unchanged.

**Run path for DSL graphs:** The existing run path (`RunService` → `GraphBuilder` → `LanggraphModelBuilder`) requires DB-backed `GraphNode` rows to construct executors. DSL graphs bypass this path entirely. A new `DSLRunService` re-parses the saved `dsl_code`, produces a `GraphSchema`, and calls `GraphCompiler.compile_from_schema()` directly — skipping `GraphBuilder` and the DB node lookup. The `RunService` dispatches to `DSLRunService` when `graph.variables.graph_mode == "dsl"`.

---

## 5. DSL Syntax

### 5.1 Imports

```python
from joysafeter.nodes import agent, condition, router, fn, http, direct_reply
from joysafeter import JoyGraph, GraphState
from langgraph.graph import START, END
from typing import Annotated
import operator
```

### 5.2 State Definition

Users subclass `GraphState` using native Python TypedDict syntax:

```python
class MyState(GraphState):
    messages: Annotated[list, operator.add]   # built-in reducer
    score: int
    context: dict
    history: Annotated[list, operator.add]    # append reducer
```

`GraphState` is a base class exported from `joysafeter` that maps to the backend `GraphState` TypedDict. The parser identifies `class X(GraphState)` and extracts field names, types, and reducers via AST annotation inspection.

### 5.3 Built-in Node Types

Node factory functions return `NodeDef` objects that the parser can identify statically:

```python
# Agent node
classifier = agent(
    model="deepseek",
    system_prompt="Classify the user intent",
    tools=["search", "calculator"],
)

# Condition node (binary true/false)
gate = condition(expression="state.get('score', 0) > 80")

# Router node (multi-route)
dispatch = router(
    routes=[
        ("state.get('score') > 90", "vip"),
        ("state.get('score') > 60", "standard"),
    ],
    default="fallback",
)

# Direct reply
sorry = direct_reply(template="Sorry, score too low.")

# HTTP request
fetch = http(
    method="GET",
    url="https://api.example.com/data",
    input_mapping={"query": "state.get('context', {}).get('query')"},
)
```

### 5.4 Inline Function Nodes

Custom logic uses a native async function with `@fn` decorator:

```python
@fn(writes=["score"])
async def scorer(state: MyState):
    messages = state.get("messages", [])
    last = messages[-1].content if messages else ""
    score = len(last) % 100
    return {"score": score}
```

The parser extracts the function body as a code string and stores it in `NodeSchema.config.code`. At execution time, `FunctionNodeExecutor` runs it in the existing sandbox.

### 5.5 Graph Structure

Graph wiring uses native LangGraph API via `JoyGraph` (thin wrapper around `StateGraph`):

```python
g = JoyGraph(MyState)

g.add_node("classifier", classifier)
g.add_node("gate", gate)
g.add_node("scorer", scorer)
g.add_node("sorry", sorry)

g.add_edge(START, "classifier")
g.add_edge("classifier", "gate")

g.add_conditional_edges("gate", lambda s: s.get("route_decision"), {
    "true": "scorer",
    "false": "sorry",
})

g.add_edge("scorer", END)
g.add_edge("sorry", END)
```

### 5.6 Complete Example

```python
from joysafeter.nodes import agent, condition, fn, direct_reply
from joysafeter import JoyGraph, GraphState
from langgraph.graph import START, END
from typing import Annotated
import operator

class MyState(GraphState):
    messages: Annotated[list, operator.add]
    score: int

classifier = agent(
    model="deepseek",
    system_prompt="Classify intent and estimate a score 0-100",
)

gate = condition(expression="state.get('score', 0) > 80")

@fn(writes=["score"])
async def scorer(state: MyState):
    return {"score": 85}

sorry = direct_reply(template="Score too low, try again.")

g = JoyGraph(MyState)
g.add_node("classifier", classifier)
g.add_node("gate", gate)
g.add_node("scorer", scorer)
g.add_node("sorry", sorry)

g.add_edge(START, "classifier")
g.add_edge("classifier", "gate")
g.add_conditional_edges("gate", lambda s: s.get("route_decision"), {
    "true": "scorer",
    "false": "sorry",
})
g.add_edge("scorer", END)
g.add_edge("sorry", END)
```

---

## 6. Backend Design

### 6.1 New Files

```
backend/app/core/dsl/
├── __init__.py
├── dsl_models.py       # Intermediate parse structures
├── dsl_parser.py       # AST visitor → GraphSchema
└── dsl_validator.py    # Post-parse semantic validation

backend/app/api/v1/
└── graph_code.py       # Two new API endpoints

backend/app/joysafeter/  # Thin SDK (importable by user code for type hints only)
├── __init__.py          # JoyGraph, GraphState
└── nodes.py             # agent, condition, router, fn, http, direct_reply
```

### 6.2 DSL Models

```python
# dsl_models.py

@dataclass
class ParsedStateField:
    name: str
    field_type: str        # "int", "str", "list", "dict", "messages"
    reducer: str | None    # "add", "append", "merge", None

@dataclass
class ParsedNode:
    var_name: str          # Python variable name (e.g. "classifier")
    node_type: str         # "agent", "condition", "router", "fn", "http", etc.
    kwargs: dict           # extracted keyword arguments
    inline_code: str | None  # for @fn nodes only

@dataclass
class ParsedEdge:
    source: str            # node string name or "START"
    target: str            # node string name or "END"
    route_key: str | None  # for conditional edges; None for normal edges

# NOTE: g.add_conditional_edges("gate", fn, {"true": "scorer", "false": "sorry"})
# produces TWO ParsedEdge instances — one per mapping entry:
#   ParsedEdge(source="gate", target="scorer", route_key="true")
#   ParsedEdge(source="gate", target="sorry",  route_key="false")
# The visitor iterates the dict literal and emits one ParsedEdge per key-value pair.

@dataclass
class ParseResult:
    state_fields: list[ParsedStateField]
    nodes: list[ParsedNode]
    edges: list[ParsedEdge]
    graph_var: str | None  # variable name of JoyGraph instance
    entry_node: str | None
    errors: list[ParseError]
```

### 6.3 DSLParser

Node IDs in DSL-produced `GraphSchema` use the string name from `g.add_node("name", var)` — not UUIDs. `GraphCompiler.compile_from_schema()` already accepts string IDs (it uses `node.id` as the LangGraph node name directly). The `_to_uuid()` helper in the compiler is only used for DB-backed paths; `compile_from_schema()` does not call it. DSL schemas never pass through `_create_executors_via_builder` — they go directly to `compile_from_schema()` via `DSLRunService`.

**Factory function name → NodeSchema.type mapping** (factory name ≠ type string):

| DSL factory call | `NodeSchema.type` passed to compiler |
|-----------------|--------------------------------------|
| `agent(...)` | `"agent"` |
| `condition(...)` | `"condition"` |
| `router(...)` | `"router_node"` |
| `fn(...)` | `"function_node"` |
| `http(...)` | `"http_request_node"` |
| `direct_reply(...)` | `"direct_reply"` |
| `human_input(...)` | `"human_input"` |
| `tool(...)` | `"tool_node"` |

The `_DSLVisitor` applies this mapping when constructing `ParsedNode.node_type`.

```python
# dsl_parser.py

_FACTORY_TO_NODE_TYPE = {
    "agent": "agent",
    "condition": "condition",
    "router": "router_node",
    "fn": "function_node",
    "http": "http_request_node",
    "direct_reply": "direct_reply",
    "human_input": "human_input",
    "tool": "tool_node",
}

class DSLParser:
    def parse(self, code: str) -> ParseResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ParseResult(errors=[ParseError(line=e.lineno, message=str(e))])

        visitor = _DSLVisitor(source=code)  # source passed for ast.get_source_segment
        visitor.visit(tree)
        return visitor.result

class _DSLVisitor(ast.NodeVisitor):
    def __init__(self, source: str):
        self._source = source   # needed by ast.get_source_segment for @fn body extraction
        self.result = ParseResult(...)

    def visit_ClassDef(self, node: ast.ClassDef):
        # Detect: class X(GraphState)
        # Extract field annotations → ParsedStateField list

    def visit_Assign(self, node: ast.Assign):
        # Detect: x = agent(...) / condition(...) / router(...) / http(...) / direct_reply(...)
        # → ParsedNode via _FACTORY_TO_NODE_TYPE mapping
        # Detect: g = JoyGraph(StateClass) → record graph_var and state class name
        # NOTE: JoyGraph detection is here (Assign), NOT in visit_Expr

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        # Detect: @fn(...) decorated async def
        # Extract: function name, @fn kwargs
        # Extract inline code: ast.get_source_segment(self._source, node)

    def visit_Expr(self, node: ast.Expr):
        # Detect bare expression statements only:
        # g.add_node("name", var) → register string name → ParsedNode mapping
        # g.add_edge(src, tgt) → ParsedEdge(source, target, route_key=None)
        #   - src/tgt may be ast.Name(id='START'/'END') or ast.Constant(value='name')
        #   - START/END edges are recorded as ParsedEdge with source/target="START"/"END"
        #   - _build_schema() drops these (not emitted as EdgeSchema rows)
        # g.add_conditional_edges(src, fn, {"key": "target", ...})
        #   → one ParsedEdge per mapping entry (route_key = dict key)
        #   - dict values may be ast.Constant(value='node_name') OR ast.Name(id='END')
        #   - ast.Name(id='END') is treated as target="END" and dropped by _build_schema()
        #   - ast.Name(id='START') is treated as target="START" (unusual but handled)
```

### 6.4 Schema Builder

After visiting, `DSLParser._build_schema()` converts `ParseResult` → `GraphSchema`:

**Node ID strategy:** `_build_schema()` sets both `NodeSchema.id` and `NodeSchema.label` to the string name from `g.add_node("name", var)`. This ensures `GraphCompiler._precompute_maps()` derives the LangGraph node name from `node.label` (which equals `node.id`), and `validate_edge_references` passes because `EdgeSchema.source`/`target` use the same string names.

```python
# _build_schema() node construction
for name, parsed_node in name_to_node.items():
    node_schema = NodeSchema(
        id=name,       # string name, e.g. "classifier"
        label=name,    # same — ensures compiler derives correct LangGraph name
        type=parsed_node.node_type,
        config={**parsed_node.kwargs},
    )
    if parsed_node.inline_code:
        node_schema.config["code"] = parsed_node.inline_code
```

**START/END edge handling:** `_build_schema()` does NOT emit `EdgeSchema` rows for `add_edge(START, x)` or `add_edge(x, END)` calls. These are dropped. The compiler's `_build_start_end_edges()` derives entry/exit nodes from topology (`get_start_nodes()` = nodes with no incoming edges, `get_end_nodes()` = nodes with no outgoing edges). The node referenced in `add_edge(START, x)` simply has no incoming `EdgeSchema` rows, so it is naturally identified as the start node.

**`ParsedNode.var_name` vs string name:** `visit_Assign` records `var_name → ParsedNode`. `visit_Expr` for `g.add_node("name", var)` resolves `var` back to its `ParsedNode` via `var_name` lookup and registers `"name" → ParsedNode`. Only the string name is used in `NodeSchema.id`; `var_name` is an internal parser detail.

**Remaining conversions:**
- `ParsedStateField` → `StateFieldSchema`
- `ParsedEdge` (non-START/END) → `EdgeSchema`

**DSL v1 supported node types** (factory functions with DSL equivalents):

| Factory | NodeSchema.type |
|---------|----------------|
| `agent` | `agent` |
| `condition` | `condition` |
| `router` | `router_node` |
| `fn` | `function_node` |
| `http` | `http_request_node` |
| `direct_reply` | `direct_reply` |
| `human_input` | `human_input` |
| `tool` | `tool_node` |

**Out of scope for DSL v1** (no factory function, migration will skip graphs using these):

| NodeSchema.type | Status |
|----------------|--------|
| `loop_condition_node` | Deferred to v2 — complex loop semantics require dedicated DSL syntax |
| `aggregator_node` | Deferred to v2 |
| `json_parser_node` | Deferred to v2 |
| `get_state_node` | Deferred to v2 |
| `set_state_node` | Deferred to v2 |
| `code_agent` | Deferred to v2 |

Graphs using out-of-scope node types remain in `graph_mode: "canvas"` after migration and are added to the manual review queue. They continue to work unchanged.

### 6.5 DSLValidator

Post-parse semantic checks:

- All nodes referenced in edges are defined
- **Duplicate node string names** — error (duplicate names cause silent edge-wiring failures in `_precompute_maps` due to `_unique_name` deduplication suffix)
- Entry point exists (at least one node has no incoming edges)
- Conditional edge route keys match node type expectations (condition → "true"/"false")
- No orphaned nodes (defined but never connected)
- `@fn` inline code is syntactically valid Python

### 6.6 New API Endpoints

```python
# graph_code.py

POST /v1/graphs/{graph_id}/code/parse
  Request:  { "code": "from joysafeter..." }
  Response: {
    "schema": GraphSchema,
    "preview": { "nodes": [...], "edges": [...] },  # ReactFlow-ready
    "errors": [{ "line": 5, "message": "...", "severity": "error|warning" }]
  }
  Notes: stateless, does not persist anything

POST /v1/graphs/{graph_id}/code/save
  Request:  { "code": "from joysafeter...", "name": "My Graph" }
  Response: { "ok": true }
  Notes: saves code string to graph.variables.dsl_code
         sets graph.variables.graph_mode = "dsl"
```

**Run flow** — dispatch point is `graph_service.py:create_graph_by_graph_id()`. This is the single function called by all execution paths (`openapi_graph_service.py`, `test_service.py`, `schema_service.py`) to get a compiled graph. The `graph_mode` check is inserted here:

```python
# graph_service.py — create_graph_by_graph_id()
async def create_graph_by_graph_id(self, graph_id, ...):
    graph = await self.graph_repo.get(graph_id)

    # DSL mode: bypass GraphBuilder entirely
    if graph.variables.get("graph_mode") == "dsl":
        return await self._compile_dsl_graph(graph, ...)

    # Existing path unchanged
    nodes = await self.node_repo.list_by_graph(graph_id)
    edges = await self.edge_repo.list_by_graph(graph_id)
    builder = GraphBuilder(graph=graph, nodes=nodes, edges=edges, ...)
    return await builder.build()

async def _compile_dsl_graph(self, graph, llm_model, api_key, base_url,
                              max_tokens, user_id, model_service, ...):
    dsl_code = graph.variables.get("dsl_code", "")
    parse_result = DSLParser().parse(dsl_code)
    if parse_result.errors:
        raise DSLParseError(parse_result.errors)

    schema = DSLParser().build_schema(parse_result)
    executor_map = await DSLExecutorBuilder(
        schema, model_service, user_id, llm_model, api_key, base_url, max_tokens
    ).build_executors()

    result = await compile_from_schema(
        schema,
        executor_map=executor_map,
        checkpointer=get_checkpointer(),
    )
    return result.compiled_graph
```

**Required change to `compile_from_schema` / `_CompilerSession`:**

`compile_from_schema` gains an optional `executor_map` parameter:

```python
async def compile_from_schema(
    schema: GraphSchema,
    *,
    builder: Any = None,
    executor_map: dict[str, Any] | None = None,  # NEW
    checkpointer: Any = None,
    validate: bool = True,
) -> CompilationResult:
    session = _CompilerSession(schema, builder, executor_map, checkpointer, validate)
    return await session.compile()
```

`_CompilerSession.__init__` stores `executor_map`. `_create_executors_and_nodes` branches on it:

```python
async def _create_executors_and_nodes(self):
    fallback_node_name = self.node_name_map.get(self.schema.fallback_node_id) \
        if self.schema.fallback_node_id else None

    if self.executor_map is not None:
        # DSL path: use pre-built executor map
        self.executors = self.executor_map
        for node in self.schema.nodes:
            name = self.node_name_map[node.id]
            executor = self.executors.get(node.id)
            if executor:
                wrapped = NodeExecutionWrapper(
                    executor, node_id=node.id, node_type=node.type,
                    metadata=node.metadata, node_config=node.config,
                    fallback_node_name=fallback_node_name \
                        if node.id != self.schema.fallback_node_id else None,
                )
                self.workflow.add_node(name, wrapped)
    elif self.builder is not None:
        # Existing path unchanged
        self.executors = await _create_executors_via_builder(...)
        ...
    else:
        # Stub path (validation only)
        ...
```

`_build_conditional_edges` and `_compile_workflow` already branch on `self.builder is not None`. With `executor_map`, `self.builder` remains `None`, so those branches are skipped. `_build_conditional_edges` must be updated to also fire when `self.executor_map is not None`:

```python
def _build_conditional_edges(self):
    if self.builder is None and self.executor_map is None:
        return
    # rest of method unchanged
```

`_compile_workflow` similarly:

```python
def _compile_workflow(self):
    if self.checkpointer is None and (self.builder is not None or self.executor_map is not None):
        self.checkpointer = get_checkpointer()
    return self.workflow.compile(checkpointer=self.checkpointer)
```

**`DSLExecutorBuilder` — executor construction approach:**

Each executor constructor takes a `GraphNode` ORM object. Rather than adding `from_schema` classmethods to every executor, `DSLExecutorBuilder._create_executor` constructs a lightweight shim that satisfies the `node.data["config"]` access pattern:

```python
class _NodeSchemaShim:
    """Minimal shim satisfying GraphNode.data["config"] access for executor constructors."""
    def __init__(self, node: NodeSchema):
        self.id = node.id
        self.type = node.type
        self.data = {"config": node.config, "label": node.label}
        self.config = node.config  # direct access alias

async def _create_executor(self, node: NodeSchema) -> Any:
    shim = _NodeSchemaShim(node)
    node_id = node.id

    if node.type == "condition":
        return ConditionNodeExecutor(shim, node_id)
    elif node.type == "direct_reply":
        return DirectReplyNodeExecutor(shim, node_id)
    elif node.type == "router_node":
        return RouterNodeExecutor(shim, node_id)
    elif node.type == "human_input":
        return HumanInputNodeExecutor(shim, node_id)
    elif node.type == "tool_node":
        return ToolNodeExecutor(shim, node_id, ...)
    elif node.type == "http_request_node":
        return HttpRequestNodeExecutor(shim, node_id)
    elif node.type == "function_node":
        return FunctionNodeExecutor(shim, node_id)
    elif node.type == "agent":
        # Agent requires resolved model — same resolution as BaseGraphBuilder
        resolved_model = await self._model_service.resolve(
            node.config.get("model", self._llm_model),
            api_key=self._api_key, base_url=self._base_url,
            max_tokens=self._max_tokens, user_id=self._user_id,
        )
        return AgentNodeExecutor(
            shim, node_id,
            model=resolved_model,
            checkpointer=None,  # per-node checkpointer not needed for DSL
        )
```

The shim approach requires zero changes to existing executor classes. If a constructor accesses a `GraphNode` attribute not covered by the shim, a clear `AttributeError` will surface during testing — making gaps easy to find and fix.

### 6.7 DB Storage

No new tables. Code stored in existing `graph.variables` JSONB:

```json
{
  "graph_mode": "dsl",
  "dsl_code": "from joysafeter.nodes import agent...",
  "state_fields": [],
  "fallback_node_id": null
}
```

`graph_mode` field controls frontend routing:
- `"dsl"` → open CodeEditor
- `"canvas"` or absent → open BuilderCanvas (DeepAgents only going forward)

### 6.8 Migration of Existing Canvas Graphs

Existing `code_generator.py` generates raw LangGraph code using `StateGraph` directly — it does **not** emit DSL-compatible syntax (`JoyGraph`, `agent(...)`, `@fn`, etc.) and cannot be used as-is for migration.

A new `dsl_code_generator.py` will be written that emits DSL-compatible output. It takes the same `GraphSchema` input as `code_generator.py` but produces code that `DSLParser` can round-trip:

```python
# dsl_code_generator.py — output example
from joysafeter.nodes import agent, condition, direct_reply
from joysafeter import JoyGraph, GraphState
from langgraph.graph import START, END
from typing import Annotated
import operator

class MyGraphState(GraphState):
    messages: Annotated[list, operator.add]
    score: int

classifier = agent(
    model="deepseek",
    system_prompt="Classify intent",
)

gate = condition(expression="state.get('score', 0) > 80")

sorry = direct_reply(template="Score too low.")

g = JoyGraph(MyGraphState)
g.add_node("classifier", classifier)
g.add_node("gate", gate)
g.add_node("sorry", sorry)

g.add_edge(START, "classifier")
g.add_edge("classifier", "gate")
g.add_conditional_edges("gate", lambda s: s.get("route_decision"), {
    "true": END,
    "false": "sorry",
})
g.add_edge("sorry", END)
```

For `function_node` nodes with existing inline code in `NodeSchema.config.code`, the generator emits an `@fn`-decorated async function with the code inlined.

Migration script:

```python
for graph in all_non_deepagents_graphs:
    # Step 1: build schema from DB — catch ValidationError for malformed graphs
    try:
        schema = GraphSchema.from_db(graph, nodes, edges)
    except ValidationError as e:
        log_failure(graph.id, "schema_from_db", str(e))
        continue  # graph stays in canvas mode

    # Step 2: check for out-of-scope node types
    unsupported = {n.type for n in schema.nodes} - DSL_V1_SUPPORTED_TYPES
    if unsupported:
        log_failure(graph.id, "unsupported_node_types", list(unsupported))
        continue  # graph stays in canvas mode, added to manual review queue

    # Step 3: generate DSL code
    try:
        code = dsl_generate_code(schema)
    except Exception as e:
        log_failure(graph.id, "dsl_generate_code", str(e))
        continue

    # Step 4: verify generated code round-trips through parser
    parse_result = DSLParser().parse(code)
    if parse_result.errors:
        log_failure(graph.id, "parse_roundtrip", parse_result.errors)
        continue

    # Step 5: persist
    graph.variables["dsl_code"] = code
    graph.variables["graph_mode"] = "dsl"
    db.save(graph)
    # original graph_nodes / graph_edges rows preserved as backup
```

**Rollback:** If a migrated graph's DSL code fails to parse after migration (e.g. due to unsupported node config), the migration script logs the failure and skips that graph — it remains in `graph_mode: "canvas"` and continues to work. A manual review queue is produced for failed graphs. The validation period ends when all graphs have been successfully migrated and verified runnable.

---

## 7. Frontend Design

### 7.1 New Files

```
frontend/app/workspace/[workspaceId]/[agentId]/
├── CodeEditorPage.tsx          # Top-level page, replaces canvas layout for dsl mode
├── components/
│   ├── CodeEditor.tsx          # Monaco Editor wrapper
│   ├── CodePreviewCanvas.tsx   # Read-only ReactFlow canvas
│   └── CodeErrorPanel.tsx      # Parse error list with line links
└── stores/
    └── codeEditorStore.ts      # code string, parse result, errors, dirty state
```

### 7.2 Page Layout

```
┌─────────────────────────────────────────────────────────────┐
│  [Graph Name]  [Save]  [▶ Run]                    Toolbar   │
├────────────────────────┬────────────────────────────────────┤
│                        │                                    │
│   Monaco Editor        │   Read-only Canvas Preview         │
│   Python syntax        │   ReactFlow (no drag/drop)         │
│   highlighting         │                                    │
│                        │   Nodes reflect parsed structure   │
│   Parse errors         │   Highlighted on parse error       │
│   underlined inline    │                                    │
│                        │                                    │
├────────────────────────┴────────────────────────────────────┤
│  Error Panel: line 12: "node 'scorer' not connected"        │
├─────────────────────────────────────────────────────────────┤
│  Execution Panel (collapsed by default, expands on Run)     │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 codeEditorStore

```typescript
interface CodeEditorState {
  code: string
  savedCode: string           // last saved version
  parseResult: ParseResult | null
  parseErrors: ParseError[]
  isParsing: boolean
  isSaving: boolean
  isDirty: boolean            // code !== savedCode

  setCode: (code: string) => void
  save: () => Promise<void>
  run: () => Promise<void>
}
```

### 7.4 useCodeParse Hook

```typescript
// Debounced parse on code change
function useCodeParse(code: string) {
  useEffect(() => {
    const timer = setTimeout(async () => {
      const result = await api.parseCode(graphId, code)
      store.setParseResult(result)
    }, 500)
    return () => clearTimeout(timer)
  }, [code])
}
```

### 7.5 CodePreviewCanvas

Reuses existing `BuilderNode` component (read-only mode — no drag, no selection, no toolbar). Receives `preview.nodes` and `preview.edges` from parse result and renders them as a static ReactFlow graph.

Nodes with parse errors get a red border highlight.

### 7.6 AgentBuilder Routing

```tsx
// AgentBuilder.tsx
const graphMode = graphData?.variables?.graph_mode

if (graphMode === 'dsl') {
  return <CodeEditorPage />
}
return <DeepAgentsCanvas />  // only remaining canvas mode
```

New graph creation flow adds a mode selector:
- "Code Editor" → creates graph with `graph_mode: "dsl"`, opens CodeEditorPage with starter template
- "Deep Agents" → creates graph with `graph_mode: "canvas"`, opens existing canvas

**Starter template** (pre-loaded for new DSL graphs):

```python
from joysafeter.nodes import agent, direct_reply
from joysafeter import JoyGraph, GraphState
from langgraph.graph import START, END
from typing import Annotated
import operator


class MyState(GraphState):
    messages: Annotated[list, operator.add]


# Define nodes
responder = agent(
    model="deepseek",
    system_prompt="You are a helpful assistant.",
)

# Build graph
g = JoyGraph(MyState)
g.add_node("responder", responder)

g.add_edge(START, "responder")
g.add_edge("responder", END)
```

This template is valid DSL, parses cleanly, and produces a runnable single-node graph.

### 7.7 Monaco Editor Configuration

```typescript
<MonacoEditor
  language="python"
  value={code}
  onChange={setCode}
  options={{
    minimap: { enabled: false },
    fontSize: 13,
    lineNumbers: "on",
    scrollBeyondLastLine: false,
  }}
  // Inline error markers from parse result
  markers={parseErrors.map(e => ({
    startLineNumber: e.line,
    severity: MarkerSeverity.Error,
    message: e.message,
  }))}
/>
```

---

## 8. joysafeter SDK (Thin Type Stub)

The `joysafeter` package is imported by user code for type hints and IDE autocomplete. It does **not** execute at parse time — the backend AST parser only reads the code statically.

```python
# joysafeter/__init__.py
from joysafeter._graph import JoyGraph, GraphState

# joysafeter/nodes.py
def agent(**kwargs) -> NodeDef: ...
def condition(**kwargs) -> NodeDef: ...
def router(**kwargs) -> NodeDef: ...
def fn(**kwargs): ...          # decorator factory
def http(**kwargs) -> NodeDef: ...
def direct_reply(**kwargs) -> NodeDef: ...

class NodeDef:
    """Marker object returned by node factory functions.
    Carries kwargs for AST parser to extract."""
    def __init__(self, node_type: str, **kwargs): ...
```

The SDK is installable as a Python package (`pip install joysafeter`) so users get autocomplete in their local IDE even outside the platform.

---

## 9. Error Handling

### Parse Errors

| Error type | Source | Surfaced as |
|-----------|--------|-------------|
| Python SyntaxError | `ast.parse()` | Inline Monaco marker + Error Panel |
| Unknown node type | DSLVisitor | Warning marker |
| Undefined node in edge | DSLValidator | Error marker on edge line |
| No entry point | DSLValidator | Error banner |
| Orphaned node | DSLValidator | Warning marker |
| Invalid route key | DSLValidator | Error marker |

Parse errors do **not** block saving — users can save broken code. They **do** block Run.

### Runtime Errors

Reuse existing execution error display in `ExecutionPanel`. No changes needed.

---

## 10. Migration Plan

### Phase 1 — Backend (no frontend changes)
1. Implement `dsl_models.py`, `dsl_parser.py`, `dsl_validator.py`
2. Implement `DSLRunService` + `DSLExecutorBuilder`
3. Add `graph_code.py` API endpoints (`/parse`, `/save`)
4. Wire `RunService` to dispatch to `DSLRunService` when `graph_mode == "dsl"`
5. Write `joysafeter` SDK stub package
6. Write `dsl_code_generator.py` (DSL-compatible output, replaces `code_generator.py` for migration)
7. Unit tests for DSLParser covering all node types, edge patterns, and error cases

### Phase 2 — Frontend
1. `codeEditorStore.ts` + `useCodeParse` hook
2. `CodeEditor.tsx` (Monaco wrapper with error markers)
3. `CodePreviewCanvas.tsx` (read-only ReactFlow)
4. `CodeErrorPanel.tsx`
5. `CodeEditorPage.tsx` (layout assembly)
6. `AgentBuilder.tsx` routing by `graph_mode`
7. New graph creation mode selector (Code Editor vs Deep Agents)

### Phase 3 — Migration & Cleanup

**Entry criteria:** Phase 1 and Phase 2 are complete and verified in staging. DSL run path is confirmed working for all node types.

**Migration steps:**
1. Run `dsl_code_generator.py` migration script against all non-DeepAgents graphs
   - Graphs that fail to generate valid DSL are logged and remain `graph_mode: "canvas"` (manual review queue)
   - Graphs that generate valid DSL but fail to parse are also logged (should not happen — generator and parser are co-designed)
2. Verify migrated graphs are runnable: run smoke tests against a sample of migrated graphs
3. After 2-week validation period with no reported regressions, proceed to cleanup

**Cleanup (after validation period):**
- Remove canvas-only frontend components: `PropertiesPanel.tsx`, `StateSidebar.tsx`, `GraphStatePanel.tsx`, `ComponentsSidebar.tsx`, `services/dataMigration.ts`, `services/nodeRegistry.tsx` (reduce to DeepAgents-only nodes)
- Remove standard canvas API endpoints (`/state` save/load for non-DeepAgents graphs)
- Remove `standard_graph_builder.py`, simplify `graph_builder_factory.py`
- Archive (do not delete) `graph_nodes` and `graph_edges` DB rows for migrated graphs — drop only after 30-day archive period with no rollback requests

**Rollback:** Any migrated graph can be reverted by setting `graph.variables.graph_mode = "canvas"` — the original DB rows are preserved throughout the validation period.

---

## 11. What Gets Deleted

After migration is complete:

**Frontend (canvas-specific, non-DeepAgents):**
- `BuilderSidebarTabs.tsx` components tab
- `PropertiesPanel.tsx` (node config forms)
- `StateSidebar.tsx`
- `GraphStatePanel.tsx`
- `ComponentsSidebar.tsx`
- `services/dataMigration.ts`
- `services/nodeRegistry.tsx` (or reduced to DeepAgents-only nodes)

**Backend:**
- `standard_graph_builder.py` (replaced by DSLParser → GraphCompiler path)
- `graph_builder_factory.py` (simplified — only DeepAgents check remains)
- Canvas-specific save/load state endpoints (non-DeepAgents)

**DB:**
- `graph_nodes` and `graph_edges` rows for migrated graphs (after validation period)

**Kept:**
- `GraphCompiler` — unchanged, still the execution engine
- `NodeExecutionWrapper` — unchanged
- All executors in `node_executors.py` — unchanged
- `GraphState` / `build_state_class` — unchanged
- `code_generator.py` — kept, useful for export
- DeepAgents builder + canvas — fully preserved
- `graph_schema.py` — unchanged, still the intermediate representation

---

## 12. Key Invariants

- DSLParser output is always a valid `GraphSchema` or a list of errors — never raises exceptions to the caller
- Parse is stateless and idempotent — same code always produces same schema
- Run always re-parses from code — never executes stale cached schema
- `graph_mode: "dsl"` graphs never open in canvas editor
- `graph_mode: "canvas"` graphs (DeepAgents) never open in code editor
- Migration is non-destructive — original DB rows preserved during transition period
