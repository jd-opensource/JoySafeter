from __future__ import annotations

from collections import defaultdict

import pytest

from app.everos.infra.ome.decorator import offline_strategy
from app.everos.infra.ome.events import BaseEvent
from app.everos.infra.ome.records import RunStatus
from app.everos.infra.ome.testing.harness import StrategyTestHarness
from app.everos.infra.ome.triggers import Immediate


class ReplayMemoryEvent(BaseEvent):
    session_id: str
    text: str


_attempts_by_event_id: defaultdict[str, int] = defaultdict(int)


@offline_strategy(
    name="extract_memory_for_replay",
    trigger=Immediate(on=[ReplayMemoryEvent]),
    emits=[],
    max_retries=0,
)
async def extract_memory_for_replay(event: ReplayMemoryEvent, ctx) -> None:
    _attempts_by_event_id[event.event_id] += 1
    if _attempts_by_event_id[event.event_id] == 1:
        raise ValueError("synthetic extraction failure")


@pytest.fixture(autouse=True)
def clear_replay_attempts():
    _attempts_by_event_id.clear()


async def test_ome_lists_dead_letters_by_optional_strategy_and_session_id():
    async with StrategyTestHarness() as h:
        h.register(extract_memory_for_replay)
        await h.start()
        await h.emit(ReplayMemoryEvent(session_id="session-a", text="first"))
        await h.emit(ReplayMemoryEvent(session_id="session-b", text="second"))
        await h.drain(timeout=5)

        records = await h._engine.list_dead_letters(  # noqa: SLF001
            strategy_name="extract_memory_for_replay",
            session_id="session-a",
            limit=10,
        )

    assert len(records) == 1
    assert records[0].status == RunStatus.DEAD_LETTER
    assert '"session-a"' in records[0].event_payload


async def test_ome_replays_dead_letter_with_original_event_payload():
    async with StrategyTestHarness() as h:
        h.register(extract_memory_for_replay)
        await h.start()
        event = ReplayMemoryEvent(session_id="session-replay", text="retry me")
        await h.emit(event)
        await h.drain(timeout=5)
        [dead] = await h._engine.list_dead_letters(  # noqa: SLF001
            strategy_name="extract_memory_for_replay",
            session_id="session-replay",
        )

        new_run_id = await h._engine.replay_dead_letter(dead.run_id)  # noqa: SLF001
        await h.drain(timeout=5)
        replayed = await h._engine.get_run_status(new_run_id)  # noqa: SLF001

    assert replayed is not None
    assert replayed.status == RunStatus.SUCCESS
    assert replayed.event_id == event.event_id
    assert replayed.event_payload == dead.event_payload
