"""Unit tests for the P2.9 security hardening of the skill stack.

Four targeted fixes:

  - #1: ``check_skill_access`` owner-branch now honors ``active_org_id``
        so multi-org owners can't read their own skill while pinned to
        a different org context.
  - #2: only the skill OWNER can flip a skill into the ``public``
        visibility tier; admin collaborators can't single-handedly
        expose a project skill to every other organization.
  - #3: same gate applies in reverse — un-publishing a public skill
        is also owner-only.
  - #5: admin batch rescan stays scoped to the caller's active org;
        this file just covers the org-isolation behavior of the
        ``check_skill_access`` change. The route-level org scoping
        is exercised end-to-end via the rescan filter SQL.

(P1's transitions stay self-approvable until P2 introduces the
admin reviewer gate — that's a documented followup, not a regression.)
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.joysafeter_domain.services.joysafeter_skill_security import SkillSecurityService
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.app_errors import AccessDeniedError, ResourceConflictError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth.context import ProjectCapability
from app.joysafeter_shared.common.skill_permissions import check_skill_access

# ── fixtures ────────────────────────────────────────────────────


def _skill(
    *,
    skill_id=None,
    owner_id="alice",
    visibility="project",
    project_id="proj-1",
):
    return SimpleNamespace(
        id=skill_id or uuid.uuid4(),
        owner_id=owner_id,
        visibility=visibility,
        project_id=project_id,
    )


class _NullDB:
    async def execute(self, _stmt):  # pragma: no cover — patched per-test
        raise AssertionError("DB hit not expected")


def _patch_skill_org_id(monkeypatch, *, org_id):
    """Stub the ``resolve_skill_org_id`` resolver. Returns the org id the
    skill is "really" in — distinct from the caller's active org."""

    async def _resolve(_db, _skill):
        return org_id

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions.resolve_skill_org_id",
        _resolve,
    )


def _patch_project_role(monkeypatch, *, role):
    async def _role(_db, _user_id, _project_id):
        return role

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._project_member_role",
        _role,
    )


# ── Risk #1 — capability path honors active_org_id (single-axis) ──


async def test_project_admin_pass_when_in_active_org(monkeypatch):
    """A project admin reading from inside the skill's org goes through."""
    s = _skill(owner_id="alice", visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="admin")

    await check_skill_access(
        _NullDB(),
        s,
        user_id="alice",
        required=ProjectCapability.ADMIN,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-A",
    )


async def test_project_admin_denied_when_in_different_active_org(monkeypatch):
    """The fix: a caller pinned to a different org context can NOT reach
    the skill via project capability. Org isolation gates the capability
    path — P2.9 closes the cross-org leak that ``list_by_user`` closes."""
    s = _skill(owner_id="alice", visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="admin")

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            user_id="alice",
            required=ProjectCapability.ADMIN,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-B",
        )


async def test_delete_skill_owner_denied_when_in_different_active_org(monkeypatch):
    """Delete uses the same active-org boundary. The owner-only rule is
    not enough in a multi-org UI: the same user can own skills in org A
    and org B, but a request pinned to org B must not delete an org A
    skill by direct id."""
    s = _skill(owner_id="alice", visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="admin")
    svc = _make_skill_service(s, current_user_id="alice", active_org_id="org-B")
    svc.repo.delete = AsyncMock()
    svc.file_repo.delete_by_skill = AsyncMock()

    with pytest.raises(AccessDeniedError):
        await svc.delete_skill(s.id, current_user_id="alice")

    svc.file_repo.delete_by_skill.assert_not_called()
    svc.repo.delete.assert_not_called()
    svc.db.commit.assert_not_called()


async def test_project_admin_non_owner_can_delete_skill(monkeypatch):
    """Regression: delete is gated on ADMIN capability, not skill ownership.

    A project admin (or org super-user) who is NOT the skill's ``owner_id``
    must be able to delete it — that is exactly what ``check_skill_access``
    with ``ProjectCapability.ADMIN`` grants, and the module contract in
    ``skill_permissions.py`` states there is "no owner short-circuit". A
    leftover ``owner_id != current_user_id`` guard used to 403 this caller
    before the capability gate ever ran; this test pins that it doesn't."""
    s = _skill(owner_id="alice", visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="admin")
    svc = _make_skill_service(s, current_user_id="bob", active_org_id="org-A")
    svc.repo.delete = AsyncMock()
    svc.file_repo.delete_by_skill = AsyncMock()
    svc._has_skill_references = AsyncMock(return_value=False)

    # "bob" is a project admin in the skill's org but NOT the owner ("alice").
    await svc.delete_skill(s.id, current_user_id="bob")

    svc.file_repo.delete_by_skill.assert_awaited_once_with(s.id)
    svc.repo.delete.assert_awaited_once_with(s.id)
    svc.db.commit.assert_awaited_once()


async def test_org_superuser_gets_admin_in_own_org(monkeypatch):
    """Org owner/admin manage every skill in their own org — capability
    resolves to ADMIN without a project row."""
    s = _skill(owner_id="alice", visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)

    await check_skill_access(
        _NullDB(),
        s,
        user_id="boss",
        required=ProjectCapability.ADMIN,
        caller_org_role=JoySafeterRole.ADMIN,
        active_org_id="org-A",
    )


async def test_public_skill_still_crosses_active_org(monkeypatch):
    """``public`` is the explicit carve-out: readable from any org even
    with an active_org mismatch."""
    s = _skill(owner_id="alice", visibility="public")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)

    await check_skill_access(
        _NullDB(),
        s,
        user_id="stranger",
        required=ProjectCapability.READ,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-B",
    )


# ── Risks #2 / #3 — public visibility is owner-only ─────────────


def _make_skill_service(skill, *, current_user_id, active_org_id=None):
    """Construct ``SkillService`` with everything it needs to walk
    the public-visibility gate. The service hits ``check_skill_access``
    first (we stub it out so the test scopes to the gate itself),
    runs the gate, then writes back. We never reach DB commit because
    the gate raises before any commit when it triggers."""
    svc = SkillService.__new__(SkillService)
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.db.flush = AsyncMock()
    svc.repo = MagicMock()
    svc.repo.get_with_files = AsyncMock(return_value=skill)
    svc.file_repo = MagicMock()
    svc.security_service = MagicMock()
    svc.security_service.scan_for_write = AsyncMock(return_value=None)
    svc.security_service.apply_latest_scan = MagicMock()
    svc._pending_async_scans = []
    svc._active_org_id = active_org_id
    return svc


async def test_archived_skill_rejects_metadata_update_before_scan_or_commit(monkeypatch):
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        visibility="project",
        project_id="proj-1",
        name="x",
        description="x",
        content="x",
        tags=[],
        source_type="manual",
        source_url=None,
        root_path=None,
        license=None,
        compatibility=None,
        meta_data={},
        allowed_tools=[],
        files=[],
        lifecycle_status="archived",
    )
    svc = _make_skill_service(skill, current_user_id="alice")

    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    with pytest.raises(ResourceConflictError) as ei:
        await svc.update_skill(
            skill_id=skill.id,
            current_user_id="alice",
            description="changed",
        )

    assert ei.value.code == "SKILL_ARCHIVED"
    assert skill.description == "x"
    svc.security_service.scan_for_write.assert_not_awaited()
    svc.db.commit.assert_not_awaited()


async def test_archived_skill_rejects_manual_rescan_before_scanning_or_background_dispatch(monkeypatch):
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        visibility="project",
        project_id="proj-1",
        name="x",
        description="x",
        content="x",
        tags=[],
        license=None,
        files=[],
        lifecycle_status="archived",
    )
    svc = _make_skill_service(skill, current_user_id="alice")
    svc.security_service.skill_repo = MagicMock()
    svc.security_service.skill_repo.get_with_files = AsyncMock(return_value=skill)
    svc.security_service.files_from_skill = MagicMock(return_value=[])
    svc.security_service.mark_scanning = AsyncMock()
    svc.security_service.repo = MagicMock()
    svc.security_service.repo.get_latest_by_skill = AsyncMock(return_value=None)
    svc.security_service.rescan_existing_skill = AsyncMock()

    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    with pytest.raises(ResourceConflictError) as ei:
        await svc.rescan_skill_async(skill.id, current_user_id="alice")

    assert ei.value.code == "SKILL_ARCHIVED"
    svc.security_service.mark_scanning.assert_not_awaited()
    svc.security_service.rescan_existing_skill.assert_not_awaited()
    assert svc.drain_pending_async_scans() == []
    svc.db.commit.assert_not_awaited()


async def test_archived_skill_rejects_sync_rescan_before_scan_or_commit(monkeypatch):
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        visibility="project",
        project_id="proj-1",
        name="x",
        description="x",
        content="x",
        tags=[],
        license=None,
        files=[],
        lifecycle_status="archived",
    )
    svc = SkillSecurityService.__new__(SkillSecurityService)
    svc.db = MagicMock()
    svc.db.commit = AsyncMock()
    svc.db.flush = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.skill_repo = MagicMock()
    svc.skill_repo.get_with_files = AsyncMock(return_value=skill)
    svc.scan_for_write = AsyncMock()
    svc._active_org_id = None

    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_security.check_skill_access",
        _allow,
    )

    with pytest.raises(ResourceConflictError) as ei:
        await svc.rescan_existing_skill(skill.id, current_user_id="alice")

    assert ei.value.code == "SKILL_ARCHIVED"
    svc.scan_for_write.assert_not_awaited()
    svc.db.commit.assert_not_awaited()


async def test_non_owner_content_edits_still_allowed(monkeypatch):
    """The fix is scoped to visibility changes. A content / metadata
    edit by an admin collaborator that does NOT touch visibility
    must still succeed — that's exactly what an admin collaborator
    is supposed to be able to do."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        visibility="organization",
        project_id="proj-1",
        name="x",
        description="x",
        content="x",
        tags=[],
        source_type="manual",
        source_url=None,
        root_path=None,
        license=None,
        compatibility=None,
        meta_data={},
        allowed_tools=[],
        files=[],
    )

    svc = _make_skill_service(skill, current_user_id="bob")

    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    # No ``visibility=`` passed — just a description change. Admin
    # collaborator is free to do this.
    await svc.update_skill(
        skill_id=skill.id,
        current_user_id="bob",
        description="updated by admin collaborator",
    )
    assert skill.description == "updated by admin collaborator"
    assert skill.visibility == "organization"  # untouched


async def test_non_owner_cannot_transfer_ownership(monkeypatch):
    """P2.12 — a non-owner cannot set ``owner_id`` to themselves
    (or anyone else). Ownership transfer is the most privileged
    write on a skill — the new owner gains every owner short-
    circuit on visibility / publish / lifecycle in a single API
    call. The service-level gate refuses it.

    Without this gate, an admin collaborator could:
      1. PUT /skills/{id} with owner_id=<themselves>, visibility=public
      2. The visibility gate sees the new owner_id matches caller -> pass
      3. The skill is published cross-org, owned by the attacker

    The gate captures ``owner_before_change`` and uses it for both
    the ownership and the visibility checks so this sequence
    breaks at step 1."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        visibility="project",
        project_id="proj-1",
        name="x",
        description="x",
        content="x",
        tags=[],
        source_type="manual",
        source_url=None,
        root_path=None,
        license=None,
        compatibility=None,
        meta_data={},
        allowed_tools=[],
        files=[],
    )

    svc = _make_skill_service(skill, current_user_id="bob")

    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    with pytest.raises(AccessDeniedError) as ei:
        await svc.update_skill(
            skill_id=skill.id,
            current_user_id="bob",  # admin collaborator
            owner_id="bob",  # tries to steal ownership
        )
    assert ei.value.code == "SKILL_OWNERSHIP_OWNER_ONLY"
    # State must NOT have moved.
    assert skill.owner_id == "alice"


async def test_owner_can_transfer_ownership(monkeypatch):
    """The owner CAN hand the skill off to someone else. We don't
    want the gate to break legitimate ownership transfers."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        visibility="project",
        project_id="proj-1",
        name="x",
        description="x",
        content="x",
        tags=[],
        source_type="manual",
        source_url=None,
        root_path=None,
        license=None,
        compatibility=None,
        meta_data={},
        allowed_tools=[],
        files=[],
    )

    svc = _make_skill_service(skill, current_user_id="alice")

    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    await svc.update_skill(
        skill_id=skill.id,
        current_user_id="alice",  # the current owner
        owner_id="carol",
    )
    assert skill.owner_id == "carol"


async def test_rejected_put_does_not_leak_via_scan_dispatch(monkeypatch):
    """P2.13 — privilege gates run BEFORE the security scan
    dispatch, so a rejected PUT must not have invoked
    ``scan_for_write``. Without this ordering, an attacker could
    PUT with spoofed owner_id + arbitrary content and trigger a
    scan run logged under their identity against a skill they
    don't own — useful for probing scanner rules against private
    content, and noise in the audit trail.

    This test pins the ordering: when the ownership gate fires,
    the mock ``scan_for_write`` must NEVER have been awaited.
    """
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        visibility="project",
        project_id="proj-1",
        name="x",
        description="x",
        content="x",
        tags=[],
        source_type="manual",
        source_url=None,
        root_path=None,
        license=None,
        compatibility=None,
        meta_data={},
        allowed_tools=[],
        files=[],
    )

    svc = _make_skill_service(skill, current_user_id="bob")

    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )

    with pytest.raises(AccessDeniedError):
        await svc.update_skill(
            skill_id=skill.id,
            current_user_id="bob",
            owner_id="bob",  # privileged attempt
            content="attacker-controlled content for scan probe",
        )
    # Scan dispatch must NOT have run — its mock would record a call.
    svc.security_service.scan_for_write.assert_not_called()
