"""Sandbox backend implementations for agent execution environments.

This module provides various backend implementations for sandbox environments:
- FilesystemSandboxBackend: Local filesystem-based backend
- StateSandboxBackend: In-memory state-based backend
- PydanticSandboxAdapter: Docker-based sandbox via pydantic-ai-backend

All backends implement the SandboxBackendProtocol interface.
"""

from app.core.agent.backends.filesystem_sandbox import FilesystemSandboxBackend
from app.core.agent.backends.state_sandbox import StateSandboxBackend

try:
    from app.core.agent.backends.pydantic_adapter import (
        BUILTIN_RUNTIMES,
        PydanticSandboxAdapter,
        RuntimeConfig,
        get_builtin_runtime,
        list_builtin_runtimes,
    )
except ImportError:
    PydanticSandboxAdapter = None  # type: ignore
    RuntimeConfig = None  # type: ignore
    BUILTIN_RUNTIMES = {}  # type: ignore
    get_builtin_runtime = None  # type: ignore
    list_builtin_runtimes = None  # type: ignore

__all__ = [
    # Backend classes
    "StateSandboxBackend",
    "FilesystemSandboxBackend",
    "PydanticSandboxAdapter",
    # Runtime configuration
    "RuntimeConfig",
    "BUILTIN_RUNTIMES",
    "get_builtin_runtime",
    "list_builtin_runtimes",
]
