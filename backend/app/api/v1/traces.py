"""
Traces API (path: /api/v1/traces)

Query historical execution trace data. Supports trace listing, single trace detail, and observation listing.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.common.exceptions import ForbiddenException
from app.core.database import get_db
from app.schemas import BaseResponse
from app.services.trace_service import TraceService

router = APIRouter(prefix="/v1/traces", tags=["Traces"])


def _bind_log(request: Request, **kwargs):
    trace_id = getattr(request.state, "trace_id", "-")
    return logger.bind(trace_id=trace_id, **kwargs)


# ==================== Response Schemas ====================


class ObservationSchema(BaseModel):
    """Observation response schema."""

    id: str
    trace_id: str
    parent_observation_id: Optional[str] = None
    type: str
    name: Optional[str] = None
    level: str = "DEFAULT"
    status: str = "RUNNING"
    status_message: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    model_name: Optional[str] = None
    model_provider: Optional[str] = None
    model_parameters: Optional[Any] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    input_cost: Optional[float] = None
    output_cost: Optional[float] = None
    total_cost: Optional[float] = None
    metadata: Optional[Any] = None
    version: Optional[str] = None

    class Config:
        from_attributes = True


class TraceSchema(BaseModel):
    """Trace response schema."""

    id: str
    workspace_id: Optional[str] = None
    graph_id: Optional[str] = None
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    name: Optional[str] = None
    status: str
    input: Optional[Any] = None
    output: Optional[Any] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    total_tokens: Optional[int] = None
    total_cost: Optional[float] = None
    metadata: Optional[Any] = None
    tags: Optional[list] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TraceDetailSchema(BaseModel):
    """Trace detail (with observations)."""

    trace: TraceSchema
    observations: list[ObservationSchema]


class TraceListSchema(BaseModel):
    """Trace list."""

    traces: list[TraceSchema]
    total: int


# ==================== Helper ====================


def _trace_to_schema(trace) -> TraceSchema:
    """Convert a Trace ORM object to a schema."""
    return TraceSchema(
        id=str(trace.id),
        workspace_id=str(trace.workspace_id) if trace.workspace_id else None,
        graph_id=str(trace.graph_id) if trace.graph_id else None,
        thread_id=trace.thread_id,
        user_id=trace.user_id,
        name=trace.name,
        status=trace.status.value if hasattr(trace.status, "value") else str(trace.status),
        input=trace.input,
        output=trace.output,
        start_time=trace.start_time,
        end_time=trace.end_time,
        duration_ms=trace.duration_ms,
        total_tokens=trace.total_tokens,
        total_cost=trace.total_cost,
        metadata=trace.metadata_,
        tags=trace.tags,
        created_at=trace.created_at,
    )


def _obs_to_schema(obs) -> ObservationSchema:
    """Convert an Observation ORM object to a schema."""
    return ObservationSchema(
        id=str(obs.id),
        trace_id=str(obs.trace_id),
        parent_observation_id=str(obs.parent_observation_id) if obs.parent_observation_id else None,
        type=obs.type.value if hasattr(obs.type, "value") else str(obs.type),
        name=obs.name,
        level=obs.level.value if hasattr(obs.level, "value") else str(obs.level),
        status=obs.status.value if hasattr(obs.status, "value") else str(obs.status),
        status_message=obs.status_message,
        start_time=obs.start_time,
        end_time=obs.end_time,
        duration_ms=obs.duration_ms,
        input=obs.input,
        output=obs.output,
        model_name=obs.model_name,
        model_provider=obs.model_provider,
        model_parameters=obs.model_parameters,
        prompt_tokens=obs.prompt_tokens,
        completion_tokens=obs.completion_tokens,
        total_tokens=obs.total_tokens,
        input_cost=obs.input_cost,
        output_cost=obs.output_cost,
        total_cost=obs.total_cost,
        metadata=obs.metadata_,
        version=obs.version,
    )


# ==================== Endpoints ====================


@router.get("", response_model=BaseResponse)
async def list_traces(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    graph_id: Optional[uuid.UUID] = Query(None, description="Filter by Graph ID"),
    workspace_id: Optional[uuid.UUID] = Query(None, description="Filter by Workspace ID"),
    thread_id: Optional[str] = Query(None, description="Filter by Thread ID"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset"),
):
    """List traces (paginated)."""
    log = _bind_log(request, user_id=str(current_user.id))
    service = TraceService(db)

    if workspace_id:
        from app.models.workspace import WorkspaceMemberRole
        from app.services.workspace_permission import check_workspace_access

        has_access = await check_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.viewer)
        if not has_access:
            raise ForbiddenException("No access to workspace traces")

    total = await service.count_traces(graph_id=graph_id, workspace_id=workspace_id, thread_id=thread_id)
    traces = await service.list_traces(
        graph_id=graph_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        limit=limit,
        offset=offset,
    )

    log.debug(
        f"Listed {len(traces)} traces (total={total}) | workspace_id={workspace_id} graph_id={graph_id} thread_id={thread_id}"
    )

    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data={
            "traces": [_trace_to_schema(t).model_dump(mode="json") for t in traces],
            "total": total,
        },
    )


@router.get("/{trace_id}", response_model=BaseResponse)
async def get_trace_detail(
    trace_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Get a single trace's detail with all observations."""
    log = _bind_log(request, user_id=str(current_user.id))
    service = TraceService(db)

    trace = await service.get_trace(trace_id)
    if trace is None:
        return BaseResponse(success=False, code=404, msg="Trace not found", data=None)

    if trace.workspace_id:
        from app.models.workspace import WorkspaceMemberRole
        from app.services.workspace_permission import check_workspace_access

        has_access = await check_workspace_access(db, trace.workspace_id, current_user, WorkspaceMemberRole.viewer)
        if not has_access:
            raise ForbiddenException("No access to workspace traces")

    observations = await service.get_observations_for_trace(trace_id)

    log.debug(f"Fetched trace {trace_id} with {len(observations)} observations")

    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data={
            "trace": _trace_to_schema(trace).model_dump(mode="json"),
            "observations": [_obs_to_schema(o).model_dump(mode="json") for o in observations],
        },
    )


@router.get("/{trace_id}/observations", response_model=BaseResponse)
async def get_trace_observations(
    trace_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Get a flat list of observations for a trace (sorted by time)."""
    log = _bind_log(request, user_id=str(current_user.id))
    service = TraceService(db)

    trace = await service.get_trace(trace_id)
    if trace is None:
        return BaseResponse(success=False, code=404, msg="Trace not found", data=None)

    if trace.workspace_id:
        from app.models.workspace import WorkspaceMemberRole
        from app.services.workspace_permission import check_workspace_access

        has_access = await check_workspace_access(db, trace.workspace_id, current_user, WorkspaceMemberRole.viewer)
        if not has_access:
            raise ForbiddenException("No access to workspace traces")

    observations = await service.get_observations_for_trace(trace_id)

    log.debug(f"Fetched {len(observations)} observations for trace {trace_id}")

    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data={
            "observations": [_obs_to_schema(o).model_dump(mode="json") for o in observations],
        },
    )
