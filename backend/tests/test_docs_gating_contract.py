"""OpenAPI docs must be disabled outside debug/development.

Interactive docs (/docs, /redoc, /openapi.json) expose the full API surface and
schema. `create_app` already gates them on debug/development; this pins that so a
regression cannot silently expose the schema on a production deployment.
"""

from contextlib import asynccontextmanager

import pytest

from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.runtime.app_factory import create_app

pytestmark = pytest.mark.no_db


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def test_docs_disabled_in_production(monkeypatch):
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "environment", "production")

    app = create_app(lifespan=_noop_lifespan)

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_docs_enabled_in_development(monkeypatch):
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "environment", "development")

    app = create_app(lifespan=_noop_lifespan)

    assert app.docs_url == "/docs"
    assert app.openapi_url == "/openapi.json"
