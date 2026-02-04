"""
登录后初始化 - 与普通登录/OAuth 登录共用

统一执行：更新最后登录时间与 IP、记录登录成功审计、确保个人空间。
供 auth_service.login 与 oauth_callback 调用，避免逻辑分散。
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.auth import AuthUser


async def run_post_login_init(db: AsyncSession, user: "AuthUser", ip_address: str) -> None:
    """
    登录成功后统一初始化：更新 last_login、审计、确保个人空间。

    与 auth_service.login 及 oauth_callback 行为一致，集中维护。
    """
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip_address
    await db.commit()

    try:
        from app.services.security_audit_service import SecurityAuditService

        audit_service = SecurityAuditService(db)
        await audit_service.log_event(
            event_type="login_success",
            event_status="success",
            ip_address=ip_address or "unknown",
            user_id=user.id,
            user_email=user.email,
        )
    except Exception:
        pass

    try:
        from app.services.workspace_service import WorkspaceService

        workspace_service = WorkspaceService(db)
        await workspace_service.ensure_personal_workspace(user)
    except Exception:
        pass
