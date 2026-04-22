"""
AgentRunService — manages AgentRun lifecycle.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
from app.models.agent_run import AgentRun
from app.models.execution import Execution
from app.repositories.agent import AgentRepository, AgentVersionRepository
from app.repositories.agent_release import AgentReleaseRepository
from app.repositories.agent_run import AgentRunRepository
from app.repositories.execution import ExecutionRepository
from app.schemas.agent_run import CreateAgentRunRequest
from app.utils.datetime import utc_now


class AgentRunService:
    """Manages AgentRun entities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.run_repo = AgentRunRepository(db)
        self.release_repo = AgentReleaseRepository(db)
        self.version_repo = AgentVersionRepository(db)
        self.agent_repo = AgentRepository(db)
        self.execution_repo = ExecutionRepository(db)

    async def list_runs(
        self,
        workspace_id: Optional[uuid.UUID] = None,
        release_id: Optional[uuid.UUID] = None,
        mission_id: Optional[uuid.UUID] = None,
    ) -> List[AgentRun]:
        """List runs filtered by parameters."""
        if mission_id:
            return await self.run_repo.list_by_mission(mission_id)
        elif release_id:
            return await self.run_repo.list_by_release(release_id)
        elif workspace_id:
            return await self.run_repo.list_by_workspace(workspace_id)
        else:
            raise BadRequestException("Must provide workspace_id, release_id, or mission_id")

    async def get_run(self, run_id: uuid.UUID) -> AgentRun:
        """Get a run by ID."""
        run = await self.run_repo.get(run_id)
        if not run:
            raise NotFoundException(f"AgentRun {run_id} not found")
        return run

    async def create_run(
        self, user_id: str, data: CreateAgentRunRequest
    ) -> AgentRun:
        """Create a new run and initial execution."""
        # Verify release exists and is ready
        release = await self.release_repo.get(data.release_id)
        if not release:
            raise NotFoundException(f"AgentRelease {data.release_id} not found")
        if release.status != "ready":
            raise BadRequestException("Release must be in 'ready' status to create a run")

        # Resolve workspace_id from release → version → agent
        version = await self.version_repo.get(release.agent_version_id)
        if not version:
            raise NotFoundException(f"AgentVersion {release.agent_version_id} not found")

        agent = await self.agent_repo.get(version.agent_id)
        if not agent:
            raise NotFoundException(f"Agent {version.agent_id} not found")

        workspace_id = agent.workspace_id

        # Create AgentRun
        run = await self.run_repo.create(
            {
                "release_id": data.release_id,
                "workspace_id": workspace_id,
                "thread_id": data.thread_id,
                "mission_id": data.mission_id,
                "trigger_source": data.trigger_source,
                "goal": data.goal,
                "input_payload": data.input_payload,
                "status": "queued",
                "created_by": user_id,
            }
        )

        # Determine executor_kind from runtime_binding
        executor_kind = release.runtime_binding.get("runtime_type", "claude_code")

        # Create initial Execution
        execution = Execution(
            run_id=run.id,
            attempt_index=1,
            executor_kind=executor_kind,
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()
        await self.db.refresh(execution)

        # Set run.current_execution_id
        run.current_execution_id = execution.id
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(run)

        logger.info(f"Created run {run.id} with initial execution {execution.id}")
        return run

    async def cancel_run(self, run_id: uuid.UUID) -> AgentRun:
        """Cancel a run."""
        run = await self.run_repo.get(run_id)
        if not run:
            raise NotFoundException(f"AgentRun {run_id} not found")

        updated = await self.run_repo.update(
            run_id, {"status": "cancelled", "ended_at": utc_now()}
        )
        assert updated is not None

        logger.info(f"Cancelled run {run_id}")
        return updated

    async def retry_run(self, run_id: uuid.UUID) -> AgentRun:
        """Retry a run by creating a new execution with incremented attempt_index."""
        run = await self.run_repo.get(run_id)
        if not run:
            raise NotFoundException(f"AgentRun {run_id} not found")

        # Get max attempt index
        max_attempt = await self.execution_repo.get_max_attempt(run_id)
        next_attempt = max_attempt + 1

        # Get release to determine executor_kind
        release = await self.release_repo.get(run.release_id)
        if not release:
            raise NotFoundException(f"AgentRelease {run.release_id} not found")

        executor_kind = release.runtime_binding.get("runtime_type", "claude_code")

        # Create new execution
        execution = Execution(
            run_id=run.id,
            attempt_index=next_attempt,
            executor_kind=executor_kind,
            status="pending",
        )
        self.db.add(execution)
        await self.db.flush()
        await self.db.refresh(execution)

        # Update run
        updated = await self.run_repo.update(
            run_id,
            {
                "status": "queued",
                "current_execution_id": execution.id,
                "ended_at": None,
            },
        )
        assert updated is not None

        await self.db.commit()
        logger.info(f"Retrying run {run_id} with execution {execution.id} (attempt {next_attempt})")
        return updated
