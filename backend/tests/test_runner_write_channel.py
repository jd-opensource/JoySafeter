"""Single-writer discipline for the runner gRPC stream.

grpc.aio forbids concurrent writes to one stream. Historically the orchestrator
wrote to `bridge.runner_stream` from several coroutines (the gRPC handler loop
plus API/relay/shutdown paths) — a latent interleave/corruption hazard — while a
parallel `runner_tx` queue had no consumer at all (silently dropped).

`bridge.write_to_runner(msg)` is now the ONE way to send to the runner: it holds
a per-bridge lock so writes can never overlap, and returns False (drop) when the
stream isn't connected instead of raising.
"""

import asyncio
import uuid

import pytest

from app.joysafeter_orchestrator.kernel.sandbox_bridge import SandboxBridge


class _RecordingStream:
    def __init__(self):
        self.writes: list = []

    async def write(self, msg):
        self.writes.append(msg)


class _OverlapDetectingStream:
    """Fails the serialization invariant if two writes are ever in flight."""

    def __init__(self):
        self.in_flight = 0
        self.max_in_flight = 0
        self.completed = 0

    async def write(self, msg):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.005)  # hold the "write" open to expose any overlap
        self.completed += 1
        self.in_flight -= 1


@pytest.mark.asyncio
async def test_write_to_runner_delivers_when_connected():
    bridge = SandboxBridge(uuid.uuid4(), "ext-1")
    stream = _RecordingStream()
    bridge.runner_stream = stream

    ok = await bridge.write_to_runner("hello")

    assert ok is True
    assert stream.writes == ["hello"]


@pytest.mark.asyncio
async def test_write_to_runner_drops_when_disconnected():
    bridge = SandboxBridge(uuid.uuid4(), "ext-1")
    bridge.runner_stream = None

    ok = await bridge.write_to_runner("hello")

    assert ok is False, "a write with no connected stream must be dropped, not raise"


@pytest.mark.asyncio
async def test_concurrent_writes_are_serialized():
    bridge = SandboxBridge(uuid.uuid4(), "ext-1")
    stream = _OverlapDetectingStream()
    bridge.runner_stream = stream

    await asyncio.gather(*(bridge.write_to_runner(i) for i in range(10)))

    assert stream.completed == 10, "every write must complete"
    assert stream.max_in_flight == 1, "writes to the gRPC stream must never overlap"
