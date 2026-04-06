# Architecture

## Overall Architecture

JoySafeter follows a layered architecture pattern with clear separation of concerns:

```mermaid
flowchart TB
    subgraph Row1[" "]
        direction LR

        subgraph Frontend["Frontend Layer (Next.js + React)"]
            direction TB
            Canvas["DeepAgents Canvas<br/>ReactFlow"]
            CodeEditor["Code Editor<br/>CodeMirror"]
            Trace["Execution Trace<br/>SSE Stream"]
            Workspace["Workspace Manager<br/>RBAC"]
            Copilot["Copilot AI<br/>Graph Assistant"]
        end

        subgraph API["API Layer (FastAPI)"]
            direction TB
            REST["REST APIs<br/>Auth/Graphs/Chat/Skills"]
            WS["WebSocket<br/>Chat/Copilot/Runs"]
            SSE["SSE Stream<br/>Real-time Events"]
            CodeAPI["Code API<br/>Save/Run"]
        end

        subgraph Services["Service Layer"]
            direction TB
            GraphSvc["GraphService"]
            SkillSvc["SkillService"]
            MemorySvc["MemoryService"]
            McpSvc["McpClient<br/>Service"]
            ToolSvc["ToolService"]
        end

        subgraph Engine["Core Engine"]
            direction TB
            DeepBuilder["DeepAgents<br/>Builder"]
            CodeExec["Code Executor<br/>Sandboxed exec()"]
            Middleware["Middleware System<br/>Memory"]
            SkillSys["Skill System<br/>Progressive Disclosure"]
            MemorySys["Memory System<br/>Long/Short-term"]
        end
    end

    subgraph Row2[" "]
        direction LR

        subgraph Runtime["Runtime Layer"]
            direction TB
            LangGraph["LangGraph Runtime<br/>StateGraph"]
            Checkpoint["Checkpointer<br/>State Persistence"]
        end

        subgraph Data["Data Layer"]
            direction TB
            PG["PostgreSQL<br/>Graphs/Skills/Memory"]
            Redis["Redis<br/>Cache/Sessions"]
        end

        subgraph MCP["MCP Tool Ecosystem"]
            direction TB
            MCPServers["MCP Servers<br/>200+ Security Tools"]
            Tools["Tool Registry<br/>Unified Management"]
        end
    end

    Canvas --> REST
    CodeEditor --> CodeAPI
    Trace --> SSE
    Workspace --> REST
    Copilot --> WS

    REST --> Services
    WS --> Services
    SSE --> Services
    CodeAPI --> Services

    Services --> Engine
    Engine --> Runtime
    Runtime --> Data
    Runtime --> MCP

    MCPServers --> Tools

    style Row1 fill:transparent,stroke:transparent
    style Row2 fill:transparent,stroke:transparent

    style Frontend fill:#e1f5ff
    style API fill:#f3e5f5
    style Services fill:#fff3e0
    style Engine fill:#e8f5e8
    style Runtime fill:#fff8e1
    style Data fill:#fce4ec
    style MCP fill:#e0f2f1

```

### Core Modules

#### 1. Graph Build System — Two Paths

The system supports two graph building modes:

```mermaid
flowchart LR
    Service[GraphService] -->|graph_mode = code| CodeExec[Code Executor<br/>exec → StateGraph.compile]
    Service -->|canvas mode| DeepBuilder[DeepAgents Builder<br/>Manager-Worker topology]

    CodeExec --> LangGraph[LangGraph Runtime]
    DeepBuilder --> LangGraph

    style Service fill:#e1f5ff
    style CodeExec fill:#fff3e0
    style DeepBuilder fill:#e8f5e8
```

**Code Mode:**
- User writes standard LangGraph Python code in the browser editor
- Backend executes code in a sandboxed environment (restricted builtins, import whitelist, exec timeout)
- Extracts `StateGraph` instance from executed code, compiles and runs it
- Zero learning curve — LangGraph docs are the docs

**DeepAgents Canvas Mode:**
- Visual drag-and-drop builder for multi-agent orchestration
- Three node types: Agent, Code Agent, A2A Agent
- Builds Manager-Worker star topology via `deepagents.create_deep_agent()`

#### 2. DeepAgents Multi-Agent Orchestration

DeepAgents implements a star topology with one Manager coordinating multiple Workers:

```mermaid
flowchart TB
    Manager[Manager Agent<br/>useDeepAgents=True<br/>DeepAgent]

    Manager -->|task| Worker1[Worker 1<br/>CompiledSubAgent]
    Manager -->|task| Worker2[Worker 2<br/>CompiledSubAgent]
    Manager -->|task| Worker3[Worker 3<br/>CompiledSubAgent]
    Manager -->|task| CodeAgent[CodeAgent<br/>CompiledSubAgent]

    subgraph Backend["Shared Docker Backend"]
        Skills["/workspace/skills/<br/>Pre-loaded Skills"]
    end

    Worker1 --> Backend
    Worker2 --> Backend
    Worker3 --> Backend
    CodeAgent --> Backend

    style Manager fill:#e1f5ff
    style Worker1 fill:#fff4e1
    style Worker2 fill:#fff4e1
    style Worker3 fill:#fff4e1
    style CodeAgent fill:#fff4e1
    style Backend fill:#e8f5e8
```

**DeepAgents Build Pipeline:**

```
build_deep_agents_graph()
    ├── 1. resolve_all_configs()     — pure config extraction, no side effects
    ├── 2. setup shared backend      — Docker sandbox if needed
    ├── 3. preload_skills()          — batch preload with deduplication
    ├── 4. ModelResolver.resolve()   — unified LLM resolution with cache
    ├── 5. build workers             — agent_factory per node type
    └── 6. create_deep_agent()       — compile and finalize
```

**Key Design Decisions:**
- **No inheritance** — composition of dedicated resolvers (ModelResolver, ToolResolver, SkillsLoader)
- **Config resolution is pure** — no side effects, each node resolved exactly once
- **Model resolution is unified and cached** — same resolver for node models and memory models
- **Star Topology**: Manager connects directly to all SubAgents (not chain)
- **Shared Backend**: Docker backend shared across agents for skills and code execution

#### 3. Code Executor Security

The code executor runs user LangGraph code with multiple security layers:

| Layer | Protection |
|-------|-----------|
| **Builtins blacklist** | `open`, `eval`, `exec`, `compile`, `globals`, `locals`, `vars`, `dir` removed |
| **Import blocklist** | `os`, `sys`, `subprocess`, `socket`, `io`, `pathlib`, etc. blocked |
| **Import allowlist** | Only `langgraph`, `langchain`, `typing`, `json`, `pydantic`, etc. allowed |
| **Exec timeout** | 10 second limit via `signal.alarm` |
| **Invoke timeout** | 30 second limit via `asyncio.wait_for` |
| **Permission checks** | Save requires member role, Run requires viewer role |
| **Error sanitization** | Server file paths stripped from error messages |

#### 4. Skill System (Progressive Disclosure)

The skill system implements progressive disclosure to reduce token consumption:

```mermaid
sequenceDiagram
    participant Node as Agent Node
    participant Loader as SkillSandboxLoader
    participant Backend as Docker Backend

    Node->>Loader: Preload skills (batch, deduplicated)
    Loader->>Backend: Write skill files to /workspace/skills/
    Backend-->>Loader: Skills loaded

    Node->>Node: Agent sees skill summaries in system prompt
    Node->>Backend: Agent reads /workspace/skills/{skill_name}/SKILL.md
    Backend-->>Node: Agent receives full skill content on demand
```

**Components:**
- **SkillService**: CRUD operations with permission control
- **SkillsLoader**: Batch preloads skills to Docker backend with deduplication
- **FilesystemMiddleware**: Agent reads skill files from `/workspace/skills/` via filesystem access

#### 5. Memory System (Long/Short-term Memory)

```mermaid
sequenceDiagram
    participant User as User Input
    participant Middleware as MemoryMiddleware
    participant Manager as MemoryManager
    participant DB as PostgreSQL
    participant Agent as Agent

    User->>Middleware: User message
    Middleware->>Manager: Retrieve relevant memories
    Manager->>DB: Query memories by user_id/topics
    DB-->>Manager: Return memories
    Manager-->>Middleware: Inject memories into context
    Middleware->>Agent: Enhanced prompt with memories
    Agent-->>Middleware: Agent response
    Middleware->>Manager: Extract and persist new memories
    Manager->>DB: Persist memory
```

**Memory Types:**
- **Fact**: Factual knowledge (target info, vulnerabilities)
- **Procedure**: Procedural knowledge (successful attack paths)
- **Episodic**: Session-specific experiences
- **Semantic**: General security knowledge

### Core Workflows

#### Graph Building Flow

```mermaid
sequenceDiagram
    participant Frontend as Frontend
    participant API as REST API
    participant Service as GraphService
    participant Builder as DeepAgentsBuilder / CodeExecutor
    participant Runtime as LangGraph Runtime

    Frontend->>API: Save graph (nodes/edges or code)
    API->>Service: build graph
    Service->>Service: Detect mode (code vs canvas)

    alt Code Mode
        Service->>Builder: execute_code(code)
        Builder->>Runtime: StateGraph.compile()
    else Canvas Mode (DeepAgents)
        Service->>Builder: build_deep_agents_graph(nodes, edges)
        Builder->>Runtime: create_deep_agent() → compile()
    end

    Runtime-->>Service: CompiledStateGraph
    Service-->>API: Compiled graph
    API-->>Frontend: Ready
```

#### Graph Execution Flow

```mermaid
sequenceDiagram
    participant Frontend as Frontend
    participant API as REST API
    participant Service as GraphService
    participant Runtime as LangGraph Runtime
    participant SSE as SSE Stream

    Frontend->>API: POST /api/chat (SSE)
    API->>Service: Load and compile graph
    Service-->>Runtime: CompiledStateGraph
    Service->>Runtime: ainvoke({"messages": [...]})

    loop Each Node
        Runtime->>Runtime: Execute node
        Runtime->>SSE: Push event (node_start/node_end)
        SSE-->>Frontend: Stream update
    end

    Runtime-->>Service: Final result
    Service-->>SSE: End event
    SSE-->>Frontend: Stream complete
```

### Data Flow

**Frontend ↔ Backend:**
- **REST API**: Graph configuration, skill management, tool management, workspace operations
- **WebSocket (`/ws/chat`)**: Shared chat protocol for Chat, Copilot, and Skill Creator turns; Copilot sends `extension: { kind: "copilot" }` through the same WS
- **WebSocket (`/ws/runs`)**: Real-time run observation — event replay and status updates for active agent runs
- **Code API**: Save and run user LangGraph code
- **SSE Stream**: Real-time execution status, streaming output, node execution events

**Backend Internal:**
- **Code Mode**: `code_executor.execute_code()` → `StateGraph.compile()` → `ainvoke()`
- **Canvas Mode**: `build_deep_agents_graph()` → `create_deep_agent()` → `compile()` → `ainvoke()`
- **Copilot Turn**: `execute_copilot_turn()` → `CopilotService._get_copilot_stream()` → events persisted to `agent_run_events` via Run Center
- **LangGraph Runtime → MCP Servers → Tools**: Tool invocation and execution
- **Middleware → Agent → Model**: Request processing pipeline

**Backend ↔ Data Layer:**
- **PostgreSQL**: Graph configurations, skills, memories, sessions, workspaces, agent runs/events/snapshots (Run Center)
- **Redis**: Cache, rate limiting, temporary data

### Backend File Structure (Graph Module)

```
app/core/graph/
├── __init__.py                    # Exports build_deep_agents_graph()
├── deep_agents/
│   ├── builder.py                 # Build orchestration (no inheritance)
│   ├── config.py                  # Pure config extraction
│   ├── model_resolver.py          # Unified LLM resolution with cache
│   ├── agent_factory.py           # Creates agent/code_agent/a2a workers
│   ├── skills_loader.py           # Batch skills preload with dedup
│   ├── tool_resolver.py           # Tool name → instance resolution
│   └── middleware.py              # Memory middleware
├── node_secrets.py                # A2A secret hydration
└── runtime_prompt_template.py     # Runtime prompt variable substitution

app/core/code_executor.py          # Sandboxed exec() for Code mode
```
