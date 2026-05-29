from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from app.conductor.events.envelope import ConductorEventEnvelope


class SubscriberPhase(Enum):
    PERSIST = 1
    BROADCAST = 2


@runtime_checkable
class ConductorEventSubscriber(Protocol):
    name: str
    phase: SubscriberPhase

    async def handle(self, envelope: ConductorEventEnvelope) -> None: ...
