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

API-layer collaborators (``SandboxService``, ``relay_sandbox_command_via_redis``)
are imported lazily inside the methods — matching the existing convention in
``joysafeter_api.api.v1.tasks`` — so importing this domain module never pulls in
the API layer at import time.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_shared.common.app_errors import ServiceUnavailableError


class TaskCancellationService:
    """Cancel a task everywhere it matters: DB state machine + running sandbox."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _resolve_sandbox_id(self, task: Any) -> Any | None:
        sandbox_id = getattr(task, "sandbox_id", None)
        if not sandbox_id and getattr(task, "chat_session_id", None):
            from app.joysafeter_api.services import SandboxService

            sandbox = await SandboxService(self.db).find_by_session(task.chat_session_id)
            sandbox_id = sandbox.id if sandbox else None
        return sandbox_id

    async def _relay_cancel_to_sandbox(self, task: Any, sandbox_id: Any, *, reason: str) -> bool:
        from app.joysafeter_api.runtime_commands import relay_sandbox_command_via_redis

        return await relay_sandbox_command_via_redis(
            sandbox_id,
            command_type="cancel",
            reason=reason,
            boundary="task_api",
            operation="cancel_task_relay_runner",
            failure_code="TASK_CANCEL_REDIS_RELAY_FAILED",
            failure_message="Task cancel Redis relay failed",
            data={
                "task_id": str(task.id),
                "session_id": str(getattr(task, "chat_session_id", "") or ""),
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
        sandbox_id = await self._resolve_sandbox_id(task)
        if sandbox_id:
            relayed = await self._relay_cancel_to_sandbox(task, sandbox_id, reason=reason)
            if not relayed:
                raise ServiceUnavailableError(
                    code="TASK_CANCEL_REDIS_RELAY_FAILED",
                    message="Failed to cancel task in sandbox runtime.",
                    data={
                        "task_id": str(task.id),
                        "session_id": str(getattr(task, "chat_session_id", "") or ""),
                        "sandbox_id": str(sandbox_id),
                    },
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                )
        await JoySafeterTaskService(self.db).cancel_task(task.id)
        return bool(sandbox_id)
