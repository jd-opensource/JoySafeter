from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError, ResourceConflictError
from app.models.enums import OrgRole
from app.services.organization_service import OrganizationService


def _build_service() -> OrganizationService:
    service = OrganizationService(AsyncMock())
    service.org_repo = SimpleNamespace(
        get_with_members=AsyncMock(),
        slug_exists=AsyncMock(),
    )
    service.member_repo = SimpleNamespace(
        get_by_user_and_org=AsyncMock(),
        count_by_org=AsyncMock(),
        get_with_user=AsyncMock(),
    )
    service.user_repo = SimpleNamespace(
        get_by_email=AsyncMock(),
    )
    service.commit = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_create_organization_duplicate_slug_has_canonical_code() -> None:
    service = _build_service()
    service.org_repo.slug_exists.return_value = True
    current_user = SimpleNamespace(id="user-1")

    with pytest.raises(ResourceConflictError) as exc_info:
        await service.create_organization(
            name="Org",
            slug="joy",
            logo=None,
            current_user=current_user,
        )

    assert exc_info.value.code == "ORGANIZATION_SLUG_ALREADY_EXISTS"
    assert exc_info.value.data == {"slug": "joy"}


@pytest.mark.asyncio
async def test_update_seats_rejects_below_member_count_with_canonical_code() -> None:
    service = _build_service()
    organization_id = uuid.uuid4()
    current_user = SimpleNamespace(id="user-1")
    organization = SimpleNamespace(
        id=organization_id,
        metadata_={"plan_type": "team", "seats": {"limit": 5}},
        members=[],
    )
    service.org_repo.get_with_members.return_value = organization
    service.member_repo.get_by_user_and_org.return_value = SimpleNamespace(role=OrgRole.OWNER)
    service.member_repo.count_by_org.return_value = 3

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.update_seats(
            organization_id,
            seats=2,
            current_user=current_user,
        )

    assert exc_info.value.code == "ORGANIZATION_SEATS_BELOW_MEMBER_COUNT"
    assert exc_info.value.data == {"seats": 2, "member_count": 3}


@pytest.mark.asyncio
async def test_get_member_requires_visibility_permission_with_canonical_code() -> None:
    service = _build_service()
    organization_id = uuid.uuid4()
    member_id = uuid.uuid4()
    current_user = SimpleNamespace(id="user-1")
    organization = SimpleNamespace(id=organization_id, members=[])
    requester = SimpleNamespace(user_id="user-1", role=OrgRole.MEMBER)
    target = SimpleNamespace(
        id=member_id,
        organization_id=organization_id,
        user_id="user-2",
        role=OrgRole.MEMBER,
    )

    service.org_repo.get_with_members.return_value = organization
    service.member_repo.get_by_user_and_org.return_value = requester
    service.member_repo.get_with_user.return_value = target

    with pytest.raises(AccessDeniedError) as exc_info:
        await service.get_member(
            organization_id,
            member_id,
            include_usage=False,
            current_user=current_user,
        )

    assert exc_info.value.code == "ORGANIZATION_MEMBER_VIEW_FORBIDDEN"


@pytest.mark.asyncio
async def test_invite_member_missing_user_has_canonical_code() -> None:
    service = _build_service()
    organization_id = uuid.uuid4()
    current_user = SimpleNamespace(id="user-1")
    organization = SimpleNamespace(id=organization_id, members=[], metadata_={"plan_type": "team", "seats": {"limit": 3}})
    inviter = SimpleNamespace(role=OrgRole.OWNER)

    service.org_repo.get_with_members.return_value = organization
    service.member_repo.get_by_user_and_org.return_value = inviter
    service.user_repo.get_by_email.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.invite_member(
            organization_id,
            email="missing@example.com",
            role=OrgRole.MEMBER,
            current_user=current_user,
        )

    assert exc_info.value.code == "USER_NOT_FOUND"
    assert exc_info.value.data == {"email": "missing@example.com"}
