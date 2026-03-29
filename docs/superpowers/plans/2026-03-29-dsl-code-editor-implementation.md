# DSL Code Editor — Implementation Plan

**Date:** 2026-03-29
**Spec:** `docs/superpowers/specs/2026-03-28-dsl-code-editor-design.md`
**Branch:** `feat/dsl-code-editor` (from `dev-0327`)

---

## Phase 1 — Backend DSL Core

### Step 1.1: DSL Models (`backend/app/core/dsl/dsl_models.py`)

**New file.** Pure dataclasses, no dependencies on existing code.

```python
# backend/app/core/dsl/dsl_models.py
from dataclasses import dataclass, field

@dataclass
class ParseError:
    line: int | None
    message: str
    severity: str = "error"  # "error" | "warning"

@dataclass
class ParsedStateField:
    name: str
    field_type: str        # "int", "str", "list", "dict", "messages"
    reducer: str | None    # "add", "append", "merge", None

@dataclass
class ParsedNode:
    var_name: str          # Python variable name (e.g. "classifier")
    node_type: str         # mapped via _FACTORY_TO_NODE_TYPE
    kwargs: dict           # extracted keyword arguments
    inline_code: str | None = None  # for @fn nodes only

@dataclass
class ParsedEdge:
    source: str            # node string name or "START"
    target: str            # node string name or "END"
    route_key: str | None = None  # for conditional edges

@dataclass
class ParseResult:
    state_fields: list[ParsedStateField] = field(default_factory=list)
    nodes: list[ParsedNode] = field(default_factory=list)
    edges: list[ParsedEdge] = field(default_factory=list)
    graph_var: str | None = None
    entry_node: str | None = None
    errors: list[ParseError] = field(default_factory=list)
```

**Tests:** `backend/tests/core/dsl/test_dsl_models.py` — basic construction, field defaults.

---

### Step 1.2: DSL Parser (`backend/app/core/dsl/dsl_parser.py`)

**New file.** Depends on `dsl_models.py` + `graph_schema.py`.

Two public methods on `DSLParser`:
- `parse(code) -> ParseResult` — used by `/parse` API
- `parse_to_schema(code) -> tuple[GraphSchema | None, list[ParseError]]` — used by `_compile_dsl_graph`

Internal `_DSLVisitor(ast.NodeVisitor)`:

| Visitor method | Detects | Produces |
|---|---|---|
| `visit_ClassDef` | `class X(GraphState)` | `ParsedStateField` list |
| `visit_Assign` | `x = agent(...)` / `g = JoyGraph(State)` | `ParsedNode` / graph_var |
| `visit_AsyncFunctionDef` | `@fn(...) async def` | `ParsedNode` with inline_code |
| `visit_Expr` | `g.add_node` / `g.add_edge` / `g.add_conditional_edges` | name→node mapping, `ParsedEdge` |

Factory-to-type mapping (spec §6.3):

```python
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
```

`_build_schema(result: ParseResult) -> GraphSchema`:
- `NodeSchema.id` = `NodeSchema.label` = string name from `g.add_node("name", var)`
- START/END edges dropped — compiler derives entry/exit from topology
- `ParsedStateField` → `StateFieldSchema`, `ParsedEdge` → `EdgeSchema`

**Key implementation details:**
- `visit_Assign` records `var_name → ParsedNode` in `self._var_nodes`
- `visit_Expr` for `g.add_node("name", var)` resolves `var` via `self._var_nodes[var.id]`, then registers `"name" → ParsedNode` in `self._named_nodes`
- `visit_Expr` for `g.add_conditional_edges(src, fn, {k: v})` emits one `ParsedEdge` per dict entry
- `ast.get_source_segment(self._source, node)` extracts `@fn` body
- `visit_ClassDef` inspects `Annotated[type, reducer]` via `ast.Subscript` → `ast.Tuple`

**Tests:** `backend/tests/core/dsl/test_dsl_parser.py`
- Parse complete example from spec §5.6 → verify all fields
- Each node type factory → correct `ParsedNode.node_type`
- `@fn` decorator → inline_code extraction
- `add_conditional_edges` → multiple `ParsedEdge` with route_keys
- START/END handling → edges present in ParseResult, absent in GraphSchema
- SyntaxError → `ParseResult.errors` with line number
- `parse_to_schema` round-trip: code → schema → verify node/edge counts
- Empty code → empty ParseResult (no crash)
- Missing `JoyGraph` instantiation → error

---

### Step 1.3: DSL Validator (`backend/app/core/dsl/dsl_validator.py`)

**New file.** Post-parse semantic checks on `ParseResult`.

```python
def validate(result: ParseResult) -> list[ParseError]:
    errors = []
    # 1. All nodes in edges are defined
    # 2. Duplicate node string names
    # 3. Entry point exists (at least one node with no incoming edges)
    # 4. Conditional edge route keys match node type (condition → "true"/"false")
    # 5. No orphaned nodes (defined but never connected)
    # 6. @fn inline code is syntactically valid (ast.parse check)
    return errors
```

Called by `DSLParser.parse()` after visitor completes — errors appended to `ParseResult.errors`.

**Tests:** `backend/tests/core/dsl/test_dsl_validator.py`
- Undefined node in edge → error
- Duplicate node name → error
- Orphaned node → warning
- Invalid route key for condition → error
- Invalid @fn code → error with line number
- Valid graph → no errors

---

### Step 1.4: joysafeter SDK Stub (`backend/app/joysafeter/`)

**New directory.** Thin type stubs — never executed at parse time.

```
backend/app/joysafeter/
├── __init__.py          # exports JoyGraph, GraphState
├── _graph.py            # JoyGraph (thin StateGraph wrapper), GraphState (TypedDict base)
└── nodes.py             # agent(), condition(), router(), fn(), http(), direct_reply(),
                         #   human_input(), tool() → NodeDef
```

`NodeDef` is a marker dataclass carrying `node_type` + `**kwargs`. The SDK exists so:
1. User code has valid imports for IDE autocomplete
2. AST parser can verify import names

**Tests:** `backend/tests/core/dsl/test_joysafeter_sdk.py`
- Import all symbols without error
- `agent(model="x")` returns `NodeDef` with correct type/kwargs
- `@fn(writes=["score"])` works as decorator

---

### Step 1.5: DSLExecutorBuilder (`backend/app/core/dsl/dsl_executor_builder.py`)

**New file.** Constructs executor instances from `GraphSchema` without DB `GraphNode` rows.

Core approach — `_NodeSchemaShim` (spec §6.6):

```python
class _NodeSchemaShim:
    """Satisfies GraphNode.data["config"] access pattern for executor constructors."""
    def __init__(self, node: NodeSchema):
        self.id = node.id
        self.type = node.type
        self.data = {"config": node.config, "label": node.label}
        self.config = node.config
```

`DSLExecutorBuilder`:

```python
class DSLExecutorBuilder:
    def __init__(self, schema, model_service, user_id, llm_model, api_key, base_url, max_tokens):
        ...

    async def build_executors(self) -> dict[str, Any]:
        """Returns {node_id: executor} for all nodes in schema."""
        executor_map = {}
        for node in self.schema.nodes:
            executor_map[node.id] = await self._create_executor(node)
        return executor_map

    async def _create_executor(self, node: NodeSchema) -> Any:
        shim = _NodeSchemaShim(node)
        # Switch on node.type → instantiate correct executor class
        # Agent nodes need model resolution via model_service
```

Executor mapping (matches spec §6.6 `_create_executor`):

| `node.type` | Executor class | Special handling |
|---|---|---|
| `"agent"` | `AgentNodeExecutor` | `model_service.resolve(...)` for resolved_model |
| `"condition"` | `ConditionNodeExecutor` | — |
| `"router_node"` | `RouterNodeExecutor` | — |
| `"function_node"` | `FunctionNodeExecutor` | — |
| `"http_request_node"` | `HttpRequestNodeExecutor` | — |
| `"direct_reply"` | `DirectReplyNodeExecutor` | — |
| `"human_input"` | `HumanInputNodeExecutor` | — |
| `"tool_node"` | `ToolNodeExecutor` | needs `user_id` |

**Tests:** `backend/tests/core/dsl/test_dsl_executor_builder.py`
- Build executors for each supported node type → verify correct class
- Agent node → model resolution called
- Shim satisfies `node.data["config"]` access pattern
- Unknown node type → raises clear error

---

### Step 1.6: Compiler Integration (`backend/app/core/graph/graph_compiler.py`)

**Modify existing file.** Three changes:

**Change A:** `compile_from_schema` gains `executor_map` parameter.

```python
# graph_compiler.py line ~398
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

**Change B:** `_CompilerSession.__init__` stores `executor_map`. `_create_executors_and_nodes` adds DSL branch.

```python
# _CompilerSession.__init__ (line ~80)
def __init__(self, schema, builder, executor_map, checkpointer, validate):
    ...
    self.executor_map = executor_map  # NEW

# _create_executors_and_nodes (line ~219)
async def _create_executors_and_nodes(self):
    fallback_node_name = ...  # unchanged

    if self.executor_map is not None:
        # DSL path: use pre-built executor map
        self.executors = self.executor_map
        for node in self.schema.nodes:
            name = self.node_name_map[node.id]
            executor = self.executors.get(node.id)
            if executor:
                wrapped = NodeExecutionWrapper(
                    executor, node_id=str(node.id), node_type=node.type,
                    metadata=node.metadata, node_config=node.config,
                    fallback_node_name=fallback_node_name
                        if node.id != self.schema.fallback_node_id else None,
                )
                self.workflow.add_node(name, wrapped)
    elif self.builder is not None:
        # Existing path unchanged
        ...
    else:
        # Stub path unchanged
        ...
```

**Change C:** `_build_conditional_edges` and `_compile_workflow` fire for `executor_map` too.

```python
# _build_conditional_edges (line ~255)
def _build_conditional_edges(self):
    if self.builder is None and self.executor_map is None:
        return
    ...  # rest unchanged

# _compile_workflow (line ~371)
def _compile_workflow(self):
    if self.checkpointer is None and (self.builder is not None or self.executor_map is not None):
        from app.core.agent.checkpointer.checkpointer import get_checkpointer
        self.checkpointer = get_checkpointer()
    ...  # rest unchanged
```

**Tests:** Existing compiler tests must still pass. New test:
- `compile_from_schema(schema, executor_map={...})` → compiled graph with correct nodes

---

### Step 1.7: GraphService DSL Dispatch (`backend/app/services/graph_service.py`)

**Modify existing file.** Insert DSL branch in `create_graph_by_graph_id` (line ~856, after graph fetch + permission check, before node/edge loading).

```python
# graph_service.py — create_graph_by_graph_id, after line ~882 (cache check)
# Insert BEFORE "Load nodes and edges" block:

if graph.variables.get("graph_mode") == "dsl":
    return await self._compile_dsl_graph(
        graph, llm_model=llm_model, api_key=api_key, base_url=base_url,
        max_tokens=max_tokens, user_id=user_id,
    )

# Existing path continues unchanged below...
```

New private method `_compile_dsl_graph`:

```python
async def _compile_dsl_graph(self, graph, *, llm_model, api_key, base_url,
                              max_tokens, user_id):
    from app.core.dsl.dsl_parser import DSLParser
    from app.core.dsl.dsl_executor_builder import DSLExecutorBuilder
    from app.core.graph.graph_compiler import compile_from_schema
    from app.core.agent.checkpointer.checkpointer import get_checkpointer

    dsl_code = graph.variables.get("dsl_code", "")
    if not dsl_code.strip():
        raise ValueError("DSL graph has no code")

    parser = DSLParser()
    schema, errors = parser.parse_to_schema(dsl_code)
    if errors:
        raise ValueError(f"DSL parse errors: {errors}")

    model_service = ModelService(self.db)
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

**Cache integration:** The existing `_build_runtime_aware_compile_cache_key` uses `graph.variables` in its hash, so DSL code changes naturally invalidate the cache. The DSL branch is inserted after the cache check — cached DSL graphs are returned from cache without re-parsing.

**Tests:** `backend/tests/services/test_graph_service_dsl.py`
- Mock graph with `variables={"graph_mode": "dsl", "dsl_code": "..."}` → dispatches to `_compile_dsl_graph`
- Graph without `graph_mode` → existing path (no regression)
- Empty `dsl_code` → raises ValueError

---

### Step 1.8: API Endpoints (`backend/app/api/v1/graph_code.py`)

**New file.** Two endpoints under `/v1/graphs/{graph_id}/code/`.

```python
# graph_code.py
router = APIRouter(prefix="/v1/graphs", tags=["Graph Code"])

class CodeParseRequest(BaseModel):
    code: str

class CodeSaveRequest(BaseModel):
    code: str
    name: str | None = None

@router.post("/{graph_id}/code/parse")
async def parse_dsl_code(
    graph_id: uuid.UUID,
    payload: CodeParseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stateless parse: code → schema + preview + errors."""
    parser = DSLParser()
    result = parser.parse(payload.code)

    schema = None
    preview = None
    if not result.errors:
        schema = parser._build_schema(result)
        preview = _schema_to_preview(schema)  # ReactFlow-ready nodes/edges

    return {
        "success": True,
        "data": {
            "schema": schema.model_dump(mode="json") if schema else None,
            "preview": preview,
            "errors": [{"line": e.line, "message": e.message, "severity": e.severity}
                       for e in result.errors],
        },
    }

@router.post("/{graph_id}/code/save")
async def save_dsl_code(
    graph_id: uuid.UUID,
    payload: CodeSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist DSL code to graph.variables."""
    graph = await _get_graph_with_access(db, graph_id, current_user)
    graph.variables = {
        **graph.variables,
        "graph_mode": "dsl",
        "dsl_code": payload.code,
    }
    if payload.name:
        graph.name = payload.name
    await db.commit()
    return {"success": True}
```

**`_schema_to_preview` helper:** Converts `GraphSchema` → `{nodes: [...], edges: [...]}` in ReactFlow format. Each node gets a position via simple auto-layout (topological sort, grid placement). This is a lightweight function in the same file.

**Router registration:** Add `from app.api.v1.graph_code import router as graph_code_router` in `backend/app/api/v1/__init__.py` (or wherever routers are collected — follow existing pattern from `graph_schemas.py`).

**Tests:** `backend/tests/api/v1/test_graph_code.py`
- POST `/parse` with valid code → schema + preview + no errors
- POST `/parse` with syntax error → errors with line numbers
- POST `/save` → graph.variables updated with `graph_mode` and `dsl_code`
- POST `/save` with name → graph.name updated

---

### Step 1.9: `__init__.py` for DSL Package

```
backend/app/core/dsl/
├── __init__.py              # exports DSLParser, ParseResult, ParseError
├── dsl_models.py            # Step 1.1
├── dsl_parser.py            # Step 1.2
├── dsl_validator.py         # Step 1.3
└── dsl_executor_builder.py  # Step 1.5
```

---

### Phase 1 Dependency Graph

```
1.1 (models) ──► 1.2 (parser) ──► 1.3 (validator)
                      │
1.4 (SDK stub)        │ (independent)
                      │
                      ▼
              1.5 (executor builder) ──► 1.6 (compiler integration)
                                                │
                                                ▼
                                    1.7 (graph_service dispatch)
                                                │
                                                ▼
                                    1.8 (API endpoints)
```

Parallelizable: 1.1 + 1.4 can start together. 1.3 can start once 1.1 is done. 1.5 can start once 1.2 is done.

---

## Phase 2 — Frontend Code Editor

### Step 2.1: Install Monaco Editor

```bash
cd frontend && npm install @monaco-editor/react
```

No other new dependencies needed. Monaco loads its workers from CDN by default.

---

### Step 2.2: Code Editor Store (`frontend/app/workspace/[workspaceId]/[agentId]/stores/codeEditorStore.ts`)

**New file.** Zustand store (matches existing pattern in `builderStore.ts`).

```typescript
// codeEditorStore.ts
import { create } from 'zustand'

interface ParseError {
  line: number
  message: string
  severity: 'error' | 'warning'
}

interface PreviewData {
  nodes: any[]  // ReactFlow node format
  edges: any[]  // ReactFlow edge format
}

interface CodeEditorState {
  // State
  code: string
  savedCode: string
  parseResult: any | null       // GraphSchema from backend
  preview: PreviewData | null
  parseErrors: ParseError[]
  isParsing: boolean
  isSaving: boolean
  isDirty: boolean

  // Graph metadata
  graphId: string | null
  graphName: string | null

  // Actions
  setCode: (code: string) => void
  setGraphId: (id: string) => void
  setGraphName: (name: string) => void
  setParseResult: (result: any, preview: PreviewData | null, errors: ParseError[]) => void
  save: () => Promise<void>
  hydrate: (graphId: string, code: string, name: string) => void
  reset: () => void
}

export const useCodeEditorStore = create<CodeEditorState>((set, get) => ({
  code: '',
  savedCode: '',
  parseResult: null,
  preview: null,
  parseErrors: [],
  isParsing: false,
  isSaving: false,
  isDirty: false,
  graphId: null,
  graphName: null,

  setCode: (code) => set({ code, isDirty: code !== get().savedCode }),

  setGraphId: (id) => set({ graphId: id }),
  setGraphName: (name) => set({ graphName: name }),

  setParseResult: (result, preview, errors) =>
    set({ parseResult: result, preview, parseErrors: errors, isParsing: false }),

  save: async () => {
    const { graphId, code, graphName } = get()
    if (!graphId) return
    set({ isSaving: true })
    try {
      await apiPost(`graphs/${graphId}/code/save`, { code, name: graphName })
      set({ savedCode: code, isDirty: false })
    } finally {
      set({ isSaving: false })
    }
  },

  hydrate: (graphId, code, name) =>
    set({ graphId, code, savedCode: code, isDirty: false, graphName: name }),

  reset: () => set({
    code: '', savedCode: '', parseResult: null, preview: null,
    parseErrors: [], isParsing: false, isSaving: false, isDirty: false,
    graphId: null, graphName: null,
  }),
}))
```

**Key design decisions:**
- Separate store from `builderStore` — DSL mode has fundamentally different state shape (code string vs nodes/edges arrays)
- `isDirty` = `code !== savedCode` — simple string comparison
- Save calls the new `/code/save` endpoint directly
- No `SaveManager` reuse — DSL save is simpler (single string, no hash computation needed)

---

### Step 2.3: `useCodeParse` Hook (`frontend/app/workspace/[workspaceId]/[agentId]/hooks/useCodeParse.ts`)

**New file.** Debounced parse on code change.

```typescript
// useCodeParse.ts
import { useEffect, useRef } from 'react'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { apiPost } from '@/lib/api-client'

export function useCodeParse(graphId: string | null) {
  const code = useCodeEditorStore(s => s.code)
  const setParseResult = useCodeEditorStore(s => s.setParseResult)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    if (!graphId || !code.trim()) return

    useCodeEditorStore.setState({ isParsing: true })

    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      try {
        const res = await apiPost(`graphs/${graphId}/code/parse`, { code })
        if (res.success) {
          setParseResult(res.data.schema, res.data.preview, res.data.errors)
        }
      } catch {
        // Network error — leave previous state
        useCodeEditorStore.setState({ isParsing: false })
      }
    }, 500)

    return () => clearTimeout(timerRef.current)
  }, [code, graphId])
}
```

---

### Step 2.4: CodeEditor Component (`frontend/app/workspace/[workspaceId]/[agentId]/components/CodeEditor.tsx`)

**New file.** Monaco Editor wrapper with inline error markers.

```tsx
// CodeEditor.tsx
'use client'
import Editor, { OnMount } from '@monaco-editor/react'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { useRef, useEffect } from 'react'
import type { editor } from 'monaco-editor'

export function CodeEditor() {
  const code = useCodeEditorStore(s => s.code)
  const setCode = useCodeEditorStore(s => s.setCode)
  const parseErrors = useCodeEditorStore(s => s.parseErrors)
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<any>(null)

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor
    monacoRef.current = monaco
  }

  // Update error markers when parseErrors change
  useEffect(() => {
    if (!editorRef.current || !monacoRef.current) return
    const model = editorRef.current.getModel()
    if (!model) return

    const markers = parseErrors.map(e => ({
      startLineNumber: e.line ?? 1,
      startColumn: 1,
      endLineNumber: e.line ?? 1,
      endColumn: model.getLineMaxColumn(e.line ?? 1),
      message: e.message,
      severity: e.severity === 'warning'
        ? monacoRef.current.MarkerSeverity.Warning
        : monacoRef.current.MarkerSeverity.Error,
    }))
    monacoRef.current.editor.setModelMarkers(model, 'dsl', markers)
  }, [parseErrors])

  return (
    <Editor
      language="python"
      value={code}
      onChange={(v) => setCode(v ?? '')}
      onMount={handleMount}
      options={{
        minimap: { enabled: false },
        fontSize: 13,
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
        automaticLayout: true,
        tabSize: 4,
      }}
    />
  )
}
```

---

### Step 2.5: CodePreviewCanvas (`frontend/app/workspace/[workspaceId]/[agentId]/components/CodePreviewCanvas.tsx`)

**New file.** Read-only ReactFlow canvas showing parsed graph structure.

```tsx
// CodePreviewCanvas.tsx
'use client'
import ReactFlow, { Background, BackgroundVariant } from 'reactflow'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { nodeTypes, edgeTypes } from '../utils/reactFlowConfig'

export function CodePreviewCanvas() {
  const preview = useCodeEditorStore(s => s.preview)
  const parseErrors = useCodeEditorStore(s => s.parseErrors)

  const nodes = preview?.nodes ?? []
  const edges = preview?.edges ?? []

  // Highlight nodes with errors
  const errorNodeIds = new Set(
    parseErrors.filter(e => e.nodeId).map(e => e.nodeId)
  )
  const styledNodes = nodes.map(n => ({
    ...n,
    style: errorNodeIds.has(n.id) ? { border: '2px solid red' } : undefined,
  }))

  return (
    <ReactFlow
      nodes={styledNodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      panOnDrag={true}
      zoomOnScroll={true}
      fitView
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} />
    </ReactFlow>
  )
}
```

Reuses existing `BuilderNode` via `nodeTypes` from `reactFlowConfig.ts`. Nodes are read-only (no drag, no connect, no select).

---

### Step 2.6: CodeErrorPanel (`frontend/app/workspace/[workspaceId]/[agentId]/components/CodeErrorPanel.tsx`)

**New file.** Displays parse errors with clickable line links.

```tsx
// CodeErrorPanel.tsx
'use client'
import { useCodeEditorStore } from '../stores/codeEditorStore'

interface Props {
  onLineClick?: (line: number) => void
}

export function CodeErrorPanel({ onLineClick }: Props) {
  const errors = useCodeEditorStore(s => s.parseErrors)

  if (errors.length === 0) return null

  return (
    <div className="border-t bg-red-50 dark:bg-red-950/20 px-4 py-2 max-h-32 overflow-y-auto">
      {errors.map((e, i) => (
        <div
          key={i}
          className="text-sm cursor-pointer hover:underline py-0.5"
          onClick={() => e.line && onLineClick?.(e.line)}
        >
          <span className={e.severity === 'error' ? 'text-red-600' : 'text-yellow-600'}>
            {e.severity === 'error' ? '✕' : '⚠'}
          </span>
          {' '}
          {e.line ? `Line ${e.line}: ` : ''}
          {e.message}
        </div>
      ))}
    </div>
  )
}
```

`onLineClick` callback scrolls Monaco editor to the error line via `editorRef.current.revealLineInCenter(line)`.

---

### Step 2.7: CodeEditorPage (`frontend/app/workspace/[workspaceId]/[agentId]/CodeEditorPage.tsx`)

**New file.** Top-level layout for DSL mode — replaces canvas layout.

```tsx
// CodeEditorPage.tsx
'use client'
import { ReactFlowProvider } from 'reactflow'
import { CodeEditor } from './components/CodeEditor'
import { CodePreviewCanvas } from './components/CodePreviewCanvas'
import { CodeErrorPanel } from './components/CodeErrorPanel'
import { CodeEditorToolbar } from './components/CodeEditorToolbar'
import { ExecutionPanelNew } from './components/execution/ExecutionPanelNew'
import { useCodeParse } from './hooks/useCodeParse'
import { useCodeEditorStore } from './stores/codeEditorStore'
import { useRef } from 'react'
import type { editor } from 'monaco-editor'

interface Props {
  graphId: string
  workspaceId: string
}

export function CodeEditorPage({ graphId, workspaceId }: Props) {
  useCodeParse(graphId)
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null)

  const handleLineClick = (line: number) => {
    editorRef.current?.revealLineInCenter(line)
    editorRef.current?.setPosition({ lineNumber: line, column: 1 })
    editorRef.current?.focus()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <CodeEditorToolbar graphId={graphId} workspaceId={workspaceId} />

      {/* Main content: editor + preview */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Monaco Editor */}
        <div className="w-1/2 border-r flex flex-col">
          <CodeEditor ref={editorRef} />
        </div>

        {/* Right: Read-only canvas preview */}
        <ReactFlowProvider>
          <div className="w-1/2">
            <CodePreviewCanvas />
          </div>
        </ReactFlowProvider>
      </div>

      {/* Error panel */}
      <CodeErrorPanel onLineClick={handleLineClick} />

      {/* Execution panel (collapsed by default) */}
      <ExecutionPanelNew />
    </div>
  )
}
```

**Layout matches spec §7.2:** toolbar top, editor left, preview right, error panel bottom, execution panel collapsed.

`CodeEditor` needs to expose `editorRef` via `forwardRef` — update Step 2.4 component to accept ref and assign it in `handleMount`.

---

### Step 2.8: CodeEditorToolbar (`frontend/app/workspace/[workspaceId]/[agentId]/components/CodeEditorToolbar.tsx`)

**New file.** Toolbar for DSL mode — Save, Run, deploy actions.

```tsx
// CodeEditorToolbar.tsx
'use client'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { useExecutionStore } from '../stores/execution/executionStore'
import { Button } from '@/components/ui/button'

interface Props {
  graphId: string
  workspaceId: string
}

export function CodeEditorToolbar({ graphId, workspaceId }: Props) {
  const { isDirty, isSaving, save, parseErrors, graphName, setGraphName } = useCodeEditorStore()
  const { isExecuting, startExecution, stopExecution } = useExecutionStore()

  const hasErrors = parseErrors.some(e => e.severity === 'error')

  const handleRun = () => {
    if (hasErrors) return
    // Save before run if dirty
    if (isDirty) {
      save().then(() => startExecution({ graphId }))
    } else {
      startExecution({ graphId })
    }
  }

  return (
    <div className="flex items-center justify-between px-4 py-2 border-b bg-background">
      {/* Left: graph name */}
      <input
        className="text-sm font-medium bg-transparent border-none outline-none"
        value={graphName ?? ''}
        onChange={(e) => setGraphName(e.target.value)}
        placeholder="Untitled Graph"
      />

      {/* Right: actions */}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => save()}
          disabled={!isDirty || isSaving}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </Button>

        <Button
          size="sm"
          onClick={isExecuting ? stopExecution : handleRun}
          disabled={hasErrors && !isExecuting}
        >
          {isExecuting ? 'Stop' : 'Run'}
        </Button>
      </div>
    </div>
  )
}
```

**Key differences from `BuilderToolbar`:**
- Explicit Save button (canvas uses autosave — DSL needs manual save since code changes are more intentional)
- Run blocked when parse errors exist
- Auto-save before run if dirty
- No drag-drop, no import/export, no validation panel toggle (those are canvas-specific)
- Deploy/publish actions can be added later — reuse existing `useDeploymentStore` pattern

---

### Step 2.9: AgentBuilder Routing (`frontend/app/workspace/[workspaceId]/[agentId]/AgentBuilder.tsx`)

**Modify existing file.** Add DSL mode routing after graph data loads.

The graph data is loaded via React Query at line ~66-79 (`useGraphState`). The `graphData` object contains `variables.graph_mode`. Insert routing logic in the render section (line ~632).

```tsx
// AgentBuilder.tsx — in the render section, before existing canvas layout

// Read graph_mode from loaded graph data
const graphMode = graphData?.variables?.graph_mode

// DSL mode: render CodeEditorPage instead of canvas
if (graphMode === 'dsl') {
  return <CodeEditorPage graphId={agentId} workspaceId={workspaceId} />
}

// Existing canvas layout continues below...
```

**Hydration for DSL mode:** In the existing graph hydration block (line ~179-310), add a DSL branch:

```tsx
// After graph data loads, before canvas hydration
if (graphData?.variables?.graph_mode === 'dsl') {
  useCodeEditorStore.getState().hydrate(
    agentId,
    graphData.variables.dsl_code ?? '',
    graphData.name ?? '',
  )
  return  // skip canvas hydration
}
```

**beforeunload for DSL:** Add DSL-aware save in the beforeunload handler (line ~132-172):

```tsx
// In beforeunload handler, check mode
const codeStore = useCodeEditorStore.getState()
if (codeStore.graphId && codeStore.isDirty) {
  navigator.sendBeacon(
    `${apiBase}/v1/graphs/${codeStore.graphId}/code/save`,
    JSON.stringify({ code: codeStore.code })
  )
}
```

---

### Step 2.10: New Graph Mode Selector

**Modify existing files.** Two creation paths need mode selection:

**A. Workspace sidebar** (`frontend/app/workspace/[workspaceId]/components/sidebar/sidebar.tsx`, line ~150):

Add a mode parameter to graph creation. When user clicks "New Graph", show a small dropdown or dialog:
- "Code Editor" → `createGraph({ variables: { graph_mode: 'dsl', dsl_code: STARTER_TEMPLATE } })`
- "Deep Agents" → `createGraph({})` (existing behavior)

**B. Workspace page auto-create** (`frontend/app/workspace/[workspaceId]/page.tsx`, line ~47):

Default auto-created graph stays as canvas (no change needed — DeepAgents is the default for empty workspaces).

**Starter template** (spec §7.6):

```typescript
// frontend/app/workspace/[workspaceId]/[agentId]/constants/dslTemplate.ts
export const DSL_STARTER_TEMPLATE = `from joysafeter.nodes import agent, direct_reply
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
`
```

---

### Step 2.11: Keyboard Shortcuts

**In `CodeEditor.tsx`**, register Monaco keybindings on mount:

```typescript
// Cmd/Ctrl+S → save
editor.addAction({
  id: 'dsl-save',
  label: 'Save',
  keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
  run: () => useCodeEditorStore.getState().save(),
})
```

---

### Phase 2 Dependency Graph

```
2.1 (install Monaco) ──► 2.4 (CodeEditor)
                                │
2.2 (store) ──► 2.3 (useCodeParse hook)
    │               │
    │               ▼
    └──────► 2.7 (CodeEditorPage) ◄── 2.5 (CodePreviewCanvas)
                    │                       │
                    │               2.6 (CodeErrorPanel)
                    │
                    ▼
            2.8 (CodeEditorToolbar)
                    │
                    ▼
            2.9 (AgentBuilder routing)
                    │
                    ▼
            2.10 (mode selector)
            2.11 (keyboard shortcuts)
```

Parallelizable: 2.1 is independent. 2.2 can start immediately. 2.4/2.5/2.6 can be built in parallel once 2.2 is done. 2.7 assembles them. 2.9 is the integration point.

---

## Phase 3 — Migration

### Step 3.1: DSL Code Generator (`backend/app/core/dsl/dsl_code_generator.py`)

**New file.** Converts `GraphSchema` → DSL-compatible Python code that `DSLParser` can round-trip.

```python
def generate_dsl_code(schema: GraphSchema) -> str:
    """Generate DSL code from a GraphSchema.

    Output is valid DSL that DSLParser.parse() can round-trip back to
    an equivalent GraphSchema.
    """
    lines = []
    lines += _generate_imports(schema)
    lines += _generate_state_class(schema)
    lines += _generate_node_definitions(schema)
    lines += _generate_graph_wiring(schema)
    return '\n'.join(lines)
```

**Import generation:** Scans node types to determine which factory functions to import.

**State class generation:** Emits `class MyGraphState(GraphState)` with typed fields and reducers.

**Node definition generation:**

| `NodeSchema.type` | Emitted DSL |
|---|---|
| `"agent"` | `name = agent(model=..., system_prompt=..., tools=[...])` |
| `"condition"` | `name = condition(expression=...)` |
| `"router_node"` | `name = router(routes=[...], default=...)` |
| `"function_node"` | `@fn(writes=[...])\nasync def name(state):` + inline code |
| `"http_request_node"` | `name = http(method=..., url=..., ...)` |
| `"direct_reply"` | `name = direct_reply(template=...)` |
| `"human_input"` | `name = human_input()` |
| `"tool_node"` | `name = tool(tool_name=..., ...)` |

**Graph wiring generation:**
- `g = JoyGraph(MyGraphState)`
- `g.add_node("name", name)` for each node
- `g.add_edge(START, "entry_node")` for start nodes (nodes with no incoming edges)
- `g.add_edge("source", "target")` for normal edges
- `g.add_conditional_edges("source", lambda s: ..., {"key": "target"})` for conditional edges
- `g.add_edge("exit_node", END)` for end nodes (nodes with no outgoing edges)

**`function_node` special handling:** If `NodeSchema.config.code` contains inline code, emit it as `@fn`-decorated async function. If `config.function_code` exists (legacy format), use that.

**Tests:** `backend/tests/core/dsl/test_dsl_code_generator.py`
- Generate code for each node type → verify output is valid Python (ast.parse)
- Round-trip test: `schema → generate_dsl_code → DSLParser.parse_to_schema → compare schemas`
- State fields with reducers → correct `Annotated[type, operator.add]` output
- Conditional edges → correct `add_conditional_edges` output
- Empty graph → minimal valid DSL

---

### Step 3.2: Migration Script (`backend/scripts/migrate_to_dsl.py`)

**New file.** One-time migration script.

```python
# migrate_to_dsl.py
"""
Migrate non-DeepAgents canvas graphs to DSL mode.

Usage:
    python -m scripts.migrate_to_dsl [--dry-run] [--graph-id UUID]

Flags:
    --dry-run     Parse and validate but don't persist changes
    --graph-id    Migrate a single graph (for testing)
"""

DSL_V1_SUPPORTED_TYPES = {
    "agent", "condition", "router_node", "function_node",
    "http_request_node", "direct_reply", "human_input", "tool_node",
}

async def migrate_graph(graph, nodes, edges, db, *, dry_run=False) -> MigrationResult:
    # Step 1: Build schema from DB
    try:
        schema = GraphSchema.from_db(graph, nodes, edges)
    except ValidationError as e:
        return MigrationResult(graph.id, "schema_from_db", str(e))

    # Step 2: Check for unsupported node types
    unsupported = {n.type for n in schema.nodes} - DSL_V1_SUPPORTED_TYPES
    if unsupported:
        return MigrationResult(graph.id, "unsupported_node_types", list(unsupported))

    # Step 3: Generate DSL code
    try:
        code = generate_dsl_code(schema)
    except Exception as e:
        return MigrationResult(graph.id, "dsl_generate_code", str(e))

    # Step 4: Verify round-trip
    parse_result = DSLParser().parse(code)
    if parse_result.errors:
        return MigrationResult(graph.id, "parse_roundtrip", parse_result.errors)

    # Step 5: Persist (unless dry-run)
    if not dry_run:
        graph.variables = {
            **graph.variables,
            "dsl_code": code,
            "graph_mode": "dsl",
        }
        await db.commit()

    return MigrationResult(graph.id, "success")

async def main():
    # Parse args, connect to DB
    # For each non-DeepAgents graph:
    #   - Skip if graph.variables.get("graph_mode") == "dsl" (already migrated)
    #   - Skip if any node has config.useDeepAgents == True
    #   - Call migrate_graph()
    #   - Log result
    # Print summary: success/fail/skip counts
```

**DeepAgents detection:** A graph is DeepAgents if any of its nodes has `data.config.useDeepAgents == True` (matches `graph_builder_factory.py:_has_deep_agents_nodes` logic at line ~58).

**Output:** Migration produces a JSON report:
```json
{
  "total": 150,
  "migrated": 120,
  "skipped_deepagents": 15,
  "skipped_already_dsl": 5,
  "failed": 10,
  "failures": [
    {"graph_id": "...", "reason": "unsupported_node_types", "detail": ["loop_condition_node"]}
  ]
}
```

**Tests:** `backend/tests/scripts/test_migrate_to_dsl.py`
- Graph with supported types → migrated successfully
- Graph with `loop_condition_node` → skipped, logged
- DeepAgents graph → skipped
- Already-migrated graph → skipped
- Dry-run mode → no DB changes
- Round-trip failure → logged, graph unchanged

---

### Step 3.3: Rollback Mechanism

No new code needed. Rollback is a DB update:

```sql
UPDATE graphs
SET variables = jsonb_set(variables, '{graph_mode}', '"canvas"')
WHERE id = '<graph_id>';
```

Original `graph_nodes` and `graph_edges` rows are preserved — the migration script does not delete them. Setting `graph_mode` back to `"canvas"` (or removing the key) restores the original canvas editing experience.

A convenience script can be added:

```python
# backend/scripts/rollback_dsl.py
async def rollback_graph(graph_id: uuid.UUID, db):
    graph = await db.get(AgentGraph, graph_id)
    graph.variables.pop("graph_mode", None)
    graph.variables.pop("dsl_code", None)
    await db.commit()
```

---

### Phase 3 Dependency Graph

```
Phase 1 + Phase 2 complete
        │
        ▼
3.1 (dsl_code_generator) ──► 3.2 (migration script)
                                      │
                                      ▼
                              3.3 (rollback — documentation only)
```

Phase 3 entry criteria: Phase 1 backend is complete and tested. Phase 2 frontend is complete. DSL run path verified for all supported node types.

---

## File Summary

### New Files (17)

| File | Phase | Step |
|---|---|---|
| `backend/app/core/dsl/__init__.py` | 1 | 1.9 |
| `backend/app/core/dsl/dsl_models.py` | 1 | 1.1 |
| `backend/app/core/dsl/dsl_parser.py` | 1 | 1.2 |
| `backend/app/core/dsl/dsl_validator.py` | 1 | 1.3 |
| `backend/app/core/dsl/dsl_executor_builder.py` | 1 | 1.5 |
| `backend/app/core/dsl/dsl_code_generator.py` | 3 | 3.1 |
| `backend/app/joysafeter/__init__.py` | 1 | 1.4 |
| `backend/app/joysafeter/_graph.py` | 1 | 1.4 |
| `backend/app/joysafeter/nodes.py` | 1 | 1.4 |
| `backend/app/api/v1/graph_code.py` | 1 | 1.8 |
| `backend/scripts/migrate_to_dsl.py` | 3 | 3.2 |
| `frontend/.../stores/codeEditorStore.ts` | 2 | 2.2 |
| `frontend/.../hooks/useCodeParse.ts` | 2 | 2.3 |
| `frontend/.../components/CodeEditor.tsx` | 2 | 2.4 |
| `frontend/.../components/CodePreviewCanvas.tsx` | 2 | 2.5 |
| `frontend/.../components/CodeErrorPanel.tsx` | 2 | 2.6 |
| `frontend/.../CodeEditorPage.tsx` | 2 | 2.7 |
| `frontend/.../components/CodeEditorToolbar.tsx` | 2 | 2.8 |
| `frontend/.../constants/dslTemplate.ts` | 2 | 2.10 |

### Modified Files (5)

| File | Phase | Step | Change |
|---|---|---|---|
| `backend/app/core/graph/graph_compiler.py` | 1 | 1.6 | Add `executor_map` param + DSL branch |
| `backend/app/services/graph_service.py` | 1 | 1.7 | Add `_compile_dsl_graph` + dispatch |
| `backend/app/api/v1/__init__.py` (or router registry) | 1 | 1.8 | Register `graph_code` router |
| `frontend/.../AgentBuilder.tsx` | 2 | 2.9 | DSL mode routing + hydration |
| `frontend/.../sidebar/sidebar.tsx` | 2 | 2.10 | Mode selector on new graph |

### New Test Files (8)

| File | Tests |
|---|---|
| `backend/tests/core/dsl/test_dsl_models.py` | Model construction |
| `backend/tests/core/dsl/test_dsl_parser.py` | All parse scenarios |
| `backend/tests/core/dsl/test_dsl_validator.py` | Semantic validation |
| `backend/tests/core/dsl/test_joysafeter_sdk.py` | SDK imports + factories |
| `backend/tests/core/dsl/test_dsl_executor_builder.py` | Executor construction |
| `backend/tests/core/dsl/test_dsl_code_generator.py` | Code generation + round-trip |
| `backend/tests/api/v1/test_graph_code.py` | API endpoints |
| `backend/tests/services/test_graph_service_dsl.py` | DSL dispatch |
| `backend/tests/scripts/test_migrate_to_dsl.py` | Migration script |

---

## Risk Register

| Risk | Mitigation |
|---|---|
| `_NodeSchemaShim` misses a `GraphNode` attribute used by an executor | Shim produces clear `AttributeError` — easy to find and fix in testing. Each executor's constructor access pattern is documented in this plan. |
| Monaco bundle size impacts frontend load time | Monaco loads workers from CDN by default. Can lazy-load `CodeEditorPage` via `next/dynamic` with `ssr: false`. |
| DSL parse latency on large graphs (500ms debounce + network) | Parse is pure AST — should be <50ms for any realistic graph. Network is the bottleneck; consider moving parse to frontend (WASM Python parser) in v2 if needed. |
| Migration round-trip produces semantically different schema | Round-trip test in migration script catches this. Failed graphs stay in canvas mode. |
| Existing compiler tests break from `executor_map` parameter | `executor_map` defaults to `None` — all existing call sites pass `builder` only, so no signature change for them. `_CompilerSession.__init__` adds one positional arg but it's called only from `compile_from_schema` which we control. |

---

## Implementation Order (Recommended)

**Week 1:** Steps 1.1 → 1.4 (models, parser, validator, SDK stub) — all independent, can be parallelized
**Week 1-2:** Steps 1.5 → 1.8 (executor builder, compiler integration, graph service, API) — sequential chain
**Week 2:** Steps 2.1 → 2.6 (Monaco install, store, hook, components) — can parallel with backend testing
**Week 2-3:** Steps 2.7 → 2.11 (page assembly, toolbar, routing, mode selector)
**Week 3:** Steps 3.1 → 3.3 (code generator, migration script, rollback)
**Week 3+:** Staging validation, migration dry-run, production migration
