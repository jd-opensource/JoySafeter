"""
OpenClaw HTTP reverse proxy — enables iframe embedding of the native
OpenClaw Web UI (Control Dashboard + WebChat).

All requests to /api/v1/openclaw/proxy/{path} are forwarded to the user's
OpenClaw Gateway running on its allocated port.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, Request, Response
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.core.settings import settings
from app.models.auth import AuthUser as User
from app.services.openclaw_instance_service import OpenClawInstanceService

router = APIRouter(prefix="/v1/openclaw/proxy", tags=["OpenClaw Proxy"])

PROXY_TIMEOUT = 300


def _make_inject_script(ws_url: str, token: str) -> str:
    """Script to set Control UI connection config in localStorage (runs before app)."""
    ws_js = json.dumps(ws_url)
    tok_js = json.dumps(token)
    return f"""<script>(function(){{
        try {{
            var k="openclaw.control.settings.v1";
            var s=localStorage.getItem(k);
            var o=s?JSON.parse(s):{{}};
            o.gatewayUrl={ws_js};
            o.token={tok_js};
            localStorage.setItem(k,JSON.stringify(o));
            localStorage.setItem("gatewayUrl",{ws_js});
            localStorage.setItem("token",{tok_js});
        }}catch(e){{}}
    }})();</script>"""


def _inject_script_into_html(html: str, script: str) -> str:
    """Inject script as early as possible (after <head> or at <body> start)."""
    if "<head" in html:
        return re.sub(r"(<head[^>]*>)", r"\1" + script, html, count=1, flags=re.I)
    if "<body" in html:
        return re.sub(r"(<body[^>]*>)", r"\1" + script, html, count=1, flags=re.I)
    return script + html


async def _poll_approve_devices(container_id: str) -> None:
    """Wait and poll to approve devices shortly after UI triggers websocket connect."""
    if not container_id:
        return
    for _ in range(8):  # Poll every 1.5s for up to 12s
        await asyncio.sleep(1.5)
        try:
            result = subprocess.run(
                ["docker", "exec", container_id, "openclaw", "devices", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                continue
            devices = json.loads(result.stdout) if result.stdout else {}
            pending = devices.get("pending", [])
            for p in pending:
                request_id = p.get("requestId")
                if request_id:
                    subprocess.run(
                        ["docker", "exec", container_id, "openclaw", "devices", "approve", request_id],
                        capture_output=True,
                        timeout=30,
                    )
                    logger.info(
                        f"[Auto-Pair] Approved device request {request_id} for openclaw container {container_id}"
                    )
            if pending:
                break  # We found and approved pending devices, done polling.
        except Exception as e:
            logger.warning(f"[Auto-Pair] Background approve devices failed: {e}")


SKIP_RESPONSE_HEADERS = {
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "content-security-policy",
    "x-frame-options",
    "content-length",
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

    base_url = service.get_gateway_url(instance)
    target_url = f"{base_url}/{path}"

    # For Control UI entry pages, inject gatewayUrl + token so the dashboard can auto-connect
    entry_paths = ("", "overview", "index.html")
    path_normalized = (path or "").rstrip("/") or ""
    is_entry = path_normalized in entry_paths

    # Auto device pair: wait for the client to connect WebSocket and then approve
    if is_entry and instance.container_id:
        asyncio.create_task(_poll_approve_devices(instance.container_id))

    query_params = {k: v for k, v in parse_qs(request.url.query).items()}
    if is_entry:
        scheme = "wss" if request.url.scheme == "https" else "ws"
        host = request.url.hostname or "localhost"
        ws_url = f"{scheme}://{host}:{instance.gateway_port}"
        query_params["gatewayUrl"] = [ws_url]
        query_params["token"] = [instance.gateway_token]

    if query_params:
        target_url += "?" + urlencode(query_params, doseq=True)

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

        content = resp.content
        # Iframe: Control UI may ignore URL params. Inject localStorage for auto-connect.
        if is_entry and resp.status_code == 200:
            ct = (resp.headers.get("content-type") or "").lower()
            if "text/html" in ct:
                scheme = "wss" if request.url.scheme == "https" else "ws"
                host = request.url.hostname or "localhost"
                ws_url = f"{scheme}://{host}:{instance.gateway_port}"
                inj = _make_inject_script(ws_url, instance.gateway_token)
                try:
                    html = content.decode("utf-8", errors="replace")
                    content = _inject_script_into_html(html, inj).encode("utf-8")
                except Exception:
                    pass

        return Response(
            content=content,
            status_code=resp.status_code,
            headers=response_headers,
            media_type=resp.headers.get("content-type"),
        )
    except httpx.ConnectError:
        return Response(content="Cannot reach OpenClaw gateway", status_code=502)
    except httpx.TimeoutException:
        return Response(content="Gateway timeout", status_code=504)
