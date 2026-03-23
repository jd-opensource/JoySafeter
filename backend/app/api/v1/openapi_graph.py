"""
OpenAPI Graph 路由 — 通过 PlatformToken 认证触发 Graph 执行

端点：
- POST /v1/openapi/graph/{graphId}/run      启动执行
- GET  /v1/openapi/graph/{executionId}/status  查询状态
- POST /v1/openapi/graph/{executionId}/abort   中止执行
- GET  /v1/openapi/graph/{executionId}/result   获取结果
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
    """启动 Graph 执行的请求体"""

    variables: Optional[Dict[str, Any]] = Field(
        default=None,
        description="运行时变量。message/query 用作用户消息，其余作为 context 变量。",
    )


class OpenApiResponse(BaseModel):
    """统一响应格式"""

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
    启动 Graph 执行

    通过 PlatformToken 认证，启动一个 Graph 的异步执行。
    返回 executionId 用于后续查询状态和获取结果。
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
    查询执行状态

    返回执行的当前状态（init / executing / finish / failed）。
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
    中止执行

    中止一个正在运行的 Graph 执行。
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
    获取执行结果

    获取 Graph 执行的输出结果。
    如果执行尚未完成，output 为 null。
    """
    user = auth.user
    log = _bind_log(request, user_id=str(user.id), execution_id=str(execution_id))
    log.info("openapi.graph.result start")

    service = OpenApiGraphService(db)
    result = await service.get_result(execution_id, user.id)

    _require_graph_execute(auth, uuid.UUID(result["graphId"]))

    log.info(f"openapi.graph.result success status={result['status']}")
    return {"success": True, "data": result}
