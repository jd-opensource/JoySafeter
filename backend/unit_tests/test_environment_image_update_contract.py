from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.joysafeter_api.api.v1 import environments as env_api  # noqa: E402
from app.joysafeter_domain.schemas.joysafeter_environment import (  # noqa: E402
    EnvironmentConfig,
    Packages,
    UpdateEnvironmentRequest,
)
from app.joysafeter_shared.common.app_errors import AppError  # noqa: E402


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.refreshes = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        self.refreshes += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeEnvironmentService:
    def __init__(self, env) -> None:
        self.env = env
        self.update_called = False
        self.update_commit_arg = None

    async def get_environment(self, env_id, project_id=None):
        return self.env if env_id == self.env.id else None

    async def update_environment(self, env_id, req, project_id=None, *, commit=True):
        self.update_called = True
        self.update_commit_arg = commit
        if env_id != self.env.id:
            return None
        if req.name is not None:
            self.env.name = req.name
        if req.description is not None:
            self.env.description = req.description
        if req.metadata is not None:
            self.env.metadata_ = req.metadata
        if req.config is not None:
            self.env.config = req.config.model_dump()
        return self.env


def _fake_env(**overrides):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = {
        "id": uuid.uuid4(),
        "name": "python-env",
        "description": "",
        "metadata_": {},
        "config": {"type": "cloud", "packages": {"pip": ["requests"]}},
        "created_at": now,
        "updated_at": now,
        "archived_at": None,
        "image_tag": "joysafeter/env-old:v3",
        "image_version": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_update_environment_rolls_back_when_image_build_fails(monkeypatch) -> None:
    env = _fake_env()
    db = FakeDb()
    svc = FakeEnvironmentService(env)

    async def failing_build(_env):
        raise RuntimeError("docker build failed")

    monkeypatch.setattr(env_api, "EnvironmentService", lambda _db: svc)
    monkeypatch.setattr(env_api, "_build_image_update", failing_build)

    req = UpdateEnvironmentRequest(
        config=EnvironmentConfig(type="cloud", packages=Packages(pip=["numpy"]))
    )

    with pytest.raises(AppError) as exc_info:
        await env_api.update_environment(req, env.id, db, SimpleNamespace(project_id=None))

    assert exc_info.value.code == "ENVIRONMENT_IMAGE_BUILD_FAILED"
    assert svc.update_called is True
    assert svc.update_commit_arg is False
    assert db.commits == 0
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_update_environment_clears_image_when_packages_are_removed(monkeypatch) -> None:
    env = _fake_env()
    db = FakeDb()
    svc = FakeEnvironmentService(env)

    async def clear_image(_env):
        return env_api._EnvironmentImageUpdate(image_tag=None, image_version=0, apply=True)

    monkeypatch.setattr(env_api, "EnvironmentService", lambda _db: svc)
    monkeypatch.setattr(env_api, "_build_image_update", clear_image)

    req = UpdateEnvironmentRequest(config=EnvironmentConfig(type="cloud"))
    response = await env_api.update_environment(req, env.id, db, SimpleNamespace(project_id=None))

    assert svc.update_commit_arg is False
    assert db.commits == 1
    assert db.refreshes == 1
    assert db.rollbacks == 0
    assert env.image_tag is None
    assert env.image_version == 0
    assert response.image_tag is None
    assert response.image_version == 0
