from __future__ import annotations

from typing import Any

from app.joysafeter_domain.credentials.bindings import McpGroupBinding
from app.joysafeter_domain.credentials.policies import validate_mcp_group_binding

from .ports import CredentialUnitOfWork


class CredentialGroupService:
    def __init__(self, uow: CredentialUnitOfWork) -> None:
        self._uow = uow

    async def validate_binding(self, binding: McpGroupBinding) -> None:
        groups = tuple(await self._uow.groups.get_many(binding.group_ids, project_id=str(binding.project_id)))
        members = tuple(await self._uow.groups.list_members(binding.group_ids, project_id=str(binding.project_id)))
        validate_mcp_group_binding(binding, groups=groups, members=members)

    async def get(self, group_id: Any, project_id: str) -> Any | None:
        return await self._uow.groups.get_group(group_id, project_id)
