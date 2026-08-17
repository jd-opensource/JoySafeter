from __future__ import annotations

from app.joysafeter_application.credentials.ports import CredentialAuditEntry
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog


class SqlAlchemyCredentialAuditAdapter:
    def __init__(self, db: object) -> None:
        self._db = db

    async def append(self, entry: CredentialAuditEntry) -> None:
        details = {
            "project_id": entry.project_id,
            "target_type": "credential",
            **dict(entry.details),
        }
        if entry.target_id is not None:
            details["target_id"] = entry.target_id
        self._db.add(
            SecurityAuditLog(
                event_type=entry.action,
                event_status="success",
                ip_address="application",
                details=details,
            )
        )


class NullCredentialAuditAdapter:
    async def append(self, entry: CredentialAuditEntry) -> None:
        return None
