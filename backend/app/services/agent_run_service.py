"""
AgentRunService — read-only queries for AgentRun entities.

All mutations (create / cancel / retry) go through ExecutionOrchestrator
which publishes events through the EventBus.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.models.agent_run import AgentRun
from app.repositories.agent_run import AgentRunRepository


class AgentRunService:
    """Read-only queries for AgentRun entities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.run_repo = AgentRunRepository(db)

    async def list_runs(
        self,
        workspace_id: Optional[uuid.UUID] = None,
        release_id: Optional[uuid.UUID] = None,
        task_id: Optional[uuid.UUID] = None,
        agent_id: Optional[uuid.UUID] = None,
        trigger_source: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[AgentRun]:
        """List runs filtered by parameters."""
        if agent_id:
            if not workspace_id:
                raise BadRequestException("workspace_id is required when filtering by agent_id")
            return await self.run_repo.find_by_agent_and_trigger(
                agent_id=agent_id,
                workspace_id=workspace_id,
                trigger_source=trigger_source,
                status=status,
            )
        elif task_id:
            if not workspace_id:
                raise BadRequestException("workspace_id is required when filtering by task_id")
            return await self.run_repo.list_by_task(task_id, workspace_id)
        elif release_id:
            if not workspace_id:
                raise BadRequestException("workspace_id is required when filtering by release_id")
            return await self.run_repo.list_by_release(release_id, workspace_id)
        elif workspace_id:
            return await self.run_repo.list_by_workspace(workspace_id)
        else:
            raise BadRequestException("Must provide workspace_id, release_id, task_id, or agent_id")

    async def get_run(self, run_id: uuid.UUID) -> AgentRun:
        """Get a run by ID."""
        run = await self.run_repo.get(run_id)
        if not run:
            raise NotFoundException(f"AgentRun {run_id} not found")
        return run

