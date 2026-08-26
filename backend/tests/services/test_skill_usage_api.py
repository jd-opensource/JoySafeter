from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.joysafeter_api.api.v1 import skills as skills_api
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


class _Skill:
    pass


def _ctx(project_id: ProjectId | None = PROJECT_ID) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=USER_ID,
        org_id=ORG_ID,
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _usage_row(skill_id: SkillId | None, scan_id: SkillSecurityScanId) -> JoySafeterSkillUsageLog:
    session_id = SessionId.new()
    row = JoySafeterSkillUsageLog(
        id=SkillUsageId.new(),
        skill_id=skill_id,
        skill_name="runtime-audit-skill",
        skill_source_type="manual",
        skill_version="1.2.3",
        skill_version_id=SkillVersionId.new(),
        target="/skills/runtime-audit-skill",
        security_scan_id=scan_id,
        target_hash="a" * 64,
        artifact_hash="b" * 64,
        session_id=session_id,
        agent_id=AgentId.new(),
        project_id=PROJECT_ID,
        user_id=USER_ID,
    )
    row.created_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    return row


@pytest.mark.asyncio
async def test_skill_usage_api_filters_security_response_surface(monkeypatch):
    skill_id = SkillId.new()
    scan_id = SkillSecurityScanId.new()
    db = _Db([_usage_row(skill_id, scan_id)])

    class _Svc:
        def __init__(self, db, active_org_id, caller_org_role=None):
            self.db = db

        async def get_skill(self, requested_skill_id, current_user_id=None, project_id=None):
            assert requested_skill_id == skill_id
            assert current_user_id == USER_ID
            assert project_id == PROJECT_ID
            return _Skill()

    monkeypatch.setattr(skills_api, "SkillService", _Svc)

    response = await skills_api.list_skill_usage(
        skill_id=skill_id,
        limit=50,
        artifact_hash="b" * 64,
        target_hash="a" * 64,
        security_scan_id=scan_id,
        db=db,  # type: ignore[arg-type]
        auth_ctx=_ctx(),
    )

    assert response.has_more is False
    assert len(response.data) == 1
    item = response.data[0]
    assert item.skill_name == "runtime-audit-skill"
    assert isinstance(item.session_id, SessionId)
    assert item.security_scan_id == scan_id

    compiled = db.statement.compile()
    assert "joysafeter_skill_usage_log.skill_id" in str(compiled)
    assert PROJECT_ID in compiled.params.values()
    assert "a" * 64 in compiled.params.values()
    assert "b" * 64 in compiled.params.values()
    assert scan_id in compiled.params.values()


@pytest.mark.asyncio
async def test_skill_usage_search_requires_specific_filter():
    db = _Db([])

    with pytest.raises(Exception) as exc_info:
        await skills_api.search_skill_usage(
            limit=50,
            artifact_hash=None,
            target_hash=None,
            security_scan_id=None,
            db=db,  # type: ignore[arg-type]
            auth_ctx=_ctx(),
        )

    assert getattr(exc_info.value, "code", None) == "SKILL_USAGE_FILTER_REQUIRED"
    assert db.statement is None


@pytest.mark.asyncio
async def test_skill_usage_search_finds_deleted_skill_by_hash():
    scan_id = SkillSecurityScanId.new()
    db = _Db([_usage_row(None, scan_id)])

    response = await skills_api.search_skill_usage(
        limit=50,
        artifact_hash="b" * 64,
        target_hash=None,
        security_scan_id=None,
        db=db,  # type: ignore[arg-type]
        auth_ctx=_ctx(),
    )

    assert response.has_more is False
    assert len(response.data) == 1
    item = response.data[0]
    assert item.skill_id is None
    assert item.skill_name == "runtime-audit-skill"
    assert item.artifact_hash == "b" * 64

    compiled = db.statement.compile()
    assert "joysafeter_skill_usage_log.skill_id =" not in str(compiled)
    assert PROJECT_ID in compiled.params.values()
    assert "b" * 64 in compiled.params.values()


@pytest.mark.asyncio
async def test_skill_usage_search_rejects_non_hex_hash():
    db = _Db([])

    with pytest.raises(Exception) as exc_info:
        await skills_api.search_skill_usage(
            limit=50,
            artifact_hash="g" * 64,
            target_hash=None,
            security_scan_id=None,
            db=db,  # type: ignore[arg-type]
            auth_ctx=_ctx(),
        )

    assert getattr(exc_info.value, "code", None) == "SKILL_USAGE_HASH_INVALID"
    assert db.statement is None


@pytest.mark.asyncio
async def test_skill_usage_search_normalizes_uppercase_hash():
    db = _Db([])

    await skills_api.search_skill_usage(
        limit=50,
        artifact_hash="B" * 64,
        target_hash=None,
        security_scan_id=None,
        db=db,  # type: ignore[arg-type]
        auth_ctx=_ctx(),
    )

    compiled = db.statement.compile()
    assert "b" * 64 in compiled.params.values()
    assert "B" * 64 not in compiled.params.values()
