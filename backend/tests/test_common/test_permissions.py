"""Tests for common permissions checking."""

from app.common.permissions import _scope_satisfies, check_token_permission


def test_global_token_satisfies():
    assert check_token_permission(["skills:read"], "skills:read", "skill", "123", None, None) is True
    assert check_token_permission(["skills:admin"], "skills:execute", "skill", "123", None, None) is True


def test_scope_hierarchy():
    assert check_token_permission(["skills:execute"], "skills:read", "skill", "1", None, None) is True
    assert check_token_permission(["skills:read"], "skills:execute", "skill", "1", None, None) is False


def test_resource_binding():
    # Matches bound resource
    assert check_token_permission(["skills:execute"], "skills:execute", "skill", "1", "skill", "1") is True
    # Fails different resource ID
    assert check_token_permission(["skills:execute"], "skills:execute", "skill", "2", "skill", "1") is False
    # Fails different resource type binding
    assert check_token_permission(["graphs:execute"], "graphs:execute", "graph", "1", "skill", "1") is False


def test_scope_satisfies_same_scope():
    assert _scope_satisfies("skills:read", "skills:read") is True
    assert _scope_satisfies("graphs:execute", "graphs:execute") is True


def test_scope_satisfies_higher_covers_lower():
    """admin > publish > execute > write > read for skills."""
    assert _scope_satisfies("skills:admin", "skills:read") is True
    assert _scope_satisfies("skills:admin", "skills:publish") is True
    assert _scope_satisfies("skills:publish", "skills:execute") is True
    assert _scope_satisfies("skills:write", "skills:read") is True


def test_scope_satisfies_lower_does_not_cover_higher():
    assert _scope_satisfies("skills:read", "skills:write") is False
    assert _scope_satisfies("skills:execute", "skills:publish") is False
    assert _scope_satisfies("skills:publish", "skills:admin") is False


def test_scope_satisfies_cross_resource_fails():
    """skills:admin should NOT satisfy graphs:read."""
    assert _scope_satisfies("skills:admin", "graphs:read") is False
    assert _scope_satisfies("graphs:execute", "tools:execute") is False


def test_scope_satisfies_malformed_scope():
    assert _scope_satisfies("invalid", "skills:read") is False
    assert _scope_satisfies("skills:read", "invalid") is False
    assert _scope_satisfies("", "") is False


def test_empty_scopes_list():
    assert check_token_permission([], "skills:read", "skill", "1", None, None) is False


def test_multiple_scopes_any_match():
    """If any scope in the list satisfies, permission is granted."""
    assert check_token_permission(["tools:read", "skills:execute"], "skills:read", "skill", "1", None, None) is True


def test_graphs_hierarchy():
    assert _scope_satisfies("graphs:execute", "graphs:read") is True
    assert _scope_satisfies("graphs:read", "graphs:execute") is False


def test_tools_hierarchy():
    assert _scope_satisfies("tools:execute", "tools:read") is True
    assert _scope_satisfies("tools:read", "tools:execute") is False


def test_resource_binding_with_uuid_strings():
    """resource_id comparison uses str() so UUIDs and strings should match."""
    uid = "550e8400-e29b-41d4-a716-446655440000"
    assert check_token_permission(["skills:execute"], "skills:execute", "skill", uid, "skill", uid) is True
