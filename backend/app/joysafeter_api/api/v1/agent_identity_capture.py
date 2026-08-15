"""Prepare task-scoped agent identity capture for HTTP submission paths."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext
from app.joysafeter_identity.config import (
    AgentIdentityProvider,
    resolve_agent_identity_provider,
)
from app.joysafeter_identity.service import (
    capture_identity_credential,
    validate_provider_configuration,
)

logger = logging.getLogger(__name__)

IdentityCaptureHook = Callable[[JoySafeterTask], Awaitable[None]]


def _decode_vault_key(vault_key: str) -> bytes:
    try:
        key_bytes = bytes.fromhex(vault_key) if len(vault_key) == 64 else base64.b64decode(vault_key, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("JOYSAFETER_VAULT_ENCRYPTION_KEY must encode a 32-byte key") from exc
    if len(key_bytes) != 32:
        raise ValueError("JOYSAFETER_VAULT_ENCRYPTION_KEY must encode a 32-byte key")
    return key_bytes


def validate_agent_identity_configuration() -> None:
    provider = resolve_agent_identity_provider()
    if provider is AgentIdentityProvider.NONE:
        return
    validate_provider_configuration()
    try:
        _decode_vault_key(os.environ.get("JOYSAFETER_VAULT_ENCRYPTION_KEY", ""))
        _context_ttl()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _encrypt(value: str, vault_key: str) -> str:
    """Encrypt a credential using the shared versioned AES-256-GCM envelope."""
    if not value:
        raise ValueError("identity credential must be non-empty")
    key_bytes = _decode_vault_key(vault_key)

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ciphertext = AESGCM(key_bytes).encrypt(nonce, value.encode(), None)
    return "enc:v1:" + base64.b64encode(nonce + ciphertext).decode()


def _context_ttl() -> timedelta:
    raw_value = os.environ.get("AGENT_IDENTITY_CONTEXT_TTL_SECONDS", "300").strip()
    try:
        seconds = int(raw_value)
    except ValueError as exc:
        raise ValueError("AGENT_IDENTITY_CONTEXT_TTL_SECONDS must be an integer") from exc
    if not 30 <= seconds <= 900:
        raise ValueError("AGENT_IDENTITY_CONTEXT_TTL_SECONDS must be between 30 and 900")
    return timedelta(seconds=seconds)


async def prepare_agent_identity_capture(
    db: AsyncSession,
    request: Request | Any | None,
    auth_ctx: Any,
    agent: Any,
    identity_auth_code: str | None = None,
) -> IdentityCaptureHook | None:
    """Validate and encrypt identity input before a task is created.

    The returned hook persists the already-encrypted context for the newly
    created task. Callers must execute it before dispatching the task.
    """
    if resolve_agent_identity_provider() is AgentIdentityProvider.NONE:
        return None

    agent_metadata = getattr(agent, "metadata_", None) or getattr(agent, "metadata", None)
    if isinstance(agent_metadata, dict):
        identity_config = agent_metadata.get("agent_identity")
        if isinstance(identity_config, dict) and not identity_config.get("enabled", True):
            return None

    captured_credential = capture_identity_credential(request, identity_auth_code)
    if captured_credential is None:
        return None

    credential_kind = captured_credential.kind
    credential = captured_credential.value
    credential_fingerprint = hashlib.sha256(credential.encode()).hexdigest() if credential_kind == "auth_code" else None
    encrypted_credential = _encrypt(
        credential,
        os.environ.get("JOYSAFETER_VAULT_ENCRYPTION_KEY", ""),
    )
    captured_at = datetime.now(timezone.utc)
    expires_at = captured_at + _context_ttl()
    project_id = getattr(auth_ctx, "project_id", None)
    user_id = str(auth_ctx.user_id)
    user_name = user_id

    from app.joysafeter_domain.models.joysafeter_auth import AuthUser

    result = await db.execute(select(AuthUser.email).where(AuthUser.id == auth_ctx.user_id).limit(1))
    email = result.scalar_one_or_none()
    if email:
        user_name = email

    async def persist(task: JoySafeterTask) -> None:
        if getattr(task, "project_id", None) != project_id:
            raise RuntimeError("task identity project scope does not match authenticated project")
        db.add(
            JoySafeterTaskIdentityContext(
                task_id=task.id,
                project_id=project_id,
                user_id=user_id,
                user_name=user_name,
                credential_kind=credential_kind,
                credential_fingerprint=credential_fingerprint,
                encrypted_credential=encrypted_credential,
                captured_at=captured_at,
                expires_at=expires_at,
            )
        )
        await db.commit()

    return persist
