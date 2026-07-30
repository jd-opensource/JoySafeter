from __future__ import annotations

import importlib

from everalgo.types import AgentCase as AlgoAgentCase
from everalgo.types import AtomicFact as AlgoAtomicFact
from everalgo.types import Episode as AlgoEpisode
from everalgo.types import Foresight as AlgoForesight
from everalgo.types import Profile as AlgoProfile

from app.everos.memory.models import AgentCase, AtomicFact, Episode, Foresight


def test_episode_uses_source_context_timestamp_instead_of_llm_timestamp():
    episode = Episode.from_algo(
        AlgoEpisode(
            owner_id=None,
            episode="用户讨论记忆字段来源。",
            subject="记忆字段",
            timestamp=111,
        ),
        owner_id="user-1",
        session_id="session-1",
        sender_ids=["user-1"],
        parent_id="mc-1",
        source_timestamp_ms=222,
    )

    assert episode.timestamp == 222


def test_atomic_fact_inherits_episode_timestamp_instead_of_llm_timestamp():
    fact = AtomicFact.from_algo(
        AlgoAtomicFact(owner_id=None, content="用户关注 timestamp 来源。", timestamp=111),
        owner_id="user-1",
        session_id="session-1",
        parent_id="ep-1",
        source_timestamp_ms=222,
    )

    assert fact.timestamp == 222


def test_foresight_uses_memcell_timestamp_instead_of_llm_timestamp():
    foresight = Foresight.from_algo(
        AlgoForesight(
            owner_id="user-1",
            foresight="用户可能会继续校验记忆字段。",
            evidence="用户连续追问 timestamp 来源。",
            timestamp=111,
        ),
        session_id="session-1",
        parent_id="mc-1",
        source_timestamp_ms=222,
    )

    assert foresight.timestamp == 222


def test_agent_case_uses_memcell_timestamp_instead_of_llm_timestamp():
    case = AgentCase.from_algo(
        AlgoAgentCase(
            id="algo-case-1",
            timestamp=111,
            task_intent="检查记忆 timestamp 来源",
            approach="阅读代码并补测试",
            quality_score=0.8,
            key_insight="timestamp 应由 EverOS 注入",
        ),
        owner_id="agent-1",
        session_id="session-1",
        parent_id="mc-1",
        source_timestamp_ms=222,
    )

    assert case.timestamp == 222


async def test_user_profile_persist_uses_latest_memcell_timestamp(monkeypatch):
    extract_user_profile = importlib.import_module(
        "app.everos.memory.strategies.extract_user_profile"
    )

    writes = []

    class FakeWriter:
        async def write(self, owner_id, *, frontmatter, body, app_id, project_id):
            writes.append(
                {
                    "owner_id": owner_id,
                    "frontmatter": frontmatter,
                    "body": body,
                    "app_id": app_id,
                    "project_id": project_id,
                }
            )

    monkeypatch.setattr(extract_user_profile, "_writer", FakeWriter())

    await extract_user_profile._persist_profile(
        AlgoProfile(owner_id="user-1", summary="用户关注记忆字段。", timestamp=111),
        owner_id="user-1",
        app_id="app-1",
        project_id="project-1",
        profile_timestamp_ms=222,
    )

    assert writes[0]["frontmatter"].profile_timestamp_ms == 222
