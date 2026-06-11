"""Subscriber protocol for JoySafeter runner events."""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope


class SubscriberPhase(Enum):
    PERSIST = 1
    BROADCAST = 2


@runtime_checkable
class JoySafeterEventSubscriber(Protocol):
    name: str
    phase: SubscriberPhase

    async def handle(self, envelope: JoySafeterEventEnvelope) -> None: ...


__all__ = ["JoySafeterEventSubscriber", "SubscriberPhase"]
