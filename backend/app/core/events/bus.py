"""
ExecutionEventBus — unified event pipeline.

Phase 1 subscribers share the caller's DB session and run sequentially.
The bus commits once after all Phase 1 subscribers complete.

Phase 2 subscribers run in parallel with independent sessions.
A failure in one does not affect the others.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from app.core.events.subscriber import EventSubscriber, SubscriberPhase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.events.envelope import ExecutionEventEnvelope


class ExecutionEventBus:
    def __init__(self) -> None:
        self._persist_subs: list[EventSubscriber] = []
        self._broadcast_subs: list[EventSubscriber] = []

    def register(self, sub: EventSubscriber) -> None:
        if sub.phase == SubscriberPhase.PERSIST:
            self._persist_subs.append(sub)
        else:
            self._broadcast_subs.append(sub)
        logger.info(f"[EventBus] Registered subscriber: {sub.name} (phase={sub.phase.name})")

    async def publish(self, envelope: ExecutionEventEnvelope, db: AsyncSession) -> None:
        # Phase 1: shared transaction, sequential
        for sub in self._persist_subs:
            await sub.handle(envelope, db=db)
        await db.commit()

        # Phase 2: independent sessions, parallel fan-out
        await self._fan_out([envelope])

    async def publish_batch(
        self,
        envelopes: list[ExecutionEventEnvelope],
        db: AsyncSession,
    ) -> None:
        """Publish multiple envelopes in a single transaction.

        Phase 1 processes all envelopes sequentially, then commits once.
        Phase 2 fans out all envelopes in parallel.
        """
        for envelope in envelopes:
            for sub in self._persist_subs:
                await sub.handle(envelope, db=db)
        await db.commit()

        await self._fan_out(envelopes)

    async def _fan_out(self, envelopes: list[ExecutionEventEnvelope]) -> None:
        if not self._broadcast_subs:
            return
        tasks = [sub.handle(envelope) for envelope in envelopes for sub in self._broadcast_subs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                sub_idx = i % len(self._broadcast_subs)
                logger.warning(
                    f"[EventBus] {self._broadcast_subs[sub_idx].name} failed: {result}",
                    exc_info=result,
                )


execution_event_bus = ExecutionEventBus()


# ---------------------------------------------------------------------------
# Conductor event bus (separate domain from ExecutionEventBus)
# ---------------------------------------------------------------------------

from app.core.events.envelope import ConductorEventEnvelope
from app.core.events.subscriber import ConductorEventSubscriber


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
                            "Conductor broadcast subscriber %s failed: %s",
                            self._broadcast_subs[sub_idx].name, result,
                        )
