from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_flush_everos_session_posts_flush(monkeypatch):
    from app.joysafeter_api.api.v1 import _everos_flush as mod

    posted: dict = {}

    class _Resp:
        def raise_for_status(self):
            pass

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            posted["url"] = url
            posted["json"] = json
            return _Resp()

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)

    async def _resolve(db, project_id):
        return "myproj_p1"
    monkeypatch.setattr(mod, "_resolve_everos_project_id", _resolve)

    sid = uuid.uuid4()
    await mod.flush_everos_session(db=None, session_id=sid, project_id="p1")

    assert posted["url"].endswith("/api/v1/memory/flush")
    assert posted["json"]["app_id"] == "joysafeter"
    assert posted["json"]["project_id"] == "myproj_p1"
    assert posted["json"]["session_id"]  # path-safe session id present


@pytest.mark.asyncio
async def test_flush_everos_session_swallows_errors(monkeypatch):
    from app.joysafeter_api.api.v1 import _everos_flush as mod

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            raise RuntimeError("everos down")

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)

    async def _resolve(db, project_id):
        return "myproj_p1"
    monkeypatch.setattr(mod, "_resolve_everos_project_id", _resolve)

    # 不抛异常即通过（best-effort）
    await mod.flush_everos_session(db=None, session_id=uuid.uuid4(), project_id="p1")
