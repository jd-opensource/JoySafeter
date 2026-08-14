"""Security tests for the single-axis project-capability skill gate.

Phase 2 of the skills single-axis redesign replaces the per-skill
collaborator ACL with a SINGLE-AXIS project-capability gate:

  ``check_skill_access(db, skill, user_id, required, *,
                       caller_org_role, active_org_id)``

The gate derives WRITE/ADMIN capability SOLELY from the caller's
effective capability on the skill's PROJECT (via
``effective_project_capability(org_role, project_role)``). Org
owner/admin are super-users (ADMIN everywhere in their org). READ can
additionally be granted through the visibility tier (public crosses
orgs; organization only inside the active org).

These tests are the security core: a wrong OR-clause or a missing
org-isolation check re-introduces a cross-tenant leak. Membership and
org-id resolution are patched at the helper boundary so the tests run
without a real database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth.context import ProjectCapability
from app.joysafeter_shared.common.skill_permissions import _effective_visibility, check_skill_access

pytestmark = pytest.mark.no_db

MODULE = "app.joysafeter_shared.common.skill_permissions"


def _skill(*, owner_id="alice", visibility="project", project_id="proj-1"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id,
        visibility=visibility,
        project_id=project_id,
    )


class _NullDB:
    """The gate resolves org id + project role + org membership through
    helpers we patch; the raw session must never be touched here."""

    async def execute(self, _stmt):  # pragma: no cover — patch a helper
        raise AssertionError("DB not expected to be hit; patch a helper")


def _patch_skill_org_id(monkeypatch, *, org_id):
    async def _resolve(_db, _skill):
        return org_id

    monkeypatch.setattr(f"{MODULE}.resolve_skill_org_id", _resolve)


def _patch_project_role(monkeypatch, *, role):
    """Stub the new single-row ProjectMember.role lookup the gate uses to
    compute the caller's capability on the skill's own project."""

    async def _role(_db, _user_id, _project_id):
        return role

    monkeypatch.setattr(f"{MODULE}._project_member_role", _role)


def _patch_org_member(monkeypatch, *, is_member):
    async def _is_member(_db, _user_id, _org_id):
        return is_member

    monkeypatch.setattr(f"{MODULE}._is_org_member", _is_member)


# ── visibility helper ──────────────────────────────────────────


def test_effective_visibility_prefers_column():
    s = _skill(visibility="public")
    assert _effective_visibility(s) == "public"


def test_effective_visibility_uses_persisted_value():
    s = _skill(visibility="organization")
    assert _effective_visibility(s) == "organization"


@pytest.mark.parametrize("v", ["project", "organization", "public"])
def test_effective_visibility_passes_through(v):
    s = _skill(visibility=v)
    assert _effective_visibility(s) == v


# ── project role -> capability threshold ────────────────────────


async def test_viewer_read_allowed_write_admin_denied(monkeypatch):
    s = _skill()
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="viewer")

    await check_skill_access(
        _NullDB(),
        s,
        "bob",
        ProjectCapability.READ,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-A",
    )
    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.WRITE,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-A",
        )
    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.ADMIN,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-A",
        )


async def test_editor_read_and_write_allowed_admin_denied(monkeypatch):
    s = _skill()
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="editor")

    await check_skill_access(
        _NullDB(),
        s,
        "bob",
        ProjectCapability.READ,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-A",
    )
    await check_skill_access(
        _NullDB(),
        s,
        "bob",
        ProjectCapability.WRITE,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-A",
    )
    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.ADMIN,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-A",
        )


async def test_project_admin_gets_admin(monkeypatch):
    s = _skill()
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="admin")

    await check_skill_access(
        _NullDB(),
        s,
        "bob",
        ProjectCapability.ADMIN,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-A",
    )


@pytest.mark.parametrize("org_role", [JoySafeterRole.OWNER, JoySafeterRole.ADMIN])
async def test_org_superuser_gets_admin_without_project_row(monkeypatch, org_role):
    """Org owner/admin manage every skill in their org regardless of a
    ProjectMember row (effective_project_capability short-circuits to ADMIN)."""
    s = _skill()
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)

    await check_skill_access(
        _NullDB(),
        s,
        "boss",
        ProjectCapability.ADMIN,
        caller_org_role=org_role,
        active_org_id="org-A",
    )


# ── cross-org isolation ─────────────────────────────────────────


async def test_cross_org_org_visibility_read_denied(monkeypatch):
    """Caller pinned to org B cannot READ an org-A ``organization``
    skill even though they'd be a project admin — org isolation gates
    the capability path, and organization visibility never crosses orgs."""
    s = _skill(visibility="organization")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="admin")
    _patch_org_member(monkeypatch, is_member=True)

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.READ,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-B",
        )


async def test_cross_org_public_read_allowed(monkeypatch):
    """``public`` is the one carve-out: readable from any org."""
    s = _skill(visibility="public")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)

    await check_skill_access(
        _NullDB(),
        s,
        "stranger",
        ProjectCapability.READ,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-B",
    )


async def test_cross_org_project_capability_write_denied(monkeypatch):
    """A caller who is a project ADMIN of an org-A skill but pinned to
    org B must NOT WRITE it — the capability path is org-gated."""
    s = _skill(visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="admin")

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.WRITE,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-B",
        )


# ── org-member (non-project-member) read via visibility ─────────


async def test_org_member_reads_organization_skill(monkeypatch):
    """Org member who is NOT a project member gets READ on an
    ``organization`` skill inside their active org."""
    s = _skill(visibility="organization")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)  # not a project member
    _patch_org_member(monkeypatch, is_member=True)

    await check_skill_access(
        _NullDB(),
        s,
        "bob",
        ProjectCapability.READ,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-A",
    )


async def test_org_member_never_gets_write_via_visibility(monkeypatch):
    """Visibility grants READ only — never WRITE. An org member with no
    project row must be denied WRITE on an organization skill."""
    s = _skill(visibility="organization")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)
    _patch_org_member(monkeypatch, is_member=True)

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.WRITE,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-A",
        )


async def test_org_member_no_read_on_project_visibility(monkeypatch):
    """A ``project`` skill is NOT readable by a bare org member — they
    need a project row (capability path). Org visibility fallback does
    not apply to the ``project`` tier."""
    s = _skill(visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)  # not a project member
    _patch_org_member(monkeypatch, is_member=True)

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.READ,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-A",
        )


async def test_non_member_non_org_non_public_denied(monkeypatch):
    """No project row, not an org member, not public → denied at every tier."""
    s = _skill(visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)
    _patch_org_member(monkeypatch, is_member=False)

    with pytest.raises(AccessDeniedError) as ei:
        await check_skill_access(
            _NullDB(),
            s,
            "stranger",
            ProjectCapability.READ,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-A",
        )
    assert ei.value.code == "SKILL_ACCESS_DENIED"


async def test_owner_without_project_row_denied_write(monkeypatch):
    """Single-axis invariant: being the skill OWNER no longer grants
    capability. An owner with no project role and only MEMBER org role
    cannot WRITE."""
    s = _skill(owner_id="bob", visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)
    _patch_org_member(monkeypatch, is_member=True)

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.WRITE,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-A",
        )
