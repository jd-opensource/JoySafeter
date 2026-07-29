"""JoySafeter proxy endpoints for EverOS memory views."""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.everos_scope import (
    compose_everos_project_id,
    everos_path_safe_id,
    extract_joysafeter_project_id,
)

router = APIRouter(tags=["joysafeter-everos-memory"])


class DreamingRequest(BaseModel):
    timeout: float = 120.0
    force: bool = False


def _everos_base_url() -> str:
    return (
        os.getenv("EVEROS_INTERNAL_BASE_URL")
        or os.getenv("EVEROS_BASE_URL")
        or "http://everos:8003"
    ).rstrip("/")


@router.post("/get")
async def proxy_everos_memory_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Proxy EverOS /get through JoySafeter lifecycle filtering."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="request body must be an object")

    project_id = _resolve_project_id_from_proxy_payload(payload)
    everos_project_id = await _resolve_everos_project_id(db, project_id)
    active_agent_ids, active_session_ids = await _active_everos_memory_scopes(
        db,
        project_id,
    )
    prepared = _prepare_memory_proxy_payload(
        payload,
        everos_project_id=everos_project_id,
        active_agent_ids=active_agent_ids,
        active_session_ids=active_session_ids,
    )
    if prepared is None:
        return _empty_everos_get_response()
    return await _forward_memory_proxy_request(
        "/api/v1/memory/get",
        prepared,
        active_agent_ids=active_agent_ids,
        active_session_ids=active_session_ids,
    )


@router.post("/search")
async def proxy_everos_memory_search(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Proxy EverOS /search through JoySafeter lifecycle filtering."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="request body must be an object")

    project_id = _resolve_project_id_from_proxy_payload(payload)
    everos_project_id = await _resolve_everos_project_id(db, project_id)
    active_agent_ids, active_session_ids = await _active_everos_memory_scopes(
        db,
        project_id,
    )
    prepared = _prepare_memory_proxy_payload(
        payload,
        everos_project_id=everos_project_id,
        active_agent_ids=active_agent_ids,
        active_session_ids=active_session_ids,
    )
    if prepared is None:
        return _empty_everos_search_response()
    return await _forward_memory_proxy_request(
        "/api/v1/memory/search",
        prepared,
        active_agent_ids=active_agent_ids,
        active_session_ids=active_session_ids,
    )


@router.get("/overview")
async def get_everos_memory_overview(
    limit: int = Query(100, ge=1, le=1000),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return EverOS memories for the current JoySafeter project."""
    everos_project_id = await _resolve_everos_project_id(db, auth_ctx.project_id)
    active_agent_ids, active_session_ids = await _active_everos_memory_scopes(
        db,
        auth_ctx.project_id,
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.get(
                f"{_everos_base_url()}/api/v1/memory/overview",
                params={
                    "app_id": "joysafeter",
                    "project_id": everos_project_id,
                    "limit": limit,
                },
            )
            response.raise_for_status()
            return _filter_overview_by_active_scopes(
                response.json(),
                active_agent_ids=active_agent_ids,
                active_session_ids=active_session_ids,
            )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text or "EverOS memory overview failed",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"EverOS memory service unavailable: {exc}",
        ) from exc


@router.get("/document")
async def get_everos_memory_document(
    md_path: str = Query(..., min_length=1),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the full markdown document for a memory row."""
    everos_project_id = await _resolve_everos_project_id(db, auth_ctx.project_id)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.get(
                f"{_everos_base_url()}/api/v1/memory/document",
                params={
                    "app_id": "joysafeter",
                    "project_id": everos_project_id,
                    "md_path": md_path,
                },
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text or "EverOS memory document failed",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"EverOS memory service unavailable: {exc}",
        ) from exc


@router.post("/dreaming")
async def start_everos_memory_dreaming(
    payload: DreamingRequest,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger EverOS episode reflection for the current project view."""
    everos_project_id = await _resolve_everos_project_id(db, auth_ctx.project_id)
    active_agent_ids, active_session_ids = await _active_everos_memory_scopes(
        db,
        auth_ctx.project_id,
    )
    response = await _forward_dreaming_request(
        timeout=payload.timeout,
        force=payload.force,
        active_agent_ids=active_agent_ids,
        active_session_ids=active_session_ids,
        project_id=everos_project_id,
    )
    return {
        **response,
        "app_id": "joysafeter",
        "project_id": everos_project_id,
    }


@router.get("/dreaming/runs/{run_id}")
async def get_everos_memory_dreaming_run_status(run_id: str) -> dict[str, Any]:
    """Return status for a previously started Dreaming run."""
    response = await _forward_dreaming_run_status(run_id)
    return {
        **response,
        "display_name": "Dreaming",
    }


async def _resolve_everos_project_id(db: AsyncSession, project_id: str) -> str:
    result = await db.execute(select(Project.slug).where(Project.id == project_id).limit(1))
    project_slug = result.scalar_one_or_none()
    if not project_slug:
        return project_id
    return compose_everos_project_id(project_slug=project_slug, project_id=project_id)


def _resolve_project_id_from_proxy_payload(payload: dict[str, Any]) -> str:
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise HTTPException(status_code=422, detail="project_id is required")
    return extract_joysafeter_project_id(project_id) or project_id


async def _active_everos_memory_scopes(
    db: AsyncSession,
    project_id: str,
) -> tuple[set[str], set[str]]:
    agent_result = await db.execute(
        select(JoySafeterAgent.id).where(
            JoySafeterAgent.project_id == project_id,
            JoySafeterAgent.archived_at.is_(None),
            JoySafeterAgent.deleted_at.is_(None),
        )
    )
    session_result = await db.execute(
        select(JoySafeterSession.id).where(
            JoySafeterSession.project_id == project_id,
            JoySafeterSession.archived_at.is_(None),
        )
    )
    active_agent_ids = {
        everos_path_safe_id(str(agent_id), "default_agent")
        for agent_id in agent_result.scalars().all()
    }
    active_session_ids = {
        everos_path_safe_id(str(session_id), "default_session")
        for session_id in session_result.scalars().all()
    }
    return active_agent_ids, active_session_ids


def _filter_overview_by_active_scopes(
    payload: dict[str, Any],
    *,
    active_agent_ids: set[str],
    active_session_ids: set[str],
) -> dict[str, Any]:
    profiles = _list_items(payload.get("profiles"))
    episodes = [
        item for item in _list_items(payload.get("episodes"))
        if _memory_is_active(item)
        and _session_scope_is_active(item, active_session_ids)
    ]
    atomic_facts = [
        item for item in _list_items(payload.get("atomic_facts"))
        if _memory_is_active(item)
        and _session_scope_is_active(item, active_session_ids)
    ]
    agent_cases = [
        item for item in _list_items(payload.get("agent_cases"))
        if _agent_scope_is_active(item, active_agent_ids)
        and _session_scope_is_active(item, active_session_ids)
    ]
    agent_skills = [
        item for item in _list_items(payload.get("agent_skills"))
        if _agent_scope_is_active(item, active_agent_ids)
    ]

    visible_ids_by_kind = {
        "profile": {str(item.get("id")) for item in profiles},
        "episode": {str(item.get("id")) for item in episodes},
        "agent_case": {str(item.get("id")) for item in agent_cases},
        "agent_skill": {str(item.get("id")) for item in agent_skills},
    }
    recent_activity = [
        item for item in _list_items(payload.get("recent_activity"))
        if str(item.get("id")) in visible_ids_by_kind.get(str(item.get("kind")), set())
    ]

    return {
        **payload,
        "counts": {
            "profiles": len(profiles),
            "episodes": len(episodes),
            "agent_cases": len(agent_cases),
            "agent_skills": len(agent_skills),
        },
        "profiles": profiles,
        "episodes": episodes,
        "atomic_facts": atomic_facts,
        "agent_cases": agent_cases,
        "agent_skills": agent_skills,
        "recent_activity": recent_activity,
    }


def _prepare_memory_proxy_payload(
    payload: dict[str, Any],
    *,
    everos_project_id: str,
    active_agent_ids: set[str],
    active_session_ids: set[str],
) -> dict[str, Any] | None:
    memory_type = payload.get("memory_type")
    agent_id = payload.get("agent_id")
    if isinstance(agent_id, str) and memory_type in {"agent_case", "agent_skill"}:
        if agent_id not in active_agent_ids:
            return None

    prepared = dict(payload)
    prepared["app_id"] = "joysafeter"
    prepared["project_id"] = everos_project_id
    if memory_type == "episode":
        prepared["filters"] = _merge_filter_with_active_sessions(
            payload.get("filters"),
            active_session_ids,
            include_aggregated_sources=True,
        )
    elif memory_type in {"atomic_fact", "agent_case"}:
        prepared["filters"] = _merge_filter_with_active_sessions(
            payload.get("filters"),
            active_session_ids,
        )
    return prepared


def _filter_memory_proxy_payload_by_active_scopes(
    payload: dict[str, Any],
    *,
    active_agent_ids: set[str],
    active_session_ids: set[str],
) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return payload

    filtered_data = dict(data)
    filtered_data["profiles"] = _list_items(data.get("profiles"))
    filtered_data["episodes"] = [
        item for item in _list_items(data.get("episodes"))
        if _memory_is_active(item)
        and _session_scope_is_active(item, active_session_ids)
    ]
    filtered_data["atomic_facts"] = [
        item for item in _list_items(data.get("atomic_facts"))
        if _memory_is_active(item)
        and _session_scope_is_active(item, active_session_ids)
    ]
    filtered_data["agent_cases"] = [
        item for item in _list_items(data.get("agent_cases"))
        if _agent_scope_is_active(item, active_agent_ids)
        and _session_scope_is_active(item, active_session_ids)
    ]
    filtered_data["agent_skills"] = [
        item for item in _list_items(data.get("agent_skills"))
        if _agent_scope_is_active(item, active_agent_ids)
    ]
    filtered_data["unprocessed_messages"] = [
        item for item in _list_items(data.get("unprocessed_messages"))
        if _session_scope_is_active(item, active_session_ids)
    ]
    visible_count = sum(
        len(filtered_data.get(key) or [])
        for key in (
            "profiles",
            "episodes",
            "atomic_facts",
            "agent_cases",
            "agent_skills",
            "unprocessed_messages",
        )
    )
    if "count" in filtered_data:
        filtered_data["count"] = visible_count
    if "total_count" in filtered_data:
        filtered_data["total_count"] = visible_count
    return {**payload, "data": filtered_data}


def _merge_filter_with_active_sessions(
    filters: Any,
    active_session_ids: set[str],
    *,
    include_aggregated_sources: bool = False,
) -> dict[str, Any]:
    session_filter = _active_session_filter(
        active_session_ids,
        include_aggregated_sources=include_aggregated_sources,
    )
    if isinstance(filters, dict) and filters:
        return {"AND": [filters, session_filter]}
    return session_filter


def _active_session_filter(
    active_session_ids: set[str],
    *,
    include_aggregated_sources: bool = False,
) -> dict[str, Any]:
    ordered_session_ids = sorted(active_session_ids)
    if not ordered_session_ids:
        return {"session_id": "__no_active_sessions__"}
    if len(ordered_session_ids) == 1:
        session_filter: dict[str, Any] = {"session_id": ordered_session_ids[0]}
        source_filter: dict[str, Any] = {"source_session_id": ordered_session_ids[0]}
    else:
        session_filter = {"session_id": {"in": ordered_session_ids}}
        source_filter = {"source_session_id": {"in": ordered_session_ids}}
    if include_aggregated_sources:
        return {"OR": [session_filter, source_filter]}
    return session_filter


async def _forward_memory_proxy_request(
    upstream_path: str,
    payload: dict[str, Any],
    *,
    active_agent_ids: set[str],
    active_session_ids: set[str],
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.post(
                f"{_everos_base_url()}{upstream_path}",
                json=payload,
            )
            response.raise_for_status()
            return _filter_memory_proxy_payload_by_active_scopes(
                response.json(),
                active_agent_ids=active_agent_ids,
                active_session_ids=active_session_ids,
            )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text or "EverOS memory proxy request failed",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"EverOS memory service unavailable: {exc}",
        ) from exc


async def _forward_dreaming_request(
    *,
    timeout: float,
    force: bool = False,
    active_agent_ids: set[str] | None = None,
    active_session_ids: set[str] | None = None,
    project_id: str = "default",
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
            response = await client.post(
                f"{_everos_base_url()}/api/v1/ome/trigger",
                json={
                    "name": "reflect_episodes",
                    "timeout": timeout,
                    "force": force,
                    "wait": False,
                    "scope_mode": "active_only",
                    "active_agent_ids": sorted(active_agent_ids or set()),
                    "active_session_ids": sorted(active_session_ids or set()),
                    "app_id": "joysafeter",
                    "project_id": project_id,
                },
            )
            response.raise_for_status()
            data = response.json()
            return {
                **data,
                "display_name": "Dreaming",
            }
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text or "EverOS Dreaming request failed",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"EverOS memory service unavailable: {exc}",
        ) from exc


async def _forward_dreaming_run_status(run_id: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.get(
                f"{_everos_base_url()}/api/v1/ome/runs/{run_id}",
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text or "EverOS Dreaming run status failed",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"EverOS memory service unavailable: {exc}",
        ) from exc


def _empty_everos_get_response() -> dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "data": {
            "episodes": [],
            "atomic_facts": [],
            "profiles": [],
            "agent_cases": [],
            "agent_skills": [],
            "total_count": 0,
            "count": 0,
        },
        "score": 0.0,
    }


def _empty_everos_search_response() -> dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "data": {
            "episodes": [],
            "profiles": [],
            "agent_cases": [],
            "agent_skills": [],
            "unprocessed_messages": [],
        },
    }


def _list_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _agent_scope_is_active(item: dict[str, Any], active_agent_ids: set[str]) -> bool:
    owner_id = item.get("owner_id") or item.get("agent_id")
    return isinstance(owner_id, str) and owner_id in active_agent_ids


def _session_scope_is_active(item: dict[str, Any], active_session_ids: set[str]) -> bool:
    session_id = item.get("session_id")
    if isinstance(session_id, str):
        return session_id in active_session_ids
    if item.get("parent_type") != "cluster":
        return True
    source_session_ids = _string_list(item.get("source_session_ids"))
    if not source_session_ids:
        return True
    return any(source_id in active_session_ids for source_id in source_session_ids)


def _memory_is_active(item: dict[str, Any]) -> bool:
    return item.get("deprecated_by") in (None, "")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
