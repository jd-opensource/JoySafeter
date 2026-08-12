"""Route-level tests for the id-based ``/credentials`` and ``/credential-groups``
APIs (P0 refactor, Task 8).

Task 8 removed the dead ``secrets``/``vaults`` routers that had blocked importing
``app.joysafeter_api.api.v1.router``, so this exercises the new routes end-to-end
through a real ``TestClient``. The full production app has a heavy lifespan and
is still mid-cutover, so instead of booting it we mount ONLY the two new routers
on a bare FastAPI app (plus the shared exception handlers, which map ``AppError``
codes to HTTP status) and override the auth + db dependencies.

Event-loop hygiene: ``TestClient`` drives the ASGI app on its OWN loop, while
``asyncpg`` connections are pinned to the loop that opened them. So the ``get_db``
override opens a FRESH session bound to TestClient's loop per request (never the
pytest-asyncio ``db_session`` fixture, which lives on a different loop). Rows
committed by one session are visible to the next, which is all these flows need.

If the shared router import itself regresses, ``test_router_imports_ok`` fails
loudly and points at the boot blocker.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.joysafeter_api.api.v1.credential_groups import router as credential_groups_router
from app.joysafeter_api.api.v1.credentials import router as credentials_router
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    JoySafeterRole,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import CredentialId


def test_router_imports_ok() -> None:
    """The shared v1 router must import (secrets/vaults cutover unblocked boot)."""
    from app.joysafeter_api.api.v1.router import joysafeter_router

    paths = {route.path for route in joysafeter_router.routes}
    assert any(p.startswith("/credentials") for p in paths)
    assert any(p.startswith("/credential-groups") for p in paths)
    # The dead name-based routes are gone.
    assert not any(p.startswith("/secrets") for p in paths)
    assert not any(p.startswith("/vaults") for p in paths)


async def _make_project(session_factory) -> str:
    async with session_factory() as session:
        org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
        session.add(org)
        await session.flush()
        project = Project(org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
        session.add(project)
        await session.commit()
        return project.id


@pytest.fixture
def client(postgres_url: str) -> Iterator[tuple[TestClient, str, async_sessionmaker]]:
    """A TestClient for a bare app mounting the two new routers.

    Yields ``(client, project_id, session_factory)`` where ``session_factory``
    opens sessions on the CURRENT (pytest) loop for direct assertions/setup, and
    the ``get_db`` override opens its own per-request sessions on TestClient's
    loop. All sessions target the same Postgres, so committed rows are shared.
    """
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    project_id = asyncio.get_event_loop().run_until_complete(_make_project(session_factory))

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(credentials_router, prefix="/credentials")
    app.include_router(credential_groups_router, prefix="/credential-groups")

    async def _override_db():
        # Fresh session bound to whatever loop TestClient is driving the app on.
        async with session_factory() as session:
            yield session

    def _override_auth() -> JoySafeterAuthContext:
        return JoySafeterAuthContext(
            user_id="test-user",
            org_id="test-org",
            project_id=project_id,
            role=JoySafeterRole.ADMIN,
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_joysafeter_auth_context] = _override_auth
    app.dependency_overrides[require_joysafeter_write] = _override_auth

    with TestClient(app) as test_client:
        yield test_client, project_id, session_factory

    asyncio.get_event_loop().run_until_complete(engine.dispose())


# --- credentials -----------------------------------------------------------------


def test_credential_create_list_get_masked_default_archive_restore(client) -> None:
    api, _project_id, _factory = client
    # create model credential
    resp = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "m1",
            "provider": "openai",
            "protocol": "openai",
            "data": {"API_KEY": "sk-supersecret", "BASE_URL": "https://api.example.com"},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    cred_id = body["id"]
    # Masked on the create response: secret masked, display-safe key cleartext.
    assert body["data"]["API_KEY"].startswith("********")
    assert "supersecret" not in body["data"]["API_KEY"]
    assert body["data"]["BASE_URL"] == "https://api.example.com"

    # list (masked)
    resp = api.get("/credentials")
    assert resp.status_code == 200, resp.text
    listed = resp.json()
    listed_item = next(item for item in listed["data"] if item["id"] == cred_id)
    assert "supersecret" not in listed_item["data"]["API_KEY"]

    # list filter by kind
    resp = api.get("/credentials", params={"kind": "mcp"})
    assert resp.status_code == 200
    assert all(item["kind"] == "mcp" for item in resp.json()["data"])

    # get (masked)
    resp = api.get(f"/credentials/{cred_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["API_KEY"].startswith("********")

    # set default
    resp = api.post(f"/credentials/{cred_id}/default")
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_default"] is True

    # archive (clears default) then restore
    resp = api.post(f"/credentials/{cred_id}/archive")
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived_at"] is not None
    assert resp.json()["is_default"] is False

    resp = api.post(f"/credentials/{cred_id}/restore")
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived_at"] is None

    # delete (not referenced) -> 204
    resp = api.delete(f"/credentials/{cred_id}")
    assert resp.status_code == 204, resp.text

    # gone
    resp = api.get(f"/credentials/{cred_id}")
    assert resp.status_code == 404


def test_credential_update_preserves_masked_value(client) -> None:
    api, _project_id, _factory = client
    resp = api.post(
        "/credentials",
        json={"kind": "service", "name": "svc1", "data": {"TOKEN": "tok-supersecret"}},
    )
    assert resp.status_code == 201, resp.text
    cred_id = resp.json()["id"]
    masked_token = resp.json()["data"]["TOKEN"]
    assert masked_token.startswith("********")

    # Re-submit the masked TOKEN; original must be kept and never leaked.
    resp = api.patch(f"/credentials/{cred_id}", json={"data": {"TOKEN": masked_token}})
    assert resp.status_code == 200, resp.text
    assert "supersecret" not in resp.json()["data"]["TOKEN"]


def test_delete_credential_in_use_returns_409(client) -> None:
    """A credential referenced by a live agent cannot be soft-deleted (409)."""
    api, project_id, session_factory = client
    resp = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "m-in-use",
            "provider": "openai",
            "protocol": "openai",
            "data": {"API_KEY": "sk-1"},
        },
    )
    assert resp.status_code == 201, resp.text
    cred_id = resp.json()["id"]

    async def _bind_agent() -> None:
        async with session_factory() as session:
            agent = JoySafeterAgent(
                project_id=project_id,
                name=f"agent-{uuid.uuid4()}",
                model_credential_id=CredentialId.from_public(cred_id),
            )
            session.add(agent)
            await session.commit()

    asyncio.get_event_loop().run_until_complete(_bind_agent())

    resp = api.delete(f"/credentials/{cred_id}")
    assert resp.status_code == 409, resp.text


# --- credential groups + membership ----------------------------------------------


def test_group_create_add_member_list_and_delete(client) -> None:
    api, _project_id, _factory = client
    # create group
    resp = api.post("/credential-groups", json={"name": "g1", "description": "first"})
    assert resp.status_code == 201, resp.text
    group_id = resp.json()["id"]

    # add mcp member
    resp = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": "m1",
            "mcp_server_url": "https://a.com/mcp",
            "data": {"AUTH_TOKEN": "tok-supersecret"},
        },
    )
    assert resp.status_code == 201, resp.text
    member = resp.json()
    member_id = member["id"]
    assert member["kind"] == "mcp"
    assert member["group_id"] == group_id
    assert "supersecret" not in member["data"]["AUTH_TOKEN"]

    # list members (masked)
    resp = api.get(f"/credential-groups/{group_id}/members")
    assert resp.status_code == 200, resp.text
    members = resp.json()["data"]
    assert [m["id"] for m in members] == [member_id]
    assert "supersecret" not in members[0]["data"]["AUTH_TOKEN"]

    # get group + list groups
    assert api.get(f"/credential-groups/{group_id}").status_code == 200
    resp = api.get("/credential-groups")
    assert resp.status_code == 200
    assert any(g["id"] == group_id for g in resp.json()["data"])

    # remove member
    resp = api.delete(f"/credential-groups/{group_id}/members/{member_id}")
    assert resp.status_code == 204, resp.text
    assert api.get(f"/credential-groups/{group_id}/members").json()["data"] == []

    # delete group (not bound to a session) -> 204
    resp = api.delete(f"/credential-groups/{group_id}")
    assert resp.status_code == 204, resp.text
    assert api.get(f"/credential-groups/{group_id}").status_code == 404


def test_group_add_member_duplicate_url_conflicts_409(client) -> None:
    api, _project_id, _factory = client
    resp = api.post("/credential-groups", json={"name": "g-dup"})
    assert resp.status_code == 201, resp.text
    group_id = resp.json()["id"]

    resp = api.post(
        f"/credential-groups/{group_id}/members",
        json={"name": "m1", "mcp_server_url": "https://example.com/mcp"},
    )
    assert resp.status_code == 201, resp.text

    # Same normalized url in the SAME group -> CREDENTIAL_GROUP_URL_CONFLICT (409).
    resp = api.post(
        f"/credential-groups/{group_id}/members",
        json={"name": "m2", "mcp_server_url": "HTTPS://Example.com:443/mcp/"},
    )
    assert resp.status_code == 409, resp.text
