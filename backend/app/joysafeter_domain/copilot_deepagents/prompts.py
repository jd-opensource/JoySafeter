"""
DeepAgents Copilot - Prompt constants for Manager and sub-agents.

Prompts are maintained as Markdown files under the ``prompts/`` directory
and loaded once at import time.
"""

from pathlib import Path

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


MANAGER_SYSTEM_PROMPT = _load("manager.md")
REQUIREMENTS_ANALYST_PROMPT = _load("requirements_analyst.md")
WORKFLOW_ARCHITECT_PROMPT = _load("workflow_architect.md")
VALIDATOR_PROMPT = _load("validator.md")
