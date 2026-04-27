from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.models.skill_collaborator import CollaboratorRole
from app.services.skill_collaborator_service import SkillCollaboratorService


def _build_service() -> SkillCollaboratorService:
    service = SkillCollaboratorService(AsyncMock())
    service.repo = SimpleNamespace(
        get_by_skill_and_user=AsyncMock(),
        delete_by_skill_and_user=AsyncMock(),
    )
    service.skill_repo = SimpleNamespace(
        get=AsyncMock(),
        get_by_name_and_owner=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
async def test_add_collaborator_rejects_owner_with_canonical_code() -> None:
    service = _build_service()
    skill_id = uuid.uuid4()
    skill = SimpleNamespace(id=skill_id, owner_id="owner-1")
    service.skill_repo.get.return_value = skill

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.add_collaborator(
            skill_id,
            "owner-1",
            "owner-1",
            CollaboratorRole.viewer,
            is_superuser=True,
        )

    assert exc_info.value.code == "SKILL_OWNER_COLLABORATOR_FORBIDDEN"


@pytest.mark.asyncio
async def test_transfer_ownership_requires_owner_with_canonical_code() -> None:
    service = _build_service()
    skill_id = uuid.uuid4()
    service.skill_repo.get.return_value = SimpleNamespace(id=skill_id, owner_id="owner-1", name="demo")

    with pytest.raises(AccessDeniedError) as exc_info:
        await service.transfer_ownership(skill_id, "user-2", "user-3")

    assert exc_info.value.code == "SKILL_OWNER_TRANSFER_FORBIDDEN"


@pytest.mark.asyncio
async def test_get_skill_or_404_has_canonical_code() -> None:
    service = _build_service()
    skill_id = uuid.uuid4()
    service.skill_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service._get_skill_or_404(skill_id)

    assert exc_info.value.code == "SKILL_NOT_FOUND"
    assert exc_info.value.data == {"skill_id": str(skill_id)}
