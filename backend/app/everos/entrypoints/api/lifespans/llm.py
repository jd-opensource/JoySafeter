"""LLM lifespan provider.

The JoySafeter sidecar must be able to boot for health and sandbox
connectivity checks before real LLM credentials are installed. Memory
operations still fail at the call site if they require an unconfigured LLM.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.everos.component.llm import LLMNotConfiguredError, get_llm_client
from app.everos.core.lifespan import LifespanProvider
from app.everos.core.observability.logging import get_logger

logger = get_logger(__name__)


class LLMLifespanProvider(LifespanProvider):
    """Resolve the LLM client at startup when credentials are configured."""

    def __init__(self, order: int = 8) -> None:
        super().__init__(name="llm", order=order)

    async def startup(self, app: FastAPI) -> Any:
        try:
            client = get_llm_client()
        except LLMNotConfiguredError as exc:
            logger.warning("llm_lifespan_not_configured", error=str(exc))
            return None
        logger.info("llm_lifespan_ready")
        return client

    async def shutdown(self, app: FastAPI) -> None:
        # The client is stateless (algo facade over openai.AsyncOpenAI);
        # nothing to tear down.
        return None
