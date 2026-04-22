# 统一执行引擎架构设计

Date: 2026-04-22
Status: Approved

## 分层架构

```
Layer 1: 入口层 (Trigger)         — REST API / WebSocket / Scheduler / Task Dispatch
Layer 2: 编排层 (Orchestration)   — AgentRunService / TaskService / ThreadService
Layer 3: 引擎层 (Engine)          — ExecutionEngine protocol + EngineRegistry
Layer 4: 运行时层 (Runtime)       — CLIRuntime(Docker) / GraphRuntime(LangGraph)
Layer 5: 持久化层 (Persistence)   — Repositories + Event Storage
Layer 6: 实时层 (Streaming)       — 统一 WebSocket 事件推送
```

## Layer 3: 引擎抽象（核心协议）

```python
# app/core/engine/protocol.py

class ExecutionEngine(Protocol):
    """所有执行引擎的统一接口。"""

    engine_kind: str  # "cli" | "graph" | "code"

    async def start(
        self,
        execution: Execution,
        release: AgentRelease,
        version: AgentVersion,
        prompt: str,
        context: ExecutionContext,
    ) -> None:
        """启动执行，事件通过 context.emit() 推送。"""
        ...

    async def cancel(self, execution: Execution) -> None:
        """取消正在运行的执行。"""
        ...

    async def send_message(self, execution: Execution, message: str) -> None:
        """向运行中的执行注入消息（human-in-the-loop）。"""
        ...


@dataclass
class ExecutionContext:
    """引擎执行时的上下文，提供事件发射和状态更新能力。"""
    db: AsyncSession
    execution_id: uuid.UUID
    run_id: uuid.UUID
    credentials: dict[str, str]
    auto_approve: bool

    async def emit(self, event_type: str, payload: dict) -> None:
        """发射一个执行事件 → 持久化 + WebSocket 推送。"""
        ...

    async def update_status(self, status: str) -> None:
        """更新 Execution 状态。"""
        ...

    async def complete(self, status: str, result_summary: str | None = None) -> None:
        """标记执行完成 → 更新 Run + Task 状态。"""
        ...
```

## Layer 3: 引擎注册表

```python
# app/core/engine/registry.py

class EngineRegistry:
    """runtime_kind → ExecutionEngine 的映射。"""

    _engines: dict[str, ExecutionEngine] = {}

    def register(self, runtime_kind: str, engine: ExecutionEngine) -> None: ...
    def get(self, runtime_kind: str) -> ExecutionEngine: ...

engine_registry = EngineRegistry()
```

## Layer 4: 两个引擎实现

### CLIEngine（已有代码包装）

```python
# app/core/engine/cli_engine.py

class CLIEngine(ExecutionEngine):
    """Docker 容器 + CLI Agent (Claude Code / Codex / OpenClaw)"""
    engine_kind = "cli"

    async def start(self, execution, release, version, prompt, context):
        # 包装现有 ExecutionRunner 逻辑：
        # 1. 从 release.runtime_binding 获取 runtime_type, custom_env
        # 2. 获取/创建 Docker 容器
        # 3. 注入 credentials, skills, config
        # 4. 通过 RuntimeProvider 执行
        # 5. 事件通过 context.emit() 推送
        ...
```

### GraphEngine（包装现有 LangGraph 代码）

```python
# app/core/engine/graph_engine.py

class GraphEngine(ExecutionEngine):
    """LangGraph 编译器 + 执行器"""
    engine_kind = "graph"

    async def start(self, execution, release, version, prompt, context):
        # 包装现有 chat_turn_executor 逻辑：
        # 1. 从 version.definition_payload 获取 {nodes, edges, variables}
        # 2. 编译为 LangGraph StateGraph
        # 3. 执行图，流式产出事件
        # 4. 事件通过 context.emit() 推送
        ...
```

## Layer 2: 统一编排器

```python
# app/services/execution_orchestrator.py

class ExecutionOrchestrator:
    """统一入口：创建 Run → 选择 Engine → 启动 Execution。"""

    async def dispatch(self, release_id, prompt, trigger_source, **kwargs):
        # 1. 创建 AgentRun + Execution
        # 2. 根据 release.runtime_kind 从 registry 获取 engine
        # 3. 构建 ExecutionContext
        # 4. engine.start(execution, release, version, prompt, context)
        ...

    async def dispatch_task(self, task_id, user_id):
        # 1. 加载 Task → Agent → active_release
        # 2. 构建 prompt from task.goal
        # 3. self.dispatch(release_id, prompt, trigger_source="task", task_id=task_id)
        ...

    async def dispatch_chat(self, thread_id, message, user_id):
        # 1. 加载 Thread → Agent → active_release
        # 2. self.dispatch(release_id, message, trigger_source="chat", thread_id=thread_id)
        ...
```

## Layer 6: 统一 WebSocket

```python
# app/websocket/execution_ws.py

# 单一 WebSocket 端点: /ws/executions/{execution_id}
# 所有引擎的事件都通过 ExecutionContext.emit() → 这里推送
# 客户端只需要订阅一个端点，不需要知道底层是 CLI 还是 Graph
```

## 现有代码映射

| 现有文件 | 归属层 | 处理方式 |
|---------|--------|---------|
| `execution_runner.py` | L4 Runtime | 包装进 CLIEngine.start() |
| `container_pool.py` | L4 Runtime | 不动，CLIEngine 内部使用 |
| `runtime_registry.py` | L4 Runtime | 不动，CLIEngine 内部使用 |
| `chat_turn_executor.py` | L4 Runtime | 包装进 GraphEngine.start() |
| `chat_ws_handler.py` | L1+L6 | 重写为统一 WS 端点 |
| `run_subscription_handler.py` | L6 | 删除，合并到统一 WS |
| `chat.py` (API) | L1 | 简化为调用 Orchestrator |
| `session_service.py` | L2 | 重写为 ThreadService 的薄包装 |
| `execution_lifecycle_service.py` | L2 | 合并到 ExecutionOrchestrator |
| `agent_run_service.py` | L2 | 保留，Orchestrator 内部使用 |
| `execution_service.py` | L5 | 保留，Context 内部使用 |
| `copilot_service.py` | 独立 | 修复 import，不改架构 |
| `node_secrets.py` | L4 Graph内部 | 从 version.definition_payload 读 |
| `node_tools.py` | L4 Graph内部 | 同上 |
| `scheduler.py` | L1 | 调用 Orchestrator.dispatch_task() |

## 实施顺序

### Phase 1: 建立引擎抽象（不破坏现有代码）
1. 创建 `app/core/engine/protocol.py` — ExecutionEngine + ExecutionContext
2. 创建 `app/core/engine/registry.py` — EngineRegistry
3. 创建 `app/core/engine/cli_engine.py` — 包装 ExecutionRunner
4. 创建 `app/core/engine/graph_engine.py` — 包装 chat_turn_executor
5. 创建 `app/services/execution_orchestrator.py` — 统一编排器

### Phase 2: 统一 WebSocket
6. 创建 `app/websocket/execution_ws.py` — 统一事件推送
7. ExecutionContext.emit() 接入 WebSocket 推送

### Phase 3: 重写入口层
8. 简化 chat.py → 调用 Orchestrator
9. 简化 scheduler.py → 调用 Orchestrator
10. 重写 session_service.py → ThreadService 包装
11. 删除 chat_ws_handler.py（合并到统一 WS）
12. 删除 run_subscription_handler.py

### Phase 4: 修复 Graph 引擎内部
13. node_secrets.py — 从 definition_payload 读
14. node_tools.py — 同上
15. runtime_prompt_template.py — 同上
16. deep_agents/config.py — 同上
17. copilot_service.py — 修复 import
