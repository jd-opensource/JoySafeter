"""langchain_utils: message conversion, usage normalization, model extraction, chain classification."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import (
    AIMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.observation.instrumentation.langchain_utils import (
    _classify_chain,
    convert_message_to_dict,
    extract_model_name,
    normalize_usage,
)
from app.core.observation.types import ObservationType


# --- convert_message_to_dict ---

class TestConvertMessageToDict:
    def test_human_message(self):
        msg = HumanMessage(content="Hello")
        result = convert_message_to_dict(msg)
        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_ai_message(self):
        msg = AIMessage(content="Hi")
        result = convert_message_to_dict(msg)
        assert result["role"] == "assistant"

    def test_system_message(self):
        msg = SystemMessage(content="You are helpful")
        result = convert_message_to_dict(msg)
        assert result["role"] == "system"

    def test_tool_message(self):
        msg = ToolMessage(content="result", tool_call_id="call_123")
        result = convert_message_to_dict(msg)
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_123"

    def test_chat_message_custom_role(self):
        msg = ChatMessage(content="custom", role="moderator")
        result = convert_message_to_dict(msg)
        assert result["role"] == "moderator"

    def test_ai_message_with_tool_calls(self):
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "get_weather", "args": {"city": "NYC"}, "id": "1"}],
        )
        result = convert_message_to_dict(msg)
        assert result["role"] == "assistant"
        assert len(result["tool_calls"]) == 1

    def test_additional_kwargs_merged(self):
        msg = HumanMessage(content="hi", additional_kwargs={"custom_field": "val"})
        result = convert_message_to_dict(msg)
        assert result["custom_field"] == "val"


# --- normalize_usage ---

class TestNormalizeUsage:
    def test_openai_format(self):
        raw = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        result = normalize_usage(raw)
        assert result == {"input": 10, "output": 5, "total": 15}

    def test_anthropic_format(self):
        raw = {"input_tokens": 20, "output_tokens": 10}
        result = normalize_usage(raw)
        assert result == {"input": 20, "output": 10, "total": 30}

    def test_vertex_format(self):
        raw = {"promptTokenCount": 30, "candidatesTokenCount": 15, "totalTokenCount": 45}
        result = normalize_usage(raw)
        assert result == {"input": 30, "output": 15, "total": 45}

    def test_bedrock_format(self):
        raw = {"inputTokens": 40, "outputTokens": 20, "totalTokens": 60}
        result = normalize_usage(raw)
        assert result == {"input": 40, "output": 20, "total": 60}

    def test_none_input(self):
        assert normalize_usage(None) == {}

    def test_empty_dict(self):
        assert normalize_usage({}) == {}

    def test_unknown_format(self):
        assert normalize_usage({"foo": 1}) == {}


# --- extract_model_name ---

class TestExtractModelName:
    def test_metadata_ls_model_name(self):
        result = extract_model_name(
            metadata={"ls_model_name": "gpt-4o"},
            serialized={},
            kwargs={},
            response=None,
        )
        assert result == "gpt-4o"

    def test_serialized_kwargs_model_name(self):
        result = extract_model_name(
            metadata={},
            serialized={"kwargs": {"model_name": "claude-3"}},
            kwargs={},
            response=None,
        )
        assert result == "claude-3"

    def test_serialized_kwargs_model(self):
        result = extract_model_name(
            metadata={},
            serialized={"kwargs": {"model": "gemini-pro"}},
            kwargs={},
            response=None,
        )
        assert result == "gemini-pro"

    def test_invocation_params_model_name(self):
        result = extract_model_name(
            metadata={},
            serialized={},
            kwargs={"invocation_params": {"model_name": "gpt-3.5"}},
            response=None,
        )
        assert result == "gpt-3.5"

    def test_invocation_params_model(self):
        result = extract_model_name(
            metadata={},
            serialized={},
            kwargs={"invocation_params": {"model": "titan"}},
            response=None,
        )
        assert result == "titan"

    def test_response_llm_output_model_name(self):
        response = MagicMock()
        response.llm_output = {"model_name": "from-response"}
        result = extract_model_name(
            metadata={},
            serialized={},
            kwargs={},
            response=response,
        )
        assert result == "from-response"

    def test_all_missing_returns_none(self):
        result = extract_model_name(
            metadata={}, serialized={}, kwargs={}, response=None
        )
        assert result is None


# --- _classify_chain ---

class TestClassifyChain:
    def test_worker_prefix(self):
        assert _classify_chain("worker:summarize", {}) == ObservationType.AGENT

    def test_subagent_in_name(self):
        assert _classify_chain("SubAgentRunner", {}) == ObservationType.AGENT

    def test_compiled_subagent(self):
        assert _classify_chain("CompiledSubAgent", {}) == ObservationType.AGENT

    def test_serialized_agent_path(self):
        assert (
            _classify_chain("run", {"id": ["langchain", "agents", "AgentExecutor"]})
            == ObservationType.AGENT
        )

    def test_regular_chain(self):
        assert _classify_chain("RunnableSequence", {}) == ObservationType.CHAIN

    def test_empty_name(self):
        assert _classify_chain("", {}) == ObservationType.CHAIN
