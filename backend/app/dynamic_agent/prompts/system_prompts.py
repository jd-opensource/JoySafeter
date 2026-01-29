"""
System Prompts - Loads prompts from centralized registry.

011: Prompt Consolidation
- main_agent.md is now 100% static (no variables)
- Scene mode content appended to system prompt
- Removed BASIC_GUIDELINES_PROMPT and TOOL_USAGE_GUIDE_PROMPT (merged into main_agent)
"""

from enum import Enum
from typing import Dict

from loguru import logger

from .registry import get_registry

# =============================================================================
# Scene Types - Define supported scene modes
# =============================================================================


class SceneType(Enum):
    """Supported scene types for agent operation modes."""

    CTF = "ctf"  # CTF competition mode
    PENTEST = "pentest"  # Corporate penetration testing mode
    AUDIT = "audit"  # Security audit mode
    WHITEBOX = "whitebox"  # General mode (default)
    GENERAL = "general"  # General mode (default)

    @classmethod
    def values(cls):
        return [e.value for e in cls]


# =============================================================================
# Prompt Loading
# =============================================================================


def _load_prompt(prompt_id: str) -> str:
    """Load a prompt from the registry (no variable substitution)."""
    try:
        registry = get_registry()
        prompt = registry.get(prompt_id)
        return prompt.content  # Direct content, no render()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"Failed to load prompt {prompt_id}: {e}")
        return f"[Prompt {prompt_id} not loaded]"


# Minimal high-confidence CTF indicators (for fast pre-check)
# These are patterns that DEFINITELY indicate CTF context
CTF_DEFINITE_PATTERNS = [
    "flag{",
    "flag:",
    "ctf{",
    "capture the flag",
]


def _classify_scene_with_llm(user_input: str) -> str:
    """
    Use LLM to classify input into a scene type.

    Uses scene_classifier.md prompt to intelligently classify user input.

    Returns:
        Scene type string: "ctf", "pentest", or "general"
    """

    from loguru import logger

    try:
        from app.dynamic_agent.infra.llm import get_default_llm

        prompt_template = _load_prompt("internal/scene_classifier")
        prompt = prompt_template.format(user_input=user_input[:500])

        response = get_default_llm().invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)
        content_str = str(content) if content is not None else ""
        result = content_str.strip().lower()

        # Validate result is a known scene type
        valid_scenes = {SceneType.CTF.value, SceneType.PENTEST.value, SceneType.GENERAL.value}
        if result in valid_scenes:
            logger.info(f"🎭 Scene classified: '{user_input[:40]}...' -> {result}")
            return result

        # Fallback: check if result contains a valid scene
        for scene in valid_scenes:
            if scene in result:
                logger.info(f"🎭 Scene classified (extracted): '{user_input[:40]}...' -> {scene}")
                return scene

        logger.warning(f"Scene classification returned unknown: '{result}', defaulting to general")
        return SceneType.GENERAL.value

    except Exception as e:
        logger.warning(f"Scene LLM classification failed: {e}, falling back to general")
        return SceneType.GENERAL.value


# Load static prompts from registry (no variable substitution)
_SYSTEM_PROMPT = _load_prompt("base/main_agent")
# _CTF_MODE_PROMPT removed - now using scenes/ctf/main_agent.md


def get_system_prompt(user_input: str = "", hint_summary: str = "") -> str:
    """
    Get the system prompt (always static).

    011: System prompt is now 100% static for KV-cache optimization.
    CTF mode content is returned separately via get_ctf_mode_suffix().

    Args:
        user_input: Ignored (kept for backward compatibility)
        hint_summary: Ignored (kept for backward compatibility)

    Returns:
        Static system prompt
    """
    return _SYSTEM_PROMPT


def get_ctf_mode_suffix(user_input: str) -> str:
    """
    Get CTF mode content to append to user message.

    DEPRECATED: Use get_scene_prompt() instead.
    Kept for backward compatibility.
    """
    scene = detect_scene(user_input, use_llm=False)
    if scene == SceneType.CTF.value:
        return f"\n\n{get_scene_prompt(scene)}"
    return ""


# Scene prompt registry - lazy loaded
_SCENE_PROMPTS: Dict[str, str] = {}
# Lazy load scene prompts from scenes/{scene}/ctf_{role}.md
MAIN_AGENT_SYSTEM_PROMPT_MAP = {
    SceneType.CTF.value: "scenes/ctf/ctf_main_agent",
    SceneType.PENTEST.value: "scenes/pentest/pentest_main_agent",
    SceneType.AUDIT.value: "scenes/whitebox/whitebox_main_agent",
    SceneType.WHITEBOX.value: "scenes/whitebox/whitebox_main_agent",
}


def _get_scene_prompt_content(scene: str) -> str:
    """
    Get scene-specific prompt content (lazy loaded).

    Args:
        scene: Scene identifier

    Returns:
        Scene-specific prompt content, empty string if not found
    """
    global _SCENE_PROMPTS

    if scene and scene in SceneType.values():
        scene_content = _load_prompt(MAIN_AGENT_SYSTEM_PROMPT_MAP[scene])
    else:
        scene_content = _load_prompt("scenes/cybersecurity/cybersecurity_main_agent.md")

    # Replace common tool variable placeholders for backward compatibility
    # This maintains compatibility with old BASIC_GUIDELINES_PROMPT and TOOL_USAGE_GUIDE_PROMPT
    # Use str.replace() instead of .format() to avoid issues with curly braces in prompt content
    # (e.g., JSON examples like {"key": "value"} or URL patterns like /api/{id})
    if scene_content:
        try:
            from app.common.constants import AGENT_TOOL, COMMAND_HELP_TOOL, COMMAND_TOOL, KNOWLEDGE_TOOL, THINK_TOOL

            scene_content = scene_content.replace("{KNOWLEDGE_TOOL}", KNOWLEDGE_TOOL)
            scene_content = scene_content.replace("{COMMAND_TOOL}", COMMAND_TOOL)
            scene_content = scene_content.replace("{AGENT_TOOL}", AGENT_TOOL)
            scene_content = scene_content.replace("{THINK_TOOL}", THINK_TOOL)
            scene_content = scene_content.replace("{COMMAND_HELP_TOOL}", COMMAND_HELP_TOOL)
        except Exception as e:
            logger.warning(f"Failed to format variables in scene {scene}: {e}")

    return scene_content


def get_scene_prompt(scene: str) -> str:
    """
    Get scene-specific prompt content to append to system prompt.

    Args:
        scene: Scene identifier (e.g., "ctf", "pentest", "audit")

    Returns:
        Scene-specific prompt content, empty string if scene not found
    """
    return _get_scene_prompt_content(scene)


def detect_scene(user_input: str, use_llm: bool = True) -> str:
    """
    Detect the appropriate scene type from user input.

    Uses a two-stage approach:
    1. Fast check: definite patterns for CTF
    2. LLM check: intelligent classification for all scene types

    Args:
        user_input: User's message
        use_llm: Whether to use LLM for classification

    Returns:
        Scene type string (SceneType.CTF, SceneType.PENTEST, etc.)
    """
    user_input_lower = user_input.lower()

    # Stage 1: Fast check for definite CTF patterns
    if any(pattern in user_input_lower for pattern in CTF_DEFINITE_PATTERNS):
        return SceneType.CTF.value

    # Stage 2: LLM classification for all scene types
    if use_llm:
        return _classify_scene_with_llm(user_input)

    return SceneType.GENERAL.value


def get_system_prompt_with_scene(scene: str = "") -> str:
    """
    Get system prompt with optional scene-specific content appended.

    This allows scene-specific content (CTF mode, pentest mode, etc.)
    to be part of the system prompt rather than user message.

    Structure:
    ```
    <base_system_prompt>
    ...base agent instructions...
    </base_system_prompt>

    <scene_prompt>  <!-- Only if scene is specified -->
    ...scene-specific instructions (ctf_mode, pentest_mode, etc.)...
    </scene_prompt>
    ```

    Args:
        scene: Scene identifier (e.g., "ctf", "pentest", "audit")

    Returns:
        System prompt with scene content appended
    """
    base_prompt = _SYSTEM_PROMPT

    if scene and scene != SceneType.GENERAL.value:
        scene_content = get_scene_prompt(scene)
        if scene_content:
            return f"{base_prompt}\n\n{scene_content}"

    return base_prompt


def format_hint_summary(applied_hints: list, skipped_hints: list) -> str:
    """
    Format applied and skipped hints into a summary for the system prompt.

    Args:
        applied_hints: List of dicts with 'hint_content' and 'description'
        skipped_hints: List of dicts with 'hint_content' and 'skip_reason'

    Returns:
        Formatted markdown summary
    """
    lines = []

    if applied_hints:
        lines.append("### ✅ Applied Hints")
        for i, hint in enumerate(applied_hints, 1):
            content = hint.get("hint_content", "")[:50]
            desc = hint.get("description", "Action generated")
            lines.append(f'{i}. **"{content}..."** → {desc}')

    if skipped_hints:
        lines.append("\n### ⏭️ Skipped Hints")
        for i, hint in enumerate(skipped_hints, 1):
            content = hint.get("hint_content", "")[:50]
            reason = hint.get("skip_reason", "Unknown reason")
            lines.append(f'{i}. **"{content}..."** → Skipped: {reason}')

    if not applied_hints and not skipped_hints:
        lines.append("No user hints provided yet.")

    return "\n".join(lines)


# Default export for backward compatibility
SYSTEM_PROMPT = _SYSTEM_PROMPT


def get_static_system_prompt() -> str:
    """
    Get the static system prompt for KV Cache optimization.

    011: Now same as get_system_prompt() since main_agent.md is 100% static.

    Returns:
        100% static system prompt with no runtime variables
    """
    return _SYSTEM_PROMPT


def get_sub_agent_static_prompt() -> str:
    """
    Get the static sub-agent prompt.

    Returns:
        Static sub-agent prompt for noise handling
    """
    return _load_prompt("base/sub_agent")


# Exports
__all__ = [
    "SYSTEM_PROMPT",
    "get_system_prompt",
    "get_static_system_prompt",
    "get_ctf_mode_suffix",  # DEPRECATED
    # Scene management
    "SceneType",
    "detect_scene",
    "get_scene_prompt",
    "get_system_prompt_with_scene",
    "format_hint_summary",
    "get_sub_agent_static_prompt",
]
