from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_provider_runs_scan_then_cancels_on_shutdown(monkeypatch):
    from app.everos.entrypoints.api.lifespans import idle_flush as prov_mod

    ran = asyncio.Event()

    async def _fake_scan(*, now, threshold_seconds):
        ran.set()
        return 0

    monkeypatch.setattr(prov_mod, "scan_and_flush_idle", _fake_scan)
    # 用极小间隔加速测试
    monkeypatch.setattr(
        prov_mod, "_resolve_interval_and_threshold", lambda: (0.01, 1800)
    )

    provider = prov_mod.IdleFlushLifespanProvider()
    await provider.startup(app=None)
    await asyncio.wait_for(ran.wait(), timeout=2.0)
    await provider.shutdown(app=None)

    assert provider._task is None or provider._task.cancelled() or provider._task.done()
