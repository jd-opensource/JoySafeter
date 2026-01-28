"""
Python Coder Tool Prompts - Loads from centralized registry.

All prompt content is stored in:
- backend/agent/prompts/tools/python_coder.md (contains <decision>, <generate>, <fix> sections)
"""

import re

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


def _extract_section(content: str, section_name: str) -> str:
    """Extract a specific XML section from the prompt content."""
    pattern = rf"<{section_name}>(.*?)</{section_name}>"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content  # Return full content if section not found


# Load from registry - single file contains all sections
_FULL_PROMPT = _load_prompt("tools/python_coder")

# Extract sections from the unified prompt
PYTHON_CODER_DESCRIPTION = _extract_section(_FULL_PROMPT, "decision")
CODE_GENERATION_PROMPT = _extract_section(_FULL_PROMPT, "generate")
CODE_FIX_PROMPT = _extract_section(_FULL_PROMPT, "fix")
