import uuid

import pytest

from app.joysafeter_api.api.v1.tasks import _stream_via_redis, _task_stream_error_payload

pytestmark = pytest.mark.no_db


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, *args, **kwargs) -> None:
        self.closed = True


class _FailingPubSub:
    async def subscribe(self, channel: str) -> None:
        raise RuntimeError("redis unavailable")

    async def unsubscribe(self, channel: str) -> None:
        return None

    async def close(self) -> None:
        return None


class _FailingRedis:
    def pubsub(self):
        return _FailingPubSub()


def test_task_stream_error_payload_uses_async_error_contract():
    task_id = uuid.uuid4()

    payload = _task_stream_error_payload(
        code="TASK_STREAM_TASK_NOT_SCHEDULED",
        message="Task is not scheduled yet",
        task_id=task_id,
        source="runtime",
        retryable=True,
        user_action="retry",
    )

    assert payload == {
        "type": "error",
        "code": "TASK_STREAM_TASK_NOT_SCHEDULED",
        "message": "Task is not scheduled yet",
        "data": {"task_id": str(task_id)},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }


@pytest.mark.asyncio
async def test_redis_task_stream_failure_sends_structured_error_before_close():
    task_id = uuid.uuid4()
    websocket = _FakeWebSocket()

    await _stream_via_redis(websocket, task_id, _FailingRedis())

    assert websocket.sent == [
        {
            "type": "error",
            "code": "TASK_STREAM_REDIS_FAILED",
            "message": "Cross-instance task stream failed",
            "data": {"task_id": str(task_id)},
            "source": "runtime",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    ]
    assert websocket.closed is True
