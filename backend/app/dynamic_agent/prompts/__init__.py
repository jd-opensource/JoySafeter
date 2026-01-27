"""
Centralized Prompt Management System.

This module provides a unified interface for managing and accessing prompts
throughout the seclens agent system.

Usage:
    from app.dynamic_agent.prompts import get_registry, get_prompt

    # Get the registry singleton
    registry = get_registry()

    # Get a prompt by ID
    prompt = registry.get("base/main_agent")
    rendered = prompt.render(hint_summary="...")

    # Or use the convenience function
    rendered = get_prompt("base/main_agent", hint_summary="...")

    # List all prompts
    all_ids = registry.list_all()

    # Get prompts by category
    system_prompts = registry.get_by_category("system")

    # Reload prompts (after editing files)
    registry.reload()
"""

# 007: Intent-First Clean Context Architecture exports
from .context_builder import (
    MessageBuilder,
    build_messages,
    inject_context_to_message,
)
from .exceptions import (
    CircularDependencyError,
    PromptLoadError,
    PromptNotFoundError,
    PromptValidationError,
)
from .intent_extractor import (
    extract_intent,
    extract_intent_simple,
    extract_intent_sync,
)
from .models import LoadedPrompt, PromptMetadata
from .registry import PromptRegistry, get_registry

# Re-export for backward compatibility
from .system_prompts import (
    SYSTEM_PROMPT,
    # Scene management
    SceneType,
    detect_scene,
    format_hint_summary,
    get_ctf_mode_suffix,  # DEPRECATED
    get_scene_prompt,
    get_static_system_prompt,
    get_sub_agent_static_prompt,
    get_system_prompt,
    get_system_prompt_with_scene,
)

__all__ = [
    # Core classes
    "PromptRegistry",
    "PromptMetadata",
    "LoadedPrompt",
    # Convenience functions
    "get_registry",
    "get_prompt",
    # Exceptions
    "PromptNotFoundError",
    "PromptValidationError",
    "PromptLoadError",
    "CircularDependencyError",
    # System prompts
    "SYSTEM_PROMPT",
    "get_system_prompt",
    "get_ctf_mode_suffix",  # DEPRECATED
    # Scene management
    "SceneType",
    "detect_scene",
    "get_scene_prompt",
    "get_system_prompt_with_scene",
    "format_hint_summary",
    "get_static_system_prompt",
    "get_sub_agent_static_prompt",
    # Context builder
    "build_messages",
    "inject_context_to_message",
    "MessageBuilder",
    # Intent extractor
    "extract_intent",
    "extract_intent_sync",
    "extract_intent_simple",
]


def get_prompt(prompt_id: str, **kwargs) -> str:
    """
    Get and render a prompt in one call.

    Convenience function that combines registry lookup and rendering.

    Args:
        prompt_id: Prompt identifier (e.g., 'base/main_agent')
        **kwargs: Variable values to substitute in the prompt

    Returns:
        Rendered prompt content with variables replaced

    Raises:
        PromptNotFoundError: If prompt_id does not exist
    """
    registry = get_registry()
    prompt = registry.get(prompt_id)
    return prompt.render(**kwargs)
