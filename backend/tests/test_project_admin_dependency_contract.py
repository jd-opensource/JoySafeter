"""Project-member mutations must be gated by a declarative project-admin dependency.

Adding/removing a project member is scoped to the PATH project_id (which may
differ from the caller's active-context project), and requires admin OF THAT
project. This was enforced by an inline `_require_project_admin_actor` call on
top of a read-level dependency — easy for a future endpoint to copy the read
dependency and forget the manual check. `require_joysafeter_project_admin`
promotes it to a declarative dependency scoped to the path project.
"""

from types import SimpleNamespace

import pytest
from fastapi.params import Depends

from app.joysafeter_api.api.v1 import auth
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth import dependencies as deps
from app.joysafeter_shared.ids import ApiKeyId, OrganizationId, ProjectId, UserId

pytestmark = pytest.mark.no_db

USER_ID = UserId.from_public("user_00000000-0000-0000-0000-000000000001")
ORG_ID = OrganizationId.from_public("org_00000000-0000-0000-0000-000000000001")
ACTIVE_PROJECT_ID = ProjectId.from_public("proj_00000000-0000-0000-0000-000000000001")
PATH_PROJECT_ID = ProjectId.from_public("proj_00000000-0000-0000-0000-000000000002")


def _dependency_for(handler, parameter_name: str = "auth_ctx"):
    default = handler.__signature__.parameters[parameter_name].default if hasattr(handler, "__signature__") else None
    if default is None:
        import inspect

        default = inspect.signature(handler).parameters[parameter_name].default
    assert isinstance(default, Depends)
    return default.dependency


def _ctx(role: JoySafeterRole, *, principal_type: str = "user") -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=USER_ID,
        org_id=ORG_ID,
        project_id=ACTIVE_PROJECT_ID,
        role=role,
        principal_type=principal_type,
    )


def _patch_role(monkeypatch, role_value, *, expect_project_id=None):
    async def fake_project(self, project_id, org_id):
        if expect_project_id is not None:
            assert project_id == expect_project_id, "project lookup must use the PATH project_id"
        return SimpleNamespace(archived_at=None)

    async def fake_role(self, project_id, user_id):
        if expect_project_id is not None:
            assert project_id == expect_project_id, "check must be scoped to the PATH project_id"
        return role_value

    monkeypatch.setattr(deps.ProjectService, "get_project", fake_project)
    monkeypatch.setattr(deps.ProjectService, "get_project_member_role", fake_role)


@pytest.mark.asyncio
async def test_project_viewer_is_rejected(monkeypatch):
    _patch_role(monkeypatch, "viewer")
    with pytest.raises(AppError) as exc_info:
        await deps.require_joysafeter_project_admin(PATH_PROJECT_ID, db=object(), ctx=_ctx(JoySafeterRole.MEMBER))
    assert exc_info.value.code == "JOYSAFETER_PROJECT_ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_project_admin_of_path_project_is_allowed(monkeypatch):
    _patch_role(monkeypatch, "admin", expect_project_id=PATH_PROJECT_ID)
    result = await deps.require_joysafeter_project_admin(PATH_PROJECT_ID, db=object(), ctx=_ctx(JoySafeterRole.MEMBER))
    assert result.user_id == USER_ID


@pytest.mark.asyncio
async def test_project_admin_is_rejected_for_archived_path_project(monkeypatch):
    async def fake_project(self, project_id, org_id):
        return SimpleNamespace(archived_at="2026-08-23T00:00:00Z")

    async def fake_role(self, project_id, user_id):
        return "admin"

    monkeypatch.setattr(deps.ProjectService, "get_project", fake_project)
    monkeypatch.setattr(deps.ProjectService, "get_project_member_role", fake_role)

    with pytest.raises(AppError) as exc_info:
        await deps.require_joysafeter_project_admin(
            PATH_PROJECT_ID,
            db=object(),
            ctx=_ctx(JoySafeterRole.MEMBER),
        )

    assert exc_info.value.code == "PROJECT_ARCHIVED"


@pytest.mark.asyncio
async def test_org_superuser_allowed_without_project_row(monkeypatch):
    _patch_role(monkeypatch, None)
    result = await deps.require_joysafeter_project_admin(PATH_PROJECT_ID, db=object(), ctx=_ctx(JoySafeterRole.OWNER))
    assert result.user_id == USER_ID


@pytest.mark.asyncio
async def test_api_key_principal_is_rejected(monkeypatch):
    _patch_role(monkeypatch, "admin")
    with pytest.raises(AppError) as exc_info:
        await deps.require_joysafeter_project_admin(
            PATH_PROJECT_ID, db=object(), ctx=_ctx(JoySafeterRole.MEMBER, principal_type="api_key")
        )
    assert exc_info.value.code == "JOYSAFETER_USER_SESSION_REQUIRED"


@pytest.mark.asyncio
async def test_dependency_reads_project_id_from_path_via_fastapi(monkeypatch):
    """Prove FastAPI injects the route's {project_id} into the dependency, so a
    viewer is gated on the PATH project (the direct-call unit tests above cannot
    verify the framework wiring)."""
    import httpx
    from fastapi import Depends, FastAPI

    from app.joysafeter_shared.common.exceptions import register_exception_handlers
    from app.joysafeter_shared.database import get_db

    seen: dict[str, ProjectId] = {}

    async def fake_role(self, project_id, user_id):
        seen["project_id"] = project_id
        return "viewer"

    async def fake_project(self, project_id, org_id):
        return SimpleNamespace(archived_at=None)

    monkeypatch.setattr(deps.ProjectService, "get_project", fake_project)
    monkeypatch.setattr(deps.ProjectService, "get_project_member_role", fake_role)

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/projects/{project_id}/thing")
    async def thing(ctx: JoySafeterAuthContext = Depends(deps.require_joysafeter_project_admin)) -> dict:
        return {"ok": True}

    app.dependency_overrides[deps.get_joysafeter_auth_context] = lambda: _ctx(JoySafeterRole.MEMBER)
    app.dependency_overrides[get_db] = lambda: None

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(f"/projects/{PATH_PROJECT_ID}/thing")

    assert resp.status_code == 403
    assert resp.json()["code"] == "JOYSAFETER_PROJECT_ADMIN_REQUIRED"
    assert seen["project_id"] == PATH_PROJECT_ID


def test_project_scoped_api_key_routes_require_project_admin():
    assert _dependency_for(auth.list_project_api_keys) is deps.require_joysafeter_project_admin
    assert _dependency_for(auth.create_project_api_key) is deps.require_joysafeter_project_admin
    assert _dependency_for(auth.revoke_project_api_key) is deps.require_joysafeter_project_admin


@pytest.mark.asyncio
async def test_project_scoped_api_key_routes_use_path_project(monkeypatch):
    seen: list[tuple[str, ProjectId]] = []

    class FakeDb:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    async def fake_list(self, project_id, *, limit, after_id):
        seen.append(("list", project_id))
        return [], False

    async def fake_create(self, *, project_id, org_id, name, created_by, role, expires_at):
        from types import SimpleNamespace

        seen.append(("create", project_id))
        return (
            SimpleNamespace(
                id=ApiKeyId.from_public("apikey_00000000-0000-0000-0000-000000000001"),
                project_id=project_id,
                name=name,
                key_prefix="sk-test",
                role=role,
                created_at=None,
                expires_at=expires_at,
                revoked_at=None,
                last_used_at=None,
            ),
            "raw-key",
        )

    async def fake_revoke(self, key_id, project_id):
        from app.joysafeter_application.api_keys.service import ApiKeyRevokeResult

        seen.append(("revoke", project_id))
        return ApiKeyRevokeResult.REVOKED

    async def fake_project_role(self, project_id, user_id):
        return "admin"

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(auth.ApiKeyService, "list_project_keys_page", fake_list)
    monkeypatch.setattr(auth.ApiKeyService, "create_api_key", fake_create)
    monkeypatch.setattr(auth.ApiKeyService, "revoke_key", fake_revoke)
    monkeypatch.setattr(auth.ProjectService, "get_project_member_role", fake_project_role)
    monkeypatch.setattr(auth, "audit_joysafeter_event", fake_audit)

    from starlette.requests import Request

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    ctx = _ctx(JoySafeterRole.MEMBER)
    ctx.project_role = "admin"
    db = FakeDb()
    await auth.list_project_api_keys(PATH_PROJECT_ID, db=db, auth_ctx=ctx)
    await auth.create_project_api_key(
        PATH_PROJECT_ID,
        auth.CreateApiKeyRequest(name="key", role="viewer"),
        request,
        db=db,
        auth_ctx=ctx,
    )
    await auth.revoke_project_api_key(
        PATH_PROJECT_ID,
        ApiKeyId.from_public("apikey_00000000-0000-0000-0000-000000000002"),
        request,
        db=db,
        auth_ctx=ctx,
    )

    assert seen == [
        ("list", PATH_PROJECT_ID),
        ("create", PATH_PROJECT_ID),
        ("revoke", PATH_PROJECT_ID),
    ]
