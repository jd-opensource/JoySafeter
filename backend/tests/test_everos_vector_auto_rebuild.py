import datetime as dt

import pytest

from app.everos.memory.cascade.vector_embedding import VECTOR_DIM
from app.everos.memory.vector_auto_rebuild import (
    VectorFallbackRebuildWorker,
    VectorRebuildSpec,
)

pytestmark = pytest.mark.no_db


class _Embedder:
    async def embed(self, _text: str) -> list[float]:
        return [1.0] * VECTOR_DIM


class _FailingEmbedder:
    async def embed(self, _text: str) -> list[float]:
        raise RuntimeError("embedding still unavailable")


class _Repo:
    def __init__(self) -> None:
        self.rows = [_Row()]
        self.updates: list[dict[str, object]] = []

    async def find_where(self, _where: str, *, limit: int):
        return self.rows[:limit]

    async def update(self, updates: dict[str, object], *, where: str) -> None:
        assert where == "id = 'row-1'"
        self.updates.append(updates)


class _Row:
    id = "row-1"
    text = "hello memory"


def _now() -> dt.datetime:
    return dt.datetime(2026, 7, 21, 10, 0, tzinfo=dt.UTC)


async def test_vector_auto_rebuild_worker_rebuilds_fallback_rows_once():
    repo = _Repo()
    worker = VectorFallbackRebuildWorker(
        specs=[
            VectorRebuildSpec(
                kind="episode",
                repo=repo,
                text_getter=lambda row: row.text,
            )
        ],
        embedder=_Embedder(),
        embedding_model="text-embedding-v4",
        batch_size=10,
        failure_cooldown_seconds=600,
        now=_now,
    )

    result = await worker.run_once()

    assert result.rebuilt == 1
    assert result.failed_kind is None
    assert repo.updates[0]["vector"] == [1.0] * VECTOR_DIM
    assert repo.updates[0]["vector_status"] == "ready"


async def test_vector_auto_rebuild_worker_cools_down_after_failure():
    repo = _Repo()
    worker = VectorFallbackRebuildWorker(
        specs=[
            VectorRebuildSpec(
                kind="agent_skill",
                repo=repo,
                text_getter=lambda row: row.text,
            )
        ],
        embedder=_FailingEmbedder(),
        embedding_model="text-embedding-v4",
        batch_size=10,
        failure_cooldown_seconds=600,
        now=_now,
    )

    first = await worker.run_once()
    second = await worker.run_once()

    assert first.rebuilt == 0
    assert first.failed_kind == "agent_skill"
    assert "embedding still unavailable" in (first.error or "")
    assert second.skipped_for_cooldown is True
    assert repo.updates == []
