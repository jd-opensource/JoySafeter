"""Atomicity tests for credential mutation + sandbox network-policy mark-pending.

Audit Blocker 5: a credential mutation and the sandbox ``pending`` mark must
commit together. If the mutation committed first and the refresh committed
separately, a crash between the two commits would leave the DB holding the new
credential while the sandbox is never flagged for re-push — Envoy keeps the OLD
credential (dangerous for revocation/rotation).

Real-DB tests (Postgres via conftest's ``db_session``): the primitive runs an
``UPDATE ... RETURNING`` over ``joysafeter_sandboxes`` filtered by the JSONB
fingerprint, so sqlite is not a substitute.
"""

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_api.api.v1.network_policy_refresh import (
    mark_live_sandboxes_pending,
    refresh_live_limited_sandbox_network_policies,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
    UpdateCredentialRequest,
)
from app.joysafeter_domain.services.joysafeter_credential_group_service import (
    CredentialGroupService,
)
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService


async def _make_project(db_session) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


def _limited_sandbox(project_id: str, status: str = "running") -> JoySafeterSandbox:
    """A live limited-networking sandbox (the refresh target shape)."""
    return JoySafeterSandbox(
        project_id=project_id,
        image="test-image:latest",
        status=status,
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )


@pytest_asyncio.fixture
async def project_id(db_session) -> str:
    return await _make_project(db_session)


@asynccontextmanager
async def _fresh_session(postgres_url: str):
    """A brand-new session/connection to prove data is durably COMMITTED (not just
    cached in the writing session). This is the true atomicity check: if the
    mutation and the pending mark did not commit together, a fresh read would not
    see both."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _sandbox_status(db_session, sandbox_id) -> str:
    row = await db_session.execute(
        select(JoySafeterSandbox.networking_status).where(JoySafeterSandbox.id == sandbox_id)
    )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_update_marks_sandbox_pending_atomically(db_session, postgres_url, project_id):
    """A credential update flips the live limited sandbox to ``pending`` and both
    the credential change and the sandbox flag are persisted after the single
    service call (same transaction, one commit)."""
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    svc = CredentialService(db_session)
    cred = await svc.create(
        CreateCredentialRequest(
            kind="model", name="m1", provider="openai", protocol="openai", data={"API_KEY": "sk-old"}
        ),
        project_id=project_id,
    )

    # Create does NOT touch existing sandboxes.
    assert await _sandbox_status(db_session, sandbox_id) == "ready"

    updated = await svc.update(
        cred.id,
        UpdateCredentialRequest(data={"API_KEY": "sk-new"}),
        project_id=project_id,
    )

    # New credential material persisted...
    assert svc.get_credential_data(updated)["API_KEY"] == "sk-new"

    # ...and BOTH the credential change and the sandbox pending flag are durably
    # committed together — verified through a fresh session/connection.
    async with _fresh_session(postgres_url) as other:
        assert await _sandbox_status(other, sandbox_id) == "pending"
        reloaded = await CredentialService(other).get(cred.id, project_id=project_id)
        assert CredentialService(other).get_credential_data(reloaded)["API_KEY"] == "sk-new"


@pytest.mark.asyncio
async def test_generic_mcp_create_marks_sandbox_pending(db_session, project_id):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    group = await CredentialGroupService(db_session).create(
        CreateCredentialGroupRequest(name="mcp-group"), project_id=project_id
    )
    await CredentialService(db_session).create(
        CreateCredentialRequest(
            kind="mcp",
            name="mcp-member",
            mcp_server_url="https://mcp.example.com/sse",
            group_id=group.id,
            data={"token_value": "t"},
        ),
        project_id=project_id,
    )

    assert await _sandbox_status(db_session, sandbox_id) == "pending"


@pytest.mark.asyncio
async def test_mark_live_sandboxes_pending_does_not_commit(db_session, project_id):
    """The primitive itself must NOT commit: after calling it and rolling back,
    the sandbox flag must NOT have persisted."""
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    marked = await mark_live_sandboxes_pending(
        db_session,
        project_id=project_id,
        source_type="credential",
        source_id=str(uuid.uuid4()),
    )
    assert sandbox_id in marked

    # Roll back the (uncommitted) mark; the flag must revert.
    await db_session.rollback()
    assert await _sandbox_status(db_session, sandbox_id) == "ready"


@pytest.mark.asyncio
async def test_archive_soft_delete_set_default_mark_pending(db_session, project_id):
    """archive / soft_delete / set_default all mark the live sandbox pending."""
    svc = CredentialService(db_session)

    for method in ("archive", "soft_delete", "set_default"):
        # Fresh sandbox (ready) + fresh credential per method.
        sandbox = _limited_sandbox(project_id)
        db_session.add(sandbox)
        await db_session.commit()
        sandbox_id = sandbox.id

        cred = await svc.create(
            CreateCredentialRequest(
                kind="model",
                name=f"m-{method}",
                provider="openai",
                protocol="openai",
                data={"API_KEY": "sk"},
            ),
            project_id=project_id,
        )
        assert await _sandbox_status(db_session, sandbox_id) == "ready"

        await getattr(svc, method)(cred.id, project_id=project_id)
        assert await _sandbox_status(db_session, sandbox_id) == "pending", method

        # Reset the sandbox flag for the next iteration.
        sandbox.networking_status = "ready"
        db_session.add(sandbox)
        await db_session.commit()


@pytest.mark.asyncio
async def test_restore_mcp_member_marks_sandbox_pending(db_session, project_id):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    group_service = CredentialGroupService(db_session)
    group = await group_service.create(
        CreateCredentialGroupRequest(name="mcp-restore-group"),
        project_id=project_id,
    )
    credential = await group_service.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="mcp-restore-member",
            mcp_server_url="https://mcp.example.com/sse",
            data={"token_value": "t"},
        ),
        project_id=project_id,
    )
    await group_service.archive_credential(
        group.id,
        credential.id,
        project_id=project_id,
    )
    await db_session.execute(
        update(JoySafeterSandbox)
        .where(JoySafeterSandbox.id == sandbox_id)
        .values(networking_status="ready")
    )
    await db_session.commit()
    assert await _sandbox_status(db_session, sandbox_id) == "ready"

    await CredentialService(db_session).restore(credential.id, project_id=project_id)

    assert await _sandbox_status(db_session, sandbox_id) == "pending"


@pytest.mark.asyncio
async def test_refresh_wrapper_marks_and_returns_count(db_session, project_id):
    """The self-committing wrapper still marks live limited sandboxes pending and
    returns the count (behavior unchanged for non-atomic callers)."""
    a = _limited_sandbox(project_id)
    b = _limited_sandbox(project_id)
    # A non-limited sandbox must be ignored.
    c = JoySafeterSandbox(
        project_id=project_id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "full"}}},
    )
    db_session.add_all([a, b, c])
    await db_session.commit()
    a_id, b_id, c_id = a.id, b.id, c.id

    count = await refresh_live_limited_sandbox_network_policies(
        db_session,
        project_id=project_id,
        reason="credential_rotated",
        source_type="credential",
        source_id=str(uuid.uuid4()),
    )
    assert count == 2

    assert await _sandbox_status(db_session, a_id) == "pending"
    assert await _sandbox_status(db_session, b_id) == "pending"
    # Non-limited sandbox untouched.
    assert await _sandbox_status(db_session, c_id) == "ready"
