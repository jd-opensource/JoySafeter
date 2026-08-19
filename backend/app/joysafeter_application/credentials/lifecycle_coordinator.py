from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    DependencyDisposition,
)
from app.joysafeter_domain.credentials.resource import CredentialResource, McpCredentialIdentity
from app.joysafeter_domain.credentials.types import (
    CredentialGroupId,
    CredentialId,
    CredentialState,
    ProjectId,
)
from app.joysafeter_shared.common.app_errors import NotFoundError, ResourceConflictError
from app.joysafeter_shared.config.settings import settings

from .ports import CredentialUnitOfWork
from .resource_service import CredentialResourceService

logger = logging.getLogger(__name__)

ResourceScanner = Callable[[ProjectId, CredentialId], Awaitable[Sequence[CredentialDependency]]]
GroupScanner = Callable[[ProjectId, CredentialGroupId], Awaitable[Sequence[CredentialDependency]]]


class CredentialLifecycleCoordinator:
    def __init__(
        self,
        uow: CredentialUnitOfWork,
        transactions: CredentialResourceService,
        *,
        scan_resource_dependencies: ResourceScanner,
        scan_group_dependencies: GroupScanner,
    ) -> None:
        self._uow = uow
        self._transactions = transactions
        self._scan_resource_dependencies = scan_resource_dependencies
        self._scan_group_dependencies = scan_group_dependencies

    async def _resolve_resource_context(
        self,
        credential_id: Any,
        project_id: str,
        *,
        requested_group_id: Any | None = None,
    ) -> CredentialResource:
        resource = await self._uow.credentials.get_resource(
            CredentialId(str(credential_id)),
            ProjectId(str(project_id)),
        )
        if resource is None:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data={"credential_id": str(credential_id)},
            )

        identity = resource.identity
        if requested_group_id is not None:
            requested = CredentialGroupId(str(requested_group_id))
            if not isinstance(identity, McpCredentialIdentity) or identity.group_id != requested:
                raise NotFoundError(
                    code="CREDENTIAL_NOT_FOUND",
                    message="Credential not found in group",
                    data={
                        "credential_id": str(credential_id),
                        "credential_group_id": str(requested_group_id),
                    },
                )

        if not isinstance(identity, McpCredentialIdentity):
            return resource

        owning_group = await self._uow.groups.get_group(identity.group_id, project_id)
        if owning_group is None or owning_group.state is CredentialState.DELETED:
            raise NotFoundError(
                code="CREDENTIAL_GROUP_NOT_FOUND",
                message="Credential group not found",
                data={"credential_group_id": str(identity.group_id)},
            )
        if owning_group.state is CredentialState.ARCHIVED:
            raise ResourceConflictError(
                code="CREDENTIAL_GROUP_ARCHIVED",
                message="Archived credential groups cannot be mutated",
                data={"credential_group_id": str(identity.group_id)},
                user_action="refresh",
            )
        return resource

    async def _observe_resource(
        self,
        credential_id: Any,
        project_id: str,
        disposition: DependencyDisposition,
    ) -> None:
        old_result, new_result = await asyncio.gather(
            self._uow.credentials.dependencies(credential_id, project_id=project_id),
            self._scan_resource_dependencies(
                ProjectId(str(project_id)),
                CredentialId(str(credential_id)),
            ),
            return_exceptions=True,
        )
        if isinstance(old_result, BaseException):
            raise old_result
        if isinstance(new_result, asyncio.CancelledError):
            raise new_result
        if isinstance(new_result, BaseException):
            if not isinstance(new_result, Exception):
                raise new_result
            if settings.credential_dependency_registry_mode == "enforce":
                raise new_result
            new_dependencies: tuple[CredentialDependency, ...] = ()
        else:
            new_dependencies = tuple(new_result)

        old_data = old_result.as_data()
        old_ids = sorted({str(source_id) for source_ids in old_data.values() for source_id in source_ids})
        old_dispositions = [disposition.value] if old_ids else []
        blockers = sorted(
            {str(dependency.source_id) for dependency in new_dependencies if dependency.blocks(disposition)}
        )
        new_dispositions = sorted(
            {
                candidate.value
                for dependency in new_dependencies
                for candidate in dependency.dispositions
                if candidate is disposition
            }
        )
        if settings.credential_dependency_registry_mode == "shadow":
            if old_ids != blockers or old_dispositions != new_dispositions:
                logger.info(
                    "credential_dependency_registry_shadow_diff",
                    extra={
                        "credential_dependency_diff": {
                            "credential_id": str(credential_id),
                            "project_id": str(project_id),
                            "old": {
                                "ids": old_ids,
                                "count": len(old_ids),
                                "dispositions": old_dispositions,
                            },
                            "new": {
                                "ids": blockers,
                                "count": len(blockers),
                                "dispositions": new_dispositions,
                            },
                            "added_ids": sorted(set(blockers) - set(old_ids)),
                            "removed_ids": sorted(set(old_ids) - set(blockers)),
                            "disposition_diff": {
                                "added": sorted(set(new_dispositions) - set(old_dispositions)),
                                "removed": sorted(set(old_dispositions) - set(new_dispositions)),
                            },
                        }
                    },
                )
            return
        if blockers:
            raise ResourceConflictError(
                code="CREDENTIAL_IN_USE",
                message="Credential is still referenced and cannot be changed",
                data={
                    "credential_id": str(credential_id),
                    "dependency_ids": blockers,
                    "dependency_count": len(blockers),
                    "dispositions": new_dispositions,
                },
                user_action="fix_input",
            )

    async def _observe_group(
        self,
        group_id: Any,
        project_id: str,
        disposition: DependencyDisposition,
    ) -> None:
        try:
            dependencies = await self._scan_group_dependencies(
                ProjectId(str(project_id)),
                CredentialGroupId(str(group_id)),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if settings.credential_dependency_registry_mode == "enforce":
                raise
            logger.info(
                "credential_group_dependency_registry_shadow_scan_failed",
                extra={"credential_group_id": str(group_id), "project_id": project_id},
                exc_info=True,
            )
            return
        blockers = sorted({str(dependency.source_id) for dependency in dependencies if dependency.blocks(disposition)})
        if settings.credential_dependency_registry_mode == "shadow":
            old = sorted(
                str(session_id)
                for session_id in await self._uow.credentials._active_group_session_ids(group_id, project_id)
            )
            if old != blockers:
                logger.info(
                    "credential_group_dependency_registry_shadow_diff",
                    extra={
                        "credential_group_dependency_diff": {
                            "credential_group_id": str(group_id),
                            "project_id": project_id,
                            "old": old,
                            "new": blockers,
                            "disposition": disposition.value,
                        }
                    },
                )
            return
        if blockers:
            raise ResourceConflictError(
                code="CREDENTIAL_IN_USE",
                message="Credential group is still referenced and cannot be changed",
                data={
                    "credential_group_id": str(group_id),
                    "dependency_ids": blockers,
                    "dependency_count": len(blockers),
                    "dispositions": [disposition.value],
                },
                user_action="fix_input",
            )

    async def archive_resource(
        self,
        credential_id: Any,
        project_id: str,
        *,
        requested_group_id: Any | None = None,
    ) -> Any:
        resource = await self._resolve_resource_context(
            credential_id,
            project_id,
            requested_group_id=requested_group_id,
        )
        if resource.state is not CredentialState.ARCHIVED:
            await self._observe_resource(
                credential_id,
                project_id,
                DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
            )
        return await self._transactions.archive(credential_id, project_id=project_id)

    async def delete_resource(
        self,
        credential_id: Any,
        project_id: str,
        *,
        requested_group_id: Any | None = None,
    ) -> Any:
        resource = await self._resolve_resource_context(
            credential_id,
            project_id,
            requested_group_id=requested_group_id,
        )
        if resource.state is not CredentialState.DELETED:
            await self._observe_resource(
                credential_id,
                project_id,
                DependencyDisposition.BLOCK_RESOURCE_DELETE,
            )
        return await self._transactions.soft_delete(credential_id, project_id=project_id)

    async def archive_group(self, group_id: Any, project_id: str, operation) -> Any:
        resource = await self._uow.groups.get_group(group_id, project_id)
        if resource is None or resource.state is not CredentialState.ARCHIVED:
            await self._observe_group(
                group_id,
                project_id,
                DependencyDisposition.BLOCK_GROUP_ARCHIVE,
            )
        return await operation(group_id, project_id)

    async def delete_group(self, group_id: Any, project_id: str, operation) -> Any:
        resource = await self._uow.groups.get_group(group_id, project_id)
        if resource is None or resource.state is not CredentialState.DELETED:
            await self._observe_group(
                group_id,
                project_id,
                DependencyDisposition.BLOCK_GROUP_DELETE,
            )
        return await operation(group_id, project_id)
