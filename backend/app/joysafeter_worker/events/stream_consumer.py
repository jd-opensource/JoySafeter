"""Redis Stream consumer for worker-side joysafeter event persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid
from typing import Any, Optional

from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.config.service_role import current_role
from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_shared.ids import EventId, SessionId
from app.joysafeter_worker.events.batch_writer import BufferedEvent, EventBatchConfig, EventBatchSender

logger = logging.getLogger(__name__)


def _event_stream_error(
    *,
    code: str,
    message: str,
    operation: str,
    error: Exception | None = None,
    data: dict[str, Any] | None = None,
    retryable: bool = True,
    user_action: str | None = "retry",
) -> dict[str, Any]:
    return async_boundary_error_payload(
        code=code,
        message=message,
        boundary="event_stream_worker",
        operation=operation,
        data=data,
        source="worker",
        detail=error.__class__.__name__ if error is not None else None,
        retryable=retryable,
        user_action=user_action,
    )


def _ids_over_delivery_limit(pending: list[dict[str, Any]], max_deliveries: int) -> list[str]:
    """From ``XPENDING``-range output, return the message ids delivered more
    than ``max_deliveries`` times — poison messages stuck in the reclaim loop
    because they can never be persisted and therefore never acked."""
    return [entry["message_id"] for entry in pending if entry.get("times_delivered", 0) > max_deliveries]


class EventStreamWorker:
    """Consumes Redis Stream joysafeter events and writes them via EventBatchSender."""

    def __init__(
        self,
        *,
        stream_key: str,
        group: str,
        consumer: Optional[str] = None,
        batch_size: int = 100,
        block_ms: int = 1000,
    ) -> None:
        self._stream_key = stream_key
        self._dead_letter_key = f"{stream_key}{joysafeter_config.event_stream_dead_letter_suffix}"
        self._group = group
        self._consumer = consumer or f"{socket.gethostname()}:{current_role().value}:{uuid.uuid4().hex[:8]}"
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._stopping = asyncio.Event()
        self._event_buffer = EventBatchSender(
            EventBatchConfig(
                enabled=joysafeter_config.event_batch_enabled,
                max_size=joysafeter_config.event_batch_max_size,
                max_delay_ms=joysafeter_config.event_batch_max_delay_ms,
            )
        )

    async def run(self) -> None:
        redis = RedisClient.get_client()
        if redis is None:
            logger.warning(
                "Redis unavailable; joysafeter event stream worker is disabled",
                extra={
                    "error": _event_stream_error(
                        code="EVENT_STREAM_REDIS_UNAVAILABLE",
                        message="Redis unavailable; event stream worker is disabled.",
                        operation="start_event_stream_worker",
                    )
                },
            )
            return

        await self._ensure_group(redis)
        self._event_buffer.start()
        logger.info(
            "JoySafeter event stream worker started (stream=%s, group=%s, consumer=%s)",
            self._stream_key,
            self._group,
            self._consumer,
        )

        backoff = 1
        try:
            while not self._stopping.is_set():
                try:
                    recovered = await self._process_pending(redis)
                    if recovered:
                        backoff = 1
                        continue

                    messages = await redis.xreadgroup(
                        self._group,
                        self._consumer,
                        {self._stream_key: ">"},
                        count=self._batch_size,
                        block=self._block_ms,
                    )
                    backoff = 1
                    if not messages:
                        continue

                    batch: list[tuple[str, BufferedEvent]] = []
                    for _stream_name, entries in messages:
                        for message_id, fields in entries:
                            try:
                                event = self._decode_event(fields)
                                batch.append((message_id, event))
                            except Exception as e:
                                logger.exception(
                                    "Failed to handle joysafeter event stream message %s: %s",
                                    message_id,
                                    e,
                                    extra={
                                        "error": _event_stream_error(
                                            code="EVENT_STREAM_MESSAGE_DECODE_FAILED",
                                            message="Failed to decode event stream message.",
                                            operation="decode_event_stream_message",
                                            error=e,
                                            data={"message_id": str(message_id)},
                                        )
                                    },
                                )

                    if batch:
                        await self._persist_and_ack(redis, batch)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # F4 fix: catch Redis/DB errors and retry with backoff
                    # instead of letting the entire worker die permanently
                    logger.error(
                        "Event stream worker error (will retry in %ds): %s",
                        backoff,
                        e,
                        extra={
                            "error": _event_stream_error(
                                code="EVENT_STREAM_WORKER_LOOP_FAILED",
                                message="Event stream worker loop failed; retrying with backoff.",
                                operation="run_event_stream_worker",
                                error=e,
                                data={"backoff_seconds": backoff},
                            )
                        },
                        exc_info=True,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    # Re-acquire Redis client in case connection was lost
                    reconnected = RedisClient.get_client()
                    if reconnected is None:
                        logger.warning(
                            "Redis unavailable during reconnect, waiting...",
                            extra={
                                "error": _event_stream_error(
                                    code="EVENT_STREAM_REDIS_RECONNECT_UNAVAILABLE",
                                    message="Redis unavailable during event stream worker reconnect.",
                                    operation="reconnect_event_stream_worker",
                                )
                            },
                        )
                        continue
                    redis = reconnected
                    await self._ensure_group(redis)

        except asyncio.CancelledError:
            raise
        finally:
            await self._event_buffer.stop()
            logger.info("JoySafeter event stream worker stopped")

    def stop(self) -> None:
        self._stopping.set()

    async def _ensure_group(self, redis: Any) -> None:
        try:
            await redis.xgroup_create(self._stream_key, self._group, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def _dead_letter_exhausted(self, redis: Any) -> int:
        """Move poison messages out of the way so they stop looping forever.

        A message that decodes but can never be persisted is never acked, so
        ``xautoclaim`` keeps re-delivering it and starves the head of the queue.
        Once its delivery count crosses ``event_stream_max_deliveries`` we copy it
        to the dead-letter stream and ack it, removing it from the pending list.
        """
        max_deliveries = joysafeter_config.event_stream_max_deliveries
        if max_deliveries <= 0:
            return 0
        try:
            pending = await redis.xpending_range(
                self._stream_key, self._group, min="-", max="+", count=self._batch_size
            )
        except Exception as e:
            logger.debug("Redis XPENDING unavailable or failed: %s", e)
            return 0

        dead_ids = _ids_over_delivery_limit(pending, max_deliveries)
        for message_id in dead_ids:
            try:
                entries = await redis.xrange(self._stream_key, min=message_id, max=message_id)
                fields = dict(entries[0][1]) if entries else {}
                fields["_dead_letter_reason"] = "max_deliveries_exceeded"
                fields["_original_message_id"] = str(message_id)
                await redis.xadd(self._dead_letter_key, fields)
                await redis.xack(self._stream_key, self._group, message_id)
                logger.error(
                    "Dead-lettered poison event %s to %s after exceeding %d deliveries",
                    message_id,
                    self._dead_letter_key,
                    max_deliveries,
                    extra={
                        "error": _event_stream_error(
                            code="EVENT_STREAM_POISON_MESSAGE_DEAD_LETTERED",
                            message="Event stream poison message moved to dead-letter stream.",
                            operation="dead_letter_poison_event",
                            data={
                                "message_id": str(message_id),
                                "dead_letter_key": self._dead_letter_key,
                                "max_deliveries": max_deliveries,
                            },
                            retryable=False,
                            user_action="refresh",
                        )
                    },
                )
            except Exception as e:
                logger.warning(
                    "Failed to dead-letter poison event %s: %s",
                    message_id,
                    e,
                    extra={
                        "error": _event_stream_error(
                            code="EVENT_STREAM_DEAD_LETTER_FAILED",
                            message="Failed to move poison event to dead-letter stream.",
                            operation="dead_letter_poison_event",
                            error=e,
                            data={"message_id": str(message_id), "dead_letter_key": self._dead_letter_key},
                        )
                    },
                    exc_info=True,
                )
        return len(dead_ids)

    async def _process_pending(self, redis: Any) -> bool:
        await self._dead_letter_exhausted(redis)
        try:
            claimed = await redis.xautoclaim(
                self._stream_key,
                self._group,
                self._consumer,
                joysafeter_config.event_stream_pending_idle_ms,
                "0-0",
                count=self._batch_size,
            )
        except Exception as e:
            logger.debug("Redis XAUTOCLAIM unavailable or failed: %s", e)
            return False

        entries = claimed[1] if len(claimed) > 1 else []
        if not entries:
            return False

        batch: list[tuple[str, BufferedEvent]] = []
        for message_id, fields in entries:
            try:
                batch.append((message_id, self._decode_event(fields)))
            except Exception as e:
                logger.exception(
                    "Failed to decode pending joysafeter event %s: %s",
                    message_id,
                    e,
                    extra={
                        "error": _event_stream_error(
                            code="EVENT_STREAM_PENDING_MESSAGE_DECODE_FAILED",
                            message="Failed to decode pending event stream message.",
                            operation="decode_pending_event_stream_message",
                            error=e,
                            data={"message_id": str(message_id)},
                        )
                    },
                )

        if batch:
            await self._persist_and_ack(redis, batch)
        return True

    async def _persist_and_ack(self, redis: Any, batch: list[tuple[str, BufferedEvent]]) -> None:
        await self._event_buffer.write_batch_now([event for _, event in batch])
        ack_ids = [message_id for message_id, _event in batch]
        await redis.xack(self._stream_key, self._group, *ack_ids)

    def _decode_event(self, fields: dict[str, Any]) -> BufferedEvent:
        session_id = SessionId.from_uuid(uuid.UUID(str(fields["session_id"])))
        event_id_raw = str(fields.get("event_id") or "")
        payload_raw = fields.get("payload") or "{}"
        # F1 fix: always assign an event_id so the batch writer's dedup check
        # (which skips events with e.id is None) can prevent duplicates on
        # crash-recovery re-delivery via XAUTOCLAIM.
        event_id = EventId.from_uuid(uuid.UUID(event_id_raw) if event_id_raw else uuid.uuid4())
        return BufferedEvent(
            session_id=session_id,
            event_type=str(fields["event_type"]),
            payload=json.loads(payload_raw),
            seq=int(fields.get("seq") or 0),
            id=event_id,
        )
