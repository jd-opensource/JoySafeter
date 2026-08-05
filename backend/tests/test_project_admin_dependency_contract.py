"""Project-member mutations must be gated by a declarative project-admin dependency.

Adding/removing a project member is scoped to the PATH project_id (which may
differ from the caller's active-context project), and requires admin OF THAT
project. This was enforced by an inline `_require_project_admin_actor` call on
top of a read-level dependency — easy for a future endpoint to copy the read
dependency and forget the manual check. `require_joysafeter_project_admin`
promotes it to a declarative dependency scoped to the path project.
"""

import pytest

from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth import dependencies as deps

pytestmark = pytest.mark.no_db


def _ctx(role: JoySafeterRole, *, principal_type: str = "user") -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="u", org_id="o", project_id="active-proj", role=role, principal_type=principal_type
    )


def _patch_role(monkeypatch, role_value, *, expect_project_id=None):
    async def fake_role(self, project_id, user_id):
        if expect_project_id is not None:
            assert project_id == expect_project_id, "check must be scoped to the PATH project_id"
        return role_value

    monkeypatch.setattr(deps.ProjectService, "get_project_member_role", fake_role)


@pytest.mark.asyncio
async def test_project_viewer_is_rejected(monkeypatch):
    _patch_role(monkeypatch, "viewer")
    with pytest.raises(AppError) as exc_info:
        await deps.require_joysafeter_project_admin("path-proj", db=object(), ctx=_ctx(JoySafeterRole.MEMBER))
    assert exc_info.value.code == "JOYSAFETER_PROJECT_ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_project_admin_of_path_project_is_allowed(monkeypatch):
    _patch_role(monkeypatch, "admin", expect_project_id="path-proj")
    result = await deps.require_joysafeter_project_admin("path-proj", db=object(), ctx=_ctx(JoySafeterRole.MEMBER))
    assert result.user_id == "u"


@pytest.mark.asyncio
async def test_org_superuser_allowed_without_project_row(monkeypatch):
    _patch_role(monkeypatch, None)
    result = await deps.require_joysafeter_project_admin("path-proj", db=object(), ctx=_ctx(JoySafeterRole.OWNER))
    assert result.user_id == "u"


@pytest.mark.asyncio
async def test_api_key_principal_is_rejected(monkeypatch):
    _patch_role(monkeypatch, "admin")
    with pytest.raises(AppError) as exc_info:
        await deps.require_joysafeter_project_admin(
            "path-proj", db=object(), ctx=_ctx(JoySafeterRole.MEMBER, principal_type="api_key")
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

    seen: dict[str, str] = {}

    async def fake_role(self, project_id, user_id):
        seen["project_id"] = project_id
        return "viewer"

    monkeypatch.setattr(deps.ProjectService, "get_project_member_role", fake_role)

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/projects/{project_id}/thing")
    async def thing(ctx: JoySafeterAuthContext = Depends(deps.require_joysafeter_project_admin)) -> dict:
        return {"ok": True}

    app.dependency_overrides[deps.get_joysafeter_auth_context] = lambda: _ctx(JoySafeterRole.MEMBER)
    app.dependency_overrides[get_db] = lambda: None

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/projects/proj-from-path/thing")

    assert resp.status_code == 403
    assert resp.json()["code"] == "JOYSAFETER_PROJECT_ADMIN_REQUIRED"
    assert seen["project_id"] == "proj-from-path"
