from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Optional, TypeVar

from app.joysafeter_application.agents.ports import (
    AgentRuntimePort,
    AgentTriggerLifecyclePort,
    AgentUnitOfWork,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_shared.common.app_errors import ResourceConflictError, ServiceUnavailableError
from app.joysafeter_shared.ids import AgentId, SessionId
from app.joysafeter_shared.utils.datetime import utc_now

logger = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")


class AgentLifecycleService:
    def __init__(
        self,
        uow: AgentUnitOfWork,
        runtime: AgentRuntimePort,
        triggers: AgentTriggerLifecyclePort,
    ) -> None:
        self._uow = uow
        self._repository = uow.agents
        self._runtime = runtime
        self._triggers = triggers

    async def _run_transaction(self, operation: Callable[[], Awaitable[_ResultT]]) -> _ResultT:
        try:
            result = await operation()
            await self._uow.commit()
            return result
        except Exception:
            await self._uow.rollback()
            raise

    async def _lock_lifecycle_aggregate(
        self,
        agent_id: AgentId,
        *,
        project_id: Optional[str],
        all_trigger_projects: bool = False,
    ) -> tuple[list[JoySafeterTrigger], Optional[JoySafeterAgent]]:
        trigger_project_id = None if all_trigger_projects else project_id
        triggers = list(await self._triggers.lock_for_agent_lifecycle(agent_id, project_id=trigger_project_id))
        agent = await self._repository.lock(agent_id, project_id=project_id)
        return triggers, agent

    async def delete_agent(
        self,
        agent_id: AgentId,
        force: bool = False,
        project_id: Optional[str] = None,
    ) -> bool:
        return await self._run_transaction(lambda: self._delete_agent(agent_id, force=force, project_id=project_id))

    async def _delete_agent(
        self,
        agent_id: AgentId,
        force: bool = False,
        project_id: Optional[str] = None,
    ) -> bool:
        triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
        )
        if agent is None:
            return False
        if not force and await self._repository.count_active_tasks(agent_id, project_id=project_id) > 0:
            raise ValueError("Agent has active tasks. Use force=true to delete.")
        self._triggers.pause_locked_agent_triggers(triggers)
        agent.deleted_at = utc_now()
        return True

    async def archive_agent_with_sessions(
        self, agent_id: AgentId, project_id: Optional[str] = None
    ) -> tuple[bool, list[SessionId]]:
        return await self._run_transaction(lambda: self._archive_agent_with_sessions(agent_id, project_id=project_id))

    async def _archive_agent_with_sessions(
        self, agent_id: AgentId, project_id: Optional[str] = None
    ) -> tuple[bool, list[SessionId]]:
        triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
        )
        if agent is None:
            return False, []
        if agent.archived_at:
            return True, []
        if await self._repository.count_active_tasks(agent_id, project_id=project_id) > 0:
            raise ValueError("Agent has active tasks. Stop or cancel them before archiving sessions.")
        session_ids = await self._repository.list_non_archived_session_ids(agent_id)
        now = utc_now()
        if not await self._repository.archive_sessions_if_no_active_tasks(session_ids, now):
            raise ValueError("Agent has active tasks. Stop or cancel them before archiving sessions.")
        self._triggers.pause_locked_agent_triggers(triggers)
        agent.archived_at = now
        agent.updated_at = now
        return True, session_ids

    async def restore_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> bool:
        return await self._run_transaction(lambda: self._restore_agent(agent_id, project_id=project_id))

    async def _restore_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> bool:
        triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
        )
        if agent is None:
            return False
        if agent.archived_at is None:
            return True
        now = utc_now()
        agent.archived_at = None
        agent.updated_at = now
        await self._repository.flush()
        await self._triggers.resume_locked_agent_triggers(triggers)
        return True

    async def hard_delete_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> bool:
        return await self._run_transaction(lambda: self._hard_delete_agent(agent_id, project_id=project_id))

    async def _hard_delete_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> bool:
        _triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
            all_trigger_projects=True,
        )
        if agent is None:
            return False
        if await self._repository.count_active_tasks(agent_id, project_id=project_id) > 0:
            raise ValueError("Agent has active tasks. Cancel them before hard delete.")
        await self._repository.hard_delete_owned_rows(agent_id)
        return True

    async def archive_sessions_for_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> list[SessionId]:
        return await self._run_transaction(lambda: self._archive_sessions_for_agent(agent_id, project_id=project_id))

    async def _archive_sessions_for_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> list[SessionId]:
        _triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
        )
        if agent is None:
            return []
        if await self._repository.count_active_tasks(agent_id, project_id=project_id) > 0:
            raise ValueError("Agent has active tasks. Stop or cancel them before archiving sessions.")
        session_ids = await self._repository.list_non_archived_session_ids(agent_id)
        if session_ids:
            if not await self._repository.archive_sessions_if_no_active_tasks(session_ids, utc_now()):
                raise ValueError("Agent has active tasks. Stop or cancel them before archiving sessions.")
        return session_ids

    async def _cancel_active_tasks(self, agent_id: AgentId, *, project_id: Optional[str]) -> None:
        active_tasks = await self._repository.list_active_tasks(agent_id, project_id=project_id)
        cancelled = 0
        for task in active_tasks:
            try:
                await self._runtime.cancel_task(task, reason="Agent deleted")
                cancelled += 1
            except ServiceUnavailableError as exc:
                if exc.code == "TASK_CANCEL_REDIS_RELAY_FAILED":
                    sandbox_id = (exc.data or {}).get("sandbox_id") or str(getattr(task, "sandbox_id", ""))
                    raise ServiceUnavailableError(
                        code="AGENT_REDIS_CANCEL_RELAY_FAILED",
                        message="Failed to cancel agent task in sandbox runtime.",
                        data={"agent_id": str(agent_id), "task_id": str(task.id), "sandbox_id": str(sandbox_id)},
                        source="runtime",
                        retryable=True,
                        user_action="retry",
                    ) from exc
                logger.debug("Failed to cancel task %s during agent force delete", task.id, exc_info=True)
            except Exception:
                logger.debug("Failed to cancel task %s during agent force delete", task.id, exc_info=True)
        remaining = await self._repository.list_active_tasks(agent_id, project_id=project_id)
        if remaining:
            raise ServiceUnavailableError(
                code="AGENT_FORCE_CANCEL_ACTIVE_TASKS_FAILED",
                message="Failed to cancel all active tasks for agent",
                data={"agent_id": str(agent_id), "active_task_ids": [str(task.id) for task in remaining]},
                source="runtime",
                retryable=True,
                user_action="retry",
            )
        try:
            await self._archive_sessions_for_agent(agent_id, project_id=project_id)
        except Exception as exc:
            raise ServiceUnavailableError(
                code="AGENT_SESSION_ARCHIVE_FAILED",
                message="Failed to archive sessions during agent cleanup.",
                data={"agent_id": str(agent_id)},
                source="api",
                retryable=True,
                user_action="retry",
            ) from exc
        if cancelled:
            logger.info("Cancelled %d active tasks for agent %s", cancelled, agent_id)

    async def delete_with_cleanup(
        self,
        agent_id: AgentId,
        *,
        force: bool,
        project_id: Optional[str],
    ) -> bool:
        return await self._run_transaction(
            lambda: self._delete_with_cleanup(agent_id, force=force, project_id=project_id)
        )

    async def _delete_with_cleanup(
        self,
        agent_id: AgentId,
        *,
        force: bool,
        project_id: Optional[str],
    ) -> bool:
        agent = await self._repository.get(agent_id, project_id=project_id)
        if agent is None:
            return False
        if not force:
            active_tasks = await self._repository.list_active_tasks(agent_id, project_id=project_id)
            if active_tasks:
                raise ResourceConflictError(
                    code="AGENT_ACTIVE_TASKS",
                    message="Agent has active tasks (pending/running). Use ?force=true to force delete.",
                    data={"agent_id": str(agent_id), "active_task_ids": [str(task.id) for task in active_tasks]},
                    retryable=True,
                    user_action="retry",
                )
            await self._runtime.destroy_sandboxes(agent_id, reason="Agent deleted", project_id=project_id)
            try:
                deleted = await self._hard_delete_agent(agent_id, project_id=project_id)
            except ValueError as exc:
                raise ResourceConflictError(
                    code="AGENT_ACTIVE_TASKS",
                    message=str(exc),
                    data={"agent_id": str(agent_id)},
                    retryable=True,
                    user_action="retry",
                ) from exc
        else:
            await self._cancel_active_tasks(agent_id, project_id=project_id)
            await self._runtime.destroy_sandboxes(agent_id, reason="Agent force deleted", project_id=project_id)
            try:
                deleted = await self._hard_delete_agent(agent_id, project_id=project_id)
            except ValueError as exc:
                raise ServiceUnavailableError(
                    code="AGENT_FORCE_DELETE_ACTIVE_TASKS_REMAIN",
                    message=str(exc),
                    data={"agent_id": str(agent_id)},
                    retryable=True,
                    user_action="refresh",
                ) from exc
        if deleted:
            await self._runtime.cleanup_identity(agent_id)
        return deleted
