from __future__ import annotations

import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from starlette.requests import Request

from app.joysafeter_api.api.v1.auth import get_me
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_shared.common.app_errors import AccessDeniedError, AuthenticationError, ResourceConflictError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth import dependencies as auth_deps
from app.joysafeter_shared.utils.datetime import utc_now


def _request_with_headers(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/agents",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        },
    )


@pytest.mark.asyncio
async def test_cookie_auth_rejects_explicit_unknown_project_instead_of_falling_back(
    db_session,
    monkeypatch,
):
    user = AuthUser(
        id=f"user-{uuid.uuid4()}",
        email=f"user-{uuid.uuid4()}@example.com",
        name="Project User",
    )
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Org",
        slug=f"org-{uuid.uuid4()}",
    )
    default_project = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all(
        [
            user,
            org,
            Member(user_id=user.id, organization_id=org.id, role="admin"),
            default_project,
        ],
    )
    await db_session.commit()

    async def fake_get_current_user(**_kwargs):
        return user

    monkeypatch.setattr(auth_deps, "get_current_user", fake_get_current_user)

    request = _request_with_headers(
        {
            "Authorization": "Bearer session-token",
            "X-Org-Id": org.id,
            "X-Project-Id": f"project-{uuid.uuid4()}",
        },
    )

    with pytest.raises(AuthenticationError) as exc_info:
        await auth_deps._auth_via_user_session(request, db_session)

    assert exc_info.value.code == "PROJECT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_cookie_auth_keeps_explicit_archived_project_for_read_context_instead_of_falling_back(
    db_session,
    monkeypatch,
):
    user = AuthUser(
        id=f"user-{uuid.uuid4()}",
        email=f"user-{uuid.uuid4()}@example.com",
        name="Project User",
    )
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name="Org",
        slug=f"org-{uuid.uuid4()}",
    )
    default_project = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    archived_project = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=org.id,
        name="Archived",
        slug="archived",
        archived_at=utc_now(),
    )
    db_session.add_all(
        [
            user,
            org,
            Member(user_id=user.id, organization_id=org.id, role="admin"),
            default_project,
            archived_project,
        ],
    )
    await db_session.commit()

    async def fake_get_current_user(**_kwargs):
        return user

    monkeypatch.setattr(auth_deps, "get_current_user", fake_get_current_user)

    request = _request_with_headers(
        {
            "Authorization": "Bearer session-token",
            "X-Org-Id": org.id,
            "X-Project-Id": archived_project.id,
        },
    )

    ctx = await auth_deps._auth_via_user_session(request, db_session)

    assert ctx is not None
    assert ctx.project_id == archived_project.id
    me = await get_me(db_session, ctx)
    assert me["project"]["id"] == archived_project.id
    assert me["project"]["archived_at"] is not None
    assert archived_project.id not in {project["id"] for project in me["projects"]}

    with pytest.raises(ResourceConflictError) as exc_info:
        await auth_deps.require_joysafeter_write(request, db_session, ctx)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ARCHIVED",
        "message": "项目已归档，仅支持只读操作 / Project is archived and read-only",
        "data": None,
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_user_context_dependency_rejects_project_scoped_api_keys():
    ctx = JoySafeterAuthContext(
        user_id="user-api-key-owner",
        org_id="org-a",
        project_id="project-a",
        role=JoySafeterRole.ADMIN,
        principal_type="api_key",
    )

    with pytest.raises(AccessDeniedError) as exc_info:
        await auth_deps.require_joysafeter_user_context(ctx)

    assert exc_info.value.code == "JOYSAFETER_USER_SESSION_REQUIRED"
