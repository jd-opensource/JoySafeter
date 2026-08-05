"""Unit tests for the security gate in ``SkillVersionService.publish_version``.

A skill that is not runtime-ready must not be publishable — otherwise we create
a published snapshot that the agent picker can select but the orchestrator will
refuse to load. ``blocked`` keeps its historical high-risk error code;
``passed``/``warning`` publish normally, while un-scanned / in-flight / drifted
states fail with a runtime-readiness reason.

Strategy: the gate fires immediately after the permission check and before any
semver / DB work, so we stub ``_get_skill_with_files_or_404`` to return a
seeded skill and bypass ``check_skill_access``. That keeps the test in-process
and focused on the gate alone.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_skill_service import (
    SkillVersionService,
)
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.config import settings as app_settings

pytestmark = pytest.mark.no_db


class _FakeDB:
    async def commit(self):
        pass

    async def refresh(self, _):
        pass

    async def flush(self):
        pass

    def add(self, _):
        pass


def _make_service(skill, *, monkeypatch):
    svc = SkillVersionService.__new__(SkillVersionService)
    svc.db = _FakeDB()
    svc._active_org_id = None

    # The publish security gate only runs when scanning is enabled; the
    # global default is off, so turn it on to exercise the gate itself.
    monkeypatch.setattr(app_settings, "skill_security_scan_enabled", True)

    async def _get_skill(_skill_id):
        return skill

    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(svc, "_get_skill_with_files_or_404", _get_skill)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )
    return svc


def _skill(security_status):
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="user-1",
        security_status=security_status,
        security_severity="HIGH" if security_status == "blocked" else None,
        security_score=7 if security_status == "blocked" else None,
    )


async def test_blocked_skill_cannot_publish(monkeypatch):
    skill = _skill("blocked")
    svc = _make_service(skill, monkeypatch=monkeypatch)
    with pytest.raises(InvalidRequestError) as exc:
        await svc.publish_version(
            skill_id=skill.id,
            current_user_id="user-1",
            version_str="1.0.0",
        )
    assert exc.value.code == "SKILL_SECURITY_BLOCKED"


@pytest.mark.parametrize("status", ["passed", "warning"])
async def test_runtime_ready_skill_passes_publish_gate(status, monkeypatch):
    """Runtime-ready statuses must clear the publish gate. The bare service may
    still fail later on semver / DB work; that is outside this gate."""
    skill = _skill(status)
    svc = _make_service(skill, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_security.is_skill_usable",
        lambda _skill: (True, None),
    )
    try:
        await svc.publish_version(
            skill_id=skill.id,
            current_user_id="user-1",
            version_str="1.0.0",
        )
    except InvalidRequestError as e:
        assert e.code not in {"SKILL_SECURITY_BLOCKED", "SKILL_VERSION_NOT_RUNTIME_READY"}
    except Exception:
        # Any non-InvalidRequestError (e.g. missing repo on the bare service)
        # means we got PAST the publish gate, which is what we're asserting.
        pass


@pytest.mark.parametrize(
    ("status", "reason"),
    [("not_scanned", "security_not_scanned"), ("scanning", "security_scanning")],
)
async def test_runtime_not_ready_skill_cannot_publish(status, reason, monkeypatch):
    skill = _skill(status)
    svc = _make_service(skill, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_security.is_skill_usable",
        lambda _skill: (False, reason),
    )

    with pytest.raises(InvalidRequestError) as exc:
        await svc.publish_version(
            skill_id=skill.id,
            current_user_id="user-1",
            version_str="1.0.0",
        )

    assert exc.value.code == "SKILL_VERSION_NOT_RUNTIME_READY"
    assert exc.value.data == {"skill_id": str(skill.id), "reason": reason}
