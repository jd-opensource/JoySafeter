"""Copilot API — SSE stream (legacy) + execution-engine dispatch (new)."""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser, get_current_user
from app.core.database import get_db
from app.schemas import BaseResponse
from app.schemas.copilot import CopilotRunRequest, CopilotRunResponse, CopilotStreamRequest
from app.services.copilot_service import CopilotService

router = APIRouter(prefix="/v1/copilot", tags=["copilot"])


@router.post("/stream")
async def copilot_stream(
    body: CopilotStreamRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream copilot graph-editing actions as Server-Sent Events (legacy)."""
    service = CopilotService(
        user_id=str(current_user.id),
        provider_name=body.provider_name,
        model_name=body.model_name,
        db=db,
    )

    async def event_generator():
        async for event in service.generate_actions_stream(
            prompt=body.prompt,
            graph_context=body.graph_context,
            conversation_history=body.conversation_history,
            mode=body.mode or "deepagents",
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
