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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.joysafeter_api.api.v1.credential_groups import router as credential_groups_router
from app.joysafeter_api.api.v1.credentials import router as credentials_router
from app.joysafeter_application.credentials.composition import CredentialApplication
from app.joysafeter_application.credentials.resource_service import credential_nudge_failures
from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    DependencyDisposition,
)
from app.joysafeter_domain.credentials.types import CredentialId as DomainCredentialId
from app.joysafeter_domain.credentials.types import ProjectId
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_infrastructure.credentials import network_policy_adapter
from app.joysafeter_infrastructure.credentials.audit_adapter import SqlAlchemyCredentialAuditAdapter
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    JoySafeterRole,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.config.settings import settings
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


def test_deleted_resource_routes_fail_closed_without_clearing_live_default(client) -> None:
    api, _project_id, _factory = client
    live_default_id = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "route-live-default",
            "provider": "openai",
            "protocol": "openai",
            "data": {"API_KEY": "live"},
            "is_default": True,
        },
    ).json()["id"]
    deleted_id = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "route-deleted-default",
            "provider": "openai",
            "protocol": "openai",
            "data": {"API_KEY": "deleted"},
        },
    ).json()["id"]
    assert api.delete(f"/credentials/{deleted_id}").status_code == 204

    responses = (
        api.patch(f"/credentials/{deleted_id}", json={"name": "must-not-change"}),
        api.post(f"/credentials/{deleted_id}/default"),
    )
    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "CREDENTIAL_NOT_FOUND"
        assert api.get(f"/credentials/{live_default_id}").json()["is_default"] is True


def test_credential_list_filters_archived_before_pagination_without_changing_default(client) -> None:
    api, _project_id, _factory = client
    active = api.post(
        "/credentials",
        json={"kind": "service", "name": "active-service", "data": {"TOKEN": "active"}},
    )
    assert active.status_code == 201, active.text
    active_id = active.json()["id"]

    archived = api.post(
        "/credentials",
        json={"kind": "service", "name": "archived-service", "data": {"TOKEN": "old"}},
    )
    assert archived.status_code == 201, archived.text
    archived_id = archived.json()["id"]
    assert api.post(f"/credentials/{archived_id}/archive").status_code == 200

    response = api.get(
        "/credentials",
        params={"kind": "service", "limit": 1, "include_archived": False},
    )
    assert response.status_code == 200, response.text
    assert [credential["id"] for credential in response.json()["data"]] == [active_id]
    assert response.json()["has_more"] is False

    response = api.get(
        "/credentials",
        params={"kind": "service", "limit": 2, "include_archived": True},
    )
    assert response.status_code == 200, response.text
    assert {credential["id"] for credential in response.json()["data"]} == {
        active_id,
        archived_id,
    }

    response = api.get("/credentials", params={"kind": "service", "limit": 2})
    assert response.status_code == 200, response.text
    assert {credential["id"] for credential in response.json()["data"]} == {
        active_id,
        archived_id,
    }


def test_credential_create_rolls_back_when_audit_write_fails(client, monkeypatch) -> None:
    api, project_id, session_factory = client

    async def fail_log_event(self, entry):
        raise RuntimeError("audit db unavailable")

    monkeypatch.setattr(SqlAlchemyCredentialAuditAdapter, "append", fail_log_event)

    with pytest.raises(RuntimeError, match="audit db unavailable"):
        api.post(
            "/credentials",
            json={
                "kind": "service",
                "name": "must-rollback",
                "data": {"TOKEN": "secret"},
            },
        )

    async def load_credential():
        async with session_factory() as session:
            result = await session.execute(
                select(JoySafeterCredential.id).where(
                    JoySafeterCredential.project_id == project_id,
                    JoySafeterCredential.name == "must-rollback",
                )
            )
            return result.scalar_one_or_none()

    assert asyncio.get_event_loop().run_until_complete(load_credential()) is None


def test_credential_list_filters_and_compat_fields(client) -> None:
    """The list endpoint restores the old /secrets server-side filters
    (compatible_engine / provider / protocol / name) and the response carries the
    catalog-derived ``model`` + ``compatible_engine_ids`` a model picker needs."""
    api, _project_id, _factory = client

    # Model cred A: openai/openai_responses -> engines include 'codex', model from OPENAI_MODEL.
    a = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "openai-a",
            "provider": "openai",
            "protocol": "openai_responses",
            "data": {"API_KEY": "sk-a", "OPENAI_MODEL": "gpt-5.5"},
        },
    )
    assert a.status_code == 201, a.text
    a_body = a.json()
    assert a_body["model"] == "gpt-5.5"
    assert "codex" in a_body["compatible_engine_ids"]
    assert "claude" not in a_body["compatible_engine_ids"]

    # Model cred B: anthropic/anthropic_messages -> engines include 'claude'.
    b = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "anthropic-b",
            "provider": "anthropic",
            "protocol": "anthropic_messages",
            "data": {"API_KEY": "sk-b"},
        },
    )
    assert b.status_code == 201, b.text
    b_body = b.json()
    assert "claude" in b_body["compatible_engine_ids"]

    # compatible_engine filter discriminates between the two.
    codex_ids = {i["id"] for i in api.get("/credentials", params={"compatible_engine": "codex"}).json()["data"]}
    assert a_body["id"] in codex_ids
    assert b_body["id"] not in codex_ids
    claude_ids = {i["id"] for i in api.get("/credentials", params={"compatible_engine": "claude"}).json()["data"]}
    assert b_body["id"] in claude_ids
    assert a_body["id"] not in claude_ids

    # provider filter.
    prov = api.get("/credentials", params={"provider": "openai"}).json()["data"]
    assert all(i["provider"] == "openai" for i in prov)
    assert a_body["id"] in {i["id"] for i in prov}
    assert b_body["id"] not in {i["id"] for i in prov}

    # name filter (exact, against the normalized stored name).
    named = api.get("/credentials", params={"name": a_body["name"]}).json()["data"]
    assert [i["id"] for i in named] == [a_body["id"]]

    # is_default sorts first.
    api.post(f"/credentials/{a_body['id']}/default")
    model_list = api.get("/credentials", params={"kind": "model"}).json()["data"]
    assert model_list[0]["id"] == a_body["id"]

    # Unknown provider/protocol list filters surface semantic errors, not empty pages.
    r = api.get("/credentials", params={"provider": "bogus"})
    assert r.status_code == 400
    assert r.json()["code"] == "LLM_PROVIDER_UNKNOWN"
    r = api.get("/credentials", params={"protocol": "bogus"})
    assert r.status_code == 400
    assert r.json()["code"] == "LLM_PROTOCOL_UNKNOWN"


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


def test_credential_update_nudges_live_sandbox_after_commit(client, monkeypatch) -> None:
    api, project_id, session_factory = client
    response = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "nudge-model",
            "provider": "openai",
            "protocol": "openai",
            "data": {"API_KEY": "sk-old"},
        },
    )
    assert response.status_code == 201, response.text
    credential_id = response.json()["id"]

    async def create_sandbox():
        async with session_factory() as session:
            sandbox = JoySafeterSandbox(
                project_id=project_id,
                image="test-image:latest",
                status="running",
                networking_status="ready",
                config={"fingerprint": {"networking": {"type": "limited"}}},
            )
            session.add(sandbox)
            await session.commit()
            return str(sandbox.id)

    sandbox_id = asyncio.get_event_loop().run_until_complete(create_sandbox())
    nudged: list[str] = []

    async def record_nudge(target_sandbox_ids, **kwargs):
        nudged.extend(str(target_sandbox_id) for target_sandbox_id in target_sandbox_ids)
        return len(target_sandbox_ids)
        return len(target_sandbox_ids)

    monkeypatch.setattr(
        network_policy_adapter,
        "nudge_sandbox_network_policy_refreshes",
        record_nudge,
    )

    response = api.patch(
        f"/credentials/{credential_id}",
        json={"data": {"API_KEY": "sk-new"}},
    )
    assert response.status_code == 200, response.text
    assert nudged == [sandbox_id]


def test_nudge_failure_is_observable_and_does_not_change_success_response(client, monkeypatch, caplog) -> None:
    api, _project_id, _factory = client
    credential_id = api.post(
        "/credentials",
        json={
            "kind": "service",
            "name": "nudge-failure",
            "data": {"TOKEN": "old"},
        },
    ).json()["id"]

    async def fail_nudge(self):
        raise RuntimeError("relay unavailable")

    monkeypatch.setattr(network_policy_adapter.SqlAlchemyCredentialImpactAdapter, "nudge_after_commit", fail_nudge)
    before = credential_nudge_failures["after_commit"]
    response = api.patch(
        f"/credentials/{credential_id}",
        json={"data": {"TOKEN": "new"}},
    )

    assert response.status_code == 200, response.text
    assert credential_nudge_failures["after_commit"] == before + 1
    assert "credential impact nudge failed after commit" in caplog.text


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
    resp = api.post(
        "/credential-groups",
        json={
            "name": "g1",
            "description": "first",
            "metadata": {"owner": "platform"},
        },
    )
    assert resp.status_code == 201, resp.text
    group_id = resp.json()["id"]
    assert resp.json()["metadata"] == {"owner": "platform"}

    # add mcp member
    resp = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": "m1",
            "mcp_server_url": "https://a.com/mcp",
            "data": {"token_value": "tok-supersecret"},
        },
    )
    assert resp.status_code == 201, resp.text
    member = resp.json()
    member_id = member["id"]
    assert member["kind"] == "mcp"
    assert member["group_id"] == group_id
    assert "supersecret" not in member["data"]["token_value"]

    # list members (masked)
    resp = api.get(f"/credential-groups/{group_id}/members")
    assert resp.status_code == 200, resp.text
    members = resp.json()["data"]
    assert [m["id"] for m in members] == [member_id]
    assert "supersecret" not in members[0]["data"]["token_value"]

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


def test_group_update_name_and_description(client) -> None:
    api, _project_id, _factory = client
    response = api.post(
        "/credential-groups",
        json={"name": "before", "description": "old"},
    )
    assert response.status_code == 201, response.text
    group_id = response.json()["id"]

    response = api.patch(
        f"/credential-groups/{group_id}",
        json={
            "name": "after",
            "description": "new",
            "metadata": {"purpose": "mcp"},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "after"
    assert response.json()["description"] == "new"
    assert response.json()["metadata"] == {"purpose": "mcp"}


def test_group_list_filters_archived_before_pagination(client) -> None:
    api, _project_id, _factory = client
    archived = api.post("/credential-groups", json={"name": "archived-group"})
    assert archived.status_code == 201, archived.text
    archived_id = archived.json()["id"]
    assert api.post(f"/credential-groups/{archived_id}/archive").status_code == 200

    active = api.post("/credential-groups", json={"name": "active-group"})
    assert active.status_code == 201, active.text
    active_id = active.json()["id"]

    response = api.get("/credential-groups", params={"limit": 1})
    assert response.status_code == 200, response.text
    assert [group["id"] for group in response.json()["data"]] == [active_id]
    assert response.json()["has_more"] is False

    response = api.get(
        "/credential-groups",
        params={"limit": 2, "include_archived": True},
    )
    assert response.status_code == 200, response.text
    assert {group["id"] for group in response.json()["data"]} == {
        active_id,
        archived_id,
    }


def test_group_restore_endpoint_and_duplicate_lifecycle_requests_are_idempotent(client) -> None:
    api, _project_id, _factory = client
    created = api.post("/credential-groups", json={"name": "restore-endpoint"})
    group_id = created.json()["id"]

    first_archive = api.post(f"/credential-groups/{group_id}/archive")
    second_archive = api.post(f"/credential-groups/{group_id}/archive")
    assert first_archive.status_code == second_archive.status_code == 200

    first_restore = api.post(f"/credential-groups/{group_id}/restore")
    second_restore = api.post(f"/credential-groups/{group_id}/restore")
    assert first_restore.status_code == second_restore.status_code == 200
    assert first_restore.json()["archived_at"] is None
    assert second_restore.json()["archived_at"] is None


def test_generic_and_group_member_endpoints_share_archived_group_decision(client) -> None:
    api, _project_id, _factory = client
    group_id = api.post("/credential-groups", json={"name": "shared-policy"}).json()["id"]
    member_id = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": "shared-policy-member",
            "mcp_server_url": "https://shared-policy.example.com/mcp",
            "data": {"token_value": "secret"},
        },
    ).json()["id"]
    assert api.post(f"/credential-groups/{group_id}/archive").status_code == 200

    generic = api.post(f"/credentials/{member_id}/archive")
    member = api.post(f"/credential-groups/{group_id}/members/{member_id}/archive")
    assert generic.status_code == member.status_code == 409
    assert generic.json()["code"] == member.json()["code"] == "CREDENTIAL_GROUP_ARCHIVED"


@pytest.mark.parametrize(
    ("generic_method", "generic_suffix", "member_method", "member_suffix"),
    [
        ("post", "/archive", "post", "/archive"),
        ("delete", "", "delete", ""),
    ],
)
def test_generic_and_group_member_lifecycle_share_registry_enforce_authority(
    client,
    monkeypatch,
    generic_method,
    generic_suffix,
    member_method,
    member_suffix,
) -> None:
    api, project_id, _factory = client
    group_id = api.post("/credential-groups", json={"name": f"registry-group-{generic_method}"}).json()["id"]
    member_id = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": f"registry-member-{generic_method}",
            "mcp_server_url": f"https://registry-{generic_method}.example.com/mcp",
            "data": {"token_value": "secret"},
        },
    ).json()["id"]

    scanner_calls: list[str] = []

    async def registry_only_blocker(self, scan_project_id, scan_credential_id):
        assert str(scan_project_id) == project_id
        assert str(scan_credential_id) == member_id
        scanner_calls.append(str(scan_credential_id))
        return (
            CredentialDependency(
                surface_id="registry_only_test_surface",
                project_id=ProjectId(project_id),
                source_id="registry-only-session",
                credential_id=DomainCredentialId(member_id),
                group_id=None,
                dispositions=frozenset(
                    {
                        DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
                        DependencyDisposition.BLOCK_RESOURCE_DELETE,
                    }
                ),
            ),
        )

    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "enforce")
    monkeypatch.setattr(
        CredentialApplication,
        "scan_resource_dependencies",
        registry_only_blocker,
    )

    generic = getattr(api, generic_method)(f"/credentials/{member_id}{generic_suffix}")
    member = getattr(api, member_method)(f"/credential-groups/{group_id}/members/{member_id}{member_suffix}")

    assert generic.status_code == member.status_code == 409
    assert generic.json()["code"] == member.json()["code"] == "CREDENTIAL_IN_USE"
    assert generic.json()["data"] == member.json()["data"]
    assert scanner_calls == [member_id, member_id]


@pytest.mark.parametrize(
    ("generic_method", "generic_suffix", "member_method", "member_suffix"),
    [
        ("post", "/archive", "post", "/archive"),
        ("delete", "", "delete", ""),
    ],
)
def test_archived_member_group_precedes_registry_blocker_for_both_endpoints(
    client,
    monkeypatch,
    generic_method,
    generic_suffix,
    member_method,
    member_suffix,
) -> None:
    api, project_id, _factory = client
    group_id = api.post("/credential-groups", json={"name": f"priority-group-{generic_method}"}).json()["id"]
    member_id = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": f"priority-member-{generic_method}",
            "mcp_server_url": f"https://priority-{generic_method}.example.com/mcp",
            "data": {"token_value": "secret"},
        },
    ).json()["id"]
    assert api.post(f"/credential-groups/{group_id}/archive").status_code == 200
    scanner_calls: list[str] = []

    async def registry_only_blocker(self, scan_project_id, scan_credential_id):
        assert str(scan_project_id) == project_id
        assert str(scan_credential_id) == member_id
        scanner_calls.append(str(scan_credential_id))
        return (
            CredentialDependency(
                surface_id="registry_only_priority_surface",
                project_id=ProjectId(project_id),
                source_id="registry-only-priority-session",
                credential_id=DomainCredentialId(member_id),
                group_id=None,
                dispositions=frozenset(
                    {
                        DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
                        DependencyDisposition.BLOCK_RESOURCE_DELETE,
                    }
                ),
            ),
        )

    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "enforce")
    monkeypatch.setattr(CredentialApplication, "scan_resource_dependencies", registry_only_blocker)

    generic = getattr(api, generic_method)(f"/credentials/{member_id}{generic_suffix}")
    member = getattr(api, member_method)(f"/credential-groups/{group_id}/members/{member_id}{member_suffix}")

    assert generic.status_code == member.status_code == 409
    assert generic.json()["code"] == member.json()["code"] == "CREDENTIAL_GROUP_ARCHIVED"
    assert generic.json()["data"] == member.json()["data"] == {"credential_group_id": group_id}
    assert scanner_calls == []


@pytest.mark.parametrize(
    ("member_method", "member_suffix"),
    [("post", "/archive"), ("delete", "")],
)
def test_wrong_group_membership_precedes_registry_observation(
    client,
    monkeypatch,
    member_method,
    member_suffix,
) -> None:
    api, project_id, _factory = client
    owning_group_id = api.post("/credential-groups", json={"name": f"owning-{member_method}"}).json()["id"]
    wrong_group_id = api.post("/credential-groups", json={"name": f"wrong-{member_method}"}).json()["id"]
    member_id = api.post(
        f"/credential-groups/{owning_group_id}/members",
        json={
            "name": f"wrong-membership-{member_method}",
            "mcp_server_url": f"https://wrong-membership-{member_method}.example.com/mcp",
            "data": {"token_value": "secret"},
        },
    ).json()["id"]
    assert api.post(f"/credential-groups/{wrong_group_id}/archive").status_code == 200
    scanner_calls: list[str] = []

    async def registry_only_blocker(self, scan_project_id, scan_credential_id):
        assert str(scan_project_id) == project_id
        scanner_calls.append(str(scan_credential_id))
        return ()

    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "enforce")
    monkeypatch.setattr(CredentialApplication, "scan_resource_dependencies", registry_only_blocker)

    response = getattr(api, member_method)(f"/credential-groups/{wrong_group_id}/members/{member_id}{member_suffix}")

    assert response.status_code == 404
    assert response.json()["code"] == "CREDENTIAL_NOT_FOUND"
    assert response.json()["data"] == {
        "credential_id": member_id,
        "credential_group_id": wrong_group_id,
    }
    assert scanner_calls == []


def test_group_member_create_rolls_back_when_audit_write_fails(client, monkeypatch) -> None:
    api, project_id, session_factory = client
    response = api.post("/credential-groups", json={"name": "atomic-group"})
    assert response.status_code == 201, response.text
    group_id = response.json()["id"]

    async def fail_log_event(self, entry):
        raise RuntimeError("audit db unavailable")

    monkeypatch.setattr(SqlAlchemyCredentialAuditAdapter, "append", fail_log_event)

    with pytest.raises(RuntimeError, match="audit db unavailable"):
        api.post(
            f"/credential-groups/{group_id}/members",
            json={
                "name": "member-must-rollback",
                "mcp_server_url": "https://atomic.example.com/mcp",
                "data": {"token_value": "secret"},
            },
        )

    async def load_credential():
        async with session_factory() as session:
            result = await session.execute(
                select(JoySafeterCredential.id).where(
                    JoySafeterCredential.project_id == project_id,
                    JoySafeterCredential.name == "member-must-rollback",
                )
            )
            return result.scalar_one_or_none()

    assert asyncio.get_event_loop().run_until_complete(load_credential()) is None


def test_group_add_member_duplicate_url_conflicts_409(client) -> None:
    api, _project_id, _factory = client
    resp = api.post("/credential-groups", json={"name": "g-dup"})
    assert resp.status_code == 201, resp.text
    group_id = resp.json()["id"]

    resp = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": "m1",
            "mcp_server_url": "https://example.com/mcp",
            "data": {"token_value": "t"},
        },
    )
    assert resp.status_code == 201, resp.text

    # Same normalized url in the SAME group -> CREDENTIAL_GROUP_URL_CONFLICT (409).
    resp = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": "m2",
            "mcp_server_url": "HTTPS://Example.com:443/mcp/",
            "data": {"token_value": "t"},
        },
    )
    assert resp.status_code == 409, resp.text


def test_group_add_member_rejects_non_http_url(client) -> None:
    api, _project_id, _factory = client
    response = api.post("/credential-groups", json={"name": "g-url-scheme"})
    assert response.status_code == 201, response.text
    group_id = response.json()["id"]

    response = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": "bad-url",
            "mcp_server_url": "file:///etc/passwd",
            "data": {"token_value": "t"},
        },
    )

    assert response.status_code == 422, response.text


def test_group_add_member_rejects_invalid_url_port(client) -> None:
    api, _project_id, _factory = client
    response = api.post("/credential-groups", json={"name": "g-url-port"})
    assert response.status_code == 201, response.text
    group_id = response.json()["id"]

    response = api.post(
        f"/credential-groups/{group_id}/members",
        json={
            "name": "bad-port",
            "mcp_server_url": "https://example.com:not-a-port/mcp",
            "data": {"token_value": "t"},
        },
    )

    assert response.status_code == 422, response.text
