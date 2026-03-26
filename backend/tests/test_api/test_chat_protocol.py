import pytest

from app.websocket.chat_protocol import (
    ChatProtocolError,
    ParsedChatStartFrame,
    parse_client_frame,
)


def test_parse_standard_chat_start_frame():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-1",
            "thread_id": None,
            "graph_id": None,
            "input": {"message": "hello", "files": []},
            "extension": None,
            "metadata": {},
        }
    )

    assert isinstance(parsed, ParsedChatStartFrame)
    assert parsed.request_id == "req-1"
    assert parsed.input.message == "hello"
    assert parsed.extension is None


def test_parse_skill_creator_extension_frame():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-2",
            "input": {"message": "build a skill", "files": []},
            "extension": {
                "kind": "skill_creator",
                "run_id": "123e4567-e89b-12d3-a456-426614174000",
                "edit_skill_id": "skill-42",
            },
            "metadata": {},
        }
    )

    assert parsed.extension is not None
    assert parsed.extension.kind == "skill_creator"
    assert parsed.extension.edit_skill_id == "skill-42"


def test_reserved_metadata_control_keys_are_rejected():
    try:
        parse_client_frame(
            {
                "type": "chat.start",
                "request_id": "req-3",
                "input": {"message": "hello"},
                "extension": None,
                "metadata": {"mode": "apk-vulnerability"},
            }
        )
    except ChatProtocolError as exc:
        assert exc.message == "reserved metadata keys are not allowed"
        assert exc.request_id == "req-3"
    else:
        raise AssertionError("expected ChatProtocolError")


def test_metadata_files_key_is_rejected_for_typed_chat_start():
    with pytest.raises(ChatProtocolError) as exc:
        parse_client_frame(
            {
                "type": "chat.start",
                "request_id": "req-files",
                "input": {"message": "hello", "files": []},
                "extension": None,
                "metadata": {
                    "files": [{"filename": "notes.md", "path": "/tmp/notes.md"}],
                },
            }
        )

    assert exc.value.message == "reserved metadata keys are not allowed"
    assert exc.value.request_id == "req-files"


def test_parse_ping_frame_passes_through():
    parsed = parse_client_frame({"type": "ping"})
    assert isinstance(parsed, dict)
    assert parsed.get("type") == "ping"


def test_parse_chat_resume_and_stop_return_dicts():
    assert parse_client_frame({"type": "chat.resume", "request_id": "req-r"}).get("type") == "chat.resume"
    assert parse_client_frame({"type": "chat.stop", "request_id": "req-s"}).get("type") == "chat.stop"


def test_malformed_chat_start_missing_input_raises():
    with pytest.raises(ChatProtocolError) as exc:
        parse_client_frame({"type": "chat.start", "request_id": "req-bad"})

    assert "input" in exc.value.message.lower()
    assert exc.value.request_id == "req-bad"
