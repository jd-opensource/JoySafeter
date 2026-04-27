"""
WebSocketSubscriber — Phase 2.

Broadcasts events to frontend clients via the existing subscription manager.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.envelope import ExecutionEventEnvelope
from app.core.events.event_types import ExecutionEventType
from app.core.events.subscriber import SubscriberPhase
from app.websocket.execution_subscription_manager import execution_subscription_manager


class WebSocketSubscriber:
    name = "websocket"
    phase = SubscriberPhase.BROADCAST

    async def handle(
        self,
        envelope: ExecutionEventEnvelope,
        db: Optional[AsyncSession] = None,
    ) -> None:
        eid = str(envelope.execution_id)

        if envelope.event_type == ExecutionEventType.EXECUTION_COMPLETED:
            payload = {
                "type": "execution_completed",
                "execution_id": eid,
                "run_id": str(envelope.run_id),
                "status": envelope.terminal_status,
            }
            if envelope.terminal_status == "failed":
                if envelope.error is None:
                    raise RuntimeError("failed execution_completed envelope missing error")
                payload["error"] = envelope.error
            await execution_subscription_manager.broadcast_event(eid, payload)
            execution_subscription_manager.remove_execution(eid)
        else:
            await execution_subscription_manager.broadcast_event(
                eid,
                {
                    "type": "event",
                    "execution_id": eid,
                    "seq": envelope.seq,
                    "event_type": envelope.event_type,
                    "payload": envelope.payload,
                    "created_at": envelope.created_at.isoformat() if envelope.created_at else None,
                },
            )
