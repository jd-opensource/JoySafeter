"""
Think Tool Prompts - Loads from centralized registry.

All prompt content is stored in backend/agent/prompts/tools/think_tool.md
"""

from app.dynamic_agent.prompts.registry import get_registry


def _load_prompt(prompt_id: str) -> str:
    """Load a prompt from the registry."""
    try:
        registry = get_registry()
        return registry.get(prompt_id).content
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"Failed to load prompt {prompt_id}: {e}")
        return f"[Prompt {prompt_id} not loaded]"


# Load from registry
THINK_PROMPT = _load_prompt("tools/think_tool")

# Backward compatibility alias
THINK_PROMPT1 = THINK_PROMPT
