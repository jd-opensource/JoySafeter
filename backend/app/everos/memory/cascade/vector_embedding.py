"""Shared embedding helper for LanceDB-backed memory rows.

Keyword retrieval only needs BM25 token columns, but the LanceDB schemas
also require a fixed-width ``vector`` column. When the embedding service
is temporarily unavailable, cascade can still write a keyword-searchable
row by storing a zero vector and marking it as fallback.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any, Callable

from app.everos.component.utils.datetime import get_utc_now
from app.everos.core.observability.logging import get_logger

logger = get_logger(__name__)

VECTOR_DIM = 1024
READY_VECTOR_STATUS = "ready"
FALLBACK_VECTOR_STATUS = "fallback_zero"
FAILED_VECTOR_STATUS = "failed"


@dataclasses.dataclass(frozen=True)
class IndexedVector:
    vector: list[float]
    vector_status: str
    vector_updated_at: dt.datetime | None
    embedding_model: str | None


async def embed_text_for_index(
    embedder: Any,
    text: str,
    *,
    allow_fallback: bool = True,
    embedding_model: str | None = None,
    now: Callable[[], dt.datetime] = get_utc_now,
) -> IndexedVector:
    """Embed text for index writes, optionally falling back to zero vector."""
    try:
        vector = await embedder.embed(text)
    except Exception as exc:  # noqa: BLE001 - preserve keyword indexing path.
        if not allow_fallback:
            raise
        logger.warning(
            "memory_embedding_fallback_zero_vector",
            error=str(exc),
        )
        return IndexedVector(
            vector=[0.0] * VECTOR_DIM,
            vector_status=FALLBACK_VECTOR_STATUS,
            vector_updated_at=None,
            embedding_model=None,
        )
    return IndexedVector(
        vector=vector,
        vector_status=READY_VECTOR_STATUS,
        vector_updated_at=now(),
        embedding_model=embedding_model,
    )
