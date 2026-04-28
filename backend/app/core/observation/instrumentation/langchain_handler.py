"""LangChain async callback handler — maps LLM/tool/chain events to observations."""
from __future__ import annotations

import uuid
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from app.core.observation.collector import ObservationCollector
from app.core.observation.types import ObservationLevel, ObservationType, SpanHandle


class ObservationCallbackHandler(AsyncCallbackHandler):

    def __init__(self, collector: ObservationCollector, root_span: SpanHandle):
        self._collector = collector
        self._root_span = root_span
        self._active_spans: dict[uuid.UUID, SpanHandle] = {}

    def _resolve_parent(self, parent_run_id: uuid.UUID | None) -> SpanHandle:
        if parent_run_id and parent_run_id in self._active_spans:
            return self._active_spans[parent_run_id]
        return self._root_span

    async def on_llm_start(self, serialized: dict | None, prompts: list[str], *,
                           run_id: uuid.UUID, parent_run_id: uuid.UUID | None = None,
                           **kwargs: Any) -> None:
        parent = self._resolve_parent(parent_run_id)
        span = await parent.child_span(
            ObservationType.GENERATION,
            name=(serialized or {}).get("name", "") or kwargs.get("name", "llm"),
            input={"messages": prompts},
        )
        self._active_spans[run_id] = span

    async def on_llm_end(self, response: Any, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            output = {}
            if hasattr(response, "generations") and response.generations and response.generations[0]:
                output["completion"] = response.generations[0][0].text
            if hasattr(response, "llm_output") and response.llm_output:
                output["usage_details"] = response.llm_output.get("token_usage")
                output["model"] = response.llm_output.get("model_name")
            await span.end(output=output)

    async def on_tool_start(self, serialized: dict | None, input_str: str, *,
                            run_id: uuid.UUID, parent_run_id: uuid.UUID | None = None,
                            **kwargs: Any) -> None:
        parent = self._resolve_parent(parent_run_id)
        span = await parent.child_span(
            ObservationType.TOOL,
            name=(serialized or {}).get("name", "") or kwargs.get("name", "tool"),
            input={"arguments": input_str},
        )
        self._active_spans[run_id] = span

    async def on_tool_end(self, output: str, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            await span.end(output={"result": output})

    async def on_chain_start(self, serialized: dict | None, inputs: dict, *,
                             run_id: uuid.UUID, parent_run_id: uuid.UUID | None = None,
                             **kwargs: Any) -> None:
        name = (serialized or {}).get("name", "") or kwargs.get("name", "chain")
        parent = self._resolve_parent(parent_run_id)
        obs_type = ObservationType.AGENT if self._is_worker_dispatch(name) else ObservationType.CHAIN
        span = await parent.child_span(obs_type, name=name, input=inputs)
        self._active_spans[run_id] = span

    async def on_chain_end(self, outputs: dict, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            await span.end(output=outputs)

    async def on_llm_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            await span.end(output={"error": str(error)}, level=ObservationLevel.ERROR)

    async def on_tool_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        span = self._active_spans.pop(run_id, None)
        if span:
            await span.end(output={"error": str(error)}, level=ObservationLevel.ERROR)

    @staticmethod
    def _is_worker_dispatch(name: str) -> bool:
        return name.startswith("worker:") or "SubAgent" in name or "CompiledSubAgent" in name
