"""
Post-login initialization shared by normal login and OAuth login.

Update last-login time and IP, record a login-success audit event, and ensure
the personal workspace exists.  Called by auth_service.login and oauth_callback
to keep the logic centralized.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.auth import AuthUser

from app.models.enums import SecurityAuditEventType


async def run_post_login_init(db: AsyncSession, user: "AuthUser", ip_address: str) -> None:
    """
    Run unified post-login initialization: update last_login, audit, ensure personal workspace.

    Consistent with auth_service.login and oauth_callback; maintained in one place.
    """
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip_address
    await db.commit()

    try:
        from app.services.security_audit_service import SecurityAuditService

        audit_service = SecurityAuditService(db)
        await audit_service.log_event(
            event_type=SecurityAuditEventType.LOGIN_SUCCESS,
            event_status="success",
            ip_address=ip_address or "unknown",
            user_id=user.id,
            user_email=user.email,
        )
    except Exception:
        logger.warning("Failed to create security audit entry", exc_info=True)

    try:
        from app.services.workspace_service import WorkspaceService

        workspace_service = WorkspaceService(db)
        await workspace_service.ensure_personal_workspace(user)
    except Exception:
        logger.warning("Failed to ensure personal workspace during login", exc_info=True)
