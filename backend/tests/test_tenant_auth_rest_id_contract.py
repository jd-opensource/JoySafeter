import inspect
import uuid
from typing import get_type_hints

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.joysafeter_api.api.v1 import auth as auth_api
from app.joysafeter_api.api.v1 import organizations as organizations_api
from app.joysafeter_api.api.v1 import tasks as tasks_api
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import (
    ApiKeyId,
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    UserId,
)

pytestmark = pytest.mark.no_db


def _auth_client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/auth")
    auth_context = JoySafeterAuthContext(
        user_id=UserId.new(),
        org_id=OrganizationId.new(),
        project_id=ProjectId.new(),
        role=JoySafeterRole.ADMIN,
        project_role="admin",
        is_super_user=True,
    )
    app.dependency_overrides[auth_api.get_db] = lambda: object()
    app.dependency_overrides[auth_api.require_joysafeter_user_context] = lambda: auth_context
    app.dependency_overrides[auth_api.require_joysafeter_user_admin] = lambda: auth_context
    app.dependency_overrides[auth_api.require_joysafeter_project_admin] = lambda: auth_context
    app.dependency_overrides[auth_api.require_joysafeter_platform_admin] = lambda: auth_context
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("invalid_project_id", [str(uuid.uuid4()), str(UserId.new())])
def test_project_paths_reject_noncanonical_project_ids_before_endpoint_execution(invalid_project_id: str) -> None:
    response = _auth_client().get(f"/auth/projects/{invalid_project_id}")

    assert response.status_code == 422


@pytest.mark.parametrize("invalid_user_id", [str(uuid.uuid4()), str(ProjectId.new())])
def test_platform_user_path_rejects_noncanonical_user_ids_before_endpoint_execution(invalid_user_id: str) -> None:
    response = _auth_client().put(
        f"/auth/platform/users/{invalid_user_id}",
        json={"is_super_user": True},
    )

    assert response.status_code == 422


def test_project_member_request_rejects_noncanonical_user_ids() -> None:
    for invalid_user_id in (str(uuid.uuid4()), str(ProjectId.new())):
        with pytest.raises(ValidationError):
            auth_api.AddProjectMemberRequest(user_id=invalid_user_id)


def test_auth_route_and_schema_ids_use_entity_specific_types() -> None:
    project_path_functions = (
        auth_api.list_project_api_keys,
        auth_api.create_project_api_key,
        auth_api.revoke_project_api_key,
        auth_api.get_project,
        auth_api.update_project,
        auth_api.archive_project,
        auth_api.set_default_project,
        auth_api.restore_project,
        auth_api.list_project_members,
        auth_api.add_project_member,
        auth_api.remove_project_member,
    )
    for route_function in project_path_functions:
        assert get_type_hints(route_function)["project_id"] is ProjectId

    assert get_type_hints(auth_api.remove_project_member)["user_id"] is UserId
    assert get_type_hints(auth_api.update_platform_user)["user_id"] is UserId
    assert auth_api.ProjectMemberResponse.model_fields["id"].annotation == OrganizationMemberId | None
    assert auth_api.ProjectMemberResponse.model_fields["user_id"].annotation is UserId
    assert auth_api.AddProjectMemberRequest.model_fields["user_id"].annotation is UserId
    assert auth_api.PaginatedProjectsResponse.model_fields["first_id"].annotation == ProjectId | None
    assert auth_api.PaginatedProjectsResponse.model_fields["last_id"].annotation == ProjectId | None
    assert auth_api.PaginatedApiKeysResponse.model_fields["first_id"].annotation == ApiKeyId | None
    assert auth_api.PaginatedApiKeysResponse.model_fields["last_id"].annotation == ApiKeyId | None
    assert auth_api.PaginatedProjectMembersResponse.model_fields["first_id"].annotation == OrganizationMemberId | None
    assert auth_api.PaginatedProjectMembersResponse.model_fields["last_id"].annotation == OrganizationMemberId | None
    assert auth_api.PlatformUserResponse.model_fields["id"].annotation is UserId
    assert auth_api.PaginatedPlatformUsersResponse.model_fields["first_id"].annotation == UserId | None
    assert auth_api.PaginatedPlatformUsersResponse.model_fields["last_id"].annotation == UserId | None
    assert auth_api.PlatformOrganizationResponse.model_fields["id"].annotation is OrganizationId
    assert organizations_api.OrganizationResponse.model_fields["id"].annotation is OrganizationId
    assert organizations_api.OrganizationResponse.model_fields["project_id"].annotation == ProjectId | None


def test_organization_pagination_cursors_use_entity_specific_types() -> None:
    assert get_type_hints(organizations_api.list_organizations)["after_id"] == OrganizationId | None
    assert get_type_hints(organizations_api.list_members)["after_id"] == OrganizationMemberId | None


def test_task_environment_helpers_keep_project_scope_typed() -> None:
    helper_names = (
        "_load_task_environment_or_raise",
        "_validate_task_environment_matches_existing_session",
        "_validate_idempotent_task_environment_replay",
    )
    for helper_name in helper_names:
        helper = getattr(tasks_api, helper_name)
        assert "project_id" in inspect.signature(helper).parameters
        assert get_type_hints(helper)["project_id"] == ProjectId | None
