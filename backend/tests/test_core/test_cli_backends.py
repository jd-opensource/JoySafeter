from __future__ import annotations

import asyncio

import pytest

from app.core.agent.cli_backends.base import CLIMessage, CLIResult, RuntimeSession
from app.core.agent.cli_backends.claude_code import ClaudeCodeProvider
from app.core.agent.cli_backends.codex import CodexProvider
from app.core.agent.cli_backends.openclaw import OpenClawProvider
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
        messages=queue,
        result=future,
        _cancel_fn=mock_cancel,
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
        messages=queue,
        result=future,
        _inject_fn=mock_inject,
    )
    await session.inject_message("hello agent")
    assert injected == ["hello agent"]


# ── Codex provider tests ────────────────────────────────────────────


def test_codex_parse_notification_text():
    provider = CodexProvider()
    raw = {
        "jsonrpc": "2.0",
        "method": "codex/event",
        "params": {
            "msg": {"type": "agent_message", "message": "Hello from Codex"},
        },
    }
    messages = provider._parse_notification(raw)
    assert len(messages) == 1
    assert messages[0].type == "text"
    assert messages[0].content == "Hello from Codex"


def test_codex_parse_notification_tool_use():
    provider = CodexProvider()
    # Legacy codex/event format
    raw = {
        "jsonrpc": "2.0",
        "method": "codex/event",
        "params": {
            "msg": {
                "type": "exec_command_begin",
                "call_id": "cmd-1",
                "command": "ls -la",
            },
        },
    }
    messages = provider._parse_notification(raw)
    assert len(messages) == 1
    assert messages[0].type == "tool_use"
    assert messages[0].tool == "exec_command"
    assert messages[0].call_id == "cmd-1"
    assert messages[0].input == {"command": "ls -la"}


def test_codex_parse_notification_tool_use_v2():
    """Raw v2 item/started notification for commandExecution."""
    provider = CodexProvider()
    raw = {
        "jsonrpc": "2.0",
        "method": "item/started",
        "params": {
            "item": {
                "type": "commandExecution",
                "id": "item-42",
                "command": "git status",
            },
        },
    }
    messages = provider._parse_notification(raw)
    assert len(messages) == 1
    assert messages[0].type == "tool_use"
    assert messages[0].tool == "exec_command"
    assert messages[0].call_id == "item-42"
    assert messages[0].input == {"command": "git status"}


def test_codex_parse_response_result():
    """item/completed with agentMessage yields a text CLIMessage."""
    provider = CodexProvider()
    raw = {
        "jsonrpc": "2.0",
        "method": "item/completed",
        "params": {
            "item": {
                "type": "agentMessage",
                "id": "msg-99",
                "text": "All done!",
            },
        },
    }
    messages = provider._parse_notification(raw)
    assert len(messages) == 1
    assert messages[0].type == "text"
    assert messages[0].content == "All done!"


def test_codex_parse_unknown_event():
    provider = CodexProvider()
    raw = {
        "jsonrpc": "2.0",
        "method": "some/unknown/method",
        "params": {},
    }
    messages = provider._parse_notification(raw)
    assert len(messages) == 0


# ── OpenClaw provider tests ─────────────────────────────────────────


def test_openclaw_parse_message_event():
    provider = OpenClawProvider()
    line = '{"type": "text", "text": "Analyzing your code..."}'
    messages = provider._parse_line(line)
    assert len(messages) == 1
    assert messages[0].type == "text"
    assert messages[0].content == "Analyzing your code..."


def test_openclaw_parse_tool_call_event():
    provider = OpenClawProvider()
    line = '{"type": "tool_use", "tool": "Bash", "callId": "tc-1", "input": {"command": "pwd"}}'
    messages = provider._parse_line(line)
    assert len(messages) == 1
    assert messages[0].type == "tool_use"
    assert messages[0].tool == "Bash"
    assert messages[0].call_id == "tc-1"
    assert messages[0].input == {"command": "pwd"}


def test_openclaw_parse_tool_result_event():
    provider = OpenClawProvider()
    line = '{"type": "tool_result", "tool": "Bash", "callId": "tc-1", "text": "/workspace"}'
    messages = provider._parse_line(line)
    assert len(messages) == 1
    assert messages[0].type == "tool_result"
    assert messages[0].tool == "Bash"
    assert messages[0].call_id == "tc-1"
    assert messages[0].output == "/workspace"


def test_openclaw_parse_error_event():
    provider = OpenClawProvider()
    line = '{"type": "error", "text": "Rate limit exceeded"}'
    messages = provider._parse_line(line)
    assert len(messages) == 1
    assert messages[0].type == "error"
    assert messages[0].content == "Rate limit exceeded"


def test_openclaw_parse_error_event_structured():
    """Error with structured error object (PaperClip format)."""
    provider = OpenClawProvider()
    line = '{"type": "error", "error": {"name": "RateLimitError", "data": {"message": "Too many requests"}}}'
    messages = provider._parse_line(line)
    assert len(messages) == 1
    assert messages[0].type == "error"
    assert messages[0].content == "Too many requests"


def test_openclaw_parse_done_event():
    """step_finish events produce a text marker."""
    provider = OpenClawProvider()
    line = '{"type": "step_finish", "usage": {"input_tokens": 100, "output_tokens": 50}}'
    messages = provider._parse_line(line)
    assert len(messages) == 1
    assert messages[0].type == "text"
    assert messages[0].content == "[step finished]"


def test_openclaw_parse_unknown_event():
    provider = OpenClawProvider()
    line = '{"type": "some_future_event", "data": "whatever"}'
    messages = provider._parse_line(line)
    assert len(messages) == 0


def test_openclaw_parse_non_json_line():
    provider = OpenClawProvider()
    messages = provider._parse_line("INFO: starting agent...")
    assert len(messages) == 0


# ── Registry integration ────────────────────────────────────────────


def test_registry_all_providers():
    reg = RuntimeProviderRegistry()
    reg.register(ClaudeCodeProvider())
    reg.register(CodexProvider())
    reg.register(OpenClawProvider())

    providers = reg.list_providers()
    assert "claude_code" in providers
    assert "codex" in providers
    assert "openclaw" in providers
    assert len(providers) == 3

    assert reg.get("codex").provider_type == "codex"
    assert reg.get("openclaw").provider_type == "openclaw"
