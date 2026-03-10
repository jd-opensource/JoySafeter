"""
OpenAPI Graph 路由 — 通过 API Key 认证触发 Graph 执行

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

from app.common.openapi_auth import get_api_key_user
from app.core.database import get_db
from app.models.api_key import ApiKey
from app.models.auth import AuthUser as User
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


# ─── Endpoints ─────────────────────────────────────


@router.post("/{graph_id}/run")
async def run_graph(
    request: Request,
    graph_id: uuid.UUID,
    payload: RunGraphRequest = RunGraphRequest(),
    auth: tuple[User, ApiKey] = Depends(get_api_key_user),
    db: AsyncSession = Depends(get_db),
):
    """
    启动 Graph 执行

    通过 API Key 认证，启动一个 Graph 的异步执行。
    返回 executionId 用于后续查询状态和获取结果。
    """
    user, api_key = auth
    log = _bind_log(request, user_id=str(user.id), graph_id=str(graph_id))
    log.info("openapi.graph.run start")

    service = OpenApiGraphService(db)
    result = await service.run_graph(
        graph_id=graph_id,
        user_id=user.id,
        api_key_id=api_key.id,
        variables=payload.variables,
        workspace_id=api_key.workspace_id,
    )

    log.info(f"openapi.graph.run success execution_id={result['executionId']}")
    return {"success": True, "data": result}


@router.get("/{execution_id}/status")
async def get_execution_status(
    request: Request,
    execution_id: uuid.UUID,
    auth: tuple[User, ApiKey] = Depends(get_api_key_user),
    db: AsyncSession = Depends(get_db),
):
    """
    查询执行状态

    返回执行的当前状态（init / executing / finish / failed）。
    """
    user, api_key = auth
    log = _bind_log(request, user_id=str(user.id), execution_id=str(execution_id))
    log.info("openapi.graph.status start")

    service = OpenApiGraphService(db)
    result = await service.get_status(execution_id, user.id)

    log.info(f"openapi.graph.status success status={result['status']}")
    return {"success": True, "data": result}


@router.post("/{execution_id}/abort")
async def abort_execution(
    request: Request,
    execution_id: uuid.UUID,
    auth: tuple[User, ApiKey] = Depends(get_api_key_user),
    db: AsyncSession = Depends(get_db),
):
    """
    中止执行

    中止一个正在运行的 Graph 执行。
    """
    user, api_key = auth
    log = _bind_log(request, user_id=str(user.id), execution_id=str(execution_id))
    log.info("openapi.graph.abort start")

    service = OpenApiGraphService(db)
    result = await service.abort_execution(execution_id, user.id)

    log.info(f"openapi.graph.abort success status={result['status']}")
    return {"success": True, "data": result}


@router.get("/{execution_id}/result")
async def get_execution_result(
    request: Request,
    execution_id: uuid.UUID,
    auth: tuple[User, ApiKey] = Depends(get_api_key_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取执行结果

    获取 Graph 执行的输出结果。
    如果执行尚未完成，output 为 null。
    """
    user, api_key = auth
    log = _bind_log(request, user_id=str(user.id), execution_id=str(execution_id))
    log.info("openapi.graph.result start")

    service = OpenApiGraphService(db)
    result = await service.get_result(execution_id, user.id)

    log.info(f"openapi.graph.result success status={result['status']}")
    return {"success": True, "data": result}
