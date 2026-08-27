"""Regression tests for OAuth material erasure on credential deletion.

Real-DB tests (Postgres via conftest's ``db_session``): the invariant under test
is a database CHECK constraint plus the repository delete paths, so sqlite is not
a substitute.

Context: OAuth-backed MCP credentials store their ``client_secret``/``refresh_token``
ciphertext in the ``oauth_config`` column, which the integrity/inventory tooling
already treats as protected material. Terminal deletion must therefore clear
``oauth_config`` in the same transaction and the ``deleted_material_erased`` CHECK
must reject any deleted row that still carries OAuth material — otherwise
``material_erased_at`` would falsely claim the material was erased.

These tests deliberately populate ``oauth_config`` directly (there is no service
writer for it yet — it is populated by the MCP OAuth flow), mirroring how the
integrity tooling reasons about the column, so the erasure invariant is proven
independently of whichever path first writes the column.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.joysafeter_application.credentials.application_service import CredentialGroupService
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
)
from app.joysafeter_shared.ids import OrganizationId, ProjectId
from app.joysafeter_shared.utils.datetime import utc_now

_OAUTH_MATERIAL = {
    "client_secret": "enc:v2:test-key:Y2xpZW50LXNlY3JldA==",
    "refresh_token": "enc:v2:test-key:cmVmcmVzaC10b2tlbg==",
}


async def _make_project(db_session) -> str:
    org = Organization(id=OrganizationId.new(), name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(id=ProjectId.new(), org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> str:
    return await _make_project(db_session)


async def _add_oauth_member(db_session, svc, project_id, *, group_name, member_name, url):
    """Create an MCP group with a member and populate its oauth_config directly.

    There is no service-layer writer for oauth_config today, so we write it with a
    raw UPDATE — exactly the surface the integrity/inventory tooling protects.
    """
    group = await svc.create(CreateCredentialGroupRequest(name=group_name), project_id=project_id)
    member = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name=member_name, mcp_server_url=url, data={"token_value": "t"}),
        project_id=project_id,
    )
    await db_session.execute(
        update(JoySafeterCredential).where(JoySafeterCredential.id == member.id).values(oauth_config=_OAUTH_MATERIAL)
    )
    await db_session.commit()
    return group, member


async def _oauth_config_of(db_session, credential_id):
    return (
        await db_session.execute(
            select(JoySafeterCredential.oauth_config).where(JoySafeterCredential.id == credential_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_direct_member_delete_erases_oauth_config(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group, member = await _add_oauth_member(
        db_session, svc, project_id, group_name="g-direct", member_name="m", url="https://a.example.com/mcp"
    )
    assert await _oauth_config_of(db_session, member.id) == _OAUTH_MATERIAL

    await svc.remove_credential(group.id, member.id, project_id=project_id)

    stored = (
        await db_session.execute(
            select(
                JoySafeterCredential.data,
                JoySafeterCredential.oauth_config,
                JoySafeterCredential.material_erased_at,
                JoySafeterCredential.deleted_at,
            ).where(JoySafeterCredential.id == member.id)
        )
    ).one()
    assert stored.deleted_at is not None
    assert stored.material_erased_at is not None
    assert stored.data == {}
    # The defect: oauth_config must be cleared, not left decryptable.
    assert stored.oauth_config is None


@pytest.mark.asyncio
async def test_group_delete_erases_member_oauth_config(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group, member = await _add_oauth_member(
        db_session, svc, project_id, group_name="g-cascade", member_name="m", url="https://b.example.com/mcp"
    )
    assert await _oauth_config_of(db_session, member.id) == _OAUTH_MATERIAL

    await svc.soft_delete(group.id, project_id=project_id)

    stored = (
        await db_session.execute(
            select(
                JoySafeterCredential.data,
                JoySafeterCredential.oauth_config,
                JoySafeterCredential.material_erased_at,
                JoySafeterCredential.deleted_at,
            ).where(JoySafeterCredential.id == member.id)
        )
    ).one()
    assert stored.deleted_at is not None
    assert stored.material_erased_at is not None
    assert stored.data == {}
    assert stored.oauth_config is None


@pytest.mark.asyncio
async def test_deleted_row_retaining_oauth_material_is_rejected_by_check(db_session, project_id):
    """A deleted, material_erased row that still carries oauth_config must be
    rejected by the database, not silently accepted. This locks the invariant
    itself: material_erased_at may only be set when every material-bearing column
    (data AND oauth_config) is empty."""
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    _group, member = await _add_oauth_member(
        db_session, svc, project_id, group_name="g-check", member_name="m", url="https://c.example.com/mcp"
    )
    now = utc_now()
    with pytest.raises(IntegrityError):
        await db_session.execute(
            update(JoySafeterCredential)
            .where(JoySafeterCredential.id == member.id)
            .values(data={}, material_erased_at=now, deleted_at=now, updated_at=now)
            # oauth_config intentionally left populated
        )
        await db_session.commit()
    await db_session.rollback()
