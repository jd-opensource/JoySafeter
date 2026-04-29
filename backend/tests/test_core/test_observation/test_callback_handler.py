"""ObservationCallbackHandler — full rewrite with all 18 LangChain hooks."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from app.core.observation.instrumentation.langchain_handler import (
    ObservationCallbackHandler,
    RunState,
)
from app.core.observation.otel.span_wrapper import ObservationSpan


def _make_handler():
    tracer = MagicMock()
    provider = MagicMock()
    obs_span = MagicMock(spec=ObservationSpan)
    obs_span.observation_id = uuid.uuid4()
    obs_span._span = MagicMock()
    tracer.start_span.return_value = obs_span._span
    provider.dispatch_live_event = MagicMock()
    handler = ObservationCallbackHandler(tracer, provider)
    return handler, tracer, provider


# --- Run tree ---

class TestRunStateTracking:
    def test_track_root_run(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        handler._track_run(run_id, None)
        assert run_id in handler._run_states
        state = handler._run_states[run_id]
        assert state.root_run_id == run_id
        assert run_id in handler._root_run_states

    def test_track_child_run(self):
        handler, _, _ = _make_handler()
        root = uuid.uuid4()
        child = uuid.uuid4()
        handler._track_run(root, None)
        handler._track_run(child, root)
        assert handler._run_states[child].root_run_id == root
        assert child in handler._root_run_states[root].run_ids

    def test_reset_clears_subtree(self):
        handler, _, _ = _make_handler()
        root = uuid.uuid4()
        child1 = uuid.uuid4()
        child2 = uuid.uuid4()
        handler._track_run(root, None)
        handler._track_run(child1, root)
        handler._track_run(child2, root)
        handler._reset(root)
        assert root not in handler._run_states
        assert child1 not in handler._run_states
        assert child2 not in handler._run_states
        assert root not in handler._root_run_states

    def test_idempotent_track(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        handler._track_run(run_id, None)
        handler._track_run(run_id, None)  # second call should be no-op
        assert len(handler._root_run_states[run_id].run_ids) == 1


# --- Callback hooks (integration with mock OTel) ---

class TestCallbackHooks:
    @pytest.mark.asyncio
    async def test_on_chain_start_creates_span(self):
        handler, tracer, provider = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_chain_start(
            serialized={"name": "RunnableSequence", "id": ["langchain", "chains"]},
            inputs={"input": "test"},
            run_id=run_id,
            parent_run_id=None,
        )
        assert run_id in handler._runs
        tracer.start_span.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_chain_end_detaches(self):
        handler, tracer, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_chain_start(
            serialized={"name": "test"},
            inputs={},
            run_id=run_id,
            parent_run_id=None,
        )
        await handler.on_chain_end(outputs={"result": "done"}, run_id=run_id)
        assert run_id not in handler._runs

    @pytest.mark.asyncio
    async def test_on_chat_model_start_creates_generation(self):
        handler, tracer, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_chat_model_start(
            serialized={"id": ["langchain", "chat_models", "ChatOpenAI"]},
            messages=[[HumanMessage(content="hi")]],
            run_id=run_id,
            parent_run_id=None,
            metadata={"ls_model_name": "gpt-4o"},
        )
        assert run_id in handler._runs

    @pytest.mark.asyncio
    async def test_on_llm_error_cleans_up(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_llm_start(
            serialized={"name": "llm"},
            prompts=["hello"],
            run_id=run_id,
        )
        await handler.on_llm_error(
            error=ValueError("boom"),
            run_id=run_id,
        )
        assert run_id not in handler._runs

    @pytest.mark.asyncio
    async def test_on_tool_start_end(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_tool_start(
            serialized={"name": "calculator"},
            input_str="2+2",
            run_id=run_id,
        )
        assert run_id in handler._runs
        await handler.on_tool_end(output="4", run_id=run_id)
        assert run_id not in handler._runs

    @pytest.mark.asyncio
    async def test_on_retriever_start_end(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_retriever_start(
            serialized={"name": "vector_store"},
            query="search query",
            run_id=run_id,
        )
        assert run_id in handler._runs
        await handler.on_retriever_end(documents=[], run_id=run_id)
        assert run_id not in handler._runs

    @pytest.mark.asyncio
    async def test_on_llm_new_token_first_sets_completion_start_time(self):
        handler, _, _ = _make_handler()
        run_id = uuid.uuid4()
        await handler.on_llm_start(
            serialized={"name": "llm"},
            prompts=["hello"],
            run_id=run_id,
        )
        span = handler._runs.get(run_id)
        assert span is not None
        await handler.on_llm_new_token(token="Hi", run_id=run_id)
        # First token sets completion_start_time
        assert run_id in handler._completion_start_memo

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_propagate(self):
        handler, tracer, _ = _make_handler()
        # Force tracer.start_span to raise
        tracer.start_span.side_effect = RuntimeError("otel crash")
        # This should NOT raise
        await handler.on_chain_start(
            serialized={"name": "test"},
            inputs={},
            run_id=uuid.uuid4(),
        )
