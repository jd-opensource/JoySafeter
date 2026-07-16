import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_shared.common.app_errors import ResourceConflictError
from app.joysafeter_shared.utils.datetime import utc_now


@pytest.mark.asyncio
async def test_database_rejects_multiple_active_default_projects_for_same_org(db_session):
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Unique Default Org",
        slug=f"unique-default-{uuid.uuid4()}",
    )
    first_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="First Default",
        slug="first-default",
        is_default=True,
    )
    second_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Second Default",
        slug="second-default",
        is_default=True,
    )
    db_session.add_all([org, first_default, second_default])

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_database_allows_archived_legacy_default_next_to_active_default(db_session):
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Archived Legacy Default Org",
        slug=f"archived-legacy-default-{uuid.uuid4()}",
    )
    active_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Active Default",
        slug="active-default",
        is_default=True,
    )
    archived_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Archived Default",
        slug="archived-default",
        is_default=True,
        archived_at=utc_now(),
    )
    db_session.add_all([org, active_default, archived_default])
    org_id = org.id
    active_default_id = active_default.id
    archived_default_id = archived_default.id
    await db_session.commit()

    db_session.expire_all()
    rows = (
        await db_session.execute(select(Project).where(Project.org_id == org_id, Project.is_default.is_(True)))
    ).scalars().all()
    assert {row.id for row in rows} == {active_default_id, archived_default_id}


@pytest.mark.asyncio
async def test_get_default_project_ignores_archived_default(db_session):
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Archived Default Org",
        slug=f"archived-default-{uuid.uuid4()}",
    )
    archived_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Old Default",
        slug="default",
        is_default=True,
        archived_at=utc_now(),
    )
    active_project = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Active",
        slug=f"active-{uuid.uuid4()}",
        is_default=False,
    )
    db_session.add_all([org, archived_default, active_project])
    await db_session.commit()

    assert await ProjectService(db_session).get_default_project(org.id) is None


@pytest.mark.asyncio
async def test_service_set_default_project_rejects_archived_target_without_mutating_current_default(db_session):
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Set Default Org",
        slug=f"set-default-{uuid.uuid4()}",
    )
    active_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Active Default",
        slug="active-default",
        is_default=True,
    )
    archived_target = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Archived Target",
        slug="archived-target",
        archived_at=utc_now(),
    )
    db_session.add_all([org, active_default, archived_target])
    await db_session.commit()
    active_default_id = active_default.id
    archived_target_id = archived_target.id

    with pytest.raises(ResourceConflictError) as exc_info:
        await ProjectService(db_session).set_default_project(archived_target_id, org.id)

    assert exc_info.value.code == "PROJECT_ARCHIVED"
    assert exc_info.value.data == {"project_id": archived_target_id, "organization_id": org.id}

    db_session.expire_all()
    active_row = (await db_session.execute(select(Project).where(Project.id == active_default_id))).scalar_one()
    archived_row = (await db_session.execute(select(Project).where(Project.id == archived_target_id))).scalar_one()
    assert active_row.is_default is True
    assert archived_row.is_default is False


@pytest.mark.asyncio
async def test_ensure_default_project_promotes_existing_active_project_when_archived_default_exists(db_session):
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Ensure Default Org",
        slug=f"ensure-default-{uuid.uuid4()}",
    )
    archived_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Archived Default",
        slug="default",
        is_default=True,
        archived_at=utc_now(),
    )
    active_project = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Active Candidate",
        slug=f"active-candidate-{uuid.uuid4()}",
        is_default=False,
    )
    db_session.add_all([org, archived_default, active_project])
    await db_session.commit()
    archived_default_id = archived_default.id
    active_project_id = active_project.id

    resolved = await ProjectService(db_session).ensure_default_project(org.id)

    assert resolved.id == active_project_id
    db_session.expire_all()
    archived_row = (await db_session.execute(select(Project).where(Project.id == archived_default_id))).scalar_one()
    active_row = (await db_session.execute(select(Project).where(Project.id == active_project_id))).scalar_one()
    assert archived_row.is_default is False
    assert active_row.is_default is True


@pytest.mark.asyncio
async def test_restore_project_unarchives_without_changing_active_default(db_session):
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Restore Org",
        slug=f"restore-org-{uuid.uuid4()}",
    )
    active_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Active Default",
        slug="active-default",
        is_default=True,
    )
    archived_project = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Archived Project",
        slug="archived-project",
        archived_at=utc_now(),
    )
    db_session.add_all([org, active_default, archived_project])
    await db_session.commit()
    active_default_id = active_default.id
    archived_project_id = archived_project.id

    restored = await ProjectService(db_session).restore_project(archived_project_id, org.id)

    assert restored.id == archived_project_id
    assert restored.archived_at is None
    assert restored.is_default is False
    db_session.expire_all()
    active_row = (await db_session.execute(select(Project).where(Project.id == active_default_id))).scalar_one()
    restored_row = (await db_session.execute(select(Project).where(Project.id == archived_project_id))).scalar_one()
    assert active_row.is_default is True
    assert restored_row.archived_at is None


@pytest.mark.asyncio
async def test_restore_archived_legacy_default_demotes_when_active_default_exists(db_session):
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Legacy Restore Org",
        slug=f"legacy-restore-org-{uuid.uuid4()}",
    )
    active_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Active Default",
        slug="active-default",
        is_default=True,
    )
    archived_default = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Archived Legacy Default",
        slug="legacy-default",
        is_default=True,
        archived_at=utc_now(),
    )
    db_session.add_all([org, active_default, archived_default])
    await db_session.commit()
    active_default_id = active_default.id
    archived_default_id = archived_default.id

    restored = await ProjectService(db_session).restore_project(archived_default_id, org.id)

    assert restored.id == archived_default_id
    assert restored.archived_at is None
    assert restored.is_default is False
    db_session.expire_all()
    active_row = (await db_session.execute(select(Project).where(Project.id == active_default_id))).scalar_one()
    restored_row = (await db_session.execute(select(Project).where(Project.id == archived_default_id))).scalar_one()
    assert active_row.is_default is True
    assert restored_row.is_default is False
