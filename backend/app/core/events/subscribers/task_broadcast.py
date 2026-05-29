from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.core.events.envelope import ConductorEventEnvelope
from app.core.events.subscriber import SubscriberPhase
from app.core.sandbox_bridge import SandboxBridge, SandboxBridgeRegistry, WsOutMessage

logger = logging.getLogger(__name__)


class TaskBroadcastSubscriber:
    """Phase 2: broadcast events to task-level WebSocket subscribers and Redis."""

    name = "task_broadcast"
    phase = SubscriberPhase.BROADCAST

    def __init__(self, bridge_registry: SandboxBridgeRegistry) -> None:
        self._bridge_registry = bridge_registry

    async def handle(self, envelope: ConductorEventEnvelope) -> None:
        if envelope.task_id is None or envelope.task_broadcast_payload is None:
            return

        if envelope.sandbox_id is None:
            return

        bridge = await self._bridge_registry.get(envelope.sandbox_id)
        if bridge is None:
            return

        ws_msg = WsOutMessage(
            type="event",
            payload=envelope.task_broadcast_payload,
        )
        await bridge.broadcast_to_task(envelope.task_id, ws_msg)

        from app.core.lifespan import get_redis_coordinator
        coordinator = get_redis_coordinator()
        if coordinator:
            await coordinator.publish_event(
                envelope.task_id,
                json.dumps({"type": ws_msg.type, **ws_msg.payload}),
            )
