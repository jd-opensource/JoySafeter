"""
Integration test: validates the full task-to-execution pipeline.

Exercises the complete flow without a live database or Docker daemon:
  Task creation → assign to agent →
  dispatch (creates execution) → verify container injection →
  verify subscription manager → verify cleanup lifecycle.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.agent.cli_backends.base import CLIMessage
from app.core.agent.cli_backends.claude_code import ClaudeCodeProvider
from app.core.agent.cli_backends.container_service import ContainerInfo
from app.core.agent.cli_backends.execution_runner import ExecutionRunner
from app.core.agent.cli_backends.injectors import (
    CLISkillInjector,
    RuntimeConfigInjector,
)
from app.schemas.task import TaskSummary
from app.websocket.execution_subscription_manager import ExecutionSubscriptionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws():
    ws = MagicMock()
    ws.send_text = AsyncMock()
    return ws


class FakeContainerService:
    """Records calls without touching Docker."""

    def __init__(self):
        self.calls: list[tuple[str, list]] = []
        self.created: list[str] = []
        self.removed: list[str] = []

    async def create_container(self, *, execution_id, config=None, env=None):
        cid = f"fake-ctr-{execution_id!s:.8}"
        self.created.append(cid)
        return ContainerInfo(
            container_id=cid,
            name=f"cli-agent-{execution_id!s:.12}",
            status="running",
            working_dir="/workspace",
        )

    async def exec_in_container(self, container_id, cmd, workdir=None):
        self.calls.append((container_id, cmd))
        return ""

    async def remove_container(self, container_id, force=True):
        self.removed.append(container_id)

    async def stop_container(self, container_id, timeout=10):
        pass

    async def copy_to_container(self, container_id, src, dest):
        pass


# ---------------------------------------------------------------------------
# 1. Schema validation
# ---------------------------------------------------------------------------


def test_schemas_round_trip():
    """Verify Pydantic schemas serialize/deserialize correctly."""
    # AgentProfileSummary removed in Task 1.8 — tested via agent schema tests instead

    task = TaskSummary(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        title="Fix bug",
        status="todo",
        priority="high",
        creator_id="user-1",
        position=0.0,
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
    )
    data = task.model_dump()
    assert data["title"] == "Fix bug"


# ---------------------------------------------------------------------------
# 3. Container + injection pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_container_injection_pipeline():
    """Create container → inject credentials → inject skills → inject config."""
    svc = FakeContainerService()
    exec_id = uuid.uuid4()

    container = await svc.create_container(execution_id=exec_id)
    assert container.status == "running"
    assert container.container_id.startswith("fake-ctr-")

    # Inject skills
    skill_injector = CLISkillInjector(svc)
    await skill_injector.inject(
        container.container_id,
        [
            {"name": "lint", "command": "ruff check ."},
            {"name": "test", "command": "pytest -x"},
        ],
    )
    assert len(svc.calls) == 3  # 1 mkdir + 2 skills

    # Inject CLAUDE.md config
    config_injector = RuntimeConfigInjector(svc)
    await config_injector.inject(
        container.container_id,
        instructions="Always write tests.",
        skill_names=["lint", "test"],
        working_dir="/workspace",
    )
    assert len(svc.calls) == 4  # + 1 config write


# ---------------------------------------------------------------------------
# 4. WebSocket subscription manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_manager_full_flow():
    """Subscribe, broadcast, unsubscribe, disconnect."""
    mgr = ExecutionSubscriptionManager()
    ws1 = _make_ws()
    ws2 = _make_ws()
    exec_id = str(uuid.uuid4())

    # Subscribe both
    await mgr.add_subscription(ws1, exec_id)
    await mgr.add_subscription(ws2, exec_id)

    # Broadcast event
    count = await mgr.broadcast_event(
        exec_id,
        {
            "type": "event",
            "execution_id": exec_id,
            "seq": 1,
            "event_type": "assistant_text",
            "data": {"content": "hello"},
        },
    )
    assert count == 2

    # Verify both received
    assert ws1.send_text.call_count == 1
    assert ws2.send_text.call_count == 1

    # Unsubscribe ws1
    mgr.remove_subscription(ws1, exec_id)
    count = await mgr.broadcast_event(exec_id, {"type": "event", "seq": 2})
    assert count == 1
    assert ws2.send_text.call_count == 2

    # Disconnect ws2
    mgr.disconnect(ws2)
    count = await mgr.broadcast_event(exec_id, {"type": "event", "seq": 3})
    assert count == 0


# ---------------------------------------------------------------------------
# 7. ExecutionRunner message mapping
# ---------------------------------------------------------------------------


def test_runner_message_mapping_pipeline():
    """Verify CLIMessage → event_type + payload mapping for all message types."""
    test_cases = [
        (CLIMessage(type="text", content="hello"), "assistant_text", {"content": "hello"}),
        (CLIMessage(type="thinking", content="hmm"), "thinking", {"content": "hmm"}),
        (
            CLIMessage(type="tool_use", tool="Bash", call_id="c1", input={"command": "ls"}),
            "tool_use_start",
            {"tool": {"name": "Bash", "call_id": "c1", "input": {"command": "ls"}, "status": "running"}},
        ),
        (
            CLIMessage(type="tool_result", tool="Bash", call_id="c1", output="file.txt"),
            "tool_use_end",
            {"call_id": "c1", "tool_name": "Bash", "output": "file.txt"},
        ),
        (CLIMessage(type="error", content="OOM"), "error", {"message": "OOM"}),
        (CLIMessage(type="artifact", content="data"), "artifact_created", {"artifact": {"content": "data"}}),
    ]

    for msg, expected_type, expected_payload in test_cases:
        assert ExecutionRunner._msg_to_event_type(msg) == expected_type
        assert ExecutionRunner._msg_to_payload(msg) == expected_payload


# ---------------------------------------------------------------------------
# 8. Claude Code NDJSON parsing
# ---------------------------------------------------------------------------


def test_claude_code_ndjson_parsing():
    """Verify ClaudeCodeProvider parses a realistic NDJSON event stream."""
    provider = ClaudeCodeProvider()

    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "Let me look at the code"},
                    {"type": "text", "text": "I'll fix the bug now"},
                    {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "grep -r 'login' ."}},
                ]
            },
        },
        {
            "type": "tool_result",
            "tool": "Bash",
            "call_id": "t1",
            "output": "auth/login.py:42: def login():",
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Found it. Applying fix..."},
                ]
            },
        },
    ]

    all_messages = []
    for event in events:
        all_messages.extend(provider._parse_event(event))

    assert len(all_messages) == 5
    assert all_messages[0].type == "thinking"
    assert all_messages[1].type == "text"
    assert all_messages[1].content == "I'll fix the bug now"
    assert all_messages[2].type == "tool_use"
    assert all_messages[2].tool == "Bash"
    assert all_messages[3].type == "tool_result"
    assert "auth/login.py" in all_messages[3].output
    assert all_messages[4].type == "text"


# ---------------------------------------------------------------------------
# 9. Container lifecycle tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_container_lifecycle():
    """Create → use → remove container, verify tracking."""
    svc = FakeContainerService()
    exec_id = uuid.uuid4()

    # Create
    container = await svc.create_container(execution_id=exec_id)
    assert len(svc.created) == 1

    # Use (exec commands)
    await svc.exec_in_container(container.container_id, ["echo", "hello"])
    assert len(svc.calls) == 1

    # Remove
    await svc.remove_container(container.container_id)
    assert len(svc.removed) == 1
    assert svc.removed[0] == container.container_id
