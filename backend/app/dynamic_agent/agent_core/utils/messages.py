"""Message creation and normalization utilities."""

from typing import Any, List, Set
from uuid import uuid4

from app.dynamic_agent.agent_core.types import (
    AssistantMessage,
    Message,
    MessageParam,
    MessageRole,
    ProgressMessage,
    TextBlock,
    ToolResultBlock,
    Usage,
    UserMessage,
)


def normalize_messages_for_api(messages: List[Message]) -> List[MessageParam]:
    """
    Normalize messages for API consumption.

    Filters out progress messages and converts to MessageParam format.
    """
    result = []
    for msg in messages:
        if isinstance(msg, UserMessage):
            result.append(msg.message)
        elif isinstance(msg, AssistantMessage):
            # AssistantMessage.content is List[TextBlock | ToolUseBlock | ThinkingBlock]
            # MessageParam.content accepts Content which includes ToolResultBlock
            # This is safe as AssistantMessage doesn't contain ToolResultBlock
            result.append(MessageParam(role=MessageRole.ASSISTANT, content=msg.content))  # type: ignore[arg-type]
        # Skip ProgressMessage - not sent to API
    return result


def create_user_message(tool_use_id: str, content: str, is_error: bool = False, data: Any = None) -> UserMessage:
    """Create a user message with tool result."""
    return UserMessage(
        uuid=str(uuid4()),
        message=MessageParam(
            role=MessageRole.USER,
            content=[ToolResultBlock(tool_use_id=tool_use_id, content=content, is_error=is_error)],
        ),
        tool_use_result={"data": data} if data else None,
    )


def create_assistant_message(text: str, is_error: bool = False) -> AssistantMessage:
    """Create a simple assistant text message."""
    return AssistantMessage(id=str(uuid4()), content=[TextBlock(text=text)], usage=Usage(), is_api_error=is_error)


def create_progress_message(
    tool_use_id: str, sibling_ids: Set[str], content: AssistantMessage, normalized_messages: List[Any], tools: List[Any]
) -> ProgressMessage:
    """Create a progress message during tool execution."""
    return ProgressMessage(
        uuid=str(uuid4()),
        tool_use_id=tool_use_id,
        sibling_tool_use_ids=sibling_ids,
        content=content,
        normalized_messages=normalized_messages,
        tools=tools,
    )
