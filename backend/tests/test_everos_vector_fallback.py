import datetime as dt
from dataclasses import dataclass

from app.everos.memory.cascade.vector_embedding import (
    FALLBACK_VECTOR_STATUS,
    READY_VECTOR_STATUS,
    VECTOR_DIM,
    embed_text_for_index,
)
from app.everos.memory.search.vector_filters import exclude_fallback_vectors
from app.everos.memory.vector_rebuild import rebuild_fallback_rows


class _FailingEmbedder:
    async def embed(self, _text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


class _WorkingEmbedder:
    async def embed(self, _text: str) -> list[float]:
        return [1.0] * VECTOR_DIM


@dataclass
class _Row:
    id: str
    episode: str
    vector_status: str | None = FALLBACK_VECTOR_STATUS


class _Repo:
    def __init__(self) -> None:
        self.rows = [_Row(id="row-1", episode="hello memory")]
        self.updates: list[tuple[str, dict[str, object]]] = []

    async def find_where(self, where: str, *, limit: int) -> list[_Row]:
        assert where == "vector_status = 'fallback_zero'"
        assert limit == 10
        return self.rows

    async def update(self, updates: dict[str, object], *, where: str) -> None:
        self.updates.append((where, updates))


async def test_embed_text_for_index_falls_back_to_zero_vector_when_allowed():
    result = await embed_text_for_index(
        _FailingEmbedder(),
        "hello memory",
        allow_fallback=True,
    )

    assert result.vector == [0.0] * VECTOR_DIM
    assert result.vector_status == FALLBACK_VECTOR_STATUS
    assert result.vector_updated_at is None
    assert result.embedding_model is None


async def test_embed_text_for_index_raises_when_fallback_is_disallowed():
    try:
        await embed_text_for_index(
            _FailingEmbedder(),
            "hello memory",
            allow_fallback=False,
        )
    except RuntimeError as exc:
        assert str(exc) == "embedding unavailable"
    else:
        raise AssertionError("expected embedding failure to propagate")


def test_exclude_fallback_vectors_adds_status_predicate():
    assert exclude_fallback_vectors("owner_id = 'alice'") == (
        "(owner_id = 'alice') AND "
        "(vector_status IS NULL OR vector_status != 'fallback_zero')"
    )


async def test_rebuild_fallback_rows_updates_vector_status_to_ready():
    repo = _Repo()

    count = await rebuild_fallback_rows(
        repo,
        text_getter=lambda row: row.episode,
        embedder=_WorkingEmbedder(),
        embedding_model="text-embedding-v4",
        now=lambda: dt.datetime(2026, 7, 21, tzinfo=dt.UTC),
        limit=10,
    )

    assert count == 1
    assert repo.updates == [
        (
            "id = 'row-1'",
            {
                "vector": [1.0] * VECTOR_DIM,
                "vector_status": READY_VECTOR_STATUS,
                "embedding_model": "text-embedding-v4",
                "vector_updated_at": dt.datetime(2026, 7, 21, tzinfo=dt.UTC),
            },
        )
    ]
