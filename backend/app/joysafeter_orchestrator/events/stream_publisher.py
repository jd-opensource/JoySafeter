"""Redis Stream publisher for runner-side joysafeter events."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope
from app.joysafeter_worker.events.batch_writer import BufferedEvent, EventBatchSender
from app.joysafeter_orchestrator.events.subscriber import SubscriberPhase
from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.config.settings import joysafeter_config

logger = logging.getLogger(__name__)


class EventStreamPersistSubscriber:
    """Persist-phase subscriber that appends joysafeter events to Redis Stream."""

    name = "event_stream_persist"
    phase = SubscriberPhase.PERSIST

    def __init__(self, stream_key: str, fallback_event_buffer: Optional[EventBatchSender] = None) -> None:
        self._stream_key = stream_key
        self._fallback_event_buffer = fallback_event_buffer

    async def handle(self, envelope: JoySafeterEventEnvelope) -> None:
        if envelope.is_status_change and not envelope.event_id:
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
        try:
            redis = RedisClient.get_client()
            if redis is None:
                raise RuntimeError("Redis client is unavailable")
            await redis.xadd(self._stream_key, payload, maxlen=joysafeter_config.event_stream_max_len, approximate=True)
        except Exception as e:
            if not joysafeter_config.event_stream_fallback_to_db or self._fallback_event_buffer is None:
                raise
            logger.warning("Redis Stream event append failed; falling back to DB persistence: %s", e)
            await self._fallback_event_buffer.send(self._decode_payload(payload))
            if envelope.flush_immediately:
                await self._fallback_event_buffer.flush()

    def _decode_payload(self, payload: dict[str, str]) -> BufferedEvent:
        event_id = payload.get("event_id") or ""
        return BufferedEvent(
            session_id=uuid.UUID(payload["session_id"]),
            event_type=payload["event_type"],
            payload=json.loads(payload.get("payload") or "{}"),
            seq=int(payload.get("seq") or 0),
            id=uuid.UUID(event_id) if event_id else None,
        )
