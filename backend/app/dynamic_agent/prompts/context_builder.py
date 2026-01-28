"""
Context Builder - 007: Intent-First Clean Context Architecture

Build KV Cache friendly messages list.
Structure: [System (static)] -> [History] -> [User (Context + Message)]
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from app.dynamic_agent.models.session_context import SessionContext


def _get_static_prompt() -> str:
    """Lazy load static prompt from registry to avoid circular import."""
    from app.dynamic_agent.prompts.registry import get_registry

    try:
        registry = get_registry()
        prompt = registry.get("system/static_main_agent")
        return prompt.render()
    except Exception as e:
        logger.warning(f"Failed to load static prompt: {e}")
        return "[Static prompt not loaded]"


def build_messages(
    user_message: str,
    session_context: Optional[SessionContext] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    system_prompt: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Build KV Cache friendly messages list.

    Structure:
    [System (static)] -> [History] -> [User (Context + Message)]

    Args:
        user_message: User's current message
        session_context: SessionContext instance (optional)
        history: Conversation history (optional)
        system_prompt: Custom System Prompt (optional, defaults to static Prompt)

    Returns:
        Built messages list
    """
    messages = []

    # 1. Static System Prompt (100% KV Cache hit)
    messages.append({"role": "system", "content": system_prompt or _get_static_prompt()})

    # 2. History (incremental cache)
    if history:
        messages.extend(history)

    # 3. User Message with Context
    if session_context:
        context_block = session_context.to_xml() + "\n\n"
        content = context_block + user_message
    else:
        content = user_message

    messages.append({"role": "user", "content": content})

    return messages


def build_messages_with_context(
    user_message: str,
    intent: str,
    progress: str,
    findings: Dict[str, str],
    todo_status: str = "",
    replan_reason: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Build messages using raw parameters (convenience method).

    Args:
        user_message: User's current message
        intent: User intent
        progress: Progress string
        findings: Key findings dictionary
        todo_status: TODO status string
        replan_reason: Replan reason
        history: Conversation history

    Returns:
        Built messages list
    """
    from collections import OrderedDict

    session_context = SessionContext(
        intent=intent,
        progress=progress,
        findings=OrderedDict(findings),
        todo_status=todo_status,
        replan_reason=replan_reason,
    )

    return build_messages(
        user_message=user_message,
        session_context=session_context,
        history=history,
    )


def inject_context_to_message(
    user_message: str,
    session_context: SessionContext,
) -> str:
    """
    Inject session_context to the beginning of user message.

    Args:
        user_message: Original user message
        session_context: SessionContext instance

    Returns:
        Message with context injected
    """
    context_block = session_context.to_xml()
    return f"{context_block}\n\n{user_message}"


def extract_context_from_message(message: str) -> tuple[Optional[str], str]:
    """
    Extract session_context block from message.

    Args:
        message: Message that may contain session_context

    Returns:
        (context_block, remaining_message) tuple
    """
    start_tag = "<session_context>"
    end_tag = "</session_context>"

    if start_tag not in message:
        return None, message

    start_idx = message.find(start_tag)
    end_idx = message.find(end_tag)

    if end_idx == -1:
        return None, message

    context_block = message[start_idx : end_idx + len(end_tag)]
    remaining = message[end_idx + len(end_tag) :].strip()

    return context_block, remaining


class MessageBuilder:
    """
    Message builder class supporting chain calls.
    """

    def __init__(self, system_prompt: Optional[str] = None):
        """
        Initialize message builder.

        Args:
            system_prompt: Custom System Prompt
        """
        self.system_prompt = system_prompt or _get_static_prompt()
        self.history: List[Dict[str, Any]] = []
        self.session_context: Optional[SessionContext] = None

    def with_context(self, session_context: SessionContext) -> "MessageBuilder":
        """Set session context."""
        self.session_context = session_context
        return self

    def with_history(self, history: List[Dict[str, Any]]) -> "MessageBuilder":
        """Set conversation history."""
        self.history = history
        return self

    def add_history(self, role: str, content: str) -> "MessageBuilder":
        """Add one history record."""
        self.history.append({"role": role, "content": content})
        return self

    def build(self, user_message: str) -> List[Dict[str, Any]]:
        """
        Build final messages list.

        Args:
            user_message: User's current message

        Returns:
            Built messages list
        """
        return build_messages(
            user_message=user_message,
            session_context=self.session_context,
            history=self.history,
            system_prompt=self.system_prompt,
        )
