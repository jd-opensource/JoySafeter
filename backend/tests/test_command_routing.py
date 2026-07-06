"""Cross-instance command routing — remote input/cancel delivery.

A cancel/input request can land on any orchestrator instance, but only the
instance that OWNS the sandbox holds the gRPC bridge to it. The owner is
resolved and the command is published to `joysafeter:cmd:{owner}`; the owning
instance's CommandListener then delivers it to the local bridge.

The delivery must land on the channels the runner loops actually consume:
  - input  -> bridge._control_queue (drained by the gRPC task loop on
              confirmation, and by the in-process TaskRunner control loop) and
              bridge.confirmation_event.
  - cancel -> bridge._cancel_event (watched by both loops to write CancelTask).

bridge.runner_tx has NO consumer, so routing a command there silently drops it
(the historical bug: remote HITL input looked delivered but never reached the
agent).
"""

import json
import uuid

import pytest

from app.joysafeter_orchestrator.kernel.command_listener import CommandListener
from app.joysafeter_orchestrator.kernel.sandbox_bridge import SandboxBridge


class _FakeRegistry:
    def __init__(self, bridge: SandboxBridge | None):
        self._bridge = bridge

    async def get(self, sandbox_id: uuid.UUID) -> SandboxBridge | None:
        return self._bridge


def _listener(bridge: SandboxBridge | None) -> CommandListener:
    return CommandListener(redis_client=None, coordinator=None, bridge_registry=_FakeRegistry(bridge))


class _FakeRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, dict]] = []
        self.expired: list[tuple[str, int]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, json.loads(value)))

    async def expire(self, key: str, seconds: int) -> None:
        self.expired.append((key, seconds))


def _listener_with_redis(bridge: SandboxBridge | None, redis: _FakeRedis) -> CommandListener:
    return CommandListener(redis_client=redis, coordinator=None, bridge_registry=_FakeRegistry(bridge))


@pytest.mark.asyncio
async def test_remote_input_reaches_the_control_queue():
    sandbox_id = uuid.uuid4()
    bridge = SandboxBridge(sandbox_id, "ext-1")
    listener = _listener(bridge)

    await listener._dispatch({"type": "input", "sandbox_id": str(sandbox_id), "content": "approve"})

    assert bridge._control_queue.get_nowait() == "approve", "remote input must land on the queue the runner drains"
    assert bridge.confirmation_event.is_set(), "remote input must wake the confirmation drain"
    assert not hasattr(bridge, "runner_tx"), "the dead runner_tx queue must no longer exist"


@pytest.mark.asyncio
async def test_remote_cancel_sets_cancel_event():
    sandbox_id = uuid.uuid4()
    bridge = SandboxBridge(sandbox_id, "ext-1")
    listener = _listener(bridge)

    await listener._dispatch({"type": "cancel", "sandbox_id": str(sandbox_id)})

    assert bridge._cancel_event.is_set(), "remote cancel must set the _cancel_event both runner loops watch"


@pytest.mark.asyncio
async def test_unknown_sandbox_is_ignored_without_error():
    listener = _listener(None)
    # No bridge for this sandbox (this instance is not the owner) — must no-op.
    await listener._dispatch({"type": "input", "sandbox_id": str(uuid.uuid4()), "content": "x"})


@pytest.mark.asyncio
async def test_remote_input_ack_confirms_execution():
    sandbox_id = uuid.uuid4()
    bridge = SandboxBridge(sandbox_id, "ext-1")
    redis = _FakeRedis()
    listener = _listener_with_redis(bridge, redis)

    await listener._dispatch(
        {
            "type": "input",
            "sandbox_id": str(sandbox_id),
            "content": "approve",
            "command_id": "cmd-1",
            "ack_key": "joysafeter:cmd_ack:cmd-1",
        }
    )

    assert redis.rpushed == [("joysafeter:cmd_ack:cmd-1", {"command_id": "cmd-1", "ok": True})]
    assert redis.expired == [("joysafeter:cmd_ack:cmd-1", 30)]


@pytest.mark.asyncio
async def test_remote_input_ack_reports_missing_bridge():
    redis = _FakeRedis()
    listener = _listener_with_redis(None, redis)

    await listener._dispatch(
        {
            "type": "input",
            "sandbox_id": str(uuid.uuid4()),
            "content": "approve",
            "command_id": "cmd-2",
            "ack_key": "joysafeter:cmd_ack:cmd-2",
        }
    )

    assert redis.rpushed == [("joysafeter:cmd_ack:cmd-2", {"command_id": "cmd-2", "ok": False})]


@pytest.mark.asyncio
async def test_remote_command_refuses_untrusted_ack_key():
    sandbox_id = uuid.uuid4()
    bridge = SandboxBridge(sandbox_id, "ext-1")
    redis = _FakeRedis()
    listener = _listener_with_redis(bridge, redis)

    await listener._dispatch(
        {
            "type": "input",
            "sandbox_id": str(sandbox_id),
            "content": "approve",
            "command_id": "cmd-3",
            "ack_key": "attacker:list",
        }
    )

    assert redis.rpushed == []
    assert bridge._control_queue.get_nowait() == "approve"
