from __future__ import annotations

from app.joysafeter_shared.security.credential_cipher import CredentialCipher


class LegacyV1MaterialProtector:
    def __init__(self, key: str | None) -> None:
        self._cipher = CredentialCipher(key)

    def require_enabled(self) -> None:
        self._cipher.require_enabled()

    def protect(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("material value must be a string")
        return self._cipher.encrypt(value)

    def reveal(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("stored material value must be a string")
        return self._cipher.decrypt_stored(value)
