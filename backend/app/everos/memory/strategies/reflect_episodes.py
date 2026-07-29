"""reflect_episodes Cron strategy — weekly Reflection consolidation.

Triggered by a cron schedule (default: ``0 0 * * sun``). Enumerates owner
scopes from the cluster table and runs the :class:`ReflectionOrchestrator`
for each. JoySafeter scopes are constrained to active agents and active
sessions so automatic Reflection matches manual Dreaming lifecycle
semantics. Configuration lives in ``[reflection]`` of ``config/default.toml``.

The strategy is a thin entry point: it constructs the orchestrator with
production singletons and iterates over owners. All business logic
lives in :mod:`everos.memory.reflection.orchestrator`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.everos.component.embedding import get_embedder
from app.everos.component.llm import get_project_llm_client
from app.everos.core.observability.logging import get_logger
from app.everos.core.persistence import MemoryRoot
from app.everos.infra.ome.context import StrategyContext
from app.everos.infra.ome.decorator import offline_strategy
from app.everos.infra.ome.events import CronTick
from app.everos.infra.ome.triggers import Cron
from app.everos.infra.persistence.lancedb import (
    atomic_fact_repo,
    episode_repo,
)
from app.everos.infra.persistence.markdown import EpisodeWriter
from app.everos.infra.persistence.sqlite import (
    cluster_repo,
    reflection_report_repo,
)
from app.everos.memory.events import EpisodeExtracted
from app.everos.memory.reflection import ReflectionOrchestrator

if TYPE_CHECKING:
    from app.everos.component.embedding import EmbeddingProvider

logger = get_logger(__name__)

_episode_writer: EpisodeWriter | None = None


@dataclass(frozen=True)
class _ActiveJoySafeterScopes:
    active_agent_ids: set[str]
    active_session_ids: set[str]


def _get_episode_writer() -> EpisodeWriter:
    """Return the lazily-initialised EpisodeWriter singleton."""
    global _episode_writer
    if _episode_writer is None:
        _episode_writer = EpisodeWriter(root=MemoryRoot.default())
    return _episode_writer


@offline_strategy(
    name="reflect_episodes",
    trigger=Cron(expr="0 0 * * sun"),
    emits=[EpisodeExtracted],
    enabled=True,
    max_retries=1,
)
async def reflect_episodes(event: CronTick, ctx: StrategyContext) -> None:
    """Run Reflection for eligible owner scopes.

    Args:
        event: Cron tick event (unused; triggers the scheduled run).
        ctx: OME strategy context for emit and logging.
    """
    # Deferred: avoid pulling LLM libs at module import time.
    from everalgo.user_memory import EpisodeReflector

    owners = await cluster_repo.list_distinct_owners()
    scope_app_id = getattr(event, "app_id", None)
    scope_project_id = getattr(event, "project_id", None)
    active_only_event = getattr(event, "scope_mode", None) == "active_only"
    event_active_agent_ids = set(getattr(event, "active_agent_ids", ()) or ())
    event_active_session_ids = set(getattr(event, "active_session_ids", ()) or ())
    scoped_owners = [
        (owner_id, owner_type, app_id, project_id)
        for owner_id, owner_type, app_id, project_id in owners
        if (scope_app_id is None or app_id == scope_app_id)
        and (scope_project_id is None or project_id == scope_project_id)
    ]
    automatic_joysafeter_scopes = (
        {}
        if active_only_event
        else await _load_active_joysafeter_scopes(
            {
                project_id
                for _, _, app_id, project_id in scoped_owners
                if app_id == "joysafeter"
            }
        )
    )
    embedder = get_embedder()
    targets = [
        (
            owner_id,
            owner_type,
            app_id,
            project_id,
            active_session_ids,
        )
        for owner_id, owner_type, app_id, project_id in scoped_owners
        for active_session_ids in [
            _resolve_active_session_scope(
                owner_id=owner_id,
                owner_type=owner_type,
                app_id=app_id,
                project_id=project_id,
                active_only_event=active_only_event,
                event_active_agent_ids=event_active_agent_ids,
                event_active_session_ids=event_active_session_ids,
                automatic_joysafeter_scopes=automatic_joysafeter_scopes,
            )
        ]
        if active_session_ids is not _SKIP_OWNER
    ]
    await asyncio.gather(
        *(
            _run_reflection_for_owner(
                ctx=ctx,
                owner_id=owner_id,
                owner_type=owner_type,
                app_id=app_id,
                project_id=project_id,
                embedder=embedder,
                reflector_cls=EpisodeReflector,
                active_session_ids=active_session_ids,
            )
            for owner_id, owner_type, app_id, project_id, active_session_ids in targets
        )
    )


_SKIP_OWNER = object()


def _resolve_active_session_scope(
    *,
    owner_id: str,
    owner_type: str,
    app_id: str,
    project_id: str,
    active_only_event: bool,
    event_active_agent_ids: set[str],
    event_active_session_ids: set[str],
    automatic_joysafeter_scopes: dict[str, _ActiveJoySafeterScopes],
) -> set[str] | None | object:
    if active_only_event:
        if owner_type == "agent" and owner_id not in event_active_agent_ids:
            return _SKIP_OWNER
        return event_active_session_ids

    if app_id != "joysafeter":
        return None

    active_scope = automatic_joysafeter_scopes.get(project_id)
    if active_scope is None:
        return _SKIP_OWNER
    if owner_type == "agent" and owner_id not in active_scope.active_agent_ids:
        return _SKIP_OWNER
    return active_scope.active_session_ids


async def _load_active_joysafeter_scopes(
    project_ids: set[str],
) -> dict[str, _ActiveJoySafeterScopes]:
    if not project_ids:
        return {}

    from sqlalchemy import select

    from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
    from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
    from app.joysafeter_shared.database import AsyncSessionLocal
    from app.joysafeter_shared.everos_scope import (
        everos_path_safe_id,
        extract_joysafeter_project_id,
    )

    everos_project_ids_by_db_project_id: dict[str, set[str]] = {}
    for project_id in project_ids:
        db_project_id = extract_joysafeter_project_id(project_id) or project_id
        everos_project_ids_by_db_project_id.setdefault(db_project_id, set()).add(project_id)

    scopes = {
        project_id: _ActiveJoySafeterScopes(
            active_agent_ids=set(),
            active_session_ids=set(),
        )
        for project_id in project_ids
    }
    db_project_ids = set(everos_project_ids_by_db_project_id)

    async with AsyncSessionLocal() as db:
        agent_result = await db.execute(
            select(JoySafeterAgent.project_id, JoySafeterAgent.id).where(
                JoySafeterAgent.project_id.in_(db_project_ids),
                JoySafeterAgent.archived_at.is_(None),
                JoySafeterAgent.deleted_at.is_(None),
            )
        )
        for db_project_id, agent_id in agent_result.all():
            for project_id in everos_project_ids_by_db_project_id.get(db_project_id, ()):
                scopes[project_id].active_agent_ids.add(
                    everos_path_safe_id(str(agent_id), "default_agent")
                )

        session_result = await db.execute(
            select(JoySafeterSession.project_id, JoySafeterSession.id).where(
                JoySafeterSession.project_id.in_(db_project_ids),
                JoySafeterSession.archived_at.is_(None),
            )
        )
        for db_project_id, session_id in session_result.all():
            for project_id in everos_project_ids_by_db_project_id.get(db_project_id, ()):
                scopes[project_id].active_session_ids.add(
                    everos_path_safe_id(str(session_id), "default_session")
                )

    return scopes


async def _run_reflection_for_owner(
    *,
    ctx: StrategyContext,
    owner_id: str,
    owner_type: str,
    app_id: str,
    project_id: str,
    embedder: "EmbeddingProvider",
    reflector_cls: type,
    active_session_ids: set[str] | None = None,
) -> None:
    llm_client = await get_project_llm_client(project_id)
    orchestrator = ReflectionOrchestrator(
        cluster_repo=cluster_repo,
        episode_store=episode_repo,
        atomic_fact_store=atomic_fact_repo,
        episode_writer=_get_episode_writer(),
        report_repo=reflection_report_repo,
        reflector=reflector_cls(llm=llm_client),
        embedder=embedder,
        llm_client=llm_client,
    )
    await orchestrator.run(
        ctx=ctx,
        owner_id=owner_id,
        owner_type=owner_type,
        app_id=app_id,
        project_id=project_id,
        active_session_ids=active_session_ids,
    )
