from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import SQLModel

from app.everos.core.persistence import MemoryRoot
from app.everos.infra.persistence.sqlite import get_engine
from app.everos.infra.persistence.sqlite.repos.conversation_status import (
    conversation_status_repo,
)


@pytest.mark.asyncio
async def test_scan_and_flush_idle_flushes_only_idle_unextracted(tmp_path, monkeypatch):
    monkeypatch.setenv("EVEROS_ROOT", str(tmp_path))
    MemoryRoot(tmp_path).ensure()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    from app.everos.service import idle_flush

    flushed: list[tuple[str, str, str]] = []

    async def _fake_memorize(payload, *, is_final=False):
        assert is_final is True
        assert payload["messages"] == []
        flushed.append((payload["app_id"], payload["project_id"], payload["session_id"]))
        class _R:
            message_count = 0
            status = "extracted"
        return _R()

    monkeypatch.setattr(idle_flush, "memorize", _fake_memorize)

    old = dt.datetime(2026, 7, 29, 10, 0, tzinfo=dt.UTC)
    now = dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.UTC)  # 2h later
    await conversation_status_repo.touch_last_message_ts(
        "sess-idle", "memorize", old, app_id="joysafeter", project_id="p1"
    )

    count = await idle_flush.scan_and_flush_idle(now=now, threshold_seconds=1800)

    assert count == 1
    assert ("joysafeter", "p1", "sess-idle") in flushed
