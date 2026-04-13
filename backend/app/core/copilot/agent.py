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
    max_tokens: int = 4096,
    db: Optional[AsyncSession] = None,
    model: Any = None,
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
        max_tokens: Maximum tokens for completion
        db: Optional database session for loading available models
        model: Pre-created LangChain model instance (from ModelResolver)

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
        model=model,
        max_tokens=max_tokens,
        user_id=user_id,
        system_prompt=system_prompt,
        tools=tools,
        enable_todo_list=False,
        enable_skills=False,
        agent_name="Copilot",
    )

    logger.debug("[get_copilot_agent] Agent created successfully")
    return agent
