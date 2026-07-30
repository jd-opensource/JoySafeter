from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest
from everalgo.clustering import Cluster as AlgoCluster

from app.everos.core.errors import EmbeddingServiceError
from app.everos.memory.reflection.orchestrator import (
    ReflectionOrchestrator,
    _ensure_merged_episode_summary,
    _merged_episode_to_entry_body,
)


@pytest.mark.asyncio
async def test_reflection_cluster_update_keeps_old_centroid_when_embedding_fails():
    old_centroid = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)

    class _ClusterRepo:
        def __init__(self):
            self.removed: tuple[str, set[str]] | None = None
            self.added: tuple[str, str, str] | None = None
            self.metadata: dict[str, object] | None = None

        async def remove_members(self, cluster_id: str, member_ids: set[str]) -> None:
            self.removed = (cluster_id, member_ids)

        async def add_member(self, cluster_id: str, member_id: str, member_type: str) -> None:
            self.added = (cluster_id, member_id, member_type)

        async def get_with_members(self, cluster_id: str) -> AlgoCluster:
            return AlgoCluster(
                id=cluster_id,
                centroid=old_centroid,
                count=2,
                last_ts=1,
                preview=["old"],
                members=["old-1", "old-2"],
            )

        async def update_metadata(self, cluster_id: str, **metadata: object) -> None:
            self.metadata = {"cluster_id": cluster_id, **metadata}

    class _Embedder:
        async def embed(self, text: str) -> list[float]:
            raise EmbeddingServiceError("Arrearage")

    cluster_repo = _ClusterRepo()
    orchestrator = ReflectionOrchestrator(
        cluster_repo=cluster_repo,
        episode_store=object(),
        atomic_fact_store=object(),
        episode_writer=object(),
        report_repo=object(),
        reflector=object(),
        embedder=_Embedder(),
    )

    await orchestrator._update_cluster_after_merge(  # noqa: SLF001
        cluster_id="cl_1",
        to_deprecate={"ep_1", "ep_2"},
        merged_entry_id="ep_merged",
        algo_result=SimpleNamespace(episode="merged text"),
        episodes=[SimpleNamespace(timestamp=datetime(2026, 7, 27, 6, tzinfo=UTC))],
    )

    assert cluster_repo.removed == ("cl_1", {"ep_1", "ep_2"})
    assert cluster_repo.added == ("cl_1", "ep_merged", "episode")
    assert cluster_repo.metadata is not None
    assert cluster_repo.metadata["cluster_id"] == "cl_1"
    assert cluster_repo.metadata["centroid_blob"] == old_centroid.tobytes()
    assert cluster_repo.metadata["count"] == 1


def test_merged_episode_entry_body_requires_subject_summary_and_content():
    inline, sections = _merged_episode_to_entry_body(
        SimpleNamespace(
            subject="",
            summary="",
            episode=(
                "Security Audit of Nanobot Repository\n\n"
                "Date: July 20, 2026\n\n"
                "The audit identified one high severity finding and several "
                "medium severity risks."
            ),
        ),
        cluster_id="cl_3429599f3a27",
        owner_id="huajie_Sun",
        timestamp_iso="2026-07-20T02:39:58.667000+00:00",
        episodes=[
            SimpleNamespace(entry_id="ep_1", session_id="session-1"),
            SimpleNamespace(entry_id="ep_2", session_id="session-1"),
            SimpleNamespace(entry_id="ep_3", session_id="session-2"),
        ],
    )

    assert inline["parent_type"] == "cluster"
    assert inline["source_entry_ids"] == ["ep_1", "ep_2", "ep_3"]
    assert inline["source_session_ids"] == ["session-1", "session-2"]
    assert sections["Subject"] == "[Aggregated Memory] Security Audit of Nanobot Repository"
    assert sections["Summary"].startswith("Security Audit of Nanobot Repository")
    assert sections["Content"].startswith("Security Audit of Nanobot Repository")


@pytest.mark.asyncio
async def test_merged_episode_summary_uses_secondary_llm_summary_when_missing():
    class _LLM:
        async def chat(self, messages, *, temperature: int, max_tokens: int):
            assert temperature == 0
            assert max_tokens == 256
            assert "Generate an independent summary" in messages[0].content
            return SimpleNamespace(
                content=(
                    '{"summary": "This aggregate captures a completed nanobot '
                    'security audit, including scope, findings, and priority fixes."}'
                )
            )

    result = await _ensure_merged_episode_summary(
        SimpleNamespace(
            subject="Security Audit of Nanobot Repository",
            summary="",
            episode=(
                "Security Audit of Nanobot Repository\n\n"
                "Date: July 20, 2026\n\n"
                "The audit identified one high severity finding and several "
                "medium severity risks."
            ),
        ),
        _LLM(),
    )

    assert result.summary == (
        "This aggregate captures a completed nanobot security audit, including "
        "scope, findings, and priority fixes."
    )


@pytest.mark.asyncio
async def test_merged_episode_summary_is_limited_to_three_sentences():
    class _LLM:
        called = False

        async def chat(self, messages, *, temperature: int, max_tokens: int):
            self.called = True
            return SimpleNamespace(content='{"summary": "should not be used"}')

    llm = _LLM()
    result = await _ensure_merged_episode_summary(
        SimpleNamespace(
            subject="Security Audit of Nanobot Repository",
            summary=(
                "The audit covered the nanobot repository. "
                "It found one high-severity shell path traversal risk. "
                "It also found medium-severity workspace and policy risks. "
                "The follow-up plan prioritized three fixes."
            ),
            episode=(
                "Security Audit of Nanobot Repository\n\n"
                "The audit identified one high severity finding and several "
                "medium severity risks."
            ),
        ),
        llm,
    )

    assert result.summary == (
        "The audit covered the nanobot repository. "
        "It found one high-severity shell path traversal risk. "
        "It also found medium-severity workspace and policy risks."
    )
    assert llm.called is False


def test_merged_episode_entry_body_rejects_empty_content():
    with pytest.raises(ValueError, match="merged episode content is empty"):
        _merged_episode_to_entry_body(
            SimpleNamespace(subject="Anything", summary="Anything", episode="   "),
            cluster_id="cl_3429599f3a27",
            owner_id="huajie_Sun",
            timestamp_iso="2026-07-20T02:39:58.667000+00:00",
        )


@pytest.mark.asyncio
async def test_reflection_active_session_scope_filters_mixed_cluster_members():
    class _ClusterRepo:
        async def get_members_with_type(self, cluster_id: str):
            assert cluster_id == "cl_1"
            return [
                ("ep_active_1", "episode"),
                ("ep_archived", "episode"),
                ("ep_active_2", "episode"),
            ]

    class _EpisodeStore:
        async def find_by_owner_entries(self, owner_id: str, entry_ids: list[str], *, app_id: str, project_id: str):
            assert entry_ids == ["ep_active_1", "ep_archived", "ep_active_2"]
            return [
                SimpleNamespace(
                    entry_id="ep_archived",
                    session_id="session-archived",
                    parent_type="memcell",
                    timestamp=datetime(2026, 7, 27, 2, tzinfo=UTC),
                ),
                SimpleNamespace(
                    entry_id="ep_active_2",
                    session_id="session-active",
                    parent_type="memcell",
                    timestamp=datetime(2026, 7, 27, 3, tzinfo=UTC),
                ),
                SimpleNamespace(
                    entry_id="ep_active_1",
                    session_id="session-active",
                    parent_type="memcell",
                    timestamp=datetime(2026, 7, 27, 1, tzinfo=UTC),
                ),
            ]

    orchestrator = ReflectionOrchestrator(
        cluster_repo=_ClusterRepo(),
        episode_store=_EpisodeStore(),
        atomic_fact_store=object(),
        episode_writer=object(),
        report_repo=object(),
        reflector=object(),
        embedder=object(),
    )

    members, episodes = await orchestrator._load_cluster_episodes(  # noqa: SLF001
        cluster_id="cl_1",
        owner_id="huajie_Sun",
        app_id="joysafeter",
        project_id="project-1",
        active_session_ids={"session-active"},
    )

    assert members == [
        ("ep_active_1", "episode"),
        ("ep_active_2", "episode"),
    ]
    assert [episode.entry_id for episode in episodes] == ["ep_active_1", "ep_active_2"]


@pytest.mark.asyncio
async def test_reflection_active_session_scope_skips_cluster_with_one_active_episode():
    class _ClusterRepo:
        async def get_members_with_type(self, cluster_id: str):
            return [("ep_active", "episode"), ("ep_archived", "episode")]

    class _EpisodeStore:
        async def find_where(self, where: str, limit: int):
            return []

        async def find_by_owner_entries(self, owner_id: str, entry_ids: list[str], *, app_id: str, project_id: str):
            return [
                SimpleNamespace(
                    entry_id="ep_active",
                    session_id="session-active",
                    parent_type="memcell",
                    timestamp=datetime(2026, 7, 27, 1, tzinfo=UTC),
                ),
                SimpleNamespace(
                    entry_id="ep_archived",
                    session_id="session-archived",
                    parent_type="memcell",
                    timestamp=datetime(2026, 7, 27, 2, tzinfo=UTC),
                ),
            ]

    class _Reflector:
        called = False

        async def areflect(self, episodes):
            self.called = True
            return SimpleNamespace(episode="should not happen")

    reflector = _Reflector()
    orchestrator = ReflectionOrchestrator(
        cluster_repo=_ClusterRepo(),
        episode_store=_EpisodeStore(),
        atomic_fact_store=object(),
        episode_writer=object(),
        report_repo=object(),
        reflector=reflector,
        embedder=object(),
    )

    report = await orchestrator._process_cluster(  # noqa: SLF001
        ctx=object(),
        cluster_id="cl_1",
        owner_id="huajie_Sun",
        owner_type="user",
        app_id="joysafeter",
        project_id="project-1",
        active_session_ids={"session-active"},
    )

    assert report is None
    assert reflector.called is False
