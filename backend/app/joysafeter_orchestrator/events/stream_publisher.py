"""Redis Stream publisher for runner-side joysafeter events."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from app.joysafeter_orchestrator.events.envelope import STATUS_EVENT_TYPES, JoySafeterEventEnvelope
from app.joysafeter_orchestrator.events.subscriber import SubscriberPhase
from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_worker.events.batch_writer import BufferedEvent, EventBatchSender

logger = logging.getLogger(__name__)


class EventStreamPersistSubscriber:
    """Persist-phase subscriber that appends joysafeter events to Redis Stream."""

    name = "event_stream_persist"
    phase = SubscriberPhase.PERSIST

    def __init__(self, stream_key: str, fallback_event_buffer: Optional[EventBatchSender] = None) -> None:
        self._stream_key = stream_key
        self._fallback_event_buffer = fallback_event_buffer

    async def handle(self, envelope: JoySafeterEventEnvelope) -> None:
        if envelope.is_status_change or envelope.event_type in STATUS_EVENT_TYPES:
            return
        if envelope.session_id is None:
            return

        payload = {
            "session_id": str(envelope.session_id),
            "event_type": envelope.event_type,
            "payload": json.dumps(envelope.payload, ensure_ascii=False, default=str),
            "seq": str(envelope.seq or 0),
            "event_id": str(envelope.event_id) if envelope.event_id else "",
        }

        redis = RedisClient.get_client()
        if redis is None:
            if await self._persist_via_fallback(payload, envelope):
                return
            raise RuntimeError("Redis client is unavailable")

        # Backpressure: if the consumer has fallen behind and the stream is at its
        # high-water mark, an xadd(maxlen, approximate) would trim the oldest
        # un-consumed entries and silently lose them. Route to the durable DB
        # buffer instead so overflow degrades to slower-but-lossless.
        if await self._stream_saturated(redis):
            if await self._persist_via_fallback(payload, envelope):
                error = self._boundary_error_payload(
                    code="EVENT_STREAM_SATURATED_FALLBACK",
                    message="Redis Stream reached high-water mark; routed event to DB fallback",
                    operation="saturation_fallback",
                    envelope=envelope,
                )
                logger.warning(
                    "Redis Stream %s at high-water mark; routed event to DB fallback",
                    self._stream_key,
                    extra={"error": error},
                )
                return
            # No DB fallback configured: accept bounded loss, but make it visible
            # rather than silently trimming.
            error = self._boundary_error_payload(
                code="EVENT_STREAM_SATURATED_NO_FALLBACK",
                message="Redis Stream reached high-water mark and no DB fallback is configured",
                operation="saturation_no_fallback",
                envelope=envelope,
                retryable=False,
                user_action=None,
            )
            logger.warning(
                "Redis Stream %s at high-water mark and no DB fallback; event may be trimmed",
                self._stream_key,
                extra={"error": error},
            )

        try:
            await redis.xadd(self._stream_key, payload, maxlen=joysafeter_config.event_stream_max_len, approximate=True)
        except Exception as e:
            if not await self._persist_via_fallback(payload, envelope):
                raise
            logger.warning(
                "Redis Stream event append failed; fell back to DB persistence",
                extra={
                    "error": self._boundary_error_payload(
                        code="EVENT_STREAM_APPEND_FALLBACK",
                        message="Redis Stream append failed; fell back to DB persistence",
                        operation="xadd_fallback",
                        envelope=envelope,
                        detail=e.__class__.__name__,
                    )
                },
                exc_info=True,
            )

    async def _stream_saturated(self, redis) -> bool:
        """True when the stream length is at/over the high-water mark, meaning an
        ``xadd`` would trim un-consumed entries. A non-positive configured mark
        auto-derives 90% of ``event_stream_max_len``. If the length can't be read
        we return False so the normal xadd path is never blocked by a probe error."""
        hwm = joysafeter_config.event_stream_high_water_mark
        if hwm <= 0:
            hwm = int(joysafeter_config.event_stream_max_len * 0.9)
        if hwm <= 0:
            return False
        try:
            length: int = await redis.xlen(self._stream_key)
        except Exception as e:
            logger.debug(
                "Redis XLEN probe failed; skipping saturation check",
                extra={
                    "error": async_boundary_error_payload(
                        code="EVENT_STREAM_XLEN_PROBE_FAILED",
                        message="Redis Stream XLEN probe failed; skipping saturation check",
                        boundary="event_stream_persist",
                        operation="xlen_probe",
                        data={"stream_key": self._stream_key},
                        detail=e.__class__.__name__,
                    )
                },
            )
            return False
        return length >= hwm

    async def _persist_via_fallback(self, payload: dict[str, str], envelope: JoySafeterEventEnvelope) -> bool:
        """Persist the event via the DB buffer instead of the stream. Returns
        False when no fallback is configured (caller decides raise vs. degrade)."""
        if not joysafeter_config.event_stream_fallback_to_db or self._fallback_event_buffer is None:
            return False
        await self._fallback_event_buffer.send(self._decode_payload(payload))
        if envelope.flush_immediately:
            await self._fallback_event_buffer.flush()
        return True

    def _decode_payload(self, payload: dict[str, str]) -> BufferedEvent:
        event_id = payload.get("event_id") or ""
        return BufferedEvent(
            session_id=uuid.UUID(payload["session_id"]),
            event_type=payload["event_type"],
            payload=json.loads(payload.get("payload") or "{}"),
            seq=int(payload.get("seq") or 0),
            id=uuid.UUID(event_id) if event_id else None,
        )

    def _boundary_error_payload(
        self,
        *,
        code: str,
        message: str,
        operation: str,
        envelope: JoySafeterEventEnvelope,
        detail: str | None = None,
        retryable: bool = True,
        user_action: str | None = "retry",
    ) -> dict[str, object]:
        return async_boundary_error_payload(
            code=code,
            message=message,
            boundary="event_stream_persist",
            operation=operation,
            data={
                "stream_key": self._stream_key,
                "session_id": str(envelope.session_id) if envelope.session_id else None,
                "event_type": envelope.event_type,
                "event_id": str(envelope.event_id) if envelope.event_id else None,
            },
            retryable=retryable,
            user_action=user_action,
            detail=detail,
        )
