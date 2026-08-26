from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.joysafeter_api.api.v1 import sessions as session_api
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillUsageLog
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import (
    AgentId,
    OrganizationId,
    ProjectId,
    SessionId,
    SkillId,
    SkillSecurityScanId,
    SkillUsageId,
    SkillVersionId,
    UserId,
)

pytestmark = pytest.mark.no_db

USER_ID = UserId.from_public("user_00000000-0000-0000-0000-000000000001")
ORG_ID = OrganizationId.from_public("org_00000000-0000-0000-0000-000000000001")
PROJECT_ID = ProjectId.from_public("proj_00000000-0000-0000-0000-000000000001")


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


def _ctx(project_id: ProjectId | None = PROJECT_ID) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=USER_ID,
        org_id=ORG_ID,
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _usage_row(session_id: SessionId, project_id: ProjectId = PROJECT_ID) -> JoySafeterSkillUsageLog:
    row = JoySafeterSkillUsageLog(
        id=SkillUsageId.new(),
        skill_id=SkillId.new(),
        skill_name="runtime-audit-skill",
        skill_source_type="manual",
        skill_version="1.2.3",
        skill_version_id=SkillVersionId.new(),
        target="/skills/runtime-audit-skill",
        security_scan_id=SkillSecurityScanId.new(),
        target_hash="a" * 64,
        artifact_hash="b" * 64,
        session_id=session_id,
        agent_id=AgentId.new(),
        project_id=project_id,
        user_id=USER_ID,
    )
    row.created_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    return row


@pytest.mark.asyncio
async def test_session_skill_usage_api_serializes_runtime_audit(monkeypatch):
    session_id = SessionId.new()
    session_id_under_test = session_id
    row = _usage_row(session_id)
    db = _Db([row])

    class _Svc:
        def __init__(self, db):
            self.db = db

        async def get_session(self, session_id, project_id=None):
            assert session_id == session_id_under_test
            assert project_id == PROJECT_ID
            return _Session()

    monkeypatch.setattr(session_api, "SessionService", _Svc)

    response = await session_api.list_session_skill_usage(
        session_id=session_id,
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
    assert item.session_id == session_id

    compiled = db.statement.compile()
    # Assert the real filter, not a compiled-SQL artifact: the WHERE targets the
    # session_id COLUMN (the `=` distinguishes a filter from the SELECT/ORDER-BY
    # column list) and binds the given typed SessionId. EntityIdType unwraps it to
    # the bare uuid at execution, so there is no as_uuid()/f"sess_{...}" round-trip.
    assert "joysafeter_skill_usage_log.session_id =" in str(compiled)
    assert session_id in compiled.params.values()
    assert PROJECT_ID in compiled.params.values()
