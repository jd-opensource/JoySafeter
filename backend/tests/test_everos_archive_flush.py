from types import SimpleNamespace
import uuid

from app.joysafeter_api.api.v1 import sessions


async def test_archive_session_triggers_everos_flush(monkeypatch):
    session_id = uuid.uuid4()
    calls = []

    class _SessionService:
        def __init__(self, db):
            self.db = db

        async def get_session(self, sid, *, project_id=None):
            assert sid == session_id
            assert project_id == "project-1"
            return SimpleNamespace(id=sid, project_id=project_id)

        async def archive_session(self, sid, *, project_id=None):
            assert sid == session_id
            assert project_id == "project-1"
            return True

    async def fake_flush(db, *, session_id, project_id):
        calls.append((session_id, project_id))

    monkeypatch.setattr(sessions, "SessionService", _SessionService)
    monkeypatch.setattr(sessions, "flush_everos_session", fake_flush)

    response = await sessions.archive_session(
        session_id=session_id,
        db=object(),
        auth_ctx=SimpleNamespace(project_id="project-1"),
    )

    assert response == {"status": "archived"}
    assert calls == [(session_id, "project-1")]
