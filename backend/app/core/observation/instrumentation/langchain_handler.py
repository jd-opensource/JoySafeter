"""LangChain async callback handler — maps all 18 hooks to OTel observation spans."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from loguru import logger
from opentelemetry.trace import Tracer

from app.core.observation.instrumentation.langchain_utils import (
    _classify_chain,
    extract_model_name,
)
from app.utils.message_serializer import serialize_message
from app.utils.token_usage import extract_usage_from_llm_result
from app.core.observation.otel.provider import ObservationTracerProvider
from app.core.observation.otel.span_wrapper import ObservationSpan
from app.core.observation.types import ObservationLevel, ObservationType


def _safe_json(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_json(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


@dataclass
class RunState:
    parent_run_id: uuid.UUID | None
    root_run_id: uuid.UUID


@dataclass
class RootRunState:
    run_ids: set[uuid.UUID] = field(default_factory=set)


class ObservationCallbackHandler(AsyncCallbackHandler):
    def __init__(self, tracer: Tracer, provider: ObservationTracerProvider) -> None:
        self._tracer = tracer
        self._provider = provider
        self._runs: dict[uuid.UUID, ObservationSpan] = {}
        self._run_states: dict[uuid.UUID, RunState] = {}
        self._root_run_states: dict[uuid.UUID, RootRunState] = {}
        self._completion_start_memo: set[uuid.UUID] = set()
        self._prompt_to_parent: dict[uuid.UUID, Any] = {}

    # --- run tree ---

    def _track_run(self, run_id: uuid.UUID, parent_run_id: uuid.UUID | None) -> None:
        if run_id in self._run_states:
            return
        if parent_run_id is None or parent_run_id not in self._run_states:
            root = run_id
            self._root_run_states[root] = RootRunState()
        else:
            root = self._run_states[parent_run_id].root_run_id
        self._run_states[run_id] = RunState(parent_run_id, root)
        self._root_run_states[root].run_ids.add(run_id)

    def _is_root(self, run_id: uuid.UUID) -> bool:
        state = self._run_states.get(run_id)
        return state is not None and state.root_run_id == run_id

    # --- OTel context ---

    def _start_obs_span(
        self,
        run_id: uuid.UUID,
        name: str,
        obs_type: ObservationType,
        parent_run_id: uuid.UUID | None = None,
    ) -> ObservationSpan:
        obs_id = uuid.uuid4()

        parent_ctx = None
        if parent_run_id and parent_run_id in self._runs:
            parent_span = self._runs[parent_run_id]
            parent_ctx = parent_span.get_context()

        otel_span = self._tracer.start_span(
            name, context=parent_ctx,
            attributes={
                "observation.id": str(obs_id),
                "observation.type": obs_type.value,
                "observation.level": ObservationLevel.DEFAULT.value,
            },
        )
        obs = ObservationSpan(otel_span, obs_id, self._provider)
        self._runs[run_id] = obs
        return obs

    def _detach_span(self, run_id: uuid.UUID) -> ObservationSpan | None:
        return self._runs.pop(run_id, None)

    def _reset(self, root_run_id: uuid.UUID) -> None:
        state = self._root_run_states.pop(root_run_id, None)
        if state:
            for rid in state.run_ids:
                self._run_states.pop(rid, None)

    # --- chain hooks ---

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "chain")
            obs_type = _classify_chain(name, serialized or {})
            obs = self._start_obs_span(run_id, name, obs_type, parent_run_id)
            obs.set_input(_safe_json(inputs))
            if metadata:
                obs.set_metadata(metadata)
                prompt = metadata.get("langfuse_prompt")
                if prompt:
                    self._prompt_to_parent[run_id] = prompt
        except Exception:
            logger.opt(exception=True).debug("on_chain_start failed")

    async def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_output(_safe_json(outputs))
                obs.end()
            if self._is_root(run_id):
                self._reset(run_id)
        except Exception:
            logger.opt(exception=True).debug("on_chain_end failed")

    async def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_level(ObservationLevel.ERROR)
                obs.set_status_message(str(error))
                obs.end()
            if self._is_root(run_id):
                self._reset(run_id)
        except Exception:
            logger.opt(exception=True).debug("on_chain_error failed")

    # --- LLM hooks ---

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[BaseMessage]],
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "chat_model")

            input_msgs = []
            for msg_list in messages:
                input_msgs.extend(serialize_message(m) for m in msg_list)

            obs = self._start_obs_span(
                run_id, name, ObservationType.GENERATION, parent_run_id
            )
            obs.set_input({"messages": input_msgs})

            model = extract_model_name(
                metadata=metadata,
                serialized=serialized,
                kwargs=kwargs,
                response=None,
            )
            if model:
                obs.set_model(model)

            inv_params = kwargs.get("invocation_params")
            if inv_params:
                obs.set_model_parameters(inv_params)

            if metadata:
                obs.set_metadata(metadata)

            self._maybe_link_prompt(run_id, parent_run_id, obs)
        except Exception:
            logger.opt(exception=True).debug("on_chat_model_start failed")

    async def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "llm")
            obs = self._start_obs_span(
                run_id, name, ObservationType.GENERATION, parent_run_id
            )
            obs.set_input({"prompts": prompts})

            model = extract_model_name(
                metadata=metadata,
                serialized=serialized or {},
                kwargs=kwargs,
                response=None,
            )
            if model:
                obs.set_model(model)

            if metadata:
                obs.set_metadata(metadata)

            self._maybe_link_prompt(run_id, parent_run_id, obs)
        except Exception:
            logger.opt(exception=True).debug("on_llm_start failed")

    async def on_llm_end(
        self,
        response: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if not obs:
                return

            output: dict[str, Any] = {}
            if hasattr(response, "generations") and response.generations:
                gen_list = response.generations[0]
                if gen_list:
                    gen = gen_list[0]
                    if hasattr(gen, "message"):
                        output = serialize_message(gen.message)
                    elif hasattr(gen, "text"):
                        output = {"completion": gen.text}

            usage = extract_usage_from_llm_result(response)
            if usage:
                obs.set_usage(usage)

            if hasattr(response, "llm_output") and response.llm_output:
                model_from_response = response.llm_output.get("model_name")
                if model_from_response:
                    obs.set_model(model_from_response)

            obs.set_output(output)
            obs.end()
            self._completion_start_memo.discard(run_id)
        except Exception:
            logger.opt(exception=True).debug("on_llm_end failed")

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_level(ObservationLevel.ERROR)
                obs.set_status_message(str(error))
                obs.end()
            self._completion_start_memo.discard(run_id)
        except Exception:
            logger.opt(exception=True).debug("on_llm_error failed")

    async def on_llm_new_token(
        self,
        token: str,
        *,
        run_id: uuid.UUID,
        chunk: Any | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._runs.get(run_id)
            if not obs:
                return
            if run_id not in self._completion_start_memo:
                self._completion_start_memo.add(run_id)
                obs.set_completion_start_time(datetime.now(tz=timezone.utc))
            idx = kwargs.get("index", 0)
            obs.add_llm_token(token, idx)
        except Exception:
            logger.opt(exception=True).debug("on_llm_new_token failed")

    # --- tool hooks ---

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "tool")
            obs = self._start_obs_span(
                run_id, name, ObservationType.TOOL, parent_run_id
            )
            obs.set_input({"arguments": input_str})
            if metadata:
                obs.set_metadata(metadata)
        except Exception:
            logger.opt(exception=True).debug("on_tool_start failed")

    async def on_tool_end(
        self,
        output: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_output({"result": output})
                obs.end()
        except Exception:
            logger.opt(exception=True).debug("on_tool_end failed")

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_level(ObservationLevel.ERROR)
                obs.set_status_message(str(error))
                obs.end()
        except Exception:
            logger.opt(exception=True).debug("on_tool_error failed")

    # --- retriever hooks ---

    async def on_retriever_start(
        self,
        serialized: dict[str, Any] | None,
        query: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            self._track_run(run_id, parent_run_id)
            name = (serialized or {}).get("name", "") or kwargs.get("name", "retriever")
            obs = self._start_obs_span(
                run_id, name, ObservationType.RETRIEVER, parent_run_id
            )
            obs.set_input({"query": query})
            if metadata:
                obs.set_metadata(metadata)
        except Exception:
            logger.opt(exception=True).debug("on_retriever_start failed")

    async def on_retriever_end(
        self,
        documents: Sequence[Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                docs_out = [_safe_json(d) for d in documents]
                obs.set_output({"documents": docs_out})
                obs.end()
        except Exception:
            logger.opt(exception=True).debug("on_retriever_end failed")

    async def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._detach_span(run_id)
            if obs:
                obs.set_level(ObservationLevel.ERROR)
                obs.set_status_message(str(error))
                obs.end()
        except Exception:
            logger.opt(exception=True).debug("on_retriever_error failed")

    # --- agent hooks ---

    async def on_agent_action(
        self,
        action: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._runs.get(run_id)
            if obs:
                obs.set_observation_type(ObservationType.AGENT)
                log = _safe_json(getattr(action, "log", str(action)))
                obs.add_intermediate_update({"type": ObservationType.AGENT.value, "action_log": log})
        except Exception:
            logger.opt(exception=True).debug("on_agent_action failed")

    async def on_agent_finish(
        self,
        finish: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._runs.get(run_id)
            if obs:
                return_values = _safe_json(
                    getattr(finish, "return_values", str(finish))
                )
                obs.set_output(return_values)
        except Exception:
            logger.opt(exception=True).debug("on_agent_finish failed")

    # --- misc hooks ---

    async def on_retry(
        self,
        retry_state: Any,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        try:
            obs = self._runs.get(run_id)
            if obs:
                obs.add_event("retry", {
                    "attempt": str(getattr(retry_state, "attempt_number", "?")),
                    "error": str(getattr(retry_state, "outcome", "")),
                })
        except Exception:
            logger.opt(exception=True).debug("on_retry failed")

    async def on_text(
        self,
        text: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        pass  # Ignored — info covered by other hooks

    # --- prompt linkage helper ---

    def _maybe_link_prompt(
        self,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None,
        obs: ObservationSpan,
    ) -> None:
        current = parent_run_id
        while current:
            prompt = self._prompt_to_parent.pop(current, None)
            if prompt:
                name = getattr(prompt, "name", str(prompt))
                version = str(getattr(prompt, "version", ""))
                obs.set_prompt(name, version or None)
                return
            state = self._run_states.get(current)
            current = state.parent_run_id if state else None
