"""Agent spawn port — type-safe interface for coordinator sub-agent dispatch."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentSpawnPort(Protocol):
    """Port for spawning and querying sub-agent executions.

    Implemented by: services/agent_spawn_adapter.py
    Used by: core/agent/coordinator_tools.py
    """

    async def spawn_and_wait(
        self,
        *,
        agent_name: str,
        prompt: str,
        workspace_id: str,
        user_id: str,
        parent_execution_id: str,
        runtime_type: str,
        model: str | None,
        timeout: int,
    ) -> dict: ...

    async def spawn_fire_and_forget(
        self,
        *,
        agent_name: str,
        prompt: str,
        workspace_id: str,
        user_id: str,
        parent_execution_id: str,
        runtime_type: str,
        model: str | None,
    ) -> dict: ...

    async def get_result(self, execution_id: str, *, user_id: str) -> dict: ...
