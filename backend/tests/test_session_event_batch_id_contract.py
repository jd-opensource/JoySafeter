import uuid

import pytest

from app.joysafeter_domain.services import joysafeter_session_service as session_service_module
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_shared.ids import SessionId

pytestmark = pytest.mark.no_db


class _NoDbWork:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"invalid session_id reached database work: {name}")


class _RecordingDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _value: object) -> None:
        return None


@pytest.mark.asyncio
async def test_batch_insert_session_events_rejects_string_session_id_before_db_work() -> None:
    service = SessionService(_NoDbWork())  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="session_id must be a SessionId or UUID"):
        await service.batch_insert_session_events(
            [{"session_id": str(SessionId.new()), "event_type": "user.message", "payload": {}}]  # type: ignore[list-item]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_session_id", [SessionId.new(), uuid.uuid4()])
async def test_batch_insert_session_events_keeps_typed_and_native_uuid_inputs_explicit(
    raw_session_id: SessionId | uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _RecordingDb()
    service = SessionService(db)  # type: ignore[arg-type]
    locked: list[SessionId] = []

    async def lock_event_sequence(session_id: SessionId) -> None:
        locked.append(session_id)

    async def max_seq_locked(_session_id: SessionId) -> int:
        return 0

    async def publish_session_event_realtime(**_event: object) -> None:
        return None

    monkeypatch.setattr(service, "_lock_event_sequence", lock_event_sequence)
    monkeypatch.setattr(service, "_max_seq_locked", max_seq_locked)
    monkeypatch.setattr(session_service_module, "publish_session_event_realtime", publish_session_event_realtime)

    created = await service.batch_insert_session_events(
        [{"session_id": raw_session_id, "event_type": "user.message", "payload": {}}]
    )

    expected_session_id = (
        raw_session_id if isinstance(raw_session_id, SessionId) else SessionId.from_uuid(raw_session_id)
    )
    assert locked == [expected_session_id]
    assert created[0].session_id == expected_session_id
    assert db.added == created
    assert db.committed is True
