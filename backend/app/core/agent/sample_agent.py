"""
Example Agent implementation.

Implements a sample chatbot node using LangChain v1 create_agent API.
"""

from typing import Any

from deepagents.middleware import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain.tools import tool
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.agent.backends.filesystem_sandbox import FilesystemSandboxBackend
from app.core.agent.midware import LoggingMiddleware

load_dotenv()


@tool
def math_tool(expression: str) -> str:
    """
    Calculate the result of a mathematical expression.
    Args:
        expression: The mathematical expression to evaluate.

    Returns:
        The result of the expression as a string.
    """
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


def get_default_model(
    llm_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 4096,
    timeout: int | None = None,
) -> ChatOpenAI:
    """
    Create and return a default ChatOpenAI model instance.

    This function resolves configuration from function parameters.
    Note: Credentials should be provided via parameters or fetched from database.

    Args:
        llm_model: Optional LLM model name. Defaults to "gpt-4o-mini".
        api_key: Optional API key for authentication (required if not provided via database).
        base_url: Optional base URL for the API endpoint.
        max_tokens: Maximum completion tokens. Defaults to 4096.
        timeout: Optional timeout in seconds. Defaults to 120 seconds.

    Returns:
        ChatOpenAI: Configured ChatOpenAI model instance with streaming enabled.
    """
    # Use provided parameters (credentials should be fetched from database by caller)
    api_key_value = api_key
    base_url_value = base_url

    # Resolve model name from parameter (不再使用 settings.openai_model)
    # 注意：调用者应该从数据库获取默认模型并传递 llm_model 参数
    model_name = llm_model or "gpt-4o-mini"  # 最后的硬编码后备（应该尽量避免）

    # Convert API key to SecretStr if provided
    secret_api_key: SecretStr | None = SecretStr(api_key_value) if api_key_value else None

    # Set default timeout to 120 seconds if not provided
    # This helps prevent "No generations found in stream" errors
    # that occur when the default 60s timeout is exceeded
    timeout_value = timeout if timeout is not None else 120

    # Create and return ChatOpenAI instance
    model = ChatOpenAI(
        model=model_name,
        api_key=secret_api_key,
        base_url=base_url_value,
        max_completion_tokens=max_tokens,
        streaming=True,  # Enable streaming output
        timeout=timeout_value,  # Set timeout to prevent premature stream termination
    )

    return model


async def get_agent(
    checkpointer: Any | None = None,
    llm_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 4096,
    user_id: str | None = None,
    system_prompt: str | None = None,
    tools: list[Any] | None = None,
    enable_todo_list: bool = True,
    enable_skills: bool = True,
    skill_user_id: str | None = None,
    agent_name: str | None = None,
    model: Any | None = None,
    node_middleware: list[Any] | None = None,
) -> Runnable:
    """
    Create and return the Agent graph.

    Args:
        checkpointer: Optional checkpointer for state persistence.
        llm_model: LLM model name.
        api_key: API key.
        base_url: API base URL.
        max_tokens: Maximum completion tokens.
        user_id: User ID (UUID), used to create an isolated workspace directory.
        system_prompt: System prompt for the agent.
        tools: List of tools for the agent.
        enable_todo_list: Whether to enable TodoListMiddleware.
                         Set to False for DeepAgents subagents to avoid state conflicts.
        enable_skills: Whether to enable SkillMiddleware for progressive skill disclosure.
        skill_user_id: User ID for skill filtering (defaults to user_id).
        agent_name: Name of the agent (for tagging).
        model: Optional pre-created model instance.
        node_middleware: List of middleware instances from node configuration (e.g., from resolve_middleware_for_node).

    Returns:
        Runnable: The compiled Agent graph.
    """
    # 如果提供了模型对象，直接使用它；否则，使用 get_default_model 创建模型实例
    if model is None:
        model = get_default_model(
            llm_model=llm_model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
        )
    else:
        from loguru import logger

    # Tools resolution:
    # - If caller provides `tools`, use exactly that list (can be empty to disable tools).
    #   Try to get tools from ToolRegistry first, then use provided tools as fallback.
    # - Otherwise, return empty list (tools should be explicitly provided via resolve_tools_for_node).
    from loguru import logger

    from app.core.tools.tool import EnhancedTool, ToolMetadata
    from app.core.tools.tool_registry import get_global_registry

    if tools is None:
        tools = []
    else:
        # 检查 tools 是否是 ToolMetadata 对象（不应该直接作为 tools 参数传递）
        if isinstance(tools, ToolMetadata):
            logger.error(f"[get_agent] ERROR: tools parameter is a ToolMetadata object, not a list! metadata: {tools}")
            logger.warning("[get_agent] Converting ToolMetadata to empty list")
            tools = []
        # 检查 tools 是否是列表或可迭代对象
        elif not isinstance(tools, (list, tuple)):
            logger.warning(f"[get_agent] tools is not a list/tuple, type: {type(tools)}, converting to list")
            try:
                tools = list(tools) if hasattr(tools, "__iter__") else [tools]
            except Exception as e:
                logger.error(f"[get_agent] Failed to convert tools to list: {e}")
                tools = []

        # 从 ToolRegistry 获取工具（如果已注册）
        registry = get_global_registry()
        resolved_tools = []
        for tool in tools:
            if isinstance(tool, ToolMetadata):
                continue

            if isinstance(tool, EnhancedTool):
                resolved_tools.append(tool)
                continue

            if isinstance(tool, str):
                # 先尝试直接获取（内置工具）
                registry_tool = registry.get_tool(tool)
                if registry_tool:
                    resolved_tools.append(registry_tool)
                    continue

                # 尝试解析为 MCP 工具（格式: server_name::tool_name）
                if "::" in tool:
                    from app.core.tools.mcp_tool_utils import parse_mcp_tool_name

                    server_name, tool_name = parse_mcp_tool_name(tool)
                    if server_name and tool_name:
                        mcp_tool = registry.get_mcp_tool(server_name, tool_name)
                        if mcp_tool:
                            resolved_tools.append(mcp_tool)
                            continue

                # 无法解析，记录警告但跳过（不添加字符串到工具列表）
                logger.warning(f"[get_agent] Unable to resolve tool '{tool}', skipping")
                continue

            resolved_tools.append(tool)

        tools = resolved_tools

    # Create per-user isolated workspace directory
    # Normalize user_id to ensure it's a string (UUID format)
    from app.core.agent.node_tools import _normalize_user_id

    normalized_user_id = _normalize_user_id(user_id)
    root_dir = f"./logs/{normalized_user_id}"
    backend = FilesystemSandboxBackend(
        root_dir=root_dir,
        virtual_mode=True,  # Use virtual filesystem (in-memory)
    )

    # Build middleware list
    middleware = [
        FilesystemMiddleware(backend=backend),
        PatchToolCallsMiddleware(),
        SummarizationMiddleware(model=model, max_tokens_before_summary=170000, messages_to_keep=10),
        LoggingMiddleware(backend=backend),
    ]

    # Only add TodoListMiddleware if enabled (disabled for DeepAgents subagents)
    if enable_todo_list:
        middleware.insert(0, TodoListMiddleware())

    # Add SkillsMiddleware if enabled
    if enable_skills:
        # Use deepagents SkillsMiddleware if backend is available
        # This injects skill descriptions into system prompt from /workspace/skills/
        # Skills must be preloaded to /workspace/skills/ via SkillSandboxLoader
        if backend:
            try:
                from deepagents.middleware.skills import SkillsMiddleware

                skills_middleware = SkillsMiddleware(
                    backend=backend,
                    sources=["/workspace/skills/"],  # Path where skills should be preloaded
                )
                # Insert after TodoListMiddleware if it exists, otherwise at the beginning
                if enable_todo_list:
                    middleware.insert(1, skills_middleware)
                else:
                    middleware.insert(0, skills_middleware)
                logger.debug(
                    "[get_agent] Added deepagents SkillsMiddleware (backend available, "
                    "reading from /workspace/skills/). "
                    "Agents can read skill files directly from the sandbox."
                )
            except ImportError:
                logger.warning(
                    "[get_agent] deepagents SkillsMiddleware not available. Skills descriptions will not be injected."
                )
            except Exception as e:
                logger.warning(
                    f"[get_agent] Failed to create deepagents SkillsMiddleware: {e}. "
                    "Skills descriptions will not be injected."
                )
        else:
            logger.debug(
                "[get_agent] No backend available for SkillsMiddleware. "
                "Skills descriptions will not be injected. "
                "Ensure skills are preloaded via SkillSandboxLoader if backend is needed."
            )

    # Add node-specific middleware (from resolve_middleware_for_node)
    # These are middleware instances created from node configuration (e.g., MemoryMiddleware)
    if node_middleware:
        # Sort middleware by priority (lower number = higher priority = executed first)
        node_middleware.sort(key=lambda mw: getattr(mw, "priority", 100))

        # Insert node middleware after default middleware but before the end
        # This ensures they have access to the full middleware chain
        for mw in node_middleware:
            middleware.append(mw)
        logger.debug(
            f"[get_agent] Added {len(node_middleware)} node middleware instance(s) "
            f"for agent '{agent_name or 'unknown'}' (sorted by priority)"
        )

    # Create agent (callbacks will be configured at invoke time)
    from langchain_core.runnables import RunnableConfig

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


if __name__ == "__main__":
    import asyncio

    async def main():
        agent = await get_agent()
        result = await agent.ainvoke({"messages": [{"role": "user", "content": "What is 1231972 / 8723?"}]})
        print(result)

    asyncio.run(main())
