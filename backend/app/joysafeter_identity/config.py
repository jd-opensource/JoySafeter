from __future__ import annotations

import os
from enum import Enum
from typing import Mapping


class AgentIdentityProvider(str, Enum):
    NONE = "none"
    JD = "jd"


def resolve_agent_identity_provider(
    environ: Mapping[str, str] | None = None,
) -> AgentIdentityProvider:
    values = os.environ if environ is None else environ
    raw_provider = values.get("AGENT_IDENTITY_PROVIDER", "").strip().lower()
    if not raw_provider:
        return AgentIdentityProvider.NONE
    try:
        return AgentIdentityProvider(raw_provider)
    except ValueError as exc:
        supported = ", ".join(provider.value for provider in AgentIdentityProvider)
        raise ValueError(f"AGENT_IDENTITY_PROVIDER must be one of: {supported}") from exc
