"""Events infrastructure.

The active path is the Redis Stream consumer (``stream_consumer.EventStreamWorker``)
that persists session events emitted by the orchestrator-rs gRPC server.
The legacy in-process ``execution_event_bus`` and its subscribers were
removed along with the old DispatchService / ExecutionOrchestrator chain.
"""

from app.joysafeter_worker.events.event_types import ExecutionEventType

__all__ = [
    "ExecutionEventType",
]
