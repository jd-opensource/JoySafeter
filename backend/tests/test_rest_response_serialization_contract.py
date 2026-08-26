from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.joysafeter_api.api.v1 import auth as auth_api
from app.joysafeter_api.api.v1 import organizations as organizations_api
from app.joysafeter_api.api.v1.middleware import ApiV1ResponseWrapperMiddleware
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse
from app.joysafeter_domain.services.joysafeter_auth_service import IssuedLoginTokens
from app.joysafeter_shared.common.dependencies import get_current_user
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import OrganizationId, ProjectId, UserId

pytestmark = pytest.mark.no_db


class _TypedUserPayload(BaseModel):
    id: UserId


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _RowsResult:
    def __init__(self, rows: list[tuple[object, object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object, object]]:
        return self._rows


class _AuthMeDatabase:
    def __init__(
        self, user: object, organization: object, membership_rows: list[tuple[object, object, object]]
    ) -> None:
        self._results = iter(
            (
                _ScalarResult(user),
                _ScalarResult(organization),
                _RowsResult(membership_rows),
            )
        )

    async def execute(self, _statement: object) -> object:
        return next(self._results)


def _assert_no_empty_object(value: object) -> None:
    if isinstance(value, dict):
        assert value != {}
        for nested_value in value.values():
            _assert_no_empty_object(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _assert_no_empty_object(nested_value)


def test_raw_entity_id_dictionary_loses_transport_type_information() -> None:
    user_id = UserId.new()
    app = FastAPI()

    @app.get("/raw")
    async def raw():
        return {"id": user_id}

    assert TestClient(app).get("/raw").json() == {"id": {}}


def test_typed_response_model_preserves_entity_id_serialization() -> None:
    user_id = UserId.new()
    app = FastAPI()

    @app.get("/typed")
    async def typed() -> _TypedUserPayload:
        return _TypedUserPayload(id=user_id)

    assert TestClient(app).get("/typed").json() == {"id": str(user_id)}


def test_cursor_page_preserves_and_validates_its_concrete_id_type() -> None:
    user_id = UserId.new()
    page = CursorPaginatedResponse[_TypedUserPayload, UserId](
        data=[_TypedUserPayload(id=user_id)],
        has_more=False,
        first_id=user_id,
        last_id=user_id,
    )

    assert page.first_id is user_id
    assert page.model_dump(mode="json")["first_id"] == str(user_id)

    with pytest.raises(ValidationError):
        CursorPaginatedResponse[_TypedUserPayload, UserId](
            data=[],
            has_more=False,
            first_id=ProjectId.new(),
        )


def test_api_routes_do_not_construct_unparameterized_cursor_pages() -> None:
    api_directory = Path(__file__).parents[1] / "app" / "joysafeter_api" / "api" / "v1"
    violations: list[str] = []

    for path in sorted(api_directory.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id in {"CursorPaginatedResponse", "PaginatedResponse"}:
                violations.append(f"{path.name}:{node.lineno}")

    assert not violations, "Unparameterized cursor page construction:\n" + "\n".join(violations)


def test_organization_creation_has_one_canonical_route_owner() -> None:
    auth_paths = {route.path for route in auth_api.router.routes}
    organization_paths = {route.path for route in organizations_api.router.routes}

    assert "/organizations" not in auth_paths
    assert "" in organization_paths


def test_auth_me_serializes_every_tenant_id_through_the_registered_route(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = UserId.new()
    organization_id = OrganizationId.new()
    project_id = ProjectId.new()
    now = datetime.now(timezone.utc)
    user = SimpleNamespace(id=user_id, email="owner@example.com", name="Owner")
    organization = SimpleNamespace(
        id=organization_id,
        name="Example Org",
        slug="example-org",
        project_creation_policy="admins_only",
        created_at=now,
    )
    project = SimpleNamespace(
        id=project_id,
        org_id=organization_id,
        name="Main",
        slug="main",
        is_default=True,
        archived_at=None,
    )
    membership = SimpleNamespace(role="owner")
    database = _AuthMeDatabase(user, organization, [(membership, organization, user)])
    auth_context = JoySafeterAuthContext(
        user_id=user_id,
        org_id=organization_id,
        project_id=project_id,
        role=JoySafeterRole.OWNER,
        project_role=None,
    )

    class _ProjectService:
        def __init__(self, _database: object) -> None:
            pass

        async def get_accessible_project(self, **_kwargs: object) -> object:
            return project

        async def list_accessible_projects(self, **_kwargs: object) -> list[object]:
            return [project]

    monkeypatch.setattr(auth_api, "ProjectService", _ProjectService)

    app = FastAPI()
    app.add_middleware(ApiV1ResponseWrapperMiddleware)
    app.include_router(auth_api.router, prefix="/api/v1/auth")
    app.dependency_overrides[auth_api.get_db] = lambda: database
    app.dependency_overrides[auth_api.require_joysafeter_user_context] = lambda: auth_context

    response = TestClient(app).get("/api/v1/auth/me")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["user"]["id"] == str(user_id)
    assert payload["organization"]["id"] == str(organization_id)
    assert payload["project"]["id"] == str(project_id)
    assert payload["project"]["org_id"] == str(organization_id)
    assert payload["organizations"][0]["id"] == str(organization_id)
    assert payload["projects"][0]["id"] == str(project_id)
    assert payload["projects"][0]["org_id"] == str(organization_id)
    _assert_no_empty_object(payload)


@pytest.mark.parametrize(
    ("path", "service_method", "body"),
    (
        ("/api/v1/auth/sign-in/email", "login", {"email": "owner@example.com", "password": "Secret123!"}),
        (
            "/api/v1/auth/sign-up/email",
            "register",
            {"email": "owner@example.com", "name": "Owner", "password": "Secret123!"},
        ),
    ),
)
def test_identity_entrypoints_serialize_user_id(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    service_method: str,
    body: dict[str, str],
) -> None:
    user_id = UserId.new()
    now = datetime.now(timezone.utc)
    user = SimpleNamespace(
        id=user_id,
        email="owner@example.com",
        name="Owner",
        image=None,
        email_verified=False,
        is_super_user=False,
        created_at=now,
        updated_at=now,
    )
    result = IssuedLoginTokens(
        user=user,
        access_token="access-token",
        refresh_token="refresh-token",
        csrf_token="csrf-token",
        access_expires_at=now + timedelta(minutes=15),
        refresh_expires_at=now + timedelta(days=7),
    )

    async def _result(*_args: object, **_kwargs: object) -> IssuedLoginTokens:
        return result

    monkeypatch.setattr(auth_api.AuthService, service_method, _result)

    app = FastAPI()
    app.add_middleware(ApiV1ResponseWrapperMiddleware)
    app.include_router(auth_api.router, prefix="/api/v1/auth")
    app.dependency_overrides[auth_api.get_db] = lambda: object()

    response = TestClient(app).post(path, json=body)

    assert response.status_code == 200
    assert response.json()["data"]["user"]["id"] == str(user_id)


class _OrganizationDatabase:
    def __init__(self, organization: object, owner: object) -> None:
        self._organization = organization
        self._owner = owner

    async def execute(self, _statement: object) -> object:
        organization = self._organization
        owner = self._owner

        class _Result:
            def one_or_none(self) -> tuple[object, object]:
                return organization, owner

            def scalar_one_or_none(self) -> object:
                return organization

        return _Result()

    async def commit(self) -> None:
        pass

    async def refresh(self, _value: object) -> None:
        pass


def test_organization_mutation_and_detail_routes_serialize_typed_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = UserId.new()
    new_owner_user_id = UserId.new()
    organization_id = OrganizationId.new()
    project_id = ProjectId.new()
    now = datetime.now(timezone.utc)
    current_user = SimpleNamespace(
        id=user_id,
        name="Owner",
        email="owner@example.com",
    )
    organization = SimpleNamespace(
        id=organization_id,
        name="Example Org",
        slug="example-org",
        logo=None,
        project_creation_policy="admins_only",
        created_at=now,
    )
    project = SimpleNamespace(id=project_id)
    created = SimpleNamespace(organization=organization, default_project=project)
    database = _OrganizationDatabase(organization, current_user)

    class _OrganizationService:
        def __init__(self, _database: object) -> None:
            pass

        async def create_with_owner_and_default_project(self, **_kwargs: object) -> object:
            return created

    class _OrganizationMemberService:
        def __init__(self, _database: object) -> None:
            pass

        async def require_membership(self, *_args: object) -> object:
            return SimpleNamespace(role="owner")

        async def require_member_manager(self, *_args: object) -> object:
            return SimpleNamespace(role="owner")

        async def transfer_ownership(self, **_kwargs: object) -> tuple[object, object]:
            return SimpleNamespace(role="admin"), SimpleNamespace(user_id=new_owner_user_id, role="owner")

    monkeypatch.setattr(organizations_api, "OrganizationService", _OrganizationService)
    monkeypatch.setattr(organizations_api, "OrganizationMemberService", _OrganizationMemberService)

    app = FastAPI()
    app.add_middleware(ApiV1ResponseWrapperMiddleware)
    app.include_router(organizations_api.router, prefix="/api/v1/organizations")
    app.dependency_overrides[organizations_api.get_db] = lambda: database
    app.dependency_overrides[get_current_user] = lambda: current_user
    client = TestClient(app)

    created_response = client.post("/api/v1/organizations", json={"name": "Example Org"})
    detail_response = client.get(f"/api/v1/organizations/{organization_id}")
    updated_response = client.put(
        f"/api/v1/organizations/{organization_id}",
        json={"name": "Updated Org"},
    )
    transferred_response = client.post(
        f"/api/v1/organizations/{organization_id}/transfer-ownership",
        json={"new_owner_user_id": str(new_owner_user_id)},
    )

    assert created_response.json()["data"]["id"] == str(organization_id)
    assert created_response.json()["data"]["project_id"] == str(project_id)
    assert detail_response.json()["data"]["id"] == str(organization_id)
    assert updated_response.json()["data"]["id"] == str(organization_id)
    assert transferred_response.json()["data"] == {
        "organization_id": str(organization_id),
        "previous_owner_user_id": str(user_id),
        "previous_owner_role": "admin",
        "new_owner_user_id": str(new_owner_user_id),
        "new_owner_role": "owner",
    }
