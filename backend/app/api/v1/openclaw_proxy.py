"""
OpenClaw HTTP reverse proxy — enables iframe embedding of the native
OpenClaw Web UI (Control Dashboard + WebChat).

All requests to /api/v1/openclaw/proxy/{path} are forwarded to the user's
OpenClaw Gateway running on its allocated port.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.core.settings import settings
from app.models.auth import AuthUser as User
from app.services.openclaw_instance_service import OpenClawInstanceService

router = APIRouter(prefix="/v1/openclaw/proxy", tags=["OpenClaw Proxy"])

PROXY_TIMEOUT = 300
SKIP_RESPONSE_HEADERS = {
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "content-security-policy",
    "x-frame-options",
}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_to_openclaw(
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reverse proxy any request to the user's OpenClaw gateway."""
    service = OpenClawInstanceService(db)
    instance = await service.get_instance_by_user(str(current_user.id))

    if not instance or instance.status != "running":
        return Response(content="OpenClaw instance not running", status_code=503)

    target_url = f"http://127.0.0.1:{instance.gateway_port}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    body = await request.body()

    upstream_headers = dict(request.headers)
    upstream_headers.pop("host", None)
    upstream_headers["Authorization"] = f"Bearer {instance.gateway_token}"

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT, follow_redirects=True) as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                content=body if body else None,
                headers=upstream_headers,
            )

        response_headers = {}
        for k, v in resp.headers.multi_items():
            if k.lower() not in SKIP_RESPONSE_HEADERS:
                response_headers[k] = v

        parsed = urlparse(settings.frontend_url)
        frontend_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        if frontend_origin:
            response_headers["Content-Security-Policy"] = f"frame-ancestors 'self' {frontend_origin}"
        response_headers["Access-Control-Allow-Origin"] = "*"

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=response_headers,
            media_type=resp.headers.get("content-type"),
        )
    except httpx.ConnectError:
        return Response(content="Cannot reach OpenClaw gateway", status_code=502)
    except httpx.TimeoutException:
        return Response(content="Gateway timeout", status_code=504)
