"""Prepare task-scoped agent identity capture for HTTP submission paths."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.composition import compose_task_identity_material_adapter
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
from app.joysafeter_infrastructure.task_identity.material_adapter import TaskIdentityMaterialConfigurationError
from app.joysafeter_shared.common.joysafeter_auth.context import JoySafeterAuthContext

logger = logging.getLogger(__name__)

IdentityCaptureHook = Callable[[JoySafeterTask], Awaitable[None]]


def validate_agent_identity_configuration() -> None:
    provider = resolve_agent_identity_provider()
    if provider is AgentIdentityProvider.NONE:
        return
    validate_provider_configuration()
    try:
        compose_task_identity_material_adapter(
            os.environ.get("JOYSAFETER_VAULT_ENCRYPTION_KEY", ""),
            keyring_json=os.environ.get("JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING"),
            write_key_id=os.environ.get("JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID"),
        ).require_enabled()
        _context_ttl()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _encrypt(value: str, vault_key: str) -> str:
    try:
        return compose_task_identity_material_adapter(
            vault_key,
            keyring_json=os.environ.get("JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING"),
            write_key_id=os.environ.get("JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID"),
        ).protect_identity_credential(value)
    except TaskIdentityMaterialConfigurationError as exc:
        raise ValueError(f"credential encryption configuration must contain valid 32-byte keys: {exc}") from exc


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
    auth_ctx: JoySafeterAuthContext,
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
    project_id = auth_ctx.project_id
    user_id = auth_ctx.user_id
    user_name = str(user_id)

    from app.joysafeter_domain.models.joysafeter_auth import AuthUser

    result = await db.execute(select(AuthUser.email).where(AuthUser.id == user_id).limit(1))
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
