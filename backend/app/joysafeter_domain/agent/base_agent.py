"""
Base Agent factory — reusable LangChain agent construction.

Provides get_agent() for building agents with standard middleware
(filesystem, skills, summarization, etc.). Callers must supply a
pre-created model instance (via ModelResolver / ModelFactory).
"""

from typing import Any, cast

from deepagents.middleware import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain_core.runnables import Runnable, RunnableConfig
from loguru import logger

from app.joysafeter_domain.agent.backends.filesystem_sandbox import FilesystemSandboxBackend
from app.joysafeter_domain.agent.middleware import LoggingMiddleware


async def get_agent(
    *,
    model: Any,
    checkpointer: Any | None = None,
    user_id: str | None = None,
    system_prompt: str | None = None,
    tools: list[Any] | None = None,
    enable_todo_list: bool = True,
    enable_skills: bool = True,
    agent_name: str | None = None,
    node_middleware: list[Any] | None = None,
) -> Runnable:
    """
    Create and return the Agent graph.

    Args:
        model: Pre-created LangChain model instance (required).
        checkpointer: Optional checkpointer for state persistence.
        user_id: User ID (UUID), used to create an isolated sandbox directory.
        system_prompt: System prompt for the agent.
        tools: List of tools for the agent.
        enable_todo_list: Whether to enable TodoListMiddleware.
                         Set to False for DeepAgents subagents to avoid state conflicts.
        enable_skills: Whether to enable SkillMiddleware for progressive skill disclosure.
        agent_name: Name of the agent (for tagging).
        node_middleware: List of middleware instances from node configuration.

    Returns:
        Runnable: The compiled Agent graph.
    """
    from app.joysafeter_shared.tools.tool import EnhancedTool, ToolMetadata
    from app.joysafeter_shared.tools.tool_registry import get_global_registry

    if tools is None:
        tools = []
    else:
        if isinstance(tools, ToolMetadata):
            logger.error(f"[get_agent] tools parameter is a ToolMetadata object, not a list! metadata: {tools}")
            tools = []
        elif not isinstance(tools, (list, tuple)):
            logger.warning(f"[get_agent] tools is not a list/tuple, type: {type(tools)}, converting to list")
            try:
                tools = list(tools) if hasattr(tools, "__iter__") else [tools]
            except Exception as e:
                logger.error(f"[get_agent] Failed to convert tools to list: {e}")
                tools = []

        registry = get_global_registry()
        resolved_tools = []
        for tool in tools:
            if isinstance(tool, ToolMetadata):
                continue

            if isinstance(tool, EnhancedTool):
                resolved_tools.append(tool)
                continue

            if isinstance(tool, str):
                registry_tool = registry.get_tool(tool)
                if registry_tool:
                    resolved_tools.append(registry_tool)
                    continue

                if "::" in tool:
                    from app.joysafeter_shared.tools.mcp_tool_utils import parse_mcp_tool_name

                    server_name, tool_name = parse_mcp_tool_name(tool)
                    if server_name and tool_name:
                        mcp_tool = registry.get_mcp_tool(server_name, tool_name)
                        if mcp_tool:
                            resolved_tools.append(mcp_tool)
                            continue

                logger.warning(f"[get_agent] Unable to resolve tool '{tool}', skipping")
                continue

            resolved_tools.append(tool)

        tools = resolved_tools

    from app.joysafeter_domain.agent.node_tools import _normalize_user_id

    normalized_user_id = _normalize_user_id(user_id)
    root_dir = f"./logs/{normalized_user_id}"
    backend = FilesystemSandboxBackend(
        root_dir=root_dir,
        virtual_mode=True,
    )

    middleware = [
        FilesystemMiddleware(backend=backend),
        PatchToolCallsMiddleware(),
        SummarizationMiddleware(model=model, max_tokens_before_summary=170000, messages_to_keep=10),
        LoggingMiddleware(backend=backend),
    ]

    if enable_todo_list:
        middleware.insert(0, cast(Any, TodoListMiddleware()))

    if enable_skills:
        try:
            from deepagents.middleware.skills import SkillsMiddleware

            skills_middleware = SkillsMiddleware(
                backend=backend,
                sources=["/workspace/skills/"],
            )
            if enable_todo_list:
                middleware.insert(1, skills_middleware)
            else:
                middleware.insert(0, skills_middleware)
        except ImportError:
            logger.warning("[get_agent] deepagents SkillsMiddleware not available")
        except Exception as e:
            logger.warning(f"[get_agent] Failed to create SkillsMiddleware: {e}")

    if node_middleware:
        node_middleware.sort(key=lambda mw: getattr(mw, "priority", 100))
        for mw in node_middleware:
            middleware.append(mw)

    agent_config: RunnableConfig = {"recursion_limit": 1000}  # type: ignore[assignment]
    if agent_name:
        agent_config["tags"] = [f"Agent:{agent_name}"]  # type: ignore[assignment]

    agent: Runnable = create_agent(
        model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        middleware=middleware,
    ).with_config(agent_config)

    return agent
