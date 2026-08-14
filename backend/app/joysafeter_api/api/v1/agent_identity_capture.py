"""Agent identity context capture (provider-agnostic).

Shared helper that captures the triggering user's identity credential and
stores it encrypted in ``session.metadata.agent_identity_context``. This is a
generic bridge: the API layer can access the user's HTTP request (cookies /
headers) but does not perform any identity-provider protocol itself — the
orchestrator's pluggable identity provider consumes this context later.

What gets captured (whichever is available):
  - an identity credential from a configured request cookie (browser flow), or
  - a one-time identity auth code supplied by an API caller.

Enablement and the cookie name are entirely env-driven, so this module carries
no provider-specific values. It lives in its own module (not tasks.py) so both
the task-creation path (POST /tasks) and the session-message path
(POST /sessions/{id}/events) can call it without a circular import.

Environment variables:
  - AGENT_IDENTITY_ENABLED / AGENT_IDENTITY_BASE_URL: when neither is set,
    capture is a no-op (feature disabled).
  - AGENT_IDENTITY_COOKIE_NAME: name of the request cookie holding the user's
    identity credential. Required for the browser flow; if unset, only the
    auth-code path works.
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


def _identity_enabled() -> bool:
    """Whether identity capture is active (env-driven, provider-agnostic)."""
    if os.environ.get("AGENT_IDENTITY_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        return True
    return bool(os.environ.get("AGENT_IDENTITY_BASE_URL", "").strip())


def _encrypt(value: str, vault_key: str) -> str:
    """AES-256-GCM encrypt, matching the orchestrator's VaultCipher ``enc:`` format."""
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
        return value  # plaintext fallback (orchestrator decrypt_or_passthrough handles it)


async def store_agent_identity_context(
    db: AsyncSession,
    session_id,
    request: Request,
    auth_ctx,
    agent,
    identity_auth_code: str | None = None,
) -> None:
    """Capture and encrypt the triggering user's identity into session.metadata.

    Applies to all agents when identity capture is enabled, unless the agent
    explicitly opts out via ``metadata.agent_identity.enabled = false``.
    """
    if not _identity_enabled():
        return  # Identity capture disabled

    agent_metadata = getattr(agent, "metadata_", None) or getattr(agent, "metadata", None)
    if isinstance(agent_metadata, dict):
        identity_config = agent_metadata.get("agent_identity")
        if isinstance(identity_config, dict) and not identity_config.get("enabled", True):
            return  # Explicit per-agent opt-out

    # --- Resolve credential: auth code (API) or request cookie (browser) ---
    cookie_name = os.environ.get("AGENT_IDENTITY_COOKIE_NAME", "").strip()
    identity_token = None
    if not identity_auth_code and cookie_name:
        identity_token = request.cookies.get(cookie_name)

    if not identity_auth_code and not identity_token:
        logger.info(
            "[agent-identity] no identity credential for session=%s "
            "(auth_code absent, cookie '%s' absent)",
            session_id,
            cookie_name or "<unset>",
        )
        return

    vault_key = os.environ.get("JOYSAFETER_VAULT_ENCRYPTION_KEY", "")

    # --- Resolve user account name for downstream cache keying ---
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
    if identity_auth_code:
        context_payload["auth_code"] = _encrypt(identity_auth_code, vault_key)
        context_payload["source"] = "auth_code"
    else:
        context_payload["identity_token"] = _encrypt(identity_token, vault_key)
        context_payload["source"] = "cookie"

    # NOTE: We deliberately do NOT persist the raw request headers/cookies. They
    # contain the user's full credential set and must not sit in the DB. The
    # orchestrator reconstructs any provider-required headers from the
    # (encrypted) identity_token at exchange time instead.

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
