from __future__ import annotations

from proxy.config import ProxySettings
from proxy.converters import (
    convert_anthropic_request_to_openai,
    convert_openai_response_to_anthropic,
)


def test_convert_anthropic_request_to_openai_with_image_tools_and_mapping() -> None:
    settings = ProxySettings(
        openai_base_url="https://example.com",
        model_map={"claude-sonnet-4-6": "Kimi-K2.5"},
        default_max_tokens=4096,
    )

    payload = {
        "model": "claude-sonnet-4-6",
        "system": "You are a helper",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this image?"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "ZmFrZQ==",
                        },
                    },
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "describe_image",
                        "input": {"detail": "high"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_1",
                        "content": "an image of a cat",
                    }
                ],
            },
        ],
        "tools": [
            {
                "name": "describe_image",
                "description": "Describe image",
                "input_schema": {"type": "object", "properties": {"detail": {"type": "string"}}},
            }
        ],
        "tool_choice": {"type": "tool", "name": "describe_image"},
        "stop_sequences": ["<end>"],
    }

    converted = convert_anthropic_request_to_openai(payload, settings)

    assert converted.original_model == "claude-sonnet-4-6"
    assert converted.mapped_model == "Kimi-K2.5"

    openai_payload = converted.openai_payload
    assert openai_payload["model"] == "Kimi-K2.5"
    assert openai_payload["max_tokens"] == 4096
    assert openai_payload["stop"] == ["<end>"]
    assert openai_payload["tool_choice"] == {"type": "function", "function": {"name": "describe_image"}}

    assert openai_payload["messages"][0] == {"role": "system", "content": "You are a helper"}

    user_msg = openai_payload["messages"][1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][0]["type"] == "text"
    assert user_msg["content"][1]["type"] == "image_url"
    assert user_msg["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    assistant_msg = openai_payload["messages"][2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "describe_image"

    tool_msg = openai_payload["messages"][3]
    assert tool_msg == {"role": "tool", "tool_call_id": "call_1", "content": "an image of a cat"}


def test_convert_openai_response_to_anthropic_with_tool_calls() -> None:
    openai_response = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "Let me call a tool",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "weather",
                                "arguments": '{"city":"Beijing"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
        },
    }

    converted = convert_openai_response_to_anthropic(openai_response, model_name="claude-sonnet-4-6")

    assert converted["id"] == "chatcmpl-test"
    assert converted["type"] == "message"
    assert converted["role"] == "assistant"
    assert converted["model"] == "claude-sonnet-4-6"
    assert converted["stop_reason"] == "tool_use"
    assert converted["usage"] == {"input_tokens": 11, "output_tokens": 7}

    blocks = converted["content"]
    assert blocks[0] == {"type": "text", "text": "Let me call a tool"}
    assert blocks[1]["type"] == "tool_use"
    assert blocks[1]["name"] == "weather"
    assert blocks[1]["input"] == {"city": "Beijing"}
