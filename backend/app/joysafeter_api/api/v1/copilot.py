"""Copilot API — execution-engine dispatch."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, require_joysafeter_write
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.schemas import BaseResponse
from app.joysafeter_domain.schemas.copilot import CopilotRunRequest, CopilotRunResponse
from app.joysafeter_api.services import DispatchService

router = APIRouter(prefix="/v1/copilot", tags=["copilot"])


@router.post("/run", response_model=BaseResponse[CopilotRunResponse])
async def copilot_run(
    body: CopilotRunRequest,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
):
    """Dispatch copilot through the execution engine for persistent history."""
    dispatch = DispatchService(db)
    run = await dispatch.dispatch_copilot_draft(
        agent_id=body.agent_id,
        version_id=body.version_id,
        project_id=auth_ctx.project_id,
        prompt=body.prompt,
        user_id=auth_ctx.user_id,
        graph_context=body.graph_context,
        conversation_history=body.conversation_history,
        mode=body.mode,
        provider_name=body.provider_name,
        model_name=body.model_name,
    )

    return BaseResponse(
        success=True,
        code=200,
        msg="Copilot run created",
        data=CopilotRunResponse(
            run_id=str(run.id),
            execution_id=str(run.current_execution_id),
        ),
    )
