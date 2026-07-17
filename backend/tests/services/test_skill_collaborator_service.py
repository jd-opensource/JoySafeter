"""Unit tests for SkillCollaboratorService (S1).

Mirrors the project-member management service: idempotent grant/upsert, revoke,
list, and the read helper. Also pins the str-enum storage footgun — the stored
role must be the plain vocabulary string ("admin"), never an enum repr.
"""

import uuid

import pytest
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterSkill,
    JoySafeterSkillCollaborator,
)
from app.joysafeter_domain.services.joysafeter_skill_collaborator_service import (
    SkillCollaboratorService,
)


async def _user(db_session, *, name: str = "U") -> AuthUser:
    user = AuthUser(id=f"user-{uuid.uuid4()}", name=name, email=f"{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    return user


async def _skill(db_session, *, owner_id: str) -> JoySafeterSkill:
    skill = JoySafeterSkill(
        name=f"skill-{uuid.uuid4()}",
        description="test skill",
        content="# Skill",
        tags=[],
        created_by_id=owner_id,
        owner_id=owner_id,
    )
    db_session.add(skill)
    await db_session.flush()
    return skill


@pytest.mark.asyncio
async def test_grant_stores_plain_vocabulary_string(db_session):
    owner = await _user(db_session, name="Owner")
    collab = await _user(db_session, name="Collab")
    skill = await _skill(db_session, owner_id=owner.id)

    svc = SkillCollaboratorService(db_session)
    row = await svc.grant_collaborator(
        skill_id=skill.id, user_id=collab.id, role="admin", invited_by=owner.id, commit=True
    )
    assert row.role == "admin"
    assert row.invited_by == owner.id

    # Reload from the DB to prove persistence stored the plain string, not an
    # enum repr like "JoySafeterCollaboratorRole.ADMIN". Capture the id before
    # expiring so the assertion doesn't lazy-load the expired ORM object.
    row_id = row.id
    db_session.expire_all()
    reloaded_role = (
        await db_session.execute(
            select(JoySafeterSkillCollaborator.role).where(JoySafeterSkillCollaborator.id == row_id)
        )
    ).scalar_one()
    assert reloaded_role == "admin"


@pytest.mark.asyncio
async def test_grant_is_idempotent_and_updates_role(db_session):
    owner = await _user(db_session, name="Owner")
    collab = await _user(db_session, name="Collab")
    skill = await _skill(db_session, owner_id=owner.id)

    svc = SkillCollaboratorService(db_session)
    first = await svc.grant_collaborator(
        skill_id=skill.id, user_id=collab.id, role="viewer", invited_by=owner.id, commit=True
    )
    second = await svc.grant_collaborator(
        skill_id=skill.id, user_id=collab.id, role="editor", invited_by=owner.id, commit=True
    )
    assert first.id == second.id
    assert second.role == "editor"

    rows = (
        (
            await db_session.execute(
                select(JoySafeterSkillCollaborator).where(JoySafeterSkillCollaborator.skill_id == skill.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_grant_folds_legacy_publisher_to_admin(db_session):
    owner = await _user(db_session, name="Owner")
    collab = await _user(db_session, name="Collab")
    skill = await _skill(db_session, owner_id=owner.id)

    svc = SkillCollaboratorService(db_session)
    row = await svc.grant_collaborator(
        skill_id=skill.id, user_id=collab.id, role="publisher", invited_by=owner.id, commit=True
    )
    assert row.role == "admin"


@pytest.mark.asyncio
async def test_revoke_returns_true_then_false(db_session):
    owner = await _user(db_session, name="Owner")
    collab = await _user(db_session, name="Collab")
    skill = await _skill(db_session, owner_id=owner.id)

    svc = SkillCollaboratorService(db_session)
    await svc.grant_collaborator(skill_id=skill.id, user_id=collab.id, role="editor", invited_by=owner.id, commit=True)
    assert await svc.revoke_collaborator(skill_id=skill.id, user_id=collab.id, commit=True) is True
    assert await svc.revoke_collaborator(skill_id=skill.id, user_id=collab.id, commit=True) is False


@pytest.mark.asyncio
async def test_list_collaborators_returns_rows_with_users(db_session):
    owner = await _user(db_session, name="Owner")
    collab = await _user(db_session, name="Collab")
    skill = await _skill(db_session, owner_id=owner.id)

    svc = SkillCollaboratorService(db_session)
    await svc.grant_collaborator(skill_id=skill.id, user_id=collab.id, role="editor", invited_by=owner.id, commit=True)
    listed = await svc.list_collaborators(skill.id)
    assert len(listed) == 1
    row, user = listed[0]
    assert row.user_id == collab.id
    assert user is not None and user.id == collab.id


@pytest.mark.asyncio
async def test_get_collaborator_role(db_session):
    owner = await _user(db_session, name="Owner")
    collab = await _user(db_session, name="Collab")
    skill = await _skill(db_session, owner_id=owner.id)

    svc = SkillCollaboratorService(db_session)
    assert await svc.get_collaborator_role(skill.id, collab.id) is None
    await svc.grant_collaborator(skill_id=skill.id, user_id=collab.id, role="admin", invited_by=owner.id, commit=True)
    assert await svc.get_collaborator_role(skill.id, collab.id) == "admin"
