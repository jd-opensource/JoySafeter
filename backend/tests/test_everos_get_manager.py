from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.everos.memory.get import GetManager, GetRequest

pytestmark = pytest.mark.no_db


class _Repo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def find_where_paginated(self, where: str, *, sort_by: str, descending: bool, page: int, page_size: int):
        self.calls.append(
            {
                "where": where,
                "sort_by": sort_by,
                "descending": descending,
                "page": page,
                "page_size": page_size,
            }
        )
        return self.rows[:page_size], len(self.rows)

    async def find_by_owner_scope(self, owner_id: str, *, app_id: str, project_id: str):
        return None


async def test_get_manager_returns_atomic_facts_for_user_owner():
    fact_repo = _Repo(
        [
            SimpleNamespace(
                id="fact-1",
                entry_id="af_20260722_00000001",
                owner_id="huajie_Sun",
                app_id="joysafeter",
                project_id="test__project-1",
                session_id="session-1",
                timestamp=datetime(2026, 7, 22, 9, 30, tzinfo=UTC),
                parent_type="episode",
                parent_id="ep_20260722_00000001",
                sender_ids=["user"],
                fact="User wants facts attached to recent episodes.",
            )
        ]
    )
    manager = GetManager(
        episode_repo=_Repo([]),
        atomic_fact_repo=fact_repo,
        agent_case_repo=_Repo([]),
        agent_skill_repo=_Repo([]),
        user_profile_repo=_Repo([]),
    )

    response = await manager.get(
        GetRequest(
            user_id="huajie_Sun",
            app_id="joysafeter",
            project_id="test__project-1",
            memory_type="atomic_fact",
            filters={"parent_id": "ep_20260722_00000001"},
            page=1,
            page_size=5,
        )
    )

    assert response.data.count == 1
    assert response.data.atomic_facts[0].id == "fact-1"
    assert response.data.atomic_facts[0].parent_id == "ep_20260722_00000001"
    assert response.data.atomic_facts[0].fact == "User wants facts attached to recent episodes."
    assert "owner_id = 'huajie_Sun'" in fact_repo.calls[0]["where"]
    assert "parent_id = 'ep_20260722_00000001'" in fact_repo.calls[0]["where"]


async def test_get_manager_episode_items_include_fact_linkage_metadata():
    episode_repo = _Repo(
        [
            SimpleNamespace(
                id="episode-row-1",
                entry_id="ep_20260722_00000001",
                owner_id="huajie_Sun",
                app_id="joysafeter",
                project_id="test__project-1",
                session_id="session-1",
                timestamp=datetime(2026, 7, 22, 9, 30, tzinfo=UTC),
                sender_ids=["user"],
                parent_type="memcell",
                parent_id="memcell-1",
                summary="Discussed bootstrap memory loading.",
                subject="Memory loading",
                episode="Full body",
            )
        ]
    )
    manager = GetManager(
        episode_repo=episode_repo,
        atomic_fact_repo=_Repo([]),
        agent_case_repo=_Repo([]),
        agent_skill_repo=_Repo([]),
        user_profile_repo=_Repo([]),
    )

    response = await manager.get(
        GetRequest(
            user_id="huajie_Sun",
            app_id="joysafeter",
            project_id="test__project-1",
            memory_type="episode",
            page=1,
            page_size=5,
        )
    )

    episode = response.data.episodes[0]
    assert episode.entry_id == "ep_20260722_00000001"
    assert episode.parent_type == "memcell"
    assert episode.parent_id == "memcell-1"
