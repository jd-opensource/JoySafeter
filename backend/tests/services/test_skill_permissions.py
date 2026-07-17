"""Unit tests for ``check_skill_access`` four-tier visibility.

The check has two independent concerns:

  1. Per-skill ACL — owner, collaborator role
  2. Visibility tier — public, organization, project (collapsed to org
     for P1), private

We cover both. Org membership is patched at the helper boundary
(``_is_org_member``) so the tests don't need a real ``Member`` table.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.models.joysafeter_skill import JoySafeterCollaboratorRole as CollaboratorRole
from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.skill_permissions import (
    _effective_visibility,
    check_skill_access,
)


def _skill(*, owner_id="owner", visibility="private", is_public=False, project_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id,
        visibility=visibility,
        is_public=is_public,
        project_id=project_id,
    )


class _NullDB:
    """``check_skill_access`` only calls ``execute`` for the collaborator
    lookup and the org-id resolution. We bypass those via the helpers
    patched below, so the DB sees no calls in these tests."""

    async def execute(self, _stmt):  # pragma: no cover — should be patched out
        raise AssertionError("DB not expected to be hit; patch a helper")


# ── visibility helper ──────────────────────────────────────────


def test_effective_visibility_prefers_new_column():
    s = _skill(visibility="public", is_public=False)
    assert _effective_visibility(s) == "public"


def test_effective_visibility_falls_back_to_is_public():
    """Pre-P1 rows may have ``visibility=''`` + ``is_public=true``."""
    s = _skill(visibility="", is_public=True)
    assert _effective_visibility(s) == "public"


def test_effective_visibility_defaults_to_private():
    s = _skill(visibility=None, is_public=False)
    assert _effective_visibility(s) == "private"


@pytest.mark.parametrize("v", ["private", "project", "organization", "public"])
def test_effective_visibility_passes_through(v):
    s = _skill(visibility=v)
    assert _effective_visibility(s) == v


# ── per-skill ACL: owner + collaborator ────────────────────────


async def test_owner_passes_without_db_hit(monkeypatch):
    """Owner check is the cheap first gate; it short-circuits before
    any collaborator or visibility lookup runs."""
    s = _skill(owner_id="alice")
    await check_skill_access(_NullDB(), s, "alice", CollaboratorRole.ADMIN)


async def test_superuser_always_passes():
    s = _skill(owner_id="someone-else", visibility="private")
    await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.ADMIN, is_superuser=True)


async def test_collaborator_with_required_role_passes(monkeypatch):
    s = _skill(owner_id="alice", visibility="private")

    async def _grant(_db, _skill_id, user_id):
        if user_id == "bob":
            return SimpleNamespace(role=CollaboratorRole.EDITOR)
        return None

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._get_collaborator",
        _grant,
    )
    # editor is enough for a viewer check
    await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)
    # editor is enough for an editor check
    await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.EDITOR)


async def test_collaborator_below_required_role_denied(monkeypatch):
    s = _skill(owner_id="alice", visibility="private")

    async def _grant(_db, _skill_id, user_id):
        return SimpleNamespace(role=CollaboratorRole.VIEWER)

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._get_collaborator",
        _grant,
    )
    with pytest.raises(AccessDeniedError) as ei:
        await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.EDITOR)
    assert ei.value.code == "SKILL_ACCESS_DENIED"


# ── visibility tier ────────────────────────────────────────────


async def test_public_skill_allows_viewer(monkeypatch):
    s = _skill(owner_id="alice", visibility="public")
    _patch_no_collaborator(monkeypatch)
    await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


async def test_public_skill_denies_higher_role(monkeypatch):
    """Visibility opens the viewer door only — editor/admin still need
    ownership or a collaborator entry."""
    s = _skill(owner_id="alice", visibility="public")
    _patch_no_collaborator(monkeypatch)
    with pytest.raises(AccessDeniedError):
        await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.EDITOR)


async def test_organization_skill_allows_org_member(monkeypatch):
    s = _skill(owner_id="alice", visibility="organization", project_id="proj-1")
    _patch_no_collaborator(monkeypatch)
    _patch_org_member(monkeypatch, org_id="org-A", is_member=True)
    await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


async def test_organization_skill_denies_non_member(monkeypatch):
    s = _skill(owner_id="alice", visibility="organization", project_id="proj-1")
    _patch_no_collaborator(monkeypatch)
    _patch_org_member(monkeypatch, org_id="org-A", is_member=False)
    with pytest.raises(AccessDeniedError):
        await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


async def test_project_skill_requires_project_membership(monkeypatch):
    """P2.8 — ``project`` and ``organization`` are no longer collapsed.
    A user who is in the same org but NOT in the project must be denied
    a ``project``-visibility skill."""
    s = _skill(owner_id="alice", visibility="project", project_id="proj-1")
    _patch_no_collaborator(monkeypatch)
    # Bob is in the org but NOT in proj-1
    _patch_org_member(monkeypatch, org_id="org-A", is_member=True)
    _patch_project_member(monkeypatch, project_id="proj-1", is_member=False)
    with pytest.raises(AccessDeniedError):
        await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


async def test_project_skill_allows_project_member(monkeypatch):
    """The same Bob from above, after being granted project_members.
    P2.8 — direct project membership unlocks ``project``-visibility skills."""
    s = _skill(owner_id="alice", visibility="project", project_id="proj-1")
    _patch_no_collaborator(monkeypatch)
    _patch_project_member(monkeypatch, project_id="proj-1", is_member=True)
    await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


async def test_org_skill_ignores_project_membership(monkeypatch):
    """``organization`` doesn't care about project membership — being
    in the org is enough."""
    s = _skill(owner_id="alice", visibility="organization", project_id="proj-1")
    _patch_no_collaborator(monkeypatch)
    _patch_org_member(monkeypatch, org_id="org-A", is_member=True)
    # No project membership at all
    _patch_project_member(monkeypatch, project_id="proj-1", is_member=False)
    await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


async def test_project_skill_ignores_org_membership(monkeypatch):
    """Mirror of the above — ``project`` doesn't fall back to org. A
    user who's in the org but explicitly not in the project is denied,
    even when org membership is granted."""
    s = _skill(owner_id="alice", visibility="project", project_id="proj-1")
    _patch_no_collaborator(monkeypatch)
    _patch_org_member(monkeypatch, org_id="org-A", is_member=True)
    _patch_project_member(monkeypatch, project_id="proj-1", is_member=False)
    with pytest.raises(AccessDeniedError):
        await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


async def test_private_skill_denies_stranger(monkeypatch):
    s = _skill(owner_id="alice", visibility="private")
    _patch_no_collaborator(monkeypatch)
    with pytest.raises(AccessDeniedError):
        await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


async def test_org_skill_without_project_id_denies(monkeypatch):
    """An ``organization`` skill with no ``project_id`` has no org to
    bind against — the org-id resolver returns ``None``, and the check
    must deny rather than fall through to the wrong tier."""
    s = _skill(owner_id="alice", visibility="organization", project_id=None)
    _patch_no_collaborator(monkeypatch)
    _patch_org_member(monkeypatch, org_id=None, is_member=False)
    with pytest.raises(AccessDeniedError):
        await check_skill_access(_NullDB(), s, "bob", CollaboratorRole.VIEWER)


# ── helpers ────────────────────────────────────────────────────


def _patch_no_collaborator(monkeypatch):
    async def _none(*_args, **_kw):
        return None
    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._get_collaborator",
        _none,
    )


def _patch_org_member(monkeypatch, *, org_id, is_member):
    async def _resolve(_db, _skill):
        return org_id

    async def _is_member(_db, _user_id, _org_id):
        return is_member

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._skill_org_id",
        _resolve,
    )
    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._is_org_member",
        _is_member,
    )


def _patch_project_member(monkeypatch, *, project_id, is_member):
    """Stub the project-membership lookup. P2.8 — ``check_skill_access``
    consults this for ``visibility=project`` skills, independent of
    org membership."""

    async def _is_member(_db, _user_id, _project_id):
        return is_member and _project_id == project_id

    monkeypatch.setattr(
        "app.joysafeter_shared.common.skill_permissions._is_project_member",
        _is_member,
    )
