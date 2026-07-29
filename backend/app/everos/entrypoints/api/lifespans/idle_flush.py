"""Idle-flush background loop lifespan provider."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from fastapi import FastAPI

from app.everos.config import load_settings
from app.everos.core.lifespan import LifespanProvider
from app.everos.core.observability.logging import get_logger
from app.everos.service.idle_flush import scan_and_flush_idle

logger = get_logger(__name__)


def _resolve_interval_and_threshold() -> tuple[float, int]:
    m = load_settings().memorize
    return float(m.idle_flush_scan_interval_seconds), int(m.idle_flush_threshold_seconds)


class IdleFlushLifespanProvider(LifespanProvider):
    """Run a periodic idle-buffer flush loop while the app is up."""

    def __init__(self, order: int = 60) -> None:
        super().__init__(name="idle_flush", order=order)
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        while True:
            interval, threshold = _resolve_interval_and_threshold()
            try:
                await scan_and_flush_idle(now=dt.datetime.now(tz=dt.UTC), threshold_seconds=threshold)
            except Exception as exc:  # loop must survive scan errors
                logger.warning("idle_flush_scan_error", extra={"error": str(exc)})
            await asyncio.sleep(interval)

    async def startup(self, app: FastAPI) -> Any:
        if not load_settings().memorize.idle_flush_enabled:
            logger.info("idle_flush_disabled")
            return None
        self._task = asyncio.create_task(self._loop())
        logger.info("idle_flush_loop_started")
        return self._task

    async def shutdown(self, app: FastAPI) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info("idle_flush_loop_stopped")
