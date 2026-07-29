"""Best-effort EverOS session flush, triggered on session archival."""

from __future__ import annotations

import logging
import os
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_shared.everos_scope import (
    compose_everos_project_id,
    everos_path_safe_id,
)

logger = logging.getLogger(__name__)


def _everos_base_url() -> str:
    return (
        os.getenv("EVEROS_INTERNAL_BASE_URL")
        or os.getenv("EVEROS_BASE_URL")
        or "http://everos:8003"
    ).rstrip("/")


async def _resolve_everos_project_id(db: AsyncSession, project_id: str) -> str:
    stable = everos_path_safe_id(project_id or "default_project", "default_project")
    result = await db.execute(select(Project.slug).where(Project.id == project_id).limit(1))
    slug = result.scalar_one_or_none()
    if not slug:
        return stable
    return compose_everos_project_id(project_slug=slug, project_id=stable)


async def flush_everos_session(
    db: AsyncSession, *, session_id: uuid.UUID, project_id: str
) -> None:
    """POST EverOS /flush for a just-archived session. Never raises."""
    try:
        everos_project_id = await _resolve_everos_project_id(db, project_id)
        everos_session_id = everos_path_safe_id(str(session_id), "default_session")
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            resp = await client.post(
                f"{_everos_base_url()}/api/v1/memory/flush",
                json={
                    "session_id": everos_session_id,
                    "app_id": "joysafeter",
                    "project_id": everos_project_id,
                },
            )
            resp.raise_for_status()
    except Exception as exc:  # best-effort: never block archival
        logger.warning("everos archive flush failed for session %s: %s", session_id, exc)
