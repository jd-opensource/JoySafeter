"""LangGraph tools for Coordinator agents to spawn and manage CLI agents.

These functions delegate to an AgentSpawnPort implementation (injected at
call time or via module-level default) so core/ never imports services/.
"""

from __future__ import annotations

from app.core.ports.agent_spawn import AgentSpawnPort

_default_spawn_port: AgentSpawnPort | None = None


def set_default_spawn_port(port: AgentSpawnPort) -> None:
    """Set the module-level default spawn port (called during app startup)."""
    global _default_spawn_port
    _default_spawn_port = port


def _get_port(port: AgentSpawnPort | None = None) -> AgentSpawnPort:
    resolved = port or _default_spawn_port
    if resolved is None:
        raise RuntimeError("AgentSpawnPort not configured — call set_default_spawn_port() at startup")
    return resolved


async def spawn_agent(
    agent_name: str,
    prompt: str,
    *,
    workspace_id: str,
    user_id: str,
    parent_execution_id: str,
    runtime_type: str = "claude_code",
    model: str | None = None,
    wait: bool = True,
    timeout: int = 3600,
    spawn_port: AgentSpawnPort | None = None,
) -> dict:
    port = _get_port(spawn_port)
    if wait:
        return await port.spawn_and_wait(
            agent_name=agent_name,
            prompt=prompt,
            workspace_id=workspace_id,
            user_id=user_id,
            parent_execution_id=parent_execution_id,
            runtime_type=runtime_type,
            model=model,
            timeout=timeout,
        )
    else:
        return await port.spawn_fire_and_forget(
            agent_name=agent_name,
            prompt=prompt,
            workspace_id=workspace_id,
            user_id=user_id,
            parent_execution_id=parent_execution_id,
            runtime_type=runtime_type,
            model=model,
        )


async def get_agent_result(
    execution_id: str,
    *,
    user_id: str,
    spawn_port: AgentSpawnPort | None = None,
) -> dict:
    port = _get_port(spawn_port)
    return await port.get_result(execution_id, user_id=user_id)
