from __future__ import annotations

from app.joysafeter_infrastructure.sensitive_material.versioned import VersionedMaterialProtector
from app.joysafeter_shared.security.credential_cipher import CredentialCipherConfigurationError


class TaskIdentityMaterialConfigurationError(ValueError):
    pass


class TaskIdentityMaterialAdapter:
    def __init__(self, protector: VersionedMaterialProtector) -> None:
        self._protector = protector

    def require_enabled(self) -> None:
        try:
            self._protector.require_enabled()
        except CredentialCipherConfigurationError as exc:
            raise TaskIdentityMaterialConfigurationError(str(exc)) from exc

    def protect_identity_credential(self, value: str) -> str:
        if not value:
            raise ValueError("identity credential must be non-empty")
        try:
            return self._protector.protect(value)
        except CredentialCipherConfigurationError as exc:
            raise TaskIdentityMaterialConfigurationError(str(exc)) from exc

    def reveal_identity_credential(self, value: str) -> str:
        return self._protector.reveal(value)
