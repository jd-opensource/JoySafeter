"""FIX 1 regression: an extract-with-tail must re-arm idle detection.

When ``/add`` extracts cells AND leaves a non-empty tail in the buffer, the
boundary stage advances ``last_memcell_ts`` but must ALSO advance
``last_message_ts`` past the extracted cells — otherwise the idle-flush
candidate rule (``last_message_ts > last_memcell_ts``) treats the session as
fully-extracted and never idle-flushes the buffered tail on an abandoned
(non-archived) session.
"""

from __future__ import annotations

import datetime as dt

import pytest
from everalgo.types import ChatMessage, MemCell
from sqlmodel import SQLModel

from app.everos.core.persistence import MemoryRoot
from app.everos.infra.persistence.sqlite import get_engine
from app.everos.infra.persistence.sqlite.repos.conversation_status import (
    conversation_status_repo,
)
from app.everos.memory import CanonicalMessage, IngestResult


class _StubPromptLoader:
    def load(self, name: str) -> str:
        return ""


@pytest.mark.asyncio
async def test_extract_with_tail_rearms_idle_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("EVEROS_ROOT", str(tmp_path))
    MemoryRoot(tmp_path).ensure()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    from app.everos.service import _boundary

    session_id = "sess-tail"
    app_id = "joysafeter"
    project_id = "p1"

    # Two canonical messages: the extracted cell's message + a strictly-later
    # tail message. Use real millisecond epochs (> 1e12) so from_timestamp
    # treats them as ms consistently with the CanonicalMessage datetimes.
    cell_ts_ms = 1_700_000_000_000
    tail_ts_ms = 1_700_000_060_000
    cell_dt = dt.datetime.fromtimestamp(cell_ts_ms / 1000.0, tz=dt.UTC)
    tail_dt = dt.datetime.fromtimestamp(tail_ts_ms / 1000.0, tz=dt.UTC)

    msg_cell = CanonicalMessage(
        message_id="m1",
        session_id=session_id,
        sender_id="u1",
        sender_name="User",
        role="user",
        timestamp=cell_dt,
        content_items=[],
        text="hello",
    )
    msg_tail = CanonicalMessage(
        message_id="m2",
        session_id=session_id,
        sender_id="u1",
        sender_name="User",
        role="user",
        timestamp=tail_dt,
        content_items=[],
        text="a later thought",
    )

    ingested = IngestResult(
        session_id=session_id,
        app_id=app_id,
        project_id=project_id,
        messages=[msg_cell, msg_tail],
    )

    # Patch _detect: one cell (closing at cell_ts_ms) + a non-empty tail of one
    # item (the strictly-later tail message). _slice_tail uses len(tail) to take
    # the trailing slice of `merged`, so tail must have exactly one item.
    cell = MemCell(
        items=[
            ChatMessage(
                id="m1",
                role="user",
                content="hello",
                timestamp=cell_ts_ms,
                sender_id="u1",
                sender_name="User",
            )
        ],
        timestamp=cell_ts_ms,
    )
    tail_item = ChatMessage(
        id="m2",
        role="user",
        content="a later thought",
        timestamp=tail_ts_ms,
        sender_id="u1",
        sender_name="User",
    )

    async def _fake_detect(merged, **kwargs):
        return [cell], [tail_item]

    monkeypatch.setattr(_boundary, "_detect", _fake_detect)

    outcome = await _boundary.prepare_cells(
        ingested,
        mode="chat",
        is_final=False,
        llm_client=object(),  # non-None; _detect is patched
        prompt_loader=_StubPromptLoader(),
        hard_token_limit=100_000,
        hard_msg_limit=1_000,
    )

    assert outcome.status == "extracted"

    # The tail re-armed idle detection: with a cutoff far in the future the
    # session appears as an idle candidate (last_message_ts > last_memcell_ts).
    cutoff = dt.datetime(2100, 1, 1, tzinfo=dt.UTC)
    candidates = await conversation_status_repo.list_idle_candidates(cutoff)
    keys = {(a, p, s) for (a, p, s) in candidates}
    assert (app_id, project_id, session_id) in keys
