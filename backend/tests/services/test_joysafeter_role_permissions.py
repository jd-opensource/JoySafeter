import pytest
from fastapi import HTTPException

from app.joysafeter_api.api.v2.auth import (
    _ensure_can_assign_role,
    _ensure_can_modify_member,
    _normalize_assignable_role,
)
from app.joysafeter_api.api.v2.organizations import _validate_member_role
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole


def test_member_alias_normalizes_to_developer():
    assert JoySafeterRole.normalize("member") is JoySafeterRole.DEVELOPER
    assert _normalize_assignable_role("member") is JoySafeterRole.DEVELOPER
    assert _validate_member_role("member") == "developer"


def test_role_grants_cannot_exceed_actor_role():
    _ensure_can_assign_role(JoySafeterRole.ADMIN, JoySafeterRole.DEVELOPER)
    _ensure_can_assign_role(JoySafeterRole.DEVELOPER, JoySafeterRole.VIEWER)

    with pytest.raises(HTTPException):
        _ensure_can_assign_role(JoySafeterRole.DEVELOPER, JoySafeterRole.ADMIN)

    with pytest.raises(HTTPException):
        _ensure_can_assign_role(JoySafeterRole.ADMIN, JoySafeterRole.OWNER)


def test_member_updates_cannot_modify_or_grant_higher_roles():
    _ensure_can_modify_member(JoySafeterRole.ADMIN, "developer", JoySafeterRole.VIEWER)
    _ensure_can_modify_member(JoySafeterRole.OWNER, "admin", JoySafeterRole.DEVELOPER)

    with pytest.raises(HTTPException):
        _ensure_can_modify_member(JoySafeterRole.ADMIN, "owner", JoySafeterRole.DEVELOPER)

    with pytest.raises(HTTPException):
        _ensure_can_modify_member(JoySafeterRole.ADMIN, "developer", JoySafeterRole.OWNER)

    with pytest.raises(HTTPException):
        _ensure_can_modify_member(JoySafeterRole.DEVELOPER, "admin", JoySafeterRole.VIEWER)


def test_invalid_assignable_role_rejected():
    with pytest.raises(HTTPException):
        _normalize_assignable_role("owner")

    with pytest.raises(HTTPException):
        _normalize_assignable_role("invalid")
