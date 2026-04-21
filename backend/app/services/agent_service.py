"""
AgentService — manages Agent lifecycle.
"""

from __future__ import annotations

import re
import uuid
from typing import List

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ConflictException, NotFoundException
from app.models.agent import Agent, AgentVersion
from app.repositories.agent import AgentRepository, AgentVersionRepository
from app.schemas.agent import CreateAgentRequest, UpdateAgentRequest


def _generate_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", name.lower())
    slug = re.sub(r"[\s]+", "-", slug).strip("-")
    return slug or "agent"


class AgentService:
    """Manages the Agent entity and its initial version."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.agent_repo = AgentRepository(db)
        self.version_repo = AgentVersionRepository(db)

    async def list_agents(self, workspace_id: uuid.UUID) -> List[Agent]:
        return await self.agent_repo.list_by_workspace(workspace_id)

    async def get_agent(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        return agent

    async def create_agent(
        self,
        workspace_id: uuid.UUID,
        user_id: str,
        data: CreateAgentRequest,
    ) -> Agent:
        slug = _generate_slug(data.name)

        # Check uniqueness within workspace
        existing = await self.agent_repo.get_by_workspace_and_slug(workspace_id, slug)
        if existing:
            raise ConflictException(f"Agent with slug '{slug}' already exists in this workspace")

        # Create the Agent
        agent = await self.agent_repo.create(
            {
                "workspace_id": workspace_id,
                "name": data.name,
                "slug": slug,
                "description": data.description,
                "avatar": data.avatar,
                "status": "draft",
                "created_by": user_id,
            }
        )

        # Create an initial draft AgentVersion (v1)
        version = await self.version_repo.create(
            {
                "agent_id": agent.id,
                "version_number": 1,
                "status": "draft",
                "source_kind": "manual",
                "definition_kind": data.definition_kind,
                "definition_payload": data.definition_payload or {},
                "capability_manifest": data.capability_manifest or {},
                "created_by": user_id,
            }
        )

        # Link the draft version
        await self.agent_repo.update(agent.id, {"current_draft_version_id": version.id})

        logger.info(f"Created agent {agent.id} ({data.name}) with initial version {version.id}")
        return agent

    async def update_agent(
        self,
        agent_id: uuid.UUID,
        data: UpdateAgentRequest,
    ) -> Agent:
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return agent

        updated = await self.agent_repo.update(agent_id, update_data)
        assert updated is not None
        return updated

    async def archive_agent(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        updated = await self.agent_repo.update(agent_id, {"status": "archived"})
        assert updated is not None
        logger.info(f"Archived agent {agent_id}")
        return updated
