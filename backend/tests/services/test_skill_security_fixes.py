"""Unit tests for the P2.9 security hardening of the skill stack.

Four targeted fixes:

  - #1: ``check_skill_access`` owner-branch now honors ``active_org_id``
        so multi-org owners can't read their own skill while pinned to
        a different org context.
  - #2: only the skill OWNER can flip a skill into the ``public``
        visibility tier; admin collaborators can't single-handedly
        expose a private skill to every other organization.
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

from app.joysafeter_domain.models.joysafeter_skill import JoySafeterCollaboratorRole as CollaboratorRole
from app.joysafeter_domain.services.joysafeter_skill_security import SkillSecurityService
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.app_errors import AccessDeniedError, ResourceConflictError
from app.joysafeter_shared.common.skill_permissions import check_skill_access

# ── fixtures ────────────────────────────────────────────────────


def _skill(
    *,
    skill_id=None,
    owner_id="alice",
    visibility="private",
    project_id="proj-1",
    is_public=False,
):
    return SimpleNamespace(
        id=skill_id or uuid.uuid4(),
        owner_id=owner_id,
        visibility=visibility,
        is_public=is_public,
        project_id=project_id,
    )


class _NullDB:
    async def execute(self, _stmt):  # pragma: no cover — patched per-test
        raise AssertionError("DB hit not expected")


def _patch_skill_org_id(monkeypatch, *, org_id):
    """Stub the ``_skill_org_id`` resolver. Returns the org id the
    skill is "really" in — distinct from the caller's active org."""

    async def _resolve(_db, _skill):
        return org_id

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._skill_org_id",
        _resolve,
    )


def _patch_no_collaborator(monkeypatch):
    async def _none(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._get_collaborator",
        _none,
    )


# ── Risk #1 — owner short-circuit honors active_org_id ──────────


async def test_owner_pass_when_in_active_org(monkeypatch):
    """Owner reading from inside the skill's org goes through — the
    fix isn't supposed to block legitimate owner reads."""
    s = _skill(owner_id="alice", visibility="private")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_no_collaborator(monkeypatch)

    await check_skill_access(
        _NullDB(),
        s,
        user_id="alice",
        min_role=CollaboratorRole.admin,
        active_org_id="org-A",
    )


async def test_owner_denied_when_in_different_active_org(monkeypatch):
    """The fix: an owner pinned to a different org context can NOT
    short-circuit through visibility. P2.9 closes the cross-org
    leak that ``list_by_user`` already closes."""
    s = _skill(owner_id="alice", visibility="private")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_no_collaborator(monkeypatch)

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            user_id="alice",
            min_role=CollaboratorRole.admin,
            active_org_id="org-B",
        )


async def test_delete_skill_owner_denied_when_in_different_active_org(monkeypatch):
    """Delete uses the same active-org boundary as read/update.

    The owner-only rule is not enough in a multi-org UI: the same user
    can own skills in org A and org B, but a request pinned to org B must
    not delete an org A skill by direct id.
    """
    s = _skill(owner_id="alice", visibility="private")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_no_collaborator(monkeypatch)
    svc = _make_skill_service(s, current_user_id="alice", active_org_id="org-B")
    svc.repo.delete = AsyncMock()
    svc.file_repo.delete_by_skill = AsyncMock()

    with pytest.raises(AccessDeniedError):
        await svc.delete_skill(s.id, current_user_id="alice")

    svc.file_repo.delete_by_skill.assert_not_called()
    svc.repo.delete.assert_not_called()
    svc.db.commit.assert_not_called()


async def test_owner_pass_when_active_org_not_supplied(monkeypatch):
    """Backwards-compatibility: when ``active_org_id`` is ``None``
    (legacy caller), the owner short-circuit works the way it always
    did. This is the fallback that keeps the rest of the codebase
    from breaking until every caller is migrated."""
    s = _skill(owner_id="alice", visibility="private")
    _patch_no_collaborator(monkeypatch)
    # NOTE: ``_skill_org_id`` is intentionally not patched — the
    # owner branch should NOT call it when ``active_org_id`` is None.

    await check_skill_access(
        _NullDB(),
        s,
        user_id="alice",
        min_role=CollaboratorRole.admin,
        active_org_id=None,
    )


async def test_collaborator_denied_when_in_different_active_org(monkeypatch):
    """Mirror of the owner test for collaborators. An editor
    collaborator pinned to org B shouldn't be able to drive a skill
    in org A — same multi-tenant boundary."""
    s = _skill(owner_id="alice", visibility="private")
    _patch_skill_org_id(monkeypatch, org_id="org-A")

    async def _grant(_db, _skill_id, user_id):
        if user_id == "bob":
            return SimpleNamespace(role=CollaboratorRole.editor)
        return None

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._get_collaborator",
        _grant,
    )

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            user_id="bob",
            min_role=CollaboratorRole.editor,
            active_org_id="org-B",
        )


async def test_public_skill_still_crosses_active_org(monkeypatch):
    """``public`` is the explicit carve-out: it's supposed to cross
    every org boundary. Even with an active_org_id mismatch, viewer
    access through ``public`` must still go through."""
    s = _skill(owner_id="alice", visibility="public", is_public=True)
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_no_collaborator(monkeypatch)

    await check_skill_access(
        _NullDB(),
        s,
        user_id="stranger",
        min_role=CollaboratorRole.viewer,
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


async def test_admin_collaborator_cannot_publish(monkeypatch):
    """An admin collaborator who tries to set ``visibility=public``
    on a skill they don't own hits ``SKILL_VISIBILITY_OWNER_ONLY``
    BEFORE any write happens. The owner-only check sits inside
    ``update_skill`` so the route layer's auth gate (which lets
    admin collaborators through) doesn't decide this on its own."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=False,
        visibility="private",
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

    # Stub ``check_skill_access`` — the route already gated, the
    # collaborator role passes the per-skill ACL. The owner-only
    # check we're testing is separate from that gate.
    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )
    # Also stub the security_service that the update path calls
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service._serialize_skill_files",
        lambda *_a, **_kw: [],
        raising=False,
    )

    with pytest.raises(AccessDeniedError) as ei:
        await svc.update_skill(
            skill_id=skill.id,
            current_user_id="bob",  # admin collaborator, NOT owner
            visibility="public",
        )
    assert ei.value.code == "SKILL_VISIBILITY_OWNER_ONLY"


async def test_archived_skill_rejects_metadata_update_before_scan_or_commit(monkeypatch):
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=False,
        visibility="private",
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
        is_public=False,
        visibility="private",
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
        is_public=False,
        visibility="private",
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


async def test_admin_collaborator_cannot_unpublish(monkeypatch):
    """Mirror of the publish test: pulling a skill OUT of public is
    just as sensitive (the audience loses access in one click) and
    is therefore also owner-only."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=True,
        visibility="public",
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
            current_user_id="bob",
            visibility="private",
        )
    assert ei.value.code == "SKILL_VISIBILITY_OWNER_ONLY"


async def test_owner_can_publish(monkeypatch):
    """Sanity: the owner of a skill can flip it to ``public`` —
    we're not blocking the legitimate path, only the
    collaborator-driven one."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=False,
        visibility="private",
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

    # No exception — owner is allowed to publish their own skill.
    await svc.update_skill(
        skill_id=skill.id,
        current_user_id="alice",  # the owner
        visibility="public",
    )
    assert skill.visibility == "public"
    assert skill.is_public is True


async def test_non_owner_cannot_change_visibility_at_all(monkeypatch):
    """P2.11 — ANY visibility change is owner-only. P2.9 originally
    only gated the public boundary; P2.11 closed the side gate that
    let admin collaborators retier a skill between private / project
    / organization without consulting the owner.

    Rationale: deciding "who can see this skill" is the owner's
    call, the same way "who's a collaborator" is the owner's call.
    Content edits (rename / file CRUD) stay open to admins; the
    audience boundary doesn't."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=False,
        visibility="private",
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

    # ``bob`` is a non-owner admin collaborator. private -> organization
    # crosses no public boundary but DOES change the audience. Reject.
    with pytest.raises(AccessDeniedError) as ei:
        await svc.update_skill(
            skill_id=skill.id,
            current_user_id="bob",
            visibility="organization",
        )
    assert ei.value.code == "SKILL_VISIBILITY_OWNER_ONLY"
    # State must NOT have moved.
    assert skill.visibility == "private"


async def test_owner_can_change_visibility_within_non_public_tiers(monkeypatch):
    """Sanity: the OWNER can retier freely between the non-public
    tiers (it's their call). Only non-owner writes get blocked."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=False,
        visibility="private",
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
        current_user_id="alice",
        visibility="organization",
    )
    assert skill.visibility == "organization"


async def test_non_owner_content_edits_still_allowed(monkeypatch):
    """The fix is scoped to visibility changes. A content / metadata
    edit by an admin collaborator that does NOT touch visibility
    must still succeed — that's exactly what an admin collaborator
    is supposed to be able to do."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=False,
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
        is_public=False,
        visibility="private",
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
        is_public=False,
        visibility="private",
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
        is_public=False,
        visibility="private",
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


async def test_non_owner_combined_owner_and_visibility_attack(monkeypatch):
    """The combined attack the ownership gate was designed to block:
    set owner_id=self + visibility=public in the same PUT. The
    visibility gate checks ``owner_before_change``, so even though
    ``skill.owner_id`` after the owner_id mutation would equal the
    caller, the gate still recognizes the caller as a non-owner.

    In practice the ownership gate above raises first, but this
    test exists to make sure NEITHER gate alone is enough — both
    have to use the pre-change owner identity."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=False,
        visibility="private",
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
            owner_id="bob",
            visibility="public",
        )
    # Both fields must remain untouched.
    assert skill.owner_id == "alice"
    assert skill.visibility == "private"


@pytest.mark.asyncio
async def test_non_owner_cannot_escalate_via_is_public_boolean(monkeypatch):
    """P2.15: ``is_public`` is the legacy boolean that the dual-write
    block translates back into ``visibility``. A non-owner admin
    collaborator who sends only ``{"is_public": true}`` would have
    skipped the ``visibility`` owner-only gate (because the explicit
    ``visibility`` arg stayed None) yet still escalate the skill to
    ``public`` once the dual-write ran. The fix recomputes the
    effective target visibility from BOTH the explicit field and
    the legacy boolean, so the gate sees the real change."""
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="alice",
        is_public=False,
        visibility="private",
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
            current_user_id="bob",   # admin collaborator, NOT owner
            is_public=True,          # the bypass vector
            # NOTE: visibility intentionally NOT passed
        )
    assert ei.value.code == "SKILL_VISIBILITY_OWNER_ONLY"
    # The dual-write must not have run.
    assert skill.is_public is False
    assert skill.visibility == "private"
