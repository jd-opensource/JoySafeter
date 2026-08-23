from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.ids import AgentId


class AgentTriggerLifecycleAdapter:
    def __init__(self, db: AsyncSession) -> None:
        self._service = JoySafeterTriggerService(db)

    async def lock_for_agent_lifecycle(
        self,
        agent_id: AgentId,
        *,
        project_id: Optional[str] = None,
    ) -> Sequence[JoySafeterTrigger]:
        return await self._service.lock_for_agent_lifecycle(agent_id, project_id=project_id)

    def pause_locked_agent_triggers(self, triggers: Sequence[JoySafeterTrigger]) -> None:
        self._service.pause_locked_agent_triggers(triggers)

    async def resume_locked_agent_triggers(self, triggers: Sequence[JoySafeterTrigger]) -> None:
        await self._service.resume_locked_agent_triggers(triggers)


__all__ = ["AgentTriggerLifecycleAdapter"]
