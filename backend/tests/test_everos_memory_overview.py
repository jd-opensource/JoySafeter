from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.everos.entrypoints.api.routes import overview
from app.joysafeter_api.api.v1 import everos_memory

pytestmark = pytest.mark.no_db


class _Repo:
    def __init__(self, rows):
        self._rows = rows

    async def find_where(self, where: str, limit: int):
        return self._rows[:limit]


class _ParentScopedFactRepo:
    def __init__(self, broad_rows, parent_rows):
        self._broad_rows = broad_rows
        self._parent_rows = parent_rows
        self.calls: list[str] = []

    async def find_where(self, where: str, limit: int):
        self.calls.append(where)
        if "parent_id IN" in where:
            return self._parent_rows[:limit]
        return self._broad_rows[:limit]


def _query_limit_cap(fn) -> int:
    query = inspect.signature(fn).parameters["limit"].default
    for item in query.metadata:
        limit = getattr(item, "le", None)
        if limit is not None:
            return limit
    raise AssertionError("limit query parameter has no upper bound")


def test_memory_overview_routes_accept_large_full_list_limit():
    assert _query_limit_cap(overview.get_memory_overview) >= 1000
    assert _query_limit_cap(everos_memory.get_everos_memory_overview) >= 1000


def test_joysafeter_memory_overview_filters_archived_agent_and_session_scopes():
    payload = {
        "counts": {
            "profiles": 1,
            "episodes": 4,
            "agent_cases": 3,
            "agent_skills": 2,
        },
        "profiles": [{"id": "profile-1", "owner_id": "user-1"}],
        "episodes": [
            {"id": "episode-active", "session_id": "session-active"},
            {"id": "episode-archived", "session_id": "session-archived"},
            {
                "id": "episode-aggregate-active-source",
                "session_id": None,
                "parent_type": "cluster",
                "source_session_ids": ["session-active", "session-archived"],
            },
            {
                "id": "episode-aggregate-archived-source",
                "session_id": None,
                "parent_type": "cluster",
                "source_session_ids": ["session-archived"],
            },
        ],
        "atomic_facts": [
            {"id": "fact-active", "session_id": "session-active", "parent_id": "ep-active"},
            {"id": "fact-archived", "session_id": "session-archived", "parent_id": "ep-archived"},
        ],
        "agent_cases": [
            {"id": "case-active", "owner_id": "agent-active", "session_id": "session-active"},
            {"id": "case-archived-agent", "owner_id": "agent-archived", "session_id": "session-active"},
            {"id": "case-archived-session", "owner_id": "agent-active", "session_id": "session-archived"},
        ],
        "agent_skills": [
            {"id": "skill-active", "owner_id": "agent-active"},
            {"id": "skill-archived", "owner_id": "agent-archived"},
        ],
        "recent_activity": [
            {"id": "profile-1", "kind": "profile", "owner_id": "user-1"},
            {"id": "episode-active", "kind": "episode", "session_id": "session-active"},
            {"id": "episode-archived", "kind": "episode", "session_id": "session-archived"},
            {
                "id": "episode-aggregate-active-source",
                "kind": "episode",
                "session_id": None,
                "parent_type": "cluster",
                "source_session_ids": ["session-active", "session-archived"],
            },
            {
                "id": "episode-aggregate-archived-source",
                "kind": "episode",
                "session_id": None,
                "parent_type": "cluster",
                "source_session_ids": ["session-archived"],
            },
            {"id": "case-active", "kind": "agent_case", "owner_id": "agent-active", "session_id": "session-active"},
            {"id": "case-archived-agent", "kind": "agent_case", "owner_id": "agent-archived", "session_id": "session-active"},
            {"id": "case-archived-session", "kind": "agent_case", "owner_id": "agent-active", "session_id": "session-archived"},
            {"id": "skill-active", "kind": "agent_skill", "owner_id": "agent-active"},
            {"id": "skill-archived", "kind": "agent_skill", "owner_id": "agent-archived"},
        ],
    }

    filtered = everos_memory._filter_overview_by_active_scopes(
        payload,
        active_agent_ids={"agent-active"},
        active_session_ids={"session-active"},
    )

    assert [item["id"] for item in filtered["profiles"]] == ["profile-1"]
    assert [item["id"] for item in filtered["episodes"]] == [
        "episode-active",
        "episode-aggregate-active-source",
    ]
    assert [item["id"] for item in filtered["atomic_facts"]] == ["fact-active"]
    assert [item["id"] for item in filtered["agent_cases"]] == ["case-active"]
    assert [item["id"] for item in filtered["agent_skills"]] == ["skill-active"]
    assert filtered["counts"] == {
        "profiles": 1,
        "episodes": 2,
        "agent_cases": 1,
        "agent_skills": 1,
    }
    assert [item["id"] for item in filtered["recent_activity"]] == [
        "profile-1",
        "episode-active",
        "episode-aggregate-active-source",
        "case-active",
        "skill-active",
    ]


def test_joysafeter_memory_overview_filters_deprecated_memories():
    payload = {
        "counts": {"profiles": 1, "episodes": 2, "agent_cases": 0, "agent_skills": 0},
        "profiles": [{"id": "profile-1", "owner_id": "user-1"}],
        "episodes": [
            {"id": "episode-active", "session_id": "session-active", "deprecated_by": None},
            {"id": "episode-old", "session_id": "session-active", "deprecated_by": "episode-merged"},
        ],
        "atomic_facts": [
            {"id": "fact-active", "session_id": "session-active", "deprecated_by": None},
            {"id": "fact-old", "session_id": "session-active", "deprecated_by": "episode-merged"},
        ],
        "agent_cases": [],
        "agent_skills": [],
        "recent_activity": [
            {"id": "episode-active", "kind": "episode", "session_id": "session-active", "deprecated_by": None},
            {"id": "episode-old", "kind": "episode", "session_id": "session-active", "deprecated_by": "episode-merged"},
        ],
    }

    filtered = everos_memory._filter_overview_by_active_scopes(
        payload,
        active_agent_ids={"agent-active"},
        active_session_ids={"session-active"},
    )

    assert [item["id"] for item in filtered["episodes"]] == ["episode-active"]
    assert [item["id"] for item in filtered["atomic_facts"]] == ["fact-active"]
    assert [item["id"] for item in filtered["recent_activity"]] == ["episode-active"]
    assert filtered["counts"]["episodes"] == 1


def test_joysafeter_memory_get_proxy_rewrites_scope_and_injects_active_session_filter():
    payload = {
        "app_id": "attacker-app",
        "project_id": "attacker-project",
        "user_id": "alice",
        "memory_type": "episode",
        "filters": {"source": "chat"},
    }

    prepared = everos_memory._prepare_memory_proxy_payload(
        payload,
        everos_project_id="project-slug__project-1",
        active_agent_ids={"agent-active"},
        active_session_ids={"session-active", "session-other"},
        include_aggregated_sources=False,
    )

    assert prepared == {
        "app_id": "joysafeter",
        "project_id": "project-slug__project-1",
        "user_id": "alice",
        "memory_type": "episode",
        "filters": {
            "AND": [
                {"source": "chat"},
                {"session_id": {"in": ["session-active", "session-other"]}},
            ]
        },
    }


def test_joysafeter_memory_search_proxy_keeps_aggregated_episode_sources_visible():
    payload = {
        "app_id": "attacker-app",
        "project_id": "attacker-project",
        "user_id": "alice",
        "memory_type": "episode",
        "filters": {"source": "chat"},
    }

    prepared = everos_memory._prepare_memory_proxy_payload(
        payload,
        everos_project_id="project-slug__project-1",
        active_agent_ids={"agent-active"},
        active_session_ids={"session-active", "session-other"},
        include_aggregated_sources=True,
    )

    assert prepared == {
        "app_id": "joysafeter",
        "project_id": "project-slug__project-1",
        "user_id": "alice",
        "memory_type": "episode",
        "filters": {
            "AND": [
                {"source": "chat"},
                {
                    "OR": [
                        {"session_id": {"in": ["session-active", "session-other"]}},
                        {"source_session_id": {"in": ["session-active", "session-other"]}},
                    ]
                },
            ]
        },
    }


def test_joysafeter_memory_proxy_injects_active_session_filter_for_atomic_facts():
    payload = {
        "app_id": "attacker-app",
        "project_id": "attacker-project",
        "user_id": "alice",
        "memory_type": "atomic_fact",
        "filters": {"parent_id": {"in": ["ep-1", "memcell-1"]}},
    }

    prepared = everos_memory._prepare_memory_proxy_payload(
        payload,
        everos_project_id="project-slug__project-1",
        active_agent_ids={"agent-active"},
        active_session_ids={"session-active"},
        include_aggregated_sources=False,
    )

    assert prepared == {
        "app_id": "joysafeter",
        "project_id": "project-slug__project-1",
        "user_id": "alice",
        "memory_type": "atomic_fact",
        "filters": {
            "AND": [
                {"parent_id": {"in": ["ep-1", "memcell-1"]}},
                {"session_id": "session-active"},
            ]
        },
    }


def test_joysafeter_memory_proxy_rejects_inactive_agent_owner_before_forwarding():
    payload = {
        "app_id": "joysafeter",
        "project_id": "project-slug__project-1",
        "agent_id": "agent-archived",
        "memory_type": "agent_skill",
    }

    prepared = everos_memory._prepare_memory_proxy_payload(
        payload,
        everos_project_id="project-slug__project-1",
        active_agent_ids={"agent-active"},
        active_session_ids={"session-active"},
        include_aggregated_sources=False,
    )

    assert prepared is None


def test_joysafeter_memory_proxy_empty_get_response_includes_atomic_facts():
    response = everos_memory._empty_everos_get_response()

    assert response["data"]["atomic_facts"] == []


@pytest.mark.asyncio
async def test_joysafeter_memory_dreaming_triggers_reflect_episodes(monkeypatch):
    requests = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "started",
                "name": "reflect_episodes",
                "run_id": "run-1",
                "run_ids": ["run-1"],
            }

    class _Client:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, json):
            requests.append({"url": url, "json": json})
            return _Response()

    monkeypatch.setenv("EVEROS_INTERNAL_BASE_URL", "http://everos.local")
    monkeypatch.setattr(everos_memory.httpx, "AsyncClient", _Client)

    response = await everos_memory._forward_dreaming_request(
        timeout=45.0,
        active_agent_ids={"agent-active"},
        active_session_ids={"session-active", "session-other"},
        project_id="project-slug__project-1",
    )

    assert requests == [
        {
            "url": "http://everos.local/api/v1/ome/trigger",
            "json": {
                "name": "reflect_episodes",
                "timeout": 45.0,
                "force": False,
                "wait": False,
                "scope_mode": "active_only",
                "active_agent_ids": ["agent-active"],
                "active_session_ids": ["session-active", "session-other"],
                "app_id": "joysafeter",
                "project_id": "project-slug__project-1",
            },
        }
    ]
    assert response == {
        "status": "started",
        "name": "reflect_episodes",
        "run_id": "run-1",
        "run_ids": ["run-1"],
        "display_name": "Dreaming",
    }


def test_joysafeter_memory_proxy_filters_get_and_search_payloads_by_active_scopes():
    payload = {
        "request_id": "req-1",
        "data": {
            "profiles": [{"id": "profile-1"}],
            "episodes": [
                {"id": "episode-active", "session_id": "session-active"},
                {"id": "episode-archived", "session_id": "session-archived"},
            ],
            "agent_cases": [
                {"id": "case-active", "agent_id": "agent-active", "session_id": "session-active"},
                {"id": "case-archived-agent", "agent_id": "agent-archived", "session_id": "session-active"},
                {"id": "case-archived-session", "agent_id": "agent-active", "session_id": "session-archived"},
            ],
            "agent_skills": [
                {"id": "skill-active", "agent_id": "agent-active"},
                {"id": "skill-archived", "agent_id": "agent-archived"},
            ],
            "total_count": 6,
            "count": 6,
        },
    }

    filtered = everos_memory._filter_memory_proxy_payload_by_active_scopes(
        payload,
        active_agent_ids={"agent-active"},
        active_session_ids={"session-active"},
    )

    assert [item["id"] for item in filtered["data"]["profiles"]] == ["profile-1"]
    assert [item["id"] for item in filtered["data"]["episodes"]] == ["episode-active"]
    assert [item["id"] for item in filtered["data"]["agent_cases"]] == ["case-active"]
    assert [item["id"] for item in filtered["data"]["agent_skills"]] == ["skill-active"]
    assert filtered["data"]["count"] == 4
    assert filtered["data"]["total_count"] == 4


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_joysafeter_memory_document_rejects_archived_session_md_path(monkeypatch):
    requests: list[tuple[str, dict[str, str]]] = []

    async def _resolve_project_id(db, project_id):
        return "project-slug__project-1"

    async def _active_scopes(db, project_id):
        return {"agent-active"}, {"session-active"}

    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, *, params):
            requests.append((url, params))
            if url.endswith("/api/v1/memory/overview"):
                return _Response(
                    {
                        "profiles": [],
                        "episodes": [
                            {
                                "id": "episode-archived",
                                "session_id": "session-archived",
                                "md_path": "joysafeter/project/users/u/episodes/archived.md",
                            }
                        ],
                        "agent_cases": [],
                        "agent_skills": [],
                        "recent_activity": [],
                    }
                )
            return _Response({"content": "archived body"})

    monkeypatch.setenv("EVEROS_INTERNAL_BASE_URL", "http://everos.local")
    monkeypatch.setattr(everos_memory, "_resolve_everos_project_id", _resolve_project_id)
    monkeypatch.setattr(everos_memory, "_active_everos_memory_scopes", _active_scopes)
    monkeypatch.setattr(everos_memory.httpx, "AsyncClient", _Client)

    with pytest.raises(everos_memory.HTTPException) as exc:
        await everos_memory.get_everos_memory_document(
            md_path="joysafeter/project/users/u/episodes/archived.md",
            auth_ctx=SimpleNamespace(project_id="project-1"),
            db=object(),
        )

    assert exc.value.status_code == 404
    assert requests == [
        (
            "http://everos.local/api/v1/memory/overview",
            {"app_id": "joysafeter", "project_id": "project-slug__project-1", "limit": 1000},
        )
    ]


@pytest.mark.asyncio
async def test_memory_overview_filters_deprecated_episodes_and_facts(monkeypatch):
    timestamp = datetime(2026, 7, 20, 2, 39, tzinfo=UTC)

    monkeypatch.setattr(overview, "user_profile_repo", _Repo([]))
    monkeypatch.setattr(
        overview,
        "episode_repo",
        _Repo([
            SimpleNamespace(
                id="episode-active",
                entry_id="ep-active",
                owner_id="user-1",
                session_id="session-1",
                timestamp=timestamp,
                parent_type="cluster",
                parent_id="cl-1",
                subject="Merged episode",
                summary="Merged summary",
                episode="Merged body",
                md_path="joysafeter/project/users/user-1/episodes/episode-2026-07-27.md",
                deprecated_by=None,
            ),
            SimpleNamespace(
                id="episode-old",
                entry_id="ep-old",
                owner_id="user-1",
                session_id="session-1",
                timestamp=timestamp,
                parent_type="memcell",
                parent_id="mc-1",
                subject="Old episode",
                summary="Old summary",
                episode="Old body",
                md_path="joysafeter/project/users/user-1/episodes/episode-2026-07-20.md",
                deprecated_by="ep-active",
            ),
        ]),
    )
    monkeypatch.setattr(
        overview,
        "atomic_fact_repo",
        _Repo([
            SimpleNamespace(
                id="fact-active",
                entry_id="af-active",
                owner_id="user-1",
                session_id="session-1",
                timestamp=timestamp,
                parent_type="episode",
                parent_id="ep-active",
                sender_ids=["user-1"],
                fact="Active fact",
                md_path="joysafeter/project/users/user-1/.atomic_facts/atomic_fact-2026-07-27.md",
                deprecated_by=None,
            ),
            SimpleNamespace(
                id="fact-old",
                entry_id="af-old",
                owner_id="user-1",
                session_id="session-1",
                timestamp=timestamp,
                parent_type="episode",
                parent_id="ep-old",
                sender_ids=["user-1"],
                fact="Old fact",
                md_path="joysafeter/project/users/user-1/.atomic_facts/atomic_fact-2026-07-20.md",
                deprecated_by="ep-active",
            ),
        ]),
    )
    monkeypatch.setattr(overview, "agent_case_repo", _Repo([]))
    monkeypatch.setattr(overview, "agent_skill_repo", _Repo([]))

    result = await overview.get_memory_overview(
        app_id="joysafeter",
        project_id="project",
        limit=20,
    )

    assert [item["id"] for item in result["episodes"]] == ["episode-active"]
    assert [item["id"] for item in result["atomic_facts"]] == ["fact-active"]
    assert [item["id"] for item in result["recent_activity"]] == ["episode-active"]
    assert result["counts"]["episodes"] == 1


@pytest.mark.asyncio
async def test_memory_overview_backfills_facts_for_visible_episodes(monkeypatch):
    timestamp = datetime(2026, 7, 28, 2, 1, tzinfo=UTC)
    monkeypatch.setattr(overview, "user_profile_repo", _Repo([]))
    monkeypatch.setattr(
        overview,
        "episode_repo",
        _Repo([
            SimpleNamespace(
                id="episode-1",
                entry_id="ep_20260728_00000001",
                owner_id="user-1",
                session_id=None,
                timestamp=timestamp,
                parent_type="cluster",
                parent_id="cl-1",
                subject="Aggregated episode",
                summary="Aggregated summary",
                episode="Aggregated body",
                md_path="joysafeter/project/users/user-1/episodes/episode-2026-07-28.md",
                deprecated_by=None,
            )
        ]),
    )
    fact_repo = _ParentScopedFactRepo(
        broad_rows=[],
        parent_rows=[
            SimpleNamespace(
                id="joysafeter/project/users/user-1/.atomic_facts/atomic_fact-2026-07-28.md#af_20260728_00000001",
                entry_id="af_20260728_00000001",
                owner_id="user-1",
                session_id=None,
                timestamp=timestamp,
                parent_type="episode",
                parent_id="ep_20260728_00000001",
                sender_ids=[],
                fact="Aggregated fact",
                md_path="joysafeter/project/users/user-1/.atomic_facts/atomic_fact-2026-07-28.md",
                deprecated_by=None,
            )
        ],
    )
    monkeypatch.setattr(overview, "atomic_fact_repo", fact_repo)
    monkeypatch.setattr(overview, "agent_case_repo", _Repo([]))
    monkeypatch.setattr(overview, "agent_skill_repo", _Repo([]))

    result = await overview.get_memory_overview(
        app_id="joysafeter",
        project_id="project",
        limit=20,
    )

    assert [item["parent_id"] for item in result["atomic_facts"]] == [
        "ep_20260728_00000001"
    ]
    assert any("parent_id IN" in call for call in fact_repo.calls)


@pytest.mark.asyncio
async def test_memory_overview_deduplicates_profiles_by_owner(monkeypatch):
    monkeypatch.setattr(
        overview,
        "user_profile_repo",
        _Repo(
            [
                SimpleNamespace(
                    id="joysafeter:project:user-1",
                    owner_id="user-1",
                    summary="Profile summary",
                    explicit_info_json="{}",
                    implicit_traits_json="{}",
                    profile_timestamp_ms=1783590600000,
                    updated_at=datetime(2026, 7, 9, 9, 50, tzinfo=UTC),
                    md_path="joysafeter/project/users/user-1/user.md",
                ),
                SimpleNamespace(
                    id="joysafeter:project:user-1",
                    owner_id="user-1",
                    summary="Profile summary",
                    explicit_info_json="{}",
                    implicit_traits_json="{}",
                    profile_timestamp_ms=1783590600000,
                    updated_at=datetime(2026, 7, 9, 9, 50, tzinfo=UTC),
                    md_path="joysafeter/project/users/user-1/user.md",
                ),
            ]
        ),
    )
    monkeypatch.setattr(overview, "episode_repo", _Repo([]))
    monkeypatch.setattr(overview, "atomic_fact_repo", _Repo([]))
    monkeypatch.setattr(overview, "agent_case_repo", _Repo([]))
    monkeypatch.setattr(overview, "agent_skill_repo", _Repo([]))

    result = await overview.get_memory_overview(
        app_id="joysafeter",
        project_id="project",
        limit=20,
    )

    assert result["counts"]["profiles"] == 1
    assert result["profiles"] == [
        {
            "id": "joysafeter:project:user-1",
            "owner_id": "user-1",
            "summary": "Profile summary",
            "explicit_info_json": "{}",
            "implicit_traits_json": "{}",
            "timestamp_ms": 1783590600000,
            "updated_at": "2026-07-09T09:50:00+00:00",
            "md_path": "joysafeter/project/users/user-1/user.md",
        }
    ]


@pytest.mark.asyncio
async def test_memory_overview_recent_activity_uses_structured_titles(monkeypatch):
    timestamp = datetime(2026, 7, 9, 9, 50, tzinfo=UTC)
    md_path = "joysafeter/project/users/user-1/episodes/episode-2026-07-09.md"

    monkeypatch.setattr(
        overview,
        "user_profile_repo",
        _Repo([
            SimpleNamespace(
                id="profile-1",
                owner_id="user-1",
                summary="Profile summary title",
                explicit_info_json="{}",
                implicit_traits_json="{}",
                profile_timestamp_ms=1783590600000,
                md_path="joysafeter/project/users/user-1/user.md",
            )
        ]),
    )
    monkeypatch.setattr(
        overview,
        "episode_repo",
        _Repo([
            SimpleNamespace(
                id="episode-1",
                entry_id="ep_20260709_00000001",
                owner_id="user-1",
                session_id="session-1",
                timestamp=timestamp,
                parent_type="memcell",
                parent_id="memcell-1",
                subject="First subject from LanceDB",
                summary="First summary",
                episode="First body",
                md_path=md_path,
            ),
            SimpleNamespace(
                id="episode-2",
                entry_id="ep_20260709_00000002",
                owner_id="user-1",
                session_id="session-1",
                timestamp=timestamp,
                parent_type="memcell",
                parent_id="memcell-2",
                subject="Second subject from same md",
                summary="Second summary",
                episode="Second body",
                md_path=md_path,
            ),
        ]),
    )
    monkeypatch.setattr(
        overview,
        "atomic_fact_repo",
        _Repo([
            SimpleNamespace(
                id="fact-1",
                entry_id="af_20260709_00000001",
                owner_id="user-1",
                session_id="session-1",
                timestamp=timestamp,
                parent_type="episode",
                parent_id="ep_20260709_00000001",
                sender_ids=["user-1"],
                fact="Fact derived from first episode",
                md_path="joysafeter/project/users/user-1/.atomic_facts/atomic_fact-2026-07-09.md",
                deprecated_by=None,
            )
        ]),
    )
    monkeypatch.setattr(
        overview,
        "agent_case_repo",
        _Repo([
            SimpleNamespace(
                id="case-1",
                entry_id="ac_20260709_00000001",
                owner_id="agent-1",
                session_id="session-1",
                timestamp=timestamp,
                task_intent="Case task intent title",
                approach="Case approach",
                key_insight="Case insight",
                quality_score=0.8,
                md_path="joysafeter/project/agents/agent-1/.cases/agent_case-2026-07-09.md",
            )
        ]),
    )
    monkeypatch.setattr(
        overview,
        "agent_skill_repo",
        _Repo([
            SimpleNamespace(
                id="skill-1",
                owner_id="agent-1",
                name="Skill name title",
                description="Skill description",
                content="Skill content",
                confidence=0.7,
                maturity_score=0.6,
                source_case_ids=["case-1"],
                cluster_id="cluster-1",
                md_path="joysafeter/project/agents/agent-1/skills/skill-name/SKILL.md",
            )
        ]),
    )

    result = await overview.get_memory_overview(
        app_id="joysafeter",
        project_id="project",
        limit=20,
    )

    by_id = {item["id"]: item for item in result["recent_activity"]}

    assert by_id["profile-1"]["summary"] == "Profile summary title"
    assert by_id["episode-1"]["entry_id"] == "ep_20260709_00000001"
    assert by_id["episode-1"]["subject"] == "First subject from LanceDB"
    assert by_id["episode-2"]["entry_id"] == "ep_20260709_00000002"
    assert by_id["episode-2"]["subject"] == "Second subject from same md"
    assert by_id["episode-1"]["md_path"] == by_id["episode-2"]["md_path"]
    assert by_id["case-1"]["entry_id"] == "ac_20260709_00000001"
    assert by_id["case-1"]["task_intent"] == "Case task intent title"
    assert by_id["skill-1"]["name"] == "Skill name title"
    assert result["episodes"][0]["parent_type"] == "memcell"
    assert result["episodes"][0]["parent_id"] == "memcell-1"
    assert result["atomic_facts"] == [
        {
            "id": "fact-1",
            "entry_id": "af_20260709_00000001",
            "owner_id": "user-1",
            "session_id": "session-1",
            "timestamp": timestamp.isoformat(),
            "parent_type": "episode",
            "parent_id": "ep_20260709_00000001",
            "sender_ids": ["user-1"],
            "fact": "Fact derived from first episode",
            "md_path": "joysafeter/project/users/user-1/.atomic_facts/atomic_fact-2026-07-09.md",
            "deprecated_by": None,
        }
    ]


@pytest.mark.asyncio
async def test_memory_overview_profile_activity_uses_row_updated_at(monkeypatch):
    profile_source_time_ms = int(
        datetime(2025, 7, 9, 9, 55, tzinfo=UTC).timestamp() * 1000
    )
    profile_updated_at = datetime(2026, 7, 9, 9, 50, tzinfo=UTC)

    monkeypatch.setattr(
        overview,
        "user_profile_repo",
        _Repo([
            SimpleNamespace(
                id="profile-1",
                owner_id="user-1",
                summary="Profile generated from older user memory",
                explicit_info_json="{}",
                implicit_traits_json="{}",
                profile_timestamp_ms=profile_source_time_ms,
                updated_at=profile_updated_at,
                md_path="joysafeter/project/users/user-1/user.md",
            )
        ]),
    )
    monkeypatch.setattr(overview, "episode_repo", _Repo([]))
    monkeypatch.setattr(overview, "atomic_fact_repo", _Repo([]))
    monkeypatch.setattr(overview, "agent_case_repo", _Repo([]))
    monkeypatch.setattr(overview, "agent_skill_repo", _Repo([]))

    result = await overview.get_memory_overview(
        app_id="joysafeter",
        project_id="project",
        limit=20,
    )

    assert result["recent_activity"][0]["id"] == "profile-1"
    assert result["recent_activity"][0]["timestamp"] == profile_updated_at.isoformat()


@pytest.mark.asyncio
async def test_memory_overview_skill_activity_uses_row_updated_at(monkeypatch):
    skill_updated_at = datetime(2026, 7, 9, 10, 5, tzinfo=UTC)

    monkeypatch.setattr(overview, "user_profile_repo", _Repo([]))
    monkeypatch.setattr(overview, "episode_repo", _Repo([]))
    monkeypatch.setattr(overview, "atomic_fact_repo", _Repo([]))
    monkeypatch.setattr(overview, "agent_case_repo", _Repo([]))
    monkeypatch.setattr(
        overview,
        "agent_skill_repo",
        _Repo([
            SimpleNamespace(
                id="skill-1",
                owner_id="agent-1",
                name="Skill name title",
                description="Skill description",
                content="Skill content",
                confidence=0.7,
                maturity_score=0.6,
                source_case_ids=["case-1"],
                cluster_id="cluster-1",
                updated_at=skill_updated_at,
                md_path="joysafeter/project/agents/agent-1/skills/skill-name/SKILL.md",
            )
        ]),
    )

    result = await overview.get_memory_overview(
        app_id="joysafeter",
        project_id="project",
        limit=20,
    )

    assert result["recent_activity"][0]["id"] == "skill-1"
    assert result["recent_activity"][0]["timestamp"] == skill_updated_at.isoformat()
