"""audit helpers for JoySafeter sensitive operations."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.services.joysafeter_security_audit_service import SecurityAuditService
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext


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
    commit: bool = True,
    best_effort: bool = True,
) -> None:
    """Write an audit log for v2 sensitive operations.

    Existing callers default to an independent, best-effort commit. Sensitive
    mutation routes can instead flush into their transaction and fail closed.
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
            commit=commit,
            user_id=auth_ctx.user_id,
            user_agent=request.headers.get("user-agent"),
            details=payload,
        )
    except Exception as exc:
        error_payload = async_boundary_error_payload(
            code="AUDIT_EVENT_WRITE_FAILED",
            message="Failed to write JoySafeter audit event",
            boundary="audit",
            operation="write_event",
            data={
                "event_type": event_type,
                "event_status": event_status,
                "target_type": target_type,
                "target_id": target_id,
                "user_id": auth_ctx.user_id,
                "org_id": auth_ctx.org_id,
                "project_id": auth_ctx.project_id,
            },
            source="api",
            retryable=True,
            user_action="retry",
            detail=exc.__class__.__name__,
        )
        logger.bind(error=error_payload).exception("Failed to write JoySafeter audit event")
        if not best_effort:
            raise
