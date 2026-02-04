"""Default constants for sandbox backends.

This module defines default configuration values used across different
sandbox backend implementations to ensure consistency.
"""

# Command execution defaults
DEFAULT_COMMAND_TIMEOUT = 30  # seconds
DEFAULT_MAX_OUTPUT_SIZE = 100000  # characters

# Docker sandbox defaults
DEFAULT_DOCKER_IMAGE = "python:3.12-slim"
DEFAULT_WORKING_DIR = "/workspace"
DEFAULT_AUTO_REMOVE = True
DEFAULT_IDLE_TIMEOUT = 3600  # 1 hour in seconds

# File size defaults
DEFAULT_MAX_FILE_SIZE_MB = 10

__all__ = [
    # Command execution
    "DEFAULT_COMMAND_TIMEOUT",
    "DEFAULT_MAX_OUTPUT_SIZE",
    # Docker sandbox
    "DEFAULT_DOCKER_IMAGE",
    "DEFAULT_WORKING_DIR",
    "DEFAULT_AUTO_REMOVE",
    "DEFAULT_IDLE_TIMEOUT",
    # File size
    "DEFAULT_MAX_FILE_SIZE_MB",
]
