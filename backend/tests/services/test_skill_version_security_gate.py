"""Unit tests for the security gate in ``SkillVersionService.publish_version``.

A skill whose latest security verdict is ``blocked`` (SkillSpector found a
HIGH/CRITICAL issue) must not be publishable — the runtime already refuses to
load such skills, so a published snapshot would be dead weight. Only
``blocked`` is gated; ``passed``/``warning`` publish normally and un-scanned /
in-flight states are intentionally allowed through this particular gate.

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


@pytest.mark.parametrize("status", ["passed", "warning", "not_scanned", "scanning"])
async def test_non_blocked_skill_passes_security_gate(status, monkeypatch):
    """Statuses other than ``blocked`` must clear the security gate. We assert
    the call does NOT raise ``SKILL_SECURITY_BLOCKED``; it may still fail later
    on semver / DB work (which we don't stub), so we only guard the gate."""
    skill = _skill(status)
    svc = _make_service(skill, monkeypatch=monkeypatch)
    try:
        await svc.publish_version(
            skill_id=skill.id,
            current_user_id="user-1",
            version_str="1.0.0",
        )
    except InvalidRequestError as e:
        assert e.code != "SKILL_SECURITY_BLOCKED"
    except Exception:
        # Any non-InvalidRequestError (e.g. missing repo on the bare service)
        # means we got PAST the security gate, which is what we're asserting.
        pass
