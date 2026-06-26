import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.schemas.joysafeter_sandbox import SandboxResponse
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_api.services import SandboxService

router = APIRouter(tags=["joysafeter-sandboxes"])


@router.get("")
async def list_sandboxes(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SandboxResponse]:
    svc = SandboxService(db)
    sandboxes, has_more = await svc.list_sandboxes(limit, after_id, project_id=auth_ctx.project_id)
    data = [SandboxResponse.model_validate(s) for s in sandboxes]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{sandbox_id}")
async def get_sandbox(
    sandbox_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SandboxResponse:
    svc = SandboxService(db)
    sandbox = await svc.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(404, "Sandbox not found")
    if sandbox.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Sandbox not found")
    return SandboxResponse.model_validate(sandbox)


@router.delete("/{sandbox_id}", status_code=204)
async def stop_sandbox(
    sandbox_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = SandboxService(db)
    sandbox = await svc.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(404, "Sandbox not found")
    if sandbox.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Sandbox not found")
    await svc.stop_sandbox(sandbox_id)
