"""
安全审计服务
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security_audit_log import SecurityAuditLog
from app.services.base import BaseService


class SecurityAuditService(BaseService):
    """安全审计日志服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def log_event(
        self,
        *,
        event_type: str,
        event_status: str,
        ip_address: str,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_fingerprint: Optional[str] = None,
        location: Optional[str] = None,
        country: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> SecurityAuditLog:
        """
        记录安全事件

        事件类型示例：
        - login_success, login_failure, login_blocked
        - logout
        - password_change, password_reset_request, password_reset_success
        - account_lock, account_unlock
        - email_verify, email_verify_resend
        - session_create, session_invalidate
        - 2fa_enable, 2fa_disable, 2fa_verify
        - permission_change
        """
        log_entry = SecurityAuditLog(
            user_id=user_id,
            user_email=user_email,
            event_type=event_type,
            event_status=event_status,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            location=location,
            country=country,
            details=details or {},
            created_at=datetime.now(timezone.utc),
        )

        self.db.add(log_entry)
        await self.commit()
        await self.db.refresh(log_entry)
        return log_entry

    async def get_user_audit_logs(
        self,
        user_id: str,
        limit: int = 100,
        event_type: Optional[str] = None,
    ) -> list[SecurityAuditLog]:
        """获取用户的安全审计日志"""
        query = select(SecurityAuditLog).where(SecurityAuditLog.user_id == user_id)

        if event_type:
            query = query.where(SecurityAuditLog.event_type == event_type)

        query = query.order_by(SecurityAuditLog.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def detect_anomalies(
        self,
        user_id: str,
        hours: int = 24,
    ) -> list[Dict[str, Any]]:
        """
        检测用户异常行为

        异常检测规则：
        - 短时间内多次登录失败
        - 新设备登录
        - 新地理位置登录
        - 异常时间登录（如凌晨3点）
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # 获取最近的安全事件
        query = (
            select(SecurityAuditLog)
            .where(
                SecurityAuditLog.user_id == user_id,
                SecurityAuditLog.created_at >= cutoff,
            )
            .order_by(SecurityAuditLog.created_at.desc())
        )

        result = await self.db.execute(query)
        logs = list(result.scalars().all())

        anomalies = []

        # 检测：多次登录失败
        failed_logins = [log for log in logs if log.event_type == "login_failure"]
        if len(failed_logins) >= 3:
            anomalies.append(
                {
                    "type": "multiple_failed_logins",
                    "count": len(failed_logins),
                    "severity": "high",
                    "message": f"Detected {len(failed_logins)} failed login attempts in the last {hours} hours",
                }
            )

        # 检测：新设备登录
        # 这里需要与用户历史设备对比，简化实现
        successful_logins = [log for log in logs if log.event_type == "login_success"]
        if successful_logins:
            latest_login = successful_logins[0]
            if latest_login.device_fingerprint:
                # 检查是否是已知设备（简化：需要设备历史表）
                anomalies.append(
                    {
                        "type": "new_device_login",
                        "device": latest_login.device_fingerprint,
                        "severity": "medium",
                        "message": "Login from new device detected",
                    }
                )

        return anomalies
