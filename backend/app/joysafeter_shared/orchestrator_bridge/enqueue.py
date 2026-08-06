"""Canonical task enqueue contract.

Handing a persisted task to the Rust orchestrator is a single Redis push onto
the global queue. This lives in the shared layer so every submitter — the HTTP
task endpoint, the session follow-up path, and the scheduler — enqueues through
one definition and cannot drift from the contract the orchestrator expects
(``joysafeter_orchestrator_rs`` pops this list and claims the task by id).
"""

import uuid

from app.joysafeter_shared.ids import EntityId

GLOBAL_QUEUE_KEY = "joysafeter:global_queue"


async def enqueue_joysafeter_task(task_id: uuid.UUID | EntityId) -> None:
    """Enqueue a persisted (pending) task for the Rust orchestrator scheduler."""
    from app.joysafeter_shared.cache.redis import RedisClient

    redis = RedisClient.get_client()
    if redis is None:
        raise RuntimeError("Redis unavailable; cannot enqueue task to global queue")
    # The Rust orchestrator pops this list and parses a bare UUID; a typed TaskId
    # must degrade to its raw uuid at this cross-language boundary (never task_<uuid>).
    raw_id = task_id.uuid if isinstance(task_id, EntityId) else task_id
    await redis.rpush(GLOBAL_QUEUE_KEY, str(raw_id))
