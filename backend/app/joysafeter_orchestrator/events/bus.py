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
                        "JoySafeter broadcast subscriber %s failed: %s",
                        self._broadcast_subs[i].name,
                        result,
                    )

    async def publish_batch(self, envelopes: list[JoySafeterEventEnvelope]) -> None:
        for envelope in envelopes:
            for sub in self._persist_subs:
                await sub.handle(envelope)

        if self._broadcast_subs:
            tasks = []
            for envelope in envelopes:
                for sub in self._broadcast_subs:
                    tasks.append(sub.handle(envelope))
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        sub_idx = i % len(self._broadcast_subs)
                        logger.warning(
                            "JoySafeter broadcast subscriber %s failed: %s",
                            self._broadcast_subs[sub_idx].name,
                            result,
                        )
