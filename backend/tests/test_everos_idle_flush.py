from datetime import UTC, datetime

from app.everos.service import idle_flush


async def test_scan_and_flush_idle_forces_final_memorize(monkeypatch):
    calls = []

    class _Repo:
        async def list_idle_candidates(self, cutoff):
            calls.append(("cutoff", cutoff))
            return [
                ("joysafeter", "project-1", "session-1"),
                ("joysafeter", "project-1", "session-2"),
            ]

    async def fake_memorize(payload, *, is_final=False):
        calls.append(("memorize", payload, is_final))

    monkeypatch.setattr(idle_flush, "conversation_status_repo", _Repo())
    monkeypatch.setattr(idle_flush, "memorize", fake_memorize)

    flushed = await idle_flush.scan_and_flush_idle(
        now=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        threshold_seconds=1800,
    )

    assert flushed == 2
    assert calls[0] == ("cutoff", datetime(2026, 7, 30, 11, 30, tzinfo=UTC))
    assert calls[1:] == [
        (
            "memorize",
            {
                "session_id": "session-1",
                "app_id": "joysafeter",
                "project_id": "project-1",
                "messages": [],
            },
            True,
        ),
        (
            "memorize",
            {
                "session_id": "session-2",
                "app_id": "joysafeter",
                "project_id": "project-1",
                "messages": [],
            },
            True,
        ),
    ]
