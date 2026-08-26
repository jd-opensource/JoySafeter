from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService
from app.joysafeter_domain.services.task_cancellation_service import TaskCancellationService
from app.joysafeter_identity.service import cleanup_agent_identity
from app.joysafeter_shared.common.app_errors import ServiceUnavailableError
from app.joysafeter_shared.ids import AgentId, ProjectId
from app.joysafeter_shared.orchestrator_bridge.runtime_commands import relay_sandbox_destroy_via_redis


class AgentRuntimeAdapter:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def cancel_task(self, task: JoySafeterTask, *, reason: str) -> None:
        await TaskCancellationService(self._db).cancel(task, reason=reason)

    async def destroy_sandboxes(
        self,
        agent_id: AgentId,
        *,
        reason: str,
        project_id: ProjectId | None = None,
    ) -> None:
        sandbox_service = SandboxService(self._db)
        sandboxes = await sandbox_service.list_active_for_agent(agent_id, project_id=project_id)
        for sandbox in sandboxes:
            expected_external_id = str(sandbox.external_id or "") or None
            relayed = await relay_sandbox_destroy_via_redis(
                sandbox.id,
                boundary="agent_application",
                operation="delete_agent_destroy_sandbox",
                failure_code="AGENT_SANDBOX_DESTROY_FAILED",
                failure_message="Redis sandbox destroy relay failed during agent delete",
                reason=reason,
                external_id=expected_external_id,
                data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
            )
            if not relayed:
                raise ServiceUnavailableError(
                    code="AGENT_SANDBOX_DESTROY_FAILED",
                    message="Agent could not be deleted because sandbox cleanup failed.",
                    data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                )
            try:
                destroyed = await sandbox_service.mark_destroyed_after_runtime_ack(
                    sandbox.id,
                    sandbox.status,
                    expected_external_id,
                )
            except Exception as exc:
                raise ServiceUnavailableError(
                    code="AGENT_SANDBOX_STATE_SYNC_FAILED",
                    message="Agent could not be deleted because sandbox state sync failed.",
                    data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
                    source="api",
                    retryable=True,
                    user_action="retry",
                ) from exc
            if not destroyed:
                raise ServiceUnavailableError(
                    code="AGENT_SANDBOX_STATE_SYNC_FAILED",
                    message="Agent could not be deleted because sandbox state sync failed.",
                    data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
                    source="api",
                    retryable=True,
                    user_action="retry",
                )

    async def cleanup_identity(self, agent_id: AgentId) -> None:
        await cleanup_agent_identity(agent_id)
