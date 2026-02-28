"""
OpenClaw Chat API — proxy to the user's OpenClaw /v1/chat/completions
and /tools/invoke endpoints.

Automatically ensures the user's instance is running before forwarding.
Supports SSE streaming for chat completions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.openclaw_instance_service import OpenClawInstanceService

router = APIRouter(prefix="/v1/openclaw/chat", tags=["OpenClaw Chat"])


class ChatMessage(BaseModel):
    role: str = "user"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = Field(default="openclaw:main")
    stream: bool = Field(default=True)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ToolInvokeRequest(BaseModel):
    tool: str
    input: Dict[str, Any] = Field(default_factory=dict)


@router.post("")
async def chat_completions(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Proxy chat completions to the user's OpenClaw instance.
    Returns SSE stream if stream=True, JSON otherwise."""
    service = OpenClawInstanceService(db)
    instance = await service.ensure_instance_running(str(current_user.id))
    url = f"{service.get_gateway_url(instance)}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {instance.gateway_token}",
        "Content-Type": "application/json",
    }

    body = payload.model_dump(exclude_none=True)

    if payload.stream:
        return StreamingResponse(
            _stream_sse(url, headers, body),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()


async def _stream_sse(url: str, headers: dict, body: dict):
    """Forward SSE stream from OpenClaw gateway."""
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        yield f"{line}\n\n"
                    else:
                        yield "\n"
    except Exception as e:
        yield f"data: {{'error': '{str(e)}'}}\n\n"


@router.post("/tools/invoke")
async def invoke_tool(
    payload: ToolInvokeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Proxy tool invocation to the user's OpenClaw instance."""
    service = OpenClawInstanceService(db)
    instance = await service.ensure_instance_running(str(current_user.id))
    url = f"{service.get_gateway_url(instance)}/tools/invoke"
    headers = {
        "Authorization": f"Bearer {instance.gateway_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload.model_dump(), headers=headers)
        resp.raise_for_status()
        return resp.json()
