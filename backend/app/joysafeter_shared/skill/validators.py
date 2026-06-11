"""Skill metadata validators per Agent Skills specification.

This module provides validation functions for skill metadata according to
the Agent Skills specification (https://agentskills.io/specification).
"""

import re
from typing import Optional, Tuple

# Agent Skills specification constraints
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500


def validate_skill_name(name: str, directory_name: Optional[str] = None) -> Tuple[bool, str]:
    """Validate skill name per Agent Skills specification.

    Requirements per spec:
    - Max 64 characters
    - Lowercase alphanumeric and hyphens only (a-z, 0-9, -)
    - Cannot start or end with hyphen
    - No consecutive hyphens
    - Must match parent directory name (if provided)

    Args:
        name: Skill name from YAML frontmatter or API
        directory_name: Optional parent directory name for matching validation

    Returns:
        (is_valid, error_message) tuple. Error message is empty if valid.
    """
    if not name:
        return False, "name is required"

    if len(name) > MAX_SKILL_NAME_LENGTH:
        return False, f"name exceeds {MAX_SKILL_NAME_LENGTH} characters (got: {name!r})"

    # Pattern: lowercase alphanumeric, single hyphens between segments, no start/end hyphen
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
        return False, f"name must be lowercase alphanumeric with single hyphens only (got: {name!r})"

    if directory_name and name != directory_name:
        return False, f"name '{name}' must match directory name '{directory_name}'"

    return True, ""


def validate_skill_description(description: str) -> Tuple[bool, str]:
    """Validate skill description length per Agent Skills specification.

    Requirements per spec:
    - Max 1024 characters

    Args:
        description: Skill description

    Returns:
        (is_valid, error_message) tuple. Error message is empty if valid.
    """
    if not description:
        return False, "description is required"

    if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
        return False, f"description exceeds {MAX_SKILL_DESCRIPTION_LENGTH} characters"

    return True, ""


def validate_compatibility(compatibility: Optional[str]) -> Tuple[bool, str]:
    """Validate compatibility field length per Agent Skills specification.

    Requirements per spec:
    - Max 500 characters (if provided)

    Args:
        compatibility: Compatibility string (optional)

    Returns:
        (is_valid, error_message) tuple. Error message is empty if valid.
    """
    if compatibility is None:
        return True, ""  # Optional field

    if len(compatibility) > MAX_COMPATIBILITY_LENGTH:
        return False, f"compatibility exceeds {MAX_COMPATIBILITY_LENGTH} characters"

    return True, ""


def truncate_description(description: str) -> str:
    """Truncate description to max length if needed.

    Args:
        description: Skill description

    Returns:
        Truncated description (if needed) or original description
    """
    if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
        return description[:MAX_SKILL_DESCRIPTION_LENGTH]
    return description


def truncate_compatibility(compatibility: Optional[str]) -> Optional[str]:
    """Truncate compatibility to max length if needed.

    Args:
        compatibility: Compatibility string (optional)

    Returns:
        Truncated compatibility (if needed) or original compatibility
    """
    if compatibility is None:
        return None

    if len(compatibility) > MAX_COMPATIBILITY_LENGTH:
        return compatibility[:MAX_COMPATIBILITY_LENGTH]
    return compatibility
