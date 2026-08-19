"""Compatibility facade for Credential Group Application services."""

from __future__ import annotations

from typing import Any

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_domain.credentials.dependencies import DependencyDisposition


class CredentialGroupService:
    def __init__(
        self,
        db: Any,
        *,
        auto_commit: bool = True,
        compatibility_mode: bool = True,
        dependency_session_factory: Any | None = None,
    ) -> None:
        application = compose_credential_application(
            db,
            auto_commit=auto_commit,
            compatibility_mode=compatibility_mode,
            dependency_session_factory=dependency_session_factory,
        )
        self._application = application
        self._service = application.group_service

    async def _observe_dependency_registry(
        self,
        group_id: Any,
        project_id: str,
        disposition: DependencyDisposition,
    ) -> None:
        await self._application.lifecycle._observe_group(group_id, project_id, disposition)

    async def archive(self, group_id: Any, project_id: str) -> Any:
        return await self._application.lifecycle.archive_group(
            group_id,
            project_id,
            self._service.archive,
        )

    async def soft_delete(self, group_id: Any, project_id: str) -> Any:
        return await self._application.lifecycle.delete_group(
            group_id,
            project_id,
            self._service.soft_delete,
        )

    async def archive_credential(self, group_id: Any, credential_id: Any, project_id: str) -> Any:
        return await self._application.lifecycle.archive_resource(
            credential_id,
            project_id,
            requested_group_id=group_id,
        )

    async def remove_credential(self, group_id: Any, credential_id: Any, project_id: str) -> Any:
        return await self._application.lifecycle.delete_resource(
            credential_id,
            project_id,
            requested_group_id=group_id,
        )

    def __getattr__(self, name: str) -> Any:
        service = self.__dict__.get("_service")
        if service is None:
            raise AttributeError(name)
        return getattr(service, name)
