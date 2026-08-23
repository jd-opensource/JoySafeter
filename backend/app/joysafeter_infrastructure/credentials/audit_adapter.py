from __future__ import annotations

from app.joysafeter_application.credentials.ports import CredentialAuditActor, CredentialAuditEntry
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog


class SqlAlchemyCredentialAuditAdapter:
    def __init__(self, db: object, *, actor: CredentialAuditActor) -> None:
        self._db = db
        self._actor = actor

    async def append(self, entry: CredentialAuditEntry) -> None:
        details = {
            **dict(entry.details),
            "project_id": entry.project_id,
            "target_type": entry.target_type,
            "principal_type": self._actor.principal_type,
            "principal_id": self._actor.principal_id,
        }
        if self._actor.org_id is not None:
            details["org_id"] = self._actor.org_id
        if self._actor.role is not None:
            details["role"] = self._actor.role
        if entry.target_id is not None:
            details["target_id"] = entry.target_id
        self._db.add(
            SecurityAuditLog(
                user_id=self._actor.user_id,
                event_type=entry.action,
                event_status="success",
                ip_address=self._actor.ip_address,
                user_agent=self._actor.user_agent,
                details=details,
            )
        )
