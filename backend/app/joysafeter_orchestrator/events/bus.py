"""JoySafeter event bus for JoySafeter runner domain events."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from app.joysafeter_orchestrator.events.envelope import STATUS_EVENT_TYPES, JoySafeterEventEnvelope
from app.joysafeter_orchestrator.events.subscriber import JoySafeterEventSubscriber, SubscriberPhase
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload


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
            error = self._failure_payload(
                envelope,
                e,
                code="EVENT_BUS_PUBLISH_FAILED",
                message="EventBus publish failed",
                phase="publish",
                operation="publish",
            )
            logger.bind(error=error).opt(exception=e).error("EventBus.publish failed (swallowed)")

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

    def _failure_payload(
        self,
        envelope: JoySafeterEventEnvelope,
        error: Exception,
        *,
        code: str,
        message: str,
        phase: str,
        operation: str,
        subscriber: JoySafeterEventSubscriber | None = None,
    ) -> dict[str, Any]:
        data = {
            "event_type": envelope.event_type,
            "session_id": str(envelope.session_id) if envelope.session_id else None,
            "phase": phase,
        }
        if subscriber is not None:
            data["subscriber"] = subscriber.name
        return async_boundary_error_payload(
            code=code,
            message=message,
            boundary="event_bus",
            operation=operation,
            data=data,
            detail=error.__class__.__name__,
        )

    def _record_persist_failure(self, envelope: JoySafeterEventEnvelope, error: Exception) -> dict[str, Any]:
        self._persist_failure_count += 1
        error_payload = self._failure_payload(
            envelope,
            error,
            code="EVENT_BUS_PERSIST_FAILED",
            message="JoySafeter event persist phase failed",
            phase="persist",
            operation="persist",
        )
        self._last_persist_failure = {
            "event_type": envelope.event_type,
            "session_id": str(envelope.session_id) if envelope.session_id else None,
            "error": error_payload,
            "timestamp": time.time(),
        }
        return error_payload

    def _record_broadcast_failure(
        self,
        envelope: JoySafeterEventEnvelope,
        subscriber: JoySafeterEventSubscriber | None,
        error: Exception,
    ) -> dict[str, Any]:
        self._broadcast_failure_count += 1
        error_payload = self._failure_payload(
            envelope,
            error,
            code="EVENT_BUS_BROADCAST_FAILED",
            message="JoySafeter event broadcast subscriber failed",
            phase="broadcast",
            operation="broadcast",
            subscriber=subscriber,
        )
        self._last_broadcast_failure = {
            "subscriber": subscriber.name if subscriber else None,
            "event_type": envelope.event_type,
            "session_id": str(envelope.session_id) if envelope.session_id else None,
            "error": error_payload,
            "timestamp": time.time(),
        }
        return error_payload

    async def _publish_inner(self, envelope: JoySafeterEventEnvelope) -> None:
        if envelope.is_status_change:
            for sub in self._persist_subs:
                try:
                    await sub.handle(envelope)
                except Exception as exc:
                    error = self._record_persist_failure(envelope, exc)
                    logger.bind(error=error).opt(exception=exc).warning("JoySafeter persist phase failed")
                    return
            if envelope.suppress_broadcast:
                return
            results = await asyncio.gather(
                *(sub.handle(envelope) for sub in self._broadcast_subs),
                return_exceptions=True,
            )
            for i, result in enumerate(results):
                if isinstance(result, Exception) and i < len(self._broadcast_subs):
                    error = self._record_broadcast_failure(envelope, self._broadcast_subs[i], result)
                    logger.bind(error=error).opt(exception=result).warning(
                        "JoySafeter broadcast subscriber failed",
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
                    error = self._record_persist_failure(envelope, result)
                    logger.bind(error=error).opt(exception=result).warning("JoySafeter persist phase failed")
                else:
                    sub_idx = i - 1
                    if sub_idx < len(self._broadcast_subs):
                        error = self._record_broadcast_failure(envelope, self._broadcast_subs[sub_idx], result)
                        logger.bind(error=error).opt(exception=result).warning(
                            "JoySafeter broadcast subscriber failed",
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
                        error = self._record_persist_failure(first_envelope, result)
                        logger.bind(error=error).opt(exception=result).warning("JoySafeter batch persist phase failed")
                    else:
                        error = async_boundary_error_payload(
                            code="EVENT_BUS_BATCH_PERSIST_FAILED",
                            message="JoySafeter batch persist phase failed",
                            boundary="event_bus",
                            operation="publish_batch",
                            data={"event_count": 0, "phase": "persist"},
                            detail=result.__class__.__name__,
                        )
                        logger.bind(error=error).opt(exception=result).warning("JoySafeter batch persist phase failed")
                    continue
                if i > 0:
                    sub_idx = (i - 1) % max(len(self._broadcast_subs), 1)
                    if sub_idx < len(self._broadcast_subs):
                        envelope_idx = (i - 1) // max(len(self._broadcast_subs), 1)
                        envelope = envelopes[envelope_idx] if envelope_idx < len(envelopes) else envelopes[-1]
                        error = self._record_broadcast_failure(envelope, self._broadcast_subs[sub_idx], result)
                        logger.bind(error=error).opt(exception=result).warning(
                            "JoySafeter broadcast subscriber failed",
                        )

    async def flush(self) -> None:
        """Force flush all buffered events to DB — mirrors Rust EventBus.flush()."""
        for sub in self._persist_subs:
            if hasattr(sub, "flush"):
                await sub.flush()

    @staticmethod
    def _normalize_status_envelope(envelope: JoySafeterEventEnvelope) -> None:
        if envelope.event_type in STATUS_EVENT_TYPES:
            envelope.is_status_change = True
