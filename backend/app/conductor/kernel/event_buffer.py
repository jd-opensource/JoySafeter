import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.conductor.kernel.runtime_config import RuntimeConfig

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
    id: Any = None  # optional pre-assigned uuid.UUID


_STOP_SENTINEL = object()


class _FlushRequest:
    """Mirrors Rust's EventBatchMessage::Flush(oneshot::Sender<()>).

    Carries an asyncio.Event that the flush loop sets after the buffer
    has been written, so callers of flush() can await actual completion.
    """
    __slots__ = ("ack",)

    def __init__(self) -> None:
        self.ack = asyncio.Event()


class EventBatchSender:
    """Batched session event writer. Accumulates events and flushes them to the DB
    either when the batch reaches max_size or after max_delay_ms elapses.

    Ported from conductor-kernel/src/event_buffer.rs.
    """

    def __init__(self, config: EventBatchConfig, runtime_config: Optional["RuntimeConfig"] = None):
        self._config = config
        self._runtime_config = runtime_config
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=config.max_size * 4)
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    @property
    def _effective_max_size(self) -> int:
        if self._runtime_config:
            return self._runtime_config.event_batch_max_size
        return self._config.max_size

    @property
    def _effective_max_delay_ms(self) -> int:
        if self._runtime_config:
            return self._runtime_config.event_batch_max_delay_ms
        return self._config.max_delay_ms

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
        """Flush buffered events and await acknowledgment from the flush loop.

        Mirrors Rust's EventBatchMessage::Flush(oneshot::Sender<()>) pattern:
        sends a _FlushRequest through the queue and waits for the loop to
        signal completion via the embedded ack event.
        """
        if not self._config.enabled or not self._task:
            return
        req = _FlushRequest()
        await self._queue.put(req)
        await req.ack.wait()

    async def _flush_loop(self) -> None:
        buffer: list[BufferedEvent] = []
        pending_flush_acks: list[_FlushRequest] = []
        deadline: float | None = None

        while True:
            max_size = self._effective_max_size
            delay = self._effective_max_delay_ms / 1000.0

            if deadline is not None:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    if buffer:
                        await self._flush_buffer(buffer)
                        buffer.clear()
                    deadline = None
                    for req in pending_flush_acks:
                        req.ack.set()
                    pending_flush_acks.clear()
                    continue
                timeout = remaining
            else:
                timeout = None

            try:
                if timeout is not None:
                    event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                else:
                    event = await self._queue.get()
            except asyncio.TimeoutError:
                if buffer:
                    await self._flush_buffer(buffer)
                    buffer.clear()
                deadline = None
                for req in pending_flush_acks:
                    req.ack.set()
                pending_flush_acks.clear()
                continue

            if event is _STOP_SENTINEL:
                while not self._queue.empty():
                    remaining_evt = self._queue.get_nowait()
                    if remaining_evt is _STOP_SENTINEL:
                        continue
                    if isinstance(remaining_evt, _FlushRequest):
                        pending_flush_acks.append(remaining_evt)
                        continue
                    buffer.append(remaining_evt)
                if buffer:
                    await self._flush_buffer(buffer)
                    buffer.clear()
                for req in pending_flush_acks:
                    req.ack.set()
                pending_flush_acks.clear()
                self._stopped.set()
                return

            if isinstance(event, _FlushRequest):
                # Flush immediately and acknowledge (Rust: Flush(ack_tx) arm)
                await self._flush_buffer(buffer)
                buffer.clear()
                deadline = None
                event.ack.set()
                for req in pending_flush_acks:
                    req.ack.set()
                pending_flush_acks.clear()
                continue

            if not buffer:
                deadline = asyncio.get_event_loop().time() + delay

            buffer.append(event)

            if len(buffer) >= max_size:
                await self._flush_buffer(buffer)
                buffer.clear()
                deadline = None
                for req in pending_flush_acks:
                    req.ack.set()
                pending_flush_acks.clear()

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
        from collections import defaultdict
        from sqlalchemy import text, func, select
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.session import ConductorSessionEvent

        groups: dict = defaultdict(list)
        for e in events:
            groups[e.session_id].append(e)

        async with AsyncSessionLocal() as db:
            for session_id, group in groups.items():
                lock_key = int.from_bytes(session_id.bytes[8:], "big", signed=True)
                await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

                result = await db.execute(
                    select(func.coalesce(func.max(ConductorSessionEvent.seq), 0)).where(
                        ConductorSessionEvent.session_id == session_id
                    )
                )
                base_seq = result.scalar()

                for i, e in enumerate(group, start=1):
                    kwargs: dict[str, Any] = dict(
                        session_id=e.session_id,
                        event_type=e.event_type,
                        payload=e.payload,
                        seq=base_seq + i,
                    )
                    if e.id is not None:
                        kwargs["id"] = e.id
                    obj = ConductorSessionEvent(**kwargs)
                    db.add(obj)

            await db.commit()

    async def _write_single(self, event: BufferedEvent) -> None:
        from sqlalchemy import text, func, select
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.session import ConductorSessionEvent

        async with AsyncSessionLocal() as db:
            async with db.begin():
                lock_key = int.from_bytes(event.session_id.bytes[8:], "big", signed=True)
                await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

                result = await db.execute(
                    select(func.coalesce(func.max(ConductorSessionEvent.seq), 0)).where(
                        ConductorSessionEvent.session_id == event.session_id
                    )
                )
                base_seq = result.scalar()

                kwargs: dict[str, Any] = dict(
                    session_id=event.session_id,
                    event_type=event.event_type,
                    payload=event.payload,
                    seq=base_seq + 1,
                )
                if event.id is not None:
                    kwargs["id"] = event.id
                obj = ConductorSessionEvent(**kwargs)
                db.add(obj)
