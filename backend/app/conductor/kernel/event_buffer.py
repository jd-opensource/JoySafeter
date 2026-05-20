import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class EventBatchConfig:
    enabled: bool = False
    max_size: int = 50
    max_delay_ms: int = 50


@dataclass
class BufferedEvent:
    session_id: Any  # uuid.UUID
    event_type: str
    payload: dict[str, Any]
    seq: int


_STOP_SENTINEL = object()


class EventBatchSender:
    """Batched session event writer. Accumulates events and flushes them to the DB
    either when the batch reaches max_size or after max_delay_ms elapses.

    Ported from conductor-kernel/src/event_buffer.rs.
    """

    def __init__(self, config: EventBatchConfig):
        self._config = config
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=config.max_size * 4)
        self._flush_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        if not self._config.enabled:
            return
        self._task = asyncio.create_task(self._flush_loop(), name="event-batch-flusher")

    async def stop(self) -> None:
        if self._task:
            await self._queue.put(_STOP_SENTINEL)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Event buffer did not drain in 5s, force cancelling")
                self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send(self, event: BufferedEvent) -> None:
        if not self._config.enabled:
            await self._write_single(event)
            return
        await self._queue.put(event)

    async def flush(self) -> None:
        self._flush_event.set()

    async def _flush_loop(self) -> None:
        buffer: list[BufferedEvent] = []
        delay = self._config.max_delay_ms / 1000.0

        while True:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=delay)
            except asyncio.TimeoutError:
                if buffer:
                    await self._flush_buffer(buffer)
                    buffer.clear()
                if self._flush_event.is_set():
                    self._flush_event.clear()
                continue

            if event is _STOP_SENTINEL:
                while not self._queue.empty():
                    remaining = self._queue.get_nowait()
                    if remaining is not _STOP_SENTINEL:
                        buffer.append(remaining)
                if buffer:
                    await self._flush_buffer(buffer)
                    buffer.clear()
                self._stopped.set()
                return

            buffer.append(event)

            if len(buffer) >= self._config.max_size or self._flush_event.is_set():
                await self._flush_buffer(buffer)
                buffer.clear()
                self._flush_event.clear()

    async def _flush_buffer(self, buffer: list[BufferedEvent]) -> None:
        if not buffer:
            return
        count = len(buffer)
        logger.debug("Flushing %d events to DB", count)
        try:
            await self._batch_insert(buffer)
        except Exception as e:
            logger.error(
                "Batch insert failed (%d events), falling back to individual inserts: %s",
                count, e,
            )
            for event in buffer:
                try:
                    await self._write_single(event)
                except Exception as inner:
                    logger.error("Individual event insert failed: %s", inner)

    async def _batch_insert(self, events: list[BufferedEvent]) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.session import ConductorSessionEvent

        async with AsyncSessionLocal() as db:
            objects = [
                ConductorSessionEvent(
                    session_id=e.session_id,
                    event_type=e.event_type,
                    payload=e.payload,
                    seq=e.seq,
                )
                for e in events
            ]
            db.add_all(objects)
            await db.commit()

    async def _write_single(self, event: BufferedEvent) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.session import ConductorSessionEvent

        async with AsyncSessionLocal() as db:
            obj = ConductorSessionEvent(
                session_id=event.session_id,
                event_type=event.event_type,
                payload=event.payload,
                seq=event.seq,
            )
            db.add(obj)
            await db.commit()
