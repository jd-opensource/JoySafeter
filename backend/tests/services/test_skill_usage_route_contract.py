from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_skill_usage_search_route_is_reachable_via_asgi(monkeypatch):
    import httpx
    from fastapi import FastAPI

    from app.joysafeter_api.api.v1 import skills as skills_api
    from app.joysafeter_shared.common.exceptions import register_exception_handlers
    from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
    from app.joysafeter_shared.database import get_db
    from app.joysafeter_shared.ids import OrganizationId, ProjectId, UserId

    class _ScalarResult:
        def all(self):
            return []

    class _ExecuteResult:
        def scalars(self):
            return _ScalarResult()

    class _Db:
        def __init__(self):
            self.executed = False

        async def execute(self, statement):
            self.executed = True
            return _ExecuteResult()

    db = _Db()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(skills_api.router, prefix="/skills")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[skills_api.get_joysafeter_auth_context] = lambda: JoySafeterAuthContext(
        user_id=UserId.from_public("user_00000000-0000-0000-0000-000000000001"),
        org_id=OrganizationId.from_public("org_00000000-0000-0000-0000-000000000001"),
        project_id=ProjectId.from_public("proj_00000000-0000-0000-0000-000000000001"),
        role=JoySafeterRole.MEMBER,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(f"/skills/usage/search?artifact_hash={'b' * 64}")

    assert resp.status_code == 200
    assert resp.json()["data"] == []
    assert db.executed is True
