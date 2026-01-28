"""
Intent Extractor - 007: Intent-First Clean Context Architecture

Extract core intent from user messages for Intent Persistence.
"""

from typing import Any

from loguru import logger

INTENT_EXTRACTION_PROMPT = """
Summarize the user's core goal in one sentence (no more than 50 words). Only output the summary, no explanation.

User message: {message}

Requirements:
- Extract the core goal
- Be concise
- No more than 50 words
- Only output the summary
"""


async def extract_intent(user_message: str, llm: Any) -> str:
    """
    Extract Intent from the first user message.

    Args:
        user_message: User's original message
        llm: LLM instance (supports ainvoke method)

    Returns:
        Extracted Intent string (<=100 characters)
    """
    # Truncate overly long messages
    truncated_message = user_message[:500]

    prompt = INTENT_EXTRACTION_PROMPT.format(message=truncated_message)

    try:
        response = await llm().ainvoke([{"role": "user", "content": prompt}])

        # Handle different response formats
        if hasattr(response, "content"):
            intent: str = str(response.content).strip()
        elif isinstance(response, str):
            intent = response.strip()
        elif isinstance(response, dict) and "content" in response:
            intent = str(response["content"]).strip()
        else:
            intent = str(response).strip()

        # Limit length
        if len(intent) > 100:
            intent = intent[:97] + "..."

        logger.info(f"Extracted intent: {intent}")
        return intent

    except Exception as e:
        logger.warning(f"Failed to extract intent via LLM: {e}")
        # Fallback: Use first 100 characters of message
        fallback = user_message[:100].strip()
        if len(fallback) > 97:
            fallback = fallback[:97] + "..."
        return fallback


def extract_intent_sync(user_message: str, llm: Any) -> str:
    """
    Synchronous version of Intent extraction (for non-async contexts).

    Args:
        user_message: User's original message
        llm: LLM instance (supports invoke method)

    Returns:
        Extracted Intent string (<=100 characters)
    """
    truncated_message = user_message[:500]
    prompt = INTENT_EXTRACTION_PROMPT.format(message=truncated_message)

    try:
        response = llm().invoke([{"role": "user", "content": prompt}])

        if hasattr(response, "content"):
            intent: str = str(response.content).strip()
        elif isinstance(response, str):
            intent = response.strip()
        else:
            intent = str(response).strip()

        if len(intent) > 100:
            intent = intent[:97] + "..."

        return intent

    except Exception as e:
        logger.warning(f"Failed to extract intent via LLM: {e}")
        fallback = user_message[:100].strip()
        if len(fallback) > 97:
            fallback = fallback[:97] + "..."
        return fallback


def extract_intent_simple(user_message: str) -> str:
    """
    Simple Intent extraction (without LLM).

    Used for quick scenarios or as a fallback when LLM is unavailable.

    Args:
        user_message: User's original message

    Returns:
        Extracted Intent string (<=100 characters)
    """
    # Remove extra whitespace
    message = " ".join(user_message.split())

    # Truncate
    if len(message) > 100:
        message = message[:97] + "..."

    return message
