from __future__ import annotations

from typing import Any

from app.joysafeter_identity.config import (
    AgentIdentityProvider,
    resolve_agent_identity_provider,
)
from app.joysafeter_identity.types import CapturedIdentityCredential
from app.joysafeter_shared.ids import AgentId


def validate_provider_configuration() -> None:
    provider = resolve_agent_identity_provider()
    if provider is AgentIdentityProvider.NONE:
        return
    if provider is AgentIdentityProvider.JD:
        from app.joysafeter_identity.providers import jd

        jd.validate_configuration()
        return
    raise AssertionError(f"unsupported agent identity provider: {provider}")


def capture_identity_credential(
    request: Any | None,
    identity_auth_code: str | None,
) -> CapturedIdentityCredential | None:
    provider = resolve_agent_identity_provider()
    if provider is AgentIdentityProvider.NONE:
        return None
    if provider is AgentIdentityProvider.JD:
        from app.joysafeter_identity.providers import jd

        return jd.capture_credential(request, identity_auth_code)
    raise AssertionError(f"unsupported agent identity provider: {provider}")


async def cleanup_agent_identity(agent_id: AgentId) -> None:
    provider = resolve_agent_identity_provider()
    if provider is AgentIdentityProvider.NONE:
        return
    if provider is AgentIdentityProvider.JD:
        from app.joysafeter_identity.providers import jd

        await jd.cleanup_agent_identity(agent_id)
        return
    raise AssertionError(f"unsupported agent identity provider: {provider}")
