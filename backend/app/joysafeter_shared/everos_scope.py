"""Helpers for JoySafeter-owned EverOS scope identifiers."""

from __future__ import annotations

import re
from typing import Any

EVEROS_PROJECT_ID_SEPARATOR = "__"
EVEROS_PROJECT_ID_MAX_LENGTH = 128
EVEROS_SESSION_USER_ID_METADATA_KEY = "joysafeter_user_id"
EVEROS_SESSION_USER_NAME_METADATA_KEY = "joysafeter_user_name"
EVEROS_SESSION_USER_EMAIL_METADATA_KEY = "joysafeter_user_email"

_EVEROS_ID_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.@+-]+")
_EVEROS_ID_UNDERSCORE_RE = re.compile(r"_+")


def everos_path_safe_id(value: Any, fallback: str) -> str:
    """Return an id safe for EverOS request fields that become path segments."""
    raw = str(value or "").strip()
    safe = _EVEROS_ID_SAFE_RE.sub("_", raw)
    safe = _EVEROS_ID_UNDERSCORE_RE.sub("_", safe).strip("._")
    if not safe or safe in {".", ".."}:
        safe = fallback
    return safe[:EVEROS_PROJECT_ID_MAX_LENGTH]


def compose_everos_project_id(*, project_slug: Any, project_id: Any) -> str:
    """Build the EverOS project scope as ``<project_slug>__<project_id>``."""
    stable_id = everos_path_safe_id(project_id, "default")
    max_slug_length = (
        EVEROS_PROJECT_ID_MAX_LENGTH
        - len(EVEROS_PROJECT_ID_SEPARATOR)
        - len(stable_id)
    )
    if max_slug_length < 1:
        return stable_id[:EVEROS_PROJECT_ID_MAX_LENGTH]

    slug = everos_path_safe_id(project_slug, "project")[:max_slug_length]
    slug = slug.strip("._") or "project"
    return f"{slug}{EVEROS_PROJECT_ID_SEPARATOR}{stable_id}"


def compose_everos_user_id(
    *,
    user_name: Any = None,
    user_id: Any = None,
    fallback: str = "default_user",
) -> str:
    """Build the EverOS user-memory owner id from JoySafeter user identity.

    Prefer the human-readable JoySafeter display name because EverOS stores this
    value as a directory segment. Fall back to the stable JoySafeter user id when
    a display name is unavailable.
    """
    return everos_path_safe_id(user_name or user_id, fallback)


def build_everos_session_user_metadata(
    *,
    user_id: Any = None,
    user_name: Any = None,
    user_email: Any = None,
) -> dict[str, str]:
    """Return JoySafeter user metadata persisted on newly-created sessions."""
    metadata: dict[str, str] = {}
    if user_id:
        metadata[EVEROS_SESSION_USER_ID_METADATA_KEY] = str(user_id)
    if user_name:
        metadata[EVEROS_SESSION_USER_NAME_METADATA_KEY] = str(user_name)
    if user_email:
        metadata[EVEROS_SESSION_USER_EMAIL_METADATA_KEY] = str(user_email)
    return metadata


def extract_joysafeter_project_id(everos_project_id: str | None) -> str | None:
    """Recover the JoySafeter DB project id from an EverOS project scope."""
    if everos_project_id is None:
        return None
    project_id = str(everos_project_id)
    if EVEROS_PROJECT_ID_SEPARATOR not in project_id:
        return project_id
    return project_id.rsplit(EVEROS_PROJECT_ID_SEPARATOR, 1)[1] or project_id
