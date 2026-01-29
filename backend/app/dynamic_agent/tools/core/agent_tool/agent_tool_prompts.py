"""
Agent Tool Prompts - Loads from centralized registry.

All prompt content is stored in:
- backend/agent/prompts/base/sub_agent.md
- backend/agent/prompts/tools/agent_tool.md
- backend/agent/prompts/scenes/ctf/sub_agent.md (CTF scene)
"""

from typing import Optional

from app.dynamic_agent.prompts.registry import get_registry
from app.dynamic_agent.prompts.system_prompts import SceneType


def _load_prompt(prompt_id: str, **kwargs) -> str:
    """Load and render a prompt from the registry."""
    try:
        registry = get_registry()
        prompt = registry.get(prompt_id)
        return prompt.render(**kwargs)
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"Failed to load prompt {prompt_id}: {e}")
        return f"[Prompt {prompt_id} not loaded]"


SUB_AGENT_SYSTEM_PROMPT_MAP = {
    SceneType.CTF.value: "scenes/ctf/ctf_sub_agent",
    SceneType.PENTEST.value: "scenes/pentest/pentest_sub_agent",
    SceneType.AUDIT.value: "scenes/whitebox/whitebox_sub_agent",
    SceneType.WHITEBOX.value: "scenes/whitebox/whitebox_sub_agent",
}


def get_sub_agent_prompt(scene: Optional[str] = None) -> str:
    """Get Sub-Agent prompt with optional scene-specific suffix.

    Args:
        scene: The detected scene type (CTF, PENTEST, etc.)

    Returns:
        Combined prompt: sub_agent.md + sub_agent_{scene}_mode.md
    """
    base_prompt = _load_prompt("base/sub_agent")
    if scene and scene in SUB_AGENT_SYSTEM_PROMPT_MAP:
        scene_prompt = _load_prompt(SUB_AGENT_SYSTEM_PROMPT_MAP[scene])
        return f"{base_prompt}\n\n{scene_prompt}"
    else:
        return base_prompt


# Default: base prompt only (for backward compatibility)
AGENT_SYSTEM_PROMPT = _load_prompt("base/sub_agent")

AGENT_TOOL_DESCRIPTION = _load_prompt("tools/agent_tool")


# Backward compatibility alias
AGENT_TOOL_DESCRIPTION1 = AGENT_TOOL_DESCRIPTION
