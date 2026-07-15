"""Project-aware LLM resolution for EverOS.

JoySafeter projects can mark one managed secret as the current/default model
credential. This module lets EverOS use that project secret for LLM calls
instead of relying only on process-level ``EVEROS_LLM__*`` settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import SecretStr

from app.everos.config import LLMSettings
from app.everos.core.errors import ConfigurationError
from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_shared.database import AsyncSessionLocal

from .anthropic_provider import AnthropicProvider
from .client import get_llm_client
from .factory import build_llm_provider
from .protocol import LLMClient


class IncompatibleProjectLLMSecretError(ConfigurationError):
    """Raised when the active project secret cannot drive EverOS LLM calls."""


@dataclass(frozen=True)
class ProjectLLMCredential:
    """Resolved credential for a project active secret."""

    provider: Literal["openai", "anthropic"]
    model: str
    api_key: str
    base_url: str
    secret_id: str
    updated_at: datetime | None


_project_llm_clients: dict[tuple[str, str, datetime | None], LLMClient] = {}


def clear_project_llm_client_cache() -> None:
    """Clear the per-project LLM cache. Intended for tests and reload hooks."""
    _project_llm_clients.clear()


async def get_project_llm_client(project_id: str | None) -> LLMClient:
    """Return the LLM client for a JoySafeter project.

    If the project has no active secret, fall back to the legacy process-level
    EverOS LLM settings. If it has an active secret but that secret is not
    OpenAI-compatible, fail explicitly so EverOS never silently uses another
    credential after the user selected a current key.
    """
    credential = await _resolve_project_llm_credential(project_id)
    if credential is None:
        return get_llm_client()

    cache_key = (
        str(project_id or "default"),
        credential.secret_id,
        credential.updated_at,
    )
    cached = _project_llm_clients.get(cache_key)
    if cached is not None:
        return cached

    if credential.provider == "anthropic":
        client = AnthropicProvider(
            model=credential.model,
            api_key=credential.api_key,
            base_url=credential.base_url,
        )
    else:
        client = build_llm_provider(
            LLMSettings(
                model=credential.model,
                api_key=SecretStr(credential.api_key),
                base_url=credential.base_url,
            )
        )
    _project_llm_clients[cache_key] = client
    return client


async def _resolve_project_llm_credential(
    project_id: str | None,
) -> ProjectLLMCredential | None:
    async with AsyncSessionLocal() as db:
        secret_svc = SecretService(db)
        secret = await secret_svc.get_default_secret(project_id=project_id)
        if secret is None:
            return None
        data = secret_svc.get_secret_data(secret)

    openai = _extract_credential(data, provider="openai")
    anthropic = _extract_credential(data, provider="anthropic")
    credential = openai or anthropic
    if credential is None:
        raise IncompatibleProjectLLMSecretError(
            "The active project secret is not compatible for EverOS LLM. "
            "Select a secret with OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL "
            "or ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL."
        )

    return ProjectLLMCredential(
        provider=credential["provider"],
        model=credential["model"],
        api_key=credential["api_key"],
        base_url=credential["base_url"],
        secret_id=str(getattr(secret, "id", "")),
        updated_at=getattr(secret, "updated_at", None),
    )


def _extract_credential(
    data: dict[str, Any],
    *,
    provider: Literal["openai", "anthropic"],
) -> dict[str, Any] | None:
    if provider == "openai":
        model = _first_non_empty(data, "OPENAI_MODEL", "MODEL")
        api_key = _first_non_empty(data, "OPENAI_API_KEY", "API_KEY")
        base_url = _first_non_empty(data, "OPENAI_BASE_URL", "BASE_URL")
    else:
        model = _first_non_empty(data, "ANTHROPIC_MODEL", "MODEL")
        api_key = _first_non_empty(data, "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        base_url = _first_non_empty(data, "ANTHROPIC_BASE_URL")
    if not (model and api_key and base_url):
        return None
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }


def _first_non_empty(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None
