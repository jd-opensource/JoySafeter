"""Agent identity context capture.

Shared helper for capturing the triggering user's identity credential
(internal SSO cookie or one-time bot_auth_code) and storing it encrypted
in ``session.metadata.agent_identity_context``.

The Rust orchestrator reads this during sandbox resolution to obtain a
BotToken from the JD identity platform (createBotToken / exchangeBotToken),
then exchanges it for a short-lived agentToken injected via Envoy.

This lives in its own module (not tasks.py) so BOTH the task-creation path
(POST /tasks) and the session-message path (POST /sessions/{id}/events) can
call it without a circular import.
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _encrypt(value: str, vault_key: str) -> str:
    """AES-256-GCM encrypt, matching the Rust VaultCipher ``enc:`` format."""
    if not vault_key or not value:
        return value
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key_bytes = bytes.fromhex(vault_key) if len(vault_key) == 64 else base64.b64decode(vault_key)
        nonce = os.urandom(12)
        aesgcm = AESGCM(key_bytes)
        ciphertext = aesgcm.encrypt(nonce, value.encode(), None)
        return "enc:" + base64.b64encode(nonce + ciphertext).decode()
    except Exception:
        return value  # plaintext fallback (Rust decrypt_or_passthrough handles it)


async def store_agent_identity_context(
    db: AsyncSession,
    session_id,
    request: Request,
    auth_ctx,
    agent,
    bot_auth_code: str | None = None,
) -> None:
    """Capture and encrypt the triggering user's identity into session.metadata.

    Global mode: applies to all agents when JD_AGENT_IDENTITY_BASE_URL is set,
    unless the agent explicitly opts out via metadata.agent_identity.enabled=false.
    """
    if not os.environ.get("JD_AGENT_IDENTITY_BASE_URL", "").strip():
        return  # Identity platform not configured

    agent_metadata = getattr(agent, "metadata_", None) or getattr(agent, "metadata", None)
    if isinstance(agent_metadata, dict):
        identity_config = agent_metadata.get("agent_identity")
        if isinstance(identity_config, dict) and not identity_config.get("enabled", True):
            return  # Explicit per-agent opt-out

    # --- Resolve credential: bot_auth_code (API) or SSO cookie (Web) ---
    identity_token = None
    if not bot_auth_code:
        identity_cookie_name = os.environ.get(
            "JD_AGENT_IDENTITY_COOKIE_NAME", "sso.jd.com"
        ).strip()
        identity_token = request.cookies.get(identity_cookie_name)

    if not bot_auth_code and not identity_token:
        logger.info(
            "[agent-identity] no SSO credential for session=%s (cookie '%s' absent, no bot_auth_code)",
            session_id,
            os.environ.get("JD_AGENT_IDENTITY_COOKIE_NAME", "sso.jd.com"),
        )
        return

    vault_key = os.environ.get("JOYSAFETER_VAULT_ENCRYPTION_KEY", "")

    # --- User email for cache keying ---
    user_name = auth_ctx.user_id
    try:
        from app.joysafeter_domain.models.joysafeter_auth import AuthUser

        result = await db.execute(
            select(AuthUser.email).where(AuthUser.id == auth_ctx.user_id).limit(1)
        )
        email = result.scalar_one_or_none()
        if email:
            user_name = email
    except Exception:
        pass

    # --- Build payload ---
    context_payload: dict = {
        "user_name": user_name,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    if bot_auth_code:
        context_payload["auth_code"] = _encrypt(bot_auth_code, vault_key)
        context_payload["source"] = "bot_auth_code"
    else:
        context_payload["identity_token"] = _encrypt(identity_token, vault_key)
        context_payload["source"] = "cookie"

    headers_map = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in ("authorization", "x-api-key")
    }
    if headers_map:
        context_payload["headers_map"] = headers_map

    context_data = {"agent_identity_context": context_payload}

    # --- Persist ---
    # Use CAST(... AS jsonb) instead of the ``::jsonb`` shorthand: with asyncpg
    # the ``:name::jsonb`` form makes the driver misparse ``::`` against the
    # ``:name`` bind marker, raising "syntax error at or near :". CAST avoids it.
    try:
        await db.execute(
            text(
                """
                UPDATE joysafeter_sessions
                SET metadata = COALESCE(metadata, CAST('{}' AS jsonb))
                               || CAST(:ctx AS jsonb)
                WHERE id = CAST(:sid AS uuid)
                """
            ),
            {"ctx": json.dumps(context_data), "sid": str(session_id)},
        )
        await db.commit()
        logger.info(
            "[agent-identity] stored identity context for session=%s source=%s",
            session_id,
            context_payload["source"],
        )
    except Exception:
        logger.exception("[agent-identity] failed to store identity context for session=%s", session_id)
        try:
            await db.rollback()
        except Exception:
            pass
