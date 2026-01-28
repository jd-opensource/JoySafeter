"""Custom exceptions for skill loading operations.

This module defines exception classes for skill loading operations,
providing better error classification and handling.
"""


class SkillLoadError(Exception):
    """Base exception for skill loading operations.

    All skill-related exceptions inherit from this class,
    allowing callers to catch all skill loading errors with a single except clause.
    """

    pass


class SkillNotFoundError(SkillLoadError):
    """Raised when a skill is not found or access is denied.

    This exception is raised when:
    - The skill ID does not exist in the database
    - The user does not have permission to access the skill
    - The skill service returns None for a skill query
    """

    pass


class SkillPermissionDeniedError(SkillLoadError):
    """Raised when user lacks permission to access a skill.

    This exception is raised when:
    - User tries to access a private skill owned by another user
    - Permission check fails during skill retrieval
    """

    pass


class SkillFileWriteError(SkillLoadError):
    """Raised when writing skill files to sandbox fails.

    This exception is raised when:
    - File write operation fails
    - Backend write() method returns an error
    - File system errors occur during write
    """

    pass
