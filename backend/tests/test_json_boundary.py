import json
from datetime import date, datetime, timezone
from enum import Enum

import pytest

from app.joysafeter_api.websocket.notification_manager import NotificationManager
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.common.exceptions import create_error_response
from app.joysafeter_shared.ids import AgentId, SessionId
from app.joysafeter_shared.json_boundary import JsonBoundaryTypeError, normalize_json_value

pytestmark = pytest.mark.no_db


class _State(str, Enum):
    READY = "ready"


def test_normalize_json_value_converts_only_supported_boundary_types() -> None:
    agent_id = AgentId.new()
    session_id = SessionId.new()
    occurred_at = datetime(2026, 8, 25, 9, 30, tzinfo=timezone.utc)

    assert normalize_json_value(
        {
            "agent_id": agent_id,
            "nested": [session_id, _State.READY, date(2026, 8, 25), occurred_at],
        }
    ) == {
        "agent_id": str(agent_id),
        "nested": [str(session_id), "ready", "2026-08-25", "2026-08-25T09:30:00+00:00"],
    }


@pytest.mark.parametrize("value", [object(), {1: "non-string-key"}, float("nan"), float("inf")])
def test_normalize_json_value_rejects_unsupported_values(value: object) -> None:
    with pytest.raises(JsonBoundaryTypeError):
        normalize_json_value(value)


def test_error_response_serializes_entity_ids() -> None:
    session_id = SessionId.new()

    response = create_error_response(
        status_code=400,
        error=InvalidRequestError("bad request", data={"session_id": session_id}),
    )

    assert json.loads(response.body)["data"] == {"session_id": str(session_id)}


@pytest.mark.asyncio
async def test_websocket_boundary_serializes_entity_ids() -> None:
    class _WebSocket:
        payload: str | None = None

        async def send_text(self, payload: str) -> None:
            self.payload = payload

    websocket = _WebSocket()
    agent_id = AgentId.new()

    assert await NotificationManager().send_to_connection(websocket, {"agent_id": agent_id})
    assert websocket.payload == f'{{"agent_id": "{agent_id}"}}'
