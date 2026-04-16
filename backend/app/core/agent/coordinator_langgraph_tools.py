"""LangChain tool wrappers for coordinator functions."""
from __future__ import annotations

from langchain_core.tools import tool


def make_coordinator_tools(
    workspace_id: str,
    user_id: str,
    parent_execution_id: str,
):
    """Create LangChain tools bound to a specific coordinator context.

    Returns a list of tools that can be added to any LangGraph agent's tool list.
    """

    @tool
    async def spawn_cli_agent(
        agent_name: str,
        prompt: str,
        runtime_type: str = "claude_code",
        wait: bool = True,
    ) -> str:
        """Spawn a CLI agent to execute a sub-task.

        Use this to delegate work to specialized agents:
        - claude_code: Best for writing code, scripts, and analysis
        - codex: Best for code review and refactoring
        - openclaw: Best for penetration testing and security scanning

        Args:
            agent_name: A descriptive name for the agent
            prompt: Detailed task description
            runtime_type: "claude_code", "codex", or "openclaw"
            wait: If True, wait for the agent to finish and return its output
        """
        from app.core.agent.coordinator_tools import spawn_agent

        result = await spawn_agent(
            agent_name=agent_name,
            prompt=prompt,
            workspace_id=workspace_id,
            user_id=user_id,
            parent_execution_id=parent_execution_id,
            runtime_type=runtime_type,
            wait=wait,
        )

        if result["status"] == "completed":
            return f"Agent '{agent_name}' completed:\n{result['output']}"
        elif result["status"] == "dispatched":
            return (
                f"Agent '{agent_name}' dispatched "
                f"(execution_id: {result['execution_id']}). "
                f"Use check_agent_result to check later."
            )
        else:
            return f"Agent '{agent_name}' {result['status']}: {result['output']}"

    @tool
    async def check_agent_result(execution_id: str) -> str:
        """Check the result of a previously spawned agent.

        Args:
            execution_id: The execution ID from spawn_cli_agent
        """
        from app.core.agent.coordinator_tools import get_agent_result

        result = await get_agent_result(execution_id, user_id=user_id)
        return f"Status: {result['status']}\nOutput: {result['output']}"

    return [spawn_cli_agent, check_agent_result]
