"""Compatibility facade for Credential Application services.

Existing consumers keep importing ``CredentialService`` until their later
migration tasks. Persistence, material protection, transaction, and impact
work is delegated through the Application composition boundary.
"""

from __future__ import annotations

from typing import Any

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.lifecycle_coordinator import (
    CredentialLifecycleCoordinator,
)
from app.joysafeter_domain.credentials.dependencies import DependencyDisposition
from app.joysafeter_domain.credentials.types import CredentialId


class CredentialService:
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
        self._service = application.resource_service

    def _lifecycle(self) -> CredentialLifecycleCoordinator:
        lifecycle = getattr(self._application, "lifecycle", None)
        if lifecycle is not None:
            return lifecycle

        async def no_group_dependencies(_project_id, _group_id):
            return ()

        return CredentialLifecycleCoordinator(
            self._application.uow,
            self.__dict__.get("_service"),
            scan_resource_dependencies=self._application.scan_resource_dependencies,
            scan_group_dependencies=no_group_dependencies,
        )

    async def _observe_dependency_registry(
        self,
        credential_id: CredentialId,
        project_id: str,
        disposition: DependencyDisposition,
    ) -> None:
        await self._lifecycle()._observe_resource(
            credential_id,
            project_id,
            disposition,
        )

    async def archive(self, credential_id: CredentialId, project_id: str) -> Any:
        lifecycle = getattr(self._application, "lifecycle", None)
        if lifecycle is not None:
            return await lifecycle.archive_resource(credential_id, project_id)
        await self._observe_dependency_registry(
            credential_id,
            project_id,
            DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
        )
        return await self._service.archive(credential_id, project_id)

    async def soft_delete(self, credential_id: CredentialId, project_id: str) -> Any:
        lifecycle = getattr(self._application, "lifecycle", None)
        if lifecycle is not None:
            return await lifecycle.delete_resource(credential_id, project_id)
        await self._observe_dependency_registry(
            credential_id,
            project_id,
            DependencyDisposition.BLOCK_RESOURCE_DELETE,
        )
        return await self._service.soft_delete(credential_id, project_id)

    def __getattr__(self, name: str) -> Any:
        service = self.__dict__.get("_service")
        if service is None:
            raise AttributeError(name)
        return getattr(service, name)
