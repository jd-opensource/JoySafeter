"""
Centralized status transition functions.

These are the ONLY functions that should modify .status on domain entities.
All status changes in the codebase should route through here.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.state_machines import (
    RUN_SM, EXECUTION_SM, TASK_SM, VERSION_SM, RELEASE_SM, AGENT_SM,
    RUN_TO_TASK_SYNC,
)
from app.core.state_machines.engine import InvalidTransition
from app.utils.datetime import utc_now


async def transition_run(
    run,  # AgentRun — avoid circular import
    to_status: str,
    db: AsyncSession,
    result_summary: str | None = None,
) -> None:
    """Transition an AgentRun to a new status with validation."""
    RUN_SM.validate(run.status, to_status)
    run.status = to_status
    if RUN_SM.is_terminal(to_status):
        run.ended_at = run.ended_at or utc_now()
        if result_summary is not None:
            run.result_summary = result_summary
    await db.flush()


async def transition_execution(
    execution,  # Execution
    to_status: str,
    db: AsyncSession,
) -> None:
    """Transition an Execution to a new status with validation."""
    EXECUTION_SM.validate(execution.status, to_status)
    execution.status = to_status
    if to_status == "running" and not execution.started_at:
        execution.started_at = utc_now()
    if EXECUTION_SM.is_terminal(to_status):
        execution.ended_at = execution.ended_at or utc_now()
    await db.flush()


async def transition_task(
    task,  # Task
    to_status: str,
    db: AsyncSession,
) -> None:
    """Transition a Task to a new status with validation."""
    TASK_SM.validate(task.status, to_status)
    task.status = to_status
    await db.flush()


async def sync_task_from_run(
    run,  # AgentRun
    db: AsyncSession,
) -> None:
    """Auto-sync Task status based on Run terminal status."""
    if not run.task_id:
        return
    from app.models.task import Task
    task = (await db.execute(
        select(Task).where(Task.id == run.task_id)
    )).scalar_one_or_none()
    if not task:
        return
    target = RUN_TO_TASK_SYNC.get(run.status)
    if target and task.status != target:
        try:
            await transition_task(task, target, db)
        except InvalidTransition:
            # Edge case: task was manually moved to a state where auto-sync
            # is not valid (e.g., user set it to "done" before run finished).
            # Don't override the manual decision.
            return
        task.latest_run_id = run.id
        await db.flush()
