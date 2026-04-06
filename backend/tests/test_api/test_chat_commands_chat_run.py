from app.websocket.chat_commands import ChatRunTurnCommand, build_command_from_parsed_frame
from app.websocket.chat_protocol import parse_client_frame


def test_chat_extension_produces_chat_run_turn_command():
    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-1",
            "thread_id": "t-1",
            "input": {"message": "hello"},
            "extension": {"kind": "chat", "run_id": "run-xyz"},
            "metadata": {},
        }
    )
    command = build_command_from_parsed_frame(parsed)
    assert isinstance(command, ChatRunTurnCommand)
    assert command.run_id == "run-xyz"
    assert command.message == "hello"


def test_no_extension_still_produces_standard_command():
    from app.websocket.chat_commands import StandardChatTurnCommand

    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-2",
            "input": {"message": "hi"},
            "extension": None,
            "metadata": {},
        }
    )
    command = build_command_from_parsed_frame(parsed)
    assert isinstance(command, StandardChatTurnCommand)
    assert not isinstance(command, ChatRunTurnCommand)


def test_skill_creator_extension_still_produces_skill_creator_command():
    from app.websocket.chat_commands import SkillCreatorTurnCommand

    parsed = parse_client_frame(
        {
            "type": "chat.start",
            "request_id": "req-3",
            "input": {"message": "create skill"},
            "extension": {"kind": "skill_creator", "run_id": "run-sc", "edit_skill_id": "sk-1"},
            "metadata": {},
        }
    )
    command = build_command_from_parsed_frame(parsed)
    assert isinstance(command, SkillCreatorTurnCommand)
    assert not isinstance(command, ChatRunTurnCommand)
    assert command.run_id == "run-sc"
    assert command.edit_skill_id == "sk-1"
