import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.joysafeter_api.api.v1 import auth as auth_api
from app.joysafeter_api.api.v1 import environments as environments_api
from app.joysafeter_api.api.v1 import storage_volumes as storage_volumes_api
from app.joysafeter_shared.ids import OrganizationId

pytestmark = pytest.mark.no_db


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_ScalarRows":
        return self

    def all(self) -> list[object]:
        return self._rows


class _Database:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statement: object | None = None

    async def execute(self, statement: object) -> _ScalarRows:
        self.statement = statement
        return _ScalarRows(self.rows)


def _organization(name: str, created_at: datetime) -> object:
    return SimpleNamespace(
        id=OrganizationId.new(),
        name=name,
        slug=name.lower(),
        logo=None,
        members=[SimpleNamespace(user=SimpleNamespace(email=f"{name.lower()}@example.com"))],
        projects=[SimpleNamespace()],
        created_at=created_at,
    )


def test_platform_organization_list_returns_standard_cursor_page() -> None:
    now = datetime(2026, 9, 3, tzinfo=UTC)
    rows = [_organization(f"Org{index}", now - timedelta(minutes=index)) for index in range(3)]
    database = _Database(rows)

    response = asyncio.run(
        auth_api.list_platform_organizations(
            q="",
            limit=2,
            after_id=None,
            db=database,
            _auth_ctx=object(),
        )
    )

    assert [item.id for item in response.data] == [rows[0].id, rows[1].id]
    assert response.has_more is True
    assert response.first_id == rows[0].id
    assert response.last_id == rows[1].id
    assert database.statement is not None


def test_storage_mount_catalog_has_one_public_route_owner() -> None:
    environment_paths = {route.path for route in environments_api.router.routes}
    storage_volume_paths = {route.path for route in storage_volumes_api.router.routes}

    assert "/mount-catalog/storage" not in environment_paths
    assert "/catalog" in storage_volume_paths
