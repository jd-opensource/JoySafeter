from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.joysafeter_domain.schemas.joysafeter_agent import SkillRef
from app.joysafeter_domain.services.joysafeter_agent_service import (
    JoySafeterAgentService,
    _merge_agent_assets,
)
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.config import settings as app_settings
from app.joysafeter_shared.ids import SkillId

pytestmark = pytest.mark.no_db


def test_merge_agent_assets_skill_ref_is_json_serializable_and_prefixed():
    """Regression: SkillRef.skill_id is a typed SkillId. _merge_agent_assets must
    dump in JSON mode so the value stored in the ``skills`` JSONB column is the
    canonical ``skill_<uuid>`` string. A python-mode dump would leave a SkillId
    object and raise ``TypeError: Object of type SkillId is not JSON serializable``
    at flush (the default JSONB serializer is ``json.dumps`` with no EntityId
    encoder), breaking agent create/update with skills."""
    skill_id = SkillId.new()
    merged = _merge_agent_assets([SkillRef(skill_id=str(skill_id), version="1.0.0")], [], [])
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


def _skill(skill_id: SkillId, *, status="passed", lifecycle="approved"):
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
    skill_id = SkillId.new()
    svc = JoySafeterAgentService(_Db([]))

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": str(skill_id)}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_FOUND"
    assert str(skill_id) in exc.value.data["skill_ids"]


async def test_agent_skill_ref_gate_rejects_unpublished_skill(monkeypatch):
    skill_id = SkillId.new()
    svc = JoySafeterAgentService(_Db([_skill(skill_id)]))

    async def _empty_latest_map(_repo, _ids):
        return {}

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.SkillVersionRepository.latest_version_map",
        _empty_latest_map,
    )
    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": str(skill_id)}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_RUNTIME_READY"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "reason": "no_published_version"}]


async def test_agent_skill_ref_gate_rejects_runtime_blocked_skill(monkeypatch):
    skill_id = SkillId.new()
    svc = JoySafeterAgentService(_Db([_skill(skill_id, status="blocked")]))

    # The security-status gate only runs when scanning is enabled; with it
    # off, only lifecycle_status is checked. Turn it on to reach is_skill_usable.
    monkeypatch.setattr(app_settings, "skill_security_scan_enabled", True)

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
            await svc._validate_skill_refs([{"skill_id": str(skill_id)}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_RUNTIME_READY"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "reason": "security_blocked"}]


async def test_agent_skill_ref_gate_accepts_published_runtime_ready_skill(monkeypatch):
    skill_id = SkillId.new()
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
        await svc._validate_skill_refs([{"skill_id": str(skill_id)}], "project-a")


async def test_agent_skill_ref_gate_rejects_draft_version(monkeypatch):
    skill_id = SkillId.new()
    svc = JoySafeterAgentService(_Db([_skill(skill_id)]))

    async def _latest_map(_repo, ids):
        return {}

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.SkillVersionRepository.latest_version_map",
        _latest_map,
    )

    with pytest.raises(InvalidRequestError) as exc:
        await svc._validate_skill_refs([{"skill_id": str(skill_id), "version": "draft"}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_RUNTIME_READY"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "version": "draft", "reason": "draft_not_allowed"}]


async def test_agent_skill_ref_gate_rejects_missing_pinned_version(monkeypatch):
    skill_id = SkillId.new()
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
            await svc._validate_skill_refs([{"skill_id": str(skill_id), "version": "9.9.9"}], "project-a")

    assert exc.value.code == "AGENT_SKILL_REF_NOT_RUNTIME_READY"
    assert exc.value.data["skills"] == [{"skill_id": str(skill_id), "version": "9.9.9", "reason": "version_not_found"}]


async def test_agent_skill_ref_gate_accepts_existing_pinned_version(monkeypatch):
    skill_id = SkillId.new()
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
        await svc._validate_skill_refs([{"skill_id": str(skill_id), "version": "1.2.3"}], "project-a")
