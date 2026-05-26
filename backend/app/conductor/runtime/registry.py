import logging
from typing import Optional

from app.conductor.runtime.adapter import HarnessAdapter
from app.conductor.runtime.claude_adapter import ClaudeAdapter
from app.conductor.runtime.codex_adapter import CodexAdapter
from app.conductor.runtime.mock_adapter import MockAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    def __init__(self):
        self._adapters: dict[str, HarnessAdapter] = {}

    @classmethod
    async def discover(cls) -> "AdapterRegistry":
        registry = cls()

        claude = ClaudeAdapter()
        if await claude.is_available():
            registry._adapters["claude"] = claude
            logger.info("Claude adapter registered")

        codex = CodexAdapter()
        if await codex.is_available():
            registry._adapters["codex"] = codex
            logger.info("Codex adapter registered")

        mock = MockAdapter()
        registry._adapters["mock"] = mock
        logger.info("Mock adapter registered")

        return registry

    def get(self, provider: str) -> Optional[HarnessAdapter]:
        return self._adapters.get(provider)

    def get_default(self) -> Optional[HarnessAdapter]:
        for name in ("claude", "codex"):
            if name in self._adapters:
                return self._adapters[name]
        if self._adapters:
            return next(iter(self._adapters.values()))
        return None

    def provider_names(self) -> list[str]:
        return list(self._adapters.keys())

    def is_empty(self) -> bool:
        return len(self._adapters) == 0
