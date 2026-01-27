"""
DeepAgents Copilot Streaming.

简化版：直接透传 DeepAgents 的 tool_call/tool_result 事件。
Manager 已经负责 SSE 事件生成，这里只做简单的包装。

凭据获取：ChatOpenAI 会自动从 OPENAI_API_KEY 环境变量获取。
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
    流式生成 DeepAgents Copilot actions。

    直接调用 manager.stream_copilot_manager 并透传事件。
    凭据自动从环境变量获取（OPENAI_API_KEY）。

    Yields SSE 事件（与现有 Copilot 兼容）:
        - status: {type, stage, message}
        - content: {type, content}
        - tool_call: {type, tool, input}
        - tool_result: {type, action}
        - result: {type, message, actions}
        - done: {type}
        - error: {type, message}
    """
    from .manager import stream_copilot_manager

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
