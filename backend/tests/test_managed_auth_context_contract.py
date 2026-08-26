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
from app.joysafeter_shared.ids import OrganizationId, OrganizationMemberId, ProjectId, UserId
from app.joysafeter_shared.security import create_access_token
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


@pytest.mark.no_db
def test_auth_context_rejects_string_identity_bridges():
    with pytest.raises(TypeError, match="user_id must be UserId"):
        JoySafeterAuthContext(
            user_id=str(UserId.new()),
            org_id=OrganizationId.new(),
            project_id=ProjectId.new(),
            role=JoySafeterRole.ADMIN,
        )


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_jwt_auth_rejects_invalid_project_header_before_database_access():
    user_id = UserId.new()
    organization_id = OrganizationId.new()
    project_id = ProjectId.new()
    token = create_access_token(
        subject=user_id,
        org_id=organization_id,
        project_id=project_id,
        role="admin",
    )
    request = _request_with_headers(
        {
            "Authorization": f"Bearer {token}",
            "X-Project-Id": str(project_id.uuid),
        }
    )

    class NoDatabaseAccess:
        async def execute(self, *args, **kwargs):
            raise AssertionError("invalid path ID reached the repository boundary")

    with pytest.raises(AuthenticationError) as exc_info:
        await auth_deps._auth_via_jwt_claims(request, NoDatabaseAccess())

    assert exc_info.value.code == "INVALID_PROJECT_ID"


@pytest.mark.asyncio
async def test_jwt_auth_rejects_explicit_unknown_project_instead_of_falling_back(db_session):
    user = AuthUser(
        id=UserId.new(),
        email=f"user-{uuid.uuid4()}@example.com",
        name="Project User",
    )
    org = Organization(
        id=OrganizationId.new(),
        name="Org",
        slug=f"org-{uuid.uuid4()}",
    )
    default_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all(
        [
            user,
            org,
            Member(
                id=OrganizationMemberId.new(),
                user_id=user.id,
                organization_id=org.id,
                role="admin",
            ),
            default_project,
        ],
    )
    await db_session.commit()

    token = create_access_token(
        subject=user.id,
        org_id=org.id,
        project_id=default_project.id,
        role="admin",
    )

    request = _request_with_headers(
        {
            "Authorization": f"Bearer {token}",
            "X-Org-Id": str(org.id),
            "X-Project-Id": str(ProjectId.new()),
        },
    )

    with pytest.raises(AuthenticationError) as exc_info:
        await auth_deps._auth_via_jwt_claims(request, db_session)

    assert exc_info.value.code == "PROJECT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_jwt_auth_keeps_explicit_archived_project_for_read_context(db_session):
    user = AuthUser(
        id=UserId.new(),
        email=f"user-{uuid.uuid4()}@example.com",
        name="Project User",
    )
    org = Organization(
        id=OrganizationId.new(),
        name="Org",
        slug=f"org-{uuid.uuid4()}",
    )
    default_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    archived_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Archived",
        slug="archived",
        archived_at=utc_now(),
    )
    db_session.add_all(
        [
            user,
            org,
            Member(
                id=OrganizationMemberId.new(),
                user_id=user.id,
                organization_id=org.id,
                role="admin",
            ),
            default_project,
            archived_project,
        ],
    )
    await db_session.commit()

    token = create_access_token(
        subject=user.id,
        org_id=org.id,
        project_id=default_project.id,
        role="admin",
    )

    request = _request_with_headers(
        {
            "Authorization": f"Bearer {token}",
            "X-Org-Id": str(org.id),
            "X-Project-Id": str(archived_project.id),
        },
    )

    ctx = await auth_deps._auth_via_jwt_claims(request, db_session)

    assert ctx is not None
    assert ctx.project_id == archived_project.id
    me = await get_me(db_session, ctx)
    assert me.project.id == archived_project.id
    assert me.project.archived_at is not None
    assert archived_project.id not in {project.id for project in me.projects}

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
        user_id=UserId.new(),
        org_id=OrganizationId.new(),
        project_id=ProjectId.new(),
        role=JoySafeterRole.ADMIN,
        principal_type="api_key",
    )

    with pytest.raises(AccessDeniedError) as exc_info:
        await auth_deps.require_joysafeter_user_context(ctx)

    assert exc_info.value.code == "JOYSAFETER_USER_SESSION_REQUIRED"
