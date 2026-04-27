"""
AgentService — manages Agent lifecycle.
"""

from __future__ import annotations

import re
import uuid
from typing import List

from loguru import logger
from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import ResourceConflictError, NotFoundError
from app.core.model.utils import encrypt_credentials
from app.models.agent import Agent, AgentRelease, AgentVersion
from app.models.agent_run import AgentRun
from app.models.execution import Artifact, Execution, ExecutionEvent
from app.models.task import Task
from app.models.thread import Thread
from app.repositories.agent import AgentRepository, AgentVersionRepository
from app.schemas.agent import CreateAgentRequest, UpdateAgentRequest


from .base import BaseService


def _generate_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", name.lower())
    slug = re.sub(r"[\s]+", "-", slug).strip("-")
    return slug or "agent"


class AgentService(BaseService):
    """Manages the Agent entity and its initial version."""

    RESPONSE_RELATIONS = ["current_draft_version", "active_release"]

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.agent_repo = AgentRepository(db)
        self.version_repo = AgentVersionRepository(db)

    async def list_agents(self, workspace_id: uuid.UUID) -> List[Agent]:
        return await self.agent_repo.list_by_workspace(workspace_id)

    async def get_agent(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.agent_repo.get(
            agent_id,
            relations=self.RESPONSE_RELATIONS,
        )
        if not agent:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})
        return agent

    async def create_agent(
        self,
        workspace_id: uuid.UUID,
        user_id: str,
        data: CreateAgentRequest,
    ) -> Agent:
        base_slug = _generate_slug(data.name)
        slug = base_slug
        suffix = 1
        while await self.agent_repo.get_by_workspace_and_slug(workspace_id, slug):
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        # Create the Agent
        create_data = {
            "workspace_id": workspace_id,
            "name": data.name,
            "slug": slug,
            "description": data.description,
            "avatar": data.avatar,
            "status": "draft",
            "created_by": user_id,
        }
        if data.custom_env:
            create_data["encrypted_custom_env"] = encrypt_credentials(data.custom_env)

        agent = await self.agent_repo.create(create_data)

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

        await self.commit()
        reloaded = await self.agent_repo.get(agent.id, relations=self.RESPONSE_RELATIONS)
        assert reloaded is not None
        logger.info(f"Created agent {agent.id} ({data.name}) with initial version {version.id}")
        return reloaded

    async def update_agent(
        self,
        agent_id: uuid.UUID,
        data: UpdateAgentRequest,
    ) -> Agent:
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return agent

        if "custom_env" in update_data:
            raw = update_data.pop("custom_env")
            if raw:
                update_data["encrypted_custom_env"] = encrypt_credentials(raw)
            else:
                update_data["encrypted_custom_env"] = None

        updated = await self.agent_repo.update(agent_id, update_data)
        assert updated is not None
        await self.commit()
        reloaded = await self.agent_repo.get(agent_id, relations=self.RESPONSE_RELATIONS)
        assert reloaded is not None
        return reloaded

    async def delete_agent(self, agent_id: uuid.UUID) -> None:
        """Delete an agent and all dependent records.

        FK dependency chain: Agent → Versions → Releases → Runs → Executions → Events/Artifacts.
        Self-referencing FKs (agent.current_draft_version_id, agent.active_release_id,
        runs.current_execution_id, executions.parent_execution_id) must be nullified
        before their targets are deleted.
        """
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})

        db = self.db

        has_tasks = (await db.execute(
            select(exists().where(Task.agent_id == agent_id))
        )).scalar()
        if has_tasks:
            raise ResourceConflictError(
                "Cannot delete agent: tasks still reference it",
                code="AGENT_DELETE_TASK_REFERENCE_CONFLICT",
                data={"agent_id": str(agent_id)},
            )

        version_ids = (await db.execute(
            select(AgentVersion.id).where(AgentVersion.agent_id == agent_id)
        )).scalars().all()

        release_ids = (await db.execute(
            select(AgentRelease.id).where(AgentRelease.agent_version_id.in_(version_ids))
        )).scalars().all() if version_ids else []

        release_run_ids = (await db.execute(
            select(AgentRun.id).where(AgentRun.release_id.in_(release_ids))
        )).scalars().all() if release_ids else []

        draft_run_ids = (await db.execute(
            select(AgentRun.id).where(AgentRun.agent_version_id.in_(version_ids))
        )).scalars().all() if version_ids else []

        run_ids = list(dict.fromkeys([*release_run_ids, *draft_run_ids]))

        exec_ids = (await db.execute(
            select(Execution.id).where(Execution.run_id.in_(run_ids))
        )).scalars().all() if run_ids else []

        if exec_ids:
            await db.execute(delete(ExecutionEvent).where(ExecutionEvent.execution_id.in_(exec_ids)))
            await db.execute(delete(Artifact).where(Artifact.execution_id.in_(exec_ids)))
            await db.execute(update(Execution).where(Execution.parent_execution_id.in_(exec_ids)).values(parent_execution_id=None))

        if run_ids:
            await db.execute(update(AgentRun).where(AgentRun.id.in_(run_ids)).values(current_execution_id=None, thread_id=None))

        if exec_ids:
            await db.execute(delete(Execution).where(Execution.id.in_(exec_ids)))

        if run_ids:
            await db.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))

        await db.execute(delete(Thread).where(Thread.agent_id == agent_id))

        await db.execute(
            update(Agent).where(Agent.id == agent_id).values(
                current_draft_version_id=None,
                active_release_id=None,
            )
        )

        if release_ids:
            await db.execute(delete(AgentRelease).where(AgentRelease.id.in_(release_ids)))

        if version_ids:
            await db.execute(delete(AgentVersion).where(AgentVersion.id.in_(version_ids)))

        await db.execute(delete(Agent).where(Agent.id == agent_id))

        await self.commit()
        logger.info(f"Deleted agent {agent_id} and all related records")
