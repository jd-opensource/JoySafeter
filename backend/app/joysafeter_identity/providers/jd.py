from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

from app.joysafeter_identity.types import CapturedIdentityCredential
from app.joysafeter_shared.ids import AgentId

logger = logging.getLogger(__name__)


def validate_configuration() -> None:
    missing = [
        name
        for name in ("AGENT_IDENTITY_BASE_URL", "AGENT_IDENTITY_ALLOWED_HOSTS")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise RuntimeError("AGENT_IDENTITY_PROVIDER=jd requires configuration: " + ", ".join(missing))


def capture_credential(
    request: Any | None,
    identity_auth_code: str | None,
) -> CapturedIdentityCredential | None:
    auth_code = identity_auth_code.strip() if identity_auth_code else None
    if auth_code:
        return CapturedIdentityCredential(kind="auth_code", value=auth_code)

    cookie_name = os.environ.get("AGENT_IDENTITY_COOKIE_NAME", "").strip()
    cookies = getattr(request, "cookies", {}) if request is not None else {}
    identity_token = cookies.get(cookie_name) if cookie_name else None
    if not isinstance(identity_token, str) or not identity_token.strip():
        return None
    return CapturedIdentityCredential(
        kind="identity_token",
        value=identity_token.strip(),
    )


async def cleanup_agent_identity(agent_id: AgentId) -> None:
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        redis_host = os.environ.get("REDIS_HOST", "")
        if not redis_host:
            return
        redis_port = os.environ.get("REDIS_PORT", "6379")
        redis_password = os.environ.get("REDIS_PASSWORD", "")
        if redis_password:
            redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/0"
        else:
            redis_url = f"redis://{redis_host}:{redis_port}/0"

    try:
        import httpx
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url)
        pattern = f"joysafeter:bot_token:*:*:{agent_id.uuid}:*:*:*"
        base_url = os.environ.get("AGENT_IDENTITY_BASE_URL", "").strip().rstrip("/")
        deleted = 0
        async with httpx.AsyncClient(timeout=10.0) as http:
            async for key in client.scan_iter(match=pattern, count=100):
                bot_token = await client.get(key)
                if base_url and bot_token:
                    if isinstance(bot_token, bytes):
                        bot_token = bot_token.decode()
                    try:
                        await http.post(
                            f"{base_url}/ai/identity/sec/api/revokeBotToken",
                            json={
                                "traceId": str(uuid.uuid4()),
                                "botToken": bot_token,
                                "timestamp": int(time.time() * 1000),
                            },
                        )
                    except Exception as exc:
                        logger.warning(
                            "JD agent identity token revoke failed for %s (non-fatal): %s",
                            agent_id,
                            exc,
                        )
                await client.delete(key)
                deleted += 1
        await client.aclose()
        if deleted:
            logger.info(
                "Cleared %s JD agent identity cache entries for agent %s",
                deleted,
                agent_id,
            )
    except Exception as exc:
        logger.warning(
            "JD agent identity cleanup failed for %s (non-fatal): %s",
            agent_id,
            exc,
        )
