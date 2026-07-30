"""Unit tests for ``check_skill_access`` — single-axis project-capability gate.

Phase 2 of the skills redesign collapses the old owner + collaborator
ACL into ONE axis: the caller's effective capability on the skill's own
PROJECT (via ``effective_project_capability``), gated by org isolation.
READ can additionally come from the visibility tier (public crosses
orgs; organization only inside the active org).

Membership and org-id resolution are patched at the helper boundary so
these run without a real database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth.context import ProjectCapability
from app.joysafeter_shared.common.skill_permissions import (
    _effective_visibility,
    check_skill_access,
)

pytestmark = pytest.mark.no_db

MODULE = "app.joysafeter_shared.common.skill_permissions"


def _skill(*, owner_id="owner", visibility="project", project_id="proj-1"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id,
        visibility=visibility,
        project_id=project_id,
    )


class _NullDB:
    """The gate resolves org id + project role + org membership through
    helpers we patch, so the raw session must never be touched."""

    async def execute(self, _stmt):  # pragma: no cover — patch a helper
        raise AssertionError("DB not expected to be hit; patch a helper")


# ── visibility helper ──────────────────────────────────────────


def test_effective_visibility_prefers_column():
    s = _skill(visibility="public")
    assert _effective_visibility(s) == "public"


def test_effective_visibility_falls_back_to_project_when_null():
    """A null/empty visibility falls back to ``project`` (the least-
    permissive shareable floor) for the single-axis gate."""
    s = _skill(visibility="")
    assert _effective_visibility(s) == "project"


@pytest.mark.parametrize("v", ["project", "organization", "public"])
def test_effective_visibility_passes_through(v):
    s = _skill(visibility=v)
    assert _effective_visibility(s) == v


# ── helpers ────────────────────────────────────────────────────


def _patch_skill_org_id(monkeypatch, *, org_id):
    async def _resolve(_db, _skill):
        return org_id

    monkeypatch.setattr(f"{MODULE}.resolve_skill_org_id", _resolve)


def _patch_project_role(monkeypatch, *, role):
    async def _role(_db, _user_id, _project_id):
        return role

    monkeypatch.setattr(f"{MODULE}._project_member_role", _role)


def _patch_org_member(monkeypatch, *, is_member):
    async def _is_member(_db, _user_id, _org_id):
        return is_member

    monkeypatch.setattr(f"{MODULE}._is_org_member", _is_member)


# ── project role -> capability threshold ────────────────────────


async def test_viewer_read_only(monkeypatch):
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


async def test_editor_write(monkeypatch):
    s = _skill()
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="editor")

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


async def test_project_admin(monkeypatch):
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
async def test_org_superuser_admin(monkeypatch, org_role):
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


# ── org isolation ───────────────────────────────────────────────


async def test_capability_denied_cross_org(monkeypatch):
    s = _skill(visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role="admin")

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.READ,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id="org-B",
        )


async def test_public_read_crosses_org(monkeypatch):
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


# ── visibility read fallback ────────────────────────────────────


async def test_org_member_reads_organization_skill(monkeypatch):
    s = _skill(visibility="organization")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)
    _patch_org_member(monkeypatch, is_member=True)

    await check_skill_access(
        _NullDB(),
        s,
        "bob",
        ProjectCapability.READ,
        caller_org_role=JoySafeterRole.MEMBER,
        active_org_id="org-A",
    )


async def test_org_visibility_never_grants_write(monkeypatch):
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


async def test_project_visibility_needs_project_row(monkeypatch):
    """A ``project`` skill is not readable by a bare org member — the
    org-visibility fallback does not apply to the project tier."""
    s = _skill(visibility="project")
    _patch_skill_org_id(monkeypatch, org_id="org-A")
    _patch_project_role(monkeypatch, role=None)
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


async def test_project_skill_denies_stranger(monkeypatch):
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


async def test_org_skill_without_project_id_denies(monkeypatch):
    """An ``organization`` skill with no ``project_id`` has no org to
    bind against — deny rather than fall through."""
    s = _skill(visibility="organization", project_id=None)
    _patch_skill_org_id(monkeypatch, org_id=None)
    _patch_project_role(monkeypatch, role=None)
    _patch_org_member(monkeypatch, is_member=False)

    with pytest.raises(AccessDeniedError):
        await check_skill_access(
            _NullDB(),
            s,
            "bob",
            ProjectCapability.READ,
            caller_org_role=JoySafeterRole.MEMBER,
            active_org_id=None,
        )
