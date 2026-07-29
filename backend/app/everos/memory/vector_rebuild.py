"""Rebuild fallback zero vectors after the embedding provider recovers."""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable
from typing import Any

from app.everos.component.utils.datetime import get_utc_now
from app.everos.core.persistence.lancedb.repository import _q
from app.everos.memory.cascade.vector_embedding import (
    FALLBACK_VECTOR_STATUS,
    READY_VECTOR_STATUS,
)


@dataclasses.dataclass(frozen=True)
class VectorRebuildSpec:
    kind: str
    repo: Any
    text_getter: Callable[[Any], str]


async def rebuild_fallback_rows(
    repo: Any,
    *,
    text_getter: Callable[[Any], str],
    embedder: Any,
    embedding_model: str | None,
    now: Callable[[], dt.datetime] = get_utc_now,
    limit: int = 100,
) -> int:
    """Re-embed rows marked ``fallback_zero`` and update them in-place."""
    rows = await repo.find_where(
        f"vector_status = '{FALLBACK_VECTOR_STATUS}'",
        limit=limit,
    )
    updated = 0
    for row in rows:
        vector = await embedder.embed(text_getter(row))
        await repo.update(
            {
                "vector": vector,
                "vector_status": READY_VECTOR_STATUS,
                "embedding_model": embedding_model,
                "vector_updated_at": now(),
            },
            where=f"id = '{_q(row.id)}'",
        )
        updated += 1
    return updated


def default_vector_rebuild_specs() -> list[VectorRebuildSpec]:
    """Return all LanceDB memory kinds that can rebuild fallback vectors."""
    from app.everos.infra.persistence.lancedb import (  # noqa: PLC0415
        agent_case_repo,
        agent_skill_repo,
        atomic_fact_repo,
        episode_repo,
        foresight_repo,
    )

    return [
        VectorRebuildSpec(
            kind="episode",
            repo=episode_repo,
            text_getter=lambda row: row.episode,
        ),
        VectorRebuildSpec(
            kind="atomic_fact",
            repo=atomic_fact_repo,
            text_getter=lambda row: row.fact,
        ),
        VectorRebuildSpec(
            kind="foresight",
            repo=foresight_repo,
            text_getter=lambda row: row.foresight,
        ),
        VectorRebuildSpec(
            kind="agent_case",
            repo=agent_case_repo,
            text_getter=lambda row: row.task_intent,
        ),
        VectorRebuildSpec(
            kind="agent_skill",
            repo=agent_skill_repo,
            text_getter=lambda row: "\n".join(
                s for s in [row.name, row.description] if s
            ),
        ),
    ]
