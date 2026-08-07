from __future__ import annotations

import inspect

import pytest
from fastapi import Response
from fastapi.params import Depends

from app.joysafeter_api.api.v1.llm import get_catalog
from app.joysafeter_api.api.v1.router import joysafeter_router
from app.joysafeter_shared.common.joysafeter_auth import get_joysafeter_auth_context
from app.joysafeter_shared.runtime import lifecycle

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_catalog_api_returns_public_metadata_and_cache_headers() -> None:
    response = Response()

    catalog = await get_catalog(response=response, auth_ctx=object())

    assert catalog.version == "2026-08-07.1"
    assert catalog.engine("codex").supported_protocol_ids == ["openai_responses"]
    assert catalog.provider("openai").protocol_bindings[0].credential_profile_id == "openai_bearer"
    assert response.headers["etag"] == '"2026-08-07.1"'
    assert response.headers["cache-control"] == "private, max-age=300"
    payload = catalog.model_dump()
    assert "data" not in payload
    assert "secret_data" not in payload


def test_catalog_route_is_mounted_with_read_auth() -> None:
    route = next(route for route in joysafeter_router.routes if route.path == "/llm/catalog")
    assert route.methods == {"GET"}

    dependency = inspect.signature(get_catalog).parameters["auth_ctx"].default
    assert isinstance(dependency, Depends)
    assert dependency.dependency is get_joysafeter_auth_context


def test_catalog_configuration_validation_forces_catalog_load(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(lifecycle, "get_llm_catalog", lambda: calls.append("loaded"))

    lifecycle.validate_llm_catalog_configuration()

    assert calls == ["loaded"]
