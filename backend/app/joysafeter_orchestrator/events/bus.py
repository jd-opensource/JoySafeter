"""JoySafeter event bus for JoySafeter runner domain events."""

from __future__ import annotations

import asyncio

from loguru import logger

from app.joysafeter_orchestrator.events.subscriber import SubscriberPhase
from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope
from app.joysafeter_orchestrator.events.subscriber import JoySafeterEventSubscriber


class JoySafeterEventBus:
    """Two-phase event bus for JoySafeter domain events."""

    def __init__(self) -> None:
        self._persist_subs: list[JoySafeterEventSubscriber] = []
        self._broadcast_subs: list[JoySafeterEventSubscriber] = []

    def register(self, sub: JoySafeterEventSubscriber) -> None:
        if sub.phase == SubscriberPhase.PERSIST:
            self._persist_subs.append(sub)
        else:
            self._broadcast_subs.append(sub)
        logger.info("Registered joysafeter event subscriber: %s", sub.name)

    async def publish(self, envelope: JoySafeterEventEnvelope) -> None:
        """Publish event. Never raises — errors are logged but don't kill callers."""
        try:
            await self._publish_inner(envelope)
        except Exception as e:
            logger.error("EventBus.publish failed (swallowed): %s", e, exc_info=True)

    async def _publish_inner(self, envelope: JoySafeterEventEnvelope) -> None:
        # Run persist and broadcast CONCURRENTLY — not sequentially.
        # Previously broadcast waited for persist (100ms+ DB batch delay per event).
        # Now SSE gets events immediately while DB persist happens in parallel.
        async def _persist():
            for sub in self._persist_subs:
                await sub.handle(envelope)

        tasks: list = [_persist()]
        for sub in self._broadcast_subs:
            tasks.append(sub.handle(envelope))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                if i == 0:
                    logger.warning("JoySafeter persist phase failed: %s", result)
                else:
                    sub_idx = i - 1
                    if sub_idx < len(self._broadcast_subs):
                        logger.warning(
                            "JoySafeter broadcast subscriber %s failed: %s",
                            self._broadcast_subs[sub_idx].name,
                            result,
                        )

    async def publish_batch(self, envelopes: list[JoySafeterEventEnvelope]) -> None:
        # Same optimization: persist and broadcast in parallel
        async def _persist():
            for envelope in envelopes:
                for sub in self._persist_subs:
                    await sub.handle(envelope)

        tasks: list = [_persist()]
        for envelope in envelopes:
            for sub in self._broadcast_subs:
                tasks.append(sub.handle(envelope))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception) and i > 0:
                    sub_idx = (i - 1) % max(len(self._broadcast_subs), 1)
                    if sub_idx < len(self._broadcast_subs):
                        logger.warning(
                            "JoySafeter broadcast subscriber %s failed: %s",
                            self._broadcast_subs[sub_idx].name,
                            result,
                        )

    async def flush(self) -> None:
        """Force flush all buffered events to DB — mirrors Rust EventBus.flush()."""
        for sub in self._persist_subs:
            if hasattr(sub, "flush"):
                await sub.flush()
