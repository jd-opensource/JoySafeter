"""Tests for check_skill_access unified permission check."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.common.exceptions import ForbiddenException
from app.common.skill_permissions import check_skill_access
from app.models.skill_collaborator import CollaboratorRole


def _make_skill(owner_id="owner-1", is_public=False):
    skill = MagicMock()
    skill.id = uuid.uuid4()
    skill.owner_id = owner_id
    skill.is_public = is_public
    return skill


@pytest.mark.asyncio
async def test_superuser_always_passes():
    skill = _make_skill(owner_id="other")
    db = AsyncMock()
    await check_skill_access(db, skill, "super-1", CollaboratorRole.admin, is_superuser=True)


@pytest.mark.asyncio
async def test_owner_always_passes():
    skill = _make_skill(owner_id="owner-1")
    db = AsyncMock()
    await check_skill_access(db, skill, "owner-1", CollaboratorRole.admin)


@pytest.mark.asyncio
async def test_collaborator_with_sufficient_role():
    skill = _make_skill(owner_id="other")
    db = AsyncMock()
    mock_collab = MagicMock()
    mock_collab.role = CollaboratorRole.editor
    with patch("app.common.skill_permissions._get_collaborator", return_value=mock_collab):
        await check_skill_access(db, skill, "user-1", CollaboratorRole.editor)


@pytest.mark.asyncio
async def test_collaborator_with_insufficient_role():
    skill = _make_skill(owner_id="other")
    db = AsyncMock()
    mock_collab = MagicMock()
    mock_collab.role = CollaboratorRole.viewer
    with patch("app.common.skill_permissions._get_collaborator", return_value=mock_collab):
        with pytest.raises(ForbiddenException):
            await check_skill_access(db, skill, "user-1", CollaboratorRole.editor)


@pytest.mark.asyncio
async def test_public_skill_viewer_access():
    skill = _make_skill(owner_id="other", is_public=True)
    db = AsyncMock()
    with patch("app.common.skill_permissions._get_collaborator", return_value=None):
        await check_skill_access(db, skill, "user-1", CollaboratorRole.viewer)


@pytest.mark.asyncio
async def test_public_skill_editor_access_denied():
    skill = _make_skill(owner_id="other", is_public=True)
    db = AsyncMock()
    with patch("app.common.skill_permissions._get_collaborator", return_value=None):
        with pytest.raises(ForbiddenException):
            await check_skill_access(db, skill, "user-1", CollaboratorRole.editor)


@pytest.mark.asyncio
async def test_token_scope_check_passes():
    skill = _make_skill(owner_id="owner-1")
    db = AsyncMock()
    await check_skill_access(
        db,
        skill,
        "owner-1",
        CollaboratorRole.viewer,
        token_scopes=["skills:read"],
        required_scope="skills:read",
    )


@pytest.mark.asyncio
async def test_token_scope_check_fails():
    skill = _make_skill(owner_id="owner-1")
    db = AsyncMock()
    with pytest.raises(ForbiddenException):
        await check_skill_access(
            db,
            skill,
            "owner-1",
            CollaboratorRole.viewer,
            token_scopes=["skills:read"],
            required_scope="skills:write",
        )
