"""Shared task-submission orchestration.

Submitting an agent run is more than inserting a row: it enforces tenant
admission quotas, ensures a chat session in ``running`` state, persists the
task, emits the ``session.status_running`` event, hands the task to the Rust
orchestrator via the canonical enqueue, and compensates (task→failed,
session→idle) if the enqueue fails.

That sequence previously lived inline in the ``POST /tasks`` endpoint. It is
extracted here so the HTTP endpoint, the session follow-up path, and the cron
scheduler all submit through ONE definition and cannot drift from the enqueue
contract the orchestrator depends on.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.app_errors import (
    RateLimitExceededError,
    ResourceConflictError,
)
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.orchestrator_bridge.enqueue import enqueue_joysafeter_task

logger = logging.getLogger(__name__)


class TaskSubmissionService:
    """Orchestrates the full, quota-aware, session-aware task submission path."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tasks = JoySafeterTaskService(db)

    async def enforce_admission(
        self,
        *,
        project_id: Optional[str],
        user_id: Optional[str],
        enforce_user_quota: bool,
    ) -> None:
        """Per-project and per-user concurrent-task admission control.

        Mirrors the endpoint gate: a project cannot exceed its
        ``max_concurrent_tasks`` (or the global default), and a human principal
        cannot exceed the per-user cap. Raises ``RateLimitExceededError`` when a
        limit is hit. Soft limit — count-then-create can slightly over-admit
        under concurrency, acceptable for a fairness quota.
        """
        from app.joysafeter_shared.config.settings import settings

        if project_id is not None:
            project_result = await self.db.execute(
                select(Project.archived_at).where(Project.id == project_id)
            )
            archived_at = project_result.scalar_one_or_none()
            if archived_at is not None:
                raise ResourceConflictError(
                    code="PROJECT_ARCHIVED",
                    message="Project is archived and cannot create new tasks.",
                    data={"project_id": project_id},
                    user_action="refresh",
                )

            limit = await self.tasks.resolve_project_task_limit(
                project_id, default_limit=settings.max_concurrent_per_project
            )
            active = await self.tasks.count_active_tasks_for_project(project_id)
            if active >= limit:
                raise RateLimitExceededError(
                    code="PROJECT_TASK_LIMIT_EXCEEDED",
                    message=f"Project has reached its concurrent task limit ({limit}).",
                    data={"limit": limit, "active": active, "project_id": project_id},
                    source="api",
                    retryable=True,
                    user_action="retry",
                )

        if enforce_user_quota and user_id:
            user_limit = settings.max_concurrent_per_user
            user_active = await self.tasks.count_active_tasks_for_user(user_id)
            if user_active >= user_limit:
                raise RateLimitExceededError(
                    code="USER_TASK_LIMIT_EXCEEDED",
                    message=f"User has reached their concurrent task limit ({user_limit}).",
                    data={"limit": user_limit, "active": user_active, "user_id": user_id},
                    source="api",
                    retryable=True,
                    user_action="retry",
                )

    async def create_and_dispatch(
        self,
        *,
        agent_id: uuid.UUID,
        prompt: str,
        system_prompt: Optional[str],
        chat_session_id: uuid.UUID,
        session_svc: SessionService,
        timeout_sec: int,
        max_retries: int,
        project_id: Optional[str],
        user_id: Optional[str],
        org_id: Optional[str],
        idempotency_key: Optional[str],
        schedule_id: Optional[uuid.UUID] = None,
        auto_created_session_id: Optional[uuid.UUID] = None,
        enforce_admission: bool = True,
        enforce_user_quota: bool = True,
    ) -> Tuple[JoySafeterTask, bool]:
        """Persist the task, mark the session running, and enqueue it.

        Returns ``(task, created)``. ``created`` is False when an idempotent
        replay returned a pre-existing task (no side effects re-run). On enqueue
        failure the task is marked failed and the session compensated to idle,
        then an ``AppError`` is raised.
        """
        if idempotency_key:
            existing = await self.tasks.get_by_idempotency_key(idempotency_key, project_id=project_id)
            if existing is not None:
                return await self._return_idempotent_task(
                    existing,
                    chat_session_id=chat_session_id,
                    auto_created_session_id=auto_created_session_id,
                    session_svc=session_svc,
                )

        if enforce_admission:
            await self.enforce_admission(
                project_id=project_id,
                user_id=user_id,
                enforce_user_quota=enforce_user_quota,
            )

        task = await self.tasks.create_task(
            agent_id=agent_id,
            prompt=prompt,
            system_prompt=system_prompt,
            chat_session_id=chat_session_id,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            project_id=project_id,
            idempotency_key=idempotency_key,
            user_id=user_id,
            org_id=org_id,
            schedule_id=schedule_id,
        )

        created = bool(getattr(task, "_created_by_create_task", True))
        if not created:
            return await self._return_idempotent_task(
                task,
                chat_session_id=chat_session_id,
                auto_created_session_id=auto_created_session_id,
                session_svc=session_svc,
            )

        # Session-running CAS. A False result means another task grabbed this
        # session between the pre-flight check and now — a session conflict, NOT
        # an enqueue failure. Mark this never-dispatched task terminal (so the
        # repair sweep won't run it on the now-busy session) and surface a 409.
        running_accepted = await session_svc.update_session_status_for_task_event(
            chat_session_id, "running", task.id
        )
        if not running_accepted:
            await self.tasks.update_task_error(
                task.id,
                "Session already has another active task",
                JoySafeterTaskStatus.FAILED,
            )
            raise ResourceConflictError(
                code="SESSION_ACTIVE_TASK",
                message="Session has an active task; wait for completion before creating a new task",
                data={"session_id": str(chat_session_id), "task_id": str(task.id)},
                retryable=True,
                user_action="retry",
            )

        # The session now owns this task. Announcing it and pushing to the Redis
        # queue are best-effort fast-path steps: the DB is the source of truth and
        # the orchestrator's repair sweep re-dispatches any PENDING task whose
        # queue entry was lost. So a transient failure here must NOT destroy the
        # task — leave it PENDING (session stays running) for the sweep to pick up
        # on Redis recovery, rather than marking it FAILED.
        try:
            await session_svc.send_event(
                chat_session_id,
                "session.status_running",
                {"task_id": str(task.id)},
            )
            await enqueue_joysafeter_task(task.id)
        except Exception as exc:
            log_boundary_failure(
                logger,
                boundary="task_submission",
                code="TASK_ENQUEUE_DEFERRED",
                message="Task enqueue deferred to the repair sweep after a transient dispatch failure",
                operation="enqueue_task",
                error=exc,
                data={"task_id": str(task.id), "session_id": str(chat_session_id)},
                retryable=True,
                user_action="retry",
            )

        return task, True

    async def _return_idempotent_task(
        self,
        task: JoySafeterTask,
        *,
        chat_session_id: uuid.UUID,
        auto_created_session_id: Optional[uuid.UUID],
        session_svc: SessionService,
    ) -> Tuple[JoySafeterTask, bool]:
        # Idempotent replay: the key already produced a task. Drop the
        # session we auto-created for this attempt (if it isn't the one the
        # existing task uses) and return the existing task unchanged.
        if auto_created_session_id is not None and task.chat_session_id != auto_created_session_id:
            try:
                await session_svc.delete_session(auto_created_session_id)
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="task_submission",
                    code="TASK_IDEMPOTENCY_ORPHAN_SESSION_DELETE_FAILED",
                    message="Failed to delete orphan idempotency session",
                    operation="delete_orphan_idempotency_session",
                    error=exc,
                    data={"session_id": str(auto_created_session_id), "task_id": str(task.id)},
                )
        elif auto_created_session_id is None and task.chat_session_id != chat_session_id:
            raise ResourceConflictError(
                code="TASK_IDEMPOTENCY_KEY_MISMATCH",
                message="Idempotency-Key was already used for a different session",
                data={
                    "task_id": str(task.id),
                    "conflict_field": "chat_session_id",
                    "requested_value": str(chat_session_id),
                    "existing_value": str(task.chat_session_id),
                },
                user_action="fix_input",
            )
        return task, False
