"""Schedule service: CRUD, atomic multi-worker claim, and cron advancement.

Claiming uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so any number of worker
replicas can run the poller concurrently without ever firing the same schedule
twice — the same coordination primitive the Rust task engine uses. Advancement
implements "catch up once and advance": a schedule that came due while the
worker was down fires exactly once, then ``next_run_at`` jumps to the next cron
instant in the future (missed intermediate slots are skipped, not backfilled).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_schedule import JoySafeterSchedule
from app.joysafeter_domain.models.joysafeter_task import (
    JOYSAFETER_TERMINAL_STATUSES,
    JoySafeterTask,
    JoySafeterTaskStatus,
)
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_shared.common.app_errors import NotFoundError, RequestValidationAppError, ResourceConflictError
from app.joysafeter_shared.utils.cron import compute_next_run

_NON_TERMINAL_STATUSES = [s.value for s in JoySafeterTaskStatus if s not in JOYSAFETER_TERMINAL_STATUSES]


class JoySafeterScheduleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_runnable_target(
        self,
        *,
        agent_id: uuid.UUID,
        project_id: Optional[str],
        environment_ref: Optional[str] = None,
    ) -> tuple[JoySafeterAgent, Optional[str]]:
        conditions = [JoySafeterAgent.id == agent_id, JoySafeterAgent.deleted_at.is_(None)]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(select(JoySafeterAgent).where(*conditions))
        agent = result.scalar_one_or_none()
        if agent is None:
            raise NotFoundError(
                code="SCHEDULE_AGENT_NOT_FOUND",
                message="Agent not found",
                data={"agent_id": str(agent_id)},
                user_action="refresh",
            )
        if agent.archived_at is not None:
            raise ResourceConflictError(
                code="AGENT_ARCHIVED",
                message="Agent is archived and cannot create new scheduled runs.",
                data={"agent_id": str(agent_id)},
                user_action="refresh",
            )

        effective_environment_ref = environment_ref or agent.environment_ref
        if effective_environment_ref:
            env = await EnvironmentService(self.db).get_environment_by_ref(
                effective_environment_ref,
                project_id=project_id,
            )
            if env is None:
                raise RequestValidationAppError(
                    code="SCHEDULE_ENVIRONMENT_NOT_FOUND",
                    message=f"Environment not found: {effective_environment_ref}",
                    data={"environment_ref": effective_environment_ref},
                    user_action="fix_input",
                )
            if env.archived_at is not None:
                raise ResourceConflictError(
                    code="ENVIRONMENT_ARCHIVED",
                    message=f"Environment is archived: {effective_environment_ref}",
                    data={"environment_ref": effective_environment_ref, "environment_id": str(env.id)},
                    user_action="refresh",
                )
        return agent, effective_environment_ref

    # --- CRUD ---

    async def create(
        self,
        *,
        name: str,
        agent_id: uuid.UUID,
        prompt: str,
        cron_expr: str,
        timezone: str = "UTC",
        system_prompt: Optional[str] = None,
        environment_ref: Optional[str] = None,
        description: Optional[str] = None,
        timeout_sec: int = 7200,
        max_retries: int = 2,
        concurrency_policy: str = "allow",
        enabled: bool = True,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> JoySafeterSchedule:
        await self.resolve_runnable_target(
            agent_id=agent_id,
            project_id=project_id,
            environment_ref=environment_ref,
        )
        schedule = JoySafeterSchedule(
            name=name,
            agent_id=agent_id,
            prompt=prompt,
            system_prompt=system_prompt,
            environment_ref=environment_ref,
            description=description,
            cron_expr=cron_expr,
            timezone=timezone,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            concurrency_policy=concurrency_policy,
            enabled=enabled,
            project_id=project_id,
            user_id=user_id,
            org_id=org_id,
            next_run_at=compute_next_run(cron_expr, timezone) if enabled else None,
        )
        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def get(self, schedule_id: uuid.UUID, project_id: Optional[str] = None) -> Optional[JoySafeterSchedule]:
        conditions = [JoySafeterSchedule.id == schedule_id]
        if project_id is not None:
            conditions.append(JoySafeterSchedule.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSchedule).where(*conditions))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, project_id: Optional[str]) -> Optional[JoySafeterSchedule]:
        result = await self.db.execute(
            select(JoySafeterSchedule).where(
                JoySafeterSchedule.name == name,
                JoySafeterSchedule.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        project_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[JoySafeterSchedule]:
        conditions = []
        if project_id is not None:
            conditions.append(JoySafeterSchedule.project_id == project_id)
        if enabled is not None:
            conditions.append(JoySafeterSchedule.enabled == enabled)
        stmt = (
            select(JoySafeterSchedule)
            .where(*conditions)
            .order_by(JoySafeterSchedule.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update(
        self, schedule_id: uuid.UUID, project_id: Optional[str], **fields: Any
    ) -> Optional[JoySafeterSchedule]:
        schedule = await self.get(schedule_id, project_id=project_id)
        if schedule is None:
            return None
        next_environment_ref = fields["environment_ref"] if "environment_ref" in fields else schedule.environment_ref
        should_validate_target = (
            "environment_ref" in fields
            or fields.get("enabled") is True
            or (schedule.enabled and any(k in fields for k in ("cron_expr", "timezone")))
        )
        if should_validate_target:
            await self.resolve_runnable_target(
                agent_id=schedule.agent_id,
                project_id=schedule.project_id,
                environment_ref=next_environment_ref,
            )
        for key, value in fields.items():
            setattr(schedule, key, value)
        # Recompute the next fire if cadence or enabled state changed.
        if any(k in fields for k in ("cron_expr", "timezone", "enabled")):
            if schedule.enabled:
                schedule.next_run_at = compute_next_run(schedule.cron_expr, schedule.timezone)
            else:
                schedule.next_run_at = None
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def delete(self, schedule_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        schedule = await self.get(schedule_id, project_id=project_id)
        if schedule is None:
            return False
        await self.db.delete(schedule)
        await self.db.commit()
        return True

    # --- Project lifecycle support ---

    async def pause_for_project_archive(self, project_id: str) -> None:
        """Pause project schedules without changing the user's enabled intent.

        The caller owns the transaction. Archiving a project freezes writes, so
        due slots and stale locks are cleared. Restore recomputes future slots
        instead of replaying cron instants that elapsed while archived.
        """
        await self.db.execute(
            update(JoySafeterSchedule)
            .where(JoySafeterSchedule.project_id == project_id)
            .values(next_run_at=None, locked_by=None, locked_at=None)
        )

    async def pause_for_agent_archive(self, agent_id: uuid.UUID) -> None:
        """Pause schedules targeting an archived agent without deleting audit state."""
        await self.db.execute(
            update(JoySafeterSchedule)
            .where(JoySafeterSchedule.agent_id == agent_id)
            .values(next_run_at=None, locked_by=None, locked_at=None)
        )

    async def resume_after_project_restore(self, project_id: str) -> None:
        """Recompute schedule fire slots after a project is restored.

        The caller owns the transaction. Enabled schedules resume from the next
        future cron instant; disabled schedules remain disabled with no due slot.
        """
        result = await self.db.execute(
            select(JoySafeterSchedule).where(JoySafeterSchedule.project_id == project_id)
        )
        for schedule in result.scalars().all():
            schedule.locked_by = None
            schedule.locked_at = None
            if schedule.enabled:
                schedule.next_run_at = compute_next_run(schedule.cron_expr, schedule.timezone)
            else:
                schedule.next_run_at = None

    # --- Poller coordination ---

    async def claim_due_schedules(
        self,
        *,
        worker_id: str,
        limit: int,
        lock_grace_sec: int,
    ) -> Sequence[JoySafeterSchedule]:
        """Atomically claim up to *limit* due, enabled, unlocked schedules.

        A schedule is claimable when ``next_run_at <= now`` and it is either
        unlocked or its lock is stale (owner crashed). ``FOR UPDATE SKIP LOCKED``
        lets concurrent workers each grab a disjoint batch without blocking.
        """
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=lock_grace_sec)

        due_ids = (
            select(JoySafeterSchedule.id)
            .where(
                or_(
                    JoySafeterSchedule.project_id.is_(None),
                    select(Project.id)
                    .where(
                        Project.id == JoySafeterSchedule.project_id,
                        Project.archived_at.is_(None),
                    )
                    .exists(),
                ),
                JoySafeterSchedule.enabled.is_(True),
                JoySafeterSchedule.next_run_at.is_not(None),
                JoySafeterSchedule.next_run_at <= now,
                or_(
                    JoySafeterSchedule.locked_by.is_(None),
                    JoySafeterSchedule.locked_at <= stale_before,
                ),
            )
            .order_by(JoySafeterSchedule.next_run_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

        stmt = (
            update(JoySafeterSchedule)
            .where(JoySafeterSchedule.id.in_(due_ids))
            .values(locked_by=worker_id, locked_at=now)
            .returning(JoySafeterSchedule)
        )
        result = await self.db.execute(stmt, execution_options={"populate_existing": True})
        claimed = result.scalars().all()
        await self.db.commit()
        return claimed

    async def advance_after_fire(
        self,
        schedule_id: uuid.UUID,
        fired_slot: Optional[datetime],
    ) -> None:
        """Release the lock and move ``next_run_at`` to the next future instant.

        Called after every processed fire (dispatched, skipped, or errored) so a
        claimed schedule never stays locked and never immediately re-fires the
        same slot. Uses ``after=now`` (catch up once and advance).
        """
        schedule = await self.get(schedule_id)
        if schedule is None:
            return
        schedule.locked_by = None
        schedule.locked_at = None
        if fired_slot is not None:
            schedule.last_fired_slot = fired_slot
        if schedule.project_id is not None:
            project_result = await self.db.execute(
                select(Project.archived_at).where(Project.id == schedule.project_id)
            )
            if project_result.scalar_one_or_none() is not None:
                schedule.next_run_at = None
                await self.db.commit()
                return
        agent_result = await self.db.execute(
            select(JoySafeterAgent.archived_at, JoySafeterAgent.environment_ref).where(
                JoySafeterAgent.id == schedule.agent_id
            )
        )
        agent_row = agent_result.one_or_none()
        if agent_row is None or agent_row.archived_at is not None:
            schedule.next_run_at = None
            await self.db.commit()
            return
        environment_ref = schedule.environment_ref or agent_row.environment_ref
        if environment_ref:
            env = await EnvironmentService(self.db).get_environment_by_ref(
                environment_ref,
                project_id=schedule.project_id,
            )
            if env is None or env.archived_at is not None:
                schedule.next_run_at = None
                await self.db.commit()
                return
        if schedule.enabled:
            schedule.next_run_at = compute_next_run(schedule.cron_expr, schedule.timezone)
        await self.db.commit()

    async def release_claim(self, schedule_id: uuid.UUID) -> None:
        """Release a worker claim without marking the current cron slot handled."""
        schedule = await self.get(schedule_id)
        if schedule is None:
            return
        schedule.locked_by = None
        schedule.locked_at = None
        await self.db.commit()

    # --- Concurrency-policy support ---

    async def list_runs(
        self,
        schedule_id: uuid.UUID,
        *,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Optional[Sequence[JoySafeterTask]]:
        """Return execution history for a schedule after proving parent scope."""
        if project_id is not None and not await self.get(schedule_id, project_id=project_id):
            return None
        result = await self.db.execute(
            select(JoySafeterTask)
            .where(JoySafeterTask.schedule_id == schedule_id)
            .order_by(JoySafeterTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def get_active_tasks(
        self, schedule_id: uuid.UUID, project_id: Optional[str] = None
    ) -> Sequence[JoySafeterTask]:
        """Non-terminal tasks previously fired by this schedule.

        Concurrency-policy enforcement (FORBID/REPLACE in the scheduler loop)
        MUST call this with ``project_id=None`` so it sees every active run for
        the schedule. Passing a ``project_id`` scopes the lookup for API listing
        and returns an empty list on a scope miss — if a concurrency-policy
        caller ever passed a mismatched ``project_id`` it would silently see no
        active tasks and start a duplicate run instead of replacing/forbidding.
        """
        if project_id is not None and not await self.get(schedule_id, project_id=project_id):
            return []
        result = await self.db.execute(
            select(JoySafeterTask).where(
                JoySafeterTask.schedule_id == schedule_id,
                JoySafeterTask.status.in_(_NON_TERMINAL_STATUSES),
            )
        )
        return result.scalars().all()
