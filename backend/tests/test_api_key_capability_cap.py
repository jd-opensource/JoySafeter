"""API-key creation must cap the key's project capability at the creator's.

The stored api-key role is later reinterpreted as a *project* capability
(dependencies._auth_via_api_key), so the creation-time check must compare
against the creator's effective_project_capability, not their org-role rank.
"""

import pytest

from app.joysafeter_api.api.v1.auth import _ensure_key_capability_within_creator
from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole


def _assert_forbidden(creator_role, creator_project_role, requested_role):
    with pytest.raises(AccessDeniedError) as exc_info:
        _ensure_key_capability_within_creator(creator_role, creator_project_role, requested_role)
    assert exc_info.value.code == "AUTH_API_KEY_CAPABILITY_EXCEEDED"


def test_project_editor_can_mint_write_key():
    # org-developer + project editor => WRITE; a "developer"(WRITE) key is allowed.
    _ensure_key_capability_within_creator(
        JoySafeterRole.DEVELOPER, "editor", JoySafeterRole.DEVELOPER
    )


def test_project_editor_cannot_mint_admin_key():
    # WRITE creator must not mint an ADMIN-capability key.
    _assert_forbidden(JoySafeterRole.DEVELOPER, "editor", JoySafeterRole.ADMIN)


def test_org_superuser_can_mint_admin_key_without_project_row():
    # Org admin is a super-user (ADMIN everywhere) even with no ProjectMember row.
    _ensure_key_capability_within_creator(JoySafeterRole.ADMIN, None, JoySafeterRole.ADMIN)


def test_project_admin_with_low_org_role_can_mint_admin_key():
    # Regression: project-admin who is only an org-developer must be able to mint
    # an admin key. The old org-rank check wrongly blocked this.
    _ensure_key_capability_within_creator(JoySafeterRole.DEVELOPER, "admin", JoySafeterRole.ADMIN)


def test_org_viewer_project_editor_can_mint_write_key():
    # Regression: org-viewer who is a project editor has WRITE and must be able to
    # mint a WRITE key. The old org-rank check wrongly blocked this (viewer<developer).
    _ensure_key_capability_within_creator(
        JoySafeterRole.VIEWER, "editor", JoySafeterRole.DEVELOPER
    )


def test_project_viewer_cannot_mint_write_key():
    # READ creator must not mint a WRITE key.
    _assert_forbidden(JoySafeterRole.DEVELOPER, "viewer", JoySafeterRole.DEVELOPER)
