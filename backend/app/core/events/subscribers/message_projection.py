"""
MessageProjectionSubscriber — Phase 2.

Projects ExecutionEvents into ThreadMessage (materialized view).

- user_message events → ThreadMessage(role=user)
- execution_completed events → ThreadMessage(role=assistant or system)

ThreadMessage is a read-optimized projection, NOT a write target.
The single source of truth is ExecutionEvent.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.envelope import ExecutionEventEnvelope
from app.core.events.subscriber import SubscriberPhase

PROJECTED_EVENT_TYPES = {"user_message", "execution_completed"}


class MessageProjectionSubscriber:
    name = "message_projection"
    phase = SubscriberPhase.BROADCAST

    async def handle(
        self,
        envelope: ExecutionEventEnvelope,
        db: Optional[AsyncSession] = None,
    ) -> None:
        if envelope.event_type not in PROJECTED_EVENT_TYPES:
            return
        if not envelope.thread_id:
            return

        from app.core.database import AsyncSessionLocal
        from app.models.thread import ThreadMessage

        async with AsyncSessionLocal() as session:
            if envelope.event_type == "user_message":
                msg = ThreadMessage(
                    thread_id=envelope.thread_id,
                    role="user",
                    content=envelope.payload,
                    run_id=envelope.run_id,
                    execution_id=envelope.execution_id,
                )
                session.add(msg)
                await session.commit()
                logger.debug(
                    f"[MessageProjection] Projected user_message to thread {envelope.thread_id}"
                )

            elif envelope.event_type == "execution_completed":
                status = envelope.terminal_status or "unknown"

                if status == "succeeded" and envelope.result_summary:
                    msg = ThreadMessage(
                        thread_id=envelope.thread_id,
                        role="assistant",
                        content={"text": envelope.result_summary},
                        run_id=envelope.run_id,
                        execution_id=envelope.execution_id,
                    )
                elif status in ("failed", "cancelled"):
                    error_detail = envelope.payload.get("error", "")
                    text = (
                        f"Execution {status}"
                        + (f": {error_detail}" if error_detail else "")
                    )
                    msg = ThreadMessage(
                        thread_id=envelope.thread_id,
                        role="system",
                        content={"text": text},
                        run_id=envelope.run_id,
                        execution_id=envelope.execution_id,
                    )
                else:
                    return

                session.add(msg)
                await session.commit()
                logger.debug(
                    f"[MessageProjection] Projected {status} reply to thread {envelope.thread_id}"
                )
