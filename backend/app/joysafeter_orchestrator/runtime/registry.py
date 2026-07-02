import logging
import os
from typing import Optional

from app.joysafeter_orchestrator.runtime.adapter import HarnessAdapter
from app.joysafeter_orchestrator.runtime.claude_adapter import ClaudeAdapter
from app.joysafeter_orchestrator.runtime.codex_adapter import CodexAdapter
from app.joysafeter_orchestrator.runtime.native_adapter import NativeAdapter

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

        native = NativeAdapter()
        if await native.is_available():
            registry._adapters["native"] = native
            logger.info("Native adapter registered")

        codex = CodexAdapter()
        if await codex.is_available():
            registry._adapters["codex"] = codex
            logger.info("Codex adapter registered")

        # Mock adapter only registered when explicitly enabled (matching Rust gate)
        mock_enabled = os.getenv("JOYSAFETER_MOCK_ADAPTER", "").lower() in ("1", "true")
        if mock_enabled:
            from app.joysafeter_orchestrator.runtime.mock_adapter import MockAdapter

            mock = MockAdapter()
            registry._adapters["mock"] = mock
            logger.info("Mock adapter registered (JOYSAFETER_MOCK_ADAPTER=1)")

        return registry

    def get(self, provider: str) -> Optional[HarnessAdapter]:
        return self._adapters.get(provider)

    def get_default(self) -> Optional[HarnessAdapter]:
        for name in ("claude", "native", "codex"):
            if name in self._adapters:
                return self._adapters[name]
        if self._adapters:
            return next(iter(self._adapters.values()))
        return None

    def provider_names(self) -> list[str]:
        return list(self._adapters.keys())

    def is_empty(self) -> bool:
        return len(self._adapters) == 0
