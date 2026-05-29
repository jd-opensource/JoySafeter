from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.conductor.events.envelope import ConductorEventEnvelope
from app.conductor.events.subscriber import ConductorEventSubscriber, SubscriberPhase

logger = logging.getLogger(__name__)


class ConductorEventBus:
    """Two-phase event bus for Conductor domain events.

    Phase 1 (PERSIST): sequential — DB writes must complete before broadcast.
    Phase 2 (BROADCAST): parallel fan-out — failures are isolated.
    """

    def __init__(self) -> None:
        self._persist_subs: list[ConductorEventSubscriber] = []
        self._broadcast_subs: list[ConductorEventSubscriber] = []

    def register(self, sub: ConductorEventSubscriber) -> None:
        if sub.phase == SubscriberPhase.PERSIST:
            self._persist_subs.append(sub)
        else:
            self._broadcast_subs.append(sub)
        logger.info("Registered conductor event subscriber: %s (phase=%s)", sub.name, sub.phase.name)

    async def publish(self, envelope: ConductorEventEnvelope) -> None:
        for sub in self._persist_subs:
            await sub.handle(envelope)

        if self._broadcast_subs:
            results = await asyncio.gather(
                *(sub.handle(envelope) for sub in self._broadcast_subs),
                return_exceptions=True,
            )
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Conductor broadcast subscriber %s failed: %s",
                        self._broadcast_subs[i].name, result,
                    )

    async def publish_batch(self, envelopes: list[ConductorEventEnvelope]) -> None:
        for envelope in envelopes:
            for sub in self._persist_subs:
                await sub.handle(envelope)

        if self._broadcast_subs:
            tasks: list[Any] = []
            for envelope in envelopes:
                for sub in self._broadcast_subs:
                    tasks.append(sub.handle(envelope))
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        sub_idx = i % len(self._broadcast_subs)
                        logger.warning(
                            "Conductor broadcast subscriber %s failed: %s",
                            self._broadcast_subs[sub_idx].name, result,
                        )
