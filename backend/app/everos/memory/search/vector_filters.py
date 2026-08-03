"""Helpers for keeping fallback zero vectors out of dense retrieval."""

from __future__ import annotations

from app.everos.memory.cascade.vector_embedding import FALLBACK_VECTOR_STATUS


def exclude_fallback_vectors(where: str) -> str:
    """Return a predicate that keeps explicit zero-vector fallbacks out."""
    return (
        f"({where}) AND "
        f"(vector_status IS NULL OR vector_status != '{FALLBACK_VECTOR_STATUS}')"
    )
