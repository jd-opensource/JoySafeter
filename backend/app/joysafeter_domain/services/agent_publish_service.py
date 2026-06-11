"""
AgentPublishService — high-level publish/rollback/retire orchestration.

All sub-service calls share the same AsyncSession. Only this service
calls commit — sub-services only flush.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError
from app.joysafeter_domain.contracts.agent import infer_runtime_kind
from app.joysafeter_domain.models.agent import AgentVersion
from app.joysafeter_domain.repositories.agent import AgentRepository, AgentVersionRepository
from app.joysafeter_domain.schemas.agent_release import CreateAgentReleaseRequest
from app.joysafeter_domain.services.agent_release_service import AgentReleaseService
from app.joysafeter_domain.services.agent_version_service import AgentVersionService

from .base import BaseService


class AgentPublishService(BaseService):
    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.version_svc = AgentVersionService(db)
        self.release_svc = AgentReleaseService(db)
        self.agent_repo = AgentRepository(db)
        self.version_repo = AgentVersionRepository(db)

    async def publish(self, agent_id: uuid.UUID, user_id: str) -> dict:
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})

        version = await self._resolve_current_draft(agent)

        if version.status == "draft":
            await self.version_svc.freeze_version(version.id)

        runtime_kind = infer_runtime_kind(version.engine_kind)
        release_data = CreateAgentReleaseRequest(
            agent_version_id=version.id,
            runtime_kind=runtime_kind,  # type: ignore[arg-type]
            runtime_binding={},
        )
        release = await self.release_svc.publish_release(agent_id, user_id, release_data)

        await self.release_svc.activate_release(agent_id, release.id)

        # Fork a fresh draft so the editor has a writable version after publish.
        await self.version_svc.fork_draft_from(version, user_id)

        await self.safe_commit()
        reloaded_agent = await self.agent_repo.get(
            agent_id,
            relations=["current_draft_version", "active_release"],
        )
        return {"agent": reloaded_agent or agent, "release": release}

    async def rollback(self, agent_id: uuid.UUID, release_id: uuid.UUID) -> dict:  # type: ignore[override]
        await self.release_svc.activate_release(agent_id, release_id)
        await self.safe_commit()
        agent = await self.agent_repo.get(
            agent_id,
            relations=["current_draft_version", "active_release"],
        )
        return {"agent": agent}

    async def unpublish(self, agent_id: uuid.UUID) -> dict:
        release = await self.release_svc.unpublish_release(agent_id)
        await self.safe_commit()
        agent = await self.agent_repo.get(
            agent_id,
            relations=["current_draft_version", "active_release"],
        )
        return {"agent": agent, "release": release}

    async def retire(self, agent_id: uuid.UUID, release_id: uuid.UUID) -> dict:
        release = await self.release_svc.retire_release(agent_id, release_id)
        await self.safe_commit()
        return {"release": release}

    async def _resolve_current_draft(self, agent) -> AgentVersion:
        if not agent.current_draft_version_id:
            raise InvalidRequestError("Agent has no draft version", code="AGENT_DRAFT_VERSION_MISSING")
        version = await self.version_repo.get(agent.current_draft_version_id)
        if not version:
            raise NotFoundError(
                "Draft version not found",
                code="AGENT_DRAFT_VERSION_NOT_FOUND",
                data={"version_id": str(agent.current_draft_version_id)},
            )
        return version
