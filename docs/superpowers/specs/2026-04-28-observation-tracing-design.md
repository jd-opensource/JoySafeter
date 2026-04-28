# Observation Tracing System Design

> 产品内调试运行的全链路 LLM 交互追踪，对齐 Langfuse observation 模型，跨全部引擎统一持续呈现。

## 1. 目标

在 AgentBuilder 中提供"调试运行"功能：用户点击调试按钮 → 后端用预设 prompt 执行 agent → WebSocket 实时推送结构化 observation tree 到前端 → 前端以 Langfuse 风格的 tree/timeline 视图持续渲染 LLM 调用链路。

覆盖四个引擎：GraphEngine / CLIEngine / CodeEngine / CopilotEngine。

## 2. 核心决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 传输层 | 复用现有 WebSocket 连接，独立 `channel: "observation"` | 不多开连接，不改 EventBus |
| 数据模型 | 独立 ObservationCollector + 独立 observation 表 | 树形数据与扁平 ExecutionEvent 形状不同 |
| 调试入口 | 复用 Orchestrator + `debug=True` 开关 | 不引入新入口，所有引擎共享同一路径 |
| 采集方式 | 各引擎各自采集 | 引擎 I/O 格式差异大，统一适配器反而增加耦合 |
| 持久化 | 独立 traces + observations 表 | 支持事后回看历史调试 trace |
| 类型体系 | 完全对齐 Langfuse ObservationType | 未来可直接导出到 Langfuse |

## 3. 数据模型（对齐 Langfuse）

### 3.1 ObservationType

```python
class ObservationType(StrEnum):
    SPAN       = "SPAN"
    EVENT      = "EVENT"        # 瞬时事件，无 end_time
    GENERATION = "GENERATION"   # LLM 调用
    AGENT      = "AGENT"        # Agent 节点执行
    TOOL       = "TOOL"         # 工具调用
    CHAIN      = "CHAIN"        # LangChain chain 步骤
    RETRIEVER  = "RETRIEVER"    # RAG 向量检索
    EMBEDDING  = "EMBEDDING"    # Embedding 生成
    EVALUATOR  = "EVALUATOR"    # 评估步骤
    GUARDRAIL  = "GUARDRAIL"    # 安全检查
```

v1 引擎主动发射：AGENT / GENERATION / TOOL / EVENT / CHAIN / SPAN。其余类型枚举保留，引擎暂不发射。

### 3.2 ObservationLevel

```python
class ObservationLevel(StrEnum):
    DEBUG   = "DEBUG"
    DEFAULT = "DEFAULT"
    WARNING = "WARNING"
    ERROR   = "ERROR"
```

### 3.3 Trace 模型

```python
class Trace(Base):
    __tablename__ = "traces"

    id: uuid.UUID                          # PK, = execution_id
    name: str                              # agent 名称
    workspace_id: uuid.UUID

    start_time: datetime
    end_time: datetime | None
    status: str                            # running / completed / error / cancelled
                                           # JoySafeter 扩展，Langfuse 无此字段

    input: dict | None                     # 用户的调试 prompt
    output: dict | None                    # 最终输出摘要
    meta: dict | None                      # agent_version_id, definition_kind, etc.
                                           # 属性名用 meta 避免与 SQLAlchemy Base.metadata 冲突
                                           # 数据库列名仍为 "metadata"：Column("metadata", JSONB)

    environment: str = "debug"             # 调试运行恒为 "debug"
    tags: list[str] = []
    release: str | None = None             # agent_version 的 release 标识
    version: str | None = None             # agent_version 版本号
    session_id: str | None = None          # 同一用户连续调试同一 agent 归为一个 session
    bookmarked: bool = False
    public: bool = False

    # 聚合统计（finalize 时写入）
    total_observations: int = 0
    total_tokens: int = 0
    total_cost: Decimal | None = None
    duration_ms: int | None = None

    # 关联
    execution_id: uuid.UUID                # FK → executions
    agent_version_id: uuid.UUID
    user_id: uuid.UUID

    created_at: datetime
```

### 3.4 Observation 模型

```python
class Observation(Base):
    __tablename__ = "observations"

    id: uuid.UUID
    trace_id: uuid.UUID                    # FK → traces.id
    parent_observation_id: uuid.UUID | None

    type: ObservationType
    name: str
    level: ObservationLevel = ObservationLevel.DEFAULT
    status_message: str | None = None      # level=ERROR 时填入错误摘要
    environment: str = "debug"

    start_time: datetime
    end_time: datetime | None              # EVENT 类型始终为 None
    completion_start_time: datetime | None # GENERATION 专用：首 token 时间

    input: dict | None
    output: dict | None
    meta: dict | None                      # 属性名用 meta，列名仍为 "metadata"

    # GENERATION 专用
    model: str | None
    model_parameters: dict | None
    usage_details: dict | None             # {"input": N, "output": N, "total": N, "cached_input": N, ...}
    cost_details: dict | None              # {"input": N, "output": N, "total": N}
    prompt_name: str | None
    prompt_version: int | None

    # GENERATION 上的工具定义和 LLM 输出的 tool_calls
    tool_definitions: dict | None          # Map<name, {description, parameters}>
    tool_calls: list | None                # [{id, name, arguments}]
    tool_call_names: list[str] | None      # 并行数组，便于过滤

    # 关联
    execution_id: uuid.UUID
    workspace_id: uuid.UUID
    created_at: datetime
```

**字段归属边界**:
- `tool_definitions` + `tool_calls` + `tool_call_names` → 写在 **GENERATION** observation 上（LLM 定义了哪些工具、输出了哪些 tool_calls）
- 每个 **TOOL** observation → `input` 存 arguments，`output` 存 result，`name` 存 tool_name
- 文件操作 → **EVENT** observation，`metadata` 承载 `file.path / file.operation / file.size_bytes / file.content_preview`

### 3.5 Session 约定

同一用户连续调试同一 `agent_version_id` 的多次 trace，自动归为同一 session:
```
session_id = f"debug-{user_id}-{agent_version_id}-{date}"
```

## 4. 架构

### 4.1 整体拓扑

```
Engine (Graph/CLI/Code/Copilot)
    │ 调用 collector API
    ▼
ObservationCollector (core/observation/collector.py)
    │ 管理 span 生命周期、树形关系
    ├──► ObservationWriter (core/observation/writer.py)
    │      攒批写入 observations 表
    └──► ObservationBroadcaster (core/observation/broadcaster.py)
           推送到现有 WebSocket 连接 {channel: "observation"}
```

### 4.2 ObservationCollector

一次调试运行绑定一个 collector 实例。

```python
class ObservationCollector:
    def __init__(
        self,
        trace_id: uuid.UUID,
        execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
        writer: ObservationWriter,
        broadcaster: ObservationBroadcaster,
    ): ...

    # Span 生命周期
    def start_span(self, type, name, *, parent_id=None, input=None, metadata=None, level=DEFAULT) -> SpanHandle
    def end_span(self, span, *, output=None, level=None) -> None

    # 便捷方法（对齐 Langfuse 类型）
    def record_generation(self, name, *, parent_id, input, output, model, usage_details, cost_details, completion_start_time=None, latency_ms, ...) -> uuid.UUID
    def record_tool(self, name, *, parent_id, input, output, latency_ms, ...) -> uuid.UUID
    def record_event(self, name, *, parent_id=None, input=None, metadata=None, ...) -> uuid.UUID
    def start_agent(self, name, *, parent_id=None, node_config=None, ...) -> SpanHandle
    def start_chain(self, name, *, parent_id=None, ...) -> SpanHandle
    def record_retriever(self, name, *, parent_id, input, output, ...) -> uuid.UUID
    def record_embedding(self, name, *, parent_id, input, output, model, usage_details, ...) -> uuid.UUID

    async def flush(self) -> None
    async def finalize(self) -> None  # 关闭未关闭 span(WARNING), 计算聚合, 最终 flush
```

### 4.3 SpanHandle

```python
@dataclass
class SpanHandle:
    observation_id: uuid.UUID
    collector: ObservationCollector

    def child_span(self, type, name, **kwargs) -> SpanHandle
    def record_generation(self, name, **kwargs) -> uuid.UUID
    def record_tool(self, name, **kwargs) -> uuid.UUID
    def record_event(self, name, **kwargs) -> uuid.UUID
    def end(self, **kwargs) -> None
```

### 4.4 ObservationWriter

攒批写入。策略：最多 10 条或 300ms，先到先 flush。

```python
class ObservationWriter:
    async def insert(self, observation: Observation) -> None
    async def update(self, observation_id: uuid.UUID, fields: dict) -> None
    async def flush(self) -> None          # collector.flush() 委托到此方法
    async def finalize(self) -> None       # flush + 清空所有 buffer + 关闭资源
```

### 4.5 ObservationBroadcaster

复用现有 WebSocket 连接。不走 EventBus，直接调用 ws_manager。
持有每 trace 单调递增的 `seq` 计数器（前端用于消息去重和顺序校验）。

```python
class ObservationBroadcaster:
    def __init__(self, execution_id: uuid.UUID):
        self._execution_id = execution_id
        self._seq = 0                      # 每 trace 单调递增

    async def emit(self, event: str, observation: dict) -> None
    # event: span_open / span_update / span_close / record / trace_complete
```

## 5. 引擎接入

### 5.1 Orchestrator 注入

```python
# orchestrator.py
async def _dispatch(self, context, ...):
    collector = None
    if context.debug:
        collector = ObservationCollector(
            trace_id=context.execution_id,
            execution_id=context.execution_id,
            workspace_id=context.workspace_id,
            writer=ObservationWriter(db_session_factory),
            broadcaster=ObservationBroadcaster(context.execution_id),
        )
        context.collector = collector
    try:
        engine = self._registry.get(runtime_kind)
        await engine.start(context, ...)
    except Exception as exc:
        if collector:
            collector.record_event(
                name=f"error:{type(exc).__name__}",
                input={"message": str(exc), "traceback": traceback.format_exc()},
                level=ObservationLevel.ERROR,
            )
        raise
    finally:
        if collector:
            await collector.finalize()
            # finalize 自动关闭未关闭的 span 时，已记录 ERROR 级 event 的 trace
            # 状态置为 "error"；未记录 ERROR 的置为 "completed"。
            # 自动关闭的 span 标记 level=WARNING，不会覆盖已存在的 ERROR 标记。
```

ExecutionContext 扩展:
```python
@dataclass
class ExecutionContext:
    # ... 已有字段 ...
    debug: bool = False
    collector: ObservationCollector | None = None
```

### 5.2 GraphEngine

采集方式：LangChain CallbackHandler + FileTrackingProxy。

```python
# ObservationCallbackHandler (instrumentation/langchain_handler.py)
# 实现 LangChain BaseCallbackHandler

class ObservationCallbackHandler(BaseCallbackHandler):
    def on_llm_start(...)       → collector.start_span(GENERATION, ...)
    def on_llm_end(...)         → span.end(output={completion, usage_details, cost_details})
    def on_tool_start(...)      → collector.start_span(TOOL, ...)
    def on_tool_end(...)        → span.end(output={result})
    def on_chain_start(...)     → collector.start_agent(...) (if worker dispatch) / start_chain(...)
    def on_chain_end(...)       → span.end(...)
```

文件操作：FileTrackingProxy 接收 collector，文件读写时发射 EVENT:
```python
collector.record_event(
    name=f"file:{operation} {path}",
    parent_id=current_tool_span.observation_id,
    metadata={"file.path": path, "file.operation": operation, "file.size_bytes": size}
)
```

### 5.3 CLIEngine

采集方式：CLIMessage 流 pattern match (instrumentation/cli_extractor.py)。

```python
class CLIObservationExtractor:
    def __init__(self, collector, root_span): ...

    async def process_message(self, msg: CLIMessage) -> None:
        match msg.type:
            case "text":      # 累积 LLM 输出
            case "tool_use":  # flush generation + 开启 TOOL span
            case "tool_result":  # 关闭 TOOL span
            case "usage":     # 更新 usage_details

    async def flush_pending(self) -> None:  # 收尾：flush 最后一个 generation
```

CLI 引擎的根 span 类型为 **AGENT**（单 agent 执行）。

### 5.4 CodeEngine

采集方式：与 GraphEngine 共用 ObservationCallbackHandler。

```python
callbacks = []
if collector:
    root_span = collector.start_agent(name="code_executor", ...)
    callbacks.append(ObservationCallbackHandler(collector, root_span))
```

### 5.5 CopilotEngine

采集方式：流式累积后 record_generation (instrumentation/copilot_extractor.py)。

```python
if collector:
    collector.record_generation(
        name=f"copilot:{model_name}",
        input={"prompt": prompt, "mode": mode},
        output={"completion": accumulated_text},
        model=model_name,
        usage_details=extracted_usage,
        cost_details=None,                 # v1 Copilot 不计算 cost
        latency_ms=elapsed_ms,
    )
```

### 5.6 引擎采集汇总

| 引擎 | 采集组件 | AGENT | GENERATION | TOOL | EVENT (file) | CHAIN |
|---|---|---|---|---|---|---|
| Graph | LangChain CallbackHandler + FileTrackingProxy | on_chain (worker) | on_llm | on_tool | proxy 拦截 | on_chain (非 worker) |
| CLI | CLIObservationExtractor | exec root span | text 累积 | tool_use/result | tool_name 推断 | — |
| Code | LangChain CallbackHandler | root span | on_llm | executor 拦截 | sandbox 文件 | on_chain |
| Copilot | CopilotObservationExtractor | — | 流累积 | — | — | — |

## 6. WebSocket 传输协议

### 6.1 消息格式

```jsonc
{
  "channel": "observation",
  "trace_id": "uuid",
  "seq": 1,
  "event": "span_open",        // span_open | span_update | span_close | record | trace_complete
  "observation": {
    "id": "uuid",
    "parent_observation_id": "uuid | null",
    "type": "GENERATION",
    "name": "gpt-4o call",
    "level": "DEFAULT",
    "status_message": null,
    "start_time": "ISO8601",
    "end_time": null,
    "completion_start_time": null,
    "input": { ... },
    "output": null,
    "metadata": { ... },
    "model": "gpt-4o",
    "usage_details": { "input": 1200, "output": 340, "total": 1540 },
    "cost_details": { "input": 0.006, "output": 0.0102, "total": 0.0162 },
    "tool_calls": null,
    "tool_call_names": null
  }
}
```

### 6.2 事件语义

| event | 含义 | 触发时机 |
|---|---|---|
| `span_open` | 新 span 开始 | start_span / start_agent / start_chain |
| `span_update` | span 中间更新（流式 token 追加等） | v1 仅 CopilotEngine 在流式 GENERATION 时发射（可选） |
| `span_close` | span 结束 | end_span，填入 end_time + output |
| `record` | 瞬时事件 | record_event / record_generation / record_tool（已完成的） |
| `trace_complete` | 整个 trace 结束 | collector.finalize() |

### 6.3 典型事件时序（Graph 调试运行）

```
1. span_open   AGENT  "root:Manager"
2. span_open   GENERATION  parent=root
3. span_close  GENERATION  output={completion, usage_details}
4. span_open   TOOL  "web_search"  parent=root
5. span_close  TOOL  output={result}
6. span_open   AGENT  "worker:Researcher"  parent=root
7. span_open   GENERATION  parent=worker
8. span_close  GENERATION
9. span_open   TOOL  "file_write"  parent=worker
10. record     EVENT  "file:write /tmp/report.md"  parent=tool
11. span_close TOOL
12. span_close AGENT  "worker:Researcher"
13. span_open  GENERATION  parent=root  (汇总)
14. span_close GENERATION
15. span_close AGENT  "root:Manager"
16. trace_complete  {total_tokens, total_cost, duration_ms}
```

## 7. 调试运行 API

```
POST /api/v1/executions/debug
Body: {
  "agent_version_id": "uuid",
  "prompt": "帮我分析这份数据",
  "variables": { ... }
}
Response: {
  "execution_id": "uuid",       // = trace_id
  "ws_topic": "execution:{id}"
}

GET /api/v1/traces/{trace_id}
Response: Trace 元信息 + 聚合统计

GET /api/v1/traces/{trace_id}/observations
Response: 该 trace 下所有 observation 扁平列表（前端重建树）
Query: ?type=GENERATION（可选过滤）

GET /api/v1/traces?workspace_id=...&agent_version_id=...
Response: 历史调试 trace 列表，按时间倒序，支持分页
```

## 8. 前端 Trace Viewer

```
DebugPanel
  ├── ObservationProvider (Context)
  │     监听 WebSocket channel="observation"
  │     增量构建 ObservationNode[] 树
  │     span_open → 插入 / span_close → 更新 / record → 插入即完成
  │
  ├── TraceTreeView (默认视图)
  │     缩进层级、图标按 type、颜色编码
  │     每行: name + 耗时 + token 数
  │     点击展开 input/output
  │
  ├── TraceTimelineView
  │     横向 Gantt 条形图
  │     span_open 时出现条，span_close 时定格
  │     并行 worker 上下排列
  │
  └── DetailPanel
        GENERATION: 对话渲染 + model/usage/cost
        TOOL: arguments + result
        EVENT (file): 路径 + 操作 + 内容预览
        AGENT: 节点配置 + 子树统计
```

颜色编码:
- AGENT → 蓝色
- GENERATION → 紫色
- TOOL → 绿色
- EVENT → 黄色
- CHAIN → 灰色
- ERROR level → 红色

### 8.1 ObservationNode

```typescript
interface ObservationNode {
  id: string;
  parentObservationId: string | null;
  type: ObservationType;
  name: string;
  level: ObservationLevel;
  statusMessage: string | null;
  startTime: number;
  endTime: number | null;
  completionStartTime: number | null;
  duration: number | null;
  input: any;
  output: any;
  metadata: Record<string, any>;
  model?: string;
  usageDetails?: Record<string, number>;
  costDetails?: Record<string, number>;
  toolCalls?: Array<{ id: string; name: string; arguments: any }>;
  toolCallNames?: string[];
  children: ObservationNode[];
  depth: number;
  totalTokens: number;
  totalCost: number;
}
```

Tree building 算法参照 Langfuse `tree-building.ts`：迭代式（非递归），O(N) 拓扑排序，bottom-up 聚合 cost/tokens。

## 9. 模块结构

### 9.1 新增

```
backend/app/core/observation/
├── __init__.py
├── types.py                       # ObservationType, ObservationLevel, SpanHandle
├── collector.py                   # ObservationCollector
├── writer.py                      # ObservationWriter 攒批持久化
├── broadcaster.py                 # ObservationBroadcaster WebSocket 推送
├── model.py                       # Trace + Observation SQLAlchemy models
└── instrumentation/
    ├── __init__.py
    ├── langchain_handler.py       # ObservationCallbackHandler (Graph + Code)
    ├── cli_extractor.py           # CLIObservationExtractor
    ├── copilot_extractor.py       # CopilotObservationExtractor
    └── file_tracker.py            # 文件操作 → EVENT

backend/app/api/routes/traces.py   # API: POST debug, GET traces, GET observations
backend/migrations/versions/xxxx_add_traces_observations.py
```

### 9.2 修改

| 文件 | 改动性质 |
|---|---|
| `core/engine/protocol.py` | ExecutionContext 加 `debug` + `collector` 字段 |
| `core/engine/orchestrator.py` | `_dispatch` 构造 collector、finally finalize |
| `core/engine/graph_engine.py` | 传 collector 到 builder + 注入 callback |
| `core/engine/cli_engine.py` | 传 collector 到 runner |
| `core/engine/code_engine.py` | 注入 callback |
| `core/engine/copilot_engine.py` | 流累积后 record_generation |
| `core/graph/deep_agents/builder.py` | 接收 collector 参数传递给 agent_factory |
| `core/agent/cli_backends/execution_runner.py` | 使用 CLIObservationExtractor |
| `core/agent/backends/file_tracking_proxy.py` | 接收 collector 发射 EVENT |

### 9.3 删除

| 文件 | 原因 |
|---|---|
| `core/agent/langfuse_callback.py` | 被 `observation/instrumentation/langchain_handler.py` 替代 |
| `core/trace_context.py` | 被 collector trace_id 替代；删除前需 grep 确认无外部调用者（如有则标记 deprecated 保留） |

## 10. 数据库迁移

```python
def upgrade():
    # traces 表
    op.create_table("traces",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("input", JSONB),
        sa.Column("output", JSONB),
        sa.Column("metadata", JSONB),
        sa.Column("environment", sa.String(50), server_default="debug"),
        sa.Column("tags", sa.ARRAY(sa.String), server_default="{}"),
        sa.Column("release", sa.String(255)),
        sa.Column("version", sa.String(100)),
        sa.Column("session_id", sa.String(255)),
        sa.Column("bookmarked", sa.Boolean, server_default="false"),
        sa.Column("public", sa.Boolean, server_default="false"),
        sa.Column("total_observations", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("total_cost", sa.Numeric(12, 6)),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("agent_version_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_traces_workspace_created", "traces", ["workspace_id", "created_at"])
    op.create_index("ix_traces_execution", "traces", ["execution_id"], unique=True)
    op.create_index("ix_traces_session", "traces", ["session_id", "created_at"])

    # observations 表
    op.create_table("observations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("trace_id", UUID, sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_observation_id", UUID),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("level", sa.String(10), nullable=False, server_default="DEFAULT"),
        sa.Column("status_message", sa.Text),
        sa.Column("environment", sa.String(50), server_default="debug"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("completion_start_time", sa.DateTime(timezone=True)),
        sa.Column("input", JSONB),
        sa.Column("output", JSONB),
        sa.Column("metadata", JSONB),
        sa.Column("model", sa.String(100)),
        sa.Column("model_parameters", JSONB),
        sa.Column("usage_details", JSONB),
        sa.Column("cost_details", JSONB),
        sa.Column("prompt_name", sa.String(255)),
        sa.Column("prompt_version", sa.Integer),
        sa.Column("tool_definitions", JSONB),
        sa.Column("tool_calls", JSONB),
        sa.Column("tool_call_names", sa.ARRAY(sa.String)),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_observations_trace_time", "observations", ["trace_id", "start_time"])
    op.create_index("ix_observations_parent", "observations", ["parent_observation_id"])
    op.create_index("ix_observations_trace_type", "observations", ["trace_id", "type"])
```

## 11. 测试策略

```
backend/tests/test_core/test_observation/
├── test_types.py                  # 枚举值与 Langfuse 对齐
├── test_collector.py              # span 生命周期、树形嵌套、finalize 自动关闭
├── test_writer.py                 # 攒批策略：max_batch / delayed flush / finalize
├── test_broadcaster.py            # WebSocket 消息格式、seq 单调递增
├── test_langchain_handler.py      # on_llm/on_tool/on_chain → observation 映射
├── test_cli_extractor.py          # CLIMessage → observation 提取
└── test_trace_api.py              # API 端到端
```

所有测试保持纯单元测试风格（无 DB/Docker），通过 Protocol 注入 fake writer/broadcaster。

## 12. 实施优先级

**Phase 1 — 核心层**
- `observation/types.py` → `model.py` → `writer.py` → `broadcaster.py` → `collector.py`
- Alembic 迁移
- 全部单元测试

**Phase 2 — 引擎接入**
- `instrumentation/langchain_handler.py` → graph_engine + code_engine
- `instrumentation/cli_extractor.py` → cli_engine + execution_runner
- `instrumentation/copilot_extractor.py` → copilot_engine
- `instrumentation/file_tracker.py` → file_tracking_proxy
- `protocol.py` / `orchestrator.py` 扩展

**Phase 3 — API + 前端**
- `routes/traces.py`
- 前端 ObservationProvider + TraceTreeView + TraceTimelineView + DetailPanel

## 13. v1 显式不做

| Langfuse 概念 | 说明 |
|---|---|
| Score | 调试场景不需要打分 |
| Prompt management | 调试 prompt 是临时的 |
| Dataset / DatasetRunItem | 不做 |
| Annotation Queue | 不做 |
| Model matching cost table | 引擎自算 cost |
| OTEL ingestion | 所有 observation 通过 collector API 进入 |
| Public/bookmarked UI | 字段保留但 UI 不暴露 |
