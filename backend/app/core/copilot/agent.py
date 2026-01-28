"""
Copilot Agent - Create and manage the Copilot Agent instance.

Uses the same infrastructure as sample_agent to create an Agent
specialized for graph manipulation tasks.
"""

from typing import Any, Dict, List, Optional

from langchain_core.runnables import Runnable
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.sample_agent import get_agent
from app.core.copilot.prompt_builder import build_copilot_system_prompt
from app.core.copilot.tools import get_copilot_tools, set_current_graph_context, set_preloaded_models


async def _preload_available_models(db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Preload available chat models from database.

    Args:
        db: Database session

    Returns:
        List of available model info dicts
    """
    try:
        from app.core.model import ModelType
        from app.services.model_service import ModelService

        service = ModelService(db)
        models = await service.get_available_models(model_type=ModelType.CHAT)
        logger.debug(f"[_preload_available_models] Loaded {len(models)} chat models")
        return models
    except Exception as e:
        logger.warning(f"[_preload_available_models] Failed to load models: {e}")
        return []


async def get_copilot_agent(
    graph_context: Dict[str, Any],
    user_id: Optional[str] = None,
    llm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_tokens: int = 4096,
    db: Optional[AsyncSession] = None,
) -> Runnable:
    """
    Create a Copilot Agent with graph manipulation tools.

    The agent is configured with:
    - System prompt built from graph context
    - Tools for creating/connecting/deleting nodes
    - Available models list for intelligent model selection
    - TodoList and Skills middleware disabled (not needed for Copilot)

    Args:
        graph_context: Current graph state with nodes and edges
        user_id: Optional user ID for workspace isolation
        llm_model: Optional LLM model name (defaults to system settings)
        api_key: Optional API key (defaults to system settings)
        base_url: Optional API base URL (defaults to system settings)
        max_tokens: Maximum tokens for completion
        db: Optional database session for loading available models

    Returns:
        Configured Runnable agent
    """
    logger.debug(f"[get_copilot_agent] Creating Copilot agent for user_id={user_id}")

    # Preload available models if db session provided
    available_models: List[Dict[str, Any]] = []
    if db:
        available_models = await _preload_available_models(db)
        # Set models for list_models tool
        set_preloaded_models(available_models)

    # Set current graph context for analysis tools (auto_layout, analyze_workflow)
    set_current_graph_context(graph_context)

    # Build system prompt from graph context (with available models)
    system_prompt = build_copilot_system_prompt(graph_context, available_models)

    # Get Copilot tools
    tools = get_copilot_tools()

    logger.debug(f"[get_copilot_agent] System prompt length: {len(system_prompt)}")
    logger.debug(f"[get_copilot_agent] Tools count: {len(tools)}")

    # Create agent using the same infrastructure as sample_agent
    agent = await get_agent(
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        user_id=user_id,
        system_prompt=system_prompt,
        tools=tools,
        # Disable middleware that's not needed for Copilot
        enable_todo_list=False,
        enable_skills=False,
        agent_name="Copilot",
    )

    logger.debug("[get_copilot_agent] Agent created successfully")
    return agent


async def invoke_copilot_agent(
    agent: Runnable,
    user_prompt: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Invoke the Copilot agent and collect tool call results.

    The agent will call tools (create_node, connect_nodes, etc.) and
    this function collects all the tool call results into actions.

    Args:
        agent: The Copilot agent runnable
        user_prompt: User's request
        conversation_history: Optional previous messages

    Returns:
        Dict with 'message' and 'actions' keys
    """
    from app.core.copilot.message_builder import build_langchain_messages

    # Build messages using unified builder
    messages = build_langchain_messages(user_prompt, conversation_history)

    logger.debug(f"[invoke_copilot_agent] Invoking with {len(messages)} messages")

    # Invoke the agent
    result = await agent.ainvoke({"messages": messages})

    # Extract results using unified function
    from app.core.copilot.response_parser import extract_actions_from_agent_result

    # Extract actions from result
    graph_actions = extract_actions_from_agent_result(result, filter_non_actions=False)

    # Convert to dict format for compatibility
    actions = []
    for action in graph_actions:
        actions.append(
            {
                "type": action.type.value,
                "payload": action.payload,
                "reasoning": action.reasoning,
            }
        )

    # Extract final message
    output_messages = result.get("messages", [])
    final_message = ""
    for msg in reversed(output_messages):
        if hasattr(msg, "content") and isinstance(msg.content, str):
            if hasattr(msg, "type") and msg.type == "ai":
                final_message = msg.content
                break
            elif msg.__class__.__name__ == "AIMessage":
                final_message = msg.content
                break

    logger.debug(f"[invoke_copilot_agent] Collected {len(actions)} actions")

    return {
        "message": final_message,
        "actions": actions,
    }
