"""
Canonical observation types — the single source of truth for Langfuse-aligned tracing.

Values MUST match Langfuse SDK enums exactly (uppercase). Used by ObservationCollector
to emit observation events to the trace tree.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.observation.collector import ObservationCollector


class ObservationType(StrEnum):
    SPAN       = "SPAN"
    EVENT      = "EVENT"
    GENERATION = "GENERATION"
    AGENT      = "AGENT"
    TOOL       = "TOOL"
    CHAIN      = "CHAIN"
    RETRIEVER  = "RETRIEVER"
    EMBEDDING  = "EMBEDDING"
    EVALUATOR  = "EVALUATOR"
    GUARDRAIL  = "GUARDRAIL"


class ObservationLevel(StrEnum):
    DEBUG   = "DEBUG"
    DEFAULT = "DEFAULT"
    WARNING = "WARNING"
    ERROR   = "ERROR"


@dataclass
class SpanHandle:
    observation_id: uuid.UUID
    collector: ObservationCollector

    async def child_span(self, observation_type: ObservationType, name: str, **kwargs: Any) -> SpanHandle:
        return await self.collector.start_span(observation_type, name, parent_id=self.observation_id, **kwargs)

    async def record_generation(self, name: str, **kwargs: Any) -> uuid.UUID:
        return await self.collector.record_generation(name, parent_id=self.observation_id, **kwargs)

    async def record_tool(self, name: str, **kwargs: Any) -> uuid.UUID:
        return await self.collector.record_tool(name, parent_id=self.observation_id, **kwargs)

    async def record_event(self, name: str, **kwargs: Any) -> uuid.UUID:
        return await self.collector.record_event(name, parent_id=self.observation_id, **kwargs)

    async def end(self, **kwargs: Any) -> None:
        await self.collector.end_span(self, **kwargs)
