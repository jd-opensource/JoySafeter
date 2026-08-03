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

from app.everos.component.embedding import get_embedder
from app.everos.component.llm import get_project_llm_client
from app.everos.core.observability.logging import get_logger
from app.everos.core.persistence import MemoryRoot
from app.everos.infra.ome.context import StrategyContext
from app.everos.infra.ome.decorator import offline_strategy
from app.everos.infra.ome.events import CronTick, ScopedManualTick
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
from app.everos.memory.language_policy import ensure_chinese_memory_llm
from app.everos.memory.reflection import ReflectionOrchestrator

logger = get_logger(__name__)

_episode_writer: EpisodeWriter | None = None
_REFLECTION_LLM_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True)
class _ActiveJoySafeterScopes:
    active_agent_ids: set[str]
    active_session_ids: set[str]


@dataclass(frozen=True)
class ReflectionOwnerResult:
    owner_id: str
    owner_type: str
    app_id: str
    project_id: str
    success_count: int
    failure_count: int
    failure_reason: str | None = None


class ReflectionRunFailed(RuntimeError):
    """Raised when a reflection strategy run had work but produced no successes."""


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
    max_retries=3,
)
async def reflect_episodes(event: CronTick, ctx: StrategyContext) -> None:
    """Run Reflection for all owner scopes.

    Args:
        event: Cron tick event (unused; triggers the scheduled run).
        ctx: OME strategy context for emit and logging.
    """
    owners = await cluster_repo.list_distinct_owners()
    scopes = await _resolve_owner_scopes(event, owners)
    results = await asyncio.gather(
        *(
            _run_reflection_for_owner(
                ctx=ctx,
                owner_id=owner_id,
                owner_type=owner_type,
                app_id=app_id,
                project_id=project_id,
                active_session_ids=active_session_ids,
            )
            for owner_id, owner_type, app_id, project_id, active_session_ids in scopes
        )
    )
    _raise_if_reflection_failed(results)


def _raise_if_reflection_failed(results: list[ReflectionOwnerResult]) -> None:
    success_count = sum(result.success_count for result in results)
    failure_count = sum(result.failure_count for result in results)
    if failure_count <= 0:
        return
    failure_reasons = [
        result.failure_reason
        for result in results
        if result.failure_reason
    ]
    reason_suffix = (
        f"; latest_reason={failure_reasons[-1]}"
        if failure_reasons
        else ""
    )
    if success_count <= 0:
        raise ReflectionRunFailed(
            "all reflection work failed "
            f"(owner_count={len(results)}, failure_count={failure_count}"
            f"{reason_suffix})"
        )
    log_fields = {
        "owner_count": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
    }
    if failure_reasons:
        log_fields["latest_reason"] = failure_reasons[-1]
    logger.warning("reflection_cycle_partial_failure", **log_fields)


async def _resolve_owner_scopes(
    event: CronTick,
    owners: list[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str, set[str] | None]]:
    if isinstance(event, ScopedManualTick):
        return _resolve_manual_owner_scopes(event, owners)

    joysafeter_project_ids = {
        project_id
        for _, _, app_id, project_id in owners
        if app_id == "joysafeter"
    }
    active_by_project = await _load_active_joysafeter_scopes(joysafeter_project_ids)
    scopes: list[tuple[str, str, str, str, set[str] | None]] = []
    for owner_id, owner_type, app_id, project_id in owners:
        if app_id != "joysafeter":
            scopes.append((owner_id, owner_type, app_id, project_id, None))
            continue
        active = active_by_project.get(project_id)
        if active is None:
            scopes.append((owner_id, owner_type, app_id, project_id, set()))
            continue
        if owner_type == "agent" and owner_id not in active.active_agent_ids:
            continue
        scopes.append(
            (
                owner_id,
                owner_type,
                app_id,
                project_id,
                set(active.active_session_ids),
            )
        )
    return scopes


def _resolve_manual_owner_scopes(
    event: ScopedManualTick,
    owners: list[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str, set[str] | None]]:
    active_agent_ids = set(event.active_agent_ids)
    active_session_ids = set(event.active_session_ids)
    scopes: list[tuple[str, str, str, str, set[str] | None]] = []
    for owner_id, owner_type, app_id, project_id in owners:
        if app_id != event.app_id or project_id != event.project_id:
            continue
        if event.scope_mode == "active_only":
            if owner_type == "agent" and owner_id not in active_agent_ids:
                continue
            scopes.append((owner_id, owner_type, app_id, project_id, active_session_ids))
        else:
            scopes.append((owner_id, owner_type, app_id, project_id, None))
    return scopes


async def _load_active_joysafeter_scopes(
    project_ids: set[str],
) -> dict[str, _ActiveJoySafeterScopes]:
    if not project_ids:
        return {}
    try:
        from sqlalchemy import select

        from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_shared.everos_scope import (
            everos_path_safe_id,
            extract_joysafeter_project_id,
        )
    except Exception:
        logger.warning("reflection_active_scope_loader_unavailable", exc_info=True)
        return {project_id: _ActiveJoySafeterScopes(set(), set()) for project_id in project_ids}

    joy_project_ids = {
        project_id: extract_joysafeter_project_id(project_id) or project_id
        for project_id in project_ids
    }
    active: dict[str, _ActiveJoySafeterScopes] = {
        everos_project_id: _ActiveJoySafeterScopes(set(), set())
        for everos_project_id in project_ids
    }
    async with AsyncSessionLocal() as db:
        agent_rows = (
            await db.execute(
                select(JoySafeterAgent.id, JoySafeterAgent.project_id).where(
                    JoySafeterAgent.project_id.in_(set(joy_project_ids.values())),
                    JoySafeterAgent.archived_at.is_(None),
                    JoySafeterAgent.deleted_at.is_(None),
                )
            )
        ).all()
        session_rows = (
            await db.execute(
                select(JoySafeterSession.id, JoySafeterSession.project_id).where(
                    JoySafeterSession.project_id.in_(set(joy_project_ids.values())),
                    JoySafeterSession.archived_at.is_(None),
                )
            )
        ).all()

    everos_by_joy = {joy_id: everos_id for everos_id, joy_id in joy_project_ids.items()}
    for agent_id, joy_project_id in agent_rows:
        everos_project_id = everos_by_joy.get(str(joy_project_id))
        if everos_project_id in active:
            active[everos_project_id].active_agent_ids.add(
                everos_path_safe_id(str(agent_id), "default_agent")
            )
    for session_id, joy_project_id in session_rows:
        everos_project_id = everos_by_joy.get(str(joy_project_id))
        if everos_project_id in active:
            active[everos_project_id].active_session_ids.add(
                everos_path_safe_id(str(session_id), "default_session")
            )
    return active


async def _run_reflection_for_owner(
    *,
    ctx: StrategyContext,
    owner_id: str,
    owner_type: str,
    app_id: str,
    project_id: str,
    active_session_ids: set[str] | None,
) -> ReflectionOwnerResult:
    # Deferred: avoid pulling LLM libs at module import time.
    from everalgo.user_memory import EpisodeReflector

    llm_client = await get_project_llm_client(
        project_id,
        default_timeout_seconds=_REFLECTION_LLM_TIMEOUT_SECONDS,
    )
    llm_client = ensure_chinese_memory_llm(llm_client)
    orchestrator = ReflectionOrchestrator(
        cluster_repo=cluster_repo,
        episode_store=episode_repo,
        atomic_fact_store=atomic_fact_repo,
        episode_writer=_get_episode_writer(),
        report_repo=reflection_report_repo,
        reflector=EpisodeReflector(llm=llm_client),
        embedder=get_embedder(),
        llm_client=llm_client,
    )
    reports = await orchestrator.run(
        ctx=ctx,
        owner_id=owner_id,
        owner_type=owner_type,
        app_id=app_id,
        project_id=project_id,
        active_session_ids=active_session_ids,
    )
    return ReflectionOwnerResult(
        owner_id=owner_id,
        owner_type=owner_type,
        app_id=app_id,
        project_id=project_id,
        success_count=len(reports),
        failure_count=getattr(
            orchestrator,
            "failure_count",
            getattr(orchestrator, "reflector_failure_count", 0),
        ),
        failure_reason=getattr(orchestrator, "failure_reason", None),
    )
