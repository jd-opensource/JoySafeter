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
        tasks = [
            sub.handle(envelope)
            for envelope in envelopes
            for sub in self._broadcast_subs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                sub_idx = i % len(self._broadcast_subs)
                logger.warning(
                    f"[EventBus] {self._broadcast_subs[sub_idx].name} failed: {result}",
                    exc_info=result,
                )


execution_event_bus = ExecutionEventBus()
