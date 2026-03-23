"""Unified permission check with hierarchical scope matching."""

from typing import List, Optional

SCOPE_HIERARCHY = {
    "skills": ["admin", "publish", "execute", "write", "read"],
    "graphs": ["execute", "read"],
    "tools": ["execute", "read"],
}

VALID_SCOPES = [f"{resource}:{action}" for resource, actions in SCOPE_HIERARCHY.items() for action in actions]


def _scope_satisfies(token_scope: str, required_scope: str) -> bool:
    """Check if token_scope satisfies required_scope via hierarchy."""
    if not token_scope or not required_scope:
        return False
    if token_scope == required_scope:
        return True

    # Parse resource:action
    try:
        token_resource, token_action = token_scope.split(":")
        required_resource, required_action = required_scope.split(":")
    except ValueError:
        return False

    if token_resource != required_resource:
        return False

    hierarchy = SCOPE_HIERARCHY.get(token_resource, [])
    try:
        token_level = hierarchy.index(token_action)
        required_level = hierarchy.index(required_action)
        return token_level <= required_level  # Lower index = higher permission
    except ValueError:
        return False


def check_token_permission(
    token_scopes: List[str],
    required_scope: str,
    resource_type: str,
    resource_id: str,
    token_resource_type: Optional[str],
    token_resource_id: Optional[str],
) -> bool:
    """Unified permission check with hierarchical scope matching."""
    # 1. Check scope presence (with hierarchy)
    has_scope = any(_scope_satisfies(ts, required_scope) for ts in token_scopes)
    if not has_scope:
        return False

    # 2. Check resource binding
    if token_resource_type is None:
        # Global token, pass
        return True

    if token_resource_type == resource_type and str(token_resource_id) == str(resource_id):
        # Bound to target resource, pass
        return True

    return False
