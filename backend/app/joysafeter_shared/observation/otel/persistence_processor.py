"""PersistenceProcessor -- global SpanProcessor that routes finished spans to per-execution buckets."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable, Coroutine

from loguru import logger
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from app.joysafeter_shared.observation.model import Observation
from app.joysafeter_shared.observation.otel.processor_base import (
    BucketRegistry,
    build_cost,
    build_usage,
    ns_to_datetime,
    parse_json_attr,
)
from app.joysafeter_shared.observation.types import ObservationLevel, ObservationType

_SENTINEL = object()

_EMPTY_AGGREGATES: dict = {
    "total_tokens": 0,
    "total_cost": 0.0,
    "total_observations": 0,
    "has_error": False,
}


class _ExecutionBucket:
    __slots__ = (
        "execution_id",
        "trace_id",
        "project_id",
        "created_at",
        "_db_session_factory",
        "_loop",
        "_queue",
        "_lock",
        "_otel_span_id_to_observation_id",
        "_total_tokens",
        "_total_cost",
        "_observation_count",
        "_has_error",
        "_drain_future",
        "_max_batch",
        "_max_wait_ms",
    )

    def __init__(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        project_id: str,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        event_loop: asyncio.AbstractEventLoop,
        *,
        max_batch: int = 10,
        max_wait_ms: int = 300,
        max_buffer_size: int = 1000,
    ) -> None:
        self.execution_id = execution_id
        self.trace_id = trace_id
        self.project_id = project_id
        self.created_at = time.monotonic()
        self._db_session_factory = db_session_factory
        self._loop = event_loop
        self._max_batch = max_batch
        self._max_wait_ms = max_wait_ms

        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_buffer_size)
        self._lock = threading.Lock()
        self._otel_span_id_to_observation_id: dict[int, uuid.UUID] = {}

        self._total_tokens = 0
        self._total_cost = 0.0
        self._observation_count = 0
        self._has_error = False

        self._drain_future = asyncio.run_coroutine_threadsafe(self._drain_loop(), self._loop)

    def on_start(self, span: ReadableSpan) -> None:
        obs_id_str = span.attributes.get("observation.id")  # type: ignore[union-attr]
        if obs_id_str:
            with self._lock:
                self._otel_span_id_to_observation_id[span.context.span_id] = uuid.UUID(  # type: ignore[union-attr]
                    str(obs_id_str)
                )

    def on_end(self, span: ReadableSpan) -> None:
        attrs = span.attributes or {}
        obs_id_str = attrs.get("observation.id")
        if not obs_id_str:
            return

        obs_id = uuid.UUID(str(obs_id_str))

        # Single lock acquisition for: parent lookup, aggregate update, span-id cleanup
        with self._lock:
            parent_obs_id: uuid.UUID | None = None
            if span.parent:
                parent_obs_id = self._otel_span_id_to_observation_id.get(span.parent.span_id)

            usage_total = attrs.get("llm.usage.total", 0)
            if usage_total:
                self._total_tokens += int(usage_total)  # type: ignore[arg-type]
            cost_total = attrs.get("llm.cost.total", 0.0)
            if cost_total:
                self._total_cost += float(cost_total)  # type: ignore[arg-type]
            self._observation_count += 1
            if attrs.get("observation.level") == ObservationLevel.ERROR.value:
                self._has_error = True

            if hasattr(span, "context") and span.context:
                self._otel_span_id_to_observation_id.pop(span.context.span_id, None)

        obs = Observation(
            id=obs_id,
            trace_id=self.trace_id,
            execution_id=self.execution_id,
            project_id=self.project_id,
            parent_observation_id=parent_obs_id,
            type=str(attrs.get("observation.type", ObservationType.SPAN.value)),
            name=span.name,
            level=str(attrs.get("observation.level", ObservationLevel.DEFAULT.value)),
            status_message=attrs.get("observation.status_message"),  # type: ignore[arg-type]
            start_time=ns_to_datetime(span.start_time),
            end_time=ns_to_datetime(span.end_time),
            input=parse_json_attr(attrs.get("observation.input")),
            output=parse_json_attr(attrs.get("observation.output")),
            meta=parse_json_attr(attrs.get("observation.metadata")),
            model=attrs.get("llm.model"),  # type: ignore[arg-type]
            model_parameters=parse_json_attr(attrs.get("llm.parameters")),
            usage_details=build_usage(attrs),
            cost_details=build_cost(attrs),
            completion_start_time=self._parse_iso_attr(attrs, "llm.completion_start_time"),
            prompt_name=attrs.get("llm.prompt.name"),  # type: ignore[arg-type]
            prompt_version=self._safe_int(attrs.get("llm.prompt.version")),
            tool_calls=parse_json_attr(attrs.get("tool.calls")),
            tool_definitions=parse_json_attr(attrs.get("tool.definitions")),
        )

        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, obs)
        except (asyncio.QueueFull, RuntimeError):
            logger.warning("Observation queue full, dropping observation {}", obs_id)

        for event in span.events:
            if event.name.startswith("stream."):
                continue
            event_obs = Observation(
                id=uuid.uuid4(),
                trace_id=self.trace_id,
                execution_id=self.execution_id,
                project_id=self.project_id,
                parent_observation_id=obs_id,
                type=ObservationType.EVENT.value,
                name=event.name,
                level=ObservationLevel.DEFAULT.value,
                start_time=ns_to_datetime(event.timestamp),
                meta=dict(event.attributes) if event.attributes else None,
            )
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, event_obs)
            except (asyncio.QueueFull, RuntimeError):
                logger.warning("Observation queue full, dropping event {}", event.name)

    def get_aggregates(self) -> dict:
        with self._lock:
            return {
                "total_tokens": self._total_tokens,
                "total_cost": self._total_cost,
                "total_observations": self._observation_count,
                "has_error": self._has_error,
            }

    async def async_shutdown(self) -> None:
        self._queue.put_nowait(_SENTINEL)
        try:
            await asyncio.wait_for(asyncio.wrap_future(self._drain_future), timeout=10)
        except Exception:
            logger.opt(exception=True).warning("ExecutionBucket drain loop did not exit cleanly")

    def sync_shutdown(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, _SENTINEL)
        except RuntimeError:
            return
        try:
            self._drain_future.result(timeout=10)
        except Exception:
            pass

    async def _drain_loop(self) -> None:
        buffer: list[Observation] = []
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=self._max_wait_ms / 1000)
            except asyncio.TimeoutError:
                if buffer:
                    await self._flush(buffer)
                    buffer.clear()
                continue

            if item is _SENTINEL:
                if buffer:
                    await self._flush(buffer)
                break

            buffer.append(item)
            if len(buffer) >= self._max_batch:
                await self._flush(buffer)
                buffer.clear()

    async def _flush(self, buffer: list[Observation]) -> None:
        if not buffer:
            return
        session = await self._db_session_factory()
        try:
            session.add_all(buffer)
            await session.commit()
        except Exception:
            logger.opt(exception=True).warning("PersistenceProcessor flush failed")
            await session.rollback()
        finally:
            await session.close()

    @staticmethod
    def _parse_iso_attr(attrs: Mapping[str, Any], key: str) -> datetime | None:
        val = attrs.get(key)
        if not val or not isinstance(val, str):
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    @staticmethod
    def _safe_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None


class PersistenceProcessor(SpanProcessor):
    """Global singleton that routes spans to per-execution buckets.

    Spans without ``execution.id`` attribute are silently ignored (e.g.
    HTTP middleware spans that exist only for trace-context propagation).
    """

    def __init__(self) -> None:
        self._registry: BucketRegistry[_ExecutionBucket] = BucketRegistry()

    def register_execution(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        project_id: str,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        bucket = _ExecutionBucket(execution_id, trace_id, project_id, db_session_factory, event_loop)
        self._registry.put(execution_id, bucket)

    def get_execution_aggregates(self, execution_id: uuid.UUID) -> dict:
        bucket = self._registry.get_by_id(execution_id)
        if bucket is None:
            return dict(_EMPTY_AGGREGATES)
        return bucket.get_aggregates()

    async def async_shutdown_execution(self, execution_id: uuid.UUID) -> dict:
        bucket = self._registry.pop(execution_id)
        if bucket is None:
            return dict(_EMPTY_AGGREGATES)
        aggregates = bucket.get_aggregates()
        await bucket.async_shutdown()
        return aggregates

    def on_start(self, span: ReadableSpan, parent_context: Any = None) -> None:  # type: ignore[override]
        bucket = self._registry.get_by_span(span)
        if bucket:
            bucket.on_start(span)

    def on_end(self, span: ReadableSpan) -> None:
        bucket = self._registry.get_by_span(span)
        if bucket:
            bucket.on_end(span)

    def reap_stale(self, max_age_seconds: float = 1800) -> list[str]:
        """Remove buckets older than *max_age_seconds* (default 30 min)."""
        stale = self._registry.pop_stale(max_age_seconds)
        for eid, bucket in stale:
            bucket.sync_shutdown()
            logger.warning("Reaped stale observation bucket for execution {}", eid)
        return [eid for eid, _ in stale]

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def shutdown(self, timeout_millis: int = 10000) -> None:
        for bucket in self._registry.clear():
            bucket.sync_shutdown()
