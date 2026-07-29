"""Background worker for rebuilding fallback zero vectors."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime as dt
from collections.abc import Callable
from typing import Any

from app.everos.component.utils.datetime import get_utc_now
from app.everos.core.observability.logging import get_logger

from .vector_rebuild import VectorRebuildSpec, rebuild_fallback_rows

logger = get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class VectorRebuildRunResult:
    rebuilt: int
    failed_kind: str | None = None
    error: str | None = None
    skipped_for_cooldown: bool = False


class VectorFallbackRebuildWorker:
    """Periodically re-embed rows marked ``vector_status='fallback_zero'``."""

    def __init__(
        self,
        *,
        specs: list[VectorRebuildSpec],
        embedder: Any,
        embedding_model: str | None,
        batch_size: int,
        failure_cooldown_seconds: float,
        interval_seconds: float = 300.0,
        initial_delay_seconds: float = 30.0,
        now: Callable[[], dt.datetime] = get_utc_now,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._specs = specs
        self._embedder = embedder
        self._embedding_model = embedding_model
        self._batch_size = batch_size
        self._failure_cooldown = dt.timedelta(seconds=failure_cooldown_seconds)
        self._interval = interval_seconds
        self._initial_delay = initial_delay_seconds
        self._now = now
        self._sleep = sleep
        self._cooldown_until: dt.datetime | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="vector-rebuild")
        logger.info(
            "vector_fallback_rebuild_worker_started",
            interval_seconds=self._interval,
            batch_size=self._batch_size,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None
        logger.info("vector_fallback_rebuild_worker_stopped")

    async def run_once(self) -> VectorRebuildRunResult:
        now = self._now()
        if self._cooldown_until is not None and now < self._cooldown_until:
            return VectorRebuildRunResult(rebuilt=0, skipped_for_cooldown=True)

        total = 0
        for spec in self._specs:
            try:
                rebuilt = await rebuild_fallback_rows(
                    spec.repo,
                    text_getter=spec.text_getter,
                    embedder=self._embedder,
                    embedding_model=self._embedding_model,
                    now=self._now,
                    limit=self._batch_size,
                )
            except Exception as exc:  # noqa: BLE001 - retry later after cooldown.
                self._cooldown_until = now + self._failure_cooldown
                logger.warning(
                    "vector_fallback_rebuild_failed",
                    kind=spec.kind,
                    cooldown_until=self._cooldown_until.isoformat(),
                    error=str(exc),
                )
                return VectorRebuildRunResult(
                    rebuilt=total,
                    failed_kind=spec.kind,
                    error=str(exc),
                )
            if rebuilt:
                logger.info(
                    "vector_fallback_rebuilt",
                    kind=spec.kind,
                    count=rebuilt,
                )
            total += rebuilt
        return VectorRebuildRunResult(rebuilt=total)

    async def _run_loop(self) -> None:
        try:
            await self._sleep(self._initial_delay)
        except asyncio.CancelledError:
            return
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue
