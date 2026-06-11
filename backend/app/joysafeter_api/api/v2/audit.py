"""V2 audit helpers for JoySafeter sensitive operations."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext
from app.joysafeter_domain.services.security_audit_service import SecurityAuditService


async def audit_joysafeter_event(
    db: AsyncSession,
    request: Request,
    auth_ctx: JoySafeterAuthContext,
    *,
    event_type: str,
    event_status: str = "success",
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit log for v2 sensitive operations.

    Audit failures must not break the user-facing operation, so this helper logs
    exceptions and returns.
    """
    payload: dict[str, Any] = {
        "org_id": auth_ctx.org_id,
        "project_id": auth_ctx.project_id,
        "role": auth_ctx.role.value,
    }
    if target_type:
        payload["target_type"] = target_type
    if target_id:
        payload["target_id"] = target_id
    if details:
        payload.update(details)

    try:
        await SecurityAuditService(db).log_event(
            event_type=event_type,
            event_status=event_status,
            ip_address=request.client.host if request.client else "unknown",
            user_id=auth_ctx.user_id,
            user_agent=request.headers.get("user-agent"),
            details=payload,
        )
    except Exception:
        logger.warning("Failed to write JoySafeter audit event", exc_info=True)
