from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.joysafeter_api.api.v1 import skills as skills_api
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


class _Skill:
    pass


def _ctx(project_id: str | None = "proj-a") -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="user-a",
        org_id="org-a",
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _usage_row(skill_id: uuid.UUID | None, scan_id: uuid.UUID) -> JoySafeterSkillUsageLog:
    row = JoySafeterSkillUsageLog(
        id=uuid.uuid4(),
        skill_id=skill_id,
        skill_name="runtime-audit-skill",
        skill_source_type="manual",
        skill_version="1.2.3",
        skill_version_id=uuid.uuid4(),
        target="/skills/runtime-audit-skill",
        security_scan_id=scan_id,
        target_hash="a" * 64,
        artifact_hash="b" * 64,
        session_id="sess-a",
        agent_id="agent-a",
        project_id="proj-a",
        user_id="user-a",
    )
    row.created_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    return row


@pytest.mark.asyncio
async def test_skill_usage_api_filters_security_response_surface(monkeypatch):
    skill_id = uuid.uuid4()
    scan_id = uuid.uuid4()
    db = _Db([_usage_row(skill_id, scan_id)])

    class _Svc:
        def __init__(self, db, active_org_id=None, caller_org_role=None):
            self.db = db

        async def get_skill(self, requested_skill_id, current_user_id=None):
            assert requested_skill_id == skill_id
            assert current_user_id == "user-a"
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
    assert item.session_id == "sess-a"
    assert item.security_scan_id == scan_id

    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "joysafeter_skill_usage_log.skill_id" in compiled
    assert "proj-a" in compiled
    assert "a" * 64 in compiled
    assert "b" * 64 in compiled
    assert "joysafeter_skill_usage_log.security_scan_id" in compiled


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
    scan_id = uuid.uuid4()
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

    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "joysafeter_skill_usage_log.skill_id =" not in compiled
    assert "proj-a" in compiled
    assert "b" * 64 in compiled


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

    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "b" * 64 in compiled
    assert "B" * 64 not in compiled
