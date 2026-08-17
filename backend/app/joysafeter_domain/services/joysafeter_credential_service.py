"""Compatibility facade for the Credential Application services.

Existing consumers keep importing ``CredentialService`` until their later
migration tasks. Persistence, material protection, transaction, and impact
work is delegated through the Application composition boundary.
"""

from __future__ import annotations

from typing import Any

from app.joysafeter_application.credentials.composition import compose_credential_application


class CredentialService:
    def __init__(self, db: Any, *, auto_commit: bool = True) -> None:
        application = compose_credential_application(
            db,
            auto_commit=auto_commit,
            compatibility_mode=True,
        )
        self._application = application
        self._service = application.resource_service

    def __getattr__(self, name: str) -> Any:
        service = self.__dict__.get("_service")
        if service is None:
            raise AttributeError(name)
        return getattr(service, name)
