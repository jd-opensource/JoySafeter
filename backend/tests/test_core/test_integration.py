"""
Integration test: validates the full mission-to-execution pipeline.

Exercises the complete flow without a live database or Docker daemon:
  Mission creation → assign to agent →
  dispatch (creates execution) → verify event sourcing → verify reducer →
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
    CredentialInjector,
    RuntimeConfigInjector,
)
from app.core.agent.cli_backends.registry import RuntimeProviderRegistry
from app.schemas.execution import (
    ExecutionSummary,
    MissionSummary,
)
from app.services.execution_lifecycle_service import build_execution_prompt
from app.services.execution_reducer import apply_execution_event, make_initial_projection
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

    mission = MissionSummary(
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
    data = mission.model_dump()
    assert data["title"] == "Fix bug"

    execution = ExecutionSummary(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_id="user-1",
        source="mission",
        status="running",
        runtime_type="claude_code",
        last_seq=5,
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
    )
    data = execution.model_dump()
    assert data["source"] == "mission"
    assert data["last_seq"] == 5


# ---------------------------------------------------------------------------
# 2. Prompt building from mission
# ---------------------------------------------------------------------------


def test_prompt_building_integration():
    """Verify prompt building produces valid agent instructions."""
    mission = MagicMock()
    mission.title = "Implement OAuth2 login"
    mission.description = "Add Google OAuth2 provider to the auth module."
    mission.objective = "Users can log in with Google accounts."
    mission.tags = ["auth", "oauth", "backend"]

    prompt = build_execution_prompt(mission)

    assert "# Mission: Implement OAuth2 login" in prompt
    assert "Google OAuth2" in prompt
    assert "Users can log in" in prompt
    assert "auth" in prompt
    assert "oauth" in prompt


# ---------------------------------------------------------------------------
# 3. Registry + provider lookup
# ---------------------------------------------------------------------------


def test_registry_lifecycle():
    """Register a provider, look it up, list it."""
    reg = RuntimeProviderRegistry()
    provider = ClaudeCodeProvider(executable_path="/usr/bin/claude")
    reg.register(provider)

    assert reg.get("claude_code") is provider
    assert "claude_code" in reg.list_providers()

    with pytest.raises(ValueError):
        reg.get("nonexistent_provider")


# ---------------------------------------------------------------------------
# 4. Container + injection pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_container_injection_pipeline():
    """Create container → inject credentials → inject skills → inject config."""
    svc = FakeContainerService()
    exec_id = uuid.uuid4()

    container = await svc.create_container(execution_id=exec_id)
    assert container.status == "running"
    assert container.container_id.startswith("fake-ctr-")

    # Build credentials env (no longer writes to container filesystem)
    cred_injector = CredentialInjector()
    env = cred_injector.build_env(
        {
            "ANTHROPIC_API_KEY": "sk-test-key",
            "GITHUB_TOKEN": "ghp-test",
        }
    )
    assert env == {"ANTHROPIC_API_KEY": "sk-test-key", "GITHUB_TOKEN": "ghp-test"}

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
# 5. Event sourcing + reducer pipeline
# ---------------------------------------------------------------------------


def test_event_sourcing_full_lifecycle():
    """Walk through a complete execution event sequence and verify projection."""
    proj = make_initial_projection(
        {"source": "mission", "mission_id": "m-1", "agent_profile_id": "a-1"},
        "queued",
    )
    assert proj["status"] == "queued"
    assert proj["messages"] == []

    # Execution starts
    proj = apply_execution_event(
        proj,
        event_type="execution_started",
        payload={"container_id": "ctr-abc", "session_id": "s-1"},
        status="running",
    )
    assert proj["container_id"] == "ctr-abc"

    # User prompt sent
    proj = apply_execution_event(
        proj,
        event_type="prompt_sent",
        payload={"message": {"role": "user", "content": "Fix the login bug"}},
        status="running",
    )
    assert len(proj["messages"]) == 1

    # Agent thinks
    proj = apply_execution_event(
        proj,
        event_type="thinking",
        payload={"content": "Let me analyze the auth module..."},
        status="running",
    )
    assert proj["meta"]["last_thinking"] == "Let me analyze the auth module..."

    # Agent responds
    proj = apply_execution_event(
        proj,
        event_type="assistant_text",
        payload={"message": {"role": "assistant", "content": "Found the issue", "id": "a1"}},
        status="running",
    )
    assert len(proj["messages"]) == 2

    # Content delta
    proj = apply_execution_event(
        proj,
        event_type="content_delta",
        payload={"delta": " in auth.py", "message_id": "a1"},
        status="running",
    )
    assert proj["messages"][-1]["content"] == "Found the issue in auth.py"

    # Tool use
    proj = apply_execution_event(
        proj,
        event_type="tool_use_start",
        payload={"tool": {"name": "Edit", "call_id": "t1", "input": {"file": "auth.py"}, "status": "running"}},
        status="running",
    )
    assert len(proj["tool_calls"]) == 1
    assert proj["tool_calls"][0]["status"] == "running"

    proj = apply_execution_event(
        proj,
        event_type="tool_use_end",
        payload={"call_id": "t1", "output": "File edited successfully"},
        status="running",
    )
    assert proj["tool_calls"][0]["status"] == "completed"

    # Approval flow
    proj = apply_execution_event(
        proj,
        event_type="approval_requested",
        payload={"tool": "Bash", "command": "git push"},
        status="approval_wait",
    )
    assert "pending_approval" in proj["meta"]

    proj = apply_execution_event(
        proj,
        event_type="approval_resolved",
        payload={"approved": True},
        status="running",
    )
    assert "pending_approval" not in proj["meta"]

    # Artifact
    proj = apply_execution_event(
        proj,
        event_type="artifact_created",
        payload={"artifact": {"type": "file", "path": "/workspace/auth.py"}},
        status="running",
    )
    assert len(proj["artifacts"]) == 1

    # Completion
    proj = apply_execution_event(
        proj,
        event_type="execution_completed",
        payload={"result_summary": {"files_changed": 2, "tests_passed": True}},
        status="completed",
    )
    assert proj["status"] == "completed"
    assert proj["meta"]["completed"] is True
    assert proj["meta"]["result_summary"]["files_changed"] == 2


# ---------------------------------------------------------------------------
# 6. WebSocket subscription manager
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


# ---------------------------------------------------------------------------
# 10. End-to-end data flow validation
# ---------------------------------------------------------------------------


def test_end_to_end_data_flow():
    """Validate the complete data flow from mission to execution result.

    This test verifies that data flows correctly through all layers:
    Mission → prompt → execution events → reducer → final projection.
    """
    # 1. Build prompt from mission
    mission = MagicMock()
    mission.title = "Add rate limiting"
    mission.description = "Implement token bucket rate limiter for API endpoints."
    mission.objective = "Prevent API abuse."
    mission.tags = ["security", "api"]

    prompt = build_execution_prompt(mission)
    assert "rate limiting" in prompt.lower()

    # 2. Initialize projection
    proj = make_initial_projection(
        {"source": "mission", "mission_id": "m-1"},
        "queued",
    )

    # 3. Simulate execution events
    events = [
        ("execution_started", {"container_id": "ctr-1", "session_id": "s-1"}, "running"),
        ("prompt_sent", {"message": {"role": "user", "content": prompt}}, "running"),
        (
            "assistant_text",
            {"message": {"role": "assistant", "content": "Implementing rate limiter", "id": "a1"}},
            "running",
        ),
        (
            "tool_use_start",
            {"tool": {"name": "Write", "call_id": "t1", "input": {"file": "rate_limiter.py"}, "status": "running"}},
            "running",
        ),
        ("tool_use_end", {"call_id": "t1", "output": "File written"}, "running"),
        ("execution_completed", {"result_summary": {"files_created": 1}}, "completed"),
    ]

    for event_type, payload, status in events:
        proj = apply_execution_event(proj, event_type=event_type, payload=payload, status=status)

    # 4. Verify final state
    assert proj["status"] == "completed"
    assert proj["container_id"] == "ctr-1"
    assert proj["session_id"] == "s-1"
    assert len(proj["messages"]) == 2  # user prompt + assistant text
    assert len(proj["tool_calls"]) == 1
    assert proj["tool_calls"][0]["status"] == "completed"
    assert proj["meta"]["completed"] is True
    assert proj["meta"]["result_summary"]["files_created"] == 1

    # 5. Verify immutability — original events didn't mutate
    assert events[0][1]["container_id"] == "ctr-1"  # unchanged
