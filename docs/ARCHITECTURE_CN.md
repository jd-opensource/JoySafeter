# 架构设计

## 整体架构

JoySafeter 采用分层架构模式，各层职责清晰：

```mermaid
flowchart TB
    subgraph Row1[" "]
        direction LR

        subgraph Frontend["前端层 (Next.js + React)"]
            direction TB
            Canvas["DeepAgents 画布<br/>ReactFlow"]
            CodeEditor["代码编辑器<br/>CodeMirror"]
            Trace["执行追踪<br/>SSE Stream"]
            Workspace["工作空间管理<br/>RBAC"]
            Copilot["Copilot AI<br/>图构建助手"]
        end

        subgraph API["API 层 (FastAPI)"]
            direction TB
            REST["REST APIs<br/>Auth/Graphs/Chat/Skills"]
            SSE["SSE Stream<br/>实时事件"]
            CodeAPI["Code API<br/>保存/运行"]
        end

        subgraph Services["服务层"]
            direction TB
            GraphSvc["GraphService"]
            SkillSvc["SkillService"]
            MemorySvc["MemoryService"]
            McpSvc["McpClient<br/>Service"]
            ToolSvc["ToolService"]
        end

        subgraph Engine["核心引擎"]
            direction TB
            DeepBuilder["DeepAgents<br/>构建器"]
            CodeExec["代码执行器<br/>沙箱 exec()"]
            Middleware["中间件系统<br/>Memory"]
            SkillSys["技能系统<br/>渐进式加载"]
            MemorySys["记忆系统<br/>长/短期记忆"]
        end
    end

    subgraph Row2[" "]
        direction LR

        subgraph Runtime["运行时层"]
            direction TB
            LangGraph["LangGraph Runtime<br/>StateGraph"]
            Checkpoint["Checkpointer<br/>状态持久化"]
        end

        subgraph Data["数据层"]
            direction TB
            PG["PostgreSQL<br/>图/技能/记忆"]
            Redis["Redis<br/>缓存/会话"]
        end

        subgraph MCP["MCP 工具生态"]
            direction TB
            MCPServers["MCP Servers<br/>200+ 安全工具"]
            Tools["工具注册表<br/>统一管理"]
        end
    end

    Canvas --> REST
    CodeEditor --> CodeAPI
    Trace --> SSE
    Workspace --> REST
    Copilot --> REST

    REST --> Services
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

### 核心模块

#### 1. 图构建系统 — 两条路径

系统支持两种图构建模式：

```mermaid
flowchart LR
    Service[GraphService] -->|graph_mode = code| CodeExec[代码执行器<br/>exec → StateGraph.compile]
    Service -->|画布模式| DeepBuilder[DeepAgents 构建器<br/>Manager-Worker 拓扑]

    CodeExec --> LangGraph[LangGraph Runtime]
    DeepBuilder --> LangGraph

    style Service fill:#e1f5ff
    style CodeExec fill:#fff3e0
    style DeepBuilder fill:#e8f5e8
```

**Code 模式：**
- 用户在浏览器编辑器中编写标准 LangGraph Python 代码
- 后端在沙箱环境中执行代码（受限 builtins、import 白名单、执行超时）
- 从执行结果中提取 `StateGraph` 实例，编译并运行
- 零学习成本 — LangGraph 官方文档就是使用文档

**DeepAgents 画布模式：**
- 可视化拖拽构建多智能体编排
- 三种节点类型：Agent、Code Agent、A2A Agent
- 通过 `deepagents.create_deep_agent()` 构建 Manager-Worker 星型拓扑

#### 2. DeepAgents 多智能体编排

DeepAgents 实现星型拓扑，一个 Manager 协调多个 Worker：

```mermaid
flowchart TB
    Manager[Manager Agent<br/>useDeepAgents=True<br/>DeepAgent]

    Manager -->|task| Worker1[Worker 1<br/>CompiledSubAgent]
    Manager -->|task| Worker2[Worker 2<br/>CompiledSubAgent]
    Manager -->|task| Worker3[Worker 3<br/>CompiledSubAgent]
    Manager -->|task| CodeAgent[CodeAgent<br/>CompiledSubAgent]

    subgraph Backend["共享 Docker 后端"]
        Skills["/workspace/skills/<br/>预加载技能"]
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

**DeepAgents 构建流水线：**

```
build_deep_agents_graph()
    ├── 1. resolve_all_configs()     — 纯配置提取，无副作用
    ├── 2. 初始化共享后端              — 按需创建 Docker 沙箱
    ├── 3. preload_skills()          — 批量预加载，自动去重
    ├── 4. ModelResolver.resolve()   — 统一 LLM 解析，带缓存
    ├── 5. 构建 Worker               — agent_factory 按节点类型创建
    └── 6. create_deep_agent()       — 编译并最终化
```

**关键设计决策：**
- **无继承** — 使用专用解析器组合（ModelResolver、ToolResolver、SkillsLoader）
- **配置解析是纯函数** — 无副作用，每个节点只解析一次
- **模型解析统一且带缓存** — 节点模型和记忆模型共用同一个解析器
- **星型拓扑**：Manager 直接连接所有 SubAgent（非链式）
- **共享后端**：Docker 后端在所有 Agent 间共享，用于技能和代码执行

#### 3. 代码执行器安全

代码执行器通过多层安全机制运行用户 LangGraph 代码：

| 安全层 | 保护措施 |
|--------|---------|
| **Builtins 黑名单** | 移除 `open`、`eval`、`exec`、`compile`、`globals`、`locals`、`vars`、`dir` |
| **Import 黑名单** | 封锁 `os`、`sys`、`subprocess`、`socket`、`io`、`pathlib` 等 |
| **Import 白名单** | 仅允许 `langgraph`、`langchain`、`typing`、`json`、`pydantic` 等 |
| **执行超时** | exec 10 秒限制（`signal.alarm`） |
| **调用超时** | ainvoke 30 秒限制（`asyncio.wait_for`） |
| **权限检查** | 保存需要 member 角色，运行需要 viewer 角色 |
| **错误脱敏** | 从错误信息中移除服务器文件路径 |

#### 4. 技能系统（渐进式加载）

```mermaid
sequenceDiagram
    participant Node as Agent 节点
    participant Loader as SkillSandboxLoader
    participant Backend as Docker 后端

    Node->>Loader: 预加载技能（批量，去重）
    Loader->>Backend: 写入技能文件到 /workspace/skills/
    Backend-->>Loader: 技能加载完成

    Node->>Node: Agent 在系统提示中看到技能摘要
    Node->>Backend: Agent 按需读取 /workspace/skills/{skill_name}/SKILL.md
    Backend-->>Node: Agent 获取完整技能内容
```

#### 5. 记忆系统（长/短期记忆）

```mermaid
sequenceDiagram
    participant User as 用户输入
    participant Middleware as MemoryMiddleware
    participant Manager as MemoryManager
    participant DB as PostgreSQL
    participant Agent as Agent

    User->>Middleware: 用户消息
    Middleware->>Manager: 检索相关记忆
    Manager->>DB: 按 user_id/主题查询
    DB-->>Manager: 返回记忆
    Manager-->>Middleware: 注入记忆到上下文
    Middleware->>Agent: 增强后的提示
    Agent-->>Middleware: Agent 响应
    Middleware->>Manager: 提取并持久化新记忆
    Manager->>DB: 保存记忆
```

### 数据流

**前端 ↔ 后端：**
- **REST API**：图配置、技能管理、工具管理、工作空间操作
- **Code API**：保存和运行用户 LangGraph 代码
- **SSE Stream**：实时执行状态、流式输出、节点执行事件

**后端内部：**
- **Code 模式**：`code_executor.execute_code()` → `StateGraph.compile()` → `ainvoke()`
- **画布模式**：`build_deep_agents_graph()` → `create_deep_agent()` → `compile()` → `ainvoke()`
- **LangGraph Runtime → MCP Servers → Tools**：工具调用和执行
- **Middleware → Agent → Model**：请求处理管道

**后端 ↔ 数据层：**
- **PostgreSQL**：图配置、技能、记忆、会话、工作空间
- **Redis**：缓存、限流、会话状态、临时数据

### 后端文件结构（图模块）

```
app/core/graph/
├── __init__.py                    # 导出 build_deep_agents_graph()
├── deep_agents/
│   ├── builder.py                 # 构建编排（无继承）
│   ├── config.py                  # 纯配置提取
│   ├── model_resolver.py          # 统一 LLM 解析，带缓存
│   ├── agent_factory.py           # 创建 agent/code_agent/a2a worker
│   ├── skills_loader.py           # 批量技能预加载，去重
│   ├── tool_resolver.py           # 工具名 → 实例解析
│   └── middleware.py              # Memory 中间件
├── node_secrets.py                # A2A secret 处理
└── runtime_prompt_template.py     # 运行时 prompt 变量替换

app/core/code_executor.py          # Code 模式沙箱执行
```
