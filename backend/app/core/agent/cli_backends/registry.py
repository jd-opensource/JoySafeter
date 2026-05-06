from __future__ import annotations

from loguru import logger

from app.common.app_errors import NotFoundError

from .base import RuntimeProvider


class RuntimeProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, RuntimeProvider] = {}

    def register(self, provider: RuntimeProvider) -> None:
        self._providers[provider.provider_type] = provider
        logger.info(f"Registered runtime provider: {provider.provider_type}")

    def get(self, provider_type: str) -> RuntimeProvider:
        if provider_type not in self._providers:
            raise NotFoundError(
                "Runtime provider not found",
                code="RUNTIME_PROVIDER_NOT_FOUND",
                data={"provider_type": provider_type, "available_providers": list(self._providers.keys())},
            )
        return self._providers[provider_type]

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())


runtime_registry = RuntimeProviderRegistry()


def init_providers() -> None:
    from .claude_code import ClaudeCodeProvider
    from .codex import CodexProvider
    from .openclaw import OpenClawProvider

    runtime_registry.register(ClaudeCodeProvider())
    runtime_registry.register(CodexProvider())
    runtime_registry.register(OpenClawProvider())
