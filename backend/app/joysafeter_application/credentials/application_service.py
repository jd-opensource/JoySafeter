from __future__ import annotations

from typing import Any

from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_domain.credentials.types import CredentialGroupId, CredentialId, ProjectId

from .composition import compose_credential_application


class CredentialService:
    def __init__(
        self,
        db: Any,
        *,
        audit_actor: CredentialAuditActor,
        auto_commit: bool = True,
        dependency_session_factory: Any | None = None,
    ) -> None:
        self._application = compose_credential_application(
            db,
            auto_commit=auto_commit,
            dependency_session_factory=dependency_session_factory,
            audit_actor=audit_actor,
        )

    async def create(self, request: Any, project_id: ProjectId) -> Any:
        return await self._application.resource_service.create(request, project_id)

    async def update(self, credential_id: CredentialId, request: Any, project_id: ProjectId) -> Any:
        return await self._application.resource_service.update(credential_id, request, project_id)

    async def set_default(self, credential_id: CredentialId, project_id: ProjectId) -> Any:
        return await self._application.resource_service.set_default(credential_id, project_id)

    async def clear_default(self, credential_id: CredentialId, project_id: ProjectId) -> Any:
        return await self._application.resource_service.clear_default(credential_id, project_id)

    async def archive(self, credential_id: CredentialId, project_id: ProjectId) -> Any:
        return await self._application.lifecycle.archive_resource(credential_id, project_id)

    async def restore(self, credential_id: CredentialId, project_id: ProjectId) -> Any:
        return await self._application.resource_service.restore(credential_id, project_id)

    async def soft_delete(self, credential_id: CredentialId, project_id: ProjectId) -> Any:
        return await self._application.lifecycle.delete_resource(credential_id, project_id)

    async def get(self, credential_id: CredentialId, project_id: ProjectId) -> Any | None:
        return await self._application.resource_service.get(credential_id, project_id)

    async def get_or_raise(self, credential_id: CredentialId, project_id: ProjectId) -> Any:
        return await self._application.resource_service.get_or_raise(credential_id, project_id)

    async def list(self, *args: Any, **kwargs: Any) -> Any:
        return await self._application.resource_service.list(*args, **kwargs)

    async def dependencies(self, credential_id: CredentialId, project_id: ProjectId) -> Any:
        return await self._application.resource_service.dependencies(credential_id, project_id)

    def get_credential_data(self, credential: Any | None) -> dict[str, str]:
        return self._application.resource_service.get_credential_data(credential)

    def get_masked(self, credential: Any | None) -> dict[str, str]:
        return self._application.resource_service.get_masked(credential)


class CredentialGroupService:
    def __init__(
        self,
        db: Any,
        *,
        audit_actor: CredentialAuditActor,
        auto_commit: bool = True,
        dependency_session_factory: Any | None = None,
    ) -> None:
        self._application = compose_credential_application(
            db,
            auto_commit=auto_commit,
            dependency_session_factory=dependency_session_factory,
            audit_actor=audit_actor,
        )
        self._groups = self._application.group_service

    async def create(self, request: Any, project_id: ProjectId) -> Any:
        return await self._groups.create(request, project_id)

    async def create_with_initial_members(self, request: Any, project_id: ProjectId) -> Any:
        return await self._groups.create_with_initial_members(request, project_id)

    async def get(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any | None:
        return await self._groups.get(group_id, project_id)

    async def get_or_raise(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any:
        return await self._groups.get_or_raise(group_id, project_id)

    async def list(self, *args: Any, **kwargs: Any) -> Any:
        return await self._groups.list(*args, **kwargs)

    async def update(self, group_id: CredentialGroupId, request: Any, project_id: ProjectId) -> Any:
        return await self._groups.update(group_id, request, project_id)

    async def archive(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any:
        return await self._application.lifecycle.archive_group(group_id, project_id, self._groups.archive)

    async def restore(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any:
        return await self._groups.restore(group_id, project_id)

    async def soft_delete(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any:
        return await self._application.lifecycle.delete_group(group_id, project_id, self._groups.soft_delete)

    async def add_credential(self, group_id: CredentialGroupId, request: Any, project_id: ProjectId) -> Any:
        return await self._groups.add_credential(group_id, request, project_id)

    async def archive_credential(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> Any:
        return await self._application.lifecycle.archive_resource(
            credential_id,
            project_id,
            requested_group_id=group_id,
        )

    async def remove_credential(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> Any:
        return await self._application.lifecycle.delete_resource(
            credential_id,
            project_id,
            requested_group_id=group_id,
        )

    async def list_members(self, *args: Any, **kwargs: Any) -> Any:
        return await self._groups.list_members(*args, **kwargs)


__all__ = ["CredentialGroupService", "CredentialService"]
