"""PersistenceProcessor -- deferred-INSERT SpanProcessor writing Observation rows to PG."""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable, Coroutine

from loguru import logger
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from app.core.observation.model import Observation
from app.core.observation.otel.processor_base import (
    build_cost,
    build_usage,
    ns_to_datetime,
    parse_json_attr,
)
from app.core.observation.types import ObservationLevel, ObservationType

_SENTINEL = object()


class PersistenceProcessor(SpanProcessor):
    """Batched async writer that converts finished OTel spans into Observation rows.

    Designed to bridge OTel's synchronous SpanProcessor callbacks to async
    SQLAlchemy persistence via an asyncio.Queue + drain loop running on the
    caller's event loop.
    """

    def __init__(
        self,
        execution_id: uuid.UUID,
        trace_id: uuid.UUID,
        workspace_id: uuid.UUID,
        db_session_factory: Callable[..., Coroutine[Any, Any, Any]],
        event_loop: asyncio.AbstractEventLoop,
        *,
        max_batch: int = 10,
        max_wait_ms: int = 300,
        max_buffer_size: int = 1000,
    ) -> None:
        self._execution_id = execution_id
        self._trace_id = trace_id
        self._workspace_id = workspace_id
        self._db_session_factory = db_session_factory
        self._loop = event_loop
        self._max_batch = max_batch
        self._max_wait_ms = max_wait_ms
        self._max_buffer_size = max_buffer_size

        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_buffer_size)
        self._otel_span_id_to_observation_id: dict[int, uuid.UUID] = {}

        # Aggregation state
        self._total_tokens = 0
        self._total_cost = 0.0
        self._observation_count = 0
        self._has_error = False

        # Start drain loop on the event loop
        self._drain_future = asyncio.run_coroutine_threadsafe(
            self._drain_loop(), self._loop
        )

    # ---- SpanProcessor interface ----

    def on_start(self, span: ReadableSpan, parent_context: Any = None) -> None:  # type: ignore[override]
        """Stash the OTel span_id -> observation_id mapping for parent resolution."""
        obs_id_str = span.attributes.get("observation.id")  # type: ignore[union-attr]
        if obs_id_str:
            self._otel_span_id_to_observation_id[span.context.span_id] = uuid.UUID(  # type: ignore[union-attr]
                str(obs_id_str)
            )

    def on_end(self, span: ReadableSpan) -> None:
        """Convert a finished span to an Observation and enqueue for persistence."""
        attrs = span.attributes or {}
        obs_id_str = attrs.get("observation.id")
        if not obs_id_str:
            return

        obs_id = uuid.UUID(str(obs_id_str))

        parent_obs_id: uuid.UUID | None = None
        if span.parent:
            parent_obs_id = self._otel_span_id_to_observation_id.get(
                span.parent.span_id
            )

        obs = Observation(
            id=obs_id,
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
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
            completion_start_time=self._parse_iso_attr(
                attrs, "llm.completion_start_time"
            ),
            prompt_name=attrs.get("llm.prompt.name"),  # type: ignore[arg-type]
            prompt_version=self._safe_int(attrs.get("llm.prompt.version")),
            tool_calls=parse_json_attr(attrs.get("tool.calls")),
            tool_definitions=parse_json_attr(attrs.get("tool.definitions")),
        )

        self._loop.call_soon_threadsafe(self._queue.put_nowait, obs)

        usage_total = attrs.get("llm.usage.total", 0)
        if usage_total:
            self._total_tokens += int(usage_total)  # type: ignore[arg-type]
        cost_total = attrs.get("llm.cost.total", 0.0)
        if cost_total:
            self._total_cost += float(cost_total)  # type: ignore[arg-type]
        self._observation_count += 1
        if str(attrs.get("observation.level")) == ObservationLevel.ERROR.value:
            self._has_error = True

        for event in span.events:
            if event.name.startswith("stream."):
                continue
            event_obs = Observation(
                id=uuid.uuid4(),
                trace_id=self._trace_id,
                execution_id=self._execution_id,
                workspace_id=self._workspace_id,
                parent_observation_id=obs_id,
                type=ObservationType.EVENT.value,
                name=event.name,
                level=ObservationLevel.DEFAULT.value,
                start_time=ns_to_datetime(event.timestamp),
                meta=dict(event.attributes) if event.attributes else None,
            )
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event_obs)

        # Prune span-id map entry — no longer needed after on_end
        if hasattr(span, "context") and span.context:
            self._otel_span_id_to_observation_id.pop(span.context.span_id, None)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """No-op; drain loop handles flushing on its own schedule."""
        return True

    # ---- Public API ----

    def get_aggregates(self) -> dict:
        """Return accumulated token/cost/observation counts."""
        return {
            "total_tokens": self._total_tokens,
            "total_cost": self._total_cost,
            "total_observations": self._observation_count,
            "has_error": self._has_error,
        }

    def shutdown(self, timeout_millis: int = 10000) -> None:
        """Signal the drain loop to exit and wait for completion.

        Sync to satisfy the SpanProcessor contract (OTel calls this from GC).
        Our own ObservationTracerProvider.shutdown() calls async_shutdown()
        for proper async waiting.
        """
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, _SENTINEL)
        except RuntimeError:
            return
        try:
            self._drain_future.result(timeout=timeout_millis / 1000)
        except Exception:
            pass

    async def async_shutdown(self) -> None:
        """Async variant used by ObservationTracerProvider.shutdown()."""
        self._queue.put_nowait(_SENTINEL)
        try:
            await asyncio.wait_for(
                asyncio.wrap_future(self._drain_future), timeout=10
            )
        except Exception:
            logger.opt(exception=True).warning(
                "PersistenceProcessor drain loop did not exit cleanly"
            )

    # ---- Internal: drain loop & flush ----

    async def _drain_loop(self) -> None:
        """Continuously drain the queue and flush batches to PG."""
        buffer: list[Observation] = []
        while True:
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._max_wait_ms / 1000
                )
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
        """Write a batch of Observation rows to PG."""
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

    # ---- Helpers ----

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
