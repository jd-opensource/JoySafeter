"""
DeepAgents Copilot Streaming.

Simplified: directly pass through DeepAgents tool_call/tool_result events.
The Manager already handles SSE event generation; this module is a thin wrapper.

Credentials: ChatOpenAI automatically reads from the OPENAI_API_KEY env var.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger


async def stream_deepagents_actions(
    *,
    prompt: str,
    graph_context: Dict[str, Any],
    graph_id: Optional[str] = None,
    user_id: Optional[str] = None,
    llm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream DeepAgents Copilot actions.

    Directly call manager.stream_copilot_manager and pass through events.
    Credentials are automatically read from env vars (OPENAI_API_KEY).

    Yields SSE events (compatible with existing Copilot):
        - status: {type, stage, message}
        - content: {type, content}
        - tool_call: {type, tool, input}
        - tool_result: {type, action}
        - result: {type, message, actions}
        - done: {type}
        - error: {type, message}
    """
    from .runner import stream_copilot_manager

    logger.info(f"[DeepAgentsStreaming] Starting stream graph_id={graph_id} user_id={user_id}")

    async for event in stream_copilot_manager(
        user_prompt=prompt,
        graph_context=graph_context,
        graph_id=graph_id,
        user_id=user_id,
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
        conversation_history=conversation_history,
    ):
        yield event

    logger.info(f"[DeepAgentsStreaming] Completed stream graph_id={graph_id}")
