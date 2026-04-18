# Mission/Execution Mediator 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过 Mediator 模式打破 Mission 与 Execution 的循环依赖，统一操作路径，将 Execution 降为内部实现细节，Mission 成为唯一用户入口。

**Architecture:** 新建 `ExecutionLifecycleService` 作为唯一的跨域协调者。`MissionService` 瘦身为纯任务 CRUD + 状态机。`ExecutionRunner` 通过 callback Protocol 回调，不再 import 任何 Service。前端砍掉 Execution 独立页面，所有操作统一走 Mission 端点。

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy AsyncSession, pytest, React/Next.js, TanStack Query

**Phases:**
- Phase 1: RunnerCallbacks Protocol + ExecutionLifecycleService（后端核心）
- Phase 2: MissionService / CommentService 瘦身 + API 端点统一
- Phase 3: 存量问题修复（FK 约束、错误处理、鉴权统一）
- Phase 4: 前端重构（API 切换、缓存修正、删除 Execution 页面）

---

## Phase 1: RunnerCallbacks Protocol + ExecutionLifecycleService

**目标：** 建立 Mediator 核心骨架，所有跨域操作集中到一个服务中。此阶段结束后，新旧路径并存，不破坏现有功能。

**文件总览：**

| 操作 | 文件路径 |
|------|----------|
| 新建 | `backend/app/core/agent/cli_backends/runner_callbacks.py` |
| 新建 | `backend/app/services/execution_lifecycle_service.py` |
| 新建 | `backend/tests/test_core/test_runner_callbacks.py` |
| 新建 | `backend/tests/test_services/test_execution_lifecycle_service.py` |
| 修改 | `backend/app/core/agent/cli_backends/execution_runner.py` |
| 修改 | `backend/tests/test_core/test_execution_runner.py` |

---

### Task 1.1: 定义 RunnerCallbacks Protocol

**目的：** 定义 ExecutionRunner 完成后的回调接口，替代当前的 deferred import。这是打破循环依赖的关键抽象。

**Files:**
- Create: `backend/app/core/agent/cli_backends/runner_callbacks.py`
- Test: `backend/tests/test_core/test_runner_callbacks.py`

**当前问题（`execution_runner.py:413-425, 427-447`）：**
```python
# 当前：deferred import 造成循环依赖
async def _update_mission_status(self, execution_id, status):
    from app.services.mission_service import MissionService  # 循环!
    svc = MissionService(self.db)
    await svc.finalize_mission_execution(...)

async def _post_completion_comment(self, execution_id, status, result=None, error_message=""):
    from app.services.mission_comment_service import MissionCommentService  # 循环!
    svc = MissionCommentService(self.db)
    await svc.post_execution_comment(...)
```

- [ ] **Step 1: 编写 Protocol 定义**

```python
# backend/app/core/agent/cli_backends/runner_callbacks.py
"""
Callback protocol for ExecutionRunner — breaks circular dependency.

ExecutionRunner calls these hooks after finalize/failure.
The concrete implementation lives in ExecutionLifecycleService.
"""
from __future__ import annotations

import uuid
from typing import Optional, Protocol, runtime_checkable

from app.core.agent.cli_backends.base import CLIResult
from app.models.execution import MissionExecutionStatus


@runtime_checkable
class RunnerCallbacks(Protocol):
    """Interface that ExecutionRunner uses to notify lifecycle events."""

    async def on_execution_finalized(
        self,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
        result: CLIResult,
    ) -> None:
        """Called after execution reaches terminal state (COMPLETED/FAILED)."""
        ...

    async def on_execution_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
    ) -> None:
        """Called when runner catches an unhandled exception."""
        ...
```

- [ ] **Step 2: 编写 Protocol 测试**

```python
# backend/tests/test_core/test_runner_callbacks.py
from __future__ import annotations

import uuid

import pytest

from app.core.agent.cli_backends.base import CLIResult
from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.models.execution import MissionExecutionStatus


class FakeCallbacks:
    """Minimal implementation for testing the Protocol contract."""

    def __init__(self):
        self.finalized: list[tuple] = []
        self.failed: list[tuple] = []

    async def on_execution_finalized(self, execution_id, status, result):
        self.finalized.append((execution_id, status, result))

    async def on_execution_failed(self, execution_id, error):
        self.failed.append((execution_id, error))


def test_fake_callbacks_satisfies_protocol():
    cb = FakeCallbacks()
    assert isinstance(cb, RunnerCallbacks)


@pytest.mark.asyncio
async def test_on_execution_finalized_records_call():
    cb = FakeCallbacks()
    eid = uuid.uuid4()
    result = CLIResult(status="completed", output="done", error=None, session_id="s1")
    await cb.on_execution_finalized(eid, MissionExecutionStatus.COMPLETED, result)
    assert len(cb.finalized) == 1
    assert cb.finalized[0][0] == eid


@pytest.mark.asyncio
async def test_on_execution_failed_records_call():
    cb = FakeCallbacks()
    eid = uuid.uuid4()
    await cb.on_execution_failed(eid, "OOM killed")
    assert len(cb.failed) == 1
    assert cb.failed[0] == (eid, "OOM killed")


def test_none_satisfies_optional_pattern():
    """Runner accepts callbacks=None for standalone executions."""
    cb = None
    assert cb is None or isinstance(cb, RunnerCallbacks)
```

- [ ] **Step 3: 运行测试确认通过**

```bash
cd backend && python -m pytest tests/test_core/test_runner_callbacks.py -v
```

- [ ] **Step 4: 提交**

```bash
git add backend/app/core/agent/cli_backends/runner_callbacks.py backend/tests/test_core/test_runner_callbacks.py
git commit -m "feat: add RunnerCallbacks Protocol to break circular dependency"
```

---

### Task 1.2: 改造 ExecutionRunner 接受 callbacks 注入

**目的：** Runner 不再 deferred import MissionService / MissionCommentService，改为调用注入的 callbacks。`callbacks=None` 时（standalone execution）跳过回调。

**Files:**
- Modify: `backend/app/core/agent/cli_backends/execution_runner.py:43-54` (构造函数)
- Modify: `backend/app/core/agent/cli_backends/execution_runner.py:345-380` (`_finalize`)
- Modify: `backend/app/core/agent/cli_backends/execution_runner.py:382-411` (`_mark_failed`)
- Delete: `backend/app/core/agent/cli_backends/execution_runner.py:413-447` (`_update_mission_status`, `_post_completion_comment`)
- Modify: `backend/tests/test_core/test_execution_runner.py`

- [ ] **Step 1: 修改 ExecutionRunner 构造函数，添加 callbacks 参数**

```python
# execution_runner.py:43-54 修改为：
class ExecutionRunner:
    """Orchestrates the full lifecycle of a CLI agent execution."""

    def __init__(
        self,
        db: AsyncSession,
        container_service: Optional[CLIContainerService] = None,
        callbacks: Optional[RunnerCallbacks] = None,
    ):
        self.db = db
        self.execution_service = ExecutionService(db)
        self.agent_repo = AgentProfileRepository(db)
        self.container_service = container_service or CLIContainerService()
        self.callbacks = callbacks
        self._auto_approve: bool = True
        self._session: Optional[RuntimeSession] = None
```

新增 import（文件顶部）：
```python
from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
```

- [ ] **Step 2: 重写 `_finalize` 方法，用 callbacks 替代 deferred import**

```python
# execution_runner.py:345-380 替换为：
async def _finalize(
    self,
    execution_id: uuid.UUID,
    result: CLIResult,
    agent_profile: Optional[AgentProfile],
) -> None:
    if result.status == "completed":
        status = MissionExecutionStatus.COMPLETED
    else:
        status = MissionExecutionStatus.FAILED

    await self.execution_service.append_event(
        execution_id=execution_id,
        event_type="execution_completed" if status == MissionExecutionStatus.COMPLETED else "error",
        payload={
            "result_summary": {"output_length": len(result.output)},
            "message": result.error or "",
        },
    )

    await self.execution_service.mark_status(
        execution_id=execution_id,
        status=status,
        session_id=result.session_id,
        error_message=result.error if result.error else None,
        result_summary=result.usage,
    )

    if agent_profile:
        await self._update_agent_status(agent_profile, AgentStatus.IDLE)

    if self.callbacks:
        try:
            await self.callbacks.on_execution_finalized(execution_id, status, result)
        except Exception as exc:
            logger.warning(f"Callback on_execution_finalized failed for {execution_id}: {exc}")
```

- [ ] **Step 3: 重写 `_mark_failed` 方法**

```python
# execution_runner.py:382-411 替换为：
async def _mark_failed(
    self,
    execution_id: uuid.UUID,
    error: str,
    agent_profile: Optional[AgentProfile],
) -> None:
    try:
        await self.execution_service.append_event(
            execution_id=execution_id,
            event_type="error",
            payload={"message": error},
        )
        await self.execution_service.mark_status(
            execution_id=execution_id,
            status=MissionExecutionStatus.FAILED,
            error_message=error[:2000],
        )
    except Exception as exc:
        logger.error(f"Failed to mark execution {execution_id} as failed: {exc}")

    if agent_profile:
        await self._update_agent_status(agent_profile, AgentStatus.ERROR)

    if self.callbacks:
        try:
            await self.callbacks.on_execution_failed(execution_id, error)
        except Exception as exc:
            logger.warning(f"Callback on_execution_failed failed for {execution_id}: {exc}")
```

- [ ] **Step 4: 删除 `_update_mission_status` 和 `_post_completion_comment` 方法**

删除 `execution_runner.py:413-447` 的 `_update_mission_status` 和 `_post_completion_comment` 两个方法。这些逻辑将移到 `ExecutionLifecycleService` 中实现 callbacks。

- [ ] **Step 5: 确认现有测试仍通过**

```bash
cd backend && python -m pytest tests/test_core/test_execution_runner.py -v
```

现有测试只测 `_msg_to_event_type` 和 `_msg_to_payload`（静态方法），不受构造函数改动影响。

- [ ] **Step 6: 添加 callbacks 注入的单元测试**

在 `backend/tests/test_core/test_execution_runner.py` 末尾追加：

```python
def test_runner_accepts_none_callbacks():
    """Standalone executions pass callbacks=None."""
    from unittest.mock import MagicMock
    db = MagicMock()
    runner = ExecutionRunner(db, callbacks=None)
    assert runner.callbacks is None


def test_runner_accepts_callbacks():
    """Mission executions pass a callbacks implementation."""
    from unittest.mock import MagicMock
    db = MagicMock()

    class StubCallbacks:
        async def on_execution_finalized(self, execution_id, status, result): ...
        async def on_execution_failed(self, execution_id, error): ...

    runner = ExecutionRunner(db, callbacks=StubCallbacks())
    assert runner.callbacks is not None
```

- [ ] **Step 7: 运行全部 runner 测试**

```bash
cd backend && python -m pytest tests/test_core/test_execution_runner.py -v
```

- [ ] **Step 8: 提交**

```bash
git add backend/app/core/agent/cli_backends/execution_runner.py backend/tests/test_core/test_execution_runner.py
git commit -m "refactor: ExecutionRunner uses injected callbacks instead of deferred imports"
```

---

### Task 1.3: 创建 ExecutionLifecycleService 骨架

**目的：** 建立 Mediator 服务，实现 RunnerCallbacks Protocol。先搬迁 `finalize` 和 `cancel` 逻辑（当前分散在 3 处的取消逻辑统一到一处）。

**Files:**
- Create: `backend/app/services/execution_lifecycle_service.py`
- Test: `backend/tests/test_services/test_execution_lifecycle_service.py`

- [ ] **Step 1: 编写 ExecutionLifecycleService 核心结构和 RunnerCallbacks 实现**

```python
# backend/app/services/execution_lifecycle_service.py
"""
ExecutionLifecycleService — the sole cross-domain coordinator
between Mission and Execution.

All operations that touch BOTH domains go through this service.
MissionService and ExecutionService remain single-domain and
never import each other.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.cli_backends.base import CLIResult
from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.core.agent.cli_backends.session_registry import session_registry
from app.models.execution import (
    ExecutionSource,
    MissionExecutionStatus,
    TERMINAL_EXECUTION_STATUSES,
)
from app.models.mission import AssigneeType, Mission, MissionStatus
from app.repositories.agent_profile import AgentProfileRepository
from app.repositories.mission import MissionRepository
from app.services.execution_service import ExecutionService
from app.utils.credentials import build_credentials
from app.utils.datetime import utc_now


class ExecutionLifecycleService(RunnerCallbacks):
    """Mediator: coordinates Mission <-> Execution interactions.

    Implements RunnerCallbacks so it can be injected into ExecutionRunner.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.execution_service = ExecutionService(db)
        self.mission_repo = MissionRepository(db)
        self.agent_repo = AgentProfileRepository(db)

    # ------------------------------------------------------------------
    # RunnerCallbacks implementation
    # ------------------------------------------------------------------

    async def on_execution_finalized(
        self,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
        result: CLIResult,
    ) -> None:
        """Called by ExecutionRunner after terminal state reached."""
        await self._post_completion_comment(execution_id, status, result)
        await self._finalize_mission(execution_id, status)

    async def on_execution_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
    ) -> None:
        """Called by ExecutionRunner on unhandled exception."""
        await self._post_completion_comment(
            execution_id,
            MissionExecutionStatus.FAILED,
            error_message=error,
        )
        await self._finalize_mission(execution_id, MissionExecutionStatus.FAILED)

    # ------------------------------------------------------------------
    # Finalize: update mission status after execution ends
    # ------------------------------------------------------------------

    async def _finalize_mission(
        self,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
    ) -> None:
        """Update mission status and clear current_execution_id.

        Consolidates logic from:
        - mission_service.py:305-346 (finalize_mission_execution)
        - executions.py:191-201 (cancel cascade)
        """
        from sqlalchemy import select

        try:
            mission = (
                await self.db.execute(
                    select(Mission)
                    .where(Mission.current_execution_id == execution_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if not mission:
                return

            mission.current_execution_id = None

            if status == MissionExecutionStatus.COMPLETED:
                if mission.status != MissionStatus.CANCELLED:
                    mission.status = (
                        MissionStatus.DONE if mission.auto_approve
                        else MissionStatus.IN_REVIEW
                    )
            elif status == MissionExecutionStatus.FAILED:
                if mission.status == MissionStatus.IN_PROGRESS:
                    mission.status = MissionStatus.TODO
            elif status == MissionExecutionStatus.CANCELLED:
                if mission.status == MissionStatus.IN_PROGRESS:
                    mission.status = MissionStatus.TODO

            await self.db.commit()

            from app.websocket.notification_manager import (
                NotificationType,
                notification_manager,
            )
            await notification_manager.broadcast({
                "type": NotificationType.MISSION_UPDATED.value,
                "mission_id": str(mission.id),
                "status": mission.status.value,
            })

            logger.info(
                f"Finalized mission {mission.id}: execution {execution_id} "
                f"-> mission status {mission.status.value}"
            )
        except Exception as exc:
            logger.warning(
                f"Failed to finalize mission for execution {execution_id}: {exc}"
            )

    # ------------------------------------------------------------------
    # Cancel: unified cancel path
    # ------------------------------------------------------------------

    async def cancel_execution(
        self,
        execution_id: uuid.UUID,
        user_id: str,
    ) -> Any:
        """Unified cancel — replaces both executions.py cancel and mission_service cancel.

        1. Mark execution CANCELLED
        2. Kill container session + asyncio task
        3. Update parent mission if linked
        """
        execution = await self.execution_service.get_execution(
            execution_id, user_id
        )
        if not execution:
            return None

        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return execution

        execution = await self.execution_service.mark_status(
            execution_id=execution_id,
            user_id=user_id,
            status=MissionExecutionStatus.CANCELLED,
            error_code="cancelled",
            error_message="Cancelled by user",
        )

        # Kill running process
        session = session_registry.get(execution_id)
        if session:
            try:
                await session.cancel()
            except Exception as exc:
                logger.warning(f"Failed to cancel session {execution_id}: {exc}")

        # Cancel asyncio background task
        try:
            from app.utils.task_manager import task_manager
            await task_manager.cancel_task(str(execution_id))
        except Exception as exc:
            logger.warning(f"Failed to cancel task {execution_id}: {exc}")

        # Update parent mission
        if execution.mission_id:
            await self._finalize_mission(
                execution_id, MissionExecutionStatus.CANCELLED
            )

        return execution

    async def cancel_mission(
        self,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Optional[Mission]:
        """Cancel mission + its active execution. Single path.

        Replaces:
        - mission_service.py:348-384 (cancel_mission)
        - executions.py:165-208 (cancel_execution cascade)
        """
        mission = await self.mission_repo.get_for_update(mission_id, workspace_id)
        if not mission:
            return None

        if mission.current_execution_id:
            exec_id = mission.current_execution_id
            # Mark execution cancelled
            try:
                await self.execution_service.mark_status(
                    execution_id=exec_id,
                    status=MissionExecutionStatus.CANCELLED,
                    error_code="cancelled",
                    error_message="Mission cancelled by user",
                )
            except Exception as exc:
                logger.warning(f"Failed to mark execution {exec_id} cancelled: {exc}")

            # Kill process
            session = session_registry.get(exec_id)
            if session:
                try:
                    await session.cancel()
                except Exception as exc:
                    logger.warning(f"Failed to cancel session {exec_id}: {exc}")

            # Cancel asyncio task
            try:
                from app.utils.task_manager import task_manager
                await task_manager.cancel_task(str(exec_id))
            except Exception as exc:
                logger.warning(f"Failed to cancel task {exec_id}: {exc}")

        mission.status = MissionStatus.CANCELLED
        mission.current_execution_id = None
        await self.db.commit()
        await self.db.refresh(mission)

        # Broadcast mission status change (matches _finalize_mission pattern)
        from app.websocket.notification_manager import (
            NotificationType,
            notification_manager,
        )
        await notification_manager.broadcast({
            "type": NotificationType.MISSION_UPDATED.value,
            "mission_id": str(mission.id),
            "status": mission.status.value,
        })

        return mission

    # ------------------------------------------------------------------
    # Auto-comment on execution completion
    # ------------------------------------------------------------------

    async def _post_completion_comment(
        self,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
        result: Optional[CLIResult] = None,
        error_message: str = "",
    ) -> None:
        try:
            execution = await self.execution_service.get_execution_internal(
                execution_id
            )
            if not execution or not execution.mission_id:
                return
            from app.services.mission_comment_service import MissionCommentService
            svc = MissionCommentService(self.db)
            await svc.post_execution_comment(
                execution=execution,
                result_status=status,
                result_output=(
                    result.output[:2000] if result and result.output else ""
                ),
                error_message=error_message[:2000] if error_message else "",
            )
        except Exception as exc:
            logger.warning(
                f"Failed to post completion comment for {execution_id}: {exc}"
            )
```

- [ ] **Step 2: 在 ExecutionService 中添加 `get_execution_internal` 方法**

当前 `get_execution` 需要 `user_id`（鉴权用），但 lifecycle service 是内部调用，不应要求 user_id。

在 `backend/app/services/execution_service.py` 中添加：

```python
async def get_execution_internal(self, execution_id: uuid.UUID) -> Optional[Execution]:
    """Internal use — no user-scope check, no FOR UPDATE lock."""
    from sqlalchemy import select
    from app.models.execution import Execution as ExecModel
    result = await self.db.execute(
        select(ExecModel).where(ExecModel.id == execution_id)
    )
    return result.scalar_one_or_none()
```

> ⚠️ 不能用 `repo.get_for_update()`——会获取写锁，在 `_finalize` 已持锁的事务中可能死锁。

- [ ] **Step 3: 编写 ExecutionLifecycleService 单元测试**

```python
# backend/tests/test_services/test_execution_lifecycle_service.py
from __future__ import annotations

import uuid

import pytest

from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.services.execution_lifecycle_service import ExecutionLifecycleService


def test_lifecycle_service_satisfies_runner_callbacks_protocol():
    """ExecutionLifecycleService must implement RunnerCallbacks."""
    from unittest.mock import MagicMock
    db = MagicMock()
    svc = ExecutionLifecycleService(db)
    assert isinstance(svc, RunnerCallbacks)
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && python -m pytest tests/test_services/test_execution_lifecycle_service.py tests/test_core/test_runner_callbacks.py -v
```

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/execution_lifecycle_service.py backend/app/services/execution_service.py backend/tests/test_services/test_execution_lifecycle_service.py
git commit -m "feat: add ExecutionLifecycleService as cross-domain mediator"
```

---

### Task 1.4: 接入 — 让 `_start_execution_runner` 传入 callbacks

**目的：** 将 Mediator 接入现有启动路径，使 ExecutionRunner 实际使用 callbacks。这是 Phase 1 的最后一步，完成后新路径生效。

**Files:**
- Modify: `backend/app/services/mission_service.py:26-55` (`_start_execution_runner`)

- [ ] **Step 1: 修改 `_start_execution_runner` 创建 lifecycle service 并传入 runner**

```python
# backend/app/services/mission_service.py:26-55 替换为：
def _start_execution_runner(
    execution_id: uuid.UUID,
    prompt: str,
    credentials: dict[str, str] | None,
) -> None:
    """Fire-and-forget: launch an ExecutionRunner in a background task."""
    from app.core.agent.cli_backends.execution_runner import ExecutionRunner
    from app.core.database import AsyncSessionLocal
    from app.services.execution_lifecycle_service import ExecutionLifecycleService
    from app.utils.task_manager import task_manager

    async def _run() -> None:
        current_task = asyncio.current_task()
        if current_task:
            await task_manager.register_task(str(execution_id), current_task)
        try:
            async with AsyncSessionLocal() as db:
                lifecycle = ExecutionLifecycleService(db)
                runner = ExecutionRunner(db, callbacks=lifecycle)
                await runner.run(
                    execution_id=execution_id,
                    prompt=prompt,
                    credentials=credentials,
                )
        except Exception as exc:
            logger.error(f"Background runner failed for {execution_id}: {exc}")
        finally:
            await task_manager.unregister_task(str(execution_id))

    safe_create_task(_run(), name=f"exec-{execution_id}")
```

- [ ] **Step 2: 运行现有 mission service 测试确认不破坏**

```bash
cd backend && python -m pytest tests/test_core/test_mission_service.py -v
```

- [ ] **Step 3: 运行全部相关测试**

```bash
cd backend && python -m pytest tests/test_core/ tests/test_services/ -v
```

- [ ] **Step 4: 提交**

```bash
git add backend/app/services/mission_service.py
git commit -m "feat: wire ExecutionLifecycleService into runner startup path"
```

---

### Phase 1 完成状态

此时系统状态：
- ✅ `ExecutionRunner` 不再 import `MissionService` 或 `MissionCommentService`
- ✅ 循环依赖链 `ExecutionRunner → MissionService` 已断开
- ✅ `ExecutionLifecycleService` 实现了统一的 finalize 和 cancel 逻辑
- ⚠️ 旧路径仍存在（`MissionService.cancel_mission`, `MissionService.finalize_mission_execution`, `executions.py` cancel cascade）
- ⚠️ 新旧路径并存，Phase 2 将删除旧路径并切换调用方

---

## Phase 2: 搬迁 dispatch 逻辑 + MissionService / CommentService 瘦身 + API 切换

**目标：** 将 dispatch / cancel / finalize / 评论触发执行 的逻辑全部搬到 `ExecutionLifecycleService`，删除 `MissionService` 和 `MissionCommentService` 中的跨域方法。API 层和 Scheduler 切换到新 service。此阶段结束后，旧路径完全删除。

**文件总览：**

| 操作 | 文件路径 |
|------|----------|
| 修改 | `backend/app/services/execution_lifecycle_service.py` — 新增 dispatch + 评论触发逻辑 |
| 修改 | `backend/app/services/mission_service.py` — 删除跨域方法，保留纯 CRUD |
| 修改 | `backend/app/services/mission_comment_service.py` — 删除执行触发逻辑 |
| 修改 | `backend/app/api/v1/missions.py` — dispatch/cancel 切换到 lifecycle service |
| 修改 | `backend/app/api/v1/executions.py` — cancel 端点切换到 lifecycle service |
| 修改 | `backend/app/core/scheduler.py` — 切换到 lifecycle service |
| 新增 | `backend/app/api/v1/mission_execution.py` — mission 下的执行操作端点 |
| 修改 | `backend/tests/test_core/test_mission_service.py` — 适配新接口 |

---

### Task 2.1: 搬迁 dispatch 逻辑到 ExecutionLifecycleService

**目的：** 将 `MissionService.dispatch_mission`（mission_service.py:221-303）搬到 lifecycle service，包括 prompt 构建、execution 创建、runner 启动。

**Files:**
- Modify: `backend/app/services/execution_lifecycle_service.py`
- Move from: `backend/app/services/mission_service.py:56-75` (`build_execution_prompt`)
- Move from: `backend/app/services/mission_service.py:26-55` (`_start_execution_runner`)
- Move from: `backend/app/services/mission_service.py:221-303` (`dispatch_mission`)

- [ ] **Step 1: 将 `build_execution_prompt` 和 `_start_execution_runner` 移到 lifecycle service 模块**

将 `mission_service.py:26-75` 的两个函数移动到 `execution_lifecycle_service.py` 中作为模块级函数。在 `_start_execution_runner` 中保留 Phase 1 的 callbacks 接入逻辑。

- [ ] **Step 2: 在 ExecutionLifecycleService 中新增 dispatch 方法**

```python
async def dispatch_mission(
    self,
    *,
    mission_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: str,
    runtime_config: Optional[dict[str, Any]] = None,
) -> tuple[Mission, Any]:
    """唯一的派发路径。
    
    搬迁自 MissionService.dispatch_mission (mission_service.py:221-303)
    """
    mission = await self.mission_repo.get_for_update(mission_id, workspace_id)
    if not mission:
        raise ValueError(f"Mission not found: {mission_id}")

    if mission.status not in {
        MissionStatus.TODO, MissionStatus.BACKLOG,
        MissionStatus.IN_PROGRESS, MissionStatus.IN_REVIEW,
    }:
        raise ValueError(
            f"Mission {mission_id} cannot be dispatched from status {mission.status.value}"
        )

    # Active execution guard
    if mission.status == MissionStatus.IN_PROGRESS and mission.current_execution_id:
        from sqlalchemy import select
        from app.models.execution import Execution as ExecModel
        current_exec = (
            await self.db.execute(
                select(ExecModel).where(ExecModel.id == mission.current_execution_id)
            )
        ).scalar_one_or_none()
        if current_exec and current_exec.status not in TERMINAL_EXECUTION_STATUSES:
            raise ValueError(f"Mission {mission_id} already has an active execution")
        mission.current_execution_id = None

    if not mission.assignee_id or mission.assignee_type != AssigneeType.AGENT:
        raise ValueError(f"Mission {mission_id} has no agent assignee")

    agent = await self.agent_repo.get_by_id_and_workspace(
        mission.assignee_id, workspace_id
    )
    if not agent:
        raise ValueError(f"Agent profile not found: {mission.assignee_id}")

    credentials = build_credentials(agent.custom_env)
    prompt = build_execution_prompt(mission)

    execution = await self.execution_service.create_execution(
        workspace_id=workspace_id,
        user_id=user_id,
        source=ExecutionSource.MISSION,
        source_id=str(mission_id),
        runtime_type=agent.runtime_type,
        title=mission.title,
        mission_id=mission_id,
        agent_profile_id=mission.assignee_id,
        runtime_config=runtime_config or agent.runtime_config,
    )

    mission.status = MissionStatus.IN_PROGRESS
    mission.current_execution_id = execution.id
    await self.db.commit()
    await self.db.refresh(mission)

    _start_execution_runner(execution.id, prompt, credentials)
    return mission, execution
```

- [ ] **Step 3: 新增 dispatch_all_ready_missions 和 dispatch_for_comment / dispatch_for_mention**

```python
async def dispatch_all_ready_missions(self, *, limit: int = 20) -> int:
    """调度器调用 — 搬迁自 MissionService.dispatch_all_ready_missions"""
    dispatchable = await self.mission_repo.list_dispatchable(limit=limit)
    dispatched = 0
    for mission in dispatchable:
        try:
            await self.dispatch_mission(
                mission_id=mission.id,
                workspace_id=mission.workspace_id,
                user_id=mission.creator_id,
            )
            dispatched += 1
        except Exception as exc:
            logger.warning(f"Failed to auto-dispatch mission {mission.id}: {exc}")
    return dispatched

async def dispatch_for_comment(
    self,
    *,
    mission: Mission,
    trigger_comment: Any,
    user_id: str,
) -> Optional[uuid.UUID]:
    """评论触发的 assignee 派发。
    
    搬迁自 MissionCommentService._enqueue_comment_execution
    """
    agent = await self.agent_repo.get_by_id_and_workspace(
        mission.assignee_id, mission.workspace_id
    )
    if not agent:
        logger.warning(f"Agent {mission.assignee_id} not found, skipping enqueue")
        return None

    execution_id = await self._create_comment_execution(
        mission=mission, agent=agent, trigger_comment=trigger_comment, user_id=user_id,
    )
    if not execution_id:
        return None

    mission_for_update = await self.mission_repo.get_for_update(
        mission.id, mission.workspace_id
    )
    if mission_for_update:
        mission_for_update.current_execution_id = execution_id
        if mission_for_update.status != MissionStatus.IN_PROGRESS:
            mission_for_update.status = MissionStatus.IN_PROGRESS
        await self.db.commit()

    return execution_id

async def dispatch_for_mention(
    self,
    *,
    mission: Mission,
    trigger_comment: Any,
    user_id: str,
) -> None:
    """@mention 触发的非 assignee agent 派发。
    
    搬迁自 MissionCommentService._enqueue_mentioned_agent_executions
    """
    from app.utils.mentions import agent_mentions

    mentions = agent_mentions(trigger_comment.content)
    if not mentions:
        return
    if mission.status in {MissionStatus.DONE, MissionStatus.CANCELLED, MissionStatus.BACKLOG}:
        return

    seen: set[uuid.UUID] = set()
    for mention in mentions:
        if mention.id == mission.assignee_id or mention.id in seen:
            continue
        seen.add(mention.id)
        agent = await self.agent_repo.get_by_id_and_workspace(
            mention.id, mission.workspace_id
        )
        if not agent:
            continue
        await self._create_comment_execution(
            mission=mission, agent=agent, trigger_comment=trigger_comment, user_id=user_id,
        )

async def _create_comment_execution(
    self,
    *,
    mission: Mission,
    agent: Any,
    trigger_comment: Any,
    user_id: str,
) -> Optional[uuid.UUID]:
    """共享 helper — 创建评论触发的 execution 并启动 runner。"""
    from sqlalchemy.exc import IntegrityError

    credentials = build_credentials(agent.custom_env)
    try:
        execution = await self.execution_service.create_execution(
            workspace_id=mission.workspace_id,
            user_id=user_id,
            source=ExecutionSource.MISSION,
            source_id=str(mission.id),
            runtime_type=agent.runtime_type,
            title=mission.title,
            mission_id=mission.id,
            agent_profile_id=agent.id,
            runtime_config=agent.runtime_config,
            trigger_comment_id=trigger_comment.id,
        )
    except IntegrityError:
        await self.db.rollback()
        logger.info(f"Dedup: skipped enqueue for agent {agent.id} on mission {mission.id}")
        return None

    prompt = build_execution_prompt(mission, trigger_comment=trigger_comment)
    _start_execution_runner(execution.id, prompt, credentials)
    return execution.id
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && python -m pytest tests/test_services/test_execution_lifecycle_service.py tests/test_core/ -v
```

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/execution_lifecycle_service.py
git commit -m "feat: add dispatch/comment-dispatch to ExecutionLifecycleService"
```

---

### Task 2.2: API 层 + Scheduler 切换到 ExecutionLifecycleService

**目的：** API 端点和 Scheduler 率先切换到 lifecycle service，**之后**再删除 MissionService 中的旧方法。顺序很重要——先切调用方，再删被调用方，保证中间状态可运行。

**Files:**
- Modify: `backend/app/api/v1/missions.py` — dispatch/cancel 切换到 lifecycle service
- Modify: `backend/app/api/v1/executions.py:165-208` — cancel 端点切换
- Modify: `backend/app/api/v1/mission_comments.py:64-72` — 适配 4-tuple 返回值 + 触发执行
- Modify: `backend/app/core/scheduler.py` — 切换到 lifecycle service

- [ ] **Step 1: missions.py — dispatch 端点切换**

```python
# missions.py:157-172 替换为：
@router.post("/{mission_id}/dispatch", response_model=BaseResponse[MissionSummary])
async def dispatch_mission(
    mission_id: uuid.UUID,
    request: DispatchMissionRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionSummary]:
    from app.services.execution_lifecycle_service import ExecutionLifecycleService
    lifecycle = ExecutionLifecycleService(db)
    mission, _execution = await lifecycle.dispatch_mission(
        mission_id=mission_id,
        workspace_id=workspace_id,
        user_id=str(current_user.id),
        runtime_config=request.runtime_config,
    )
    return BaseResponse(success=True, code=200, msg="Mission dispatched", data=_to_summary(mission))
```

- [ ] **Step 2: missions.py — cancel 端点切换**

```python
# missions.py:175-186 替换为：
@router.post("/{mission_id}/cancel", response_model=BaseResponse[MissionSummary])
async def cancel_mission(
    mission_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionSummary]:
    from app.services.execution_lifecycle_service import ExecutionLifecycleService
    lifecycle = ExecutionLifecycleService(db)
    mission = await lifecycle.cancel_mission(mission_id=mission_id, workspace_id=workspace_id)
    if not mission:
        return BaseResponse(success=False, code=404, msg="Mission not found", data=None)
    return BaseResponse(success=True, code=200, msg="Mission cancelled", data=_to_summary(mission))
```

- [ ] **Step 3: executions.py — cancel 端点切换（删除内联 mission 逻辑）**

```python
# executions.py:165-208 替换为：
@router.post("/{execution_id}/cancel", response_model=BaseResponse[ExecutionSummary])
async def cancel_execution(
    execution_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionSummary]:
    from app.services.execution_lifecycle_service import ExecutionLifecycleService
    lifecycle = ExecutionLifecycleService(db)
    execution = await lifecycle.cancel_execution(execution_id, str(current_user.id))
    if not execution:
        return BaseResponse(success=False, code=404, msg="Execution not found", data=None)
    if execution.status in TERMINAL_EXECUTION_STATUSES and execution.error_code != "cancelled":
        return BaseResponse(
            success=False, code=409,
            msg=f"Execution already in terminal state: {execution.status.value}",
            data=_to_summary(execution),
        )
    return BaseResponse(success=True, code=200, msg="Execution cancelled", data=_to_summary(execution))
```

- [ ] **Step 4: mission_comments.py — 适配 4-tuple 返回值 + 触发执行**

> ⚠️ **Critical fix:** Task 2.3 将 `create_comment` 返回值从 2-tuple 改为 4-tuple。此处必须同步更新，否则每次创建评论都会崩溃。

```python
# backend/app/api/v1/mission_comments.py:64-72 替换为：
    comment, mission, should_dispatch, mentioned_agent_ids = await service.create_comment(
        mission_id=mission_id,
        workspace_id=workspace_id,
        author_type=CommentAuthorType.MEMBER,
        author_id=str(current_user.id),
        content=request.content,
        comment_type=CommentType.COMMENT,
        parent_comment_id=request.parent_comment_id,
    )

    # Trigger executions via lifecycle service
    if should_dispatch or mentioned_agent_ids:
        from app.services.execution_lifecycle_service import ExecutionLifecycleService
        lifecycle = ExecutionLifecycleService(db)
        if should_dispatch:
            await lifecycle.dispatch_for_comment(
                mission=mission, trigger_comment=comment, user_id=str(current_user.id),
            )
        if mentioned_agent_ids:
            await lifecycle.dispatch_for_mention(
                mission=mission, trigger_comment=comment, user_id=str(current_user.id),
            )
```

- [ ] **Step 5: Scheduler 切换**

```python
# scheduler.py — mission_dispatcher_loop 中：
# 将 MissionService(db).dispatch_all_ready_missions() 替换为：
from app.services.execution_lifecycle_service import ExecutionLifecycleService
lifecycle = ExecutionLifecycleService(db)
count = await lifecycle.dispatch_all_ready_missions()

# _reap_stale_executions 中：
# 将 mission_svc.finalize_mission_execution(...) 替换为：
await lifecycle._finalize_mission(execution.id, MissionExecutionStatus.FAILED)
```

删除 scheduler.py 中的 `from app.services.mission_service import MissionService` import。

- [ ] **Step 6: 运行测试确认切换不破坏**

```bash
cd backend && python -m pytest tests/ -v -x
```

- [ ] **Step 7: 提交**

```bash
git add backend/app/api/v1/missions.py backend/app/api/v1/executions.py backend/app/api/v1/mission_comments.py backend/app/core/scheduler.py
git commit -m "refactor: API + scheduler switch to ExecutionLifecycleService"
```

---

### Task 2.3: 瘦身 MissionCommentService — 删除执行触发逻辑

**目的：** CommentService 不再直接触发执行。改为 `create_comment` 返回触发信号，由 API 层调用 lifecycle service 完成触发（已在 Task 2.2 Step 4 接入）。

**Files:**
- Modify: `backend/app/services/mission_comment_service.py`

- [ ] **Step 1: 改造 `create_comment` 返回值**

```python
# 之前 (line 40-89)：create_comment 内部直接调用 _enqueue_comment_execution
# 之后：返回触发信号，不直接执行

async def create_comment(
    self, *, mission_id, workspace_id, author_type, author_id,
    content, comment_type=CommentType.COMMENT, parent_comment_id=None,
) -> tuple[MissionComment, Mission, bool, list[uuid.UUID]]:
    """Returns (comment, mission, should_dispatch_assignee, mentioned_agent_ids)."""
    mission = await self.mission_repo.get_by_id_and_workspace(mission_id, workspace_id)
    if not mission:
        raise ValueError(f"Mission not found: {mission_id}")

    if parent_comment_id is not None:
        parent = await self.repo.get(parent_comment_id)
        if parent and parent.parent_comment_id is not None:
            parent_comment_id = parent.parent_comment_id

    comment = MissionComment(
        mission_id=mission_id, workspace_id=workspace_id,
        author_type=author_type, author_id=author_id,
        content=content, type=comment_type, parent_comment_id=parent_comment_id,
    )
    self.db.add(comment)
    await self.db.commit()
    await self.db.refresh(comment)

    # Compute trigger signals — but don't execute them
    should_dispatch = False
    mentioned_agent_ids: list[uuid.UUID] = []

    if author_type == CommentAuthorType.MEMBER and comment_type == CommentType.COMMENT:
        should_dispatch = self._should_enqueue_on_comment(mission)

        from app.utils.mentions import agent_mentions
        mentions = agent_mentions(content)
        seen: set[uuid.UUID] = set()
        for m in mentions:
            if m.id != mission.assignee_id and m.id not in seen:
                seen.add(m.id)
                mentioned_agent_ids.append(m.id)

    return comment, mission, should_dispatch, mentioned_agent_ids
```

- [ ] **Step 2: 删除不再需要的方法**

```
删除：
  - _create_and_start_execution (line 189-225)
  - _enqueue_comment_execution (line 227-257)
  - _enqueue_mentioned_agent_executions (line 259-297)
```

- [ ] **Step 3: 清理 import**

```python
# 删除这些 import：
from sqlalchemy.exc import IntegrityError      # 不再需要
from app.services.execution_service import ExecutionService  # 不再需要
# 删除 __init__ 中的 self.execution_service = ExecutionService(db)
```

保留：
- `_should_enqueue_on_comment` — 纯判断，无副作用
- `post_execution_comment` — lifecycle service 会调用
- CRUD 方法

- [ ] **Step 4: 运行测试**

```bash
cd backend && python -m pytest tests/ -v -x
```

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/mission_comment_service.py
git commit -m "refactor: CommentService returns trigger signals instead of dispatching executions"
```

---

### Task 2.4: 瘦身 MissionService — 删除跨域方法

**目的：** 调用方已在 Task 2.2 全部切换到 lifecycle service。现在安全地删除 MissionService 中的跨域方法和 import。

**Files:**
- Modify: `backend/app/services/mission_service.py`
- Modify: `backend/tests/test_core/test_mission_service.py`
- Modify: `backend/tests/test_core/test_integration.py`

- [ ] **Step 1: 从 MissionService 中删除以下方法和函数**

```
删除模块级函数：
  - _start_execution_runner (line 26-55) → 已搬到 lifecycle service
  - build_execution_prompt (line 56-75) → 已搬到 lifecycle service

删除 MissionService 方法：
  - dispatch_mission (line 221-303) → 已搬到 lifecycle service
  - finalize_mission_execution (line 305-346) → 已搬到 lifecycle service
  - cancel_mission (line 348-384) → 已搬到 lifecycle service
  - dispatch_ready_missions (line 386-413) → 已搬到 lifecycle service
  - dispatch_all_ready_missions (line 415-429) → 已搬到 lifecycle service
```

> ⚠️ `dispatch_ready_missions`（workspace-scoped 版本）仅被 scheduler 调用，scheduler 已在 Task 2.2 切换到 `dispatch_all_ready_missions`，可安全删除。

- [ ] **Step 2: 清理 MissionService 的 import**

删除不再需要的 import：
```python
# 删除这些 import：
import asyncio
from app.models.execution import Execution as ExecModel, ExecutionSource, MissionExecutionStatus, TERMINAL_EXECUTION_STATUSES
from app.services.execution_service import ExecutionService
from app.utils.credentials import build_credentials
from app.utils.safe_task import safe_create_task
```

从 `__init__` 中删除 `self.execution_service = ExecutionService(db)`。

- [ ] **Step 3: 更新 `build_execution_prompt` 的所有 import 引用**

全局搜索 `from app.services.mission_service import build_execution_prompt`，替换为：
```python
from app.services.execution_lifecycle_service import build_execution_prompt
```

影响文件（**完整列表**）：
- `backend/tests/test_core/test_mission_service.py:7`
- `backend/tests/test_core/test_integration.py:45`

- [ ] **Step 4: 运行测试**

```bash
cd backend && python -m pytest tests/test_core/test_mission_service.py tests/test_core/test_integration.py -v
```

- [ ] **Step 7: 提交**

```bash
git add backend/app/services/mission_service.py backend/tests/test_core/test_mission_service.py
git commit -m "refactor: slim MissionService to pure CRUD — remove all execution logic"
```

---

### Task 2.5: 新增 Mission 下的执行操作端点

**目的：** 前端将通过 mission 端点操作执行（message/approve/events/snapshot），不再直接调用 execution 端点。

**Files:**
- Create: `backend/app/api/v1/mission_execution.py`
- Modify: `backend/app/api/v1/__init__.py` (注册路由到 ROUTERS 列表)

- [ ] **Step 1: 创建 mission_execution.py**

```python
# backend/app/api/v1/mission_execution.py
"""Mission-scoped execution endpoints — the frontend's primary interface."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_workspace_role
from app.common.exceptions import NotFoundException
from app.core.agent.cli_backends.session_registry import session_registry
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.execution import MissionExecutionStatus, TERMINAL_EXECUTION_STATUSES
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.execution import (
    ApproveActionRequest,
    ExecutionEventsPageResponse,
    ExecutionSnapshotResponse,
    ExecutionSummary,
    InjectMessageRequest,
)
from app.services.execution_service import ExecutionService
from app.services.mission_service import MissionService

router = APIRouter(prefix="/v1/missions/{mission_id}/execution", tags=["Mission Execution"])


async def _get_current_execution_id(
    mission_id: uuid.UUID, workspace_id: uuid.UUID, db: AsyncSession,
) -> uuid.UUID:
    svc = MissionService(db)
    mission = await svc.get_mission(mission_id, workspace_id)
    if not mission or not mission.current_execution_id:
        raise NotFoundException("No active execution for this mission")
    return mission.current_execution_id


@router.post("/message", response_model=BaseResponse)
async def inject_message(
    mission_id: uuid.UUID,
    request: InjectMessageRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    exec_id = await _get_current_execution_id(mission_id, workspace_id, db)
    session = session_registry.get(exec_id)
    if not session:
        raise NotFoundException("Execution session not found")

    svc = ExecutionService(db)
    await session.inject_message(request.message)
    await svc.append_event(
        execution_id=exec_id,
        event_type="user_message",
        payload={"content": request.message},
    )
    return BaseResponse(success=True, code=200, msg="Message injected")


@router.post("/approve", response_model=BaseResponse)
async def approve_action(
    mission_id: uuid.UUID,
    request: ApproveActionRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    exec_id = await _get_current_execution_id(mission_id, workspace_id, db)
    session = session_registry.get(exec_id)
    if not session:
        raise NotFoundException("Execution session not found")

    svc = ExecutionService(db)
    snapshot = await svc.repo.get_snapshot(exec_id)  # internal: bypass user_id check
    if not snapshot:
        raise NotFoundException("Execution snapshot not found")

    from app.core.agent.cli_backends.base import build_control_response
    pending = (snapshot.projection or {}).get("meta", {}).get("pending_approval", {})
    request_id = pending.get("request_id", "")

    if request.approved:
        await session.inject_message(build_control_response(request_id, "allow"))
        await svc.append_event(exec_id, "approval_resolved", {"decision": "approved"})
        await svc.mark_status(exec_id, status=MissionExecutionStatus.RUNNING)
    else:
        await session.inject_message(build_control_response(request_id, "deny"))
        await svc.append_event(exec_id, "approval_resolved", {"decision": "rejected"})

    return BaseResponse(success=True, code=200, msg="Action processed")


@router.get("/events", response_model=BaseResponse[ExecutionEventsPageResponse])
async def get_events(
    mission_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    after_seq: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    exec_id = await _get_current_execution_id(mission_id, workspace_id, db)
    svc = ExecutionService(db)
    events = await svc.list_events_after(exec_id, after_seq=after_seq, limit=limit)
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=ExecutionEventsPageResponse(
            execution_id=exec_id,
            events=events,
            next_after_seq=events[-1].seq if events else after_seq,
        ),
    )


@router.get("/snapshot", response_model=BaseResponse[ExecutionSnapshotResponse])
async def get_snapshot(
    mission_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    exec_id = await _get_current_execution_id(mission_id, workspace_id, db)
    svc = ExecutionService(db)
    snapshot = await svc.repo.get_snapshot(exec_id)  # internal: bypass user_id check
    if not snapshot:
        raise NotFoundException("Snapshot not found")
    return BaseResponse(success=True, code=200, msg="ok", data=snapshot)
```

- [ ] **Step 2: 注册路由**

在 `backend/app/api/v1/__init__.py` 中添加 import 和路由注册：

```python
# 在 import 区域添加：
from .mission_execution import router as mission_execution_router

# 在 ROUTERS 列表中添加（放在 mission_comments_router 之后）：
    mission_execution_router,
```

- [ ] **Step 3: 运行测试**

```bash
cd backend && python -m pytest tests/ -v -x
```

- [ ] **Step 4: 提交**

```bash
git add backend/app/api/v1/mission_execution.py backend/app/api/__init__.py
git commit -m "feat: add mission-scoped execution endpoints (message/approve/events/snapshot)"
```

---

### Phase 2 完成状态

此时系统状态：
- ✅ `MissionService` 只剩纯 CRUD + 状态机（约 150 行，原 429 行）
- ✅ `MissionCommentService` 不再 import ExecutionService，返回触发信号
- ✅ `ExecutionLifecycleService` 拥有所有跨域操作：dispatch / cancel / finalize / comment-dispatch / mention-dispatch
- ✅ API 层全部切换到 lifecycle service
- ✅ Scheduler 切换到 lifecycle service
- ✅ 新增 `/v1/missions/{id}/execution/*` 端点供前端使用
- ✅ 旧 `/v1/executions/*` 端点保留但不再包含 mission 内联逻辑
- ✅ 循环依赖链完全消除：无任何 service 互相 import

---

## Phase 3: 存量问题修复（FK 约束、冗余字段、错误处理、鉴权统一、并发控制）

**目标：** 修复 Phase 1-2 重构后仍然存在的遗留问题。包括数据库约束缺失、冗余字段清理、错误处理不一致、鉴权模型不统一、并发限制未执行、死代码清理、前后端状态机去重。此阶段全部是增量改进，不影响已重构的核心架构。

**文件总览：**

| 操作 | 文件路径 |
|------|----------|
| 新增 | `backend/alembic/versions/20260418_000002_f8f7f6f5f4f3_add_current_execution_fk.py` |
| 新增 | `backend/alembic/versions/20260418_000003_a9a8a7a6a5a4_drop_source_id_column.py` |
| 修改 | `backend/app/models/mission.py:73-75` — 添加 FK 约束 |
| 修改 | `backend/app/models/execution.py:18-27` — 标记 INTERRUPT_WAIT 为保留 |
| 修改 | `backend/app/models/execution.py:62` — 删除 source_id 字段 |
| 修改 | `backend/app/services/execution_service.py:48` — 删除 source_id 参数 |
| 修改 | `backend/app/services/execution_lifecycle_service.py` — 删除 source_id 传参 + 添加并发检查 + 使用具名异常 |
| 修改 | `backend/app/services/mission_service.py` — ValueError 替换为具名异常 |
| 修改 | `backend/app/services/mission_comment_service.py` — ValueError 替换为具名异常 |
| 修改 | `backend/app/api/v1/executions.py` — 鉴权切换到 require_workspace_role |
| 修改 | `backend/app/api/v1/missions.py` — 新增 transitions 端点 |
| 修改 | `frontend/types/missions.ts` — 从 API 获取 transitions（后续 Phase 4 处理） |

---

### Task 3.1: 为 `current_execution_id` 添加 FK 约束

**目的：** `missions.current_execution_id` 当前是裸 UUID 列（mission.py:73-75），没有 FK 指向 `executions.id`。这意味着删除 execution 后可能出现孤儿引用。添加 FK + SET NULL on delete。

**Files:**
- Modify: `backend/app/models/mission.py:73-75`
- Create: `backend/alembic/versions/20260418_000002_f8f7f6f5f4f3_add_current_execution_fk.py`

- [ ] **Step 1: 修改 Mission 模型添加 FK**

```python
# backend/app/models/mission.py:73-75 替换为：
current_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("executions.id", ondelete="SET NULL"),
    nullable=True,
)
```

同时在顶部 import 中确认 `ForeignKey` 已导入（当前 line 8 已有）。

- [ ] **Step 2: 创建 Alembic 迁移**

```python
# backend/alembic/versions/20260418_000002_f8f7f6f5f4f3_add_current_execution_fk.py
"""Add FK constraint on missions.current_execution_id -> executions.id"""

from alembic import op

revision = "f8f7f6f5f4f3"
down_revision = "e7e6e5e4e3e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # First, clean up any orphan references
    op.execute("""
        UPDATE missions
        SET current_execution_id = NULL
        WHERE current_execution_id IS NOT NULL
          AND current_execution_id NOT IN (SELECT id FROM executions)
    """)
    op.create_foreign_key(
        "fk_missions_current_execution_id",
        "missions",
        "executions",
        ["current_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_missions_current_execution_id", "missions", type_="foreignkey")
```

- [ ] **Step 3: 运行迁移测试**

```bash
cd backend && alembic upgrade head
```

- [ ] **Step 4: 提交**

```bash
git add backend/app/models/mission.py backend/alembic/versions/20260418_000002_f8f7f6f5f4f3_add_current_execution_fk.py
git commit -m "fix: add FK constraint on missions.current_execution_id"
```

---

### Task 3.2: 删除冗余 `source_id` 字段

**目的：** `Execution.source_id`（execution.py:62）存的是 `str(mission.id)`，与 `Execution.mission_id`（execution.py:71-75）完全重复。所有读取 `source_id` 的地方实际上都在用 `mission_id`。删除冗余字段。

**Files:**
- Modify: `backend/app/models/execution.py:62`
- Modify: `backend/app/services/execution_service.py:40,51`
- Modify: `backend/app/services/execution_lifecycle_service.py` — 所有 `source_id=str(mission_id)` 传参
- Create: `backend/alembic/versions/20260418_000003_a9a8a7a6a5a4_drop_source_id_column.py`

- [ ] **Step 1: 全局搜索 `source_id` 引用并确认可删除**

```bash
cd backend && grep -rn "source_id" app/ --include="*.py" | grep -v "__pycache__"
```

确认所有 `source_id` 的写入都是 `str(mission_id)` 或 `str(mission.id)`，所有读取都可用 `mission_id` 替代。

- [ ] **Step 2: 从 Execution 模型删除字段**

```python
# backend/app/models/execution.py:62 删除这一行：
source_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```

- [ ] **Step 3: 从 ExecutionService.create_execution 删除参数**

```python
# backend/app/services/execution_service.py:40 删除 source_id 参数：
#   source_id: Optional[str] = None,    ← 删除
# execution_service.py:51 删除赋值：
#   source_id=source_id,                ← 删除
```

- [ ] **Step 4: 从 ExecutionLifecycleService 的所有调用点删除 source_id 传参**

搜索 lifecycle service 中所有 `source_id=str(mission` 并删除。涉及：
- `dispatch_mission` 方法中的 `create_execution` 调用
- `_create_comment_execution` 方法中的 `create_execution` 调用

- [ ] **Step 5: 创建 Alembic 迁移**

```python
# backend/alembic/versions/20260418_000003_a9a8a7a6a5a4_drop_source_id_column.py
"""Drop redundant source_id column from executions table."""

from alembic import op

revision = "a9a8a7a6a5a4"
down_revision = "f8f7f6f5f4f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("executions", "source_id")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column("executions", sa.Column("source_id", sa.String(255), nullable=True))
```

- [ ] **Step 6: 运行测试**

```bash
cd backend && python -m pytest tests/ -v -x
```

- [ ] **Step 7: 提交**

```bash
git add backend/app/models/execution.py backend/app/services/execution_service.py backend/app/services/execution_lifecycle_service.py backend/alembic/versions/20260418_000003_a9a8a7a6a5a4_drop_source_id_column.py
git commit -m "refactor: drop redundant source_id column — mission_id already carries this info"
```

---

### Task 3.3: 统一错误处理 — ValueError 替换为具名异常

**目的：** 当前 service 层大量使用 `raise ValueError(...)`,依赖 `general_exception_handler`（exceptions.py:238-241）中的字符串匹配（`"not found" in msg.lower()` → 404）来确定 HTTP 状态码。这很脆弱——换个措辞就会从 404 变 400。改为直接 raise 对应的 `AppException` 子类。

**当前问题：**
```python
# mission_service.py — 这些全是 ValueError：
raise ValueError(f"Mission not found: {mission_id}")           # 应该是 NotFoundException
raise ValueError(f"Cannot transition from ... to ...")          # 应该是 BadRequestException
raise ValueError(f"Mission {id} already has an active execution") # 应该是 ConflictException
raise ValueError(f"Agent profile not found: {id}")              # 应该是 NotFoundException
```

**Files:**
- Modify: `backend/app/services/mission_service.py`
- Modify: `backend/app/services/mission_comment_service.py`
- Modify: `backend/app/services/execution_lifecycle_service.py`

- [ ] **Step 1: 替换 MissionService 中的 ValueError**

在 `mission_service.py` 顶部添加 import：
```python
from app.common.exceptions import BadRequestException, ConflictException, NotFoundException
```

逐一替换：
```python
# update_mission 方法中：
# ValueError("Invalid status: ...") → BadRequestException
raise BadRequestException(f"Invalid status: {new_status}")

# ValueError("Cannot transition from ... to ...") → BadRequestException
raise BadRequestException(
    f"Cannot transition from {mission.status.value} to {new_status.value}"
)

# ValueError("Cannot move to ... while an execution is active") → ConflictException
raise ConflictException(
    f"Cannot move to {new_status.value} while an execution is active — "
    f"cancel the execution first"
)

# assign_to_agent 方法中：
# ValueError("Mission not found: ...") → NotFoundException
raise NotFoundException(f"Mission not found: {mission_id}")

# ValueError("Agent profile not found: ...") → NotFoundException
raise NotFoundException(f"Agent profile not found: {agent_profile_id}")
```

- [ ] **Step 2: 替换 MissionCommentService 中的 ValueError**

在 `mission_comment_service.py` 顶部添加 import：
```python
from app.common.exceptions import NotFoundException
```

替换：
```python
# create_comment 方法中：
# ValueError("Mission not found: ...") → NotFoundException
raise NotFoundException(f"Mission not found: {mission_id}")

# list_comments 方法中同理
```

- [ ] **Step 3: 替换 ExecutionLifecycleService 中的 ValueError**

在 `execution_lifecycle_service.py` 顶部添加 import：
```python
from app.common.exceptions import BadRequestException, ConflictException, NotFoundException
```

替换 dispatch_mission 中：
```python
raise NotFoundException(f"Mission not found: {mission_id}")

raise BadRequestException(
    f"Mission {mission_id} cannot be dispatched from status {mission.status.value}"
)

raise ConflictException(f"Mission {mission_id} already has an active execution")

raise BadRequestException(f"Mission {mission_id} has no agent assignee")

raise NotFoundException(f"Agent profile not found: {mission.assignee_id}")
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && python -m pytest tests/ -v -x
```

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/mission_service.py backend/app/services/mission_comment_service.py backend/app/services/execution_lifecycle_service.py
git commit -m "fix: replace ValueError with typed exceptions (NotFoundException/BadRequestException/ConflictException)"
```

---

### Task 3.4: 统一鉴权模型 — Execution 端点使用 require_workspace_role

**目的：** Mission 端点使用 `require_workspace_role(WorkspaceMemberRole.member)`（missions.py:56, 79, 126 等），但 Execution 端点使用裸 `CurrentUser`（executions.py:86, 99, 168 等），只验证登录身份，不验证 workspace 访问权限。这意味着任何登录用户都能取消其他 workspace 的执行。

**当前对比：**
```python
# missions.py — 正确的模式：
current_user: User = require_workspace_role(WorkspaceMemberRole.member)

# executions.py — 有漏洞的模式：
current_user: CurrentUser  # 只验证登录，不验证 workspace 权限
```

**Files:**
- Modify: `backend/app/api/v1/executions.py`

- [ ] **Step 1: 为需要写操作的端点切换到 require_workspace_role**

修改 `cancel_execution`（line 165-170）、`inject_message`（line 211-216）、`approve_action`（line 239-245）：

```python
# cancel_execution — 需要 member 权限 + workspace_id 参数
@router.post("/{execution_id}/cancel", response_model=BaseResponse[ExecutionSummary])
async def cancel_execution(
    execution_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionSummary]:
    ...

# inject_message — 需要 member 权限
@router.post("/{execution_id}/message", response_model=BaseResponse)
async def inject_message(
    execution_id: uuid.UUID,
    request: InjectMessageRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    ...

# approve_action — 需要 member 权限
@router.post("/{execution_id}/approve", response_model=BaseResponse)
async def approve_action(
    execution_id: uuid.UUID,
    request: ApproveActionRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    ...
```

- [ ] **Step 2: 为只读端点切换到 require_workspace_role(viewer)**

修改 `get_execution`（line 82-87）、`list_child_executions`（line 95-100）、`get_execution_snapshot`（line 114-119）、`get_execution_events`（line 135-141）：

```python
# 所有只读端点改为：
current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
workspace_id: uuid.UUID = Query(...),
```

注意：`list_executions`（line 57-65）已经使用了 `require_workspace_role(WorkspaceMemberRole.viewer)`，不需要修改。

- [ ] **Step 3: 在端点实现中添加 workspace 归属校验**

在修改后的端点中，确认 execution 属于该 workspace：

```python
# get_execution 等端点中：
execution = await service.get_execution(execution_id, str(current_user.id))
if not execution:
    return BaseResponse(success=False, code=404, msg="Execution not found", data=None)
if execution.workspace_id != workspace_id:
    return BaseResponse(success=False, code=403, msg="Execution does not belong to this workspace", data=None)
```

- [ ] **Step 4: 清理未使用的 CurrentUser import**

如果 `executions.py` 中所有端点都已切换到 `require_workspace_role`，则从 import 中移除 `CurrentUser`。

- [ ] **Step 5: 运行测试**

```bash
cd backend && python -m pytest tests/ -v -x
```

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/v1/executions.py
git commit -m "security: execution endpoints now require workspace role, not just login"
```

---

### Task 3.5: 在 dispatch 路径中执行 max_concurrent_tasks 检查

**目的：** `AgentProfile.max_concurrent_tasks`（agent_profile.py:40）已持久化但从未在 dispatch 路径中检查。一个 agent 可以被无限并发派发，造成资源争用。

**Files:**
- Modify: `backend/app/services/execution_lifecycle_service.py`

- [ ] **Step 1: 在 dispatch_mission 方法中添加并发检查**

在 `ExecutionLifecycleService.dispatch_mission` 的 agent 验证后、execution 创建前，添加：

```python
# 在 "agent = await self.agent_repo..." 之后，"credentials = build_credentials..." 之前：
from sqlalchemy import select, func
from app.models.execution import Execution as ExecModel

active_count_result = await self.db.execute(
    select(func.count()).select_from(ExecModel).where(
        ExecModel.agent_profile_id == agent.id,
        ExecModel.status.in_([
            MissionExecutionStatus.QUEUED,
            MissionExecutionStatus.DISPATCHED,
            MissionExecutionStatus.RUNNING,
            MissionExecutionStatus.APPROVAL_WAIT,
        ]),
    )
)
active_count = active_count_result.scalar() or 0
if active_count >= agent.max_concurrent_tasks:
    raise ConflictException(
        f"Agent {agent.name} already has {active_count}/{agent.max_concurrent_tasks} "
        f"active executions"
    )
```

- [ ] **Step 2: 在 dispatch_for_comment 和 _create_comment_execution 中添加同样检查**

```python
# _create_comment_execution 方法中，credentials 行之前：
from sqlalchemy import select, func
from app.models.execution import Execution as ExecModel

active_count_result = await self.db.execute(
    select(func.count()).select_from(ExecModel).where(
        ExecModel.agent_profile_id == agent.id,
        ExecModel.status.in_([
            MissionExecutionStatus.QUEUED,
            MissionExecutionStatus.DISPATCHED,
            MissionExecutionStatus.RUNNING,
            MissionExecutionStatus.APPROVAL_WAIT,
        ]),
    )
)
active_count = active_count_result.scalar() or 0
if active_count >= agent.max_concurrent_tasks:
    logger.info(
        f"Agent {agent.name} at concurrency limit ({active_count}/{agent.max_concurrent_tasks}), "
        f"skipping comment-triggered dispatch for mission {mission.id}"
    )
    return None
```

注意区别：手动 dispatch 抛异常通知用户，评论触发的 dispatch 静默跳过（因为用户没有直接触发）。

- [ ] **Step 3: 运行测试**

```bash
cd backend && python -m pytest tests/ -v -x
```

- [ ] **Step 4: 提交**

```bash
git add backend/app/services/execution_lifecycle_service.py
git commit -m "feat: enforce max_concurrent_tasks limit on agent dispatch"
```

---

### Task 3.6: 标记 INTERRUPT_WAIT 为保留状态 + 清理死代码

**目的：** `MissionExecutionStatus.INTERRUPT_WAIT`（execution.py:22）从未在 execution 代码路径中使用——它只在 `AgentRun`（旧系统）中使用。但因为它已在 DB 的 enum 中，不能直接删除。标记为保留并确保不被误用。

**Files:**
- Modify: `backend/app/models/execution.py:22`

- [ ] **Step 1: 添加注释标记**

```python
# backend/app/models/execution.py:22
class MissionExecutionStatus(str, enum.Enum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    INTERRUPT_WAIT = "interrupt_wait"  # Reserved: not used in execution flow. From legacy AgentRun.
    APPROVAL_WAIT = "approval_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

- [ ] **Step 2: 确认 `INTERRUPT_WAIT` 未在 execution 代码中使用**

```bash
cd backend && grep -rn "INTERRUPT_WAIT" app/ --include="*.py" | grep -v "__pycache__" | grep -v "agent_run" | grep -v "run_service" | grep -v "runs.py" | grep -v "chat_ws"
```

应该只有 `execution.py` 的枚举定义本身。如果有其他引用，需要一并清理。

- [ ] **Step 3: 提交**

```bash
git add backend/app/models/execution.py
git commit -m "docs: mark INTERRUPT_WAIT as reserved legacy status in execution model"
```

---

### Task 3.7: 添加 MANUAL_TRANSITIONS API 端点

**目的：** `MANUAL_TRANSITIONS` 状态转换表在后端（mission_service.py:143-150）和前端（missions.ts:86-93）各维护一份。两份独立定义会不可避免地漂移。新增一个轻量 API 端点让前端从后端获取真实转换表。

**Files:**
- Modify: `backend/app/api/v1/missions.py`
- Modify: `backend/app/services/mission_service.py`

- [ ] **Step 1: 在 MissionService 中暴露 transitions 为静态数据**

```python
# backend/app/services/mission_service.py，在 MANUAL_TRANSITIONS 定义下方添加：
@classmethod
def get_transitions(cls) -> dict[str, list[str]]:
    """Return MANUAL_TRANSITIONS as JSON-serializable dict."""
    return {
        status.value: [t.value for t in targets]
        for status, targets in cls.MANUAL_TRANSITIONS.items()
    }
```

- [ ] **Step 2: 在 missions.py 中新增端点**

```python
# backend/app/api/v1/missions.py 末尾添加：
@router.get("/meta/transitions", response_model=BaseResponse)
async def get_transitions(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=MissionService.get_transitions(),
    )
```

**注意：** 这个端点需要放在 `/{mission_id}` 路由之前，否则 FastAPI 会将 `meta` 当作 `mission_id` 的 path parameter 匹配。确认路由顺序：

```python
# 路由顺序（从上到下）：
# GET  /v1/missions                          ← list
# POST /v1/missions                          ← create
# GET  /v1/missions/meta/transitions         ← ⚠️ 必须在 /{mission_id} 之前
# GET  /v1/missions/{mission_id}             ← get
# PATCH /v1/missions/{mission_id}            ← update
# ...
```

- [ ] **Step 3: 运行测试**

```bash
cd backend && python -m pytest tests/ -v -x
```

- [ ] **Step 4: 提交**

```bash
git add backend/app/api/v1/missions.py backend/app/services/mission_service.py
git commit -m "feat: add /missions/meta/transitions endpoint to eliminate frontend duplication"
```

---

### Phase 3 完成状态

此时系统状态：
- ✅ `missions.current_execution_id` 有 FK 约束 → `executions.id`，ON DELETE SET NULL
- ✅ 冗余字段 `source_id` 已删除，所有调用点清理完毕
- ✅ Service 层使用 `NotFoundException` / `BadRequestException` / `ConflictException`，不再依赖字符串匹配推断 HTTP 状态码
- ✅ Execution 端点统一使用 `require_workspace_role`，与 Mission 端点鉴权模型一致
- ✅ `max_concurrent_tasks` 在 dispatch 路径中强制执行
- ✅ `INTERRUPT_WAIT` 标记为保留状态，确认无误用
- ✅ `MANUAL_TRANSITIONS` 有 API 端点，前端可从后端获取真实转换表
- ⚠️ 前端仍硬编码本地 `MANUAL_TRANSITIONS`，Phase 4 将切换为 API 获取

---

## Phase 4: 前端重构（API 切换、缓存修正、删除 Execution 独立页面）

**目标：** 前端完成 Mission-first 转型。ExecutionTimeline 在 Mission 上下文中改用 mission-scoped 端点；缓存失效补全；MANUAL_TRANSITIONS 从 API 获取；删除孤立的 `/executions/[executionId]` 页面；mission board 支持 URL 深链。

**文件总览：**

| 操作 | 文件路径 |
|------|----------|
| 修改 | `frontend/services/missionService.ts` — 新增 mission-scoped execution 方法 |
| 修改 | `frontend/hooks/queries/executions.ts` — 修正 mutation 缓存失效 |
| 修改 | `frontend/hooks/queries/missions.ts` — 新增 transitions query + 补全缓存失效 |
| 修改 | `frontend/types/executions.ts` — 删除 `source_id`、`interrupt_wait` |
| 修改 | `frontend/types/missions.ts` — MANUAL_TRANSITIONS 改为 API 获取 |
| 修改 | `frontend/components/executions/execution-timeline.tsx` — 支持 mission context 透传 |
| 修改 | `frontend/components/missions/mission-detail-panel.tsx` — 传 missionId 给 timeline |
| 修改 | `frontend/components/missions/mission-board.tsx` — transitions 从 API 获取 |
| 修改 | `frontend/app/missions/page.tsx` — URL 深链 selectedMissionId |
| 删除 | `frontend/app/executions/[executionId]/page.tsx` |

---

### Task 4.1: 在 missionService 中新增 mission-scoped execution 方法

**目的：** Phase 2 后端已新增 `/v1/missions/{id}/execution/*` 端点。前端需要对应的 service 方法，以便 ExecutionTimeline 在 mission 上下文中直接调用 mission 端点，不再走 `/v1/executions/*`。

**Files:**
- Modify: `frontend/services/missionService.ts`

- [ ] **Step 1: 添加 mission-scoped execution 方法**

```typescript
// frontend/services/missionService.ts 末尾，在 missionService 对象中追加：

  // --- Mission-scoped execution operations ---

  getExecutionEvents: async (
    missionId: string, workspaceId: string, afterSeq?: number,
  ): Promise<ExecutionEventsPage> => {
    const params = new URLSearchParams({ workspace_id: workspaceId })
    if (afterSeq !== undefined) params.set('after_seq', String(afterSeq))
    return apiGet<ExecutionEventsPage>(
      `missions/${missionId}/execution/events?${params}`,
    )
  },

  getExecutionSnapshot: async (
    missionId: string, workspaceId: string,
  ): Promise<ExecutionSnapshot> => {
    return apiGet<ExecutionSnapshot>(
      `missions/${missionId}/execution/snapshot?workspace_id=${workspaceId}`,
    )
  },

  injectExecutionMessage: async (
    missionId: string, workspaceId: string, message: string,
  ): Promise<void> => {
    await apiPost(
      `missions/${missionId}/execution/message?workspace_id=${workspaceId}`,
      { message },
    )
  },

  approveExecutionAction: async (
    missionId: string, workspaceId: string, approved: boolean,
  ): Promise<void> => {
    await apiPost(
      `missions/${missionId}/execution/approve?workspace_id=${workspaceId}`,
      { approved },
    )
  },
```

同时在文件顶部添加 import：
```typescript
import type { ExecutionSnapshot } from '@/types/executions'
import type { ExecutionEventsPage } from '@/services/executionService'
```

- [ ] **Step 2: 运行类型检查**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: 提交**

```bash
git add frontend/services/missionService.ts
git commit -m "feat(frontend): add mission-scoped execution service methods"
```

---

### Task 4.2: ExecutionTimeline 支持 mission context 透传

**目的：** `ExecutionTimeline` 当前只接受 `executionId` 并直接调用 `executionService`。当在 `MissionDetailPanel` 中渲染时，应改用 mission-scoped 端点（自动解析 current_execution_id）。通过新增可选 `missionId` prop 实现。

**Files:**
- Modify: `frontend/components/executions/execution-timeline.tsx`

- [ ] **Step 1: 扩展 props 接受 missionId**

```typescript
// execution-timeline.tsx props 改为：
interface ExecutionTimelineProps {
  executionId: string
  workspaceId: string
  compact?: boolean
  isLive?: boolean
  missionId?: string  // 新增：当有值时使用 mission-scoped 端点
}
```

- [ ] **Step 2: injectMessage 和 approveAction 根据 missionId 切换调用**

```typescript
// 在组件内部：
const handleSendMessage = async (message: string) => {
  if (missionId) {
    await missionService.injectExecutionMessage(missionId, workspaceId, message)
  } else {
    await executionService.injectMessage(executionId, message)
  }
  // ... 追加 user_message event 到本地列表（现有逻辑）
}

const handleApprove = async (approved: boolean) => {
  if (missionId) {
    await missionService.approveExecutionAction(missionId, workspaceId, approved)
  } else {
    await executionService.approveAction(executionId, approved)
  }
}
```

注意：events 和 snapshot 的 REST 轮询仍走 `executionService`（因为 executionId 已知，且 events 需要 after_seq 参数，直接用 executionId 更高效）。mission-scoped 主要用于写操作（message/approve），因为这些是 Phase 4 后唯一可能在没有 executionId 的情况下调用的场景。

- [ ] **Step 3: 运行类型检查**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: 提交**

```bash
git add frontend/components/executions/execution-timeline.tsx
git commit -m "feat(frontend): ExecutionTimeline supports mission-scoped operations via missionId prop"
```

---

### Task 4.3: MissionDetailPanel 传递 missionId 给 ExecutionTimeline

**目的：** `MissionDetailPanel` 中嵌入的 `<ExecutionTimeline>` 需要传 `missionId`，使 message/approve 操作走 mission-scoped 端点。

**Files:**
- Modify: `frontend/components/missions/mission-detail-panel.tsx`

- [ ] **Step 1: 找到 ExecutionTimeline 的渲染位置并添加 missionId**

当前代码中有两处渲染 ExecutionTimeline：

```typescript
// 1. Current Execution（活跃执行）：
<ExecutionTimeline
  executionId={mission.current_execution_id}
  workspaceId={workspaceId}
  compact
  missionId={missionId}  // ← 新增
/>

// 2. Past Executions（历史执行 — PastExecutionRow）：
<ExecutionTimeline
  executionId={exec.id}
  workspaceId={workspaceId}
  compact
  isLive={false}
  // 不传 missionId — 历史执行不需要 message/approve
/>
```

- [ ] **Step 2: 运行类型检查**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: 提交**

```bash
git add frontend/components/missions/mission-detail-panel.tsx
git commit -m "feat(frontend): pass missionId to active ExecutionTimeline in detail panel"
```

---

### Task 4.4: 修正缓存失效 — dispatch/cancel 同时失效 execution 缓存

**目的：** 当前 `useDispatchMission` 和 `useCancelMission` 只失效 `missionKeys.all`，但 dispatch 会创建新 execution、cancel 会改变 execution 状态，而 `executionKeys` 缓存不会更新。导致 ExecutionTimeline 显示过时数据直到下次轮询。

**当前问题（hooks/queries/missions.ts:139-163）：**
```typescript
// dispatch 和 cancel 只失效 missions，不失效 executions
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: missionKeys.all })
  // 缺少: queryClient.invalidateQueries({ queryKey: executionKeys.all })
}
```

**Files:**
- Modify: `frontend/hooks/queries/missions.ts`

- [ ] **Step 1: 在 missions.ts 中添加 executionKeys import**

```typescript
// frontend/hooks/queries/missions.ts 顶部添加：
import { executionKeys } from './executions'
```

- [ ] **Step 2: dispatch mutation 补充 execution 缓存失效**

```typescript
// useDispatchMission 的 onSuccess：
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: missionKeys.all })
  queryClient.invalidateQueries({ queryKey: executionKeys.all })
},
```

- [ ] **Step 3: cancel mutation 补充 execution 缓存失效**

```typescript
// useCancelMission 的 onSuccess：
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: missionKeys.all })
  queryClient.invalidateQueries({ queryKey: executionKeys.all })
},
```

- [ ] **Step 4: 确认 useCancelExecution 已双向失效**

检查 `hooks/queries/executions.ts:125-128` — `useCancelExecution` 已经同时失效 `executionKeys.all` 和 `missionKeys.all`，无需修改。

- [ ] **Step 5: useCreateMissionComment 补充 execution 缓存失效**

评论创建可能触发新 execution（通过 lifecycle dispatch）。在 `hooks/queries/missionComments.ts` 的 `useCreateMissionComment` 的 `onSuccess` 中添加：

```typescript
import { executionKeys } from './executions'

// 在 onSuccess 回调中添加：
queryClient.invalidateQueries({ queryKey: executionKeys.all })
```

- [ ] **Step 5: 运行类型检查**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: 提交**

```bash
git add frontend/hooks/queries/missions.ts
git commit -m "fix(frontend): dispatch/cancel mutations invalidate both mission and execution caches"
```

---

### Task 4.5: MANUAL_TRANSITIONS 从 API 获取

**目的：** Phase 3.7 后端已提供 `/missions/meta/transitions` 端点。前端不再硬编码 `MANUAL_TRANSITIONS`，改为从 API 获取，消除重复定义漂移风险。

**Files:**
- Modify: `frontend/hooks/queries/missions.ts`
- Modify: `frontend/types/missions.ts`
- Modify: `frontend/components/missions/mission-board.tsx`
- Modify: `frontend/components/missions/mission-detail-panel.tsx`

- [ ] **Step 1: 在 missions.ts hooks 中添加 transitions query**

```typescript
// frontend/hooks/queries/missions.ts 新增：
export const missionMetaKeys = {
  transitions: (workspaceId: string) => ['missions', 'meta', 'transitions', workspaceId] as const,
}

export function useMissionTransitions(workspaceId: string) {
  return useQuery({
    queryKey: missionMetaKeys.transitions(workspaceId),
    queryFn: async (): Promise<Record<MissionStatus, MissionStatus[]>> => {
      const res = await apiGet<Record<string, string[]>>(
        `missions/meta/transitions?workspace_id=${workspaceId}`,
      )
      return (res ?? {}) as Record<MissionStatus, MissionStatus[]>
    },
    enabled: Boolean(workspaceId),
    staleTime: Infinity,  // 几乎不变，缓存永久有效
  })
}
```

在 import 中添加：
```typescript
import { apiGet } from '@/lib/api-client'
import type { MissionStatus } from '@/types/missions'
```

- [ ] **Step 2: 将 types/missions.ts 中的硬编码 MANUAL_TRANSITIONS 改为 fallback**

```typescript
// frontend/types/missions.ts:86-93 改为：
/** Fallback transitions — used before API response arrives. */
export const DEFAULT_MANUAL_TRANSITIONS: Record<MissionStatus, readonly MissionStatus[]> = {
  backlog: ['todo', 'in_progress', 'cancelled'],
  todo: ['backlog', 'in_progress', 'cancelled'],
  in_progress: ['todo', 'in_review', 'done', 'cancelled'],
  in_review: ['todo', 'in_progress', 'done', 'cancelled'],
  done: ['backlog', 'todo'],
  cancelled: ['backlog', 'todo'],
}

/** @deprecated Use useMissionTransitions() hook instead. Kept as re-export for backward compat. */
export const MANUAL_TRANSITIONS = DEFAULT_MANUAL_TRANSITIONS
```

- [ ] **Step 3: mission-board.tsx 使用 API transitions**

```typescript
// frontend/components/missions/mission-board.tsx
// 之前：
import { MANUAL_TRANSITIONS, ... } from '@/types/missions'

// 之后：
import { DEFAULT_MANUAL_TRANSITIONS, ... } from '@/types/missions'
import { useMissionTransitions } from '@/hooks/queries/missions'

// 在组件内：
export function MissionBoard({ missions, workspaceId, agentsMap, onSelectMission }: Props) {
  const { data: transitions } = useMissionTransitions(workspaceId)
  const effectiveTransitions = transitions ?? DEFAULT_MANUAL_TRANSITIONS

  // DnD handleDragEnd 中（约 line 124）：
  // 之前：const allowed = MANUAL_TRANSITIONS[from] ?? []
  // 之后：const allowed = effectiveTransitions[from] ?? []
}
```

- [ ] **Step 4: mission-detail-panel.tsx 使用 API transitions**

```typescript
// frontend/components/missions/mission-detail-panel.tsx:44
// 之前：
import { MANUAL_TRANSITIONS, ... } from '@/types/missions'

// 之后：
import { DEFAULT_MANUAL_TRANSITIONS, ... } from '@/types/missions'
import { useMissionTransitions } from '@/hooks/queries/missions'

// 在组件内：
const { data: transitions } = useMissionTransitions(workspaceId)
const effectiveTransitions = transitions ?? DEFAULT_MANUAL_TRANSITIONS

// 约 line 259 渲染状态选择器：
// 之前：(MANUAL_TRANSITIONS[mission.status] ?? []).map(...)
// 之后：(effectiveTransitions[mission.status] ?? []).map(...)
```

- [ ] **Step 5: 运行类型检查 + 开发服务器验证**

```bash
cd frontend && npx tsc --noEmit
cd frontend && npm run dev  # 手动验证：board 拖拽 + detail panel 状态切换
```

- [ ] **Step 6: 提交**

```bash
git add frontend/hooks/queries/missions.ts frontend/types/missions.ts frontend/components/missions/mission-board.tsx frontend/components/missions/mission-detail-panel.tsx
git commit -m "feat(frontend): fetch MANUAL_TRANSITIONS from API, fallback to local defaults"
```

---

### Task 4.6: 清理 Execution 类型中的冗余字段

**目的：** Phase 3.2 后端已删除 `source_id` 字段，Phase 3.6 标记 `interrupt_wait` 为保留。前端类型需同步清理。

**Files:**
- Modify: `frontend/types/executions.ts`

- [ ] **Step 1: 删除 source_id 字段**

```typescript
// frontend/types/executions.ts:6 删除：
//   source_id?: string | null
```

- [ ] **Step 2: 从 ACTIVE_EXECUTION_STATUSES 中移除 interrupt_wait**

```typescript
// 之前：
export const ACTIVE_EXECUTION_STATUSES: readonly ExecutionStatus[] = ['queued', 'dispatched', 'running', 'interrupt_wait', 'approval_wait'] as const

// 之后：
export const ACTIVE_EXECUTION_STATUSES: readonly ExecutionStatus[] = ['queued', 'dispatched', 'running', 'approval_wait'] as const
```

保留 `interrupt_wait` 在 `ExecutionStatus` 类型联合中（与后端枚举一致），但从活跃状态列表中移除。

- [ ] **Step 3: 全局搜索确认无 source_id 读取**

```bash
cd frontend && grep -rn "source_id" --include="*.ts" --include="*.tsx" | grep -v node_modules
```

如果有组件读取 `execution.source_id`，需一并删除。

- [ ] **Step 4: 运行类型检查**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: 提交**

```bash
git add frontend/types/executions.ts
git commit -m "fix(frontend): remove source_id, exclude interrupt_wait from active statuses"
```

---

### Task 4.7: 删除 `/executions/[executionId]` 独立页面

**目的：** `/executions/[executionId]` 页面是 Execution 作为独立概念时的遗留产物。它不在侧边栏导航中（sidebar 没有 `/executions` 链接），没有任何入口指向它。所有 execution 查看/操作都已内嵌到 MissionDetailPanel 的 ExecutionTimeline 中。直接删除。

**Files:**
- Delete: `frontend/app/executions/[executionId]/page.tsx`
- Delete: `frontend/app/executions/` (整个目录)

- [ ] **Step 1: 确认无其他文件引用该页面路由**

```bash
cd frontend && grep -rn "/executions/" --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v "api" | grep -v "services/"
```

预期结果：只有 `app/executions/[executionId]/page.tsx` 本身内部的 `<Link href="/executions">` 返回按钮。

- [ ] **Step 2: 删除页面文件**

```bash
rm -rf frontend/app/executions/
```

- [ ] **Step 3: 确认构建不报错**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 4: 提交**

```bash
git add -A frontend/app/executions/
git commit -m "refactor(frontend): delete standalone /executions page — all execution UI is in mission panel"
```

---

### Task 4.8: Mission Board URL 深链

**目的：** 当前 `selectedMissionId` 是 React state，刷新页面或分享链接时丢失。改为 URL query param `?mission=<id>`，支持深链跳转到特定 mission 的 detail panel。

**Files:**
- Modify: `frontend/app/missions/page.tsx`

- [ ] **Step 1: 用 URL searchParams 替代 React state**

```typescript
// frontend/app/missions/page.tsx
// 之前：
const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null)

// 之后：
import { useSearchParams, useRouter } from 'next/navigation'

// 在组件内：
const searchParams = useSearchParams()
const router = useRouter()
const selectedMissionId = searchParams.get('mission')

const setSelectedMissionId = (id: string | null) => {
  const params = new URLSearchParams(searchParams.toString())
  if (id) {
    params.set('mission', id)
  } else {
    params.delete('mission')
  }
  router.replace(`/missions?${params.toString()}`, { scroll: false })
}
```

- [ ] **Step 2: 确认 MissionDetailPanel 的 onClose 清除 URL param**

```typescript
// MissionDetailPanel 的 onClose 传给的回调：
onClose={() => setSelectedMissionId(null)}
// 这会 router.replace('/missions') 移除 ?mission= 参数
```

- [ ] **Step 3: 确认 MissionBoard/MissionCard 的 onSelectMission 设置 URL param**

```typescript
// 在 missions/page.tsx 中：
<MissionBoard
  missions={missions}
  workspaceId={workspaceId}
  agentsMap={agentsMap}
  onSelectMission={(id) => setSelectedMissionId(id)}
/>
```

原有行为不变，只是底层从 setState 变成了 URL push。

- [ ] **Step 4: 测试深链**

手动验证：
1. 打开 `/missions?mission=<some-id>` → detail panel 自动打开
2. 点击 mission card → URL 变为 `?mission=<id>`
3. 关闭 panel → URL 回到 `/missions`
4. 浏览器前进/后退 → panel 跟随 URL 变化

- [ ] **Step 5: 提交**

```bash
git add frontend/app/missions/page.tsx
git commit -m "feat(frontend): mission detail panel deep-linked via URL query param"
```

---

### Phase 4 完成状态

此时系统状态：
- ✅ `missionService` 拥有 mission-scoped execution 操作方法（message/approve/events/snapshot）
- ✅ `ExecutionTimeline` 在 mission 上下文中使用 mission-scoped 端点写操作
- ✅ dispatch/cancel mutations 同时失效 mission 和 execution 缓存
- ✅ `MANUAL_TRANSITIONS` 从 API `/missions/meta/transitions` 获取，本地定义降为 fallback
- ✅ `source_id` 从前端类型中清除，`interrupt_wait` 从活跃状态列表中移除
- ✅ `/executions/[executionId]` 独立页面已删除，无导航残留
- ✅ Mission board 支持 URL 深链 `?mission=<id>`
- ✅ Execution 完全降为 Mission 的内部实现细节，前端无独立 Execution 入口

---

## 全量重构完成标志

四个 Phase 全部完成后，系统应满足以下不变量：

### 后端
1. **零循环依赖**：`ExecutionRunner` ← `RunnerCallbacks` Protocol → `ExecutionLifecycleService` → `MissionService` / `ExecutionService` / `MissionCommentService`，单向箭头
2. **单一操作路径**：dispatch / cancel / finalize 各只有一个入口（`ExecutionLifecycleService`）
3. **Service 单域**：`MissionService` 不 import `ExecutionService`，反之亦然
4. **统一鉴权**：所有 API 端点使用 `require_workspace_role`
5. **统一异常**：Service 层 raise `NotFoundException` / `BadRequestException` / `ConflictException`
6. **数据完整性**：`current_execution_id` 有 FK 约束，冗余 `source_id` 已删除
7. **并发控制**：`max_concurrent_tasks` 在所有 dispatch 路径中执行

### 前端
1. **Mission-first**：无独立 Execution 页面，所有 execution UI 内嵌在 Mission 面板
2. **缓存一致性**：所有跨域 mutation 双向失效 mission + execution 缓存
3. **单一真实源**：`MANUAL_TRANSITIONS` 从后端 API 获取
4. **URL 可分享**：`/missions?mission=<id>` 深链到特定任务
