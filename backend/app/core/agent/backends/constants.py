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

# Sandbox host directory
DEFAULT_SANDBOX_HOST_ROOT = "/tmp/sandboxes"
SANDBOX_UPLOADS_SUBDIR = "uploads"

# User sandbox defaults
DEFAULT_USER_SANDBOX_IMAGE = "python:3.12-slim"
DEFAULT_USER_SANDBOX_IDLE_TIMEOUT = 3600  # 1 hour in seconds
DEFAULT_USER_SANDBOX_CPU_LIMIT = 1.0  # 1 core
DEFAULT_USER_SANDBOX_MEMORY_LIMIT = 512  # 512MB
# Stop/restart keep container; only rebuild removes it
DEFAULT_USER_SANDBOX_AUTO_REMOVE = False
MAX_SANDBOX_POOL_SIZE = 100


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
    # User sandbox
    "DEFAULT_USER_SANDBOX_IMAGE",
    "DEFAULT_USER_SANDBOX_IDLE_TIMEOUT",
    "DEFAULT_USER_SANDBOX_CPU_LIMIT",
    "DEFAULT_USER_SANDBOX_MEMORY_LIMIT",
    "DEFAULT_USER_SANDBOX_AUTO_REMOVE",
    "MAX_SANDBOX_POOL_SIZE",
    # Sandbox host directory
    "DEFAULT_SANDBOX_HOST_ROOT",
    "SANDBOX_UPLOADS_SUBDIR",
]
