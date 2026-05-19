"""Observation collector port — type-safe interface for ExecutionContext.collector."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ObservationCollectorPort(Protocol):
    """Port for observation tracing within an execution.

    Implemented by: core/observation/collector.py (ObservationCollector)
    Used by: engines via ExecutionContext.collector
    """

    def start_span(self, obs_type: Any, name: str, **kw: Any) -> Any: ...
    def start_agent(self, name: str, **kw: Any) -> Any: ...
    def record_event(self, name: str, **kw: Any) -> Any: ...
    def create_langchain_handler(self) -> Any: ...
    async def finalize(self, status: str = "complete") -> None: ...
