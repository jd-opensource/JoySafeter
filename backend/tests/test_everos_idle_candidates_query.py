# backend/tests/test_everos_idle_candidates_query.py
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
async def test_list_idle_candidates_filters_by_time_and_unextracted(tmp_path, monkeypatch):
    monkeypatch.setenv("EVEROS_ROOT", str(tmp_path))
    MemoryRoot(tmp_path).ensure()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    old = dt.datetime(2026, 7, 29, 10, 0, tzinfo=dt.UTC)
    cutoff = dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.UTC)

    # 候选：有新内容(last_message_ts > last_memcell_ts) 且早于 cutoff
    await conversation_status_repo.touch_last_message_ts(
        "sess-idle", "memorize", old, app_id="joysafeter", project_id="p1"
    )
    # 已提取到位：last_memcell_ts >= last_message_ts → 不该是候选
    await conversation_status_repo.touch_last_message_ts(
        "sess-done", "memorize", old, app_id="joysafeter", project_id="p1"
    )
    await conversation_status_repo.touch_last_memcell_ts(
        "sess-done", "memorize", old, app_id="joysafeter", project_id="p1"
    )

    result = await conversation_status_repo.list_idle_candidates(cutoff)

    keys = {(a, p, s) for (a, p, s) in result}
    assert ("joysafeter", "p1", "sess-idle") in keys
    assert ("joysafeter", "p1", "sess-done") not in keys


@pytest.mark.asyncio
async def test_list_idle_candidates_excludes_recent_and_other_track(tmp_path, monkeypatch):
    monkeypatch.setenv("EVEROS_ROOT", str(tmp_path))
    MemoryRoot(tmp_path).ensure()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    old = dt.datetime(2026, 7, 29, 10, 0, tzinfo=dt.UTC)
    recent = dt.datetime(2026, 7, 29, 12, 30, tzinfo=dt.UTC)  # >= cutoff
    cutoff = dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.UTC)

    # (i) too recent: last_message_ts >= cutoff → excluded.
    await conversation_status_repo.touch_last_message_ts(
        "sess-recent", "memorize", recent, app_id="joysafeter", project_id="p1"
    )
    # (ii) different track: unextracted + old, but track != "memorize" → excluded.
    await conversation_status_repo.touch_last_message_ts(
        "sess-other-track", "other", old, app_id="joysafeter", project_id="p1"
    )
    # control: a real candidate so we know the query returns something.
    await conversation_status_repo.touch_last_message_ts(
        "sess-idle", "memorize", old, app_id="joysafeter", project_id="p1"
    )

    result = await conversation_status_repo.list_idle_candidates(cutoff)

    keys = {(a, p, s) for (a, p, s) in result}
    assert ("joysafeter", "p1", "sess-idle") in keys
    assert ("joysafeter", "p1", "sess-recent") not in keys
    assert ("joysafeter", "p1", "sess-other-track") not in keys
