"""Copilot API — execution-engine dispatch."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.core.database import get_db
from app.schemas import BaseResponse
from app.schemas.copilot import CopilotRunRequest, CopilotRunResponse

router = APIRouter(prefix="/v1/copilot", tags=["copilot"])


@router.post("/run", response_model=BaseResponse[CopilotRunResponse])
async def copilot_run(
    body: CopilotRunRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Dispatch copilot through the execution engine for persistent history.

    Returns run_id + execution_id. Subscribe to the execution WebSocket
    for real-time events (same as any other execution).
    """
    from app.core.engine.orchestrator import ExecutionOrchestrator

    orchestrator = ExecutionOrchestrator(db)
    run = await orchestrator.dispatch_copilot(
        agent_id=body.agent_id,
        prompt=body.prompt,
        user_id=str(current_user.id),
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
