"""SSE replay/poll must not silently truncate at one page.

The session event stream replays DB events after a cursor and polls for new ones
in three places. Each called `list_events(session_id, 1000, cursor)` and discarded
`has_more`, so when a session has more than one page of events after the cursor
(reconnect to a long session, or a fast producer), the tail past 1000 was never
sent — a permanent gap for an active session whose live traffic keeps the 30s
catch-up timeout from firing. `_iter_events_after` drains every page until
`has_more` is False, advancing the cursor to the last seq of each page.
"""

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_api.api.v1.sessions import _iter_events_after

pytestmark = pytest.mark.no_db


def _ev(seq: int) -> SimpleNamespace:
    return SimpleNamespace(seq=seq, id=seq, event_type="t", payload={})


class _FakeSvc:
    def __init__(self, pages):
        self._pages = list(pages)
        self.cursors: list = []

    async def list_events(self, session_id, limit, after_seq, project_id=None):
        self.cursors.append(after_seq)
        return self._pages.pop(0)


@pytest.mark.asyncio
async def test_drains_all_pages_beyond_the_first():
    page1 = ([_ev(i) for i in range(1, 1001)], True)
    page2 = ([_ev(i) for i in range(1001, 1501)], False)
    svc = _FakeSvc([page1, page2])

    got = [ev.seq async for ev in _iter_events_after(svc, uuid.uuid4(), 0, None)]

    assert got == list(range(1, 1501)), "the tail past the first page must not be dropped"
    # Second page must be requested from the last seq of the first page (cursor advanced).
    assert svc.cursors == [0, 1000]


@pytest.mark.asyncio
async def test_single_page_stops_when_has_more_false():
    svc = _FakeSvc([([_ev(1), _ev(2)], False)])
    got = [ev.seq async for ev in _iter_events_after(svc, uuid.uuid4(), 0, None)]
    assert got == [1, 2]
    assert svc.cursors == [0]


@pytest.mark.asyncio
async def test_empty_yields_nothing():
    svc = _FakeSvc([([], False)])
    got = [ev.seq async for ev in _iter_events_after(svc, uuid.uuid4(), 5, None)]
    assert got == []
