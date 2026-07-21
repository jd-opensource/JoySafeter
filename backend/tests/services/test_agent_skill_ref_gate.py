from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_shared.common.app_errors import InvalidRequestError


pytestmark = pytest.mark.no_db


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


def _skill(skill_id: uuid.UUID, *, status="passed", lifecycle="approved"):
    return SimpleNamespace(
        id=skill_id,
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
    svc = JoySafeterAgentService(_Db([]))

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": "skill_not-a-uuid"}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_INVALID"


async def test_agent_skill_ref_gate_rejects_missing_skill():
    skill_id = uuid.uuid4()
    svc = JoySafeterAgentService(_Db([]))

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": f"skill_{skill_id}"}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_FOUND"
    assert str(skill_id) in exc.value.data["skill_ids"]


async def test_agent_skill_ref_gate_rejects_unpublished_skill(monkeypatch):
    skill_id = uuid.uuid4()
    svc = JoySafeterAgentService(_Db([_skill(skill_id)]))

    async def _empty_latest_map(_repo, _ids):
        return {}

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.SkillVersionRepository.latest_version_map",
        _empty_latest_map,
    )
    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": f"skill_{skill_id}"}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_RUNTIME_READY"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "reason": "no_published_version"}]


async def test_agent_skill_ref_gate_rejects_runtime_blocked_skill(monkeypatch):
    skill_id = uuid.uuid4()
    svc = JoySafeterAgentService(_Db([_skill(skill_id, status="blocked")]))

    async def _latest_map(_repo, ids):
        return {ids[0]: "1.0.0"}

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.SkillVersionRepository.latest_version_map",
        _latest_map,
    )
    with patch(
        "app.joysafeter_domain.services.joysafeter_agent_service.is_skill_usable",
        return_value=(False, "security_blocked"),
    ):
        with pytest.raises(InvalidRequestError) as exc:
            await svc._validate_skill_refs([{"skill_id": f"skill_{skill_id}"}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_RUNTIME_READY"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "reason": "security_blocked"}]


async def test_agent_skill_ref_gate_accepts_published_runtime_ready_skill(monkeypatch):
    skill_id = uuid.uuid4()
    svc = JoySafeterAgentService(_Db([_skill(skill_id)]))

    async def _latest_map(_repo, ids):
        return {ids[0]: "1.0.0"}

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.SkillVersionRepository.latest_version_map",
        _latest_map,
    )
    with patch(
        "app.joysafeter_domain.services.joysafeter_agent_service.is_skill_usable",
        return_value=(True, None),
    ):
        await svc._validate_skill_refs([{"skill_id": f"skill_{skill_id}"}], "project-a")


async def test_agent_skill_ref_gate_rejects_draft_version(monkeypatch):
    skill_id = uuid.uuid4()
    svc = JoySafeterAgentService(_Db([_skill(skill_id)]))

    async def _latest_map(_repo, ids):
        return {}

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.SkillVersionRepository.latest_version_map",
        _latest_map,
    )

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": f"skill_{skill_id}", "version": "draft"}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_RUNTIME_READY"
    assert exc.value.data["skills"] == [
        {"skill_id": str(skill_id), "version": "draft", "reason": "draft_not_allowed"}
    ]


async def test_agent_skill_ref_gate_rejects_missing_pinned_version(monkeypatch):
    skill_id = uuid.uuid4()
    svc = JoySafeterAgentService(_Db([_skill(skill_id)]))

    async def _get_by_version(_repo, requested_skill_id, version):
        assert requested_skill_id == skill_id
        assert version == "9.9.9"
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.SkillVersionRepository.get_by_version",
        _get_by_version,
    )

    with patch(
        "app.joysafeter_domain.services.joysafeter_agent_service.is_skill_usable",
        return_value=(True, None),
    ):
        with pytest.raises(InvalidRequestError) as exc:
            await svc._validate_skill_refs([{"skill_id": f"skill_{skill_id}", "version": "9.9.9"}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_RUNTIME_READY"
    assert exc.value.data["skills"] == [
        {"skill_id": str(skill_id), "version": "9.9.9", "reason": "version_not_found"}
    ]


async def test_agent_skill_ref_gate_accepts_existing_pinned_version(monkeypatch):
    skill_id = uuid.uuid4()
    svc = JoySafeterAgentService(_Db([_skill(skill_id)]))

    async def _get_by_version(_repo, requested_skill_id, version):
        assert requested_skill_id == skill_id
        assert version == "1.2.3"
        return object()

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.SkillVersionRepository.get_by_version",
        _get_by_version,
    )

    with patch(
        "app.joysafeter_domain.services.joysafeter_agent_service.is_skill_usable",
        return_value=(True, None),
    ):
        await svc._validate_skill_refs([{"skill_id": f"skill_{skill_id}", "version": "1.2.3"}], "project-a")
