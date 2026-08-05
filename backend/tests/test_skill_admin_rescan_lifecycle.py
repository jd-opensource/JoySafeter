import uuid

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.joysafeter_api.api.v1.skills import admin_rescan_all_skills
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterSkill,
    JoySafeterSkillLifecycleStatus,
)
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _admin_ctx(project_id: str, org_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="admin-user",
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.ADMIN,
    )


@pytest.mark.asyncio
async def test_admin_batch_rescan_skips_archived_skills_without_marking_scanning(db_session):
    org_id = f"org-{uuid.uuid4()}"
    project_id = f"proj-{uuid.uuid4()}"
    user = AuthUser(id="owner-user", name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Skill Rescan Org", slug=f"skill-rescan-{uuid.uuid4()}")
    project = Project(id=project_id, org_id=org_id, name="Skill Rescan", slug=f"skill-rescan-{uuid.uuid4()}")
    active_skill = JoySafeterSkill(
        name=f"active-rescan-skill-{uuid.uuid4()}",
        description="active skill",
        content="active content",
        owner_id="owner-user",
        created_by_id="owner-user",
        project_id=project_id,
        lifecycle_status=JoySafeterSkillLifecycleStatus.DRAFT.value,
        security_status="not_scanned",
    )
    archived_skill = JoySafeterSkill(
        name=f"archived-rescan-skill-{uuid.uuid4()}",
        description="archived skill",
        content="archived content",
        owner_id="owner-user",
        created_by_id="owner-user",
        project_id=project_id,
        lifecycle_status=JoySafeterSkillLifecycleStatus.ARCHIVED.value,
        security_status="not_scanned",
    )
    db_session.add_all([user, org, project, active_skill, archived_skill])
    await db_session.commit()
    await db_session.refresh(active_skill)
    await db_session.refresh(archived_skill)

    response = await admin_rescan_all_skills(
        BackgroundTasks(),
        ruleset_below=None,
        limit=10,
        db=db_session,
        auth_ctx=_admin_ctx(project_id, org_id),
    )

    assert response["scheduled"] == [f"skill_{active_skill.id}"]
    assert response["count"] == 1

    rows = (
        await db_session.execute(
            select(JoySafeterSkill).where(JoySafeterSkill.id.in_([active_skill.id, archived_skill.id]))
        )
    ).scalars()
    by_id = {row.id: row for row in rows}
    assert by_id[active_skill.id].security_status == "scanning"
    assert by_id[archived_skill.id].security_status == "not_scanned"
