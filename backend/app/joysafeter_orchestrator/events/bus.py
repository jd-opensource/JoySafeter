"""JoySafeter event bus for JoySafeter runner domain events."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope
from app.joysafeter_orchestrator.events.subscriber import JoySafeterEventSubscriber, SubscriberPhase

_STATUS_EVENT_TYPES = {
    "session.status_running",
    "session.status_idle",
    "session.status_rescheduling",
    "session.status_terminated",
}


class JoySafeterEventBus:
    """Two-phase event bus for JoySafeter domain events."""

    def __init__(self) -> None:
        self._persist_subs: list[JoySafeterEventSubscriber] = []
        self._broadcast_subs: list[JoySafeterEventSubscriber] = []
        self._persist_failure_count = 0
        self._broadcast_failure_count = 0
        self._last_persist_failure: dict[str, Any] | None = None
        self._last_broadcast_failure: dict[str, Any] | None = None

    def register(self, sub: JoySafeterEventSubscriber) -> None:
        if sub.phase == SubscriberPhase.PERSIST:
            self._persist_subs.append(sub)
        else:
            self._broadcast_subs.append(sub)
        logger.info("Registered joysafeter event subscriber: %s", sub.name)

    async def publish(self, envelope: JoySafeterEventEnvelope) -> None:
        """Publish event. Never raises — errors are logged but don't kill callers."""
        self._normalize_status_envelope(envelope)
        try:
            await self._publish_inner(envelope)
        except Exception as e:
            logger.error("EventBus.publish failed (swallowed): %s", e, exc_info=True)

    def health_snapshot(self) -> dict[str, Any]:
        status = "degraded" if self._persist_failure_count else "ok"
        return {
            "status": status,
            "persist_subscribers": [sub.name for sub in self._persist_subs],
            "broadcast_subscribers": [sub.name for sub in self._broadcast_subs],
            "persist_failure_count": self._persist_failure_count,
            "broadcast_failure_count": self._broadcast_failure_count,
            "last_persist_failure": self._last_persist_failure,
            "last_broadcast_failure": self._last_broadcast_failure,
        }

    def _record_persist_failure(self, envelope: JoySafeterEventEnvelope, error: Exception) -> None:
        self._persist_failure_count += 1
        self._last_persist_failure = {
            "event_type": envelope.event_type,
            "session_id": str(envelope.session_id) if envelope.session_id else None,
            "error": str(error),
            "timestamp": time.time(),
        }

    def _record_broadcast_failure(
        self,
        envelope: JoySafeterEventEnvelope,
        subscriber: JoySafeterEventSubscriber | None,
        error: Exception,
    ) -> None:
        self._broadcast_failure_count += 1
        self._last_broadcast_failure = {
            "subscriber": subscriber.name if subscriber else None,
            "event_type": envelope.event_type,
            "session_id": str(envelope.session_id) if envelope.session_id else None,
            "error": str(error),
            "timestamp": time.time(),
        }

    async def _publish_inner(self, envelope: JoySafeterEventEnvelope) -> None:
        if envelope.is_status_change:
            for sub in self._persist_subs:
                try:
                    await sub.handle(envelope)
                except Exception as exc:
                    self._record_persist_failure(envelope, exc)
                    logger.warning("JoySafeter persist phase failed: %s", exc)
                    return
            if envelope.suppress_broadcast:
                return
            results = await asyncio.gather(
                *(sub.handle(envelope) for sub in self._broadcast_subs),
                return_exceptions=True,
            )
            for i, result in enumerate(results):
                if isinstance(result, Exception) and i < len(self._broadcast_subs):
                    self._record_broadcast_failure(envelope, self._broadcast_subs[i], result)
                    logger.warning(
                        "JoySafeter broadcast subscriber %s failed: %s",
                        self._broadcast_subs[i].name,
                        result,
                    )
            return

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
                    self._record_persist_failure(envelope, result)
                    logger.warning("JoySafeter persist phase failed: %s", result)
                else:
                    sub_idx = i - 1
                    if sub_idx < len(self._broadcast_subs):
                        self._record_broadcast_failure(envelope, self._broadcast_subs[sub_idx], result)
                        logger.warning(
                            "JoySafeter broadcast subscriber %s failed: %s",
                            self._broadcast_subs[sub_idx].name,
                            result,
                        )

    async def publish_batch(self, envelopes: list[JoySafeterEventEnvelope]) -> None:
        for envelope in envelopes:
            self._normalize_status_envelope(envelope)

        if any(envelope.is_status_change for envelope in envelopes):
            for envelope in envelopes:
                await self._publish_inner(envelope)
            return

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
                if not isinstance(result, Exception):
                    continue
                if i == 0:
                    first_envelope = envelopes[0] if envelopes else None
                    if first_envelope is not None:
                        self._record_persist_failure(first_envelope, result)
                    logger.warning("JoySafeter batch persist phase failed: %s", result)
                    continue
                if i > 0:
                    sub_idx = (i - 1) % max(len(self._broadcast_subs), 1)
                    if sub_idx < len(self._broadcast_subs):
                        envelope_idx = (i - 1) // max(len(self._broadcast_subs), 1)
                        envelope = envelopes[envelope_idx] if envelope_idx < len(envelopes) else envelopes[-1]
                        self._record_broadcast_failure(envelope, self._broadcast_subs[sub_idx], result)
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

    @staticmethod
    def _normalize_status_envelope(envelope: JoySafeterEventEnvelope) -> None:
        if envelope.event_type in _STATUS_EVENT_TYPES:
            envelope.is_status_change = True
