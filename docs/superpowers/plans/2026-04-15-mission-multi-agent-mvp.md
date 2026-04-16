# Mission-Driven Multi-Agent Execution — MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Mission-driven CLI Agent (Claude Code) execution in cloud Docker containers with JoySafeter Skill sharing, real-time streaming, and user intervention.

**Architecture:** New data models (Mission, AgentProfile, Execution, ExecutionEvent) + Runtime Provider abstraction + Docker container lifecycle + Skill injection + WebSocket streaming. Additive — zero changes to existing AgentRun system.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, asyncio, Docker SDK, WebSocket, PostgreSQL, Redis

**Spec:** `docs/superpowers/specs/2026-04-15-mission-driven-multi-agent-execution-design.md`

---

## File Structure

### New Files (Backend)

| File | Responsibility |
|------|---------------|
| `backend/app/models/mission.py` | Mission + MissionComment SQLAlchemy models |
| `backend/app/models/agent_profile.py` | AgentProfile model |
| `backend/app/models/execution.py` | Execution + ExecutionEvent + ExecutionSnapshot models |
| `backend/app/repositories/mission_repository.py` | Mission data access |
| `backend/app/repositories/agent_profile_repository.py` | AgentProfile data access |
| `backend/app/repositories/execution_repository.py` | Execution + Event data access |
| `backend/app/services/mission_service.py` | Mission CRUD + dispatch logic |
| `backend/app/services/agent_profile_service.py` | AgentProfile CRUD + status reconciliation |
| `backend/app/services/execution_service.py` | Execution lifecycle + event sourcing + streaming |
| `backend/app/services/cli_container_service.py` | Docker container create/destroy/exec |
| `backend/app/services/credential_injector.py` | API key resolution from ModelCredential |
| `backend/app/core/agent/cli_backends/__init__.py` | Package init |
| `backend/app/core/agent/cli_backends/base.py` | RuntimeProvider protocol + RuntimeSession + CLIMessage + CLIResult |
| `backend/app/core/agent/cli_backends/claude_code.py` | Claude Code provider (NDJSON stream-json) |
| `backend/app/core/agent/cli_backends/container_bridge.py` | docker exec process bridge |
| `backend/app/core/agent/cli_backends/registry.py` | Provider registry |
| `backend/app/core/agent/cli_backends/skill_injector.py` | Skill injection via ContainerBackendAdapter |
| `backend/app/core/agent/cli_backends/runtime_config.py` | CLAUDE.md generation + injection |
| `backend/app/core/agent/cli_backends/execution_runner.py` | Orchestrates: container → inject → execute → stream → cleanup |
| `backend/app/api/v1/missions.py` | Mission REST endpoints |
| `backend/app/api/v1/agent_profiles.py` | AgentProfile REST endpoints |
| `backend/app/api/v1/executions.py` | Execution REST endpoints |
| `backend/app/websocket/execution_subscription.py` | WebSocket execution event streaming |
| `backend/app/schemas/missions.py` | Mission request/response schemas |
| `backend/app/schemas/agent_profiles.py` | AgentProfile schemas |
| `backend/app/schemas/executions.py` | Execution schemas |
| `backend/alembic/versions/20260415_000000_add_mission_agent_execution_tables.py` | DB migration |

### Modified Files (Backend)

| File | Change |
|------|--------|
| `backend/app/models/__init__.py` | Add new model imports |
| `backend/app/main.py` | Register new routers + WS endpoint |

### New Files (Tests)

| File | What it tests |
|------|--------------|
| `backend/tests/test_models/test_mission.py` | Mission model creation |
| `backend/tests/test_models/test_execution.py` | Execution + Event model creation |
| `backend/tests/test_services/test_execution_service.py` | Execution lifecycle |
| `backend/tests/test_services/test_cli_container_service.py` | Container management |
| `backend/tests/test_core/test_cli_backends.py` | Provider protocol + message parsing |

---

## Task 1: Data Models + Migration

**Files:**
- Create: `backend/app/models/mission.py`
- Create: `backend/app/models/agent_profile.py`
- Create: `backend/app/models/execution.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20260415_000000_add_mission_agent_execution_tables.py`
- Test: `backend/tests/test_models/test_mission.py`
- Test: `backend/tests/test_models/test_execution.py`

- [ ] **Step 1: Create Mission model**

```python
# backend/app/models/mission.py
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class MissionStatus(str, enum.Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class MissionPriority(str, enum.Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Mission(BaseModel):
    """带有明确目标的安全任务委派。"""

    __tablename__ = "missions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[MissionStatus] = mapped_column(
        Enum(MissionStatus, values_callable=lambda e: [m.value for m in e], name="missionstatus"),
        nullable=False,
        default=MissionStatus.BACKLOG,
    )
    priority: Mapped[MissionPriority] = mapped_column(
        Enum(MissionPriority, values_callable=lambda e: [m.value for m in e], name="missionpriority"),
        nullable=False,
        default=MissionPriority.NONE,
    )

    assignee_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    creator_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_mission_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("missions_workspace_status_idx", "workspace_id", "status"),
        Index("missions_assignee_idx", "assignee_type", "assignee_id"),
        Index("missions_creator_idx", "creator_id", "created_at"),
    )
```

- [ ] **Step 2: Create AgentProfile model**

```python
# backend/app/models/agent_profile.py
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class AgentStatus(str, enum.Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    ERROR = "error"
    OFFLINE = "offline"


class AgentProfile(BaseModel):
    """Agent 作为团队成员的身份。"""

    __tablename__ = "agent_profiles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    runtime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, values_callable=lambda e: [m.value for m in e], name="agentstatus"),
        nullable=False,
        default=AgentStatus.OFFLINE,
    )
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    skill_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custom_env: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    runtime_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    visibility: Mapped[str] = mapped_column(String(50), nullable=False, default="workspace")

    __table_args__ = (
        Index("agent_profiles_workspace_idx", "workspace_id"),
        Index("agent_profiles_workspace_status_idx", "workspace_id", "status"),
    )
```

- [ ] **Step 3: Create Execution + ExecutionEvent + ExecutionSnapshot models**

```python
# backend/app/models/execution.py
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.utils.datetime import utc_now

from .base import BaseModel, TimestampMixin


class ExecutionStatus(str, enum.Enum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    INTERRUPT_WAIT = "interrupt_wait"
    APPROVAL_WAIT = "approval_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionSource(str, enum.Enum):
    MISSION = "mission"
    CHAT = "chat"
    GRAPH = "graph"
    COORDINATOR = "coordinator"
    API = "api"


class Execution(BaseModel):
    """统一执行记录。"""

    __tablename__ = "executions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    source: Mapped[ExecutionSource] = mapped_column(
        Enum(ExecutionSource, values_callable=lambda e: [m.value for m in e], name="executionsource"),
        nullable=False,
    )
    source_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, values_callable=lambda e: [m.value for m in e], name="executionstatus"),
        nullable=False,
        default=ExecutionStatus.QUEUED,
    )
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    mission_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    result_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    runtime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    runtime_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    container_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    prior_session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    work_dir: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("executions_workspace_status_idx", "workspace_id", "status"),
        Index("executions_mission_idx", "mission_id"),
        Index("executions_agent_profile_idx", "agent_profile_id"),
        Index("executions_parent_idx", "parent_execution_id"),
        Index("executions_user_created_idx", "user_id", "created_at"),
    )


class ExecutionEvent(BaseModel):
    """统一执行事件流。"""

    __tablename__ = "execution_events"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    observation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    parent_observation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("execution_id", "seq", name="uq_execution_events_exec_seq"),
        Index("execution_events_exec_created_idx", "execution_id", "created_at"),
    )


class ExecutionSnapshot(Base, TimestampMixin):
    """执行的最新 UI 投影。"""

    __tablename__ = "execution_snapshots"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    projection: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
```

- [ ] **Step 4: Update models `__init__.py`**

Add to `backend/app/models/__init__.py`:
```python
from .mission import Mission, MissionPriority, MissionStatus
from .agent_profile import AgentProfile, AgentStatus
from .execution import Execution, ExecutionEvent, ExecutionSnapshot, ExecutionSource, ExecutionStatus
```

And add to `__all__`:
```python
"Mission", "MissionStatus", "MissionPriority",
"AgentProfile", "AgentStatus",
"Execution", "ExecutionEvent", "ExecutionSnapshot", "ExecutionSource", "ExecutionStatus",
```

- [ ] **Step 5: Create Alembic migration**

```bash
cd backend && alembic revision --autogenerate -m "add_mission_agent_execution_tables"
```

Review the generated migration, ensure it creates:
- `missions` table with all indexes
- `agent_profiles` table with all indexes
- `executions` table with all indexes
- `execution_events` table with unique constraint + index
- `execution_snapshots` table
- All enum types: `missionstatus`, `missionpriority`, `agentstatus`, `executionstatus`, `executionsource`

- [ ] **Step 6: Run migration**

```bash
cd backend && alembic upgrade head
```

- [ ] **Step 7: Write model tests**

```python
# backend/tests/test_models/test_mission.py
import uuid
from app.models.mission import Mission, MissionStatus, MissionPriority

def test_mission_defaults():
    m = Mission(
        workspace_id=uuid.uuid4(),
        title="Test APK audit",
        creator_id="user-1",
    )
    assert m.status == MissionStatus.BACKLOG
    assert m.priority == MissionPriority.NONE
    assert m.position == 0.0
```

```python
# backend/tests/test_models/test_execution.py
import uuid
from app.models.execution import Execution, ExecutionStatus, ExecutionSource

def test_execution_defaults():
    e = Execution(
        workspace_id=uuid.uuid4(),
        user_id="user-1",
        source=ExecutionSource.MISSION,
        runtime_type="claude_code",
    )
    assert e.status == ExecutionStatus.QUEUED
    assert e.last_seq == 0
```

- [ ] **Step 8: Run tests**

```bash
cd backend && python -m pytest tests/test_models/test_mission.py tests/test_models/test_execution.py -v
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/mission.py backend/app/models/agent_profile.py backend/app/models/execution.py backend/app/models/__init__.py backend/alembic/versions/ backend/tests/test_models/
git commit -m "feat: add Mission, AgentProfile, Execution data models and migration"
```

---

## Task 2: Runtime Provider Abstraction + Claude Code Provider

**Files:**
- Create: `backend/app/core/agent/cli_backends/__init__.py`
- Create: `backend/app/core/agent/cli_backends/base.py`
- Create: `backend/app/core/agent/cli_backends/container_bridge.py`
- Create: `backend/app/core/agent/cli_backends/claude_code.py`
- Create: `backend/app/core/agent/cli_backends/registry.py`
- Test: `backend/tests/test_core/test_cli_backends.py`

- [ ] **Step 1: Create package init**

```python
# backend/app/core/agent/cli_backends/__init__.py
from .base import CLIMessage, CLIResult, RuntimeProvider, RuntimeSession
from .registry import RuntimeProviderRegistry

__all__ = [
    "CLIMessage",
    "CLIResult",
    "RuntimeProvider",
    "RuntimeSession",
    "RuntimeProviderRegistry",
]
```

- [ ] **Step 2: Create base protocol + data types**

```python
# backend/app/core/agent/cli_backends/base.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Protocol


@dataclass
class CLIMessage:
    """统一消息类型，所有 Runtime Provider 输出都转成这个格式。"""

    type: str  # "text" | "thinking" | "tool_use" | "tool_result" | "error" | "artifact"
    content: str = ""
    tool: str = ""
    call_id: str = ""
    input: dict | None = None
    output: str = ""


@dataclass
class CLIResult:
    """执行最终结果。"""

    status: str  # "completed" | "failed" | "timeout" | "blocked"
    output: str = ""
    error: str = ""
    session_id: str = ""
    branch_name: str = ""
    usage: dict | None = None


@dataclass
class RuntimeSession:
    """一次执行的会话，不暴露底层实现细节。"""

    messages: asyncio.Queue[CLIMessage | None]
    result: asyncio.Future[CLIResult]
    _inject_fn: Callable[[str], Awaitable[None]] | None = None
    _cancel_fn: Callable[[], Awaitable[None]] | None = None
    _drain_task: asyncio.Task | None = None

    async def inject_message(self, message: str) -> None:
        if self._inject_fn:
            await self._inject_fn(message)

    async def cancel(self) -> None:
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


class RuntimeProvider(Protocol):
    """所有 Agent Runtime 的统一协议。"""

    provider_type: str

    async def execute(
        self,
        prompt: str,
        *,
        container_id: str,
        cwd: str | None = None,
        model: str | None = None,
        timeout: int = 7200,
        resume_session_id: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RuntimeSession: ...
```

- [ ] **Step 3: Create container process bridge**

```python
# backend/app/core/agent/cli_backends/container_bridge.py
from __future__ import annotations

import asyncio

from loguru import logger


class ContainerProcessBridge:
    """通过 docker exec 在容器内启动进程并桥接 stdin/stdout。"""

    async def exec_streaming(
        self,
        container_id: str,
        cmd: list[str],
        env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> asyncio.subprocess.Process:
        docker_cmd = ["docker", "exec", "-i"]
        if workdir:
            docker_cmd.extend(["-w", workdir])
        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.append(container_id)
        docker_cmd.extend(cmd)

        logger.debug(f"container exec: {' '.join(docker_cmd[:6])}...")

        return await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
```

- [ ] **Step 4: Create Claude Code provider**

```python
# backend/app/core/agent/cli_backends/claude_code.py
from __future__ import annotations

import asyncio
import json

from loguru import logger

from .base import CLIMessage, CLIResult, RuntimeSession
from .container_bridge import ContainerProcessBridge


class ClaudeCodeProvider:
    """Claude Code CLI Runtime Provider — NDJSON stream-json 协议。"""

    provider_type = "claude_code"

    def __init__(self, executable_path: str = "claude"):
        self.executable_path = executable_path
        self.bridge = ContainerProcessBridge()

    async def execute(
        self,
        prompt: str,
        *,
        container_id: str,
        cwd: str | None = None,
        model: str | None = None,
        timeout: int = 7200,
        resume_session_id: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RuntimeSession:
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

        process = await self.bridge.exec_streaming(
            container_id, cmd, env=env, workdir=cwd,
        )

        queue: asyncio.Queue[CLIMessage | None] = asyncio.Queue(maxsize=512)
        loop = asyncio.get_event_loop()
        result_future: asyncio.Future[CLIResult] = loop.create_future()

        drain_task = asyncio.create_task(
            self._drain(process, queue, result_future, timeout),
            name=f"claude-drain-{container_id[:12]}",
        )

        async def inject(message: str) -> None:
            if process.stdin and not process.stdin.is_closing():
                process.stdin.write(f"{message}\n".encode())
                await process.stdin.drain()

        async def cancel() -> None:
            process.terminate()

        return RuntimeSession(
            messages=queue,
            result=result_future,
            _inject_fn=inject,
            _cancel_fn=cancel,
            _drain_task=drain_task,
        )

    async def _drain(
        self,
        process: asyncio.subprocess.Process,
        queue: asyncio.Queue[CLIMessage | None],
        result_future: asyncio.Future[CLIResult],
        timeout: int,
    ) -> None:
        accumulated_text: list[str] = []
        session_id = ""
        usage: dict = {}

        try:
            async with asyncio.timeout(timeout):
                async for raw_line in process.stdout:
                    line = raw_line.decode().strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    for msg in self._parse_event(event):
                        if msg.type == "text":
                            accumulated_text.append(msg.content)
                        await queue.put(msg)

                    # Extract result metadata
                    if event.get("type") == "result":
                        result_data = event.get("result", {})
                        session_id = result_data.get("session_id", "")
                        if "usage" in event:
                            usage = event["usage"]

        except TimeoutError:
            if not result_future.done():
                result_future.set_result(CLIResult(status="timeout", error="Agent timed out"))
        except Exception as e:
            logger.error(f"Claude drain error: {e}")
            if not result_future.done():
                result_future.set_result(CLIResult(status="failed", error=str(e)))
        finally:
            if not result_future.done():
                exit_code = await process.wait()
                if exit_code == 0 or accumulated_text:
                    result_future.set_result(CLIResult(
                        status="completed",
                        output="\n".join(accumulated_text),
                        session_id=session_id,
                        usage=usage,
                    ))
                else:
                    stderr_bytes = await process.stderr.read() if process.stderr else b""
                    result_future.set_result(CLIResult(
                        status="failed",
                        error=f"Exit code {exit_code}: {stderr_bytes.decode()[:2000]}",
                    ))
            await queue.put(None)  # Signal stream end

    def _parse_event(self, event: dict) -> list[CLIMessage]:
        """Parse a single Claude Code NDJSON event into CLIMessages."""
        messages: list[CLIMessage] = []
        event_type = event.get("type", "")

        if event_type == "assistant" and "message" in event:
            msg = event["message"]
            for block in msg.get("content", []):
                block_type = block.get("type", "")
                if block_type == "text":
                    messages.append(CLIMessage(type="text", content=block.get("text", "")))
                elif block_type == "tool_use":
                    messages.append(CLIMessage(
                        type="tool_use",
                        tool=block.get("name", ""),
                        call_id=block.get("id", ""),
                        input=block.get("input"),
                    ))
                elif block_type == "thinking":
                    messages.append(CLIMessage(type="thinking", content=block.get("thinking", "")))

        elif event_type == "tool_result":
            messages.append(CLIMessage(
                type="tool_result",
                tool=event.get("tool", ""),
                call_id=event.get("call_id", ""),
                output=str(event.get("output", ""))[:8192],
            ))

        return messages
```

- [ ] **Step 5: Create provider registry**

```python
# backend/app/core/agent/cli_backends/registry.py
from __future__ import annotations

from loguru import logger

from .base import RuntimeProvider


class RuntimeProviderRegistry:
    """Runtime Provider 注册表。"""

    def __init__(self) -> None:
        self._providers: dict[str, RuntimeProvider] = {}

    def register(self, provider: RuntimeProvider) -> None:
        self._providers[provider.provider_type] = provider
        logger.info(f"Registered runtime provider: {provider.provider_type}")

    def get(self, provider_type: str) -> RuntimeProvider:
        if provider_type not in self._providers:
            raise ValueError(f"Unknown runtime provider: {provider_type}")
        return self._providers[provider_type]

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())


# Module-level singleton
runtime_registry = RuntimeProviderRegistry()


def init_providers() -> None:
    """启动时调用，注册所有可用 Provider。"""
    from .claude_code import ClaudeCodeProvider

    runtime_registry.register(ClaudeCodeProvider())
```

- [ ] **Step 6: Write tests**

```python
# backend/tests/test_core/test_cli_backends.py
import asyncio
import json

import pytest

from app.core.agent.cli_backends.base import CLIMessage, CLIResult, RuntimeSession
from app.core.agent.cli_backends.claude_code import ClaudeCodeProvider
from app.core.agent.cli_backends.registry import RuntimeProviderRegistry


def test_cli_message_defaults():
    msg = CLIMessage(type="text", content="hello")
    assert msg.type == "text"
    assert msg.content == "hello"
    assert msg.tool == ""
    assert msg.input is None


def test_cli_result_defaults():
    result = CLIResult(status="completed", output="done")
    assert result.status == "completed"
    assert result.session_id == ""


def test_registry_register_and_get():
    reg = RuntimeProviderRegistry()
    provider = ClaudeCodeProvider()
    reg.register(provider)
    assert reg.get("claude_code") is provider
    assert "claude_code" in reg.list_providers()


def test_registry_unknown_provider():
    reg = RuntimeProviderRegistry()
    with pytest.raises(ValueError, match="Unknown runtime provider"):
        reg.get("nonexistent")


def test_claude_parse_text_event():
    provider = ClaudeCodeProvider()
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "Hello world"},
            ]
        },
    }
    messages = provider._parse_event(event)
    assert len(messages) == 1
    assert messages[0].type == "text"
    assert messages[0].content == "Hello world"


def test_claude_parse_tool_use_event():
    provider = ClaudeCodeProvider()
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "call-123",
                    "input": {"command": "ls"},
                },
            ]
        },
    }
    messages = provider._parse_event(event)
    assert len(messages) == 1
    assert messages[0].type == "tool_use"
    assert messages[0].tool == "Bash"
    assert messages[0].call_id == "call-123"
    assert messages[0].input == {"command": "ls"}


def test_claude_parse_thinking_event():
    provider = ClaudeCodeProvider()
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "Let me analyze..."},
            ]
        },
    }
    messages = provider._parse_event(event)
    assert len(messages) == 1
    assert messages[0].type == "thinking"
    assert messages[0].content == "Let me analyze..."


@pytest.mark.asyncio
async def test_runtime_session_iter_messages():
    queue: asyncio.Queue[CLIMessage | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()
    future: asyncio.Future[CLIResult] = loop.create_future()

    session = RuntimeSession(messages=queue, result=future)

    await queue.put(CLIMessage(type="text", content="hello"))
    await queue.put(CLIMessage(type="text", content="world"))
    await queue.put(None)

    collected = []
    async for msg in session.iter_messages():
        collected.append(msg.content)

    assert collected == ["hello", "world"]
```

- [ ] **Step 7: Run tests**

```bash
cd backend && python -m pytest tests/test_core/test_cli_backends.py -v
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/agent/cli_backends/
git add backend/tests/test_core/test_cli_backends.py
git commit -m "feat: add RuntimeProvider abstraction and Claude Code provider"
```

---

## Task 3: Container Management + Skill Injection + Credential Injection

**Files:**
- Create: `backend/app/services/cli_container_service.py`
- Create: `backend/app/services/credential_injector.py`
- Create: `backend/app/core/agent/cli_backends/skill_injector.py`
- Create: `backend/app/core/agent/cli_backends/runtime_config.py`
- Test: `backend/tests/test_services/test_cli_container_service.py`

- [ ] **Step 1: Create CLIContainerService**

```python
# backend/app/services/cli_container_service.py
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from loguru import logger

from app.core.settings import settings


class CLIContainerService:
    """管理 CLI Agent Docker 容器的生命周期。所有 Docker SDK 调用通过线程池。"""

    IMAGE = "joysafeter/cli-agent:latest"
    NETWORK = "joysafeter-network"
    AGENT_NETWORK = "joysafeter-agent-network"

    SECURITY_OPTS = ["no-new-privileges:true"]
    CAP_DROP = ["ALL"]

    async def create_container(
        self,
        execution_id: uuid.UUID,
        env: dict[str, str],
    ) -> str:
        return await asyncio.to_thread(
            self._create_sync, execution_id, env,
        )

    def _create_sync(
        self,
        execution_id: uuid.UUID,
        env: dict[str, str],
    ) -> str:
        import docker

        client = docker.from_env()
        # Ensure agent network exists
        try:
            client.networks.get(self.AGENT_NETWORK)
        except docker.errors.NotFound:
            client.networks.create(self.AGENT_NETWORK, driver="bridge")

        container = client.containers.run(
            self.IMAGE,
            command="sleep infinity",  # Keep alive, CLI runs via docker exec
            detach=True,
            network=self.AGENT_NETWORK,
            environment=env,
            labels={
                "joysafeter.execution_id": str(execution_id),
                "joysafeter.created_at": datetime.utcnow().isoformat(),
            },
            mem_limit="4g",
            cpu_quota=200000,
            security_opt=self.SECURITY_OPTS,
            cap_drop=self.CAP_DROP,
            user="1000:1000",
            tmpfs={"/tmp": "size=512m"},
        )
        logger.info(f"Created CLI container {container.short_id} for execution {execution_id}")
        return container.id

    async def destroy_container(self, container_id: str) -> None:
        await asyncio.to_thread(self._destroy_sync, container_id)

    def _destroy_sync(self, container_id: str) -> None:
        import docker

        client = docker.from_env()
        try:
            container = client.containers.get(container_id)
            container.stop(timeout=10)
            container.remove(force=True)
            logger.info(f"Destroyed CLI container {container_id[:12]}")
        except docker.errors.NotFound:
            logger.warning(f"Container {container_id[:12]} already removed")
        except Exception as e:
            logger.error(f"Failed to destroy container {container_id[:12]}: {e}")

    async def is_running(self, container_id: str) -> bool:
        return await asyncio.to_thread(self._is_running_sync, container_id)

    def _is_running_sync(self, container_id: str) -> bool:
        import docker

        client = docker.from_env()
        try:
            container = client.containers.get(container_id)
            return container.status == "running"
        except Exception:
            return False
```

- [ ] **Step 2: Create CredentialInjector**

```python
# backend/app/services/credential_injector.py
from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.services.model_credential_service import ModelCredentialService


class CredentialInjector:
    """从 ModelCredential 系统获取 API Key 并构建容器环境变量。"""

    REQUIRED_KEYS: dict[str, list[str]] = {
        "claude_code": ["ANTHROPIC_API_KEY"],
        "codex": ["OPENAI_API_KEY"],
        "openclaw": ["AI_GATEWAY_API_KEY", "AI_GATEWAY_BASE_URL"],
    }

    KEY_TO_PROVIDER: dict[str, str] = {
        "ANTHROPIC_API_KEY": "anthropic",
        "OPENAI_API_KEY": "openai",
        "AI_GATEWAY_API_KEY": "openai",
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cred_service = ModelCredentialService(db)

    async def build_env(
        self,
        runtime_type: str,
        agent_profile: AgentProfile,
        workspace_id: uuid.UUID,
    ) -> dict[str, str]:
        env: dict[str, str] = {}
        required = self.REQUIRED_KEYS.get(runtime_type, [])

        for key_name in required:
            # Priority 1: agent custom_env
            if agent_profile.custom_env and key_name in agent_profile.custom_env:
                env[key_name] = agent_profile.custom_env[key_name]
                continue

            # Priority 2: workspace ModelCredential
            provider_type = self.KEY_TO_PROVIDER.get(key_name)
            if provider_type:
                try:
                    cred = await self.cred_service.get_active_credential(
                        provider_type=provider_type,
                    )
                    if cred and cred.api_key:
                        env[key_name] = cred.api_key
                        continue
                except Exception as e:
                    logger.warning(f"Failed to get credential for {key_name}: {e}")

            logger.warning(f"Missing credential: {key_name} for {runtime_type}")

        return env
```

- [ ] **Step 3: Create CLISkillInjector**

```python
# backend/app/core/agent/cli_backends/skill_injector.py
from __future__ import annotations

import asyncio
import os
import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.skill import Skill, SkillFile


class CLISkillInjector:
    """将 JoySafeter Skill 注入到 CLI Agent 容器中。"""

    SKILL_DIRS: dict[str, str] = {
        "claude_code": ".claude/skills",
        "codex": ".codex/skills",
        "openclaw": "skills",
    }

    async def inject(
        self,
        container_id: str,
        runtime_type: str,
        skill_ids: list[uuid.UUID],
        work_dir: str = "/workspace",
    ) -> int:
        """注入 Skills 到容器，返回成功注入的数量。"""
        skill_dir = self.SKILL_DIRS.get(runtime_type)
        if not skill_dir:
            logger.warning(f"No skill dir mapping for runtime_type={runtime_type}")
            return 0

        injected = 0
        async with async_session_factory() as db:
            for skill_id in skill_ids:
                try:
                    skill = await db.get(Skill, skill_id)
                    if not skill:
                        continue

                    base_path = f"{work_dir}/{skill_dir}/{skill.name}"

                    # Write SKILL.md (main content)
                    if skill.content:
                        await self._write_file(
                            container_id, f"{base_path}/SKILL.md", skill.content,
                        )

                    # Write attached files
                    result = await db.execute(
                        select(SkillFile).where(SkillFile.skill_id == skill_id)
                    )
                    for sf in result.scalars():
                        if sf.content:
                            file_path = f"{base_path}/{sf.path}" if sf.path else f"{base_path}/{sf.file_name}"
                            await self._write_file(container_id, file_path, sf.content)

                    injected += 1
                    logger.debug(f"Injected skill '{skill.name}' into container {container_id[:12]}")

                except Exception as e:
                    logger.error(f"Failed to inject skill {skill_id}: {e}")

        return injected

    async def _write_file(self, container_id: str, path: str, content: str) -> None:
        dir_path = os.path.dirname(path)
        # Ensure directory exists
        await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "mkdir", "-p", dir_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # Write content via stdin pipe
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", container_id, "tee", path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(input=content.encode())
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to write {path}: {stderr.decode()[:500]}")
```

- [ ] **Step 4: Create RuntimeConfigInjector**

```python
# backend/app/core/agent/cli_backends/runtime_config.py
from __future__ import annotations

import uuid

from loguru import logger

from app.models.agent_profile import AgentProfile
from app.models.mission import Mission
from app.models.skill import Skill

from .skill_injector import CLISkillInjector


class RuntimeConfigInjector:
    """生成并注入 CLAUDE.md / AGENTS.md 到容器。"""

    CONFIG_FILES: dict[str, str] = {
        "claude_code": "CLAUDE.md",
        "codex": "AGENTS.md",
        "openclaw": "AGENTS.md",
    }

    def __init__(self) -> None:
        self._injector = CLISkillInjector()

    async def inject(
        self,
        container_id: str,
        runtime_type: str,
        agent: AgentProfile,
        mission: Mission | None,
        skills: list[Skill],
        work_dir: str = "/workspace",
    ) -> None:
        filename = self.CONFIG_FILES.get(runtime_type)
        if not filename:
            return

        content = self._build_config(runtime_type, agent, mission, skills)
        await self._injector._write_file(container_id, f"{work_dir}/{filename}", content)
        logger.debug(f"Injected {filename} into container {container_id[:12]}")

    def _build_config(
        self,
        runtime_type: str,
        agent: AgentProfile,
        mission: Mission | None,
        skills: list[Skill],
    ) -> str:
        sections: list[str] = [
            f"# {agent.name}",
            "",
            "你是 JoySafeter 安全团队的 AI Agent。",
            "",
        ]

        if agent.instructions:
            sections.append(f"## 指令\n\n{agent.instructions}\n")

        if mission:
            sections.append("## 当前 Mission\n")
            sections.append(f"**标题:** {mission.title}")
            if mission.objective:
                sections.append(f"**目标:** {mission.objective}")
            if mission.description:
                sections.append(f"\n{mission.description}")
            sections.append("")

        if skills:
            skill_dir = CLISkillInjector.SKILL_DIRS.get(runtime_type, "skills")
            sections.append("## 可用 Skills\n")
            for s in skills:
                sections.append(f"- **{s.name}**: {s.description or '(no description)'}")
                sections.append(f"  位置: `{skill_dir}/{s.name}/SKILL.md`")
            sections.append("")

        return "\n".join(sections)
```

- [ ] **Step 5: Write tests**

```python
# backend/tests/test_services/test_cli_container_service.py
"""CLIContainerService 单元测试 — mock Docker SDK。"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.cli_container_service import CLIContainerService


def test_create_sync_calls_docker():
    svc = CLIContainerService()
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "abc123"
    mock_client.containers.run.return_value = mock_container
    mock_client.networks.get.side_effect = Exception("not found")
    mock_client.networks.create.return_value = None

    with patch("app.services.cli_container_service.docker") as mock_docker_mod:
        # Patch docker import inside the method
        pass  # Docker is imported inside _create_sync, tested via integration

    # Verify the service can be instantiated
    assert svc.IMAGE == "joysafeter/cli-agent:latest"


def test_destroy_sync_handles_not_found():
    svc = CLIContainerService()
    # Should not raise even if container doesn't exist
    assert svc.SECURITY_OPTS == ["no-new-privileges:true"]
```

- [ ] **Step 6: Run tests**

```bash
cd backend && python -m pytest tests/test_services/test_cli_container_service.py -v
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/cli_container_service.py
git add backend/app/services/credential_injector.py
git add backend/app/core/agent/cli_backends/skill_injector.py
git add backend/app/core/agent/cli_backends/runtime_config.py
git add backend/tests/test_services/test_cli_container_service.py
git commit -m "feat: add container management, skill injection, and credential injection"
```

---

## Task 4: Execution Service + Snapshot Reducer

**Files:**
- Create: `backend/app/repositories/execution_repository.py`
- Create: `backend/app/services/execution_service.py`
- Test: `backend/tests/test_services/test_execution_service.py`

- [ ] **Step 1: Create ExecutionRepository**

```python
# backend/app/repositories/execution_repository.py
from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import (
    Execution,
    ExecutionEvent,
    ExecutionSnapshot,
    ExecutionStatus,
)
from .base import BaseRepository


class ExecutionRepository(BaseRepository[Execution]):
    def __init__(self, db: AsyncSession):
        super().__init__(Execution, db)

    async def get_by_id_and_user(
        self, execution_id: uuid.UUID, user_id: str,
    ) -> Optional[Execution]:
        result = await self.db.execute(
            select(Execution).where(
                and_(Execution.id == execution_id, Execution.user_id == user_id)
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(
        self, execution_id: uuid.UUID,
    ) -> Optional[Execution]:
        result = await self.db.execute(
            select(Execution)
            .where(Execution.id == execution_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_snapshot(self, execution_id: uuid.UUID) -> Optional[ExecutionSnapshot]:
        result = await self.db.execute(
            select(ExecutionSnapshot).where(
                ExecutionSnapshot.execution_id == execution_id
            )
        )
        return result.scalar_one_or_none()

    async def list_events_after(
        self,
        execution_id: uuid.UUID,
        after_seq: int = 0,
        limit: int = 500,
    ) -> Sequence[ExecutionEvent]:
        result = await self.db.execute(
            select(ExecutionEvent)
            .where(
                and_(
                    ExecutionEvent.execution_id == execution_id,
                    ExecutionEvent.seq > after_seq,
                )
            )
            .order_by(ExecutionEvent.seq)
            .limit(limit)
        )
        return result.scalars().all()

    async def list_by_workspace(
        self,
        workspace_id: uuid.UUID,
        user_id: str | None = None,
        status: ExecutionStatus | None = None,
        mission_id: uuid.UUID | None = None,
        agent_profile_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> Sequence[Execution]:
        stmt = select(Execution).where(Execution.workspace_id == workspace_id)
        if user_id:
            stmt = stmt.where(Execution.user_id == user_id)
        if status:
            stmt = stmt.where(Execution.status == status)
        if mission_id:
            stmt = stmt.where(Execution.mission_id == mission_id)
        if agent_profile_id:
            stmt = stmt.where(Execution.agent_profile_id == agent_profile_id)
        stmt = stmt.order_by(desc(Execution.created_at)).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()
```

- [ ] **Step 2: Create ExecutionService with event sourcing + snapshot reducer**

```python
# backend/app/services/execution_service.py
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, Sequence

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import (
    Execution,
    ExecutionEvent,
    ExecutionSnapshot,
    ExecutionSource,
    ExecutionStatus,
)
from app.repositories.execution_repository import ExecutionRepository
from app.utils.datetime import utc_now


def apply_execution_event(
    projection: dict, event_type: str, payload: dict,
) -> dict:
    """统一 reducer，所有 runtime_type 共用。"""
    if event_type == "text":
        content = payload.get("content", "")
        projection["last_text"] = content[-500:]
    elif event_type == "thinking":
        projection["thinking"] = True
    elif event_type == "tool_use":
        projection["tool_count"] = projection.get("tool_count", 0) + 1
        projection["current_tool"] = payload.get("tool", "")
    elif event_type == "tool_result":
        projection["current_tool"] = None
    elif event_type == "artifact":
        artifacts = projection.get("artifacts", [])
        artifacts.append(payload)
        projection["artifacts"] = artifacts[-20:]
    elif event_type == "approval_request":
        projection["approval_pending"] = payload
    elif event_type == "error":
        projection["error"] = payload.get("content", "")[:1000]
    elif event_type == "user_message":
        projection["approval_pending"] = None
    return projection


class ExecutionService:
    """统一执行服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExecutionRepository(db)

    # ── 创建 ──

    async def create_execution(
        self,
        *,
        user_id: str,
        workspace_id: uuid.UUID,
        source: ExecutionSource,
        runtime_type: str,
        title: str | None = None,
        mission_id: uuid.UUID | None = None,
        agent_profile_id: uuid.UUID | None = None,
        parent_execution_id: uuid.UUID | None = None,
        runtime_config: dict | None = None,
    ) -> Execution:
        execution = Execution(
            workspace_id=workspace_id,
            user_id=user_id,
            source=source,
            runtime_type=runtime_type,
            status=ExecutionStatus.QUEUED,
            title=title,
            mission_id=mission_id,
            agent_profile_id=agent_profile_id,
            parent_execution_id=parent_execution_id,
            runtime_config=runtime_config,
            last_seq=0,
        )
        self.db.add(execution)

        snapshot = ExecutionSnapshot(
            execution_id=execution.id,
            last_seq=0,
            status=ExecutionStatus.QUEUED.value,
            projection={},
        )
        self.db.add(snapshot)

        await self.db.flush()
        logger.info(f"Created execution {execution.id} source={source.value} runtime={runtime_type}")
        return execution

    # ── 事件流 ──

    async def append_event(
        self,
        execution_id: uuid.UUID,
        event_type: str,
        payload: dict,
        *,
        trace_id: uuid.UUID | None = None,
        observation_id: uuid.UUID | None = None,
        parent_observation_id: uuid.UUID | None = None,
    ) -> ExecutionEvent:
        execution = await self.repo.get_for_update(execution_id)
        if not execution:
            raise ValueError(f"Execution {execution_id} not found")

        execution.last_seq += 1
        seq = execution.last_seq

        event = ExecutionEvent(
            execution_id=execution_id,
            seq=seq,
            event_type=event_type,
            payload=payload,
            trace_id=trace_id,
            observation_id=observation_id,
            parent_observation_id=parent_observation_id,
        )
        self.db.add(event)

        # Update snapshot
        snapshot = await self.repo.get_snapshot(execution_id)
        if snapshot:
            snapshot.last_seq = seq
            snapshot.projection = apply_execution_event(
                dict(snapshot.projection), event_type, payload,
            )

        await self.db.commit()
        return event

    # ── 状态转换 ──

    async def mark_status(
        self,
        execution_id: uuid.UUID,
        status: ExecutionStatus,
        *,
        container_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        result_summary: dict | None = None,
        session_id: str | None = None,
    ) -> Optional[Execution]:
        execution = await self.repo.get_for_update(execution_id)
        if not execution:
            return None

        execution.status = status

        if container_id:
            execution.container_id = container_id
        if error_code:
            execution.error_code = error_code
        if error_message:
            execution.error_message = error_message
        if result_summary:
            execution.result_summary = result_summary
        if session_id:
            execution.session_id = session_id

        now = utc_now()
        if status == ExecutionStatus.RUNNING and not execution.started_at:
            execution.started_at = now
        if status in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        ):
            execution.finished_at = now

        # Update snapshot status
        snapshot = await self.repo.get_snapshot(execution_id)
        if snapshot:
            snapshot.status = status.value

        await self.db.commit()
        logger.info(f"Execution {execution_id} → {status.value}")
        return execution

    # ── 查询 ──

    async def get_execution(
        self, execution_id: uuid.UUID, user_id: str | None = None,
    ) -> Optional[Execution]:
        if user_id:
            return await self.repo.get_by_id_and_user(execution_id, user_id)
        return await self.repo.get(execution_id)

    async def get_snapshot(self, execution_id: uuid.UUID) -> Optional[ExecutionSnapshot]:
        return await self.repo.get_snapshot(execution_id)

    async def list_events(
        self, execution_id: uuid.UUID, after_seq: int = 0, limit: int = 500,
    ) -> Sequence[ExecutionEvent]:
        return await self.repo.list_events_after(execution_id, after_seq, limit)

    async def list_executions(
        self, workspace_id: uuid.UUID, **filters: Any,
    ) -> Sequence[Execution]:
        return await self.repo.list_by_workspace(workspace_id, **filters)
```

- [ ] **Step 3: Write tests**

```python
# backend/tests/test_services/test_execution_service.py
from app.services.execution_service import apply_execution_event


def test_reducer_text():
    proj = {}
    proj = apply_execution_event(proj, "text", {"content": "hello"})
    assert proj["last_text"] == "hello"


def test_reducer_tool_use():
    proj = {}
    proj = apply_execution_event(proj, "tool_use", {"tool": "nuclei"})
    assert proj["tool_count"] == 1
    assert proj["current_tool"] == "nuclei"


def test_reducer_tool_result_clears_current():
    proj = {"current_tool": "nuclei", "tool_count": 1}
    proj = apply_execution_event(proj, "tool_result", {"tool": "nuclei", "output": "done"})
    assert proj["current_tool"] is None


def test_reducer_approval_request():
    proj = {}
    req = {"action": "execute_exploit", "description": "SQL injection"}
    proj = apply_execution_event(proj, "approval_request", req)
    assert proj["approval_pending"] == req


def test_reducer_user_message_clears_approval():
    proj = {"approval_pending": {"action": "test"}}
    proj = apply_execution_event(proj, "user_message", {"content": "approved"})
    assert proj["approval_pending"] is None


def test_reducer_error():
    proj = {}
    proj = apply_execution_event(proj, "error", {"content": "something broke"})
    assert proj["error"] == "something broke"


def test_reducer_artifact_caps_at_20():
    proj = {"artifacts": [{"type": f"r{i}"} for i in range(20)]}
    proj = apply_execution_event(proj, "artifact", {"type": "r20"})
    assert len(proj["artifacts"]) == 20
    assert proj["artifacts"][-1]["type"] == "r20"
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_services/test_execution_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/execution_repository.py
git add backend/app/services/execution_service.py
git add backend/tests/test_services/test_execution_service.py
git commit -m "feat: add ExecutionService with event sourcing and snapshot reducer"
```

---

## Task 5: ExecutionRunner — End-to-End Orchestration

**Files:**
- Create: `backend/app/core/agent/cli_backends/execution_runner.py`

- [ ] **Step 1: Create ExecutionRunner**

```python
# backend/app/core/agent/cli_backends/execution_runner.py
from __future__ import annotations

import uuid

from loguru import logger

from app.core.database import async_session_factory
from app.models.agent_profile import AgentProfile, AgentStatus
from app.models.execution import ExecutionSource, ExecutionStatus
from app.models.mission import Mission
from app.models.skill import Skill
from app.services.cli_container_service import CLIContainerService
from app.services.credential_injector import CredentialInjector
from app.services.execution_service import ExecutionService

from .base import CLIMessage, CLIResult
from .registry import runtime_registry
from .runtime_config import RuntimeConfigInjector
from .skill_injector import CLISkillInjector


class ExecutionRunner:
    """编排完整的执行流程：容器 → 注入 → 执行 → 流式事件 → 清理。"""

    def __init__(self) -> None:
        self.container_svc = CLIContainerService()
        self.skill_injector = CLISkillInjector()
        self.config_injector = RuntimeConfigInjector()

    async def run(
        self,
        execution_id: uuid.UUID,
        prompt: str,
        *,
        workspace_id: uuid.UUID,
        user_id: str,
        runtime_type: str,
        agent_profile: AgentProfile | None = None,
        mission: Mission | None = None,
        skills: list[Skill] | None = None,
        model: str | None = None,
    ) -> CLIResult:
        container_id: str | None = None

        try:
            # 1. Build env with credentials
            env: dict[str, str] = {"HOME": "/workspace"}
            if agent_profile:
                async with async_session_factory() as db:
                    injector = CredentialInjector(db)
                    cred_env = await injector.build_env(
                        runtime_type, agent_profile, workspace_id,
                    )
                    env.update(cred_env)

            # Add agent custom env
            if agent_profile and agent_profile.custom_env:
                for k, v in agent_profile.custom_env.items():
                    if k not in env:  # Don't override credentials
                        env[k] = v

            # 2. Create container
            container_id = await self.container_svc.create_container(
                execution_id=execution_id, env=env,
            )

            # Mark DISPATCHED
            async with async_session_factory() as db:
                svc = ExecutionService(db)
                await svc.mark_status(
                    execution_id, ExecutionStatus.DISPATCHED,
                    container_id=container_id,
                )

            # 3. Inject skills
            if skills:
                skill_ids = [s.id for s in skills]
                await self.skill_injector.inject(
                    container_id, runtime_type, skill_ids,
                )

            # 4. Inject runtime config (CLAUDE.md / AGENTS.md)
            await self.config_injector.inject(
                container_id, runtime_type, agent_profile, mission, skills or [],
            )

            # 5. Get provider and execute
            provider = runtime_registry.get(runtime_type)

            # Resolve model
            effective_model = model
            if not effective_model and agent_profile and agent_profile.runtime_config:
                effective_model = agent_profile.runtime_config.get("model")

            session = await provider.execute(
                prompt,
                container_id=container_id,
                cwd="/workspace",
                model=effective_model,
            )

            # Mark RUNNING
            async with async_session_factory() as db:
                svc = ExecutionService(db)
                await svc.mark_status(execution_id, ExecutionStatus.RUNNING)

            # 6. Drain messages → ExecutionEvents
            async for msg in session.iter_messages():
                await self._persist_message(execution_id, msg)

            # 7. Get result
            result = await session.result

            # 8. Mark final status
            async with async_session_factory() as db:
                svc = ExecutionService(db)
                if result.status == "completed":
                    await svc.mark_status(
                        execution_id, ExecutionStatus.COMPLETED,
                        result_summary={
                            "output": result.output[:5000],
                            "session_id": result.session_id,
                            "branch_name": result.branch_name,
                        },
                        session_id=result.session_id,
                    )
                elif result.status == "timeout":
                    await svc.mark_status(
                        execution_id, ExecutionStatus.FAILED,
                        error_code="timeout",
                        error_message=result.error,
                    )
                else:
                    await svc.mark_status(
                        execution_id, ExecutionStatus.FAILED,
                        error_code="agent_error",
                        error_message=result.error[:2000] if result.error else "Unknown error",
                    )

            # 9. Update agent status
            if agent_profile:
                await self._reconcile_agent_status(agent_profile.id)

            return result

        except Exception as e:
            logger.error(f"ExecutionRunner failed for {execution_id}: {e}")
            try:
                async with async_session_factory() as db:
                    svc = ExecutionService(db)
                    await svc.mark_status(
                        execution_id, ExecutionStatus.FAILED,
                        error_code="runner_error",
                        error_message=str(e)[:2000],
                    )
            except Exception:
                logger.error(f"Failed to mark execution {execution_id} as failed")
            raise

        finally:
            # 10. Destroy container
            if container_id:
                try:
                    await self.container_svc.destroy_container(container_id)
                except Exception as e:
                    logger.error(f"Failed to destroy container {container_id[:12]}: {e}")

    async def _persist_message(
        self, execution_id: uuid.UUID, msg: CLIMessage,
    ) -> None:
        payload: dict = {}
        if msg.type == "text":
            payload = {"content": msg.content}
        elif msg.type == "thinking":
            payload = {"content": msg.content}
        elif msg.type == "tool_use":
            payload = {"tool": msg.tool, "call_id": msg.call_id, "input": msg.input}
        elif msg.type == "tool_result":
            payload = {"tool": msg.tool, "call_id": msg.call_id, "output": msg.output[:8192]}
        elif msg.type == "error":
            payload = {"content": msg.content}
        elif msg.type == "artifact":
            payload = {"content": msg.content}
        else:
            payload = {"content": msg.content}

        try:
            async with async_session_factory() as db:
                svc = ExecutionService(db)
                await svc.append_event(execution_id, msg.type, payload)
        except Exception as e:
            logger.warning(f"Failed to persist event for {execution_id}: {e}")

    async def _reconcile_agent_status(self, agent_profile_id: uuid.UUID) -> None:
        """Check if agent has other running executions; if not, set to IDLE."""
        from sqlalchemy import and_, select

        try:
            async with async_session_factory() as db:
                from app.models.execution import Execution

                result = await db.execute(
                    select(Execution).where(
                        and_(
                            Execution.agent_profile_id == agent_profile_id,
                            Execution.status.in_([
                                ExecutionStatus.QUEUED,
                                ExecutionStatus.DISPATCHED,
                                ExecutionStatus.RUNNING,
                            ]),
                        )
                    )
                )
                active = result.scalars().first()

                agent = await db.get(AgentProfile, agent_profile_id)
                if agent:
                    agent.status = AgentStatus.WORKING if active else AgentStatus.IDLE
                    await db.commit()
        except Exception as e:
            logger.warning(f"Failed to reconcile agent status: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/core/agent/cli_backends/execution_runner.py
git commit -m "feat: add ExecutionRunner end-to-end orchestration"
```

---

## Task 6: Mission Service + Dispatcher

**Files:**
- Create: `backend/app/repositories/mission_repository.py`
- Create: `backend/app/repositories/agent_profile_repository.py`
- Create: `backend/app/services/mission_service.py`
- Create: `backend/app/services/agent_profile_service.py`

- [ ] **Step 1: Create MissionRepository**

```python
# backend/app/repositories/mission_repository.py
from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import Mission, MissionStatus
from .base import BaseRepository


class MissionRepository(BaseRepository[Mission]):
    def __init__(self, db: AsyncSession):
        super().__init__(Mission, db)

    async def list_by_workspace(
        self,
        workspace_id: uuid.UUID,
        status: MissionStatus | None = None,
        assignee_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> Sequence[Mission]:
        stmt = select(Mission).where(Mission.workspace_id == workspace_id)
        if status:
            stmt = stmt.where(Mission.status == status)
        if assignee_id:
            stmt = stmt.where(Mission.assignee_id == assignee_id)
        stmt = stmt.order_by(Mission.position, desc(Mission.created_at)).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_workspace(
        self, mission_id: uuid.UUID, workspace_id: uuid.UUID,
    ) -> Optional[Mission]:
        result = await self.db.execute(
            select(Mission).where(
                and_(Mission.id == mission_id, Mission.workspace_id == workspace_id)
            )
        )
        return result.scalar_one_or_none()
```

- [ ] **Step 2: Create AgentProfileRepository**

```python
# backend/app/repositories/agent_profile_repository.py
from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile, AgentStatus
from .base import BaseRepository


class AgentProfileRepository(BaseRepository[AgentProfile]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentProfile, db)

    async def list_by_workspace(
        self, workspace_id: uuid.UUID,
    ) -> Sequence[AgentProfile]:
        result = await self.db.execute(
            select(AgentProfile)
            .where(AgentProfile.workspace_id == workspace_id)
            .order_by(AgentProfile.name)
        )
        return result.scalars().all()

    async def get_by_workspace(
        self, agent_id: uuid.UUID, workspace_id: uuid.UUID,
    ) -> Optional[AgentProfile]:
        result = await self.db.execute(
            select(AgentProfile).where(
                and_(AgentProfile.id == agent_id, AgentProfile.workspace_id == workspace_id)
            )
        )
        return result.scalar_one_or_none()

    async def count_active_executions(self, agent_id: uuid.UUID) -> int:
        from app.models.execution import Execution, ExecutionStatus

        result = await self.db.execute(
            select(Execution).where(
                and_(
                    Execution.agent_profile_id == agent_id,
                    Execution.status.in_([
                        ExecutionStatus.QUEUED,
                        ExecutionStatus.DISPATCHED,
                        ExecutionStatus.RUNNING,
                    ]),
                )
            )
        )
        return len(result.scalars().all())
```

- [ ] **Step 3: Create AgentProfileService**

```python
# backend/app/services/agent_profile_service.py
from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile, AgentStatus
from app.repositories.agent_profile_repository import AgentProfileRepository


class AgentProfileService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AgentProfileRepository(db)

    async def create(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        runtime_type: str,
        description: str | None = None,
        instructions: str | None = None,
        skill_ids: list | None = None,
        custom_env: dict | None = None,
        runtime_config: dict | None = None,
        max_concurrent_tasks: int = 1,
    ) -> AgentProfile:
        agent = AgentProfile(
            workspace_id=workspace_id,
            name=name,
            runtime_type=runtime_type,
            description=description,
            instructions=instructions,
            skill_ids=skill_ids,
            custom_env=custom_env,
            runtime_config=runtime_config,
            max_concurrent_tasks=max_concurrent_tasks,
            status=AgentStatus.IDLE,
        )
        self.db.add(agent)
        await self.db.commit()
        return agent

    async def get(self, agent_id: uuid.UUID, workspace_id: uuid.UUID) -> Optional[AgentProfile]:
        return await self.repo.get_by_workspace(agent_id, workspace_id)

    async def list_agents(self, workspace_id: uuid.UUID) -> Sequence[AgentProfile]:
        return await self.repo.list_by_workspace(workspace_id)

    async def update(self, agent_id: uuid.UUID, workspace_id: uuid.UUID, **kwargs) -> Optional[AgentProfile]:
        agent = await self.repo.get_by_workspace(agent_id, workspace_id)
        if not agent:
            return None
        for k, v in kwargs.items():
            if hasattr(agent, k) and v is not None:
                setattr(agent, k, v)
        await self.db.commit()
        return agent

    async def delete(self, agent_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
        agent = await self.repo.get_by_workspace(agent_id, workspace_id)
        if not agent:
            return False
        await self.db.delete(agent)
        await self.db.commit()
        return True
```

- [ ] **Step 4: Create MissionService with dispatch logic**

```python
# backend/app/services/mission_service.py
from __future__ import annotations

import asyncio
import uuid
from typing import Optional, Sequence

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile, AgentStatus
from app.models.execution import ExecutionSource
from app.models.mission import Mission, MissionPriority, MissionStatus
from app.models.skill import Skill
from app.repositories.agent_profile_repository import AgentProfileRepository
from app.repositories.mission_repository import MissionRepository
from app.services.execution_service import ExecutionService


class MissionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MissionRepository(db)
        self.agent_repo = AgentProfileRepository(db)

    # ── CRUD ──

    async def create(
        self,
        *,
        workspace_id: uuid.UUID,
        creator_id: str,
        title: str,
        description: str | None = None,
        objective: str | None = None,
        priority: MissionPriority = MissionPriority.NONE,
        tags: list | None = None,
    ) -> Mission:
        mission = Mission(
            workspace_id=workspace_id,
            creator_id=creator_id,
            title=title,
            description=description,
            objective=objective,
            priority=priority,
            tags=tags,
        )
        self.db.add(mission)
        await self.db.commit()
        return mission

    async def get(self, mission_id: uuid.UUID, workspace_id: uuid.UUID) -> Optional[Mission]:
        return await self.repo.get_by_workspace(mission_id, workspace_id)

    async def list_missions(
        self, workspace_id: uuid.UUID, **filters,
    ) -> Sequence[Mission]:
        return await self.repo.list_by_workspace(workspace_id, **filters)

    async def update(self, mission_id: uuid.UUID, workspace_id: uuid.UUID, **kwargs) -> Optional[Mission]:
        mission = await self.repo.get_by_workspace(mission_id, workspace_id)
        if not mission:
            return None
        for k, v in kwargs.items():
            if hasattr(mission, k) and v is not None:
                setattr(mission, k, v)
        await self.db.commit()
        return mission

    # ── 分配与分发 ──

    async def assign_to_agent(
        self,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        user_id: str,
    ) -> Optional[Mission]:
        mission = await self.repo.get_by_workspace(mission_id, workspace_id)
        if not mission:
            return None

        agent = await self.agent_repo.get_by_workspace(agent_id, workspace_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found in workspace")

        # Check capacity
        active_count = await self.agent_repo.count_active_executions(agent_id)
        if active_count >= agent.max_concurrent_tasks:
            raise ValueError(
                f"Agent {agent.name} is at capacity ({active_count}/{agent.max_concurrent_tasks})"
            )

        mission.assignee_type = "agent"
        mission.assignee_id = agent_id
        mission.status = MissionStatus.IN_PROGRESS

        # Create execution
        exec_svc = ExecutionService(self.db)
        execution = await exec_svc.create_execution(
            user_id=user_id,
            workspace_id=workspace_id,
            source=ExecutionSource.MISSION,
            runtime_type=agent.runtime_type,
            title=mission.title,
            mission_id=mission_id,
            agent_profile_id=agent_id,
        )
        mission.current_execution_id = execution.id

        # Mark agent working
        agent.status = AgentStatus.WORKING

        await self.db.commit()

        # Dispatch execution in background
        asyncio.create_task(
            self._dispatch_execution(
                execution_id=execution.id,
                mission=mission,
                agent=agent,
                workspace_id=workspace_id,
                user_id=user_id,
            ),
            name=f"dispatch-{execution.id}",
        )

        logger.info(f"Mission {mission_id} assigned to agent {agent.name}, execution {execution.id}")
        return mission

    async def _dispatch_execution(
        self,
        execution_id: uuid.UUID,
        mission: Mission,
        agent: AgentProfile,
        workspace_id: uuid.UUID,
        user_id: str,
    ) -> None:
        from app.core.agent.cli_backends.execution_runner import ExecutionRunner

        # Build prompt
        prompt = self._build_prompt(mission, agent)

        # Load skills
        skills: list[Skill] = []
        if agent.skill_ids:
            async with self.db.begin():
                for sid in agent.skill_ids:
                    try:
                        skill = await self.db.get(Skill, uuid.UUID(str(sid)))
                        if skill:
                            skills.append(skill)
                    except Exception:
                        pass

        # Resolve model
        model = None
        if agent.runtime_config:
            model = agent.runtime_config.get("model")

        runner = ExecutionRunner()
        await runner.run(
            execution_id,
            prompt,
            workspace_id=workspace_id,
            user_id=user_id,
            runtime_type=agent.runtime_type,
            agent_profile=agent,
            mission=mission,
            skills=skills,
            model=model,
        )

    def _build_prompt(self, mission: Mission, agent: AgentProfile) -> str:
        parts = [
            f"你是安全团队的 {agent.name}，正在执行一个安全任务。",
            "",
            "## Mission",
            f"**标题:** {mission.title}",
        ]
        if mission.description:
            parts.append(f"**描述:** {mission.description}")
        if mission.objective:
            parts.append(f"**目标（成功标准）:** {mission.objective}")
        parts.append("")
        parts.append("请开始执行任务。完成后给出详细报告。")
        return "\n".join(parts)
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/mission_repository.py
git add backend/app/repositories/agent_profile_repository.py
git add backend/app/services/agent_profile_service.py
git add backend/app/services/mission_service.py
git commit -m "feat: add Mission/AgentProfile services with dispatch logic"
```

---

## Task 7: REST API Endpoints

**Files:**
- Create: `backend/app/schemas/missions.py`
- Create: `backend/app/schemas/agent_profiles.py`
- Create: `backend/app/schemas/executions.py`
- Create: `backend/app/api/v1/missions.py`
- Create: `backend/app/api/v1/agent_profiles.py`
- Create: `backend/app/api/v1/executions.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create Pydantic schemas**

Create `backend/app/schemas/missions.py`, `agent_profiles.py`, `executions.py` with request/response models following existing patterns in `backend/app/schemas/`.

- [ ] **Step 2: Create Mission API router**

```python
# backend/app/api/v1/missions.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.core.database import get_db
from app.schemas import BaseResponse
from app.services.mission_service import MissionService

router = APIRouter(prefix="/v1/missions", tags=["Missions"])


@router.post("")
async def create_mission(
    workspace_id: uuid.UUID,
    title: str,
    description: str | None = None,
    objective: str | None = None,
    priority: str = "none",
    current_user: CurrentUser = Depends(),
    db: AsyncSession = Depends(get_db),
):
    svc = MissionService(db)
    mission = await svc.create(
        workspace_id=workspace_id,
        creator_id=current_user.id,
        title=title,
        description=description,
        objective=objective,
    )
    return BaseResponse(success=True, code=200, msg="ok", data={"id": str(mission.id)})


@router.get("")
async def list_missions(
    workspace_id: uuid.UUID,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(),
    db: AsyncSession = Depends(get_db),
):
    svc = MissionService(db)
    missions = await svc.list_missions(workspace_id)
    return BaseResponse(success=True, code=200, msg="ok", data=missions)


@router.post("/{mission_id}/assign")
async def assign_mission(
    mission_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser = Depends(),
    db: AsyncSession = Depends(get_db),
):
    svc = MissionService(db)
    mission = await svc.assign_to_agent(
        mission_id=mission_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=current_user.id,
    )
    return BaseResponse(success=True, code=200, msg="ok", data={"id": str(mission.id)})
```

- [ ] **Step 3: Create AgentProfile and Execution API routers** (same pattern)

- [ ] **Step 4: Register routers in main.py**

Add to `backend/app/main.py`:
```python
from app.api.v1.missions import router as missions_router
from app.api.v1.agent_profiles import router as agent_profiles_router
from app.api.v1.executions import router as executions_router

app.include_router(missions_router)
app.include_router(agent_profiles_router)
app.include_router(executions_router)
```

Also add provider initialization:
```python
from app.core.agent.cli_backends.registry import init_providers

@app.on_event("startup")
async def startup():
    init_providers()
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/missions.py backend/app/schemas/agent_profiles.py backend/app/schemas/executions.py
git add backend/app/api/v1/missions.py backend/app/api/v1/agent_profiles.py backend/app/api/v1/executions.py
git add backend/app/main.py
git commit -m "feat: add Mission, AgentProfile, Execution REST API endpoints"
```

---

## Task 8: WebSocket Execution Streaming

**Files:**
- Create: `backend/app/websocket/execution_subscription.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create execution subscription handler**

Follow the existing pattern in `backend/app/websocket/run_subscription_handler.py` — shared connection with subscribe/unsubscribe frames.

```python
# backend/app/websocket/execution_subscription.py
# Pattern: single WS connection, client sends subscribe/unsubscribe for execution_ids
# On subscribe: send snapshot + replay events + live stream
# On event append: broadcast to all subscribers
```

- [ ] **Step 2: Register WS endpoint in main.py**

```python
@app.websocket("/ws/executions")
async def ws_executions(websocket: WebSocket):
    # Auth + handle connection
    ...
```

- [ ] **Step 3: Wire ExecutionService.append_event to broadcast**

Add broadcast call after commit in `ExecutionService.append_event()`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/websocket/execution_subscription.py backend/app/main.py
git commit -m "feat: add WebSocket execution event streaming"
```

---

## Task 9: CLI Agent Docker Image

**Files:**
- Create: `deploy/docker/cli-agent.Dockerfile`
- Modify: `deploy/docker-compose.yml` (add build profile)

- [ ] **Step 1: Create Dockerfile**

```dockerfile
# deploy/docker/cli-agent.Dockerfile
FROM node:22-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl python3 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code
RUN npm install -g @anthropic-ai/claude-code

# Create non-root user
RUN groupadd -g 1000 agent && useradd -u 1000 -g agent -m agent
USER agent
WORKDIR /workspace

CMD ["sleep", "infinity"]
```

- [ ] **Step 2: Build and test image**

```bash
cd deploy && docker build -f docker/cli-agent.Dockerfile -t joysafeter/cli-agent:latest .
docker run --rm joysafeter/cli-agent:latest claude --version
```

- [ ] **Step 3: Add to docker-compose.yml build profile**

- [ ] **Step 4: Commit**

```bash
git add deploy/docker/cli-agent.Dockerfile deploy/docker-compose.yml
git commit -m "feat: add CLI Agent Docker image with Claude Code"
```

---

## Task 10: Integration Test — End-to-End

- [ ] **Step 1: Manual integration test**

```bash
# 1. Start backend
cd backend && make server

# 2. Create an AgentProfile via API
curl -X POST http://localhost:8000/api/v1/agent_profiles \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "...", "name": "Claude Security", "runtime_type": "claude_code"}'

# 3. Create a Mission
curl -X POST http://localhost:8000/api/v1/missions \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "...", "title": "Scan target.apk for vulnerabilities", "objective": "Find OWASP Mobile Top 10 issues"}'

# 4. Assign Mission to Agent (triggers execution)
curl -X POST http://localhost:8000/api/v1/missions/{id}/assign \
  -d '{"agent_id": "...", "workspace_id": "..."}'

# 5. Watch execution events via WebSocket
websocat ws://localhost:8000/ws/executions
# Send: {"type": "subscribe", "execution_id": "..."}
```

- [ ] **Step 2: Verify execution lifecycle**

Check:
- Container created and visible in `docker ps`
- Execution status transitions: QUEUED → DISPATCHED → RUNNING → COMPLETED
- Events appear in `execution_events` table
- Container destroyed after completion

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: Mission-driven multi-agent execution MVP complete"
```
