import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_task import (
    JOYSAFETER_TERMINAL_STATUSES,
    JoySafeterTask,
    JoySafeterTaskStatus,
)
from app.joysafeter_shared.utils.datetime import utc_now


TERMINAL_VALUES = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]


class JoySafeterTaskStateMachine:
    """Centralized DB state transitions for joysafeter tasks."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def claim_for_scheduling(self, task_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.id == task_id,
                    JoySafeterTask.status == JoySafeterTaskStatus.PENDING.value,
                )
            )
            .values(status=JoySafeterTaskStatus.SCHEDULING.value, started_at=func.now())
        )
        await self.db.commit()
        return result.rowcount > 0

    async def claim_pending_batch(self, limit: int) -> list[uuid.UUID]:
        if limit <= 0:
            return []

        pending_ids = (
            select(JoySafeterTask.id)
            .where(JoySafeterTask.status == JoySafeterTaskStatus.PENDING.value)
            .order_by(JoySafeterTask.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("pending_claim")
        )
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(JoySafeterTask.id.in_(select(pending_ids.c.id)))
            .values(status=JoySafeterTaskStatus.SCHEDULING.value, started_at=func.now())
            .returning(JoySafeterTask.id)
        )
        await self.db.commit()
        return list(result.scalars().all())

    async def cancel(self, task_id: uuid.UUID) -> Optional[JoySafeterTask]:
        task = await self._get_task(task_id)
        if not task:
            return None
        status = JoySafeterTaskStatus.from_str_lossy(task.status)
        if status.is_terminal():
            raise ValueError(f"Task already in terminal state: {task.status}")

        task.status = JoySafeterTaskStatus.CANCELLED.value
        task.completed_at = utc_now()
        task.duration_ms = self._duration_ms(task.started_at, task.completed_at)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def transition_to(
        self,
        task_id: uuid.UUID,
        new_status: JoySafeterTaskStatus,
    ) -> bool:
        now = utc_now()
        if new_status == JoySafeterTaskStatus.RUNNING:
            result = await self.db.execute(
                sa_update(JoySafeterTask)
                .where(
                    and_(
                        JoySafeterTask.id == task_id,
                        JoySafeterTask.status.in_(
                            [
                                JoySafeterTaskStatus.SCHEDULING.value,
                            ]
                        ),
                    )
                )
                .values(status=new_status.value, started_at=now)
            )
        elif new_status.is_terminal():
            duration_ms = await self._duration_ms_for_task(task_id, now)
            result = await self.db.execute(
                sa_update(JoySafeterTask)
                .where(
                    and_(
                        JoySafeterTask.id == task_id,
                        JoySafeterTask.status.notin_(TERMINAL_VALUES),
                    )
                )
                .values(
                    status=new_status.value,
                    completed_at=now,
                    duration_ms=duration_ms,
                )
            )
        else:
            result = await self.db.execute(
                sa_update(JoySafeterTask)
                .where(
                    and_(
                        JoySafeterTask.id == task_id,
                        JoySafeterTask.status.notin_(TERMINAL_VALUES),
                    )
                )
                .values(status=new_status.value)
            )
        await self.db.commit()
        return result.rowcount > 0

    async def claim_next_sandbox_task_for_running(
        self, sandbox_id: uuid.UUID
    ) -> Optional[uuid.UUID]:
        now = utc_now()
        next_task = (
            select(JoySafeterTask.id)
            .where(
                and_(
                    JoySafeterTask.sandbox_id == sandbox_id,
                    JoySafeterTask.status == JoySafeterTaskStatus.SCHEDULING.value,
                )
            )
            .order_by(JoySafeterTask.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(JoySafeterTask.id == next_task)
            .values(status=JoySafeterTaskStatus.RUNNING.value, started_at=now)
            .returning(JoySafeterTask.id)
        )
        await self.db.commit()
        return result.scalar_one_or_none()

    async def fail_with_error(
        self,
        task_id: uuid.UUID,
        error: str,
        new_status: JoySafeterTaskStatus,
    ) -> bool:
        assert new_status.is_terminal(), (
            f"fail_with_error called with non-terminal status: {new_status}"
        )
        now = utc_now()
        duration_ms = await self._duration_ms_for_task(task_id, now)
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.id == task_id,
                    JoySafeterTask.status.notin_(TERMINAL_VALUES),
                )
            )
            .values(
                error=error,
                status=new_status.value,
                completed_at=now,
                duration_ms=duration_ms,
            )
        )
        await self.db.commit()
        return result.rowcount > 0

    async def retry(self, task_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.id == task_id,
                    JoySafeterTask.status.notin_(TERMINAL_VALUES),
                )
            )
            .values(
                retry_count=JoySafeterTask.retry_count + 1,
                status=JoySafeterTaskStatus.PENDING.value,
                started_at=None,
                sandbox_id=None,
            )
        )
        await self.db.commit()
        return result.rowcount > 0

    async def reset_sandbox_scheduling_to_pending(self, sandbox_id: uuid.UUID) -> int:
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.status == JoySafeterTaskStatus.SCHEDULING.value,
                    JoySafeterTask.sandbox_id == sandbox_id,
                )
            )
            .values(
                status=JoySafeterTaskStatus.PENDING.value,
                started_at=None,
                sandbox_id=None,
                retry_count=JoySafeterTask.retry_count + 1,
            )
        )
        await self.db.commit()
        return result.rowcount

    async def attach_sandbox_if_scheduling(
        self, task_id: uuid.UUID, sandbox_id: uuid.UUID
    ) -> bool:
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.id == task_id,
                    JoySafeterTask.status == JoySafeterTaskStatus.SCHEDULING.value,
                )
            )
            .values(sandbox_id=sandbox_id)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def _get_task(self, task_id: uuid.UUID) -> Optional[JoySafeterTask]:
        result = await self.db.execute(
            select(JoySafeterTask).where(JoySafeterTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def _duration_ms_for_task(
        self, task_id: uuid.UUID, completed_at: datetime
    ) -> Optional[int]:
        started_at = (
            await self.db.execute(
                select(JoySafeterTask.started_at).where(JoySafeterTask.id == task_id)
            )
        ).scalar_one_or_none()
        return self._duration_ms(started_at, completed_at)

    @staticmethod
    def _duration_ms(
        started_at: Optional[datetime], completed_at: datetime
    ) -> Optional[int]:
        if started_at is None:
            return None
        return int((completed_at - started_at).total_seconds() * 1000)
