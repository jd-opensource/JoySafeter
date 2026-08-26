from __future__ import annotations

from typing import Any

from app.joysafeter_domain.credentials.bindings import McpGroupBinding
from app.joysafeter_domain.credentials.policies import validate_mcp_group_binding
from app.joysafeter_domain.credentials.types import CredentialGroupId, CredentialId, ProjectId

from .ports import CredentialUnitOfWork
from .resource_service import CredentialResourceService


class CredentialGroupService:
    def __init__(self, uow: CredentialUnitOfWork, transactions: CredentialResourceService) -> None:
        self._uow = uow
        self._transactions = transactions

    async def validate_binding(self, binding: McpGroupBinding) -> None:
        groups = tuple(await self._uow.groups.get_many(binding.group_ids, project_id=binding.project_id))
        members = tuple(await self._uow.groups.list_members(binding.group_ids, project_id=binding.project_id))
        validate_mcp_group_binding(binding, groups=groups, members=members)

    async def create(self, request: Any, project_id: ProjectId) -> Any:
        group_id = CredentialGroupId.new()
        return await self._transactions._mutate(
            lambda: self._uow.groups.create_group(group_id, request, project_id),
            action="credential_group.created",
            project_id=project_id,
            target_id=str(group_id),
            target_type="credential_group",
        )

    async def create_with_initial_members(self, request: Any, project_id: ProjectId) -> Any:
        members = tuple(request.initial_members)
        if not members:
            return await self.create(request, project_id)

        batch = CredentialResourceService(
            self._uow,
            manage_transaction=False,
        )
        batch.begin_batch()
        batch_groups = CredentialGroupService(self._uow, batch)
        try:
            group = await batch_groups.create(request, project_id)
            for member in members:
                await batch_groups.add_credential(group.id, member, project_id)
            await batch.commit_pending()
        except Exception:
            await batch.rollback_pending()
            raise
        return group

    async def get(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any | None:
        return await self._uow.groups.get_group_row(group_id, project_id)

    async def get_or_raise(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any:
        group = await self.get(group_id, project_id)
        if group is None:
            from app.joysafeter_shared.common.app_errors import NotFoundError

            raise NotFoundError(
                code="CREDENTIAL_GROUP_NOT_FOUND",
                message="Credential group not found",
                data={"credential_group_id": str(group_id)},
            )
        return group

    async def list(self, *args: Any, **kwargs: Any) -> Any:
        return await self._uow.groups.list_group_rows(*args, **kwargs)

    async def update(self, group_id: CredentialGroupId, request: Any, project_id: ProjectId) -> Any:
        return await self._transactions._mutate(
            lambda: self._uow.groups.update_group(group_id, request, project_id),
            action="credential_group.updated",
            project_id=project_id,
            target_id=str(group_id),
            target_type="credential_group",
        )

    async def archive(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any:
        return await self._transactions._mutate(
            lambda: self._uow.groups.archive_group(group_id, project_id),
            action="credential_group.archived",
            project_id=project_id,
            target_id=str(group_id),
            target_type="credential_group",
        )

    async def restore(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any:
        return await self._transactions._mutate(
            lambda: self._uow.groups.restore_group(group_id, project_id),
            action="credential_group.restored",
            project_id=project_id,
            target_id=str(group_id),
            target_type="credential_group",
        )

    async def soft_delete(self, group_id: CredentialGroupId, project_id: ProjectId) -> Any:
        return await self._transactions._mutate(
            lambda: self._uow.groups.delete_group(group_id, project_id),
            action="credential_group.deleted",
            project_id=project_id,
            target_id=str(group_id),
            target_type="credential_group",
        )

    async def add_credential(self, group_id: CredentialGroupId, request: Any, project_id: ProjectId) -> Any:
        credential_id = CredentialId.new()
        return await self._transactions._mutate(
            lambda: self._uow.groups.add_group_member(group_id, credential_id, request, project_id),
            action="credential_group.member_added",
            project_id=project_id,
            target_id=str(credential_id),
            target_type="credential",
            details={"credential_group_id": str(group_id)},
        )

    async def archive_credential(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> Any:
        return await self._transactions._mutate(
            lambda: self._uow.groups.archive_group_member(group_id, credential_id, project_id),
            action="credential_group.member_archived",
            project_id=project_id,
            target_id=str(credential_id),
            details={"credential_group_id": str(group_id)},
        )

    async def validate_member_mutation(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> Any:
        return await self._uow.groups.validate_group_member_mutation(group_id, credential_id, project_id)

    async def remove_credential(
        self, group_id: CredentialGroupId, credential_id: CredentialId, project_id: ProjectId
    ) -> Any:
        return await self._transactions._mutate(
            lambda: self._uow.groups.delete_group_member(group_id, credential_id, project_id),
            action="credential_group.member_removed",
            project_id=project_id,
            target_id=str(credential_id),
            details={"credential_group_id": str(group_id)},
        )

    async def list_members(self, *args: Any, **kwargs: Any) -> Any:
        return await self._uow.groups.list_group_member_rows(*args, **kwargs)
