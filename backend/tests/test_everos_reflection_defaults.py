import importlib

import pytest

from app.everos.infra.ome.events import CronTick, ScopedManualTick
from app.everos.memory.strategies.reflect_episodes import reflect_episodes

reflect_strategy = importlib.import_module("app.everos.memory.strategies.reflect_episodes")


def test_reflect_episodes_is_enabled_by_default() -> None:
    assert reflect_episodes.meta.enabled is True


def test_reflect_episodes_cron_runs_sunday_midnight() -> None:
    assert reflect_episodes.meta.trigger.expr == "0 0 * * sun"


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
