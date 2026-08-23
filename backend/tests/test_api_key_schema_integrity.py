import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project


async def _seed_identity(db_session):
    suffix = uuid.uuid4().hex
    user_id = f"user-{suffix}"
    org_id = f"org-{suffix}"
    project_id = f"project-{suffix}"
    db_session.add_all(
        [
            AuthUser(id=user_id, name="User", email=f"{suffix}@example.test"),
            Organization(id=org_id, name="Org", slug=f"org-{suffix}"),
            Project(id=project_id, org_id=org_id, name="Project", slug=f"project-{suffix}", is_default=False),
        ]
    )
    await db_session.commit()
    return user_id, org_id, project_id


@pytest.mark.asyncio
async def test_api_key_hash_is_unique(db_session):
    user_id, org_id, project_id = await _seed_identity(db_session)
    values = {"user_id": user_id, "org_id": org_id, "project_id": project_id, "key_hash": uuid.uuid4().hex}
    statement = text(
        "INSERT INTO joysafeter_api_keys "
        "(id, project_id, org_id, name, key_hash, key_prefix, created_by, role) "
        "VALUES (:id, :project_id, :org_id, 'key', :key_hash, 'cnkey_probe', :user_id, 'viewer')"
    )
    await db_session.execute(statement, {**values, "id": uuid.uuid4()})
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(statement, {**values, "id": uuid.uuid4()})
        await db_session.commit()


@pytest.mark.asyncio
async def test_api_key_project_and_org_must_match(db_session):
    user_id, org_id, project_id = await _seed_identity(db_session)
    other_org_id = f"org-{uuid.uuid4().hex}"
    db_session.add(Organization(id=other_org_id, name="Other", slug=other_org_id))
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO joysafeter_api_keys "
                "(id, project_id, org_id, name, key_hash, key_prefix, created_by, role) "
                "VALUES (:id, :project_id, :org_id, 'key', :key_hash, 'cnkey_probe', :user_id, 'viewer')"
            ),
            {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "org_id": other_org_id,
                "key_hash": uuid.uuid4().hex,
                "user_id": user_id,
            },
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_api_key_constraints_and_active_list_index_exist(db_session):
    constraint_names = set(
        (
            await db_session.execute(
                text("SELECT conname FROM pg_constraint WHERE conrelid = 'joysafeter_api_keys'::regclass")
            )
        ).scalars()
    )
    index_names = set(
        (
            await db_session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'joysafeter_api_keys'"))
        ).scalars()
    )

    assert "fk_api_keys_project_org" in constraint_names
    assert any(name.endswith("api_keys_role") for name in constraint_names)
    assert any(name.endswith("api_keys_name") for name in constraint_names)
    assert any(name.endswith("api_keys_expiry") for name in constraint_names)
    assert "uq_api_keys_key_hash" in index_names
    assert "ix_api_keys_active_project_created_id" in index_names
