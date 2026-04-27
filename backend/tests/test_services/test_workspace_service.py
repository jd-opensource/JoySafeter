from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.models.workspace import WorkspaceMemberRole
from app.services.workspace_service import WorkspaceService


def _build_service() -> WorkspaceService:
    service = WorkspaceService(AsyncMock())
    service.workspace_repo = SimpleNamespace(get=AsyncMock())
    service.member_repo = SimpleNamespace(
        get_member=AsyncMock(),
        count_admins=AsyncMock(),
    )
    service.commit = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_ensure_member_missing_workspace_has_canonical_code() -> None:
    service = _build_service()
    workspace_id = uuid.uuid4()
    current_user = SimpleNamespace(id="user-1", is_superuser=False)
    service.workspace_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service._ensure_member(workspace_id, current_user)

    assert exc_info.value.code == "WORKSPACE_NOT_FOUND"
    assert exc_info.value.data == {"workspace_id": str(workspace_id)}


@pytest.mark.asyncio
async def test_update_member_role_rejects_last_admin_removal_with_canonical_code() -> None:
    service = _build_service()
    workspace_id = uuid.uuid4()
    target_user_id = "user-2"
    current_user = SimpleNamespace(id="user-1", is_superuser=False)
    workspace = SimpleNamespace(id=workspace_id, owner_id="owner-1")
    target_member = SimpleNamespace(role=WorkspaceMemberRole.admin)

    service.workspace_repo.get.return_value = workspace
    service.member_repo.get_member.side_effect = [SimpleNamespace(role=WorkspaceMemberRole.owner), target_member]
    service.member_repo.count_admins.return_value = 1

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.update_member_role(
            workspace_id,
            target_user_id,
            WorkspaceMemberRole.member,
            current_user,
        )

    assert exc_info.value.code == "WORKSPACE_LAST_ADMIN_REMOVE_FORBIDDEN"


@pytest.mark.asyncio
async def test_remove_member_requires_permission_with_canonical_code() -> None:
    service = _build_service()
    workspace_id = uuid.uuid4()
    target_user_id = uuid.uuid4()
    current_user = SimpleNamespace(id="user-1", is_superuser=False)
    workspace = SimpleNamespace(id=workspace_id, owner_id="owner-1")
    target_member = SimpleNamespace(role=WorkspaceMemberRole.member)

    service.workspace_repo.get.return_value = workspace
    service.member_repo.get_member.return_value = target_member
    service._get_role = AsyncMock(return_value=WorkspaceMemberRole.member)

    with pytest.raises(AccessDeniedError) as exc_info:
        await service.remove_member(
            workspace_id=workspace_id,
            target_user_id=target_user_id,
            current_user=current_user,
        )

    assert exc_info.value.code == "WORKSPACE_PERMISSION_DENIED"
