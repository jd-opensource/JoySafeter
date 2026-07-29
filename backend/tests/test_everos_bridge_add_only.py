# backend/tests/test_everos_bridge_add_only.py
from __future__ import annotations

import pytest

from app.joysafeter_orchestrator.kernel import everos_bridge


@pytest.mark.asyncio
async def test_post_to_everos_only_calls_add(monkeypatch):
    calls: list[str] = []

    class _Resp:
        def raise_for_status(self) -> None:
            pass

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            calls.append(url)
            return _Resp()

    monkeypatch.setattr(everos_bridge.httpx, "AsyncClient", _Client)

    await everos_bridge._post_to_everos(
        {"session_id": "s1", "app_id": "joysafeter", "project_id": "p1", "messages": [{"x": 1}]}
    )

    assert any(u.endswith("/api/v1/memory/add") for u in calls)
    assert not any(u.endswith("/api/v1/memory/flush") for u in calls)
