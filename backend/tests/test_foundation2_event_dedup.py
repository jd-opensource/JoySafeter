"""Foundation 2 (effectively-once) — idempotent session-event insert.

The event pipeline is at-least-once: a Redis-Stream redelivery (after a crash
between the DB write and the xack) — or, once the outbox is wired in, the
relay's at-least-once publish — can hand the worker the same event id twice.
Dedup must therefore be owned by the DB unique constraint (the event id is the
``joysafeter_session_events`` primary key), not an application-level
check-then-insert: within a single flush the pending row is invisible to a
follow-up ``exists()`` query (autoflush is off), so two same-id events in one
batch slip past the precheck and blow up the whole batch on the commit's PK
violation. An ``INSERT ... ON CONFLICT (id) DO NOTHING`` makes redelivery a
no-op instead.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import (
    JoySafeterSession,
    JoySafeterSessionEvent,
)
from app.joysafeter_worker.events.batch_writer import (
    BufferedEvent,
    EventBatchConfig,
    EventBatchSender,
)


@pytest_asyncio.fixture
async def session_id(db_session) -> uuid.UUID:
    agent = JoySafeterAgent(name=f"dedup-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    sess = JoySafeterSession(agent_id=agent.id)
    db_session.add(sess)
    await db_session.commit()
    await db_session.refresh(sess)
    return sess.id


@pytest.mark.asyncio
async def test_duplicate_event_id_within_one_batch_inserts_once(postgres_url, db_session, session_id, monkeypatch):
    """Two events sharing an id in the SAME batch: the constraint must dedup it
    to one row instead of the commit's PK violation losing the entire batch."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    dup_id = uuid.uuid4()
    events = [
        BufferedEvent(session_id=session_id, event_type="agent.message", payload={"i": 1}, seq=0, id=dup_id),
        BufferedEvent(session_id=session_id, event_type="agent.message", payload={"i": 2}, seq=0, id=dup_id),
    ]
    sender = EventBatchSender(EventBatchConfig())
    try:
        inserted = await sender._insert_session_group(session_id, events)
    finally:
        await engine.dispose()

    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterSessionEvent).where(JoySafeterSessionEvent.id == dup_id)
    )
    assert total == 1, "a duplicate event id in one batch must persist exactly one row"
    assert len(inserted) == 1, "only the first occurrence of the id should be reported inserted"


@pytest.mark.asyncio
async def test_redelivered_event_id_across_batches_inserts_once(postgres_url, db_session, session_id, monkeypatch):
    """At-least-once transport: the same event id delivered in a later batch
    (a crash-then-redeliver, or the outbox relay re-publishing) must not create
    a second row."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    eid = uuid.uuid4()
    ev = BufferedEvent(session_id=session_id, event_type="agent.message", payload={"i": 1}, seq=0, id=eid)
    sender = EventBatchSender(EventBatchConfig())
    try:
        first = await sender._insert_session_group(session_id, [ev])
        second = await sender._insert_session_group(session_id, [ev])
    finally:
        await engine.dispose()

    assert len(first) == 1, "the first delivery inserts the event"
    assert second == [], "a redelivery of the same id inserts nothing"

    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterSessionEvent).where(JoySafeterSessionEvent.id == eid)
    )
    assert total == 1, "redelivery across batches must still leave exactly one row"


@pytest.mark.asyncio
async def test_distinct_events_get_gapless_seq_around_a_duplicate(postgres_url, db_session, session_id, monkeypatch):
    """A duplicate in the middle of a batch must not consume a seq number, so
    the surviving events stay densely ordered (1, 2, 3) — and id-less events
    still insert normally."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    dup = uuid.uuid4()
    events = [
        BufferedEvent(session_id=session_id, event_type="agent.message", payload={"n": 1}, seq=0, id=dup),
        BufferedEvent(session_id=session_id, event_type="agent.message", payload={"n": 2}, seq=0, id=dup),  # dup
        BufferedEvent(session_id=session_id, event_type="agent.message", payload={"n": 3}, seq=0, id=uuid.uuid4()),
        BufferedEvent(session_id=session_id, event_type="agent.message", payload={"n": 4}, seq=0, id=None),  # id-less
    ]
    sender = EventBatchSender(EventBatchConfig())
    try:
        inserted = await sender._insert_session_group(session_id, events)
    finally:
        await engine.dispose()

    assert [e.seq for e in inserted] == [1, 2, 3], "seq must be dense despite the skipped duplicate"

    all_seqs = list(
        (
            await db_session.execute(
                select(JoySafeterSessionEvent.seq)
                .where(JoySafeterSessionEvent.session_id == session_id)
                .order_by(JoySafeterSessionEvent.seq)
            )
        )
        .scalars()
        .all()
    )
    assert all_seqs == [1, 2, 3], "exactly three rows with a gapless sequence must persist"


@pytest.mark.asyncio
async def test_batch_writer_skips_session_status_events_without_consuming_seq(
    postgres_url, db_session, session_id, monkeypatch
):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    events = [
        BufferedEvent(
            session_id=session_id,
            event_type="session.status_idle",
            payload={"task_id": str(uuid.uuid4()), "stop_reason": {"type": "end_turn"}},
            seq=0,
            id=uuid.uuid4(),
        ),
        BufferedEvent(session_id=session_id, event_type="agent.message", payload={"content": "done"}, seq=0),
    ]
    sender = EventBatchSender(EventBatchConfig())
    try:
        inserted = await sender._batch_insert(events)
    finally:
        await engine.dispose()

    assert [(event.event_type, event.seq) for event in inserted] == [("agent.message", 1)]
    rows = (
        await db_session.execute(
            select(JoySafeterSessionEvent.event_type, JoySafeterSessionEvent.seq)
            .where(JoySafeterSessionEvent.session_id == session_id)
            .order_by(JoySafeterSessionEvent.seq.asc())
        )
    ).all()
    assert rows == [("agent.message", 1)]


@pytest.mark.asyncio
async def test_write_single_is_idempotent_on_event_id(postgres_url, db_session, session_id, monkeypatch):
    """The unbatched path (_write_single) must also dedup a redelivered id."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr("app.joysafeter_shared.database.AsyncSessionLocal", factory)

    eid = uuid.uuid4()
    ev = BufferedEvent(session_id=session_id, event_type="agent.message", payload={"x": 1}, seq=0, id=eid)
    sender = EventBatchSender(EventBatchConfig())
    try:
        first = await sender._write_single(ev)
        second = await sender._write_single(ev)
    finally:
        await engine.dispose()

    assert first is not None and first.id == eid, "first write persists the event"
    assert second is None, "a redelivered id must be a no-op in the single-write path"

    total = await db_session.scalar(
        select(func.count()).select_from(JoySafeterSessionEvent).where(JoySafeterSessionEvent.id == eid)
    )
    assert total == 1, "the single-write path must leave exactly one row for a repeated id"
