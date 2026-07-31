"""Unit tests for ``SkillService._dispatch_security_scan`` async dispatch.

The dispatch helper is the seam that lets large-skill writes return
to the user fast while their scan runs as a background task. We
verify:

  - Below threshold: runs sync, returns scan, nothing queued
  - Above threshold + skill_id set: marks scanning, queues descriptor,
    returns None
  - No skill_id (create-time): always sync, even when payload is big
    (P2.7 carve-out — see ``_dispatch_security_scan`` docstring)
  - drain_pending_async_scans empties the queue
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.joysafeter_domain.services.joysafeter_skill_service import SkillService

pytestmark = pytest.mark.no_db


@pytest.fixture(autouse=True)
def _enable_scanner(monkeypatch):
    """Force ``skill_security_scan_enabled`` True for every test in this
    module. The default in ``settings`` is False (so disabling SkillSpector
    in dev doesn't accidentally trigger scans), but every test here is
    explicitly exercising the dispatch branch that only runs when the
    scanner is enabled. P2.17 added a short-circuit at the top of
    ``_dispatch_security_scan`` that returns None when the scanner is
    disabled — without this fixture each test would hit that and never
    reach ``should_scan_async``.
    """
    from app.joysafeter_shared.config.settings import settings as _settings

    monkeypatch.setattr(
        _settings,
        "skill_security_scan_enabled",
        True,
        raising=False,
    )


def _bare_service():
    """Construct a ``SkillService`` with stubbed deps.

    The dispatch path uses three collaborators:
      - ``security_service.mark_scanning``  (async)
      - ``security_service.scan_for_write`` (async, the sync fallback)
      - the pending-async-scans list

    We stub the first two with AsyncMocks so the test stays in-process.
    """
    svc = SkillService.__new__(SkillService)
    svc.db = MagicMock()
    svc.security_service = MagicMock()
    svc.security_service.mark_scanning = AsyncMock()
    svc.security_service.scan_for_write = AsyncMock(return_value=MagicMock(status="passed"))
    svc._pending_async_scans = []
    return svc


_KW = dict(
    trigger="update",
    created_by_id="user-1",
    owner_id="user-1",
    project_id="proj-1",
    name="t",
    description="d",
    content="c",
    tags=[],
    license=None,
    files=[],
)


async def test_small_payload_runs_sync():
    """Small skill goes through the sync path — scan_for_write is
    awaited, mark_scanning is NOT called, nothing queued."""
    with patch("app.joysafeter_domain.services.joysafeter_skill_security.settings") as s:
        s.skill_security_async_threshold_bytes = 100_000  # 100KB
        svc = _bare_service()
        skill_id = uuid.uuid4()

        result = await svc._dispatch_security_scan(skill_id=skill_id, **_KW)

    assert result is not None  # sync path returned the mocked scan
    svc.security_service.scan_for_write.assert_called_once()
    svc.security_service.mark_scanning.assert_not_called()
    assert svc._pending_async_scans == []


async def test_large_payload_with_skill_id_defers_async():
    """When payload exceeds threshold AND the skill row exists, the
    helper marks scanning + queues + returns None — the API layer
    then forwards the descriptor to a BackgroundTask."""
    with patch("app.joysafeter_domain.services.joysafeter_skill_security.settings") as s:
        s.skill_security_async_threshold_bytes = 10  # tiny — even "ttdc" exceeds
        svc = _bare_service()
        skill_id = uuid.uuid4()

        result = await svc._dispatch_security_scan(
            skill_id=skill_id,
            **{**_KW, "content": "a" * 5_000},  # 5KB content
        )

    assert result is None
    svc.security_service.scan_for_write.assert_not_called()
    svc.security_service.mark_scanning.assert_called_once_with(skill_id)
    assert len(svc._pending_async_scans) == 1
    descriptor = svc._pending_async_scans[0]
    assert descriptor["skill_id"] == skill_id
    assert descriptor["trigger"] == "update"
    # The descriptor must carry everything ``run_scan_in_background``
    # needs — no extra DB lookup later.
    for key in ("name", "description", "content", "tags", "license", "files"):
        assert key in descriptor


async def test_large_payload_no_skill_id_falls_back_to_sync():
    """Create-time call has no skill_id yet. Even with a huge payload,
    the dispatcher must run sync because there's no row to flip into
    ``scanning`` state. This is the P2.7 explicit carve-out."""
    with patch("app.joysafeter_domain.services.joysafeter_skill_security.settings") as s:
        s.skill_security_async_threshold_bytes = 10
        svc = _bare_service()

        result = await svc._dispatch_security_scan(
            skill_id=None,
            **{**_KW, "content": "a" * 5_000},
        )

    assert result is not None
    svc.security_service.scan_for_write.assert_called_once()
    svc.security_service.mark_scanning.assert_not_called()
    assert svc._pending_async_scans == []


async def test_drain_pending_async_scans_empties_queue():
    """Drain consumes the list — a second drain is empty, so the API
    layer can't double-spawn tasks if it's called twice by mistake."""
    svc = _bare_service()
    svc._pending_async_scans.append({"skill_id": uuid.uuid4()})
    svc._pending_async_scans.append({"skill_id": uuid.uuid4()})

    first = svc.drain_pending_async_scans()
    assert len(first) == 2

    second = svc.drain_pending_async_scans()
    assert second == []


async def test_drain_returns_independent_list():
    """Caller can mutate / iterate the drained list without affecting
    future drains. Important because FastAPI's BackgroundTasks iterates
    the list when scheduling."""
    svc = _bare_service()
    svc._pending_async_scans.append({"skill_id": uuid.uuid4()})

    drained = svc.drain_pending_async_scans()
    drained.append({"injected": True})
    assert svc._pending_async_scans == []


@pytest.mark.parametrize("trigger", ["update", "file_add", "file_update", "file_delete"])
async def test_dispatch_threads_trigger_through(trigger):
    """Each call site passes its own trigger name; the descriptor must
    preserve it so BG-run scans land with the right ``trigger`` field
    in ``joysafeter_skill_security_scans``."""
    with patch("app.joysafeter_domain.services.joysafeter_skill_security.settings") as s:
        s.skill_security_async_threshold_bytes = 10
        svc = _bare_service()
        skill_id = uuid.uuid4()

        await svc._dispatch_security_scan(
            skill_id=skill_id,
            **{**_KW, "trigger": trigger, "content": "a" * 5_000},
        )

    assert svc._pending_async_scans[0]["trigger"] == trigger


async def test_scanner_disabled_short_circuits_with_no_side_effects(monkeypatch):
    """P2.17: when ``SKILL_SECURITY_SCAN_ENABLED=false`` the dispatcher
    must short-circuit BEFORE deciding sync vs async. Otherwise the
    async branch would flip the skill row to ``security_status='scanning'``
    and queue a descriptor that ``run_scan_in_background`` would just
    translate back to ``not_scanned`` — a useless DB round-trip in the
    happy case and (pre-P2.16, when create_skill didn't flush BG tasks)
    a permanent stuck-in-scanning state in the bad case.

    The disabled-path contract: return None, touch nothing.
    """
    from app.joysafeter_shared.config.settings import settings as _settings

    monkeypatch.setattr(
        _settings,
        "skill_security_scan_enabled",
        False,
        raising=False,
    )
    # Even with a tiny threshold (so async would otherwise fire) and a
    # large content payload, the disabled gate has to win first.
    with patch("app.joysafeter_domain.services.joysafeter_skill_security.settings") as s:
        s.skill_security_async_threshold_bytes = 10
        svc = _bare_service()
        skill_id = uuid.uuid4()

        result = await svc._dispatch_security_scan(
            skill_id=skill_id,
            **{**_KW, "content": "a" * 5_000},
        )

    assert result is None
    svc.security_service.mark_scanning.assert_not_called()
    svc.security_service.scan_for_write.assert_not_called()
    assert svc._pending_async_scans == []
