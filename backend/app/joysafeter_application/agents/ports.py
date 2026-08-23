from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Protocol, Sequence

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_shared.ids import AgentId, CredentialId, SessionId, SkillId


class AgentNameConflictError(Exception):
    pass


class AgentRepositoryPort(Protocol):
    def add(self, agent: JoySafeterAgent) -> None: ...

    async def flush(self) -> None: ...

    async def refresh(self, instance: Any) -> None: ...

    async def get(self, agent_id: AgentId, project_id: Optional[str] = None) -> Optional[JoySafeterAgent]: ...

    async def lock(self, agent_id: AgentId, project_id: Optional[str] = None) -> Optional[JoySafeterAgent]: ...

    async def get_by_name(self, name: str, project_id: Optional[str] = None) -> Optional[JoySafeterAgent]: ...

    async def list(
        self,
        limit: int = 20,
        after_id: Optional[AgentId] = None,
        include_archived: bool = False,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterAgent], bool]: ...

    async def lock_environment_by_ref(
        self, ref: str, project_id: Optional[str] = None
    ) -> Optional[JoySafeterEnvironment]: ...

    async def skills_by_ids(self, skill_ids: Sequence[SkillId]) -> dict[SkillId, JoySafeterSkill]: ...

    async def project_org_ids(self, project_ids: Sequence[str]) -> dict[str, str]: ...

    async def skill_version_strings_by_ids(self, version_ids: Sequence[Any]) -> dict[Any, str]: ...

    async def latest_skill_versions(self, skill_ids: Sequence[SkillId]) -> dict[SkillId, str]: ...

    async def get_skill_version(self, skill_id: SkillId, version: str) -> Any | None: ...

    async def save_version(self, agent: JoySafeterAgent, snapshot: dict[str, Any]) -> None: ...

    async def count_active_tasks(self, agent_id: AgentId, project_id: Optional[str] = None) -> int: ...

    async def list_active_tasks(self, agent_id: AgentId, project_id: Optional[str] = None) -> list[JoySafeterTask]: ...

    async def list_non_archived_session_ids(self, agent_id: AgentId) -> list[SessionId]: ...

    async def archive_sessions_if_no_active_tasks(
        self, session_ids: list[SessionId], archived_at: datetime
    ) -> bool: ...

    async def hard_delete_owned_rows(self, agent_id: AgentId) -> None: ...

    async def list_versions(
        self,
        agent_id: AgentId,
        limit: int = 20,
        before_version: Optional[int] = None,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterAgentVersion], bool]: ...

    async def get_version_snapshot(
        self, agent_id: AgentId, version: int, project_id: Optional[str] = None
    ) -> Optional[dict]: ...

    async def count_delete_preview(
        self, agent_id: AgentId, project_id: Optional[str] = None
    ) -> Optional[tuple[int, int, int, int]]: ...


class AgentUnitOfWork(Protocol):
    agents: AgentRepositoryPort

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class AgentCredentialBindingPort(Protocol):
    async def lock_credentials(self, credential_ids: Sequence[CredentialId], *, project_id: str) -> None: ...

    async def validate_model_reference(
        self,
        credential_id: CredentialId,
        *,
        project_id: str,
        engine_kind: str,
        model_id: Optional[str],
    ) -> None: ...


class AgentRuntimePort(Protocol):
    async def cancel_task(self, task: JoySafeterTask, *, reason: str) -> None: ...

    async def destroy_sandboxes(
        self,
        agent_id: AgentId,
        *,
        reason: str,
        project_id: Optional[str] = None,
    ) -> None: ...

    async def cleanup_identity(self, agent_id: AgentId) -> None: ...


class AgentTriggerLifecyclePort(Protocol):
    async def lock_for_agent_lifecycle(
        self,
        agent_id: AgentId,
        *,
        project_id: Optional[str] = None,
    ) -> Sequence[JoySafeterTrigger]: ...

    def pause_locked_agent_triggers(self, triggers: Sequence[JoySafeterTrigger]) -> None: ...

    async def resume_locked_agent_triggers(self, triggers: Sequence[JoySafeterTrigger]) -> None: ...
