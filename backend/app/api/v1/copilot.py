"""Copilot SSE endpoint."""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.schemas.copilot import CopilotStreamRequest
from app.services.copilot_service import CopilotService

router = APIRouter(prefix="/v1/copilot", tags=["copilot"])


@router.post("/stream")
async def copilot_stream(
    body: CopilotStreamRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream copilot graph-editing actions as Server-Sent Events."""
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
