"""
Traces API (path: /api/v1/traces)

Query historical execution trace data. Supports trace listing, single trace
detail, and observation listing.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import AccessDeniedError, NotFoundError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.observation.model import Observation, Trace
from app.joysafeter_domain.schemas import BaseResponse

router = APIRouter(prefix="/v1/traces", tags=["Traces"])


# ==================== Response Schemas ====================


class TraceSchema(BaseResponse):
    """Single trace representation (field-level, not the envelope)."""

    class Config:
        from_attributes = True


# ==================== Endpoints ====================


@router.get("", response_model=BaseResponse)
async def list_traces(
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    agent_version_id: Optional[uuid.UUID] = Query(None, description="Filter by Agent Version ID"),
    session_id: Optional[str] = Query(None, description="Filter by session (thread) ID"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """List traces, sorted by created_at DESC."""
    stmt = select(Trace).where(Trace.project_id == auth_ctx.project_id).order_by(Trace.created_at.desc())
    if agent_version_id is not None:
        stmt = stmt.where(Trace.agent_version_id == agent_version_id)
    if session_id is not None:
        stmt = stmt.where(Trace.session_id == session_id)

    offset = (page - 1) * page_size
    stmt = stmt.limit(page_size).offset(offset)
    result = await db.execute(stmt)
    traces = list(result.scalars().all())

    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_trace_to_dict(t) for t in traces],
    )


@router.get("/{trace_id}", response_model=BaseResponse)
async def get_trace(
    trace_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """Get a single Trace record by ID."""
    trace = (await db.execute(select(Trace).where(Trace.id == trace_id))).scalar_one_or_none()
    if trace is None:
        raise NotFoundError("Trace not found", code="TRACE_NOT_FOUND", data={"trace_id": str(trace_id)})

    if trace.project_id != auth_ctx.project_id:
        raise AccessDeniedError("No access to trace", code="TRACE_ACCESS_DENIED")

    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=_trace_to_dict(trace),
    )


@router.get("/{trace_id}/observations", response_model=BaseResponse)
async def get_trace_observations(
    trace_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    type: Optional[str] = Query(None, description="Filter by observation type (e.g. GENERATION)"),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """Return a flat list of observations for a trace, optionally filtered by type."""
    trace = (await db.execute(select(Trace).where(Trace.id == trace_id))).scalar_one_or_none()
    if trace is None:
        raise NotFoundError("Trace not found", code="TRACE_NOT_FOUND", data={"trace_id": str(trace_id)})

    if trace.project_id != auth_ctx.project_id:
        raise AccessDeniedError("No access to trace", code="TRACE_ACCESS_DENIED")

    stmt = select(Observation).where(Observation.trace_id == trace_id).order_by(Observation.start_time.asc())
    if type is not None:
        stmt = stmt.where(Observation.type == type)

    result = await db.execute(stmt)
    observations = list(result.scalars().all())

    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_observation_to_dict(o) for o in observations],
    )


# ==================== Helpers ====================


def _trace_to_dict(trace: Trace) -> dict[str, Any]:
    return {
        "id": str(trace.id),
        "name": trace.name,
        "project_id": str(trace.project_id) if trace.project_id else None,
        "execution_id": str(trace.execution_id),
        "agent_version_id": str(trace.agent_version_id),
        "user_id": str(trace.user_id),
        "status": trace.status,
        "input": trace.input,
        "output": trace.output,
        "metadata": trace.meta,
        "start_time": trace.start_time.isoformat() if trace.start_time else None,
        "end_time": trace.end_time.isoformat() if trace.end_time else None,
        "duration_ms": trace.duration_ms,
        "total_observations": trace.total_observations,
        "total_tokens": trace.total_tokens,
        "total_cost": float(trace.total_cost) if trace.total_cost is not None else None,
        "tags": trace.tags,
        "session_id": trace.session_id,
        "environment": trace.environment,
        "release": trace.release,
        "version": trace.version,
        "bookmarked": trace.bookmarked,
        "public": trace.public,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }


def _observation_to_dict(obs: Observation) -> dict[str, Any]:
    return {
        "id": str(obs.id),
        "trace_id": str(obs.trace_id),
        "parent_observation_id": str(obs.parent_observation_id) if obs.parent_observation_id else None,
        "type": obs.type,
        "name": obs.name,
        "level": obs.level,
        "status_message": obs.status_message,
        "environment": obs.environment,
        "start_time": obs.start_time.isoformat() if obs.start_time else None,
        "end_time": obs.end_time.isoformat() if obs.end_time else None,
        "completion_start_time": obs.completion_start_time.isoformat() if obs.completion_start_time else None,
        "input": obs.input,
        "output": obs.output,
        "metadata": obs.meta,
        "model": obs.model,
        "model_parameters": obs.model_parameters,
        "usage_details": obs.usage_details,
        "cost_details": obs.cost_details,
        "prompt_name": obs.prompt_name,
        "prompt_version": obs.prompt_version,
        "tool_definitions": obs.tool_definitions,
        "tool_calls": obs.tool_calls,
        "execution_id": str(obs.execution_id),
        "project_id": str(obs.project_id) if hasattr(obs, "project_id") and obs.project_id else None,
        "created_at": obs.created_at.isoformat() if obs.created_at else None,
    }
