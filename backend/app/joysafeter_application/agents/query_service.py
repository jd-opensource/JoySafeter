from __future__ import annotations

from typing import Any, Optional

from app.joysafeter_application.agents.ports import AgentRepositoryPort
from app.joysafeter_domain.agents.snapshots import build_agent_snapshot, build_environment_snapshot
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_shared.ids import AgentId, EnvironmentId, ProjectId


class AgentQueryService:
    def __init__(self, repository: AgentRepositoryPort) -> None:
        self._repository = repository

    @staticmethod
    def build_environment_execution_snapshot(environment: Any) -> Optional[dict]:
        return build_environment_snapshot(environment)

    @staticmethod
    def build_execution_snapshot(
        agent: JoySafeterAgent,
        *,
        environment: Any = None,
        environment_id: Optional[EnvironmentId] = None,
        version: Optional[int] = None,
    ) -> dict:
        return build_agent_snapshot(
            agent,
            environment=environment,
            environment_id=environment_id,
            version=version,
        )

    async def get_agent(self, agent_id: AgentId, project_id: ProjectId | None = None) -> Optional[JoySafeterAgent]:
        return await self._repository.get(agent_id, project_id=project_id)

    async def get_agent_by_name(self, name: str, project_id: ProjectId | None = None) -> Optional[JoySafeterAgent]:
        return await self._repository.get_by_name(name, project_id=project_id)

    async def list_agents(
        self,
        limit: int = 20,
        after_id: Optional[AgentId] = None,
        include_archived: bool = False,
        project_id: ProjectId | None = None,
    ) -> tuple[list[JoySafeterAgent], bool]:
        return await self._repository.list(limit, after_id, include_archived, project_id)

    async def list_versions(
        self,
        agent_id: AgentId,
        limit: int = 20,
        before_version: Optional[int] = None,
        project_id: ProjectId | None = None,
    ) -> tuple[list[JoySafeterAgentVersion], bool]:
        return await self._repository.list_versions(agent_id, limit, before_version, project_id)

    async def get_agent_version_snapshot(
        self, agent_id: AgentId, version: int, project_id: ProjectId | None = None
    ) -> Optional[dict]:
        return await self._repository.get_version_snapshot(agent_id, version, project_id)

    async def count_delete_preview(
        self, agent_id: AgentId, project_id: ProjectId | None = None
    ) -> Optional[tuple[int, int, int, int]]:
        return await self._repository.count_delete_preview(agent_id, project_id)

    async def list_active_tasks_for_agent(
        self, agent_id: AgentId, project_id: ProjectId | None = None
    ) -> list[JoySafeterTask]:
        return await self._repository.list_active_tasks(agent_id, project_id)
