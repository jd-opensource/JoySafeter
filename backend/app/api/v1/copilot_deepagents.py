"""
DeepAgents Copilot API (independent endpoints).

Independent DeepAgents Copilot interface, does not affect existing Copilot:
POST /api/v1/graphs/copilot/deepagents/actions/stream

Features:
- Uses DeepAgents Manager + sub-agent collaboration to generate graphs
- Outputs standard GraphAction (fully compatible with existing Copilot)
- No frontend changes required, SSE event format remains the same
"""

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.copilot.action_types import CopilotRequest
from app.core.copilot_deepagents.streaming import stream_deepagents_actions
from app.core.database import get_db
from app.core.model.utils.credential_resolver import LLMCredentialResolver
from app.models.auth import AuthUser as User
from app.services.copilot_service import CopilotService

router = APIRouter(prefix="/v1/graphs", tags=["Graphs"])


def _bind_log(request: Request, **kwargs):
    trace_id = getattr(request.state, "trace_id", "-")
    return logger.bind(trace_id=trace_id, **kwargs)


# Use unified LLMCredentialResolver for credential fetching


@router.post("/copilot/deepagents/actions/stream", response_class=StreamingResponse)
async def deepagents_copilot_actions_stream(
    request: Request,
    payload: CopilotRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Generate Agent workflow graph using DeepAgents mode (streaming).

    Uses SSE (Server-Sent Events) streaming for DeepAgents workflow.
    Note: Standard Copilot uses WebSocket + async tasks, but DeepAgents
    maintains SSE for its specialized multi-stage processing pipeline.

    Event format compatible with standard Copilot:
    - Accepts the same CopilotRequest input
    - Returns SSE events in the same format
    - Frontend can reuse event handling logic

    SSE Event Types:
    - status: Stage progress {stage, message}
    - content: Streaming content
    - tool_call: Tool invocation {tool, input}
    - tool_result: Tool result {action}  <-- Each action is pushed immediately
    - result: Final result {message, actions}
    - done: Completion
    - error: Error

    DeepAgents Mode Advantages:
    - Sub-agent collaboration: Analysis → Design → Validation → Generation
    - Artifact persistence: /analysis.json, /blueprint.json, /validation.json
    - Auditable: Complete decision process is traceable

    Args:
        payload: CopilotRequest with prompt, graph_context, graph_id
        current_user: Authenticated user
        db: Database session

    Returns:
        StreamingResponse: SSE stream of progress events
    """
    log = _bind_log(request, user_id=str(current_user.id))

    # Get credentials using unified CredentialManager (same as standard Copilot)
    api_key, base_url, llm_model = await LLMCredentialResolver.get_credentials(
        db=db,
        api_key=None,
        base_url=None,
        llm_model=None,
    )

    if not api_key:
        log.warning("No API key found in database, will try OPENAI_API_KEY environment variable")

    async def event_generator():
        try:
            log.info(f"copilot.deepagents.stream start graph_id={payload.graph_id}")

            # Collect data for persistence (same as standard copilot)
            collected_thought_steps: List[Dict[str, Any]] = []
            collected_tool_calls: List[Dict[str, Any]] = []
            final_message = ""
            final_actions: List[Dict[str, Any]] = []

            async for event in stream_deepagents_actions(
                prompt=payload.prompt,
                graph_context=payload.graph_context,
                conversation_history=payload.conversation_history,
                graph_id=payload.graph_id,
                user_id=str(current_user.id),
                api_key=api_key,
                base_url=base_url,
                llm_model=llm_model,
            ):
                # Collect data for persistence
                event_type = event.get("type")

                if event_type == "thought_step":
                    step = event.get("step", {})
                    collected_thought_steps.append(step)
                elif event_type == "tool_call":
                    collected_tool_calls.append(
                        {
                            "tool": event.get("tool", ""),
                            "input": event.get("input", {}),
                        }
                    )
                elif event_type == "result":
                    final_message = event.get("message", "")
                    final_actions = event.get("actions", [])

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # Save messages to database if graph_id is provided
            if payload.graph_id:
                try:
                    service = CopilotService(user_id=str(current_user.id), db=db)
                    saved = await service.save_conversation_from_stream(
                        graph_id=payload.graph_id,
                        prompt=payload.prompt,
                        final_message=final_message,
                        collected_thought_steps=collected_thought_steps,
                        collected_tool_calls=collected_tool_calls,
                        final_actions=final_actions,
                    )
                    if saved:
                        log.info(f"copilot.deepagents.stream saved messages for graph_id={payload.graph_id}")
                    else:
                        log.warning(
                            f"copilot.deepagents.stream failed to save messages for graph_id={payload.graph_id}"
                        )
                except Exception as save_error:
                    log.error(f"copilot.deepagents.stream save error: {save_error}")

            log.info(f"copilot.deepagents.stream success graph_id={payload.graph_id}")

        except Exception as e:
            log.error(f"copilot.deepagents.stream failed error={e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
