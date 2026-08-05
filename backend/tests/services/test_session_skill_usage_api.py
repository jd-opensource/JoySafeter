from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.joysafeter_api.api.v1 import sessions as session_api
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillUsageLog
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole

pytestmark = pytest.mark.no_db


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _ExecuteResult(self.rows)


class _Session:
    pass


def _ctx(project_id: str | None = "proj-a") -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="user-a",
        org_id="org-a",
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _usage_row(session_id: str, project_id: str = "proj-a") -> JoySafeterSkillUsageLog:
    row = JoySafeterSkillUsageLog(
        id=uuid.uuid4(),
        skill_id=uuid.uuid4(),
        skill_name="runtime-audit-skill",
        skill_source_type="manual",
        skill_version="1.2.3",
        skill_version_id=uuid.uuid4(),
        target="/skills/runtime-audit-skill",
        security_scan_id=uuid.uuid4(),
        target_hash="a" * 64,
        artifact_hash="b" * 64,
        session_id=session_id,
        agent_id="agent-a",
        project_id=project_id,
        user_id="user-a",
    )
    row.created_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    return row


@pytest.mark.asyncio
async def test_session_skill_usage_api_serializes_runtime_audit(monkeypatch):
    session_uuid = uuid.uuid4()
    row = _usage_row(f"sess_{session_uuid}")
    db = _Db([row])

    class _Svc:
        def __init__(self, db):
            self.db = db

        async def get_session(self, session_id, project_id=None):
            assert session_id == session_uuid
            assert project_id == "proj-a"
            return _Session()

    monkeypatch.setattr(session_api, "SessionService", _Svc)

    response = await session_api.list_session_skill_usage(
        session_id=session_uuid,
        limit=50,
        db=db,  # type: ignore[arg-type]
        auth_ctx=_ctx(),
    )

    assert response.has_more is False
    assert len(response.data) == 1
    item = response.data[0]
    assert item.skill_version == "1.2.3"
    assert item.skill_name == "runtime-audit-skill"
    assert item.skill_source_type == "manual"
    assert item.target == "/skills/runtime-audit-skill"
    assert item.target_hash == "a" * 64
    assert item.artifact_hash == "b" * 64
    assert item.session_id == f"sess_{session_uuid}"

    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert f"sess_{session_uuid}" in compiled
    assert str(session_uuid) in compiled
    assert "proj-a" in compiled
