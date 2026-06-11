"""
Shared credential helpers for CLI agent containers.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.joysafeter_domain.models.agent import Agent

# Host env keys that should be passed through to CLI agent containers
PASSTHROUGH_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AI_GATEWAY_BASE_URL",
    "AI_GATEWAY_API_KEY",
    "AI_GATEWAY_PROVIDER",
    "AI_GATEWAY_MODEL",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
)


def build_credentials(custom_env: dict[str, str] | None) -> dict[str, str]:
    """Merge agent custom_env with host AI provider keys (agent overrides host).

    Raises ValueError if no Anthropic API key is found from any source.
    """
    env: dict[str, str] = {}
    for key in PASSTHROUGH_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = val
    if custom_env:
        env.update(custom_env)

    has_key = env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN")
    if not has_key:
        raise ValueError(
            "CLI agent requires an Anthropic API key. "
            "Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN in "
            "the backend environment (.env) or in the agent's custom_env."
        )
    return env


def build_agent_credentials(agent: Agent) -> dict[str, str]:
    """Build credentials for an agent, merging its custom_env with host keys."""
    from app.joysafeter_shared.model.utils import decrypt_credentials

    custom_env = decrypt_credentials(agent.encrypted_custom_env) if agent.encrypted_custom_env else None
    return build_credentials(custom_env)
