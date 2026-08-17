"""The single authoritative anthropic auth-scheme resolver must run on the
create/update/test credential entry points.

Reuses the same bare-app wiring as ``tests/test_credentials_api.py`` (a
synchronous ``TestClient`` mounted on the credential routers with auth + db
dependency-overridden, so no ``auth_headers`` are needed). The response ``data``
is masked (``_credential_response``) but key NAMES are preserved, so assertions
inspect the key SET only.
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

from app.joysafeter_api.api.v1.credentials import router as credentials_router
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


async def _make_project(session_factory: async_sessionmaker) -> str:
    async with session_factory() as session:
        org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
        session.add(org)
        await session.flush()
        project = Project(org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
        session.add(project)
        await session.commit()
        return project.id


@pytest.fixture
def api(postgres_url: str) -> Iterator[TestClient]:
    """A bare-app TestClient for the ``/credentials`` router with auth + db
    overridden (same wiring style as tests/test_credentials_api.py)."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    project_id = asyncio.get_event_loop().run_until_complete(_make_project(session_factory))

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(credentials_router, prefix="/credentials")

    async def _override_db():
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
        yield test_client

    asyncio.get_event_loop().run_until_complete(engine.dispose())


def test_create_anthropic_auto_gateway_stores_auth_token(api: TestClient) -> None:
    payload = {
        "kind": "model",
        "name": "jd-claude",
        "provider": "anthropic",
        "protocol": "anthropic_messages",
        "auth_scheme": "auto",
        "data": {
            "ANTHROPIC_API_KEY": "pk-jd-secret",
            "ANTHROPIC_BASE_URL": "http://ai-api.jdcloud.com/anthropic",
            "ANTHROPIC_MODEL": "claude-3-5-sonnet",
        },
        "is_default": False,
    }
    resp = api.post("/credentials", json=payload)
    assert resp.status_code == 201, resp.text
    keys = set(resp.json()["data"].keys())
    assert "ANTHROPIC_AUTH_TOKEN" in keys
    assert "ANTHROPIC_API_KEY" not in keys


def test_create_anthropic_auto_official_stores_api_key(api: TestClient) -> None:
    payload = {
        "kind": "model",
        "name": "official-claude",
        "provider": "anthropic",
        "protocol": "anthropic_messages",
        "auth_scheme": "auto",
        "data": {
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_MODEL": "claude-3-5-sonnet",
        },
        "is_default": False,
    }
    resp = api.post("/credentials", json=payload)
    assert resp.status_code == 201, resp.text
    keys = set(resp.json()["data"].keys())
    assert "ANTHROPIC_API_KEY" in keys
    assert "ANTHROPIC_AUTH_TOKEN" not in keys


def test_update_anthropic_auto_gateway_rewrites_to_auth_token(api: TestClient) -> None:
    """Update routes through the SAME resolver: switching an official cred's
    base_url to a gateway under auth_scheme=auto rewrites the stored key."""
    create = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "switchable-claude",
            "provider": "anthropic",
            "protocol": "anthropic_messages",
            "auth_scheme": "auto",
            "data": {
                "ANTHROPIC_API_KEY": "sk-ant-secret",
                "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                "ANTHROPIC_MODEL": "claude-3-5-sonnet",
            },
        },
    )
    assert create.status_code == 201, create.text
    cred_id = create.json()["id"]
    assert "ANTHROPIC_API_KEY" in create.json()["data"]
    assert "ANTHROPIC_AUTH_TOKEN" not in create.json()["data"]

    patch = api.patch(
        f"/credentials/{cred_id}",
        json={
            "auth_scheme": "auto",
            "data": {
                "ANTHROPIC_API_KEY": "pk-jd-secret",
                "ANTHROPIC_BASE_URL": "http://ai-api.jdcloud.com/anthropic",
                "ANTHROPIC_MODEL": "claude-3-5-sonnet",
            },
        },
    )
    assert patch.status_code == 200, patch.text
    keys = set(patch.json()["data"].keys())
    assert "ANTHROPIC_AUTH_TOKEN" in keys
    assert "ANTHROPIC_API_KEY" not in keys


def test_non_anthropic_create_untouched(api: TestClient) -> None:
    """Normalization is anthropic-only; other providers keep their keys as-is."""
    resp = api.post(
        "/credentials",
        json={
            "kind": "model",
            "name": "openai-cred",
            "provider": "openai",
            "protocol": "openai_responses",
            "auth_scheme": "auto",
            "data": {
                "OPENAI_API_KEY": "sk-openai",
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
            },
        },
    )
    assert resp.status_code == 201, resp.text
    keys = set(resp.json()["data"].keys())
    assert "OPENAI_API_KEY" in keys
    assert "ANTHROPIC_AUTH_TOKEN" not in keys
