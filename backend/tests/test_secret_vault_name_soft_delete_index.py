import pytest
from sqlalchemy.exc import IntegrityError

from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_vault import JoySafeterVault
from app.joysafeter_shared.utils.datetime import utc_now


async def _ensure_project(db_session, project_id: str) -> None:
    org = await db_session.get(Organization, "org-idx")
    if not org:
        db_session.add(Organization(id="org-idx", name="Org Idx", slug="org-idx"))
    if not await db_session.get(Project, project_id):
        db_session.add(Project(id=project_id, org_id="org-idx", name=project_id, slug=project_id, is_default=False))
    await db_session.commit()


@pytest.mark.asyncio
async def test_secret_name_reusable_after_soft_delete_within_project(db_session):
    # The partial unique index must exclude soft-deleted rows. Insert a
    # soft-deleted secret and then a live one with the SAME (project_id, name).
    # Without `AND deleted_at IS NULL` in the index predicate the second insert
    # raises IntegrityError.
    await _ensure_project(db_session, "proj-idx")

    db_session.add(JoySafeterSecret(name="shared", project_id="proj-idx", deleted_at=utc_now()))
    await db_session.commit()

    db_session.add(JoySafeterSecret(name="shared", project_id="proj-idx", deleted_at=None))
    await db_session.commit()

    # Two LIVE rows with the same (project_id, name) must still collide.
    db_session.add(JoySafeterSecret(name="shared", project_id="proj-idx", deleted_at=None))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_vault_name_reusable_after_soft_delete_within_project(db_session):
    await _ensure_project(db_session, "proj-idx")

    db_session.add(JoySafeterVault(name="creds", project_id="proj-idx", deleted_at=utc_now()))
    await db_session.commit()

    db_session.add(JoySafeterVault(name="creds", project_id="proj-idx", deleted_at=None))
    await db_session.commit()

    db_session.add(JoySafeterVault(name="creds", project_id="proj-idx", deleted_at=None))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
