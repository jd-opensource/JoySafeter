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

    db_session.add(
        JoySafeterSecret(
            name="shared",
            kind="generic",
            provider=None,
            protocol=None,
            project_id="proj-idx",
            deleted_at=utc_now(),
        )
    )
    await db_session.commit()

    db_session.add(
        JoySafeterSecret(
            name="shared", kind="generic", provider=None, protocol=None, project_id="proj-idx", deleted_at=None
        )
    )
    await db_session.commit()

    # Two LIVE rows with the same (project_id, name) must still collide.
    db_session.add(
        JoySafeterSecret(
            name="shared", kind="generic", provider=None, protocol=None, project_id="proj-idx", deleted_at=None
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_create_secret_duplicate_active_name_raises_conflict(db_session):
    # A duplicate ACTIVE (project_id, name) must surface as a clean 409-style
    # ResourceConflictError, not a raw IntegrityError bubbling up to a 500.
    from app.joysafeter_domain.schemas.joysafeter_secret import CreateSecretRequest
    from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
    from app.joysafeter_shared.common.app_errors import ResourceConflictError

    await _ensure_project(db_session, "proj-idx")
    svc = SecretService(db_session)
    await svc.create_secret(
        CreateSecretRequest(kind="generic", name="dup", data={"WEBHOOK_SECRET": "x"}),
        project_id="proj-idx",
    )

    with pytest.raises(ResourceConflictError) as exc_info:
        await svc.create_secret(
            CreateSecretRequest(kind="generic", name="dup", data={"WEBHOOK_SECRET": "y"}),
            project_id="proj-idx",
        )
    assert exc_info.value.code == "SECRET_NAME_EXISTS"


@pytest.mark.asyncio
async def test_secret_name_conflicts_use_canonical_create_and_update_names(db_session):
    from app.joysafeter_domain.schemas.joysafeter_secret import CreateSecretRequest, UpdateSecretRequest
    from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
    from app.joysafeter_shared.common.app_errors import ResourceConflictError

    await _ensure_project(db_session, "proj-idx")
    svc = SecretService(db_session)
    first = await svc.create_secret(
        CreateSecretRequest(kind="generic", name="canonical", data={"TOKEN": "first"}),
        project_id="proj-idx",
    )
    second = await svc.create_secret(
        CreateSecretRequest(kind="generic", name="second", data={"TOKEN": "second"}),
        project_id="proj-idx",
    )
    first_id = first.id
    second_id = second.id

    with pytest.raises(ResourceConflictError) as create_error:
        await svc.create_secret(
            CreateSecretRequest(kind="generic", name="  canonical  ", data={"TOKEN": "third"}),
            project_id="proj-idx",
        )
    assert create_error.value.code == "SECRET_NAME_EXISTS"
    assert create_error.value.data == {"name": "canonical"}

    with pytest.raises(ResourceConflictError) as update_error:
        await svc.update_secret(
            second_id,
            UpdateSecretRequest(name=" canonical ", data={"TOKEN": "second"}),
            project_id="proj-idx",
        )
    assert update_error.value.code == "SECRET_NAME_EXISTS"
    assert update_error.value.data == {"name": "canonical"}

    db_session.expire_all()
    assert (await db_session.get(JoySafeterSecret, first_id)).name == "canonical"
    assert (await db_session.get(JoySafeterSecret, second_id)).name == "second"


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
