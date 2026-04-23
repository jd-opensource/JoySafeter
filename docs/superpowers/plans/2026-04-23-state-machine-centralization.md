# 状态管控及流转集中化 — 实施计划

> **目标**: 将分散在 15+ 文件中的状态赋值收敛到一个显式状态机模块，消除隐式转换、重复逻辑和命名不一致。

## 一、设计决策

### 1.1 统一词汇表

| 实体 | 现有 | 统一后 | 变更 |
|---|---|---|---|
| AgentRun | `queued, running, succeeded, failed, cancelled` | `pending, running, succeeded, failed, cancelled` | `queued` → `pending`（与 Execution 一致） |
| Execution | `pending, dispatched, running, approval_wait, succeeded, failed, cancelled` | 保持不变 | `dispatched`/`approval_wait` 是 CLI 引擎中间态，合理保留 |
| Task | `backlog, todo, in_progress, in_review, done, cancelled` | 保持不变 | `todo` 补充 MANUAL_TRANSITIONS 入口 |
| AgentVersion | `draft, frozen` | 保持不变 | — |
| AgentRelease | `building, ready, failed, retired` | `pending, ready, failed, retired` | `building` → `pending`（语义更准确，且和 Release 实际创建流程一致） |
| Agent | `draft, active, archived` | 保持不变 | — |

**总计 DB 枚举值变更**: 2 个 rename（`queued→pending`, `building→pending`）

### 1.2 状态机定义

```python
# 每个状态机定义: { from_status: {allowed_to_statuses} }

AGENT_STATES = {
    "draft":    {"active", "archived"},
    "active":   {"archived"},
    "archived": {"draft"},
}

VERSION_STATES = {
    "draft":  {"frozen"},
    "frozen": {"draft"},        # unfreeze
}

RELEASE_STATES = {
    "pending": {"ready", "failed"},
    "ready":   {"retired"},
    "failed":  {"retired"},
    "retired": set(),           # 终态
}

RUN_STATES = {
    "pending":   {"running", "cancelled"},
    "running":   {"succeeded", "failed", "cancelled"},
    "succeeded": set(),         # 终态
    "failed":    set(),         # 终态  
    "cancelled": set(),         # 终态
}

EXECUTION_STATES = {
    "pending":       {"dispatched", "running", "cancelled", "failed"},
    "dispatched":    {"running", "failed", "cancelled"},
    "running":       {"approval_wait", "succeeded", "failed", "cancelled"},
    "approval_wait": {"running", "cancelled"},
    "succeeded":     set(),
    "failed":        set(),
    "cancelled":     set(),
}

TASK_STATES = {
    "backlog":     {"todo", "in_progress", "cancelled"},
    "todo":        {"in_progress", "backlog", "cancelled"},
    "in_progress": {"done", "in_review", "cancelled", "backlog"},
    "in_review":   {"in_progress", "done", "backlog", "cancelled"},
    "done":        {"backlog"},
    "cancelled":   {"backlog"},
}
```

### 1.3 自动同步规则（Run → Task）

```python
RUN_TO_TASK_SYNC = {
    "pending":   "in_progress",
    "running":   "in_progress",
    "succeeded": "done",
    "failed":    "in_review",
    "cancelled": "backlog",
}
```

### 1.4 终态定义

```python
TERMINAL_STATUSES = {
    "run":       {"succeeded", "failed", "cancelled"},
    "execution": {"succeeded", "failed", "cancelled"},
    "release":   {"retired"},
    "agent":     {"archived"},
    "task":      {"done", "cancelled"},
}
```

---

## 二、文件结构

```
backend/app/core/
  state_machines/
    __init__.py              # 导出所有状态机和工具函数
    definitions.py           # 状态转换表 + 终态 + 同步映射（纯数据，无逻辑）
    engine.py                # StateMachine 类 + InvalidTransition 异常
    transitions.py           # transition_status() 统一入口函数（带 DB commit + 时间戳）
```

**为什么分 3 个文件而非 1 个:**
- `definitions.py` — 纯数据，可以被前端代码生成脚本读取
- `engine.py` — 通用状态机逻辑，不含业务
- `transitions.py` — 业务层，含 DB 操作和副作用

---

## 三、实施步骤

### Task 1: 创建 state_machines 模块

**创建:**
- `backend/app/core/state_machines/__init__.py`
- `backend/app/core/state_machines/definitions.py`
- `backend/app/core/state_machines/engine.py`
- `backend/app/core/state_machines/transitions.py`

**`engine.py` 核心实现:**

```python
class InvalidTransition(Exception):
    def __init__(self, entity: str, from_status: str, to_status: str):
        self.entity = entity
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"{entity}: {from_status} → {to_status} is not allowed")

class StateMachine:
    def __init__(self, name: str, transitions: dict[str, set[str]], terminal: set[str]):
        self.name = name
        self._transitions = transitions
        self._terminal = terminal

    def validate(self, from_status: str, to_status: str) -> None:
        allowed = self._transitions.get(from_status)
        if allowed is None:
            raise InvalidTransition(self.name, from_status, to_status)
        if to_status not in allowed:
            raise InvalidTransition(self.name, from_status, to_status)

    def is_terminal(self, status: str) -> bool:
        return status in self._terminal

    @property
    def all_statuses(self) -> set[str]:
        return set(self._transitions.keys())
```

**`transitions.py` 统一入口:**

```python
from app.core.state_machines.definitions import (
    RUN_SM, EXECUTION_SM, TASK_SM, VERSION_SM, RELEASE_SM, AGENT_SM,
    RUN_TO_TASK_SYNC,
)
from app.utils.datetime import utc_now

async def transition_run(run: AgentRun, to_status: str, db: AsyncSession, 
                         result_summary: str | None = None) -> None:
    RUN_SM.validate(run.status, to_status)
    run.status = to_status
    if RUN_SM.is_terminal(to_status):
        run.ended_at = utc_now()
        run.result_summary = result_summary
    await db.flush()

async def transition_execution(execution: Execution, to_status: str, db: AsyncSession) -> None:
    EXECUTION_SM.validate(execution.status, to_status)
    execution.status = to_status
    if to_status == "running" and not execution.started_at:
        execution.started_at = utc_now()
    if EXECUTION_SM.is_terminal(to_status):
        execution.ended_at = utc_now()
    await db.flush()

async def transition_task(task: Task, to_status: str, db: AsyncSession) -> None:
    TASK_SM.validate(task.status, to_status)
    task.status = to_status
    await db.flush()

async def sync_task_from_run(run: AgentRun, db: AsyncSession) -> None:
    """自动同步: Run 终态 → Task 状态"""
    if not run.task_id:
        return
    task = await db.get(Task, run.task_id)
    if not task:
        return
    target = RUN_TO_TASK_SYNC.get(run.status)
    if target and task.status != target:
        TASK_SM.validate(task.status, target)
        task.status = target
        task.latest_run_id = run.id
        await db.flush()
```

### Task 2: Alembic migration — 统一词汇

**变更:**
- `agent_run_status` 枚举: rename `queued` → `pending`
- `agent_release_status` 枚举: rename `building` → `pending`
- 更新 DB 中现有行的值

```python
def upgrade():
    # AgentRun: queued → pending
    op.execute("ALTER TYPE agent_run_status RENAME VALUE 'queued' TO 'pending'")
    # AgentRelease: building → pending
    op.execute("ALTER TYPE agent_release_status RENAME VALUE 'building' TO 'pending'")

def downgrade():
    op.execute("ALTER TYPE agent_run_status RENAME VALUE 'pending' TO 'queued'")
    op.execute("ALTER TYPE agent_release_status RENAME VALUE 'building' TO 'pending'")
```

同步更新:
- `backend/app/models/agent_run.py` — 枚举值 `queued` → `pending`，默认值改为 `"pending"`
- `backend/app/models/agent.py` — AgentRelease 枚举值 `building` → `pending`，默认值改为 `"ready"` (已改)

### Task 3: 收敛后端状态赋值 — Orchestrator

**修改:** `backend/app/core/engine/orchestrator.py`

将所有 `.status =` 直接赋值替换为 `transition_*()` 调用:

| 当前代码 | 替换为 |
|---|---|
| `run.status = "running"` (line 194) | `await transition_run(run, "running", db)` |
| `run.status = "cancelled"` (line 160) | `await transition_run(run, "cancelled", db)` |
| `run.status = "failed"` (line 282) | `await transition_run(run, "failed", db, str(exc))` |
| `execution.status = "cancelled"` (line 157) | `await transition_execution(execution, "cancelled", db)` |
| `execution.status = "failed"` (line 284) | `await transition_execution(execution, "failed", db)` |
| `task.status = "in_progress"` (line 81) | `await transition_task(task, "in_progress", db)` |
| `_sync_task_status()` 整个方法 | 替换为 `await sync_task_from_run(run, db)` |

**修改 `_wire_context` 回调:**

`_status` 回调 → `await transition_execution(execution, status, ctx.db)`
`_complete` 回调 → `await transition_execution(...)` + `await transition_run(...)` + `await sync_task_from_run(...)`

删除 `_sync_task_status` 方法（逻辑移到 `transitions.py`）。

### Task 4: 收敛后端状态赋值 — Services + API

**修改:** `backend/app/services/task_service.py`

| 当前代码 | 替换为 |
|---|---|
| `task.status = TaskStatus.IN_PROGRESS` (assign_to_agent:165) | `await transition_task(task, "in_progress", db)` |
| `update_task` 中的 `MANUAL_TRANSITIONS` 验证 | 替换为 `TASK_SM.validate(task.status, new_status)` |
| 删除 `MANUAL_TRANSITIONS` dict | 由 `definitions.py` 中的 `TASK_STATES` 替代 |
| 删除 `sync_status_from_run` 方法 | 由 `transitions.sync_task_from_run` 替代 |

**修改:** `backend/app/api/v1/tasks.py`

| 当前代码 | 替换为 |
|---|---|
| `task.status = "cancelled"` (line 216) | `await transition_task(task, "cancelled", db)` |

**修改:** `backend/app/services/agent_version_service.py`

| 当前代码 | 替换为 |
|---|---|
| `version.status = "frozen"` | `VERSION_SM.validate(version.status, "frozen"); version.status = "frozen"` |
| `version.status = "draft"` (unfreeze) | `VERSION_SM.validate(version.status, "draft"); version.status = "draft"` |

**修改:** `backend/app/services/agent_release_service.py`

| 当前代码 | 替换为 |
|---|---|
| 创建时 `status = "ready"` | 保持（初始态不需要转换验证） |
| `release.status = "retired"` | `RELEASE_SM.validate(release.status, "retired"); release.status = "retired"` |

**修改:** `backend/app/services/execution_service.py`

| 当前代码 | 替换为 |
|---|---|
| `mark_status()` 中 `execution.status = status` | `await transition_execution(execution, status, db)` |

**修改:** `backend/app/core/scheduler.py`

| 当前代码 | 替换为 |
|---|---|
| `run.status = "failed"` (reaper) | `await transition_run(run, "failed", db, "Reaped: stale execution")` |

### Task 5: 收敛 CLI Engine 状态赋值

**修改:** `backend/app/core/agent/cli_backends/execution_runner.py`

execution_runner 通过 `execution_service.mark_status()` 写状态。Task 4 已将 `mark_status` 内部改为 `transition_execution()`，所以 runner 调用方不需要改 —— 只需确认传入的 status 值在状态机中合法。

验证: `dispatched`, `running`, `approval_wait`, `succeeded/completed`, `failed` 都在 EXECUTION_STATES 中。

**注意:** runner 写 `"completed"` 但 orchestrator 期望 `"succeeded"`。需要在 runner 中将 `"completed"` 映射为 `"succeeded"`，或在状态机中将 `"completed"` 作为 `"succeeded"` 的别名。

**推荐:** 在 `execution_runner.py` 中修正: `status = "succeeded" if status == "completed" else status`

### Task 6: 前端类型同步

**修改:** `frontend/types/agent-run.ts`
- `AgentRunStatus`: `'queued'` → `'pending'`
- `TERMINAL_RUN_STATUSES`, `RUN_STATUS_STYLES`, `RUN_STATUS_I18N` 同步更新

**修改:** `frontend/types/agent-release.ts`
- `AgentReleaseStatus`: `'building'` → `'pending'`

**修改:** `frontend/types/missions.ts`
- `MANUAL_TRANSITIONS`: 补充 `todo` 的出口（`backlog`, `in_progress`, `cancelled`）

**修改:** `frontend/app/runs/page.tsx`
- `RUN_STATUS_OPTIONS`: `'queued'` → `'pending'`

**修改:** `frontend/lib/utils/runHelpers.ts`
- `formatRunStatus`: `queued:` → `pending:`

**修改:** i18n locale files — 添加 `statusPending` key

### Task 7: 补充 `todo` 状态的转换路径

**后端:** `definitions.py` 中 `TASK_STATES` 已包含 `"todo"` 出口。
**后端:** `task_service.py` 的旧 `MANUAL_TRANSITIONS` 被删除（Task 4），新逻辑走状态机。无需额外操作。
**前端:** Task 6 已在 `MANUAL_TRANSITIONS` 中补充 `todo`。

### Task 8: 测试 + 验证

**新建测试:** `backend/tests/test_core/test_state_machines.py`

```python
def test_run_valid_transition():
    RUN_SM.validate("pending", "running")  # should not raise

def test_run_invalid_transition():
    with pytest.raises(InvalidTransition):
        RUN_SM.validate("succeeded", "running")  # 终态不可回退

def test_task_sync_from_run():
    assert RUN_TO_TASK_SYNC["succeeded"] == "done"
    assert RUN_TO_TASK_SYNC["failed"] == "in_review"

def test_all_states_reachable():
    """确保没有孤立状态"""
    for sm in [RUN_SM, EXECUTION_SM, TASK_SM]:
        all_targets = set()
        for targets in sm._transitions.values():
            all_targets |= targets
        orphans = all_targets - sm.all_statuses
        assert orphans == set(), f"Orphan states: {orphans}"
```

**验证:**
- `cd backend && python -m pytest tests/test_core/test_state_machines.py -v`
- `cd backend && python -m pytest tests/ -x --timeout=30`
- `cd frontend && npx tsc --noEmit`
- `cd frontend && npx vitest run`

---

## 四、影响范围总结

| 操作 | 文件数 | 新建/修改/删除 |
|---|---|---|
| 创建 state_machines 模块 | 4 | 新建 |
| Alembic migration | 1 | 新建 |
| 后端模型枚举值更新 | 2 | 修改 |
| Orchestrator 收敛 | 1 | 修改 |
| Services 收敛 | 4 | 修改 |
| API 层修正 | 1 | 修改 |
| Scheduler 修正 | 1 | 修改 |
| execution_runner 修正 | 1 | 修改 |
| 前端类型同步 | 5 | 修改 |
| 测试 | 1 | 新建 |
| **总计** | **~21 文件** | |

## 五、风险点

1. `ALTER TYPE ... RENAME VALUE` 需要 PostgreSQL 10+，确认生产环境版本
2. execution_runner 的 `"completed"` → `"succeeded"` 映射需要同时处理历史数据（DB 中可能存在 `"completed"` 值的旧行）
3. `InvalidTransition` 异常会阻断原本"静默错误"的路径 — 需要在所有调用点加适当的 error handling
