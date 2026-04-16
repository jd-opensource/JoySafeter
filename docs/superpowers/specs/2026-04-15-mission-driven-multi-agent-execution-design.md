# Mission-Driven Multi-Agent Execution Platform

> 将 Multica 的 Agent-as-Teammate 模式与 JoySafeter 的安全领域能力深度融合，
> 构建统一的多 Agent 云端执行平台。

**日期:** 2026-04-15
**状态:** Draft
**分支:** mul_cli

---

## 1. 产品定位

**JoySafeter 从"AI 安全对话工具"升级为"安全团队的 AI 协作平台"。**

核心循环：

```
Mission 进入看板 → 分配给 Agent（或人）→ Agent 在云端容器自主执行
→ 调用安全 Skill 和工具链 → 实时查看进度、可干预
→ 结果沉淀为新 Skill → 团队安全能力持续增长
```

### 1.1 与 Multica 的差异化

| 维度 | Multica | JoySafeter |
|------|---------|------------|
| 任务模型 | Issue（通用开发任务） | Mission（带明确目标的安全任务委派） |
| Agent 能力 | 通用编码 | 安全领域专家（Skill 库 + 工具链） |
| Skill 沉淀 | 简单 name+content | 版本管理 + 协作者权限 + 文件附件 + allowed_tools |
| 执行编排 | 单 Agent 单任务 | 多 Agent 协同（Graph 编排 / Coordinator 模式） |
| 工具集成 | 无 | MCP 200+ 安全工具（后续阶段） |
| 可观测性 | 消息流 | 消息流 + Langfuse trace + 执行追踪 |

### 1.2 四种执行触发模式

| 模式 | 描述 | 场景 |
|------|------|------|
| Mission-driven | 看板上创建 Mission，分配给 Agent | "对 target.apk 做 OWASP Mobile Top 10 审计" |
| Chat-driven | 对话中触发执行 | 现有模式，保持不变 |
| Graph-driven | 可视化工作流编排多 Agent | 标准化安全审计流水线 |
| Coordinator-driven | LangGraph Agent 动态调度 CLI Agent | 探索性渗透测试 |

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Mission  │  │  Chat    │  │  Graph   │  │  Execution  │ │
│  │  Board   │  │  Page    │  │  Editor  │  │  Monitor    │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│       │              │             │               │         │
│       └──────────────┴─────────────┴───────────────┘         │
│                          │                                    │
│                    WebSocket + REST                           │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────┴─────────────────────────────────────┐
│                     Backend (FastAPI)                          │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                   Orchestrator Layer                      │ │
│  │  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │ │
│  │  │  Mission     │  │  Execution   │  │  Coordinator  │  │ │
│  │  │  Dispatcher  │  │  Engine      │  │  (LangGraph)  │  │ │
│  │  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │ │
│  │         └────────────────┼───────────────────┘          │ │
│  └──────────────────────────┼──────────────────────────────┘ │
│                             │                                 │
│  ┌──────────────────────────┴──────────────────────────────┐ │
│  │                  Unified Execution Layer                  │ │
│  │                                                          │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐│ │
│  │  │ Execution  │  │  Step      │  │  Event Stream      ││ │
│  │  │ (run)      │  │  (per-agent│  │  (unified protocol)││ │
│  │  │            │  │   action)  │  │                    ││ │
│  │  └────────────┘  └────────────┘  └────────────────────┘│ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             │                                 │
│  ┌──────────────────────────┴──────────────────────────────┐ │
│  │                Runtime Provider Layer                     │ │
│  │                                                          │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐│ │
│  │  │LangGraph │ │ Claude   │ │ Codex    │ │ OpenClaw   ││ │
│  │  │ Runtime  │ │ Code RT  │ │ Runtime  │ │ Runtime    ││ │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────┘│ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             │                                 │
│  ┌──────────────────────────┴──────────────────────────────┐ │
│  │              Container Management Layer                   │ │
│  │  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐ │ │
│  │  │ CLI Container│  │ Skill Injector│  │ Sandbox Pool │ │ │
│  │  │ Service      │  │               │  │ (existing)   │ │ │
│  │  └──────────────┘  └───────────────┘  └──────────────┘ │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │   Docker Containers  │
              │  ┌────┐ ┌────┐ ┌──┐ │
              │  │ CC │ │ CX │ │OC│ │
              │  └────┘ └────┘ └──┘ │
              └─────────────────────┘
```

---

## 3. 数据模型

### 3.1 Mission（任务委派）

对标 Multica 的 Issue，但语义是"带明确目标的安全任务委派"。

```python
class MissionStatus(str, Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

class MissionPriority(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

class Mission(BaseModel):
    """带有明确目标的安全任务委派。"""
    __tablename__ = "missions"

    workspace_id: Mapped[UUID]          # 所属工作区
    title: Mapped[str]                  # 任务标题
    description: Mapped[Optional[str]]  # 任务描述（Markdown）
    objective: Mapped[Optional[str]]    # 明确目标（Agent 的成功标准）

    status: Mapped[MissionStatus]       # 看板状态
    priority: Mapped[MissionPriority]   # 优先级

    # 多态指派：人或 Agent
    assignee_type: Mapped[Optional[str]]  # "member" | "agent"
    assignee_id: Mapped[Optional[UUID]]   # member.id 或 agent_profile.id

    creator_id: Mapped[UUID]            # 创建者（人）
    parent_mission_id: Mapped[Optional[UUID]]  # 父任务（支持分解）

    # 执行关联
    current_execution_id: Mapped[Optional[UUID]]  # 当前执行

    due_date: Mapped[Optional[datetime]]
    position: Mapped[float]             # 看板排序
    tags: Mapped[Optional[list]]        # JSONB 标签
```

### 3.2 AgentProfile（Agent 身份）

对标 Multica 的 Agent，是"团队成员"的 Agent 版本。

```python
class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    ERROR = "error"
    OFFLINE = "offline"

class AgentProfile(BaseModel):
    """Agent 作为团队成员的身份。"""
    __tablename__ = "agent_profiles"

    workspace_id: Mapped[UUID]
    name: Mapped[str]                   # 显示名称
    avatar: Mapped[Optional[str]]       # 头像 URL
    description: Mapped[Optional[str]]  # Agent 描述

    runtime_type: Mapped[str]           # "claude_code" | "codex" | "openclaw" | "langgraph"
    status: Mapped[AgentStatus]
    max_concurrent_tasks: Mapped[int]   # 最大并发任务数，默认 1

    # 能力配置
    skill_ids: Mapped[Optional[list]]   # JSONB: 绑定的 Skill ID 列表
    instructions: Mapped[Optional[str]] # 自定义指令
    custom_env: Mapped[Optional[dict]]  # JSONB: 自定义环境变量

    # Runtime 配置
    runtime_config: Mapped[Optional[dict]]  # JSONB: provider-specific 配置
    # 例如: {"model": "claude-sonnet-4-20250514", "timeout": "2h"}

    visibility: Mapped[str]             # "workspace" | "private"
```

### 3.3 Execution（统一执行记录）

替代现有的 AgentRun，支持多 Step 协同。

```python
class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"       # 新增：容器已创建、环境已准备，CLI 即将启动
    RUNNING = "running"
    INTERRUPT_WAIT = "interrupt_wait"  # 用户主动暂停执行
    APPROVAL_WAIT = "approval_wait"   # Agent 请求人工审批危险操作
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ExecutionSource(str, Enum):
    MISSION = "mission"             # Mission 看板触发
    CHAT = "chat"                   # Chat 对话触发
    GRAPH = "graph"                 # Graph 编排触发
    COORDINATOR = "coordinator"     # Coordinator Agent 触发
    API = "api"                     # 外部 API 触发

class Execution(BaseModel):
    """统一执行记录，承载所有类型的 Agent 执行。"""
    __tablename__ = "executions"

    workspace_id: Mapped[UUID]
    user_id: Mapped[str]                # 发起者

    source: Mapped[ExecutionSource]     # 触发来源
    source_id: Mapped[Optional[str]]    # 来源 ID（mission_id / thread_id / graph_execution_id）

    status: Mapped[ExecutionStatus]
    title: Mapped[Optional[str]]        # 执行标题

    # 关联
    mission_id: Mapped[Optional[UUID]]  # FK to missions
    agent_profile_id: Mapped[Optional[UUID]]  # FK to agent_profiles
    parent_execution_id: Mapped[Optional[UUID]]  # 父执行（Coordinator 模式）

    # 结果
    result_summary: Mapped[Optional[dict]]  # JSONB
    error_code: Mapped[Optional[str]]
    error_message: Mapped[Optional[str]]

    # 运行时
    runtime_type: Mapped[str]           # "langgraph" | "claude_code" | "codex" | "openclaw"
    runtime_config: Mapped[Optional[dict]]  # JSONB: 运行时配置快照
    container_id: Mapped[Optional[str]] # Docker 容器 ID（CLI 执行时）

    # 时间线
    started_at: Mapped[Optional[datetime]]
    finished_at: Mapped[Optional[datetime]]
    last_heartbeat_at: Mapped[Optional[datetime]]

    # 事件流
    last_seq: Mapped[int]               # 最高事件序号

    # Session 复用（对标 Multica 的 session resume）
    prior_session_id: Mapped[Optional[str]]
    session_id: Mapped[Optional[str]]
    work_dir: Mapped[Optional[str]]     # 容器内工作目录
```

### 3.4 ExecutionEvent（统一事件流）

替代 AgentRunEvent，统一所有 Agent 类型的消息协议。

```python
class ExecutionEvent(BaseModel):
    """统一的执行事件流，所有 Agent 类型共用同一协议。"""
    __tablename__ = "execution_events"

    execution_id: Mapped[UUID]          # FK to executions
    seq: Mapped[int]                    # 单调递增序号

    event_type: Mapped[str]
    # 统一事件类型：
    # "text"          - 文本输出
    # "thinking"      - 思考过程
    # "tool_use"      - 工具调用开始
    # "tool_result"   - 工具调用结果
    # "error"         - 错误
    # "status"        - 状态变更
    # "artifact"      - 产出物（文件、报告等）
    # "approval_request" - 审批请求（用户干预点）
    # "user_message"  - 用户注入的消息

    payload: Mapped[dict]               # JSONB: 事件数据
    # text:     {"content": "..."}
    # thinking: {"content": "..."}
    # tool_use: {"tool": "nuclei", "input": {...}}
    # tool_result: {"tool": "nuclei", "output": "...", "call_id": "..."}
    # artifact: {"type": "report", "path": "...", "size": 1234}
    # approval_request: {"action": "execute_exploit", "description": "..."}
    # user_message: {"content": "换个方向试试"}

    trace_id: Mapped[Optional[UUID]]
    observation_id: Mapped[Optional[UUID]]
    parent_observation_id: Mapped[Optional[UUID]]

    __table_args__ = (
        UniqueConstraint("execution_id", "seq"),
        Index("execution_events_exec_created_idx", "execution_id", "created_at"),
    )
```

### 3.5 RuntimeDevice（运行时设备注册）

对标 Multica 的 Runtime 注册机制，但扩展为云端容器。

```python
class RuntimeMode(str, Enum):
    CLOUD = "cloud"         # 云端 Docker 容器（主要模式）
    LOCAL = "local"         # 本地 Daemon（未来扩展）

class RuntimeDevice(BaseModel):
    """注册的运行时设备/容器。"""
    __tablename__ = "runtime_devices"

    workspace_id: Mapped[UUID]
    agent_profile_id: Mapped[Optional[UUID]]  # 绑定的 Agent

    name: Mapped[str]                   # 显示名称
    runtime_mode: Mapped[RuntimeMode]
    runtime_type: Mapped[str]           # "claude_code" | "codex" | "openclaw"
    status: Mapped[str]                 # "online" | "offline" | "busy"

    # 容器信息
    container_id: Mapped[Optional[str]]
    container_image: Mapped[Optional[str]]

    # 设备信息
    device_info: Mapped[Optional[dict]] # JSONB: 版本、能力等
    metadata: Mapped[Optional[dict]]    # JSONB

    last_seen_at: Mapped[Optional[datetime]]
```

---

## 4. Runtime Provider 层

### 4.1 统一接口

所有 Agent 类型实现同一个协议。这是整个系统的核心抽象。

```python
from typing import AsyncIterator, Protocol
from dataclasses import dataclass

@dataclass
class CLIMessage:
    """统一消息类型，所有 Runtime Provider 输出都转成这个格式。"""
    type: str       # "text" | "thinking" | "tool_use" | "tool_result" | "error" | "artifact"
    content: str = ""
    tool: str = ""
    call_id: str = ""
    input: dict | None = None
    output: str = ""

@dataclass
class CLIResult:
    """执行最终结果。"""
    status: str         # "completed" | "failed" | "timeout" | "blocked"
    output: str = ""
    error: str = ""
    session_id: str = ""    # 用于 session resume
    branch_name: str = ""
    usage: dict | None = None  # per-model token usage

class RuntimeProvider(Protocol):
    """所有 Agent Runtime 的统一协议。"""

    provider_type: str  # "claude_code" | "codex" | "openclaw" | "langgraph"

    async def execute(
        self,
        prompt: str,
        *,
        cwd: str | None = None,
        model: str | None = None,
        timeout: int = 7200,
        resume_session_id: str | None = None,
        env: dict[str, str] | None = None,
    ) -> "RuntimeSession":
        """启动执行，返回 Session。"""
        ...

    async def inject_message(self, session: "RuntimeSession", message: str) -> None:
        """向正在执行的 Agent 注入用户消息（干预）。"""
        ...

    async def cancel(self, session: "RuntimeSession") -> None:
        """取消执行。"""
        ...

@dataclass
class RuntimeSession:
    """一次执行的会话，包含消息流和最终结果。"""
    messages: AsyncIterator[CLIMessage]   # 实时消息流
    result: asyncio.Future[CLIResult]     # 最终结果
    process: asyncio.subprocess.Process | None = None  # 底层进程引用
    stdin_writer: asyncio.StreamWriter | None = None    # 用于注入消息
```

### 4.2 Claude Code Provider

对标 Multica `pkg/agent/claude.go`，Python 重写。

```python
class ClaudeCodeProvider:
    """Claude Code CLI Runtime Provider。"""

    provider_type = "claude_code"

    def __init__(self, executable_path: str = "claude"):
        self.executable_path = executable_path

    async def execute(self, prompt, *, cwd=None, model=None,
                      timeout=7200, resume_session_id=None, env=None):
        cmd = [
            self.executable_path,
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", "200",
        ]
        if model:
            cmd.extend(["--model", model])
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        else:
            cmd.extend(["--print", prompt])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, **(env or {})},
        )

        result_future = asyncio.get_event_loop().create_future()
        messages = self._parse_ndjson_stream(process.stdout, result_future)

        return RuntimeSession(
            messages=messages,
            result=result_future,
            process=process,
            stdin_writer=process.stdin,
        )

    async def _parse_ndjson_stream(self, stdout, result_future):
        """解析 Claude Code 的 NDJSON stream-json 输出。"""
        accumulated_text = []
        session_id = None
        usage = {}

        async for line in stdout:
            line = line.decode().strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "assistant" and "message" in event:
                msg = event["message"]
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        yield CLIMessage(type="text", content=block["text"])
                        accumulated_text.append(block["text"])
                    elif block.get("type") == "tool_use":
                        yield CLIMessage(
                            type="tool_use",
                            tool=block.get("name", ""),
                            call_id=block.get("id", ""),
                            input=block.get("input"),
                        )
                    elif block.get("type") == "thinking":
                        yield CLIMessage(type="thinking", content=block.get("thinking", ""))

            elif event_type == "result":
                result = event.get("result", {})
                session_id = result.get("session_id")
                # 提取 usage
                if "usage" in event:
                    usage = event["usage"]

                result_future.set_result(CLIResult(
                    status="completed",
                    output="\n".join(accumulated_text),
                    session_id=session_id or "",
                    usage=usage,
                ))

    async def inject_message(self, session, message):
        if session.stdin_writer:
            session.stdin_writer.write(f"{message}\n".encode())
            await session.stdin_writer.drain()

    async def cancel(self, session):
        if session.process:
            session.process.terminate()
```

### 4.3 Codex Provider

对标 Multica `pkg/agent/codex.go`，JSON-RPC stdio 通信。

```python
class CodexProvider:
    """Codex CLI Runtime Provider (JSON-RPC over stdio)。"""

    provider_type = "codex"

    def __init__(self, executable_path: str = "codex"):
        self.executable_path = executable_path

    async def execute(self, prompt, *, cwd=None, model=None,
                      timeout=7200, resume_session_id=None, env=None):
        cmd = [self.executable_path, "app-server", "--listen", "stdio://"]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, **(env or {})},
        )

        result_future = asyncio.get_event_loop().create_future()
        # 发送 JSON-RPC 请求
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "execute",
            "params": {"prompt": prompt, "model": model},
        }
        process.stdin.write(json.dumps(request).encode() + b"\n")
        await process.stdin.drain()

        messages = self._parse_jsonrpc_stream(process.stdout, result_future)
        return RuntimeSession(messages=messages, result=result_future, process=process)

    async def _parse_jsonrpc_stream(self, stdout, result_future):
        """解析 Codex 的 JSON-RPC 响应流。"""
        # ... JSON-RPC notification/response 解析逻辑
        pass

    async def inject_message(self, session, message):
        if session.process and session.process.stdin:
            request = {
                "jsonrpc": "2.0",
                "method": "user_message",
                "params": {"content": message},
            }
            session.process.stdin.write(json.dumps(request).encode() + b"\n")
            await session.process.stdin.drain()

    async def cancel(self, session):
        if session.process:
            session.process.terminate()
```

### 4.4 OpenClaw Provider

对标 Multica `pkg/agent/openclaw.go`，stderr NDJSON。

```python
class OpenClawProvider:
    """OpenClaw CLI Runtime Provider。"""

    provider_type = "openclaw"

    def __init__(self, executable_path: str = "openclaw"):
        self.executable_path = executable_path

    async def execute(self, prompt, *, cwd=None, model=None,
                      timeout=7200, resume_session_id=None, env=None):
        session_id = resume_session_id or str(uuid.uuid4())
        cmd = [
            self.executable_path, "agent",
            "--local", "--json",
            "--session-id", session_id,
            prompt,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,  # OpenClaw 事件在 stderr
            cwd=cwd,
            env={**os.environ, **(env or {})},
        )

        result_future = asyncio.get_event_loop().create_future()
        messages = self._parse_stderr_ndjson(process.stderr, result_future, session_id)
        return RuntimeSession(messages=messages, result=result_future, process=process)

    async def _parse_stderr_ndjson(self, stderr, result_future, session_id):
        """解析 OpenClaw 的 stderr NDJSON 事件流。"""
        accumulated_text = []
        async for line in stderr:
            line = line.decode().strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")
            if event_type == "message":
                content = event.get("content", "")
                yield CLIMessage(type="text", content=content)
                accumulated_text.append(content)
            elif event_type == "tool_call":
                yield CLIMessage(
                    type="tool_use",
                    tool=event.get("tool", ""),
                    input=event.get("args"),
                )
            elif event_type == "tool_result":
                yield CLIMessage(
                    type="tool_result",
                    tool=event.get("tool", ""),
                    output=event.get("output", ""),
                )
            elif event_type == "error":
                yield CLIMessage(type="error", content=event.get("message", ""))
            elif event_type == "done":
                result_future.set_result(CLIResult(
                    status="completed",
                    output="\n".join(accumulated_text),
                    session_id=session_id,
                ))

    async def inject_message(self, session, message):
        if session.stdin_writer:
            session.stdin_writer.write(f"{message}\n".encode())
            await session.stdin_writer.drain()

    async def cancel(self, session):
        if session.process:
            session.process.terminate()
```

### 4.5 LangGraph Provider（适配现有系统）

将现有的 LangGraph 执行包装为 RuntimeProvider，实现统一接口。

```python
class LangGraphProvider:
    """将现有 LangGraph 执行适配为 RuntimeProvider 接口。"""

    provider_type = "langgraph"

    async def execute(self, prompt, *, cwd=None, model=None,
                      timeout=7200, resume_session_id=None, env=None):
        # 复用现有的 GraphService 和 ChatTurnExecutor 逻辑
        # 将 LangGraph 的 stream events 转换为 CLIMessage 格式
        ...

    async def inject_message(self, session, message):
        # 通过 LangGraph 的 interrupt/resume 机制注入
        ...

    async def cancel(self, session):
        # 通过现有的 task_manager.stop_task() 取消
        ...
```

### 4.6 Provider Registry

```python
class RuntimeProviderRegistry:
    """Runtime Provider 注册表。新增 Agent 类型只需注册 Provider。"""

    _providers: dict[str, RuntimeProvider] = {}

    @classmethod
    def register(cls, provider: RuntimeProvider):
        cls._providers[provider.provider_type] = provider

    @classmethod
    def get(cls, provider_type: str) -> RuntimeProvider:
        if provider_type not in cls._providers:
            raise ValueError(f"Unknown runtime provider: {provider_type}")
        return cls._providers[provider_type]

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._providers.keys())

# 启动时注册
RuntimeProviderRegistry.register(ClaudeCodeProvider())
RuntimeProviderRegistry.register(CodexProvider())
RuntimeProviderRegistry.register(OpenClawProvider())
RuntimeProviderRegistry.register(LangGraphProvider())
```

## 5. Execution Engine（执行引擎）

### 5.1 核心流程

```
Mission/Chat/Graph/Coordinator 触发
        │
        ▼
┌─ ExecutionService.create_execution() ─┐
│  创建 Execution 记录 (QUEUED)          │
│  关联 Mission / Agent / Workspace      │
└────────────┬──────────────────────────┘
             │
             ▼
┌─ ExecutionDispatcher.dispatch() ──────┐
│  1. 查找 AgentProfile → runtime_type  │
│  2. 从 Registry 获取 Provider         │
│  3. 创建 Docker 容器（CLI 类型）       │
│  4. 注入 Skills + Context             │
│  5. 状态 → DISPATCHED                 │
└────────────┬──────────────────────────┘
             │
             ▼
┌─ ExecutionRunner.run() ───────────────┐
│  1. Provider.execute(prompt, opts)    │
│  2. 状态 → RUNNING                    │
│  3. 消费 session.messages:            │
│     - 转为 ExecutionEvent 写入 DB     │
│     - 通过 WebSocket 实时推送         │
│     - 检测 approval_request → 暂停    │
│  4. 等待 session.result               │
│  5. 状态 → COMPLETED / FAILED         │
│  6. 销毁容器（CLI 类型）              │
└───────────────────────────────────────┘
```

### 5.2 状态机

```
                    ┌──────────┐
                    │  QUEUED  │
                    └────┬─────┘
                         │ dispatch()
                         ▼
                  ┌──────────────┐
                  │  DISPATCHED  │
                  └──────┬───────┘
                         │ provider.execute()
                         ▼
                    ┌──────────┐
              ┌────►│ RUNNING  │◄────┐
              │     └──┬───┬───┘     │
              │        │   │         │
     resume() │        │   │         │ user approves
              │        │   │         │
    ┌─────────┴──┐     │   │   ┌─────┴──────────┐
    │ INTERRUPT  │◄────┘   └──►│ APPROVAL_WAIT  │
    │   _WAIT    │  interrupt  │                 │
    └────────────┘             └────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌───────────┐ ┌────────┐ ┌───────────┐
    │ COMPLETED │ │ FAILED │ │ CANCELLED │
    └───────────┘ └────────┘ └───────────┘
```

新增 `DISPATCHED` 和 `APPROVAL_WAIT` 两个状态：
- `DISPATCHED`：容器已创建、环境已准备，CLI 即将启动
- `APPROVAL_WAIT`：Agent 遇到需要用户审批的操作（如执行危险命令），等待用户决策

### 5.3 ExecutionService

```python
class ExecutionService:
    """统一执行服务，替代现有 RunService。"""

    def __init__(self, db: AsyncSession, hub: WebSocketHub):
        self.db = db
        self.hub = hub
        self.registry = RuntimeProviderRegistry

    # ── 创建 ──

    async def create_execution(
        self,
        *,
        user_id: str,
        workspace_id: UUID,
        source: ExecutionSource,
        runtime_type: str,
        prompt: str,
        mission_id: UUID | None = None,
        agent_profile_id: UUID | None = None,
        parent_execution_id: UUID | None = None,
        title: str | None = None,
    ) -> Execution:
        """创建执行记录。所有触发模式统一入口。"""

    # ── 事件流 ──

    async def append_event(
        self,
        execution_id: UUID,
        event_type: str,
        payload: dict,
    ) -> ExecutionEvent:
        """追加事件，自增 seq，广播到 WebSocket 订阅者。"""

    # ── 状态转换 ──

    async def mark_dispatched(self, execution_id: UUID, container_id: str) -> None:
    async def mark_running(self, execution_id: UUID) -> None:
    async def mark_approval_wait(self, execution_id: UUID, request: dict) -> None:
    async def mark_completed(self, execution_id: UUID, result: dict) -> None:
    async def mark_failed(self, execution_id: UUID, error: str) -> None:
    async def mark_cancelled(self, execution_id: UUID) -> None:

    # ── 用户干预 ──

    async def inject_user_message(self, execution_id: UUID, message: str) -> None:
        """向正在执行的 Agent 注入用户消息。"""

    async def approve_action(self, execution_id: UUID, approved: bool) -> None:
        """审批 Agent 的操作请求。"""

    # ── 查询 ──

    async def list_executions(self, user_id: str, **filters) -> list[Execution]:
    async def get_execution(self, execution_id: UUID) -> Execution:
    async def list_events(self, execution_id: UUID, after_seq: int = 0) -> list[ExecutionEvent]:
```

---

## 6. Mission Dispatcher（任务分发）

### 6.1 分发流程

```
Mission 状态变为 IN_PROGRESS 且 assignee_type == "agent"
        │
        ▼
MissionDispatcher.on_mission_assigned()
        │
        ├─ 查找 AgentProfile
        ├─ 检查 Agent 并发容量
        ├─ 构建 prompt（从 Mission 的 title + description + objective）
        ├─ 加载 Agent 绑定的 Skills
        ├─ 调用 ExecutionService.create_execution(source=MISSION)
        └─ 启动 ExecutionRunner
```

### 6.2 Prompt 构建

对标 Multica 的 `BuildPrompt`，但融入 Mission 语义：

```python
def build_mission_prompt(mission: Mission, agent: AgentProfile) -> str:
    parts = [
        f"你是安全团队的 {agent.name}，正在执行一个安全任务。",
        f"",
        f"## Mission",
        f"**标题:** {mission.title}",
    ]
    if mission.description:
        parts.append(f"**描述:** {mission.description}")
    if mission.objective:
        parts.append(f"**目标（成功标准）:** {mission.objective}")

    parts.append("")
    parts.append("请开始执行任务。完成后给出详细报告。")

    if agent.instructions:
        parts.append(f"\n## Agent 指令\n{agent.instructions}")

    return "\n".join(parts)
```

---

## 7. Agent 协同机制

### 7.1 模式 A：Graph 编排协同

扩展现有 Graph 编辑器，新增 CLI Agent 节点类型：

```python
# Graph 节点类型扩展
class CLIAgentNode:
    """Graph 中的 CLI Agent 执行节点。"""
    node_type = "cli_agent"

    agent_profile_id: UUID      # 使用哪个 Agent
    prompt_template: str        # prompt 模板，可引用上游节点输出
    skills: list[UUID]          # 额外注入的 Skill

    async def execute(self, context: GraphContext) -> dict:
        # 1. 渲染 prompt（替换上游变量）
        prompt = self.render_prompt(context)
        # 2. 创建子 Execution
        execution = await execution_service.create_execution(
            source=ExecutionSource.GRAPH,
            runtime_type=agent.runtime_type,
            prompt=prompt,
            parent_execution_id=context.root_execution_id,
        )
        # 3. 等待完成，返回结果给下游节点
        result = await execution_runner.run_and_wait(execution)
        return result
```

示例 Graph：安全审计流水线

```
[Claude Code: 写扫描脚本] → [OpenClaw: 执行渗透测试] → [LangGraph: 分析结果生成报告]
```

### 7.2 模式 B：Coordinator 动态协同

LangGraph Agent 作为 Coordinator，通过工具调用动态启动其他 Agent：

```python
# 注册为 LangGraph 的工具
@tool
async def spawn_agent(
    agent_name: str,
    prompt: str,
    wait: bool = True,
) -> str:
    """启动一个 Agent 执行子任务。

    Args:
        agent_name: Agent 名称（如 "Claude Code", "OpenClaw"）
        prompt: 任务描述
        wait: 是否等待完成
    """
    agent = await find_agent_by_name(agent_name)
    execution = await execution_service.create_execution(
        source=ExecutionSource.COORDINATOR,
        runtime_type=agent.runtime_type,
        prompt=prompt,
        parent_execution_id=current_execution_id,
    )
    if wait:
        result = await execution_runner.run_and_wait(execution)
        return result.output
    else:
        return f"已启动 Agent {agent_name}，execution_id={execution.id}"

@tool
async def get_agent_result(execution_id: str) -> str:
    """获取已启动 Agent 的执行结果。"""
    execution = await execution_service.get_execution(UUID(execution_id))
    if execution.status == "completed":
        return execution.result_summary.get("output", "")
    return f"Agent 仍在执行中，当前状态: {execution.status}"
```

Coordinator 使用示例：

```
用户: "帮我全面审计 target.apk"

Coordinator (LangGraph Agent):
  思考: 这需要多个步骤，我来协调
  1. spawn_agent("Claude Code", "反编译 target.apk 并分析 AndroidManifest.xml")
  2. 等待结果 → 发现 exported activities
  3. spawn_agent("OpenClaw", "对以下 exported activities 进行渗透测试: ...")
  4. 等待结果 → 发现 SQL 注入
  5. spawn_agent("Claude Code", "编写 PoC 验证 SQL 注入漏洞: ...")
  6. 汇总所有结果，生成安全审计报告
```

---

## 8. Skill 注入机制

### 8.1 容器启动时注入

复用 JoySafeter 现有的 `SkillSandboxLoader`，按 provider 类型写入不同路径：

```python
class CLISkillInjector:
    """将 JoySafeter Skill 注入到 CLI Agent 容器中。"""

    # Provider → Skill 目录映射（对标 Multica execenv/context.go）
    SKILL_PATHS = {
        "claude_code": ".claude/skills/{name}/SKILL.md",
        "codex": ".codex/skills/{name}/SKILL.md",      # via CODEX_HOME
        "openclaw": "/workspace/skills/{name}/SKILL.md",
    }

    async def inject(
        self,
        container_id: str,
        runtime_type: str,
        skill_ids: list[UUID],
        work_dir: str,
    ) -> None:
        """将 Skills 写入容器文件系统。"""
        async with async_session_factory() as db:
            for skill_id in skill_ids:
                skill = await db.get(Skill, skill_id)
                if not skill:
                    continue

                # 写入 SKILL.md
                path_template = self.SKILL_PATHS.get(runtime_type)
                if not path_template:
                    continue
                skill_path = path_template.format(name=skill.name)
                full_path = f"{work_dir}/{skill_path}"

                await self._write_to_container(container_id, full_path, skill.content)

                # 写入附属文件
                files = await db.execute(
                    select(SkillFile).where(SkillFile.skill_id == skill_id)
                )
                for f in files.scalars():
                    file_path = f"{work_dir}/{os.path.dirname(skill_path)}/{f.path}"
                    await self._write_to_container(container_id, file_path, f.content)

    async def _write_to_container(self, container_id: str, path: str, content: str):
        """通过 Docker API 写入文件到容器。"""
        # docker cp 或 exec echo > file
        ...
```

### 8.2 Runtime Config 注入

对标 Multica 的 `InjectRuntimeConfig`，生成 provider-specific 配置文件：

```python
class RuntimeConfigInjector:
    """生成并注入 CLAUDE.md / AGENTS.md / GEMINI.md。"""

    async def inject(
        self,
        container_id: str,
        runtime_type: str,
        agent: AgentProfile,
        mission: Mission | None,
        skills: list[Skill],
        work_dir: str,
    ) -> None:
        if runtime_type == "claude_code":
            content = self._build_claude_md(agent, mission, skills)
            await self._write_to_container(container_id, f"{work_dir}/CLAUDE.md", content)
        elif runtime_type == "codex":
            content = self._build_agents_md(agent, mission, skills)
            await self._write_to_container(container_id, f"{work_dir}/AGENTS.md", content)
        elif runtime_type == "openclaw":
            # OpenClaw 通过 gateway config 注入
            pass

    def _build_claude_md(self, agent, mission, skills) -> str:
        sections = [
            f"# {agent.name}",
            "",
            f"你是 JoySafeter 安全团队的 AI Agent。",
            "",
        ]
        if agent.instructions:
            sections.append(f"## 指令\n{agent.instructions}\n")
        if mission:
            sections.append(f"## 当前 Mission\n{mission.title}\n{mission.objective or ''}\n")
        if skills:
            sections.append("## 可用 Skills")
            for s in skills:
                sections.append(f"- **{s.name}**: {s.description}")
                sections.append(f"  位置: `.claude/skills/{s.name}/SKILL.md`")
            sections.append("")
        return "\n".join(sections)
```

---

## 9. API 设计

### 9.1 Mission API

```
POST   /api/v1/missions                    # 创建 Mission
GET    /api/v1/missions                    # 列表（支持 status/priority/assignee 过滤）
GET    /api/v1/missions/{id}               # 详情
PUT    /api/v1/missions/{id}               # 更新
DELETE /api/v1/missions/{id}               # 删除
POST   /api/v1/missions/{id}/assign        # 分配给 Agent 或人
POST   /api/v1/missions/{id}/status        # 变更状态
GET    /api/v1/missions/{id}/executions    # 该 Mission 的所有执行记录
POST   /api/v1/missions/{id}/comments      # 添加评论
GET    /api/v1/missions/{id}/comments      # 评论列表
```

### 9.2 Agent Profile API

```
POST   /api/v1/agents                      # 创建 Agent Profile
GET    /api/v1/agents                      # 列表
GET    /api/v1/agents/{id}                 # 详情（含状态、当前任务）
PUT    /api/v1/agents/{id}                 # 更新配置
DELETE /api/v1/agents/{id}                 # 删除
GET    /api/v1/agents/{id}/executions      # 该 Agent 的执行历史
```

### 9.3 Execution API

```
POST   /api/v1/executions                  # 直接创建执行（Chat/API 触发）
GET    /api/v1/executions                  # 列表
GET    /api/v1/executions/{id}             # 详情
GET    /api/v1/executions/{id}/events      # 事件流（支持 after_seq 分页）
POST   /api/v1/executions/{id}/cancel      # 取消
POST   /api/v1/executions/{id}/message     # 注入用户消息（干预）
POST   /api/v1/executions/{id}/approve     # 审批操作请求
```

### 9.4 WebSocket

```
/ws/executions/{execution_id}              # 订阅单个执行的实时事件流
/ws/missions/board                         # 订阅看板变更（状态、分配、进度）
```

复用现有的 `/ws/chat/{user_id}` 用于 Chat-driven 执行。

---

## 10. 容器管理

### 10.1 CLI 容器镜像

基于现有的 `openclaw/Dockerfile` 扩展，预装所有 CLI：

```dockerfile
FROM node:22-slim

# 安装 Claude Code
RUN npm install -g @anthropic-ai/claude-code

# 安装 Codex
RUN npm install -g @openai/codex

# 安装 OpenClaw
RUN npm install -g openclaw@latest

# 安装基础工具
RUN apt-get update && apt-get install -y git curl python3 && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /workspace
```

### 10.2 CLIContainerService

```python
class CLIContainerService:
    """管理 CLI Agent 的 Docker 容器生命周期。"""

    IMAGE = "joysafeter/cli-agent:latest"
    NETWORK = "joysafeter-network"

    async def create_container(
        self,
        execution_id: UUID,
        runtime_type: str,
        env: dict[str, str],
    ) -> str:
        """创建并启动容器，返回 container_id。"""
        container = docker_client.containers.run(
            self.IMAGE,
            detach=True,
            network=self.NETWORK,
            environment=env,
            labels={"joysafeter.execution_id": str(execution_id)},
            mem_limit="4g",
            cpu_quota=200000,  # 2 cores
        )
        return container.id

    async def destroy_container(self, container_id: str) -> None:
        """停止并删除容器。"""
        container = docker_client.containers.get(container_id)
        container.stop(timeout=10)
        container.remove()

    async def exec_in_container(self, container_id: str, cmd: list[str]) -> str:
        """在容器内执行命令。"""
        container = docker_client.containers.get(container_id)
        result = container.exec_run(cmd)
        return result.output.decode()
```

---

## 11. 与现有系统的迁移关系

### 11.1 渐进式迁移，不破坏现有功能

| 阶段 | 动作 | 影响 |
|------|------|------|
| Phase 0 | 新增 Mission / AgentProfile / Execution 表，不动现有表 | 零影响 |
| Phase 1 | 实现 CLI Runtime Providers + 容器管理 | 新功能，不影响现有 |
| Phase 2 | 实现 Mission 看板 + Dispatcher | 新功能，不影响现有 |
| Phase 3 | 将 Chat-driven 执行迁移到 Execution 系统 | 现有 AgentRun 逐步废弃 |
| Phase 4 | 实现 Graph 编排协同 + Coordinator 模式 | 扩展现有 Graph 系统 |
| Phase 5 | 完全移除旧 AgentRun 系统 | 清理 |

### 11.2 AgentRun → Execution 映射

```
AgentRun.run_type          → Execution.source + runtime_type
AgentRun.agent_name        → Execution.agent_profile_id
AgentRun.source            → Execution.source
AgentRun.thread_id         → Execution.source_id (when source=CHAT)
AgentRun.graph_id          → 通过 Mission 或 Graph 关联
AgentRunEvent              → ExecutionEvent（事件类型统一化）
AgentRunSnapshot           → 可选，或直接从 ExecutionEvent 实时计算
```

### 11.3 数据迁移

Phase 3 时编写 Alembic migration：
- 将 `agent_runs` 数据迁移到 `executions`
- 将 `agent_run_events` 数据迁移到 `execution_events`
- 保留旧表一段时间作为备份

---

## 12. 第一阶段实现范围（MVP）

聚焦最小可用版本：

1. **数据模型**: Mission + AgentProfile + Execution + ExecutionEvent 四张表
2. **Runtime Provider**: Claude Code Provider（先支持一个）
3. **容器管理**: CLIContainerService（创建/销毁）
4. **Skill 注入**: CLISkillInjector（写入 .claude/skills/）
5. **执行引擎**: ExecutionService + ExecutionRunner
6. **API**: Mission CRUD + Execution CRUD + 事件流查询
7. **WebSocket**: /ws/executions/{id} 实时推送
8. **前端**: Mission 看板（简单列表视图）+ Execution 监控（消息流展示）

不在 MVP 中：
- Codex / OpenClaw Provider（Phase 2）
- Graph 编排协同（Phase 4）
- Coordinator 动态协同（Phase 4）
- 旧系统迁移（Phase 3）
- 用户干预/审批（Phase 2）

---

## 13. Spec Review 修复（基于架构评审）

以下修复针对 spec review 发现的 Critical 和 Major 问题。

### 13.1 [C2 修复] CLI 进程在容器内执行的正确方式

原 spec 中 Provider 使用 `asyncio.create_subprocess_exec` 直接启动 CLI 进程，但 CLI 实际运行在 Docker 容器内，后端无法直接 spawn 容器内的进程。

**正确方案：通过 `docker exec` 桥接。**

```python
class ContainerProcessBridge:
    """通过 docker exec 在容器内启动进程并桥接 stdin/stdout。"""

    async def exec_streaming(
        self,
        container_id: str,
        cmd: list[str],
        env: dict[str, str] | None = None,
    ) -> asyncio.subprocess.Process:
        """在容器内启动进程，返回可读写的 Process 对象。"""
        docker_cmd = ["docker", "exec", "-i"]
        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.append(container_id)
        docker_cmd.extend(cmd)

        return await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
```

所有 CLI Provider 的 `execute()` 方法改为：
1. 由 `ExecutionRunner` 先通过 `CLIContainerService` 创建容器
2. 将 `container_id` 传给 Provider
3. Provider 通过 `ContainerProcessBridge.exec_streaming()` 在容器内启动 CLI

```python
class ClaudeCodeProvider:
    async def execute(self, prompt, *, container_id, cwd=None, model=None, ...):
        bridge = ContainerProcessBridge()
        cmd = ["claude", "--output-format", "stream-json", "--verbose", "--print", prompt]
        if model:
            cmd = ["claude", "--output-format", "stream-json", "--model", model, "--print", prompt]

        process = await bridge.exec_streaming(container_id, cmd, env={"HOME": "/workspace"})
        # ... 后续解析逻辑不变
```

### 13.2 [C3/C4 修复] 消息流与 Result Future 的安全解耦

原 spec 中 async generator 内部设置 future，存在死锁和未完成 future 的风险。

**修复：使用 asyncio.Queue + 独立后台任务。**

```python
@dataclass
class RuntimeSession:
    """一次执行的会话。"""
    messages: asyncio.Queue[CLIMessage | None]  # None 表示流结束
    result: asyncio.Future[CLIResult]
    _drain_task: asyncio.Task | None = None     # 后台解析任务
    _cancel_func: Callable | None = None        # 取消回调

    async def iter_messages(self) -> AsyncIterator[CLIMessage]:
        """安全地迭代消息流。"""
        while True:
            msg = await self.messages.get()
            if msg is None:
                break
            yield msg


class ClaudeCodeProvider:
    async def execute(self, prompt, *, container_id, **kwargs) -> RuntimeSession:
        process = await bridge.exec_streaming(container_id, cmd)
        queue = asyncio.Queue(maxsize=256)
        result_future = asyncio.get_event_loop().create_future()

        async def drain():
            """独立后台任务：解析流 → 写入 queue + 设置 result。"""
            accumulated = []
            try:
                async for line in process.stdout:
                    parsed = self._parse_line(line.decode().strip())
                    if parsed:
                        if parsed.type == "_result":
                            # 内部标记，不放入 queue
                            result_future.set_result(parsed.to_cli_result())
                        else:
                            await queue.put(parsed)
                            if parsed.type == "text":
                                accumulated.append(parsed.content)
            except Exception as e:
                if not result_future.done():
                    result_future.set_result(CLIResult(status="failed", error=str(e)))
            finally:
                # 确保 future 一定被设置
                if not result_future.done():
                    exit_code = await process.wait()
                    if exit_code == 0:
                        result_future.set_result(CLIResult(
                            status="completed",
                            output="\n".join(accumulated),
                        ))
                    else:
                        stderr_out = await process.stderr.read()
                        result_future.set_result(CLIResult(
                            status="failed",
                            error=f"Process exited with code {exit_code}: {stderr_out.decode()[:2000]}",
                        ))
                await queue.put(None)  # 标记流结束

        drain_task = asyncio.create_task(drain())

        return RuntimeSession(
            messages=queue,
            result=result_future,
            _drain_task=drain_task,
            _cancel_func=lambda: process.terminate(),
        )
```

### 13.3 [M1 修复] 工作区级别授权

```python
# Mission API 授权规则
class MissionPermissions:
    """
    - 创建 Mission: workspace member (any role)
    - 查看 Mission: workspace member (any role)
    - 更新 Mission: creator 或 workspace admin/owner
    - 分配给 Agent: workspace admin/owner
    - 取消 Mission: creator 或 workspace admin/owner
    - 删除 Mission: workspace admin/owner

    # Execution API 授权规则
    - 创建 Execution: workspace member (any role)
    - 查看 Execution: workspace member (any role)
    - 取消他人的 Execution: workspace admin/owner
    - 注入消息/审批: execution 的创建者 或 workspace admin/owner
    """
```

所有 API endpoint 需要：
1. 从 `X-Workspace-ID` header 获取 workspace_id
2. 验证当前用户是该 workspace 的 member
3. 按上述规则检查角色权限

### 13.4 [M2 修复] Skill 注入复用现有 SkillSandboxLoader

不重写 Skill 注入逻辑，而是为 Docker 容器实现一个 `BackendProtocol` 适配器：

```python
class ContainerBackendAdapter:
    """将 Docker 容器适配为 SkillSandboxLoader 可用的 Backend。"""

    def __init__(self, container_id: str, work_dir: str = "/workspace"):
        self.container_id = container_id
        self.work_dir = work_dir

    async def write_file(self, path: str, content: str) -> None:
        """通过 docker exec 写入文件到容器。"""
        full_path = f"{self.work_dir}/{path}"
        # 确保目录存在
        dir_path = os.path.dirname(full_path)
        await self._exec(["mkdir", "-p", dir_path])
        # 写入内容（通过 stdin pipe 避免 shell 转义问题）
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", self.container_id,
            "tee", full_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(input=content.encode())

    async def _exec(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", self.container_id, *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()


# 使用方式：
async def inject_skills_to_container(container_id, runtime_type, skill_ids, user_id):
    backend = ContainerBackendAdapter(container_id)
    loader = SkillSandboxLoader(backend)

    # 复用现有的 skill 加载逻辑
    async with async_session_factory() as db:
        for skill_id in skill_ids:
            skill = await db.get(Skill, skill_id)
            if skill:
                await loader.load_skill(skill, user_id=user_id)
```

### 13.5 [M3 修复] Docker SDK 异步调用

```python
class CLIContainerService:
    """管理 CLI Agent 的 Docker 容器生命周期。所有 Docker SDK 调用通过线程池执行。"""

    async def create_container(self, execution_id: UUID, runtime_type: str, env: dict) -> str:
        return await asyncio.to_thread(self._create_sync, execution_id, runtime_type, env)

    def _create_sync(self, execution_id, runtime_type, env) -> str:
        container = docker_client.containers.run(
            self.IMAGE, detach=True, network=self.NETWORK,
            environment=env,
            labels={"joysafeter.execution_id": str(execution_id)},
            mem_limit="4g", cpu_quota=200000,
        )
        return container.id

    async def destroy_container(self, container_id: str) -> None:
        await asyncio.to_thread(self._destroy_sync, container_id)

    def _destroy_sync(self, container_id):
        container = docker_client.containers.get(container_id)
        container.stop(timeout=10)
        container.remove()
```

### 13.6 [M4 修复] 容器安全隔离

```python
class CLIContainerService:
    # 安全配置
    SECURITY_OPTS = ["no-new-privileges:true"]
    CAP_DROP = ["ALL"]
    CAP_ADD = ["NET_RAW"]  # 安全扫描工具可能需要

    def _create_sync(self, execution_id, runtime_type, env) -> str:
        container = docker_client.containers.run(
            self.IMAGE,
            detach=True,
            # 网络隔离：使用独立网络，仅允许访问后端 API
            network=self.AGENT_NETWORK,  # 独立于 joysafeter-network
            # 资源限制
            mem_limit="4g",
            cpu_quota=200000,
            # 安全加固
            security_opt=self.SECURITY_OPTS,
            cap_drop=self.CAP_DROP,
            cap_add=self.CAP_ADD,
            user="1000:1000",           # 非 root 用户
            read_only=False,            # /workspace 需要可写
            tmpfs={"/tmp": "size=512m"},
            # 自动销毁保底
            labels={
                "joysafeter.execution_id": str(execution_id),
                "joysafeter.created_at": datetime.utcnow().isoformat(),
            },
            environment=env,
        )
        return container.id
```

网络隔离方案：
- 创建 `joysafeter-agent-network`，仅允许 Agent 容器访问后端 API
- Agent 容器不能直接访问 PostgreSQL 或 Redis
- 通过后端 API 代理所有外部交互

### 13.7 [M5 修复] API Key 注入机制

```python
class CredentialInjector:
    """从 ModelCredential 系统获取 API Key 并注入到容器环境变量。"""

    # runtime_type → 需要的环境变量
    REQUIRED_KEYS = {
        "claude_code": ["ANTHROPIC_API_KEY"],
        "codex": ["OPENAI_API_KEY"],
        "openclaw": ["AI_GATEWAY_API_KEY", "AI_GATEWAY_BASE_URL"],
    }

    async def build_env(
        self,
        runtime_type: str,
        agent_profile: AgentProfile,
        workspace_id: UUID,
        user_id: str,
    ) -> dict[str, str]:
        env = {}
        async with async_session_factory() as db:
            cred_service = ModelCredentialService(db)

            for key_name in self.REQUIRED_KEYS.get(runtime_type, []):
                # 优先从 agent 的 custom_env 获取
                if agent_profile.custom_env and key_name in agent_profile.custom_env:
                    env[key_name] = agent_profile.custom_env[key_name]
                    continue
                # 其次从 workspace 的 ModelCredential 获取
                cred = await cred_service.get_credential_for_provider(
                    workspace_id=workspace_id,
                    provider_type=self._key_to_provider(key_name),
                )
                if cred:
                    env[key_name] = cred.decrypted_key

        return env

    def _key_to_provider(self, key_name: str) -> str:
        return {
            "ANTHROPIC_API_KEY": "anthropic",
            "OPENAI_API_KEY": "openai",
            "AI_GATEWAY_API_KEY": "openai",  # OpenClaw 使用 OpenAI 兼容接口
        }.get(key_name, "unknown")
```

### 13.8 [M6 修复] ExecutionSnapshot 投影机制

保留 snapshot 机制，但使用统一 reducer 替代 per-agent reducer：

```python
class ExecutionSnapshot(Base, TimestampMixin):
    """执行的最新 UI 投影。"""
    __tablename__ = "execution_snapshots"

    execution_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("executions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(100))
    projection: Mapped[dict] = mapped_column(JSONB, default=dict)
    # projection 结构（所有 runtime_type 统一）:
    # {
    #   "last_text": "...",           # 最新文本输出（截断）
    #   "tool_count": 5,              # 工具调用次数
    #   "current_tool": "nuclei",     # 当前正在执行的工具
    #   "artifacts": [...],           # 产出物列表
    #   "approval_pending": null,     # 待审批请求
    #   "error": null,                # 最新错误
    # }


def apply_execution_event(projection: dict, event_type: str, payload: dict) -> dict:
    """统一 reducer，所有 runtime_type 共用。"""
    if event_type == "text":
        content = payload.get("content", "")
        projection["last_text"] = content[-500:]  # 保留最后 500 字符
    elif event_type == "tool_use":
        projection["tool_count"] = projection.get("tool_count", 0) + 1
        projection["current_tool"] = payload.get("tool", "")
    elif event_type == "tool_result":
        projection["current_tool"] = None
    elif event_type == "artifact":
        artifacts = projection.get("artifacts", [])
        artifacts.append(payload)
        projection["artifacts"] = artifacts[-20:]  # 最多保留 20 个
    elif event_type == "approval_request":
        projection["approval_pending"] = payload
    elif event_type == "error":
        projection["error"] = payload.get("content", "")[:1000]
    return projection
```

### 13.9 [M7 修复] RuntimeSession 抽象化

```python
@dataclass
class RuntimeSession:
    """一次执行的会话，不暴露底层实现细节。"""
    messages: asyncio.Queue[CLIMessage | None]
    result: asyncio.Future[CLIResult]

    # 控制方法（由 Provider 在创建时注入）
    _inject_fn: Callable[[str], Awaitable[None]] | None = None
    _cancel_fn: Callable[[], Awaitable[None]] | None = None
    _drain_task: asyncio.Task | None = None

    async def inject_message(self, message: str) -> None:
        """向 Agent 注入用户消息。"""
        if self._inject_fn:
            await self._inject_fn(message)

    async def cancel(self) -> None:
        """取消执行。"""
        if self._cancel_fn:
            await self._cancel_fn()
        if self._drain_task:
            self._drain_task.cancel()

    async def iter_messages(self) -> AsyncIterator[CLIMessage]:
        while True:
            msg = await self.messages.get()
            if msg is None:
                break
            yield msg
```

这样 `RuntimeProvider` 接口简化为只有 `execute()` 方法，控制逻辑封装在 `RuntimeSession` 内部：

```python
class RuntimeProvider(Protocol):
    provider_type: str

    async def execute(self, prompt: str, *, container_id: str, **kwargs) -> RuntimeSession:
        ...
```

### 13.10 [m5/m8 修复] 索引补充 + WebSocket 复用

**索引：**
```python
class Execution(BaseModel):
    __table_args__ = (
        Index("executions_workspace_status_idx", "workspace_id", "status"),
        Index("executions_mission_idx", "mission_id"),
        Index("executions_agent_profile_idx", "agent_profile_id"),
        Index("executions_parent_idx", "parent_execution_id"),
        Index("executions_user_created_idx", "user_id", "created_at"),
    )
```

**WebSocket：** 复用现有的共享连接模式，不使用 per-execution 连接：

```
# 替代 /ws/executions/{execution_id}
# 复用现有 /ws/runs 模式：

/ws/executions                          # 共享连接
  → client sends: {"type": "subscribe", "execution_id": "...", "after_seq": 0}
  → server sends: {"type": "snapshot", ...}
  → server sends: {"type": "event", ...}  (实时流)
  → client sends: {"type": "unsubscribe", "execution_id": "..."}
```
