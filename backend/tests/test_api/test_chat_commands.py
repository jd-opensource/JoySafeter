from app.websocket.chat_commands import build_command_from_legacy_frame


def test_build_command_from_legacy_frame_drops_non_list_files_metadata():
    command = build_command_from_legacy_frame(
        {
            "type": "chat",
            "request_id": "req-legacy-files",
            "message": "hello",
            "metadata": {
                "mode": "apk-vulnerability",
                "files": "not-a-list",
            },
        }
    )

    assert command.files == []
    assert "files" not in command.metadata
    assert command.metadata["mode"] == "apk-vulnerability"


def test_build_command_from_legacy_frame_drops_invalid_files_entries():
    command = build_command_from_legacy_frame(
        {
            "type": "chat",
            "request_id": "req-legacy-files-invalid",
            "message": "hello",
            "metadata": {
                "files": ["bad-entry", 1, None],
            },
        }
    )

    assert command.files == []
    assert "files" not in command.metadata
