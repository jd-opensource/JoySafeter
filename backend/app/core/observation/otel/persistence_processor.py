"""PersistenceProcessor -- deferred-INSERT SpanProcessor writing Observation rows to PG."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from loguru import logger
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from app.core.observation.model import Observation
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

        self._queue: asyncio.Queue[Any] = asyncio.Queue()
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

        # Resolve parent observation_id from OTel parent span
        parent_obs_id: uuid.UUID | None = None
        if span.parent:
            parent_obs_id = self._otel_span_id_to_observation_id.get(
                span.parent.span_id
            )

        # Build Observation
        obs = Observation(
            id=obs_id,
            trace_id=self._trace_id,
            execution_id=self._execution_id,
            workspace_id=self._workspace_id,
            parent_observation_id=parent_obs_id,
            type=str(attrs.get("observation.type", ObservationType.SPAN.value)),
            name=span.name,
            level=str(attrs.get("observation.level", ObservationLevel.DEFAULT.value)),
            start_time=self._ns_to_dt(span.start_time),
            end_time=self._ns_to_dt(span.end_time),
            input=self._parse_json_attr(attrs, "observation.input"),
            output=self._parse_json_attr(attrs, "observation.output"),
            meta=self._parse_json_attr(attrs, "observation.metadata"),
            model=attrs.get("llm.model"),  # type: ignore[arg-type]
            model_parameters=self._parse_json_attr(attrs, "llm.parameters"),
            usage_details=self._build_usage(attrs),
            cost_details=self._build_cost(attrs),
            completion_start_time=self._parse_iso_attr(
                attrs, "llm.completion_start_time"
            ),
            prompt_name=attrs.get("llm.prompt.name"),  # type: ignore[arg-type]
            prompt_version=self._safe_int(attrs.get("llm.prompt.version")),
            tool_calls=self._parse_json_attr(attrs, "tool.calls"),
            tool_definitions=self._parse_json_attr(attrs, "tool.definitions"),
        )

        self._loop.call_soon_threadsafe(self._queue.put_nowait, obs)

        # Accumulate aggregates
        usage_total = attrs.get("llm.usage.total", 0)
        if usage_total:
            self._total_tokens += int(usage_total)  # type: ignore[arg-type]
        cost_total = attrs.get("llm.cost.total", 0.0)
        if cost_total:
            self._total_cost += float(cost_total)  # type: ignore[arg-type]
        self._observation_count += 1
        if str(attrs.get("observation.level")) == "ERROR":
            self._has_error = True

        # Persist non-stream events as child observations
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
                start_time=self._ns_to_dt(event.timestamp),
                meta=dict(event.attributes) if event.attributes else None,
            )
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event_obs)

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

    async def shutdown(self) -> None:  # type: ignore[override]
        """Signal the drain loop to exit and wait for it to finish.

        Note: returns a coroutine, intentionally diverging from the sync
        SpanProcessor.shutdown contract -- callers in this codebase always
        await it. OTel's own shutdown path is not used.
        """
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
        try:
            session = await self._db_session_factory()
            session.add_all(buffer)
            await session.commit()
        except Exception:
            logger.opt(exception=True).warning("PersistenceProcessor flush failed")

    # ---- Helpers ----

    @staticmethod
    def _ns_to_dt(ns: int | None) -> datetime | None:
        if ns is None:
            return None
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)

    @staticmethod
    def _parse_json_attr(attrs: Mapping[str, Any], key: str) -> Any:
        val = attrs.get(key)
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, ValueError):
                return val
        return val

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

    @staticmethod
    def _build_usage(attrs: Mapping[str, Any]) -> dict | None:
        inp = attrs.get("llm.usage.input")
        out = attrs.get("llm.usage.output")
        total = attrs.get("llm.usage.total")
        if inp is None and out is None and total is None:
            return None
        return {
            "input": int(inp) if inp is not None else 0,  # type: ignore[arg-type]
            "output": int(out) if out is not None else 0,  # type: ignore[arg-type]
            "total": int(total) if total is not None else 0,  # type: ignore[arg-type]
        }

    @staticmethod
    def _build_cost(attrs: Mapping[str, Any]) -> dict | None:
        inp = attrs.get("llm.cost.input")
        out = attrs.get("llm.cost.output")
        total = attrs.get("llm.cost.total")
        if inp is None and out is None and total is None:
            return None
        return {
            "input": float(inp) if inp is not None else 0.0,  # type: ignore[arg-type]
            "output": float(out) if out is not None else 0.0,  # type: ignore[arg-type]
            "total": float(total) if total is not None else 0.0,  # type: ignore[arg-type]
        }
