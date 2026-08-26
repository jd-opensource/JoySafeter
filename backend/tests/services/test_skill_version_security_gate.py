"""Publish-boundary tests for Skill security enforcement.

Security scans are informational by default.  When the global enforcement
switch is enabled, publishing performs a fresh fail-closed scan; no other
workflow is allowed to treat the mutable Skill row's scan status as a gate.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_skill_service import SkillVersionService
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.config import settings as app_settings
from app.joysafeter_shared.ids import OrganizationId, ProjectId, SkillId, SkillSecurityScanId, UserId

pytestmark = pytest.mark.no_db

USER_ID = UserId.new()
ORGANIZATION_ID = OrganizationId.new()
PROJECT_ID = ProjectId.new()


class _ReachedVersionValidation(Exception):
    pass


class _FakeDB:
    def __init__(self):
        self.commit_count = 0

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _):
        pass

    async def flush(self):
        pass

    def add(self, _):
        pass


class _StopAfterPublishGateRepo:
    async def get_highest_version_str(self, _skill_id):
        raise _ReachedVersionValidation


class _EmptyVersionRepo:
    async def get_highest_version_str(self, _skill_id):
        return None


class _EmptySkillFileRepo:
    async def list_by_skill(self, _skill_id):
        return []


def _make_service(skill, *, monkeypatch, stop_after_gate=True):
    svc = SkillVersionService.__new__(SkillVersionService)
    svc.db = _FakeDB()
    svc.repo = _StopAfterPublishGateRepo() if stop_after_gate else _EmptyVersionRepo()
    svc.skill_file_repo = _EmptySkillFileRepo()
    svc._active_org_id = ORGANIZATION_ID

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


def _skill(*, lifecycle_status="approved", security_status="blocked"):
    return SimpleNamespace(
        id=SkillId.new(),
        owner_id=USER_ID,
        project_id=PROJECT_ID,
        lifecycle_status=lifecycle_status,
        name="skill-a",
        description="description",
        content="content",
        tags=[],
        license=None,
        compatibility=None,
        meta_data={},
        allowed_tools=[],
        files=[],
        security_status=security_status,
        security_severity="HIGH" if security_status == "blocked" else None,
        security_score=7 if security_status == "blocked" else None,
        security_scan_id=None,
        security_scan_hash=None,
        security_scanned_at=None,
        security_recommendation=None,
        security_issues_count=0,
        security_critical_count=0,
        security_high_count=0,
        security_medium_count=0,
        security_low_count=0,
    )


def _scan(status: str, *, error_message: str | None = None):
    return SimpleNamespace(
        id=SkillSecurityScanId.new(),
        created_at=None,
        status=status,
        score=9 if status == "blocked" else None,
        severity="CRITICAL" if status == "blocked" else None,
        recommendation="DO_NOT_INSTALL" if status == "blocked" else None,
        target_hash="a" * 64,
        issues_count=1 if status == "blocked" else 0,
        critical_count=1 if status == "blocked" else 0,
        high_count=0,
        medium_count=0,
        low_count=0,
        report={},
        error_message=error_message,
    )


async def test_enforcement_defaults_to_disabled():
    assert app_settings.skill_security_scan_enforcement_enabled is False


async def test_blocked_scan_does_not_gate_publish_when_enforcement_disabled(monkeypatch):
    monkeypatch.setattr(app_settings, "skill_security_scan_enabled", True)
    monkeypatch.setattr(app_settings, "skill_security_scan_enforcement_enabled", False)
    skill = _skill(security_status="blocked")
    svc = _make_service(skill, monkeypatch=monkeypatch)

    with pytest.raises(_ReachedVersionValidation):
        await svc.publish_version(skill.id, USER_ID, "1.0.0")


async def test_publish_requires_approved_skill_even_without_scan_enforcement(monkeypatch):
    monkeypatch.setattr(app_settings, "skill_security_scan_enabled", False)
    monkeypatch.setattr(app_settings, "skill_security_scan_enforcement_enabled", False)
    skill = _skill(lifecycle_status="draft", security_status="not_scanned")
    svc = _make_service(skill, monkeypatch=monkeypatch, stop_after_gate=False)

    with pytest.raises(InvalidRequestError) as exc:
        await svc.publish_version(skill.id, USER_ID, "1.0.0")

    assert exc.value.code == "SKILL_VERSION_NOT_APPROVED"
    assert exc.value.data["reason"] == "skill_not_approved"


async def test_enforced_publish_runs_fresh_fail_closed_scan(monkeypatch):
    monkeypatch.setattr(app_settings, "skill_security_scan_enabled", True)
    monkeypatch.setattr(app_settings, "skill_security_scan_enforcement_enabled", True)
    skill = _skill(security_status="passed")
    svc = _make_service(skill, monkeypatch=monkeypatch, stop_after_gate=False)
    calls = []

    async def _blocked(_self, **kwargs):
        calls.append(kwargs)
        return _scan("blocked")

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_security.SkillSecurityService.scan_for_write",
        _blocked,
    )

    with pytest.raises(InvalidRequestError) as exc:
        await svc.publish_version(skill.id, USER_ID, "1.0.0")

    assert exc.value.code == "SKILL_SECURITY_SCAN_REJECTED"
    assert calls[0]["trigger"] == "publish"
    assert "enforce_write_policy" not in calls[0]
    assert "failure_mode" not in calls[0]
    assert skill.security_status == "blocked"
    assert svc.db.commit_count == 1


async def test_enforced_publish_records_scanner_failure_before_rejecting(monkeypatch):
    monkeypatch.setattr(app_settings, "skill_security_scan_enabled", True)
    monkeypatch.setattr(app_settings, "skill_security_scan_enforcement_enabled", True)
    skill = _skill(security_status="passed")
    svc = _make_service(skill, monkeypatch=monkeypatch, stop_after_gate=False)

    async def _failed(_self, **_kwargs):
        return _scan("failed", error_message="scanner unreachable")

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_security.SkillSecurityService.scan_for_write",
        _failed,
    )

    with pytest.raises(InvalidRequestError) as exc:
        await svc.publish_version(skill.id, USER_ID, "1.0.0")

    assert exc.value.code == "SKILL_SECURITY_SCAN_FAILED"
    assert exc.value.data["error_message"] == "scanner unreachable"
    assert skill.security_status == "failed"
    assert svc.db.commit_count == 1


async def test_enforced_publish_fails_when_scanner_is_disabled(monkeypatch):
    monkeypatch.setattr(app_settings, "skill_security_scan_enabled", False)
    monkeypatch.setattr(app_settings, "skill_security_scan_enforcement_enabled", True)
    skill = _skill(security_status="passed")
    svc = _make_service(skill, monkeypatch=monkeypatch, stop_after_gate=False)

    with pytest.raises(InvalidRequestError) as exc:
        await svc.publish_version(skill.id, USER_ID, "1.0.0")

    assert exc.value.code == "SKILL_SECURITY_SCAN_FAILED"
    assert exc.value.data["reason"] == "scanner_disabled"
