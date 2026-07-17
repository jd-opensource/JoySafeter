import pytest

from app.joysafeter_shared.common.joysafeter_auth.context import (
    JoySafeterRole,
    ProjectCapability,
    ProjectRole,
    effective_project_capability,
)

pytestmark = pytest.mark.no_db


def test_org_owner_and_admin_are_admin_everywhere():
    # Super-users reach every project at admin capability, even without a row.
    assert effective_project_capability(JoySafeterRole.OWNER, None) is ProjectCapability.ADMIN
    assert effective_project_capability(JoySafeterRole.ADMIN, None) is ProjectCapability.ADMIN
    # ...and a project row never downgrades a super-user.
    assert effective_project_capability(JoySafeterRole.ADMIN, "viewer") is ProjectCapability.ADMIN


def test_non_superuser_without_row_has_no_capability():
    assert effective_project_capability(JoySafeterRole.DEVELOPER, None) is ProjectCapability.NONE
    assert effective_project_capability(JoySafeterRole.VIEWER, None) is ProjectCapability.NONE


def test_non_superuser_capability_comes_solely_from_project_role():
    assert effective_project_capability(JoySafeterRole.DEVELOPER, "admin") is ProjectCapability.ADMIN
    assert effective_project_capability(JoySafeterRole.DEVELOPER, "editor") is ProjectCapability.WRITE
    assert effective_project_capability(JoySafeterRole.DEVELOPER, "viewer") is ProjectCapability.READ


def test_org_viewer_with_project_admin_role_is_admin():
    # The core GitHub-model rule: a non-super-user's capability is ONLY their
    # project role, independent of their org role. No intersection.
    assert effective_project_capability(JoySafeterRole.VIEWER, "admin") is ProjectCapability.ADMIN


def test_capability_is_ordered_for_threshold_checks():
    assert ProjectCapability.NONE < ProjectCapability.READ < ProjectCapability.WRITE < ProjectCapability.ADMIN
    assert ProjectCapability.ADMIN >= ProjectCapability.WRITE
    assert not (ProjectCapability.READ >= ProjectCapability.WRITE)


def test_project_role_normalizes_legacy_values():
    assert ProjectRole.normalize("owner") is ProjectRole.ADMIN
    assert ProjectRole.normalize("developer") is ProjectRole.EDITOR
    assert ProjectRole.normalize("member") is ProjectRole.EDITOR
    assert ProjectRole.normalize("viewer") is ProjectRole.VIEWER
    assert ProjectRole.normalize("editor") is ProjectRole.EDITOR
    assert ProjectRole.normalize(None) is None
    assert ProjectRole.normalize("") is None
