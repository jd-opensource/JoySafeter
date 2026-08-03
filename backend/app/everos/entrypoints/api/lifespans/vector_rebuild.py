"""Vector fallback rebuild lifespan provider.

Starts a background worker that periodically retries rows written with
``vector_status='fallback_zero'``. The worker is best-effort: startup is
skipped when embedding is not configured, and provider failures during a run
are handled by cooldown inside the worker.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.everos.component.embedding import build_embedding_provider
from app.everos.config import load_settings
from app.everos.core.lifespan import LifespanProvider
from app.everos.core.observability.logging import get_logger
from app.everos.memory.vector_auto_rebuild import VectorFallbackRebuildWorker
from app.everos.memory.vector_rebuild import default_vector_rebuild_specs

logger = get_logger(__name__)


class VectorRebuildLifespanProvider(LifespanProvider):
    """Manage automatic zero-vector rebuilds for the API lifecycle."""

    def __init__(self, order: int = 13) -> None:
        super().__init__(name="vector_rebuild", order=order)
        self._worker: VectorFallbackRebuildWorker | None = None

    async def startup(self, app: FastAPI) -> Any:
        settings = load_settings()
        search = settings.search
        if not search.vector_auto_rebuild_enabled:
            logger.info("vector_fallback_rebuild_disabled")
            return None

        try:
            embedder = build_embedding_provider(settings.embedding)
        except ValueError as exc:
            logger.warning(
                "vector_fallback_rebuild_not_configured",
                error=str(exc),
            )
            return None

        self._worker = VectorFallbackRebuildWorker(
            specs=default_vector_rebuild_specs(),
            embedder=embedder,
            embedding_model=settings.embedding.model,
            batch_size=search.vector_auto_rebuild_batch_size,
            interval_seconds=search.vector_auto_rebuild_interval_seconds,
            initial_delay_seconds=(
                search.vector_auto_rebuild_initial_delay_seconds
            ),
            failure_cooldown_seconds=(
                search.vector_auto_rebuild_failure_cooldown_seconds
            ),
        )
        await self._worker.start()
        return self._worker

    async def shutdown(self, app: FastAPI) -> None:
        if self._worker is not None:
            await self._worker.stop()
            self._worker = None
