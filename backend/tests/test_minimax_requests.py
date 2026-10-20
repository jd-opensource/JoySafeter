"""Exercise MiniMax through the installed SDKs with an offline HTTP transport."""

import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from test_minimax_provider import _load_providers


@pytest.fixture
def provider():
    base, module = _load_providers()
    return module.MiniMaxProvider(), base.ModelType.CHAT


@pytest.fixture
def requests(monkeypatch):
    captured = []

    def handle(request):
        body = json.loads(request.content)
        captured.append((str(request.url), body))
        if request.url.path.endswith("/chat/completions"):
            message = {"role": "assistant", "content": "Done", "reasoning_content": "Consider the request."}
            if body.get("stream"):
                chunks = [
                    {
                        "id": "offline",
                        "object": "chat.completion.chunk",
                        "model": body["model"],
                        "choices": [{"index": 0, "delta": message, "finish_reason": None}],
                    },
                    {
                        "id": "offline",
                        "object": "chat.completion.chunk",
                        "model": body["model"],
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    },
                ]
                data = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
                return httpx.Response(200, request=request, text=data, headers={"content-type": "text/event-stream"})
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "offline",
                    "object": "chat.completion",
                    "model": body["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )
        assert request.url.path.endswith("/messages")
        message = {
            "id": "offline",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [{"type": "text", "text": "Done"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        if body.get("stream"):
            events = [
                {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Done"}},
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 5},
                },
                {"type": "message_stop"},
            ]
            data = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, request=request, text=data, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, request=request, json=message)

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.Client, "send", lambda self, request, **kwargs: transport.handle_request(request))

    async def send(self, request, **kwargs):
        return await transport.handle_async_request(request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return captured


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize("region,host", [("global_en", "api.minimax.io"), ("cn_zh", "api.minimaxi.com")])
@pytest.mark.parametrize("model_name", [None, "MiniMax-M3", "MiniMax-M2.7", "saved-custom-id"])
def test_selected_model_reaches_http(provider, requests, protocol, region, host, model_name):
    impl, chat = provider
    selected = model_name or impl.get_model_list(chat)[0]["name"]
    model = impl.create_model_instance(
        selected, chat, {"api_key": "offline", "protocol_type": protocol, "region": region}
    )
    assert model.invoke("Hello").content == "Done"
    url, body = requests[-1]
    path = "/v1/chat/completions" if protocol == "openai" else "/anthropic/v1/messages"
    assert url == f"https://{host}{path}"
    assert body["model"] == (model_name or "MiniMax-M3.1-Flash")
    assert body["stream"] is True
    assert "thinking" not in body
    assert "reasoning_effort" not in body
    assert "output_config" not in body
    assert "service_tier" not in body
    assert body.get("reasoning_split") is not False


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_flash_effort_serialization(provider, requests, protocol, effort):
    impl, chat = provider
    model = impl.create_model_instance(
        "MiniMax-M3.1-Flash",
        chat,
        {"api_key": "offline", "protocol_type": protocol},
        {"thinking": "adaptive", "reasoning_effort": effort, "max_tokens": 8192},
    )
    model.invoke("Hello")
    body = requests[-1][1]
    assert body["thinking"] == {"type": "adaptive"}
    if protocol == "openai":
        assert body["reasoning_effort"] == effort
        assert body["max_completion_tokens"] == 8192
        assert "output_config" not in body
    else:
        assert body["output_config"] == {"effort": effort}
        assert body["max_tokens"] == 8192
        assert "reasoning_effort" not in body


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize("thinking", ["adaptive", "disabled"])
def test_m3_thinking_without_effort(provider, requests, protocol, thinking):
    impl, chat = provider
    model = impl.create_model_instance(
        "MiniMax-M3",
        chat,
        {"api_key": "offline", "protocol_type": protocol},
        {"thinking": thinking, "reasoning_effort": "max"},
    )
    model.invoke("Hello")
    body = requests[-1][1]
    assert body["thinking"] == {"type": thinking}
    assert "reasoning_effort" not in body
    assert "output_config" not in body


@pytest.mark.parametrize("parameters", [{"thinking": "disabled"}, {"reasoning_effort": "none"}])
@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_flash_rejects_incompatible_settings(provider, requests, parameters, protocol):
    impl, chat = provider
    with pytest.raises(ValueError, match="MiniMax-M3.1-Flash"):
        impl.create_model_instance(
            "MiniMax-M3.1-Flash", chat, {"api_key": "offline", "protocol_type": protocol}, parameters
        )
    assert not requests


@pytest.mark.parametrize("protocol,path", [("openai", "/chat/completions"), ("anthropic", "/v1/messages")])
async def test_credentials_use_flash_and_explicit_endpoint(provider, requests, protocol, path):
    impl, _ = provider
    valid, error = await impl.validate_credentials(
        {"api_key": "offline", "protocol_type": protocol, "base_url": "https://custom.example/compat"}
    )
    assert (valid, error) == (True, None)
    url, body = requests[-1]
    assert url == "https://custom.example/compat" + path
    assert body["model"] == "MiniMax-M3.1-Flash"
    assert body.get("max_tokens", body.get("max_completion_tokens")) == 4096


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_multimodal_tool_history(provider, requests, protocol):
    impl, chat = provider
    model = impl.create_model_instance("MiniMax-M3.1-Flash", chat, {"api_key": "offline", "protocol_type": protocol})
    if protocol == "openai":
        content = [
            {"type": "text", "text": "Describe"},
            {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
            {"type": "video_url", "video_url": {"url": "mm_file://video"}},
        ]
        assistant = AIMessage(
            content="<think>Keep history.</think>",
            additional_kwargs={"reasoning_content": "Consider the request."},
            tool_calls=[{"id": "call_1", "name": "inspect", "args": {}}],
        )
    else:
        content = [
            {"type": "text", "text": "Describe"},
            {"type": "image", "source": {"type": "url", "url": "https://example.com/image.png"}},
            {"type": "video", "source": {"type": "url", "url": "mm_file://video"}},
        ]
        assistant = AIMessage(
            content=[
                {"type": "thinking", "thinking": "Consider the request.", "signature": "offline"},
                {"type": "tool_use", "id": "call_1", "name": "inspect", "input": {}},
            ]
        )
    tool = {
        "type": "function",
        "function": {
            "name": "inspect",
            "description": "Inspect a file",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    model.bind_tools([tool]).invoke(
        [HumanMessage(content=content), assistant, ToolMessage(content="Result", tool_call_id="call_1")]
    )
    body = requests[-1][1]
    if protocol == "openai":
        assert body["tools"][0]["function"]["name"] == "inspect"
    else:
        assert body["tools"][0]["name"] == "inspect"
    assert body["messages"][0]["content"] == content
    sent = body["messages"][1]
    if protocol == "openai":
        assert sent["content"] == assistant.content
        assert sent["reasoning_content"] == "Consider the request."
        assert sent["tool_calls"][0]["id"] == "call_1"
    else:
        assert sent["content"] == assistant.content


@pytest.mark.parametrize("streaming", [True, False])
def test_openai_reasoning_round_trip(provider, requests, streaming):
    impl, chat = provider
    model = impl.create_model_instance("MiniMax-M3.1-Flash", chat, {"api_key": "offline"})
    model.streaming = streaming
    response = model.invoke("First turn")
    assert response.additional_kwargs["reasoning_content"] == "Consider the request."
    model.invoke([HumanMessage(content="First turn"), response, HumanMessage(content="Continue")])
    assert requests[-1][1]["messages"][1]["reasoning_content"] == "Consider the request."
