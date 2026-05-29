"""
Subscriber protocol and phase enum.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.events.envelope import ExecutionEventEnvelope


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
# Conductor event subscriber protocol
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from app.core.events.envelope import ConductorEventEnvelope


@runtime_checkable
class ConductorEventSubscriber(Protocol):
    name: str
    phase: SubscriberPhase

    async def handle(self, envelope: ConductorEventEnvelope) -> None: ...
