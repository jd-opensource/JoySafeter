"""
AgentRunService — read-only queries for AgentRun entities.

All mutations (create / cancel / retry) go through ExecutionOrchestrator
which publishes events through the EventBus.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError
from app.joysafeter_domain.models.agent_run import AgentRun
from app.joysafeter_domain.repositories.agent_run import AgentRunRepository


class AgentRunService:
    """Read-only queries for AgentRun entities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.run_repo = AgentRunRepository(db)

    async def list_runs(
        self,
        project_id: Optional[str] = None,
        release_id: Optional[uuid.UUID] = None,
        task_id: Optional[uuid.UUID] = None,
        agent_id: Optional[uuid.UUID] = None,
        trigger_medium: Optional[str] = None,
        run_purpose: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[AgentRun]:
        """List runs filtered by parameters."""
        if agent_id:
            if not project_id:
                raise InvalidRequestError(
                    "project_id is required when filtering by agent_id",
                    code="AGENT_RUN_PROJECT_REQUIRED",
                    data={"filter": "agent_id"},
                )
            return await self.run_repo.find_by_agent_and_project(
                agent_id=agent_id,
                project_id=project_id,
                trigger_medium=trigger_medium,
                run_purpose=run_purpose,
                status=status,
            )
        elif task_id:
            return await self.run_repo.list_by_task_and_project(task_id, project_id)
        elif release_id:
            return await self.run_repo.list_by_release_and_project(release_id, project_id)
        elif project_id:
            return await self.run_repo.list_by_project(project_id)
        else:
            raise InvalidRequestError(
                "Must provide project_id, release_id, task_id, or agent_id",
                code="AGENT_RUN_FILTER_REQUIRED",
            )

    async def get_run(self, run_id: uuid.UUID) -> AgentRun:
        """Get a run by ID."""
        run = await self.run_repo.get(run_id)
        if not run:
            raise NotFoundError("Agent run not found", code="AGENT_RUN_NOT_FOUND", data={"run_id": str(run_id)})
        return run
