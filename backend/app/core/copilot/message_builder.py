"""
Message Builder - Unified builder for LangChain messages from conversation history.

Converts conversation history (List[Dict]) to LangChain message objects
(HumanMessage, AIMessage) for agent invocation.
"""

from typing import Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def build_langchain_messages(
    prompt: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> List[BaseMessage]:
    """
    Build LangChain messages list from prompt and conversation history.

    Converts conversation history dicts to LangChain message objects:
    - {"role": "user", "content": "..."} -> HumanMessage
    - {"role": "assistant", "content": "..."} -> AIMessage

    Args:
        prompt: Current user prompt
        conversation_history: Optional list of previous messages in format
                            [{"role": "user"|"assistant", "content": "..."}, ...]

    Returns:
        List of LangChain message objects (HumanMessage, AIMessage)
    """
    messages: List[BaseMessage] = []

    # Add conversation history if provided
    if conversation_history:
        for msg in conversation_history:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                role = msg["role"]
                content = msg.get("content", "")
                if role == "user" and content:
                    messages.append(HumanMessage(content=content))
                elif role == "assistant" and content:
                    messages.append(AIMessage(content=content))

    # Add current user message
    messages.append(HumanMessage(content=prompt))

    return messages
