from app.websocket.chat_protocol import (
    ParsedChatStartFrame,
    parse_client_frame,
)


def test_parse_chat_extension_frame():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-chat-1",
            "thread_id": "t-1",
            "graph_id": None,
            "input": {"message": "hello"},
            "extension": {"kind": "chat", "run_id": "run-abc"},
            "metadata": {},
        }
    )
    assert isinstance(parsed, ParsedChatStartFrame)
    assert parsed.extension is not None
    assert parsed.extension.kind == "chat"
    assert parsed.extension.run_id == "run-abc"


def test_parse_chat_extension_with_no_run_id():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-chat-2",
            "input": {"message": "hi"},
            "extension": {"kind": "chat"},
            "metadata": {},
        }
    )
    assert parsed.extension is not None
    assert parsed.extension.kind == "chat"
    assert parsed.extension.run_id is None


def test_unsupported_extension_kind_still_rejected():
    import pytest
    from app.websocket.chat_protocol import ChatProtocolError

    with pytest.raises(ChatProtocolError, match="unsupported extension kind"):
        parse_client_frame(
            {
                "type": "chat.start",
                "request_id": "req-bad",
                "input": {"message": "hi"},
                "extension": {"kind": "copilot"},
                "metadata": {},
            }
        )
