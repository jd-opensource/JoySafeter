import uuid
from datetime import datetime, timedelta
from typing import Any, Optional, cast

from sqlalchemy import CursorResult, Sequence, and_, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_task import (
    JOYSAFETER_TERMINAL_STATUSES,
    JoySafeterTask,
    JoySafeterTaskStatus,
)
from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_shared.utils.datetime import utc_now

TERMINAL_VALUES = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]

# Durable monotonic source for the fencing token stamped at each →RUNNING claim.
# Standalone (not bound to metadata) so referencing .next_value() only renders
# ``nextval('joysafeter_task_owner_epoch_seq')`` — the sequence itself is
# created/dropped by migration 20260702_000004.
_OWNER_EPOCH_SEQ = Sequence("joysafeter_task_owner_epoch_seq")


def _lease_expiry(now: datetime) -> datetime:
    """The lease deadline for a task claimed at ``now``."""
    return now + timedelta(seconds=joysafeter_config.task_lease_ttl_sec)


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
        return cast(CursorResult[Any], result).rowcount > 0

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
                status=JoySafeterTaskStatus.CANCELLED.value,
                completed_at=now,
                duration_ms=duration_ms,
            )
            .returning(JoySafeterTask.id)
        )
        await self.db.commit()
        row = result.one_or_none()
        if row is not None:
            return await self._get_task(task_id)

        current = await self._get_task(task_id)
        if not current:
            return None
        status = JoySafeterTaskStatus.from_str_lossy(current.status)
        if status.is_terminal():
            raise ValueError(f"Task already in terminal state: {current.status}")
        return None

    async def transition_to(
        self,
        task_id: uuid.UUID,
        new_status: JoySafeterTaskStatus,
        expected_epoch: Optional[int] = None,
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
                .values(
                    status=new_status.value,
                    started_at=now,
                    owner_instance_id=joysafeter_config.instance_id,
                    lease_expires_at=_lease_expiry(now),
                    owner_epoch=_OWNER_EPOCH_SEQ.next_value(),
                )
            )
        elif new_status.is_terminal():
            duration_ms = await self._duration_ms_for_task(task_id, now)
            result = await self.db.execute(
                sa_update(JoySafeterTask)
                .where(self._owned_and_active(task_id, expected_epoch))
                .values(
                    status=new_status.value,
                    completed_at=now,
                    duration_ms=duration_ms,
                )
            )
        else:
            result = await self.db.execute(
                sa_update(JoySafeterTask)
                .where(self._owned_and_active(task_id, expected_epoch))
                .values(status=new_status.value)
            )
        await self.db.commit()
        return cast(CursorResult[Any], result).rowcount > 0

    async def claim_next_sandbox_task_for_running(self, sandbox_id: uuid.UUID) -> Optional[tuple[uuid.UUID, int]]:
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
            .values(
                status=JoySafeterTaskStatus.RUNNING.value,
                started_at=now,
                owner_instance_id=joysafeter_config.instance_id,
                lease_expires_at=_lease_expiry(now),
                owner_epoch=_OWNER_EPOCH_SEQ.next_value(),
            )
            .returning(JoySafeterTask.id, JoySafeterTask.owner_epoch)
        )
        await self.db.commit()
        row = result.one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def fail_with_error(
        self,
        task_id: uuid.UUID,
        error: str,
        new_status: JoySafeterTaskStatus,
        expected_epoch: Optional[int] = None,
    ) -> bool:
        assert new_status.is_terminal(), f"fail_with_error called with non-terminal status: {new_status}"
        now = utc_now()
        duration_ms = await self._duration_ms_for_task(task_id, now)
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(self._owned_and_active(task_id, expected_epoch))
            .values(
                error=error,
                status=new_status.value,
                completed_at=now,
                duration_ms=duration_ms,
            )
        )
        await self.db.commit()
        return cast(CursorResult[Any], result).rowcount > 0

    async def retry(self, task_id: uuid.UUID, expected_epoch: Optional[int] = None) -> bool:
        conditions = [
            JoySafeterTask.id == task_id,
            JoySafeterTask.status.notin_(TERMINAL_VALUES),
        ]
        if expected_epoch is not None:
            conditions.append(JoySafeterTask.owner_epoch == expected_epoch)

        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(and_(*conditions))
            .values(
                retry_count=JoySafeterTask.retry_count + 1,
                status=JoySafeterTaskStatus.PENDING.value,
                started_at=None,
                sandbox_id=None,
                owner_instance_id=None,
                lease_expires_at=None,
                owner_epoch=None,
            )
        )
        await self.db.commit()
        return cast(CursorResult[Any], result).rowcount > 0

    async def attach_sandbox_if_scheduling(self, task_id: uuid.UUID, sandbox_id: uuid.UUID) -> bool:
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
        return cast(CursorResult[Any], result).rowcount > 0

    async def renew_leases(self, instance_id: str) -> int:
        """Extend the lease on every running task owned by ``instance_id``.

        Called on a fast cadence by the owning instance's watchdog so a live
        owner never lets its own lease lapse. Only running tasks carry a live
        lease, so non-running rows (even if still tagged with a stale
        ``owner_instance_id``) are deliberately excluded.
        """
        now = utc_now()
        result = await self.db.execute(
            sa_update(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.owner_instance_id == instance_id,
                    JoySafeterTask.status == JoySafeterTaskStatus.RUNNING.value,
                )
            )
            .values(lease_expires_at=_lease_expiry(now))
        )
        await self.db.commit()
        return cast(CursorResult[Any], result).rowcount

    async def find_lease_expired_running(self) -> list[uuid.UUID]:
        """Running tasks whose lease has lapsed — their owner is presumed dead.

        These are reclaimed by the watchdog in seconds instead of waiting for
        the ``timeout_sec`` upper bound.
        """
        now = utc_now()
        result = await self.db.execute(
            select(JoySafeterTask.id).where(
                and_(
                    JoySafeterTask.status == JoySafeterTaskStatus.RUNNING.value,
                    JoySafeterTask.lease_expires_at.isnot(None),
                    JoySafeterTask.lease_expires_at < now,
                )
            )
        )
        return list(result.scalars().all())

    @staticmethod
    def _owned_and_active(task_id: uuid.UUID, expected_epoch: Optional[int]) -> Any:
        """WHERE clause for a mutating write on a live task.

        Always guards on "not already terminal" (the pre-fencing invariant).
        When ``expected_epoch`` is supplied, additionally fences on the ownership
        grant: a caller holding a stale token (its task was reclaimed and re-run,
        bumping ``owner_epoch``) matches zero rows and its write is dropped.
        ``None`` preserves the unconditional-by-status behavior for callers that
        hold no grant (pre-RUNNING scheduler/watchdog paths).
        """
        conditions = [
            JoySafeterTask.id == task_id,
            JoySafeterTask.status.notin_(TERMINAL_VALUES),
        ]
        if expected_epoch is not None:
            conditions.append(JoySafeterTask.owner_epoch == expected_epoch)
        return and_(*conditions)

    async def update_output(self, task_id: uuid.UUID, output: str, expected_epoch: Optional[int] = None) -> bool:
        """Epoch-fenced write of the full task output."""
        result = await self.db.execute(
            sa_update(JoySafeterTask).where(self._owned_and_active(task_id, expected_epoch)).values(output=output)
        )
        await self.db.commit()
        return cast(CursorResult[Any], result).rowcount > 0

    async def update_usage(self, task_id: uuid.UUID, usage: dict, expected_epoch: Optional[int] = None) -> bool:
        """Epoch-fenced write of the task usage record."""
        result = await self.db.execute(
            sa_update(JoySafeterTask).where(self._owned_and_active(task_id, expected_epoch)).values(usage=usage)
        )
        await self.db.commit()
        return cast(CursorResult[Any], result).rowcount > 0

    async def _get_task(self, task_id: uuid.UUID) -> Optional[JoySafeterTask]:
        result = await self.db.execute(
            select(JoySafeterTask).where(JoySafeterTask.id == task_id).execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def _duration_ms_for_task(self, task_id: uuid.UUID, completed_at: datetime) -> Optional[int]:
        started_at = (
            await self.db.execute(select(JoySafeterTask.started_at).where(JoySafeterTask.id == task_id))
        ).scalar_one_or_none()
        return self._duration_ms(started_at, completed_at)

    @staticmethod
    def _duration_ms(started_at: Optional[datetime], completed_at: datetime) -> Optional[int]:
        if started_at is None:
            return None
        return int((completed_at - started_at).total_seconds() * 1000)
