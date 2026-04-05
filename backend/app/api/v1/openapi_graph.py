"""
OpenAPI Graph routes — trigger Graph execution via PlatformToken auth

Endpoints:
- POST /v1/openapi/graph/{graphId}/run      Start execution
- GET  /v1/openapi/graph/{executionId}/status  Query status
- POST /v1/openapi/graph/{executionId}/abort   Abort execution
- GET  /v1/openapi/graph/{executionId}/result   Get result
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth_dependency import AuthContext, get_current_user_or_token
from app.common.exceptions import ForbiddenException
from app.common.permissions import check_token_permission
from app.core.database import get_db
from app.services.openapi_graph_service import OpenApiGraphService

router = APIRouter(prefix="/v1/openapi/graph", tags=["OpenAPI Graph"])


# ─── Request / Response Models ─────────────────────────────────


class RunGraphRequest(BaseModel):
    """Request body for starting a Graph execution."""

    variables: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Runtime variables. message/query is used as the user message; the rest are context variables.",
    )


class OpenApiResponse(BaseModel):
    """Unified response format."""

    success: bool = True
    data: Optional[Dict[str, Any]] = None
    errCode: Optional[str] = None
    errMsg: Optional[str] = None


# ─── Helper ─────────────────────────────────────


def _bind_log(request: Request, **kwargs):
    trace_id = getattr(request.state, "trace_id", "-")
    return logger.bind(trace_id=trace_id, **kwargs)


def _require_graph_execute(auth: AuthContext, graph_id: uuid.UUID) -> None:
    """Require graphs:execute scope if using token auth."""
    if not auth.is_token_auth:
        return
    has_perm = check_token_permission(
        token_scopes=auth.token_scopes or [],
        required_scope="graphs:execute",
        resource_type="graph",
        resource_id=str(graph_id),
        token_resource_type=auth.token_resource_type,
        token_resource_id=auth.token_resource_id,
    )
    if not has_perm:
        raise ForbiddenException("Token missing required scope: graphs:execute")


# ─── Endpoints ─────────────────────────────────────


@router.post("/{graph_id}/run")
async def run_graph(
    request: Request,
    graph_id: uuid.UUID,
    payload: RunGraphRequest = RunGraphRequest(),
    auth: AuthContext = Depends(get_current_user_or_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a Graph execution.

    Authenticate via PlatformToken and start an async Graph execution.
    Returns an executionId for subsequent status queries and result retrieval.
    """
    _require_graph_execute(auth, graph_id)
    user = auth.user
    log = _bind_log(request, user_id=str(user.id), graph_id=str(graph_id))
    log.info("openapi.graph.run start")

    service = OpenApiGraphService(db)
    result = await service.run_graph(
        graph_id=graph_id,
        user_id=user.id,
        variables=payload.variables,
    )

    log.info(f"openapi.graph.run success execution_id={result['executionId']}")
    return {"success": True, "data": result}


@router.get("/{execution_id}/status")
async def get_execution_status(
    request: Request,
    execution_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user_or_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Query execution status.

    Return the current status (init / executing / finish / failed).
    """
    user = auth.user
    log = _bind_log(request, user_id=str(user.id), execution_id=str(execution_id))
    log.info("openapi.graph.status start")

    service = OpenApiGraphService(db)
    result = await service.get_status(execution_id, user.id)

    _require_graph_execute(auth, uuid.UUID(result["graphId"]))

    log.info(f"openapi.graph.status success status={result['status']}")
    return {"success": True, "data": result}


@router.post("/{execution_id}/abort")
async def abort_execution(
    request: Request,
    execution_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user_or_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Abort execution.

    Abort a running Graph execution.
    """
    user = auth.user
    log = _bind_log(request, user_id=str(user.id), execution_id=str(execution_id))
    log.info("openapi.graph.abort start")

    service = OpenApiGraphService(db)
    result = await service.abort_execution(execution_id, user.id)

    _require_graph_execute(auth, uuid.UUID(result["graphId"]))

    log.info(f"openapi.graph.abort success status={result['status']}")
    return {"success": True, "data": result}


@router.get("/{execution_id}/result")
async def get_execution_result(
    request: Request,
    execution_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_user_or_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Get execution result.

    Retrieve the output of a Graph execution.
    If execution is not yet complete, output is null.
    """
    user = auth.user
    log = _bind_log(request, user_id=str(user.id), execution_id=str(execution_id))
    log.info("openapi.graph.result start")

    service = OpenApiGraphService(db)
    result = await service.get_result(execution_id, user.id)

    _require_graph_execute(auth, uuid.UUID(result["graphId"]))

    log.info(f"openapi.graph.result success status={result['status']}")
    return {"success": True, "data": result}
