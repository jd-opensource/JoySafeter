"""Sandbox port — type-safe interface for sandbox acquisition/release in core/."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SandboxPort(Protocol):
    """Port for acquiring and releasing code-execution sandboxes.

    Implemented by: services/sandbox_manager.py
    Used by: core/graph/deep_agents/builder.py
    """

    async def get_handle(self, user_id: str) -> Any: ...

    async def release_handle(self, handle: Any) -> None: ...
