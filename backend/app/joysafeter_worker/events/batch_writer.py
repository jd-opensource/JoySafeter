import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from app.joysafeter_shared.utils.locks import session_advisory_lock_key

if TYPE_CHECKING:
    from app.joysafeter_orchestrator.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

DEDUP_EVENT_TYPES = {
    "session.status_idle",
    "session.status_rescheduling",
    "session.status_rescheduled",
    "session.status_running",
    "session.status_terminated",
    "session.thread_status_idle",
    "session.thread_status_running",
    "session.thread_status_terminated",
    "span.model_request_start",
    "span.model_request_end",
}

SESSION_STATUS_EVENT_TYPES = {
    "session.status_idle",
    "session.status_rescheduling",
    "session.status_rescheduled",
    "session.status_running",
    "session.status_terminated",
}


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


def _dedup_payload_key(event: BufferedEvent) -> object:
    if event.event_type.startswith("session."):
        return {
            "task_id": event.payload.get("task_id"),
            "stop_reason": event.payload.get("stop_reason") or {},
        }
    if event.event_type == "span.model_request_start":
        return {"model": event.payload.get("model")}
    if event.event_type == "span.model_request_end":
        return {"model": event.payload.get("model"), "usage": event.payload.get("usage") or {}}
    return event.payload


def _is_session_status_event(event_type: str) -> bool:
    return event_type in SESSION_STATUS_EVENT_TYPES


def _is_duplicate_event(a: BufferedEvent | None, b: BufferedEvent) -> bool:
    if a is None:
        return False
    return (
        a.event_type == b.event_type
        and b.event_type in DEDUP_EVENT_TYPES
        and _dedup_payload_key(a) == _dedup_payload_key(b)
    )


_STOP_SENTINEL = object()


class _PartialBatchError(Exception):
    """Raised when _batch_insert succeeds for some sessions but fails for others.
    Carries the failed events so _flush_buffer can retry them individually."""

    def __init__(self, failed_events: list):
        self.failed_events = failed_events
        super().__init__(f"{len(failed_events)} events failed in batch")


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

    Ported from joysafeter-kernel/src/event_buffer.rs.
    """

    def __init__(self, config: EventBatchConfig, runtime_config: Optional["RuntimeConfig"] = None):
        self._config = config
        self._runtime_config = runtime_config
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=config.max_size * 4)
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        self._lost_event_count = 0
        self._last_lost_event: dict[str, Any] | None = None

    def health_snapshot(self) -> dict[str, Any]:
        status = "degraded" if self._lost_event_count else "ok"
        return {
            "status": status,
            "enabled": self._config.enabled,
            "queue_size": self._queue.qsize(),
            "queue_max_size": self._queue.maxsize,
            "lost_event_count": self._lost_event_count,
            "last_lost_event": self._last_lost_event,
        }

    def _record_lost_event(self, event: BufferedEvent, error: Exception) -> None:
        self._lost_event_count += 1
        self._last_lost_event = {
            "session_id": str(event.session_id),
            "event_type": event.event_type,
            "event_id": str(event.id) if event.id else None,
            "error": str(error),
            "timestamp": time.time(),
        }

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
            try:
                await asyncio.wait_for(self._queue.put(_STOP_SENTINEL), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Could not enqueue stop sentinel (queue full), force cancelling")
                self._task.cancel()
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
            inserted = await self._write_single(event)
            if inserted is not None:
                await self._publish_inserted([inserted])
            return
        # Do not silently drop here. This sender is used as the durable fallback
        # for Redis Stream backpressure; if the in-memory queue is wedged, write
        # synchronously so callers either get durable persistence or a real error.
        try:
            await asyncio.wait_for(self._queue.put(event), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error(
                "Event batch queue full for 10s (size=%d), writing event synchronously for session %s",
                self._queue.qsize(),
                event.session_id,
            )
            inserted = await self._write_single(event)
            if inserted is not None:
                await self._publish_inserted([inserted])

    async def flush(self) -> None:
        """Flush buffered events and await acknowledgment from the flush loop.

        Mirrors Rust's EventBatchMessage::Flush(oneshot::Sender<()>) pattern:
        sends a _FlushRequest through the queue and waits for the loop to
        signal completion via the embedded ack event.
        """
        if not self._config.enabled or not self._task:
            return
        req = _FlushRequest()
        try:
            await asyncio.wait_for(self._queue.put(req), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Flush request could not be enqueued (queue full for 10s)")
            return
        await req.ack.wait()

    async def write_batch_now(self, events: list[BufferedEvent]) -> None:
        """Synchronously persist a batch and raise on failure."""
        await self._batch_insert(events)

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
            # Publish handled inside _batch_insert now (F4 regression fix)
        except _PartialBatchError as e:
            # Some sessions succeeded (already published inside _batch_insert),
            # only retry the failed ones individually
            logger.error(
                "Partial batch failure (%d events failed), retrying individually",
                len(e.failed_events),
            )
            await self._retry_individual(e.failed_events)
        except Exception as e:
            logger.error(
                "Batch insert failed (%d events), falling back to individual inserts: %s",
                count,
                e,
            )
            await self._retry_individual(buffer)

    async def _retry_individual(self, events: list[BufferedEvent]) -> None:
        """Retry failed events one by one with one retry attempt each."""
        for event in events:
            for attempt in range(2):
                try:
                    inserted = await self._write_single(event)
                    if inserted is not None:
                        try:
                            await self._publish_inserted([inserted])
                        except Exception as pub_err:
                            logger.warning("Realtime publish failed (event persisted): %s", pub_err)
                    break
                except Exception as inner:
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                    else:
                        self._record_lost_event(event, inner)
                        logger.error("Individual event insert failed after retry (event lost): %s", inner)

    async def _batch_insert(self, events: list[BufferedEvent]) -> list[BufferedEvent]:
        from collections import defaultdict

        groups: dict = defaultdict(list)
        for e in events:
            if _is_session_status_event(e.event_type):
                logger.warning(
                    "Skipping session status event in batch writer: session=%s event_type=%s",
                    e.session_id,
                    e.event_type,
                )
                continue
            groups[e.session_id].append(e)

        # F2 fix: process each session in its OWN transaction so that a slow
        # query on one session doesn't hold advisory locks for all others.
        # Sorted key order still prevents deadlocks between concurrent calls.
        all_inserted: list[BufferedEvent] = []
        failed_events: list[BufferedEvent] = []
        for session_id in sorted(groups.keys()):
            try:
                inserted = await self._insert_session_group(session_id, groups[session_id])
                all_inserted.extend(inserted)
            except Exception as e:
                logger.error(
                    "Batch insert failed for session %s (%d events): %s",
                    session_id,
                    len(groups[session_id]),
                    e,
                )
                failed_events.extend(groups[session_id])

        # Publish successfully inserted events immediately
        if all_inserted:
            try:
                await self._publish_inserted(all_inserted)
            except Exception as pub_err:
                logger.warning("Realtime publish failed for batch (events persisted): %s", pub_err)

        # If any sessions failed, raise so callers can handle:
        # - _flush_buffer will fall back to individual inserts for failed_events
        # - write_batch_now (stream consumer) will NOT ACK → Redis re-delivers
        if failed_events:
            raise _PartialBatchError(failed_events)
        return all_inserted

    async def _insert_session_group(self, session_id, events: list[BufferedEvent]) -> list[BufferedEvent]:
        """Insert events for a single session within its own transaction."""
        from sqlalchemy import func, select, text
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSessionEvent
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            lock_key = session_advisory_lock_key(session_id)
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

            result = await db.execute(
                select(func.coalesce(func.max(JoySafeterSessionEvent.seq), 0)).where(
                    JoySafeterSessionEvent.session_id == session_id
                )
            )
            base_seq = result.scalar()

            latest_result = await db.execute(
                select(JoySafeterSessionEvent)
                .where(JoySafeterSessionEvent.session_id == session_id)
                .order_by(JoySafeterSessionEvent.seq.desc(), JoySafeterSessionEvent.id.desc())
                .limit(1)
            )
            previous = latest_result.scalar_one_or_none()
            previous_event = (
                BufferedEvent(
                    session_id=previous.session_id,
                    event_type=previous.event_type,
                    payload=previous.payload or {},
                    seq=previous.seq,
                    id=previous.id,
                )
                if previous is not None
                else None
            )
            next_seq: int = base_seq or 0

            inserted: list[BufferedEvent] = []
            for e in events:
                if _is_duplicate_event(previous_event, e):
                    continue

                next_seq += 1
                values: dict[str, Any] = dict(
                    session_id=e.session_id,
                    event_type=e.event_type,
                    payload=e.payload,
                    seq=next_seq,
                )
                if e.id is not None:
                    values["id"] = e.id
                insert_stmt = pg_insert(JoySafeterSessionEvent).values(**values)
                if e.id is not None:
                    # The event id is the PK, so a redelivered id becomes a no-op
                    # instead of a PK violation that would abort the whole batch.
                    insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["id"])
                stmt = insert_stmt.returning(JoySafeterSessionEvent.id, JoySafeterSessionEvent.seq)
                row = (await db.execute(stmt)).first()
                if row is None:
                    # Duplicate id: nothing inserted, so don't consume the seq.
                    next_seq -= 1
                    continue

                inserted.append(
                    BufferedEvent(
                        session_id=e.session_id,
                        event_type=e.event_type,
                        payload=e.payload or {},
                        seq=row.seq,
                        id=row.id,
                    )
                )
                previous_event = e

            await db.commit()
            return inserted

    async def _write_single(self, event: BufferedEvent) -> BufferedEvent | None:
        if _is_session_status_event(event.event_type):
            logger.warning(
                "Skipping session status event in batch writer: session=%s event_type=%s",
                event.session_id,
                event.event_type,
            )
            return None

        from sqlalchemy import func, select, text
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSessionEvent
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            async with db.begin():
                lock_key = int.from_bytes(event.session_id.bytes[8:], "big", signed=True)
                await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

                result = await db.execute(
                    select(func.coalesce(func.max(JoySafeterSessionEvent.seq), 0)).where(
                        JoySafeterSessionEvent.session_id == event.session_id
                    )
                )
                base_seq = result.scalar()

                latest_result = await db.execute(
                    select(JoySafeterSessionEvent)
                    .where(JoySafeterSessionEvent.session_id == event.session_id)
                    .order_by(JoySafeterSessionEvent.seq.desc(), JoySafeterSessionEvent.id.desc())
                    .limit(1)
                )
                latest = latest_result.scalar_one_or_none()
                latest_event = (
                    BufferedEvent(
                        session_id=latest.session_id,
                        event_type=latest.event_type,
                        payload=latest.payload or {},
                        seq=latest.seq,
                        id=latest.id,
                    )
                    if latest is not None
                    else None
                )
                if _is_duplicate_event(latest_event, event):
                    return None

                seq = (base_seq or 0) + 1
                values: dict[str, Any] = dict(
                    session_id=event.session_id,
                    event_type=event.event_type,
                    payload=event.payload,
                    seq=seq,
                )
                if event.id is not None:
                    values["id"] = event.id
                insert_stmt = pg_insert(JoySafeterSessionEvent).values(**values)
                if event.id is not None:
                    # Idempotent on the event-id PK: a redelivery (or a row the
                    # SessionStateSubscriber already wrote) is a no-op, not a crash.
                    insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["id"])
                stmt = insert_stmt.returning(JoySafeterSessionEvent.id, JoySafeterSessionEvent.seq)
                row = (await db.execute(stmt)).first()
                if row is None:
                    return None
            return BufferedEvent(
                session_id=event.session_id,
                event_type=event.event_type,
                payload=event.payload or {},
                seq=row.seq,
                id=row.id,
            )

    async def _publish_inserted(self, events: list[BufferedEvent]) -> None:
        if not events:
            return
        from app.joysafeter_domain.services.joysafeter_session_service import publish_session_event_realtime

        for event in events:
            await publish_session_event_realtime(
                session_id=event.session_id,
                event_id=event.id,
                event_type=event.event_type,
                seq=event.seq,
                payload=event.payload,
            )
