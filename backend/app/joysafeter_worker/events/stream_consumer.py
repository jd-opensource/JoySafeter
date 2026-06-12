"""Redis Stream consumer for worker-side joysafeter event persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid
from typing import Any, Optional

from app.joysafeter_worker.events.batch_writer import BufferedEvent, EventBatchConfig, EventBatchSender
from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.config.service_role import current_role
from app.joysafeter_shared.config.settings import joysafeter_config

logger = logging.getLogger(__name__)


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
        self._group = group
        self._consumer = consumer or f"{socket.gethostname()}:{current_role().value}:{uuid.uuid4().hex[:8]}"
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._stopping = asyncio.Event()
        self._event_buffer = EventBatchSender(EventBatchConfig(
            enabled=joysafeter_config.event_batch_enabled,
            max_size=joysafeter_config.event_batch_max_size,
            max_delay_ms=joysafeter_config.event_batch_max_delay_ms,
        ))

    async def run(self) -> None:
        redis = RedisClient.get_client()
        if redis is None:
            logger.warning("Redis unavailable; joysafeter event stream worker is disabled")
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
                                logger.exception("Failed to handle joysafeter event stream message %s: %s", message_id, e)

                    if batch:
                        await self._persist_and_ack(redis, batch)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # F4 fix: catch Redis/DB errors and retry with backoff
                    # instead of letting the entire worker die permanently
                    logger.error(
                        "Event stream worker error (will retry in %ds): %s",
                        backoff, e,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    # Re-acquire Redis client in case connection was lost
                    redis = RedisClient.get_client()
                    if redis is None:
                        logger.warning("Redis unavailable during reconnect, waiting...")
                        continue
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

    async def _process_pending(self, redis: Any) -> bool:
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
                logger.exception("Failed to decode pending joysafeter event %s: %s", message_id, e)

        if batch:
            await self._persist_and_ack(redis, batch)
        return True

    async def _persist_and_ack(self, redis: Any, batch: list[tuple[str, BufferedEvent]]) -> None:
        await self._event_buffer.write_batch_now([event for _, event in batch])
        ack_ids = [message_id for message_id, _event in batch]
        await redis.xack(self._stream_key, self._group, *ack_ids)

    def _decode_event(self, fields: dict[str, Any]) -> BufferedEvent:
        session_id = uuid.UUID(str(fields["session_id"]))
        event_id_raw = str(fields.get("event_id") or "")
        payload_raw = fields.get("payload") or "{}"
        # F1 fix: always assign an event_id so the batch writer's dedup check
        # (which skips events with e.id is None) can prevent duplicates on
        # crash-recovery re-delivery via XAUTOCLAIM.
        event_id = uuid.UUID(event_id_raw) if event_id_raw else uuid.uuid4()
        return BufferedEvent(
            session_id=session_id,
            event_type=str(fields["event_type"]),
            payload=json.loads(payload_raw),
            seq=int(fields.get("seq") or 0),
            id=event_id,
        )
