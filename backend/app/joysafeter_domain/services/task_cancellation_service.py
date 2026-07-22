"""Shared task cancellation: DB state-machine transition + real orchestrator relay.

Single source of truth for "cancel a task AND actually stop the run". Both the
HTTP ``POST /tasks/{id}/cancel`` endpoint and the scheduler's ``replace``
concurrency policy go through here, so the two paths can never drift.

The critical invariant: a task marked ``CANCELLED`` in Postgres must be
accompanied by the Redis ``cancel`` command that the Rust orchestrator's command
listener consumes to call ``request_cancel()`` on the sandbox actually running
it. Flipping only the DB row (the previous scheduler behaviour) left the run
executing to completion — a cosmetic cancel. This service guarantees both halves
happen together.

Runtime command relay goes through the shared orchestrator bridge. This keeps
the cancellation boundary usable from both API and worker/scheduler code without
pulling the API layer into the domain service.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_session import SessionStatus
from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.app_errors import ConflictError, ServiceUnavailableError
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.orchestrator_bridge.runtime_commands import relay_sandbox_command_via_redis

logger = logging.getLogger(__name__)


class TaskCancellationService:
    """Cancel a task everywhere it matters: DB state machine + running sandbox."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _resolve_sandbox_id(self, task: Any) -> Any | None:
        sandbox_id = getattr(task, "sandbox_id", None)
        if not sandbox_id and getattr(task, "chat_session_id", None):
            sandbox = await SandboxService(self.db).find_by_session(task.chat_session_id)
            sandbox_id = sandbox.id if sandbox else None
        return sandbox_id

    async def _relay_cancel_to_sandbox(self, task: Any, sandbox_id: Any, *, reason: str) -> bool:
        task_id = getattr(task, "id")
        session_id = getattr(task, "chat_session_id", None)
        return await relay_sandbox_command_via_redis(
            sandbox_id,
            command_type="cancel",
            reason=reason,
            boundary="task_api",
            operation="cancel_task_relay_runner",
            failure_code="TASK_CANCEL_REDIS_RELAY_FAILED",
            failure_message="Task cancel Redis relay failed",
            data={
                "task_id": str(task_id),
                "session_id": str(session_id or ""),
            },
        )

    async def relay_cancel(self, task: Any, *, reason: str) -> bool:
        """Publish the Redis ``cancel`` command to the sandbox running *task*.

        Returns ``True`` when a cancel command was relayed, ``False`` when the
        task has no sandbox yet (still pending) — such a task is stopped purely
        by its DB state transition, so no relay is needed.
        """
        sandbox_id = await self._resolve_sandbox_id(task)
        if not sandbox_id:
            return False
        return await self._relay_cancel_to_sandbox(task, sandbox_id, reason=reason)

    async def cancel(self, task: Any, *, reason: str) -> bool:
        """Transition *task* to CANCELLED and relay the real cancel to its runner.

        Cancellation is asynchronous — the running sandbox stops shortly after the
        relayed command is consumed, not synchronously. Callers that need to start
        a replacement run should do so immediately after this returns and accept a
        brief overlap; the lease/watchdog and epoch fencing keep the two runs from
        corrupting each other's terminal state.
        """
        task_id = getattr(task, "id")
        session_id = getattr(task, "chat_session_id", None)
        observed_task_sandbox_id = getattr(task, "sandbox_id", None)
        observed_owner_epoch = getattr(task, "owner_epoch", None)
        sandbox_id = await self._resolve_sandbox_id(task)
        task_svc = JoySafeterTaskService(self.db)
        if sandbox_id:
            relayed = await self._relay_cancel_to_sandbox(task, sandbox_id, reason=reason)
            if not relayed:
                raise ServiceUnavailableError(
                    code="TASK_CANCEL_REDIS_RELAY_FAILED",
                    message="Failed to cancel task in sandbox runtime.",
                    data={
                        "task_id": str(task_id),
                        "session_id": str(session_id or ""),
                        "sandbox_id": str(sandbox_id),
                    },
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                )
            try:
                cancelled = await task_svc.cancel_task_if_owner_matches(
                    task_id,
                    expected_sandbox_id=observed_task_sandbox_id,
                    expected_owner_epoch=observed_owner_epoch,
                )
            except ValueError:
                raise
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="task_cancellation",
                    code="TASK_CANCEL_STATE_SYNC_FAILED",
                    message="Failed to finalize task cancel after runtime ACK",
                    operation="cancel_task_finalize_after_runtime_ack",
                    error=exc,
                    data={"task_id": str(task_id), "session_id": str(session_id or ""), "sandbox_id": str(sandbox_id)},
                )
                await self.db.rollback()
                raise ServiceUnavailableError(
                    code="TASK_CANCEL_STATE_SYNC_FAILED",
                    message="Task cancel could not be finalized because task ownership changed.",
                    data={"task_id": str(task_id), "session_id": str(session_id or ""), "sandbox_id": str(sandbox_id)},
                    source="api",
                    retryable=True,
                    user_action="refresh",
                ) from None
            if not cancelled:
                raise ServiceUnavailableError(
                    code="TASK_CANCEL_STATE_SYNC_FAILED",
                    message="Task cancel could not be finalized because task ownership changed.",
                    data={"task_id": str(task_id), "session_id": str(session_id or ""), "sandbox_id": str(sandbox_id)},
                    source="api",
                    retryable=True,
                    user_action="refresh",
                )
        else:
            await task_svc.cancel_task(task_id)
        await self._mark_session_idle_after_cancel(task_id=task_id, session_id=session_id)
        return bool(sandbox_id)

    async def _mark_session_idle_after_cancel(self, *, task_id: Any, session_id: Any | None) -> bool:
        if not session_id:
            return False

        session_svc = SessionService(self.db)
        stop_reason = {"type": "cancelled"}
        try:
            session_idle_updated = await session_svc.update_session_status_for_task_event(
                session_id,
                SessionStatus.IDLE.value,
                task_id,
                stop_reason=stop_reason,
            )
        except ConflictError:
            logger.debug(
                "Ignoring stale session idle transition while cancelling task %s for session %s",
                task_id,
                session_id,
                exc_info=True,
            )
            return False
        except Exception as exc:
            log_boundary_failure(
                logger,
                boundary="task_cancellation",
                code="TASK_CANCEL_SESSION_IDLE_MARK_FAILED",
                message="Failed to mark session idle after cancelling task",
                operation="cancel_task_mark_session_idle",
                error=exc,
                data={"session_id": str(session_id), "task_id": str(task_id)},
            )
            await self.db.rollback()
            raise ServiceUnavailableError(
                code="TASK_CANCEL_SESSION_SYNC_FAILED",
                message="Task was cancelled, but failed to mark the linked session idle.",
                data={"task_id": str(task_id), "session_id": str(session_id)},
                source="api",
                retryable=True,
                user_action="refresh",
            ) from None

        if session_idle_updated:
            try:
                await session_svc.send_event(
                    session_id,
                    "session.status_idle",
                    {"task_id": str(task_id), "stop_reason": stop_reason},
                )
            except Exception:
                logger.debug("Failed to persist cancel idle event for session %s", session_id, exc_info=True)

        return bool(session_idle_updated)
