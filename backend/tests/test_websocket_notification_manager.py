import json
from typing import get_type_hints

import pytest

from app.joysafeter_api.websocket.notification_manager import NotificationManager
from app.joysafeter_shared.ids import UserId

pytestmark = pytest.mark.no_db


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


def test_notification_manager_public_contract_uses_user_id():
    assert get_type_hints(NotificationManager.connect)["user_id"] is UserId
    assert get_type_hints(NotificationManager.send_to_user)["user_id"] is UserId
    assert get_type_hints(NotificationManager.send_to_users)["user_ids"] == list[UserId]
    assert get_type_hints(NotificationManager.send_to_users)["return"] == dict[UserId, int]
    assert get_type_hints(NotificationManager.is_user_online)["user_id"] is UserId
    assert get_type_hints(NotificationManager.get_online_users)["return"] == list[UserId]
    assert get_type_hints(NotificationManager.get_user_connection_count)["user_id"] is UserId


@pytest.mark.asyncio
async def test_notification_manager_routes_and_cleans_up_by_typed_user_id():
    manager = NotificationManager()
    first_user_id = UserId.new()
    second_user_id = UserId.new()
    first_websocket = _FakeWebSocket()
    second_websocket = _FakeWebSocket()

    await manager.connect(first_websocket, first_user_id, already_accepted=False)
    await manager.connect(second_websocket, second_user_id, already_accepted=False)

    results = await manager.send_to_users(
        [first_user_id, second_user_id],
        {"type": "account_updated"},
    )

    assert first_websocket.accepted is True
    assert second_websocket.accepted is True
    assert results == {first_user_id: 1, second_user_id: 1}
    assert manager.get_online_users() == [first_user_id, second_user_id]
    assert first_websocket.sent[-1]["type"] == "account_updated"
    assert second_websocket.sent[-1]["type"] == "account_updated"

    manager.disconnect(first_websocket)

    assert manager.is_user_online(first_user_id) is False
    assert manager.is_user_online(second_user_id) is True
    assert manager.get_user_connection_count(first_user_id) == 0
    assert manager.get_user_connection_count(second_user_id) == 1
