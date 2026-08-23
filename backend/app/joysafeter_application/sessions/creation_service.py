from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.credentials.snapshot_service import (
    CreateCredentialAwareSession,
    create_session_from_source,
)
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession


class SessionCreationService:
    """Application entry point for credential-aware session creation."""

    def __init__(self, db: AsyncSession, *, audit_actor: CredentialAuditActor) -> None:
        self._application = compose_credential_application(
            db,
            auto_commit=False,
            audit_actor=audit_actor,
        )

    async def create_from_source(self, command: CreateCredentialAwareSession) -> JoySafeterSession:
        return await create_session_from_source(command, self._application.uow)
