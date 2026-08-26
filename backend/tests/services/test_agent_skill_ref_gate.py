from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.joysafeter_application.agents.command_service import AgentCommandService
from app.joysafeter_domain.agents import merge_agent_assets
from app.joysafeter_domain.schemas.joysafeter_agent import SkillRef
from app.joysafeter_infrastructure.agents import SqlAlchemyAgentRepository
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.ids import ProjectId, SkillId

pytestmark = pytest.mark.no_db

PROJECT_ID = ProjectId.new()


def test_merge_agent_assets_skill_ref_is_json_serializable_and_prefixed():
    """Regression: SkillRef.skill_id is a typed SkillId. merge_agent_assets must
    dump in JSON mode so the value stored in the ``skills`` JSONB column is the
    canonical ``skill_<uuid>`` string. A python-mode dump would leave a SkillId
    object and raise ``TypeError: Object of type SkillId is not JSON serializable``
    at flush (the default JSONB serializer is ``json.dumps`` with no EntityId
    encoder), breaking agent create/update with skills."""
    skill_id = SkillId.new()
    merged = merge_agent_assets([SkillRef(skill_id=str(skill_id), version="1.0.0")], [], [])
    # Must survive the JSONB column's default json.dumps serializer.
    json.dumps(merged)
    assert merged[0]["skill_id"] == str(skill_id)
    assert isinstance(merged[0]["skill_id"], str)
    assert merged[0]["target"] == "skills"


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


class _Db:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _query):
        return _Result(self.rows)


def _service(rows) -> AgentCommandService:
    db = _Db(rows)
    return AgentCommandService(SimpleNamespace(agents=SqlAlchemyAgentRepository(db)), SimpleNamespace())


def _skill(skill_id: SkillId, *, status="passed", lifecycle="approved"):
    return SimpleNamespace(
        id=skill_id,
        project_id=PROJECT_ID,
        org_version_id=None,
        public_version_id=None,
        name="safe-skill",
        description="d",
        content="c",
        tags=[],
        license=None,
        files=[],
        lifecycle_status=lifecycle,
        security_status=status,
        security_scan_hash="hash",
    )


async def test_agent_skill_ref_gate_rejects_bad_uuid():
    svc = _service([])

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": "skill_not-a-uuid"}], PROJECT_ID)

    assert exc.value.code == "AGENT_SKILL_REF_INVALID"


async def test_agent_skill_ref_gate_rejects_objects_that_only_stringify_as_skill_ids():
    skill_id = SkillId.new()
    svc = _service([])

    class _StringableSkillId:
        def __str__(self) -> str:
            return str(skill_id)

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": _StringableSkillId()}], PROJECT_ID)

    assert exc.value.code == "AGENT_SKILL_REF_INVALID"


async def test_agent_skill_ref_gate_rejects_missing_skill():
    skill_id = SkillId.new()
    svc = _service([])

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": str(skill_id)}], PROJECT_ID)

    assert exc.value.code == "AGENT_SKILL_REF_NOT_FOUND"
    assert str(skill_id) in exc.value.data["skill_ids"]


async def test_agent_skill_ref_gate_rejects_unpublished_skill(monkeypatch):
    skill_id = SkillId.new()
    svc = _service([_skill(skill_id)])

    async def _empty_latest_map(_repo, _ids):
        return {}

    monkeypatch.setattr(
        "app.joysafeter_infrastructure.agents.sqlalchemy_repository.SkillVersionRepository.latest_version_map",
        _empty_latest_map,
    )
    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": str(skill_id)}], PROJECT_ID)

    assert exc.value.code == "AGENT_SKILL_REF_NOT_PUBLISHED"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "reason": "no_published_version"}]


async def test_agent_skill_ref_gate_accepts_published_skill_regardless_of_current_scan(monkeypatch):
    skill_id = SkillId.new()
    svc = _service([_skill(skill_id, status="blocked", lifecycle="draft")])

    async def _latest_map(_repo, ids):
        return {ids[0]: "1.0.0"}

    monkeypatch.setattr(
        "app.joysafeter_infrastructure.agents.sqlalchemy_repository.SkillVersionRepository.latest_version_map",
        _latest_map,
    )
    await svc._validate_skill_refs([{"skill_id": str(skill_id)}], PROJECT_ID)


async def test_agent_skill_ref_gate_accepts_published_runtime_ready_skill(monkeypatch):
    skill_id = SkillId.new()
    svc = _service([_skill(skill_id)])

    async def _latest_map(_repo, ids):
        return {ids[0]: "1.0.0"}

    monkeypatch.setattr(
        "app.joysafeter_infrastructure.agents.sqlalchemy_repository.SkillVersionRepository.latest_version_map",
        _latest_map,
    )
    await svc._validate_skill_refs([{"skill_id": str(skill_id)}], PROJECT_ID)


async def test_agent_skill_ref_gate_rejects_draft_version(monkeypatch):
    skill_id = SkillId.new()
    svc = _service([_skill(skill_id)])

    async def _latest_map(_repo, ids):
        return {}

    monkeypatch.setattr(
        "app.joysafeter_infrastructure.agents.sqlalchemy_repository.SkillVersionRepository.latest_version_map",
        _latest_map,
    )

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": str(skill_id), "version": "draft"}], PROJECT_ID)

    assert exc.value.code == "AGENT_SKILL_REF_NOT_PUBLISHED"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "version": "draft", "reason": "draft_not_allowed"}]


async def test_agent_skill_ref_gate_rejects_missing_pinned_version(monkeypatch):
    skill_id = SkillId.new()
    svc = _service([_skill(skill_id)])

    async def _get_by_version(_repo, requested_skill_id, version):
        assert requested_skill_id == skill_id
        assert version == "9.9.9"
        return None

    monkeypatch.setattr(
        "app.joysafeter_infrastructure.agents.sqlalchemy_repository.SkillVersionRepository.get_by_version",
        _get_by_version,
    )

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": str(skill_id), "version": "9.9.9"}], PROJECT_ID)

    assert exc.value.code == "AGENT_SKILL_REF_NOT_PUBLISHED"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "version": "9.9.9", "reason": "version_not_found"}]


async def test_agent_skill_ref_gate_accepts_existing_pinned_version(monkeypatch):
    skill_id = SkillId.new()
    svc = _service([_skill(skill_id)])

    async def _get_by_version(_repo, requested_skill_id, version):
        assert requested_skill_id == skill_id
        assert version == "1.2.3"
        return object()

    monkeypatch.setattr(
        "app.joysafeter_infrastructure.agents.sqlalchemy_repository.SkillVersionRepository.get_by_version",
        _get_by_version,
    )

    await svc._validate_skill_refs([{"skill_id": str(skill_id), "version": "1.2.3"}], PROJECT_ID)
