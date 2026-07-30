import importlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.joysafeter_orchestrator.grpc import server
from app.joysafeter_orchestrator.events.event_mapping import map_harness_event
from app.joysafeter_orchestrator.kernel import everos_bridge
from app.joysafeter_orchestrator.runtime.codex_adapter import CodexAdapter

extract_agent_skill = importlib.import_module(
    "app.everos.memory.strategies.extract_agent_skill"
)


class _Agent:
    engine_kind = "claude"
    system_prompt = "Use EverOS memory when helpful."


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ProjectSlugDb:
    async def execute(self, statement):
        return _ScalarResult("test")


def _harness_input(**overrides):
    base = dict(
        prompt="hello",
        system_prompt="system",
        env={},
        secrets={"ANTHROPIC_MODEL": "Claude-Opus-4.6"},
        permission_mode="bypassPermissions",
        model=None,
        mcp_servers=[],
        skill_archives=[],
        custom_tools=[],
        memory_mounts=[],
        memory_system_prompt=None,
        file_mounts=[],
        file_refs=[],
        allowed_tools=[],
        ask_tools=[],
        repos=[],
        session_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_setup_harness_task_has_id_for_history_builder():
    session_id = uuid.uuid4()

    task = server._build_setup_harness_task(_Agent(), session_id)

    assert task.id == session_id
    assert task.prompt == ""
    assert task.system_prompt == "Use EverOS memory when helpful."


def test_setup_sandbox_carries_secrets_without_cli_model():
    setup = server._build_setup_sandbox(
        _harness_input(),
        _Agent(),
    )

    assert not setup.HasField("model")
    assert setup.secrets["ANTHROPIC_MODEL"] == "Claude-Opus-4.6"


def test_start_task_carries_secrets_without_cli_model():
    start = server._build_start_task(
        uuid.uuid4(),
        _harness_input(),
        SimpleNamespace(timeout_sec=None),
        SimpleNamespace(task_default_timeout=60),
        agent=_Agent(),
    )

    assert not start.HasField("model")
    assert start.secrets["ANTHROPIC_MODEL"] == "Claude-Opus-4.6"


def test_runner_idle_does_not_close_session_before_task_result():
    assert server._should_close_session_on_runner_idle(
        task_done=False,
        requires_action_pending=False,
    ) is False


def test_runner_idle_closes_session_after_task_result():
    assert server._should_close_session_on_runner_idle(
        task_done=True,
        requires_action_pending=False,
    ) is True


async def test_everos_bridge_project_scope_uses_project_slug_and_id():
    project_id = await everos_bridge._resolve_everos_project_id(
        _ProjectSlugDb(),
        "55c665e3-5fe7-4e26-a11b-e6bf095d1a07",
    )

    assert project_id == "test__55c665e3-5fe7-4e26-a11b-e6bf095d1a07"


async def test_everos_bridge_uses_session_id_and_user_name_owner(monkeypatch):
    task_id = uuid.UUID("019f7e52-49d0-7c02-9dab-d364a1538b16")
    session_id = uuid.UUID("019f64b7-bdb8-7520-a780-ecc5fa152549")
    posted_payloads = []

    class _BridgeDb:
        async def get(self, model, key):
            assert model.__name__ == "JoySafeterTask"
            assert key == task_id
            return SimpleNamespace(
                id=task_id,
                project_id="e032a643-5415-4390-be97-4ac225e500f2",
                agent_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                prompt="remember this",
            )

    async def fake_project_id(db, project_id):
        return "default__e032a643-5415-4390-be97-4ac225e500f2"

    async def fake_user_id(db, session_id_arg):
        assert session_id_arg == session_id
        return "huajie_Sun"

    async def fake_latest_seq(db, session_id_arg):
        return 0

    async def fake_events(db, session_id_arg, *, after_seq):
        return [
            _event(1, "agent.message", {"content": "stored"}),
        ]

    async def fake_post(payload):
        posted_payloads.append(payload)

    monkeypatch.setattr(everos_bridge, "_resolve_everos_project_id", fake_project_id)
    monkeypatch.setattr(everos_bridge, "_resolve_everos_user_id", fake_user_id)
    monkeypatch.setattr(everos_bridge, "_latest_status_running_seq", fake_latest_seq)
    monkeypatch.setattr(everos_bridge, "_list_agent_events", fake_events)
    monkeypatch.setattr(everos_bridge, "_post_to_everos", fake_post)

    await everos_bridge.sync_task_to_everos_agent_memory(
        _BridgeDb(),
        task_id=task_id,
        session_id=session_id,
    )

    assert posted_payloads
    assert posted_payloads[0]["session_id"] == str(session_id)
    assert posted_payloads[0]["messages"][0]["sender_id"] == "huajie_Sun"


def test_runner_idle_does_not_close_session_during_control_request():
    assert server._should_close_session_on_runner_idle(
        task_done=True,
        requires_action_pending=True,
    ) is False


def _event(seq: int, event_type: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"event-{seq}",
        seq=seq,
        event_type=event_type,
        payload=payload,
        created_at=datetime(2026, 7, 9, 12, 0, tzinfo=UTC) + timedelta(seconds=seq),
    )


@pytest.mark.parametrize("engine_kind", ["claude", "codex", "native"])
def test_setup_sandbox_carries_everos_env_for_all_engines(engine_kind):
    setup = server._build_setup_sandbox(
        _harness_input(
            env={
                "EVEROS_BASE_URL": "http://host.docker.internal:8000/api/v1/everos_memory",
                "EVEROS_APP_ID": "joysafeter",
                "EVEROS_PROJECT_ID": "project-1",
                "EVEROS_SESSION_ID": "session-1",
                "EVEROS_USER_ID": "user-1",
                "EVEROS_AGENT_ID": "agent-1",
            }
        ),
        SimpleNamespace(
            engine_kind=engine_kind,
            system_prompt="Use EverOS memory when helpful.",
        ),
    )

    assert setup.provider == engine_kind
    assert setup.env["EVEROS_BASE_URL"] == "http://host.docker.internal:8000/api/v1/everos_memory"
    assert setup.env["EVEROS_APP_ID"] == "joysafeter"
    assert setup.env["EVEROS_PROJECT_ID"] == "project-1"
    assert setup.env["EVEROS_SESSION_ID"] == "session-1"
    assert setup.env["EVEROS_USER_ID"] == "user-1"
    assert setup.env["EVEROS_AGENT_ID"] == "agent-1"


@pytest.mark.parametrize("engine_kind", ["claude", "codex", "native"])
def test_engine_message_events_convert_to_everos_agent_messages(engine_kind):
    if engine_kind == "codex":
        payload = CodexAdapter()._assistant_text_event("codex remembered this")
    else:
        payload = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": f"{engine_kind} remembered this"}
                ]
            },
        }

    mapped = map_harness_event(payload, custom_tool_names=set(), mcp_server_names=set())
    assert mapped == [
        (
            "agent.message",
            {
                "content": [
                    {
                        "type": "text",
                        "text": f"{engine_kind} remembered this",
                    }
                ]
            },
        )
    ]

    messages = everos_bridge.build_agent_memory_messages(
        task_prompt=f"{engine_kind} task",
        session_events=[
            _event(1, event_type, event_payload)
            for event_type, event_payload in mapped
        ],
        user_id="user-1",
        agent_id=f"{engine_kind}-agent",
    )

    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["sender_id"] == f"{engine_kind}-agent"
    assert messages[1]["content"] == f"{engine_kind} remembered this"


@pytest.mark.parametrize("engine_kind", ["claude", "codex", "native"])
async def test_everos_bridge_posts_completed_task_memory_for_all_engines(
    monkeypatch, engine_kind
):
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    posted_payloads = []

    class _BridgeDb:
        async def get(self, model, key):
            assert model.__name__ == "JoySafeterTask"
            assert key == task_id
            return SimpleNamespace(
                id=task_id,
                project_id="project-1",
                agent_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                engine_kind=engine_kind,
                prompt=f"{engine_kind} task",
            )

    async def fake_project_id(db, project_id):
        return "project-1"

    async def fake_user_id(db, session_id_arg):
        assert session_id_arg == session_id
        return "user-1"

    async def fake_latest_seq(db, session_id_arg):
        assert session_id_arg == session_id
        return 0

    async def fake_events(db, session_id_arg, *, after_seq):
        assert session_id_arg == session_id
        assert after_seq == 0
        return [
            _event(
                1,
                "agent.message",
                {"content": [{"type": "text", "text": f"{engine_kind} output"}]},
            )
        ]

    async def fake_post(payload):
        posted_payloads.append(payload)

    monkeypatch.setattr(everos_bridge, "_resolve_everos_project_id", fake_project_id)
    monkeypatch.setattr(everos_bridge, "_resolve_everos_user_id", fake_user_id)
    monkeypatch.setattr(everos_bridge, "_latest_status_running_seq", fake_latest_seq)
    monkeypatch.setattr(everos_bridge, "_list_agent_events", fake_events)
    monkeypatch.setattr(everos_bridge, "_post_to_everos", fake_post)

    await everos_bridge.sync_task_to_everos_agent_memory(
        _BridgeDb(),
        task_id=task_id,
        session_id=session_id,
    )

    assert len(posted_payloads) == 1
    payload = posted_payloads[0]
    assert payload["app_id"] == "joysafeter"
    assert payload["project_id"] == "project-1"
    assert payload["session_id"] == str(session_id)
    assert payload["messages"][0]["content"] == f"{engine_kind} task"
    assert payload["messages"][1]["content"] == f"{engine_kind} output"


def test_session_events_are_converted_to_structured_everos_agent_messages():
    messages = everos_bridge.build_agent_memory_messages(
        task_prompt="create a report",
        session_events=[
            _event(
                1,
                "agent.tool_use",
                {"name": "Bash", "input": {"command": "pwd"}, "_call_id": "toolu_1"},
            ),
            _event(
                2,
                "agent.tool_result",
                {
                    "tool_use_id": "toolu_1",
                    "content": [{"type": "text", "text": "/workspace"}],
                },
            ),
            _event(
                3,
                "agent.message",
                {"content": [{"type": "text", "text": "done"}]},
            ),
        ],
        user_id="user-1",
        agent_id="agent-1",
    )

    assert messages[0]["role"] == "user"
    assert messages[0]["sender_id"] == "user-1"
    assert messages[0]["content"] == "create a report"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["sender_id"] == "agent-1"
    assert messages[1]["tool_calls"] == [
        {
            "id": "toolu_1",
            "type": "function",
            "function": {"name": "Bash", "arguments": '{"command":"pwd"}'},
        }
    ]
    assert messages[2]["role"] == "tool"
    assert messages[2]["sender_id"] == "agent-1"
    assert messages[2]["tool_call_id"] == "toolu_1"
    assert messages[2]["content"] == "/workspace"
    assert messages[3]["role"] == "assistant"
    assert messages[3]["content"] == "done"


def test_session_events_without_agent_activity_are_not_submitted():
    messages = everos_bridge.build_agent_memory_messages(
        task_prompt="hello",
        session_events=[_event(1, "session.status_idle", {})],
        user_id="user-1",
        agent_id="agent-1",
    )

    assert messages == []


@pytest.mark.asyncio
async def test_load_target_case_waits_for_cascade_index(monkeypatch):
    calls = 0
    expected = object()

    async def fake_find_by_owner_entry(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return None
        return expected

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(
        extract_agent_skill.agent_case_repo,
        "find_by_owner_entry",
        fake_find_by_owner_entry,
    )
    monkeypatch.setattr(
        extract_agent_skill,
        "asyncio",
        SimpleNamespace(sleep=no_sleep),
        raising=False,
    )

    result = await extract_agent_skill._load_target_case(
        "agent-1",
        "case-1",
        app_id="joysafeter",
        project_id="project-1",
    )

    assert result is expected
    assert calls == 3


@pytest.mark.asyncio
async def test_extract_agent_skill_enables_maturity_scoring(monkeypatch):
    captured: dict[str, object] = {}

    class _Lock:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Extractor:
        def __init__(self, *, llm):
            self.llm = llm

        async def aextract(self, case, *, existing_relevant_skills, supporting_cases, **kwargs):
            captured.update(kwargs)
            return []

    async def noop(*args, **kwargs):
        return None

    async def fake_llm(_project_id):
        return object()

    target_case = SimpleNamespace(
        entry_id="case-1",
        timestamp=datetime(2026, 7, 22, tzinfo=UTC),
        task_intent="Fix a flaky integration test",
        approach="1. Inspect the failure\n2. Patch the root cause",
        quality_score=0.9,
        key_insight="Trace the failing boundary first",
    )

    async def load_target_case(*args, **kwargs):
        return target_case

    async def select_existing_skills(*args, **kwargs):
        return []

    async def select_supporting_cases(*args, **kwargs):
        return []

    monkeypatch.setattr(extract_agent_skill, "get_partition_lock", lambda *args: _Lock())
    monkeypatch.setattr(extract_agent_skill, "_ensure_cluster_exists", noop)
    monkeypatch.setattr(extract_agent_skill, "_load_target_case", load_target_case)
    monkeypatch.setattr(extract_agent_skill, "_select_existing_skills", select_existing_skills)
    monkeypatch.setattr(extract_agent_skill, "_select_supporting_cases", select_supporting_cases)
    monkeypatch.setattr(extract_agent_skill, "get_project_llm_client", fake_llm)
    monkeypatch.setattr(extract_agent_skill, "bind_json_schema", lambda llm, _schema: llm)
    monkeypatch.setattr(extract_agent_skill, "AgentSkillExtractor", _Extractor)
    monkeypatch.setattr(extract_agent_skill, "_get_writer", lambda: object())

    await extract_agent_skill.extract_agent_skill(
        extract_agent_skill.SkillClusterUpdated(
            case_entry_id="case-1",
            cluster_id="cluster-1",
            agent_id="agent-1",
            app_id="joysafeter",
            project_id="project-1",
        ),
        SimpleNamespace(),
    )

    assert captured["skip_maturity_scoring"] is False


@pytest.mark.asyncio
async def test_persist_agent_skill_injects_cluster_and_creation_timestamps(monkeypatch):
    first_write_at = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)
    second_write_at = datetime(2026, 7, 22, 10, 30, tzinfo=UTC)
    writes = []

    class _Writer:
        async def write_main(self, *args, frontmatter, body, **kwargs):
            writes.append((frontmatter, body))

    class _Reader:
        async def read_main(self, *args, **kwargs):
            if not writes:
                return None
            return writes[-1][0], writes[-1][1]

    now_values = iter([first_write_at, second_write_at])

    monkeypatch.setattr(extract_agent_skill, "_get_reader", lambda: _Reader())
    monkeypatch.setattr(
        extract_agent_skill,
        "get_now_with_timezone",
        lambda: next(now_values),
    )

    skill = extract_agent_skill.AlgoAgentSkill(
        id="skill-1",
        cluster_id="ignored-by-everos",
        name="debug_json_failures",
        description="Debug JSON extraction failures",
        content="Check dead-letter payloads before changing prompts.",
        confidence=0.8,
        maturity_score=0.7,
        source_case_ids=["ac_20260722_00000001"],
    )

    await extract_agent_skill._persist_skill(
        _Writer(),
        skill,
        agent_id="agent-1",
        cluster_id="cl_abc123",
        app_id="joysafeter",
        project_id="project-1",
    )
    await extract_agent_skill._persist_skill(
        _Writer(),
        skill,
        agent_id="agent-1",
        cluster_id="cl_abc123",
        app_id="joysafeter",
        project_id="project-1",
    )

    first_frontmatter = writes[0][0]
    second_frontmatter = writes[1][0]

    assert first_frontmatter.cluster_id == "cl_abc123"
    assert first_frontmatter.created_at == first_write_at
    assert first_frontmatter.updated_at == first_write_at
    assert second_frontmatter.cluster_id == "cl_abc123"
    assert second_frontmatter.created_at == first_write_at
    assert second_frontmatter.updated_at == second_write_at
