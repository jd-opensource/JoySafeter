"""Shared sandbox path helpers.

Single source of truth for computing host-side sandbox directories.
"""

from pathlib import Path

from app.core.agent.backends.constants import DEFAULT_SANDBOX_HOST_ROOT
from app.utils.path_utils import sanitize_path_component


def get_user_sandbox_host_dir(user_id: str) -> Path:
    """Return the host-side sandbox root for a user: /tmp/sandboxes/{safe_uid}."""
    safe_uid = sanitize_path_component(user_id, default="default")
    return Path(DEFAULT_SANDBOX_HOST_ROOT) / safe_uid
