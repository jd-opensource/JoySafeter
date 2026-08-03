import importlib
import sys
from types import SimpleNamespace

import pytest

from app.everos.infra.ome.events import CronTick, ScopedManualTick
from app.everos.memory.language_policy import ChineseMemoryLLMClient
from app.everos.memory.strategies.reflect_episodes import reflect_episodes

reflect_strategy = importlib.import_module("app.everos.memory.strategies.reflect_episodes")

pytestmark = pytest.mark.no_db


def test_reflect_episodes_is_enabled_by_default() -> None:
    assert reflect_episodes.meta.enabled is True


def test_reflect_episodes_cron_runs_sunday_midnight() -> None:
    assert reflect_episodes.meta.trigger.expr == "0 0 * * sun"


def test_reflect_episodes_retries_three_times_after_failure() -> None:
    assert reflect_episodes.meta.max_retries == 3


@pytest.mark.asyncio
async def test_reflect_episodes_automatic_joysafeter_scope_uses_active_agents_and_sessions(monkeypatch):
    class _ClusterRepo:
        async def list_distinct_owners(self):
            return [
                ("agent-active", "agent", "joysafeter", "project-slug__project-1"),
                ("agent-archived", "agent", "joysafeter", "project-slug__project-1"),
                ("user-owner", "user", "joysafeter", "project-slug__project-1"),
                ("agent-other", "agent", "other-app", "project-slug__project-1"),
            ]

    calls = []

    async def _fake_run_reflection_for_owner(**kwargs):
        calls.append(
            {
                "owner_id": kwargs["owner_id"],
                "owner_type": kwargs["owner_type"],
                "app_id": kwargs["app_id"],
                "project_id": kwargs["project_id"],
                "active_session_ids": kwargs["active_session_ids"],
            }
        )
        return reflect_strategy.ReflectionOwnerResult(
            owner_id=kwargs["owner_id"],
            owner_type=kwargs["owner_type"],
            app_id=kwargs["app_id"],
            project_id=kwargs["project_id"],
            success_count=1,
            failure_count=0,
        )

    async def _fake_load_active_scopes(project_ids):
        assert project_ids == {"project-slug__project-1"}
        return {
            "project-slug__project-1": reflect_strategy._ActiveJoySafeterScopes(
                active_agent_ids={"agent-active"},
                active_session_ids={"session-active"},
            )
        }

    monkeypatch.setattr(reflect_strategy, "cluster_repo", _ClusterRepo())
    monkeypatch.setattr(reflect_strategy, "get_embedder", lambda: object())
    monkeypatch.setattr(reflect_strategy, "_run_reflection_for_owner", _fake_run_reflection_for_owner)
    monkeypatch.setattr(reflect_strategy, "_load_active_joysafeter_scopes", _fake_load_active_scopes, raising=False)

    await reflect_episodes(CronTick(strategy_name="reflect_episodes"), ctx=object())

    assert calls == [
        {
            "owner_id": "agent-active",
            "owner_type": "agent",
            "app_id": "joysafeter",
            "project_id": "project-slug__project-1",
            "active_session_ids": {"session-active"},
        },
        {
            "owner_id": "user-owner",
            "owner_type": "user",
            "app_id": "joysafeter",
            "project_id": "project-slug__project-1",
            "active_session_ids": {"session-active"},
        },
        {
            "owner_id": "agent-other",
            "owner_type": "agent",
            "app_id": "other-app",
            "project_id": "project-slug__project-1",
            "active_session_ids": None,
        },
    ]


@pytest.mark.asyncio
async def test_reflect_episodes_manual_active_only_empty_sessions_does_not_fall_back_to_all(monkeypatch):
    class _ClusterRepo:
        async def list_distinct_owners(self):
            return [("agent-active", "agent", "joysafeter", "project-1")]

    calls = []

    async def _fake_run_reflection_for_owner(**kwargs):
        calls.append(kwargs["active_session_ids"])
        return reflect_strategy.ReflectionOwnerResult(
            owner_id=kwargs["owner_id"],
            owner_type=kwargs["owner_type"],
            app_id=kwargs["app_id"],
            project_id=kwargs["project_id"],
            success_count=1,
            failure_count=0,
        )

    monkeypatch.setattr(reflect_strategy, "cluster_repo", _ClusterRepo())
    monkeypatch.setattr(reflect_strategy, "get_embedder", lambda: object())
    monkeypatch.setattr(reflect_strategy, "_run_reflection_for_owner", _fake_run_reflection_for_owner)

    await reflect_episodes(
        ScopedManualTick(
            strategy_name="reflect_episodes",
            scope_mode="active_only",
            app_id="joysafeter",
            project_id="project-1",
            active_agent_ids=("agent-active",),
            active_session_ids=(),
        ),
        ctx=object(),
    )

    assert calls == [set()]


@pytest.mark.asyncio
async def test_reflect_episodes_raises_when_all_owner_reflections_fail(monkeypatch):
    class _ClusterRepo:
        async def list_distinct_owners(self):
            return [("user-owner", "user", "joysafeter", "project-1")]

    async def _fake_run_reflection_for_owner(**kwargs):
        return reflect_strategy.ReflectionOwnerResult(
            owner_id=kwargs["owner_id"],
            owner_type=kwargs["owner_type"],
            app_id=kwargs["app_id"],
            project_id=kwargs["project_id"],
            success_count=0,
            failure_count=1,
        )

    async def _fake_load_active_scopes(project_ids):
        return {
            "project-1": reflect_strategy._ActiveJoySafeterScopes(
                active_agent_ids=set(),
                active_session_ids=set(),
            )
        }

    monkeypatch.setattr(reflect_strategy, "cluster_repo", _ClusterRepo())
    monkeypatch.setattr(reflect_strategy, "_run_reflection_for_owner", _fake_run_reflection_for_owner)
    monkeypatch.setattr(reflect_strategy, "_load_active_joysafeter_scopes", _fake_load_active_scopes)

    with pytest.raises(reflect_strategy.ReflectionRunFailed, match="all reflection work failed"):
        await reflect_episodes(CronTick(strategy_name="reflect_episodes"), ctx=object())


@pytest.mark.asyncio
async def test_reflect_episodes_allows_partial_owner_reflection_failure(monkeypatch):
    class _ClusterRepo:
        async def list_distinct_owners(self):
            return [
                ("user-ok", "user", "joysafeter", "project-1"),
                ("user-failed", "user", "joysafeter", "project-1"),
            ]

    logs = []

    async def _fake_run_reflection_for_owner(**kwargs):
        if kwargs["owner_id"] == "user-ok":
            return reflect_strategy.ReflectionOwnerResult(
                owner_id=kwargs["owner_id"],
                owner_type=kwargs["owner_type"],
                app_id=kwargs["app_id"],
                project_id=kwargs["project_id"],
                success_count=1,
                failure_count=0,
            )
        return reflect_strategy.ReflectionOwnerResult(
            owner_id=kwargs["owner_id"],
            owner_type=kwargs["owner_type"],
            app_id=kwargs["app_id"],
            project_id=kwargs["project_id"],
            success_count=0,
            failure_count=1,
        )

    async def _fake_load_active_scopes(project_ids):
        return {
            "project-1": reflect_strategy._ActiveJoySafeterScopes(
                active_agent_ids=set(),
                active_session_ids=set(),
            )
        }

    class _Logger:
        def warning(self, event, **kwargs):
            logs.append((event, kwargs))

    monkeypatch.setattr(reflect_strategy, "cluster_repo", _ClusterRepo())
    monkeypatch.setattr(reflect_strategy, "_run_reflection_for_owner", _fake_run_reflection_for_owner)
    monkeypatch.setattr(reflect_strategy, "_load_active_joysafeter_scopes", _fake_load_active_scopes)
    monkeypatch.setattr(reflect_strategy, "logger", _Logger())

    await reflect_episodes(CronTick(strategy_name="reflect_episodes"), ctx=object())

    assert logs == [
        (
            "reflection_cycle_partial_failure",
            {
                "owner_count": 2,
                "success_count": 1,
                "failure_count": 1,
            },
        )
    ]


@pytest.mark.asyncio
async def test_run_reflection_for_owner_uses_dreaming_llm_timeout(monkeypatch):
    captured = {}
    llm_client = object()

    async def _fake_get_project_llm_client(project_id, *, default_timeout_seconds):
        captured["project_id"] = project_id
        captured["default_timeout_seconds"] = default_timeout_seconds
        return llm_client

    class _FakeEpisodeReflector:
        def __init__(self, *, llm):
            captured["reflector_llm"] = llm

    class _FakeReflectionOrchestrator:
        def __init__(self, **kwargs):
            captured["orchestrator_llm"] = kwargs["llm_client"]
            self.reflector_failure_count = 0

        async def run(self, **kwargs):
            return [object()]

    monkeypatch.setattr(
        reflect_strategy,
        "get_project_llm_client",
        _fake_get_project_llm_client,
    )
    monkeypatch.setattr(
        reflect_strategy,
        "ReflectionOrchestrator",
        _FakeReflectionOrchestrator,
    )
    monkeypatch.setitem(
        sys.modules,
        "everalgo.user_memory",
        SimpleNamespace(EpisodeReflector=_FakeEpisodeReflector),
    )

    result = await reflect_strategy._run_reflection_for_owner(
        ctx=object(),
        owner_id="owner-1",
        owner_type="user",
        app_id="joysafeter",
        project_id="project-1",
        active_session_ids=set(),
    )

    assert captured["project_id"] == "project-1"
    assert captured["default_timeout_seconds"] == 180.0
    assert isinstance(captured["reflector_llm"], ChineseMemoryLLMClient)
    assert isinstance(captured["orchestrator_llm"], ChineseMemoryLLMClient)
    assert captured["reflector_llm"] is captured["orchestrator_llm"]
    assert captured["reflector_llm"]._delegate is llm_client
    assert result.success_count == 1
    assert result.failure_count == 0
