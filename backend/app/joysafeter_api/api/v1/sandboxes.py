from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_sandbox import SandboxResponse
from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService
from app.joysafeter_shared.common.app_errors import AppError, NotFoundError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import SandboxId

router = APIRouter(tags=["joysafeter-sandboxes"])


def _sandbox_not_found_error(sandbox_id: SandboxId) -> AppError:
    return NotFoundError(
        code="SANDBOX_NOT_FOUND",
        message="Sandbox not found",
        data={"sandbox_id": str(sandbox_id)},
        user_action="refresh",
    )


@router.get("")
async def list_sandboxes(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[SandboxId] = Query(None),
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
    sandbox_id: SandboxId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SandboxResponse:
    svc = SandboxService(db)
    sandbox = await svc.get_sandbox(sandbox_id, project_id=auth_ctx.project_id)
    if not sandbox:
        raise _sandbox_not_found_error(sandbox_id)
    return SandboxResponse.model_validate(sandbox)


@router.delete("/{sandbox_id}", status_code=204)
async def stop_sandbox(
    sandbox_id: SandboxId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = SandboxService(db)
    stopped = await svc.stop_sandbox(sandbox_id, project_id=auth_ctx.project_id)
    if not stopped:
        raise _sandbox_not_found_error(sandbox_id)
