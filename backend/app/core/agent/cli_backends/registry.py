from __future__ import annotations

from loguru import logger

from .base import RuntimeProvider


class RuntimeProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, RuntimeProvider] = {}

    def register(self, provider: RuntimeProvider) -> None:
        self._providers[provider.provider_type] = provider
        logger.info(f"Registered runtime provider: {provider.provider_type}")

    def get(self, provider_type: str) -> RuntimeProvider:
        if provider_type not in self._providers:
            raise ValueError(f"Unknown runtime provider: {provider_type}")
        return self._providers[provider_type]

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())


runtime_registry = RuntimeProviderRegistry()


def init_providers() -> None:
    from .claude_code import ClaudeCodeProvider
    runtime_registry.register(ClaudeCodeProvider())
