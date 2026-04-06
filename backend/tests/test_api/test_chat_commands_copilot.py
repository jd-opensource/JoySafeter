"""Tests for copilot command dispatch."""
from app.websocket.chat_commands import build_command_from_parsed_frame, CopilotTurnCommand, ChatRunTurnCommand, SkillCreatorTurnCommand
from app.websocket.chat_protocol import ParsedChatStartFrame, ParsedChatInput, ParsedCopilotExtension


def test_copilot_extension_produces_copilot_turn_command():
    frame = ParsedChatStartFrame(
        request_id="req-1",
        thread_id=None,
        graph_id=None,
        input=ParsedChatInput(message="Build RAG", files=[], model=None),
        extension=ParsedCopilotExtension(
            kind="copilot",
            run_id="run-123",
            graph_context={"nodes": [], "edges": []},
            conversation_history=[{"role": "user", "content": "hi"}],
            mode="deepagents",
        ),
        metadata={},
    )
    cmd = build_command_from_parsed_frame(frame)
    assert isinstance(cmd, CopilotTurnCommand)
    assert cmd.run_id == "run-123"
    assert cmd.graph_context == {"nodes": [], "edges": []}
    assert cmd.conversation_history == [{"role": "user", "content": "hi"}]
    assert cmd.mode == "deepagents"
    assert cmd.message == "Build RAG"


def test_no_extension_still_standard():
    frame = ParsedChatStartFrame(
        request_id="req-2",
        thread_id=None,
        graph_id=None,
        input=ParsedChatInput(message="hello", files=[], model=None),
        extension=None,
        metadata={},
    )
    cmd = build_command_from_parsed_frame(frame)
    assert not isinstance(cmd, CopilotTurnCommand)
    assert not isinstance(cmd, SkillCreatorTurnCommand)


def test_chat_extension_still_chat_run():
    from app.websocket.chat_protocol import ParsedChatExtension
    frame = ParsedChatStartFrame(
        request_id="req-3",
        thread_id=None,
        graph_id=None,
        input=ParsedChatInput(message="hello", files=[], model=None),
        extension=ParsedChatExtension(kind="chat", run_id="r1"),
        metadata={},
    )
    cmd = build_command_from_parsed_frame(frame)
    assert isinstance(cmd, ChatRunTurnCommand)
