"""
Subscriber protocol and phase enum.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.joysafeter_worker.events.envelope import ExecutionEventEnvelope


class SubscriberPhase(Enum):
    PERSIST = 1
    BROADCAST = 2


@runtime_checkable
class EventSubscriber(Protocol):
    name: str
    phase: SubscriberPhase

    async def handle(
        self,
        envelope: ExecutionEventEnvelope,
        db: Optional[AsyncSession] = None,
    ) -> None: ...


# ---------------------------------------------------------------------------
# JoySafeter event subscriber protocol
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from app.joysafeter_worker.events.envelope import JoySafeterEventEnvelope


@runtime_checkable
class JoySafeterEventSubscriber(Protocol):
    name: str
    phase: SubscriberPhase

    async def handle(self, envelope: JoySafeterEventEnvelope) -> None: ...
