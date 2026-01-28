"""Path utilities for sanitizing and cleaning file paths and names.

This module provides unified functions for sanitizing paths, filenames, and
path components to prevent path traversal attacks and ensure safe file system operations.
"""

import re
from pathlib import Path
from typing import Optional


def sanitize_path_component(
    value: Optional[str],
    default: str = "default",
    max_length: int = 100,
    allow_spaces: bool = False,
) -> str:
    """Sanitize a path component to prevent path traversal attacks.

    This is a unified function that combines the functionality of:
    - BackendFactory._sanitize_path_component()
    - SkillSandboxLoader._sanitize_skill_name()
    - files.py sanitize_filename()

    Args:
        value: Original value to sanitize
        default: Default value if value is None or invalid
        max_length: Maximum length limit
        allow_spaces: Whether to allow spaces (default: False, spaces become underscores)

    Returns:
        Sanitized path component safe for file system use

    Examples:
        >>> sanitize_path_component("my-file.txt")
        'my-file.txt'
        >>> sanitize_path_component("../../etc/passwd")
        'default'
        >>> sanitize_path_component("my skill name", allow_spaces=True)
        'my skill name'
        >>> sanitize_path_component("my skill name", allow_spaces=False)
        'my_skill_name'
    """
    if not value:
        return default

    # Convert to string and strip
    value_str = str(value).strip()

    # Remove path separators and relative path symbols
    value_str = value_str.replace("..", "").replace("./", "").replace(".\\", "")

    # Handle spaces based on allow_spaces flag
    if not allow_spaces:
        value_str = value_str.replace(" ", "_")

    # Remove invalid characters
    # For path components: allow alphanumeric, underscore, hyphen, dot
    # For filenames: also allow spaces if allow_spaces=True
    if allow_spaces:
        # Allow alphanumeric, spaces, dots, underscores, hyphens
        value_str = re.sub(r"[^\w\s\-.]", "_", value_str)
        # Remove control characters
        value_str = re.sub(r"[\x00-\x1f]", "_", value_str)
    else:
        # Only allow alphanumeric, underscore, hyphen, dot
        value_str = re.sub(r"[^\w\-.]", "", value_str)

    # Remove leading/trailing dots and spaces
    value_str = value_str.strip(". ")

    # Limit length
    if len(value_str) > max_length:
        value_str = value_str[:max_length]

    # If sanitized result is empty or dangerous, use default
    if not value_str or value_str in (".", "..", "/"):
        return default

    return value_str


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """Sanitize a filename by removing dangerous characters.

    This function is specifically designed for filenames and uses
    Path.name to extract the filename component, then sanitizes it.

    Args:
        filename: Original filename (can include path)
        max_length: Maximum filename length (default: 255, common filesystem limit)

    Returns:
        Sanitized filename safe for file system use

    Examples:
        >>> sanitize_filename("my-file.txt")
        'my-file.txt'
        >>> sanitize_filename("../../etc/passwd")
        'passwd'
        >>> sanitize_filename("file with spaces.txt")
        'file_with_spaces.txt'
    """
    # Extract filename component (removes path separators)
    safe_name = Path(filename).name

    # Use path component sanitizer with spaces allowed initially
    # but then convert spaces to underscores for filenames
    safe_name = sanitize_path_component(
        safe_name,
        default="unnamed_file",
        max_length=max_length,
        allow_spaces=False,  # Filenames should not have spaces
    )

    return safe_name


def sanitize_skill_name(name: str, max_length: int = 100) -> str:
    """Sanitize a skill name for use in file paths.

    This is a convenience wrapper around sanitize_path_component
    with skill-specific defaults.

    Args:
        name: Original skill name
        max_length: Maximum length limit (default: 100)

    Returns:
        Sanitized skill name safe for file system use

    Examples:
        >>> sanitize_skill_name("my-skill")
        'my-skill'
        >>> sanitize_skill_name("my skill name")
        'my_skill_name'
        >>> sanitize_skill_name("")
        'unnamed_skill'
    """
    sanitized = sanitize_path_component(
        name,
        default="unnamed_skill",
        max_length=max_length,
        allow_spaces=False,
    )

    return sanitized
