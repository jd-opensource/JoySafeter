from __future__ import annotations

import asyncio

import pytest

from app.core.agent.cli_backends.base import CLIMessage, CLIResult, RuntimeSession
from app.core.agent.cli_backends.claude_code import ClaudeCodeProvider
from app.core.agent.cli_backends.registry import RuntimeProviderRegistry


def test_cli_message_defaults():
    msg = CLIMessage(type="text", content="hello")
    assert msg.type == "text"
    assert msg.content == "hello"
    assert msg.tool == ""
    assert msg.input is None


def test_cli_result_defaults():
    result = CLIResult(status="completed", output="done")
    assert result.status == "completed"
    assert result.session_id == ""


def test_registry_register_and_get():
    reg = RuntimeProviderRegistry()
    provider = ClaudeCodeProvider()
    reg.register(provider)
    assert reg.get("claude_code") is provider
    assert "claude_code" in reg.list_providers()


def test_registry_unknown_provider():
    reg = RuntimeProviderRegistry()
    with pytest.raises(ValueError, match="Unknown runtime provider"):
        reg.get("nonexistent")


def test_claude_parse_text_event():
    provider = ClaudeCodeProvider()
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "Hello world"},
            ]
        },
    }
    messages = provider._parse_event(event)
    assert len(messages) == 1
    assert messages[0].type == "text"
    assert messages[0].content == "Hello world"


def test_claude_parse_tool_use_event():
    provider = ClaudeCodeProvider()
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "call-123",
                    "input": {"command": "ls"},
                },
            ]
        },
    }
    messages = provider._parse_event(event)
    assert len(messages) == 1
    assert messages[0].type == "tool_use"
    assert messages[0].tool == "Bash"
    assert messages[0].call_id == "call-123"
    assert messages[0].input == {"command": "ls"}


def test_claude_parse_thinking_event():
    provider = ClaudeCodeProvider()
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "Let me analyze..."},
            ]
        },
    }
    messages = provider._parse_event(event)
    assert len(messages) == 1
    assert messages[0].type == "thinking"
    assert messages[0].content == "Let me analyze..."


def test_claude_parse_mixed_content():
    provider = ClaudeCodeProvider()
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "hmm"},
                {"type": "text", "text": "I'll run a scan"},
                {"type": "tool_use", "name": "Bash", "id": "c1", "input": {"command": "nmap"}},
            ]
        },
    }
    messages = provider._parse_event(event)
    assert len(messages) == 3
    assert messages[0].type == "thinking"
    assert messages[1].type == "text"
    assert messages[2].type == "tool_use"


def test_claude_parse_tool_result_event():
    provider = ClaudeCodeProvider()
    event = {
        "type": "tool_result",
        "tool": "Bash",
        "call_id": "c1",
        "output": "scan complete",
    }
    messages = provider._parse_event(event)
    assert len(messages) == 1
    assert messages[0].type == "tool_result"
    assert messages[0].tool == "Bash"
    assert messages[0].output == "scan complete"


def test_claude_parse_unknown_event():
    provider = ClaudeCodeProvider()
    event = {"type": "unknown_event"}
    messages = provider._parse_event(event)
    assert len(messages) == 0


@pytest.mark.asyncio
async def test_runtime_session_iter_messages():
    queue: asyncio.Queue[CLIMessage | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()
    future: asyncio.Future[CLIResult] = loop.create_future()

    session = RuntimeSession(messages=queue, result=future)

    await queue.put(CLIMessage(type="text", content="hello"))
    await queue.put(CLIMessage(type="text", content="world"))
    await queue.put(None)

    collected = []
    async for msg in session.iter_messages():
        collected.append(msg.content)

    assert collected == ["hello", "world"]


@pytest.mark.asyncio
async def test_runtime_session_cancel():
    queue: asyncio.Queue[CLIMessage | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()
    future: asyncio.Future[CLIResult] = loop.create_future()

    cancelled = False
    async def mock_cancel():
        nonlocal cancelled
        cancelled = True

    session = RuntimeSession(
        messages=queue, result=future, _cancel_fn=mock_cancel,
    )
    await session.cancel()
    assert cancelled


@pytest.mark.asyncio
async def test_runtime_session_inject():
    queue: asyncio.Queue[CLIMessage | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()
    future: asyncio.Future[CLIResult] = loop.create_future()

    injected = []
    async def mock_inject(msg: str):
        injected.append(msg)

    session = RuntimeSession(
        messages=queue, result=future, _inject_fn=mock_inject,
    )
    await session.inject_message("hello agent")
    assert injected == ["hello agent"]
