"""
JoySafeter auth — context and dependency helpers for org/project-scoped auth.
"""

from .context import JoySafeterAuthContext, JoySafeterRole

_DEPENDENCY_EXPORTS = {
    "get_joysafeter_auth_context",
    "require_joysafeter_admin",
    "require_joysafeter_read",
    "require_joysafeter_user_admin",
    "require_joysafeter_user_context",
    "require_joysafeter_user_write",
    "require_joysafeter_write",
}

__all__ = [
    "JoySafeterAuthContext",
    "JoySafeterRole",
    "get_joysafeter_auth_context",
    "require_joysafeter_admin",
    "require_joysafeter_read",
    "require_joysafeter_user_admin",
    "require_joysafeter_user_context",
    "require_joysafeter_user_write",
    "require_joysafeter_write",
]


def __getattr__(name: str):
    if name in _DEPENDENCY_EXPORTS:
        from . import dependencies

        return getattr(dependencies, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
